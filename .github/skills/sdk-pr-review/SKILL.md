---
name: sdk-pr-review
description: 'Review Azure Python management SDK pull requests against the azure-sdk-for-python MGMT SDK Code Review Rules and local checks such as API-version drift. Use when asked to review, inspect, or validate a PR that changes packages under sdk/*/azure-mgmt-*.'
argument-hint: 'PR URL or number, or a local branch/diff to review'
---

# Management SDK PR Review

Review a pull request that changes Azure Python management-plane SDK packages and report concrete, actionable findings.

## Authoritative Rules

Follow the current [MGMT SDK Code Review Rules](https://github.com/Azure/azure-sdk-for-python/blob/main/.github/copilot-instructions.md#mgmt-sdk-code-review-rules) in `Azure/azure-sdk-for-python`.

At the start of each review, read the linked section from `main` and apply every rule in it. Do not rely on a cached or reproduced copy of those rules. The linked section is the single source of truth, including any rules added after this skill was written.

## Inputs

Accept one of:

- A pull request URL or number.
- The active pull request in the editor.
- A local branch or diff when no pull request exists.

If the target is ambiguous and cannot be inferred from the current repository or editor, ask for the pull request URL or number.

## Review Boundaries

1. Identify changed packages matching `sdk/*/azure-mgmt-*/`.
2. Review each affected package independently.
3. Apply the scope and exclusions defined in the authoritative rules.
4. Base findings on the pull request diff and repository state. Do not report unrelated pre-existing problems unless they are necessary to explain a regression introduced by the pull request.
5. Do not modify files, submit reviews, or post comments unless the user explicitly requests it.

## Workflow

Use this checklist and update it while reviewing:

```text
Management SDK PR review
- [ ] Read the current upstream MGMT SDK Code Review Rules
- [ ] Identify affected azure-mgmt packages and changed files
- [ ] Apply every upstream rule and exclusion
- [ ] Compare _metadata.json apiVersion before and after the PR
- [ ] Report findings and unverified checks
```

### 1. Collect Evidence

For each affected package, inspect the pull request diff plus the package files needed to evaluate the rules. Record the base and head revisions so findings can be attributed to the pull request.

### 2. Apply the Rules

Execute the authoritative rules directly. Use their current headings as the review checklist so no rule is silently omitted. Gather only the evidence required by those rules, and cite the authoritative rule heading for each finding.

### 3. Check API-Version Drift

For each affected package:

1. Find the earliest commit belonging to the pull request.
2. Use the first parent of that commit as the original revision immediately before the pull request.
3. Parse the package's `_metadata.json` at the original revision and read its `apiVersion` value.
4. Parse the same file at the latest pull request commit and read its `apiVersion` value.
5. Compare the parsed values exactly. Do not compare raw JSON text.
6. If the values differ, report a `Blocking` finding titled `API version changed` with the package path, original revision and value, latest revision and value, and a request to restore the original API version or explain and obtain approval for the change.

If `_metadata.json` or `apiVersion` does not exist at either revision, do not guess a value. List the check as unverified with the missing revision, file, or field. This rule applies even when `_metadata.json` is not included in the pull request diff.

### 4. Handle Missing Evidence

Do not guess. When a required file or value is absent, determine whether its absence is itself a rule violation. Otherwise, list the check as unverified and state exactly what evidence is missing.

## Output Format

Lead with findings ordered by severity. Each finding must include:

- Severity: `Blocking`, `Warning`, or `Suggestion`.
- A concise title.
- A file and line reference when available.
- The observed evidence.
- The violated rule and a specific remediation.

Then include:

1. **Unverified checks**: checks that could not be completed and why.
2. **Review summary**: affected packages and the checks completed.

Do not include a finding for a passing check. If there are no findings, say so clearly and mention any unverified checks or residual risk.
