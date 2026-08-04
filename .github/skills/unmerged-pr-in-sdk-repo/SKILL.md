---
name: unmerged-pr-in-sdk-repo
description: Use when the user wants to detect unmerged AutoPR SDK pull requests (title starts with "[AutoPR azure-mgmt-") whose SDK version is not 1.0.0b1, and produce a markdown summary of id, PR link, sdk name, created time, approval state, whether new commits were added after approval, and release plan.
---

# Unmerged PR in SDK Repo

Detect open (unmerged) SDK pull requests in the SDK repo that meet the selection
criteria, then output a markdown summary.

## Selection Criteria

A PR is reported only when **all** hold:

1. Its title starts with `[AutoPR azure-mgmt-`.
2. It is **open** (not merged, not closed).
3. Its SDK version is **not** `1.0.0b1`.

## Output

A markdown table with these columns:

```
id | PR link | sdk name | sdk version | PR created time (2026-XX-XX) | PR approved time (2026-XX-XX) | new commit after approval | release plan
```

`id` is a 1-based row number in the final table.
`PR approved time` is `-` when the reviewer has not approved the PR.
`new commit after approval` is `Yes` when the PR has at least one commit whose committed time is later than the latest approval by the reviewer; it is `No` when approved with no newer commit, and `-` when not approved.
`release plan` is extracted from the PR description. The script recognizes the first HTTP link after a `Release plan: ...` / `Release plan link: ...` label or inside a `## Release plan` markdown section; if no release-plan link exists, it reports `unknown`.
When a table cell is an HTTP link, the script renders it as `[number]({url})` when the URL has a `releaseplan=<number>` / `releasePlan=<number>` query value or ends with a number, or `[...]({url})` otherwise, to keep the displayed table compact.

Rows are sorted by PR created time (newest first).

## Prerequisites

- **GitHub CLI (`gh`)** installed and authenticated with read access to the SDK repo.
- **Python 3** available on `PATH`.

## Inputs

- **repo** (optional): SDK repo. Default `Azure/azure-sdk-for-python`.
- **reviewer** (optional): approver login. Default `msyyc`.
- **exclude-version** (optional): version to filter out. Default `1.0.0b1`.

## Workflow

The steps are stable and fully automated by the bundled Python script — run it directly.

```powershell
$env:PYTHONIOENCODING = 'utf-8'
python <skill-dir>/scripts/detect_unmerged_pr.py
```

Optional overrides:

```powershell
python <skill-dir>/scripts/detect_unmerged_pr.py `
  --repo Azure/azure-sdk-for-python `
  --reviewer msyyc `
  --exclude-version 1.0.0b1 `
  --limit 500
```

### What the script does

1. Lists open AutoPR PRs via
   `gh pr list --repo <repo> --search "AutoPR azure-mgmt in:title" --state open --json number,title,url,createdAt`,
   then keeps only titles starting with `[AutoPR azure-mgmt-`.
2. Parses the sdk name from the title (e.g. `[AutoPR azure-mgmt-search]-generated-from...` -> `azure-mgmt-search`).
3. For each PR, reads reviews, commits, and description in one call via
  `gh pr view <n> --json reviews,commits,body`; if the PR has an `APPROVED` review by the reviewer, the latest such review's `submittedAt` is the approved time. Otherwise, the approved time is `-`.
4. Determines the SDK version from the PR diff via `gh api repos/<repo>/pulls/<n>/files`:
   - Primary: the added `VERSION = "..."` line in the package `_version.py`.
   - Fallback: the latest `##` version heading added in `CHANGELOG.md`.
5. Drops PRs whose version equals the excluded version (`1.0.0b1`).
6. Uses the already-fetched PR commits to report whether any commit was committed after the latest approval by the reviewer.
7. Uses the already-fetched PR description to extract the release plan.
8. Prints progress to stderr and the final markdown table to stdout.

**Report to user:** the markdown table printed on stdout.

## Notes

- Diagnostic lines are written to **stderr** (prefixed with `#`); the clean markdown
  table is written to **stdout** — redirect stdout if you need the table alone.
- The script uses only the GitHub CLI (`gh`); no other network access is required.

## Failure Handling

- If `gh` is not authenticated, the script raises a `RuntimeError` with the `gh` stderr —
  run `gh auth login` and retry.
- If a PR listing returns nothing, the table has only its header — report that no PRs matched.
- `gh pr list --limit` caps how many PRs are inspected; raise `--limit` if some expected PRs
  are missing from a very large backlog.
