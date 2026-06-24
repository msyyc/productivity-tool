---
name: reserve-pypi-package-name
description: Use when the user wants to register/reserve a new Python SDK package name on PyPI by triggering the Azure DevOps "python - reserve-package-name" pipeline (definitionId 8013). User provides a package name like "azure-mgmt-xxx".
---

# Reserve PyPI Package Name

Reserve (register) a new Python SDK package name on PyPI by triggering the Azure DevOps
pipeline **`python - reserve-package-name`** (definitionId `8013`, org `azure-sdk`, project `internal`).
The pipeline builds a minimal placeholder distribution and publishes it to PyPI so the name is
claimed for future use.

Pipeline reference: https://dev.azure.com/azure-sdk/internal/_build?definitionId=8013

## Prerequisites

- **Azure CLI** authenticated (`az login`) with access to the `azure-sdk` DevOps org.

## Input

- **Package name** (required): the PyPI distribution name to reserve, e.g. `azure-mgmt-examplnew`.
  Must use hyphens (`-`), not underscores.
- **Version** (optional): the placeholder version to publish. Defaults to `0.0.0`. Ask the user
  only if they hint they want a non-default value.

If the package name is missing, ask the user before continuing.

## Workflow

### Step 0: Check Prerequisites

Verify the Azure CLI is installed and authenticated:

```
az account show --query "{name:name, user:user.name}" -o json
```

- If the command **fails with "not recognized"** or **file not found**: tell the user to install
  Azure CLI from https://learn.microsoft.com/cli/azure/install-azure-cli then run `az login`.
- If it **returns an error about login**: tell the user to run `az login` to authenticate.
- If it **succeeds**: print the account name and continue.

**Do NOT proceed until this check passes.**

### Step 1: Confirm the Name Is Not Already Taken

Check whether the package name already exists on PyPI:

```
python -c "import urllib.request,sys; n='<package-name>'; \
print('TAKEN' if urllib.request.urlopen(urllib.request.Request('https://pypi.org/pypi/'+n+'/json', method='GET'), timeout=20).status==200 else 'OK')" 2>$null
```

- If it prints `TAKEN` (HTTP 200): the name is already reserved/published. Report this to the user
  with the link `https://pypi.org/project/<package-name>/` and **stop** — do not trigger the pipeline.
- If it raises an `HTTPError 404` (name not found): the name is free. Continue.

### Step 2: Trigger the Pipeline

Get an Azure DevOps access token and queue the build via the REST API, passing the package name and
version as **template parameters** (`NameForReservation`, `VersionForReservation`).

Run this as an inline Python snippet (substitute `<package-name>` and `<version>`; version defaults
to `0.0.0`):

```python
import json, subprocess
from urllib.request import Request, urlopen

PACKAGE_NAME = "<package-name>"
VERSION = "<version>"  # default "0.0.0"

# Get an Azure DevOps access token
token = subprocess.run(
    "az account get-access-token --resource 499b84ac-1321-427f-aa17-267ca6975798 --query accessToken -o tsv",
    shell=True, capture_output=True, text=True
).stdout.strip()

# Queue the build. Template parameters go in "templateParameters" (a JSON object, NOT a string).
url = "https://dev.azure.com/azure-sdk/internal/_apis/build/builds?api-version=7.0"
body = json.dumps({
    "definition": {"id": 8013},
    "sourceBranch": "refs/heads/main",
    "templateParameters": {
        "NameForReservation": PACKAGE_NAME,
        "VersionForReservation": VERSION,
    },
})

req = Request(url, method="POST", data=body.encode())
req.add_header("Authorization", f"Bearer {token}")
req.add_header("Content-Type", "application/json")
with urlopen(req) as resp:
    result = json.loads(resp.read())
    build_id = result["id"]
    build_url = f"https://dev.azure.com/azure-sdk/internal/_build/results?buildId={build_id}&view=results"
    print(f"build_id={build_id}")
    print(f"build_url={build_url}")
```

