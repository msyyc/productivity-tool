---
name: release-python-sdk
description: Use when the user wants to release a Python SDK package by triggering its ADO release pipeline, monitoring the build, and auto-approving release stages. User provides a package name like "azure-mgmt-frontdoor".
---

# Release Python SDK

Trigger the Azure DevOps release pipeline for a Python SDK package, monitor the build, and automatically approve all release stages.

## Prerequisites

- **Azure CLI** authenticated (`az login`)
- `azure-sdk-for-python` repo cloned at `C:/dev/azure-sdk-for-python`
- `productivity-tool` repo at `C:/dev/productivity-tool`

## Input

- **SDK package name** (required): e.g., `azure-mgmt-frontdoor`

## Workflow

### Step 0: Check Prerequisites

Verify the Azure CLI is installed and authenticated before proceeding:

```
az account show --query "{name:name, user:user.name}" -o json
```

- If the command **fails with "not recognized"** or **file not found**: tell the user to install Azure CLI from https://learn.microsoft.com/cli/azure/install-azure-cli then run `az login`.
- If it **returns an error about login**: tell the user to run `az login` to authenticate.
- If it **succeeds**: print the account name and continue to Step 1.

**Do NOT proceed to subsequent steps until this check passes.**

### Step 1: Find Service Name

Run the bundled script to resolve the package name to its service folder:

```
python <skill-dir>/scripts/find_service_name.py <package-name>
```

**Parse the `=== SESSION_STATE ===` block** to extract:
- `service_name` — the service folder name (e.g., `network`)
- `package_name` — the SDK package name

**Store to SQL session state:**

```sql
CREATE TABLE IF NOT EXISTS session_state (key TEXT PRIMARY KEY, value TEXT);
INSERT OR REPLACE INTO session_state (key, value) VALUES
  ('package_name', '<package-name>'),
  ('service_name', '<parsed service_name>');
```

### Step 2: Find Pipeline Definition

Use the Azure DevOps REST API to look up the pipeline definition by name `python - <service_name>`:

```
az devops invoke --area build --resource definitions --route-parameters project=internal --org https://dev.azure.com/azure-sdk --api-version=7.0 --query-parameters "name=python - <service_name>" --query "value[0].{id:id, name:name}" -o json
```

Extract the pipeline `id` from the JSON output.

If no pipeline is found, report an error — the service name may not have a matching release pipeline.

**Update session state:**

```sql
INSERT OR REPLACE INTO session_state (key, value) VALUES
  ('pipeline_id', '<parsed id>'),
  ('pipeline_name', 'python - <service_name>');
```

### Step 3: Trigger Pipeline

Get an Azure DevOps access token and trigger the pipeline via REST API:

```python
import json, subprocess
from urllib.request import Request, urlopen

# Get token
token = subprocess.run(
    "az account get-access-token --resource 499b84ac-1321-427f-aa17-267ca6975798 --query accessToken -o tsv",
    shell=True, capture_output=True, text=True
).stdout.strip()

# Trigger build
url = "https://dev.azure.com/azure-sdk/internal/_apis/build/builds?api-version=7.0"
body = json.dumps({
    "definition": {"id": <pipeline_id>},
    "sourceBranch": "refs/heads/main",
    "parameters": json.dumps({
        "BuildTargetingString": "<package_name>",
        "Skip.CreateApiReview": "true"
    })
})

req = Request(url, method="POST", data=body.encode())
req.add_header("Authorization", f"Bearer {token}")
req.add_header("Content-Type", "application/json")
with urlopen(req) as resp:
    result = json.loads(resp.read())
    build_id = result["id"]
    build_url = f"https://dev.azure.com/azure-sdk/internal/_build/results?buildId={build_id}&view=results"
```

Run this as an inline Python snippet (not a script file). Extract `build_id` and `build_url` from the response.

**Print the build link** so the user can monitor it in the browser:
```
Pipeline triggered: <pipeline_name>
Build ID: <build_id>
Build URL: <build_url>
```

**Update session state:**

```sql
INSERT OR REPLACE INTO session_state (key, value) VALUES
  ('build_id', '<build_id>'),
  ('build_url', '<build_url>');
```

### Step 4: Monitor and Approve

Run the build monitor & approver script:

```
python <skill-dir>/scripts/ado_build_approve.py "<build_url>" --target <package_name>
```

This script will:
1. Poll the build timeline until all non-release stages (Build, Integration, SDLSources) complete
2. Find all pending release stage approvals
3. Automatically approve them all
4. Poll PyPI until the new version appears (up to 10 minutes)
5. Exit with code 1 if any build stage fails

**Important:** This step may take several minutes. The script prints live progress. Let it run to completion — do NOT interrupt it.

After the script completes successfully, **parse the `=== RELEASE SUMMARY ===` block** from its output. Report the result to the user:

- If PyPI verification succeeded:
```
✅ Released <package_name> <version> successfully!
Pipeline: <pipeline_name>
Build: <build_url>
PyPI: https://pypi.org/project/<package_name>/<version>/
```

- If PyPI verification timed out:
```
✅ Released <package_name> (approval done)
Pipeline: <pipeline_name>
Build: <build_url>
⚠️ Could not confirm new version on PyPI yet. Check manually: https://pypi.org/project/<package_name>/
```

## Rules

- Always use `az` CLI for Azure DevOps authentication (never ask for PAT tokens)
- The pipeline naming convention is `python - <service_name>` (e.g., `python - network`, `python - compute`)
- The `parameters` field in the ADO trigger API must be a **JSON-encoded string**, not an object
- ADO org is always `https://dev.azure.com/azure-sdk`, project is always `internal`
- If `ado_build_approve.py` exits with code 1 (build failure), report the failure and suggest the user check the build URL
- If `ado_build_approve.py` exits with code 2 (configuration error, e.g. wrong --target), report the error and suggest the user verify the package name
- Use forward slashes in all file paths passed to scripts
