---
name: unmerged-pr-in-sdk-repo
description: Use when the user wants to detect unmerged AutoPR SDK pull requests (title starts with "[AutoPR azure-mgmt-") that were approved by msyyc and whose SDK version is not 1.0.0b1, and produce a markdown summary of PR link, sdk name, created time, and approved time.
---

# Unmerged PR in SDK Repo

Detect open (unmerged) SDK pull requests in the SDK repo that meet **all** of these
conditions, then output a markdown summary.

## Selection Criteria

A PR is reported only when **all** hold:

1. Its title starts with `[AutoPR azure-mgmt-`.
2. It is **open** (not merged, not closed).
3. It has been **APPROVED** by `msyyc`.
4. Its SDK version is **not** `1.0.0b1`.

## Output

A markdown table with these columns:

```
PR link | sdk name | sdk version | PR created time (2026-XX-XX) | PR approved time (2026-XX-XX)
```

Rows are sorted by approval time (most recent first).

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
3. For each PR, reads reviews via `gh pr view <n> --json reviews` and keeps only PRs with an
   `APPROVED` review by the reviewer; the latest such review's `submittedAt` is the approved time.
4. Determines the SDK version from the PR diff via `gh api repos/<repo>/pulls/<n>/files`:
   - Primary: the added `VERSION = "..."` line in the package `_version.py`.
   - Fallback: the latest `##` version heading added in `CHANGELOG.md`.
5. Drops PRs whose version equals the excluded version (`1.0.0b1`).
6. Prints progress to stderr and the final markdown table to stdout.

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
