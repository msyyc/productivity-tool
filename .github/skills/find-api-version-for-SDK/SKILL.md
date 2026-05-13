---
name: find-api-version-for-SDK
description: Use when the user wants to find the api-version(s) used by a specific Python Azure SDK package version (e.g., azure-mgmt-compute 1.0.0b1, latest stable, latest preview), and locate its readme.python.md in the spec repo. Triggers on phrases like "find api-version for SDK", "what api-version does <package> use", "api version of <package>".
---

# Find API Version for SDK

Quickly resolve the api-version(s) baked into a specific Python Azure SDK release, and surface where to open the source code and the corresponding spec folder.

## Input

- **SDK package name** (required): e.g., `azure-mgmt-compute`
- **Version** (required): one of
  - explicit version: `1.0.0b1`, `30.0.0`, etc.
  - `latest` or `latest-stable` — latest stable release on PyPI
  - `latest-preview` or `preview` — latest pre-release on PyPI

If either is missing, ask the user for it.

## Workflow

Run the bundled script — it does everything in one process for speed:

```
python <skill-dir>/scripts/find_api_version.py <package-name> <version>
```

The script will:
1. Resolve `latest` / `latest-preview` against PyPI if needed.
2. `pip download` that exact version into `temp/<package>-<version>/download`.
3. Extract the sdist/wheel into `temp/<package>-<version>/extracted`.
4. Scan `_configuration.py` and `*_client.py` for api-version literals like `2021-02-01`.
5. Search every `readme.python.md` under `C:/dev/azure-rest-api-specs/specification` for the package name.
6. Print a `=== SUMMARY ===` block with `api_versions`, `source_dir`, `readme_paths`, `readme_urls`.

Parse that block and report to the user in this exact format:

```
Package: <package> <resolved-version>

API version(s): <comma-separated list>     # or: "Could not find api-version in the package"

Open source code:
code <source_dir>

Spec folder(s):
<readme_url_1>
<readme_url_2>
...
```

Notes for the report:
- If `api_versions: NOT_FOUND`, print **"Could not find api-version in the package"** for that line.
- The `code <path>` line is intentionally a copy-paste-ready command for the user to open the extracted SDK source in VS Code.
- Each `readme_url` is the GitHub folder URL with `readme.python.md` stripped, so the user lands on the folder.
- If `readme_paths: NOT_FOUND`, print **"No matching readme.python.md found in the spec repo"** under "Spec folder(s):".

## Rules

- Always run the bundled script — do not manually pip-download / extract / grep step by step. Speed matters.
- Pass the version exactly as the user typed it, except map natural-language synonyms to the script's keywords:
  - "latest", "latest stable", "newest stable" → `latest`
  - "latest preview", "newest preview", "latest beta" → `latest-preview`
- If the user gives an explicit version that doesn't exist on PyPI, the script will fail; surface the pip error to the user and stop.
- Spec repo location is hard-coded to `C:/dev/azure-rest-api-specs`. If that path doesn't exist, the script logs a warning and skips the readme search; report "spec repo not found locally" to the user.
- If multiple `readme.python.md` files match, list them **all** (paths and URLs), in the order returned.
- Do not delete the `temp/` folder afterwards — the user may want to browse it via the printed `code` command.
