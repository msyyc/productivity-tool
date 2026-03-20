# Breaking Changes Classification Guide

Full guide: https://github.com/Azure/azure-sdk-for-python/blob/main/doc/dev/mgmt/sdk-breaking-changes-guide.md

Read the guide above to understand how to classify and resolve each breaking change during TypeSpec migration. It may also exist locally in your `azure-sdk-for-python` clone at `doc/dev/mgmt/sdk-breaking-changes-guide.md`.

**Fallback:** If the local file is unavailable, fetch the guide from the GitHub URL above using `gh api` or `web_fetch`. The guide contains the Action Matrix for classifying each breaking change as ACCEPT (no code change needed) or MITIGATE (requires `@@clientName` or `@@override` decorators in TypeSpec).
