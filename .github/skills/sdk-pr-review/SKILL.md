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
- [ ] Compare _metadata.json apiVersion at the first and latest PR revisions
- [ ] Report findings and unverified checks
```

### 1. Collect Evidence

For each affected package, inspect the pull request diff plus the package files needed to evaluate the rules. Record the base and head revisions so findings can be attributed to the pull request.

### 2. Apply the Rules

Execute the authoritative rules directly. Use their current headings as the review checklist so no rule is silently omitted. Gather only the evidence required by those rules, and cite the authoritative rule heading for each finding.

### 3. Check API-Version Drift

Run the deterministic checker with every affected package path, even when `_metadata.json` is not included in the pull request diff:

```powershell
python .github/skills/sdk-pr-review/scripts/check_api_version_drift.py <pr-url-or-number> <package-path> [<package-path> ...]
```

The script gets the ordered commit list from pull request metadata and compares the parsed `apiVersion` at the first and latest commits belonging to the pull request. It does not substitute a first parent, pull request base, or merge base. Its Markdown table contains the package, status, first and latest revisions, both API versions, and any error.

Interpret each table row and the process exit code as follows:

- Exit `0`, status `unchanged`: the check passed; do not report a finding.
- Exit `1`, status `changed`: report a `Blocking` finding titled `API version changed` with the package, first revision and API version, latest revision and API version, and a request to restore the original API version or explain and obtain approval for the change.
- Exit `2`, status `unverified`: list the check as unverified using the table's `Error` value. Do not guess a revision or API version.

When multiple packages are checked, interpret each result independently. A process exit code of `1` means at least one package changed; exit `2` means no package changed but at least one package could not be verified.

### 4. Handle Missing Evidence

Do not guess. When a required file or value is absent, determine whether its absence is itself a rule violation. Otherwise, list the check as unverified and state exactly what evidence is missing.

## Output Format

Lead with findings ordered by severity in a Markdown table:

| Severity | Finding | Location | Evidence | Rule | Remediation |
| --- | --- | --- | --- | --- | --- |
| `Blocking`, `Warning`, or `Suggestion` | Concise title | File and line when available | Observed evidence | Violated rule | Specific remediation |

Keep one finding per row and preserve full revision and API-version values. Use `None` instead of a findings table when there are no findings.

Then include unverified checks in a separate table:

| Check | Reason |
| --- | --- |
| Check that could not be completed | Exact missing evidence or error |

Use `None` when every check was verified. Finish with a brief **Review summary** naming the affected packages and checks completed.

Do not include a finding for a passing check. If there are no findings, say so clearly and mention any unverified checks or residual risk.
