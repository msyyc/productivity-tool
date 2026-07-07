---
name: verify-python-package-name
description: 'Use when reviewing an automated Python SDK pull request and you need to verify whether the Python package/namespace name was approved through a "Board Review: Management Plane Namespace Review" issue. Triggers on requests to verify a Python package/namespace, check namespace review status, or review an automated Python SDK PR.'
---

# Verify Python Package Name

Verify whether the Python package (and its derived namespace) introduced by an automated SDK
pull request has been approved through the **"Board Review: Management Plane Namespace Review"**
process, then comment the result back on the PR.

## Workflow

Copy this checklist and update it as work progresses:

```text
Automated PR review progress
- [ ] Check existing comments on Python package name
- [ ] Search "Board Review: Management Plane Namespace Review" issues in https://github.com/Azure/azure-sdk-pr/issues and https://github.com/Azure/azure-sdk/issues
- [ ] Find the Python package and namespace from review issues
- [ ] When find matching review issue, also confirm that the issue was closed
```

## Default process

1. If there is already a comment in the PR in the form of `namespace review <url>`, skip the rest
   of this process. The package name has already been reviewed.
2. The new package lives at `sdk/<service>/<package-name>/`. Remember the `<service>` and
   `<package-name>`. You are going to verify whether this `<package-name>` is approved.
3. Search https://github.com/Azure/azure-sdk-pr/issues and https://github.com/Azure/azure-sdk/issues
   for GitHub issues that contain `Board Review: Management Plane Namespace Review` and `<service>`
   in the title.
4. For all such GitHub issues, read the issue description and search for an exact match of
   `<package-name> <namespace>`. The `<namespace>` would be `<package-name>` with all `-` replaced
   by `.` (e.g. `azure-mgmt-example` -> `azure.mgmt.example`).
5. If the matching review issue is found but is still open, comment
   `namespace review not completed <url-to-review-issue>` and skip the rest of this process.
6. If no such review issue is found, log it and skip the rest of this process.
7. When the matching review issue is found, verify that the issue was closed. This signifies that
   the review was completed.
8. Comment `namespace review completed <url-to-review-issue>` in the PR.
9. Comment `/azp run prepare-pipelines` in the PR.
