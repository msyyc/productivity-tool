---
name: merge-pr-with-squash-mode
description: Use when the user wants to squash and merge a GitHub pull request with the GitHub CLI, optionally deleting the source branch when it lives in the msyyc fork.
---

# Merge PR with Squash Mode

Squash and merge a GitHub pull request using the GitHub CLI (`gh`). If the PR's source (head) branch is in a repository forked under the `msyyc` account, delete that source branch after the merge succeeds.

## Prerequisites

- GitHub CLI (`gh`) must be installed and authenticated with permission to merge the target PR.

## Inputs

- PR URL or PR number provided by the user.
- Optional repo `owner/name` if the PR is not identified by a full URL.

## Workflow

1. Determine the target repo and PR number from the user-provided PR URL or number. When the user gives a full URL, `gh` accepts it directly.

2. Read the PR's head (source) repository owner and branch to decide whether to delete the branch after merging:

```powershell
$pr = "<pr-number-or-url>"

$headRepoOwner = gh pr view $pr --json headRepositoryOwner --jq '.headRepositoryOwner.login'
$headBranch    = gh pr view $pr --json headRefName --jq '.headRefName'
```

3. Squash and merge the PR. Only pass `--delete-branch` when the head repository owner is `msyyc`, so the fork's source branch is cleaned up automatically:

```powershell
if ($headRepoOwner -eq "msyyc") {
    gh pr merge $pr --squash --delete-branch
} else {
    gh pr merge $pr --squash
}
```

- `--squash` combines all PR commits into a single commit on the base branch.
- `--delete-branch` deletes the head branch after a successful merge. Because the branch is in the `msyyc` fork, this removes the source branch there.

4. Verify the merge succeeded:

```powershell
gh pr view <pr-number-or-url> --json state,mergedAt --jq '{state: .state, mergedAt: .mergedAt}'
```

Report the merge result and, when applicable, that the `msyyc` fork source branch was deleted.

## Failure Handling

- If the PR is not mergeable (conflicts, failing required checks, or missing approvals), `gh pr merge` fails. Report the reason and do not retry blindly.
- If the head repository owner is not `msyyc`, do not delete the source branch — merge only.
- If the PR is already merged or closed, report its current state instead of attempting to merge again.
- If the PR cannot be identified from the input, ask the user for the PR URL or repo and number instead of guessing.
