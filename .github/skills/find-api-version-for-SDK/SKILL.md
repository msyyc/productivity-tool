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
2. Download the **sdist** (`.tar.gz` / `.zip`) for that exact version directly from PyPI's JSON API into `temp/<package>-<version>/download`. (Pip is intentionally bypassed to avoid PEP 517 metadata preparation overhead — a wheel-less `pip download` would spin up an isolated build env per call.)
3. Extract the sdist into `temp/<package>-<version>/extracted`. `source_dir` is the **top-level** extracted folder (sdist root containing `setup.py`/`pyproject.toml`), not the deep `azure/mgmt/<svc>` package directory.
4. Scan `_configuration.py` and `*_client.py` for api-version literals like `2021-02-01`.
5. Search every `readme.python.md` under `<spec-repo>/specification` for the package name.
6. If the extracted sources contain a `_meta.json`, read `commit` + `readme` to build the **old readme link** and parse `--tag=<value>` out of `autorest_command` for the **old tag**.
7. Locate the package folder under `<sdk-repo>/sdk/*/<package>/`. The script does **not** run any keyword-based deprecation detection (it produced false positives). Instead, it prints the full `README.md` and the latest `CHANGELOG.md` section between `--- BEGIN ... ---` / `--- END ... ---` markers so **the agent itself must read them and decide** whether the package is deprecated.
8. Print a `=== SUMMARY ===` block with `deprecation` (`NEEDS_JUDGEMENT` or `WARNING: README.md/CHANGELOG.md not found !!!`), `api_versions`, `source_dir`, `readme_paths`, `readme_urls`, `old readme link`, `old tag`, followed by the README/CHANGELOG content blocks.

Parse that block and report to the user in this exact format:

```
Package: <package> <resolved-version>

<deprecation-line>     # only printed when deprecation != OK; see notes below

PyPI history: https://pypi.org/project/<package>/#history

API version(s): <comma-separated list>     # or: "Could not find api-version in the package"

Open source code:

code <source_dir>

Spec folder(s):
<readme_url_1>
<readme_url_2>
...

Old readme link: <url>     # or "not found"

Old tag: <tag>              # or "not found"

```

Notes for the report:
- **Deprecation judgement (mandatory, agent-only):** The script no longer attempts to detect deprecation by keywords — it just hands you the raw content.
  - If `deprecation: WARNING: README.md/CHANGELOG.md not found !!!`, print that line verbatim.
  - If `deprecation: NEEDS_JUDGEMENT`, **you must read the `--- BEGIN SDK README.md ---` and `--- BEGIN SDK CHANGELOG.md (latest section) ---` blocks yourself** and decide. Only print **`WARNING: deprecated!!!`** when those files **explicitly state** that this Python SDK package is deprecated / retired / unmaintained / superseded — for example wording like "this package is deprecated", "this package will no longer receive updates", "please use `<other-package>` instead", "this is the final release", "this library has been retired". Otherwise omit the deprecation line entirely.
  - **Whenever you print `WARNING: deprecated!!!` or `WARNING: README.md/CHANGELOG.md not found !!!`**, append the SDK repo link from `sdk_repo_url:` on the next line so the user can click straight to the package folder, e.g. `SDK repo: https://github.com/Azure/azure-sdk-for-python/tree/main/sdk/commerce/azure-mgmt-commerce`. If `sdk_repo_url: NOT_FOUND`, omit that line.
  - **Do NOT infer deprecation from:** the generic Python 2.7 EOL disclaimer ("support for Python 2.7 has ended"), a CHANGELOG breaking-change line like "credentials are no longer supported" or "Model X no longer has parameter Y", the underlying Azure service/REST API being retired, external knowledge about the product, or an old "last release" date. Rely **only** on wording in the package's own README.md / CHANGELOG.md that is unambiguously about this SDK package itself.
- If `api_versions: NOT_FOUND`, print **"Could not find api-version in the package"** for that line.
- The `code <path>` line is intentionally a copy-paste-ready command for the user to open the extracted SDK source in VS Code.
- Each `readme_url` is the GitHub folder URL with `readme.python.md` stripped, so the user lands on the folder.
- If `readme_paths: NOT_FOUND`, print **"No matching readme.python.md found in the spec repo"** under "Spec folder(s):".
- `old readme link` is built from `_meta.json` as `https://github.com/Azure/azure-rest-api-specs/blob/<commit>/<readme>`. If `_meta.json` is absent or fields are missing, print `not found`.
- `old tag` is the value after `--tag=` (or `--tag `) inside `autorest_command` in `_meta.json`; print `not found` if absent.

## Rules

- Always run the bundled script — do not manually pip-download / extract / grep step by step. Speed matters.
- Pass the version exactly as the user typed it, except map natural-language synonyms to the script's keywords:
  - "latest", "latest stable", "newest stable" → `latest`
  - "latest preview", "newest preview", "latest beta" → `latest-preview`
- If the user gives an explicit version that doesn't exist on PyPI, the script will fail; surface the pip error to the user and stop.
- Spec and SDK repo locations are resolved at startup:
  1. If a `.env` file exists at the productivity-tool repo root, the script reads `LOCAL_AZURE_SPEC_REPO` and `LOCAL_AZURE_SDK_REPO` from it.
  2. Otherwise it falls back to `C:/dev/azure-rest-api-specs` and `C:/dev/azure-sdk-for-python`.
  If the resolved spec path doesn't exist, the script logs a warning and skips the readme search; report "spec repo not found locally" to the user.
- If multiple `readme.python.md` files match, list them **all** (paths and URLs), in the order returned.
- Do not delete the `temp/` folder afterwards — the user may want to browse it via the printed `code` command.
