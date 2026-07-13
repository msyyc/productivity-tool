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

# Get an Azure DevOps access token.
# 499b84ac-1321-427f-aa17-267ca6975798 is the well-known PUBLIC Azure DevOps
# resource/application ID (not a secret) used to scope the token to Azure DevOps.
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

# 499b84ac-1321-427f-aa17-267ca6975798 is the well-known PUBLIC Azure DevOps
# resource/application ID (not a secret) used to scope the token to Azure DevOps.
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

  First diagnose the cause (see "Diagnosing a 429 failure"). If it is the PyPI **429
  `Too many new projects created`** throttle, do **not** give up — **retry the reservation, at least
  5 attempts, until it succeeds** (re-run Step 2 + Step 3 for the same name). Space attempts out
  (the throttle is time-based; back-to-back retries just fail again — wait before each retry, and if
  the cap is exhausted this may need a longer/scheduled gap). Stop early as soon as `pypi_found=True`.

  Only if all retries are exhausted, or the failure is **not** a 429, report and stop:
```
❌ Reservation failed for <package-name>
Build: <build_url>
```
  Report the failure and the build URL, then **stop**.

## Reserving Multiple Names (Batch) and the PyPI 429 Throttle

### Why batching needs care

The reserve pipeline publishes through a **shared `azure-sdk` PyPI account**. PyPI enforces a
rate limit on **new project creation** per account (roughly ~20/hour and ~100/day, shared with all
other Azure SDK releases). When exceeded, the ESRP "Publish to ESRP" task fails with:

```
Failed Activity : Package Manager., ErrorCode : 2201.
"429, Too Many Requests ... 429 Too many new projects created"
... terminal state which is - failDoNotRetry
```

The ADO build, signing, upload, and auth all succeed — only the final PyPI publish is rejected. This
is **external throttling, not a pipeline/config bug**. Do NOT debug the pipeline; just retry later.

Key consequences:
- **Never trigger many new reservations at once** — they will nearly all fail with 429.
- **Trigger at most one new-name reservation per run**, spaced out (≈1 hour apart is a good default).
- Because the cap is shared and partly daily, a batch can span **hours or even days**; some names may
  fail several times before landing on an unthrottled window. This is expected — just keep retrying.

### Diagnosing a 429 failure

When a build fails, fetch the timeline, find the `Publish to ESRP` record, and read its log. If the
log contains `429` / `Too many new projects created`, it is the throttle (retry later). Only if the
error is something else should you treat it as a real failure per Step 4.

```python
# timeline: https://dev.azure.com/azure-sdk/internal/_apis/build/builds/<build_id>/timeline?api-version=7.0
# find record where name == "Publish to ESRP" and has a "log" -> GET record["log"]["url"]
# grep the log text for "429" / "Too many new projects created" / "ErrorMessage"
```

### Retry loop for multiple names

When the user asks to reserve several names and wants them all eventually registered (regardless of
how long it takes), run a **scheduled retry loop** (e.g. one tick per hour). Track state in a small
table so it survives across ticks:

```sql
CREATE TABLE IF NOT EXISTS reservations (
  name TEXT PRIMARY KEY,
  registered INTEGER DEFAULT 0,
  last_build_id INTEGER,
  last_result TEXT,
  attempts INTEGER DEFAULT 0
);
-- INSERT OR IGNORE one row per requested name.
```

Each tick:
1. Select rows where `registered = 0` (candidates). Re-check each on PyPI; if now 200, set
   `registered = 1` and drop it.
2. If no candidates remain, report success and **stop the schedule**. Done.
3. Otherwise pick exactly **one** candidate (random is fine) and trigger the pipeline for it (Step 2).
4. Poll the build to completion, then verify the name on PyPI (Step 3). PyPI (`pypi_found`) is the
   source of truth — a build may still show `inProgress` in ADO after the publish has succeeded, so
   treat a 200 on PyPI as success even if the ADO result is not yet `succeeded`.
5. Update the row (`last_build_id`, `last_result`, `attempts += 1`). On PyPI hit set `registered = 1`;
   on 429 failure leave `registered = 0` so it stays a candidate. Do **not** stop the schedule.
6. Only **one** trigger per tick to respect the rate limit; the loop fires again next interval.

Report progress after each tick (e.g. "2 of 4 registered") and stop only when all names are on PyPI.

## Rules

- Always use `az` CLI for Azure DevOps authentication (never ask for PAT tokens).
- For a **single** name, if the reservation fails with the **429 throttle**, retry it — **at least
  5 attempts, spaced out, until it succeeds** (see Step 4). For any **non-429** failure, keep the
  fast-fail behavior (report the build URL and stop). The multi-name retry loop above applies when the
  user asks to reserve several names and wants them all registered over time.
- Never trigger more than one new-name reservation at a time; space batch triggers ~1 hour apart.
- A 429 `Too many new projects created` ESRP failure is external throttling on the shared `azure-sdk`
  PyPI account — retry later, do NOT debug the pipeline or treat it as a config error.
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
