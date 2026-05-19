---
name: create-sdk-release-pr-from-swagger
description: Use when the user wants to regenerate a Python Azure Mgmt SDK package from swagger (azure-rest-api-specs) and open a PR. The user provides an SDK package name (e.g. `azure-mgmt-xxx`) and a swagger tag (e.g. `package-xxx`).
---

# Create SDK Release PR From Swagger

Regenerate a Python SDK package from the swagger (azure-rest-api-specs) repo using the local `sdk_generator` tool, bump the version, replace the latest changelog section with a fixed regeneration note, and open a PR against `Azure/azure-sdk-for-python`.

## Prerequisites

- Local repos for `azure-rest-api-specs` and `azure-sdk-for-python` (the SDK repo must already have a `.venv` created). The script locates them in the following order:
  1. If `--work-dir <path>` is passed, both repos must live directly under `<path>` (`<path>/azure-rest-api-specs`, `<path>/azure-sdk-for-python`).
  2. Otherwise, if the productivity-tool repo root contains a `.env` file, the script reads `LOCAL_AZURE_SPEC_REPO` and `LOCAL_AZURE_SDK_REPO` from it and uses those full paths.
  3. Otherwise the script defaults to `C:/dev/azure-rest-api-specs` and `C:/dev/azure-sdk-for-python`.
- `gh` CLI authenticated.

## Input

- **SDK package name** (required): e.g. `azure-mgmt-frontdoor`
- **Tag** (required): swagger python tag, e.g. `package-2024-05`
- **Release type** (optional): `stable` or `beta` — written to `sdkReleaseType` in the generator input. Defaults to `stable`. Ask the user if unsure.
- **Spec SHA** (optional): a commit SHA in `azure-rest-api-specs`. If provided, the spec repo is checked out at this SHA instead of `origin/main`.

If either of the required inputs is missing, ask the user before continuing.

## Workflow

A single orchestrator script runs every step end-to-end. Any failure raises and the script exits non-zero — do not retry, just report the failure to the user.

```
python <skill-dir>/scripts/regen_sdk.py <sdk-name> <tag> [--release-type stable|beta] [--sha <spec-sha>] [--work-dir C:/dev]
```

The script performs, in order:

1. **Pre-flight** — resolve the spec/SDK repo paths (`--work-dir`, then `.env` at the productivity-tool root with `LOCAL_AZURE_SPEC_REPO` / `LOCAL_AZURE_SDK_REPO`, then `C:/dev`). Verify both repos exist and the SDK repo has a `.venv` folder. Raises if any are missing.
2. **Sync swagger repo** — `git reset HEAD && git clean -fd && git checkout .`, then either checkout the user-provided `--sha` (after `git fetch origin`) or `git checkout origin/main && git pull origin main`. Records the resulting HEAD SHA.
3. **Sync SDK repo** — same clean/sync sequence on `azure-sdk-for-python`.
4. **Find readme.md** — searches every `readme.python.md` under `<spec-repo>/specification/` for the SDK package name; uses the sibling `readme.md`. Errors if zero or multiple matches.
5. **Write `<sdk-repo>/.venv/generate_input_swagger.json`:**

   ```json
   {
     "specFolder": "../azure-rest-api-specs",
     "headSha": "<SHA>",
     "runMode": "release",
     "repoHttpsUrl": "https://github.com/Azure/azure-rest-api-specs",
     "python_tag": "<tag>",
     "sdkReleaseType": "<stable|beta>",
     "enableChangelog": false,
     "relatedReadmeMdFiles": ["<readme_path>"]
   }
   ```
6. **Install tooling & generate** — using the SDK repo's `.venv` (no shell activation needed; the script invokes `<.venv>/Scripts/pip` and `<.venv>/Scripts/sdk_generator` directly with `VIRTUAL_ENV`/`PATH` set):
   ```
   pip install -e eng/tools/azure-sdk-tools[ghtools]
   sdk_generator .venv/generate_input_swagger.json .venv/generate_output.json
   ```
7. **Bump version (stable only) & rewrite CHANGELOG (always)** — for **stable** releases, `_version.py` `A.B.0` → `A.(B-1).1`. For **beta** releases (`--release-type beta`), the version in `_version.py` is left untouched. In both cases, `CHANGELOG.md` is rewritten: keep the original date in the topmost heading and set the version to match `_version.py`; replace the section body with:
   ```
   ## <version> (<original_date>)

   ### Other Changes

     - Regenerated with latest code generator tool
   ```
8. **Ensure `aiohttp` in `dev_requirements.txt`** — check the package's `dev_requirements.txt`; if `aiohttp` is missing (or the file does not exist), append it.
9. **Branch, push, open PR** — branch `regen-<sdk-name>-YYYY-MM-DD`, force-push to `origin`, then `gh pr create` against `Azure/azure-sdk-for-python:main` with title `Regenerate <sdk-name> with latest code generator tool`.

At the end the script emits a `=== SESSION_STATE === ... === END_SESSION_STATE ===` block with `head_sha`, `readme_path`, `pkg_dir`, `version_old`, `version_new`, `branch`, `pr_url`. Parse it and report the PR URL to the user.

## Rules

- The script is the single source of truth. Do not split the workflow into manual steps.
- On any failure, surface the script's stderr to the user and stop — do not attempt recovery or retries.
- Use forward slashes when passing `--work-dir`.
- The `.env` file (when present) lives at the productivity-tool repo root and may contain:
  ```
  LOCAL_AZURE_SPEC_REPO=C:/path/to/azure-rest-api-specs
  LOCAL_AZURE_SDK_REPO=C:/path/to/azure-sdk-for-python
  ```
