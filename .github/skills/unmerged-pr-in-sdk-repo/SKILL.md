---
name: unmerged-pr-in-sdk-repo
description: Find open, non-draft AutoPR management SDK PRs needing a review label, SDK-maintainer approval, re-review after new commits, or a release plan. Exclude version 1.0.0b1 and report only actionable PRs in four fixed, numbered sections.
---

# Unmerged PR in SDK Repo

Report only SDK pull requests that need action. This skill is read-only: it does
not add labels, request reviews, post comments, or change PRs.

## Selection Criteria

Inspect PRs only when all hold:

1. The title starts with `[AutoPR azure-mgmt-`.
2. The PR is open and is not a draft.
3. Its SDK version is not the excluded version (default `1.0.0b1`).

Ignore drafts entirely, including for release-plan checks. Omit PRs that need no
action.

## Output

Output a list, not a table. Keep these section IDs and this order:

### 1. Add `mgmt-review-needed`

List PRs missing this label. Tell the user to add the label manually to trigger
Copilot review.

### 2. SDK maintainer review needed

List PRs without an effective approval from an SDK maintainer configured in the
target repository's base-branch `CODEOWNERS`. Show the applicable maintainer
logins and teams and ask a maintainer to review and approve.

Read CODEOWNERS from GitHub, in GitHub's precedence order: `.github/CODEOWNERS`,
`CODEOWNERS`, then `docs/CODEOWNERS`. Use the last matching rule for each changed
file in the SDK package, not owners of unrelated engineering files. Members of
owner teams count as maintainers. Cache ownership rules and team membership for
the duration of the scan.

Use the latest opinionated review per maintainer: a later `CHANGES_REQUESTED` or
`DISMISSED` review invalidates that maintainer's earlier approval; a subsequent
comment alone does not. Approval by any applicable maintainer is sufficient.
The former single-login `--reviewer` option is replaced by CODEOWNERS resolution.

If ownership or team membership cannot be resolved, put an explicit
ownership-verification warning here; do not claim that approval is missing or
that the PR needs no action.

### 3. SDK maintainer re-review needed

List approved PRs with commits newer than the latest effective SDK-maintainer
approval. Show the approver and approval date and ask for re-review.

Compare commit timestamps with the approval timestamp. Also flag a different
current head from the approved commit, so rebases or commits with older
timestamps cannot hide changes to the reviewed code.

### 4. Release plan needs checking

List PRs where no release-plan link is detected in the description. Ask the SDK
maintainer to inspect the PR description:

- If the release plan is missing, contact the service team to create and link one.
- If the link is already present, update this skill's extraction logic.

Detect links after `Release plan:` or `Release plan link:` labels, including
bold/inline Markdown, inside a `Release plan` heading section, in the value cell
of a `Release plan` / `Release plan link` Markdown table row (including bold
labels in the generated `SDK generation details` table), or URLs with a numeric
`releaseplan` / `releasePlan` query value. Table-row detection does not require
a particular URL host, path, or query format. For example:

```markdown
| **Release plan** | [Release plan #36557](https://example.test/plans/36557) |
```

Do not mistake an unrelated link in another table cell, row, or later section
for a release plan when the release-plan value is empty.

### Formatting

- Omit empty sections without renumbering the remaining section IDs.
- A PR may appear in multiple sections when multiple actions apply.
- Sort each section by full PR creation timestamp, newest first.
- Each entry includes a clickable `owner/repo#number`, SDK name, and version.
- If nothing requires action, print exactly `No PRs need action.`
- Print progress and scan-limit/version warnings to stderr, not in the report.

Example (illustrative):

```markdown
## 1. Add `mgmt-review-needed`

Add this label manually to trigger Copilot review.

- [Azure/azure-sdk-for-python#42](https://github.com/Azure/azure-sdk-for-python/pull/42) - `azure-mgmt-example` `2.0.0`

## 4. Release plan needs checking

Check the PR description. If the release plan is missing, contact the service team to create and link one. If a link is already present, update this skill to recognize it.

- [Azure/azure-sdk-for-python#42](https://github.com/Azure/azure-sdk-for-python/pull/42) - `azure-mgmt-example` `2.0.0` - no release-plan link detected.
```

## Prerequisites

- GitHub CLI (`gh`), authenticated with read access to the SDK repository.
- Read access to CODEOWNERS teams' membership to verify team-member approvals.
- Python 3.10+ on `PATH`.

No local SDK repository clone is needed.

## Inputs

- **repo**: default `Azure/azure-sdk-for-python`.
- **exclude-version**: default `1.0.0b1`.
- **limit**: maximum initial PR listing size; default `500`.

## Workflow

Run the bundled script directly:

```powershell
$env:PYTHONIOENCODING = 'utf-8'
python <skill-dir>\scripts\detect_unmerged_pr.py
```

Optional overrides:

```powershell
python <skill-dir>\scripts\detect_unmerged_pr.py `
  --repo Azure/azure-sdk-for-python `
  --exclude-version 1.0.0b1 `
  --limit 500
```

The script lists open AutoPRs, skips drafts, and fetches PR labels, body, base and
head SHAs, changed files, reviews, and commits through `gh`. REST list endpoints
are paginated. It determines the package version from an added `VERSION` line
in `_version.py`, falling back to an added version heading in `CHANGELOG.md`.
It reads ownership at each PR's base commit and prints the action report.

**Report to user:** the report printed on stdout, plus any relevant diagnostic
warnings. Preserve the fixed section IDs and order.

## Failure Handling

- GitHub command failures raise an error with the original stderr. Resolve the
  reported authentication/access problem before retrying.
- Missing/unreadable CODEOWNERS prevents a reliable scan and raises an error.
- Unreadable team membership is reported as incomplete approval verification in
  section 2, with the original error; it is never treated as an empty team.
- Unknown SDK versions are explicitly warned about and displayed as `unknown`,
  rather than silently excluded.
- A listing that reaches `--limit` prints a warning. Increase the limit before
  treating the report as a complete backlog scan.