**Print the build link** so the user can monitor it:
```
Pipeline triggered: python - reserve-package-name
Reserving: <package-name>==<version>
Build ID: <build_id>
Build URL: <build_url>
```

### Step 3: Monitor and Verify

Poll the build status until it finishes, then confirm the name appears on PyPI.

Inline Python snippet (substitute `<build_id>` and `<package-name>`):

```python
import json, time, subprocess
from urllib.request import Request, urlopen
from urllib.error import HTTPError

BUILD_ID = <build_id>
PACKAGE_NAME = "<package-name>"

token = subprocess.run(
    "az account get-access-token --resource 499b84ac-1321-427f-aa17-267ca6975798 --query accessToken -o tsv",
    shell=True, capture_output=True, text=True
).stdout.strip()

status_url = f"https://dev.azure.com/azure-sdk/internal/_apis/build/builds/{BUILD_ID}?api-version=7.0"
deadline = time.time() + 20 * 60  # up to 20 minutes
result = None
while time.time() < deadline:
    req = Request(status_url)
    req.add_header("Authorization", f"Bearer {token}")
    with urlopen(req) as resp:
        b = json.loads(resp.read())
    if b.get("status") == "completed":
        result = b.get("result")
        print(f"Build completed: {result}")
        break
    print(f"Build status: {b.get('status')}...")
    time.sleep(30)

# Verify on PyPI (poll a few minutes for propagation)
found = False
for _ in range(20):
    try:
        with urlopen(Request(f"https://pypi.org/pypi/{PACKAGE_NAME}/json"), timeout=20) as r:
            if r.status == 200:
                found = True
                break
    except HTTPError as e:
        if e.code != 404:
            raise
    time.sleep(30)
print(f"pypi_found={found}")
```

**Important:** This step may take several minutes. Let it run to completion — do NOT interrupt it.

### Step 4: Report Result

The reservation is only considered successful when the name is confirmed registered on PyPI
(`pypi_found=True`). Use `pypi_found` from Step 3 as the source of truth.

- If the build result is `succeeded` **and** `pypi_found=True`:
```
✅ Reserved <package-name> <version> on PyPI successfully!
Pipeline: python - reserve-package-name
Build: <build_url>
PyPI: https://pypi.org/project/<package-name>/
```

- If the build result is `succeeded` **but** `pypi_found=False` (name NOT registered on PyPI):
  Show an **error** — the reservation did not take effect.
```
❌ ERROR: <package-name> is NOT registered on PyPI after the pipeline completed.
Pipeline: python - reserve-package-name
Build: <build_url>
The build reported success but the package name could not be found at
https://pypi.org/project/<package-name>/. This may be a publish/propagation delay or a
silent publish failure. Re-check the link in a few minutes; if it is still missing, inspect
the build logs and re-run the reservation.
```
  After reporting the error, **stop**.

- If the build failed:
```
❌ Reservation failed for <package-name>
Build: <build_url>
```
  Report the failure and the build URL, then **stop**.

## Rules

- Always use `az` CLI for Azure DevOps authentication (never ask for PAT tokens).
- ADO org is always `https://dev.azure.com/azure-sdk`, project is always `internal`, definitionId is `8013`.
- Template parameters (`NameForReservation`, `VersionForReservation`) must be passed in the
  `templateParameters` field (a JSON object), **not** in `parameters`.
- Package names use hyphens (`-`); if the user provides underscores, convert them to hyphens for PyPI.
- The default version is `0.0.0`. Only change it if the user explicitly asks.
- If the name is already taken on PyPI, do NOT trigger the pipeline — report and stop.
- After the pipeline completes, the reservation is only successful if the name is confirmed
  registered on PyPI. If the name is NOT found on PyPI, show an error (do not claim success).
- When the pipeline fails, report the build URL and stop. Do NOT take deeper remediation actions.
- Always include the PyPI link (`https://pypi.org/project/<package-name>/`) in the final output.
