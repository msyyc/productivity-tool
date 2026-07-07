---
name: add-approval-label-for-spec-pr
description: Use when adding approval, suppression approval, PublishToCustomers, or ARMSignedOff labels to an Azure REST API specs pull request.
---

# Add Approval Labels for Spec PR

Add the required approval labels to an Azure REST API specs pull request based on its existing breaking-change labels.

## Prerequisites

- GitHub CLI (`gh`) must be installed and authenticated.
- The target PR is usually in `Azure/azure-rest-api-specs` unless the user gives a different repo.

## Inputs

- Spec PR URL or PR number.
- Optional repo owner/name if the PR is not in `Azure/azure-rest-api-specs`.

## Label Rules

Always add:

- `PublishToCustomers`
- `ARMSignedOff`

For each existing language breaking label:

| Existing label | Add label |
|---|---|
| `BreakingChange-<Language>-Sdk` | `BreakingChange-<Language>-Sdk-Approved` |
| `BreakingChange-<Language>-Sdk-Suppression` | `BreakingChange-<Language>-Sdk-Suppression-Approval` |

Examples:

- `BreakingChange-Python-Sdk` -> `BreakingChange-Python-Sdk-Approved`
- `BreakingChange-Python-Sdk-Suppression` -> `BreakingChange-Python-Sdk-Suppression-Approval`

Do not infer labels from package names or PR text. Only derive language-specific approval labels from labels already present on the PR.

## Workflow

1. Determine the repo and PR number. Default repo: `Azure/azure-rest-api-specs`.
2. Read current labels:

```powershell
gh pr view <pr-number-or-url> --repo Azure/azure-rest-api-specs --json labels
```

3. Build the label set to add:

```powershell
$repo = "Azure/azure-rest-api-specs"
$pr = "<pr-number-or-url>"

$currentLabels = gh pr view $pr --repo $repo --json labels --jq '.labels[].name'
$labelsToAdd = [System.Collections.Generic.List[string]]::new()

$labelsToAdd.Add("PublishToCustomers")
$labelsToAdd.Add("ARMSignedOff")

foreach ($label in $currentLabels) {
    if ($label -match '^BreakingChange-(.+)-Sdk$') {
        $labelsToAdd.Add("$label-Approved")
    }
    elseif ($label -match '^BreakingChange-(.+)-Sdk-Suppression$') {
        $labelsToAdd.Add("$label-Approval")
    }
}

$labelsToAdd = $labelsToAdd | Sort-Object -Unique

foreach ($label in $labelsToAdd) {
    gh pr edit $pr --repo $repo --add-label $label
}
```

4. Verify the labels were added:

```powershell
gh pr view <pr-number-or-url> --repo Azure/azure-rest-api-specs --json labels --jq '.labels[].name'
```

Report the labels added and any expected labels that were already present.

## Failure Handling

- If `gh pr edit` reports that a label does not exist, stop and report the missing label name. Do not create labels unless the user explicitly asks.
- If the PR has no `BreakingChange-<Language>-Sdk` or `BreakingChange-<Language>-Sdk-Suppression` labels, still add `PublishToCustomers` and `ARMSignedOff`.
- If the PR repo cannot be determined from the input, ask for the repo instead of guessing beyond the default.
