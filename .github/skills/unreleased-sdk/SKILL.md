---
name: unreleased-sdk
description: Use when the user wants to find azure-mgmt-* Python SDK packages whose latest CHANGELOG version has not yet been published to PyPI (i.e. unreleased/pending releases). Triggers on phrases like "unreleased sdk", "which packages are not released", "scan unreleased mgmt versions", "pending SDK releases".
---

# Unreleased SDK

Scan the local **azure-sdk-for-python** clone for `azure-mgmt-*` packages whose latest
`CHANGELOG.md` version is **not yet published on PyPI** — i.e. a release is pending. The result
is a Markdown table of every such package with links to its CHANGELOG and PyPI history.

Reference PR: https://github.com/Azure/azure-sdk-for-python/pull/47522

## Input

- No required input. Optionally the user may point at a specific repo root or adjust concurrency.

## Prerequisites

- A local clone of **azure-sdk-for-python**. The script resolves its path from:
  1. `LOCAL_AZURE_SDK_REPO` in a `.env` file at the productivity-tool repo root, or
  2. the default `C:/dev/azure-sdk-for-python`.
- Network access to `pypi.org` (the script queries the PyPI JSON API for each package).

## Workflow

Run the bundled script — it does everything in one process:

```
python <skill-dir>/scripts/check_unreleased_mgmt.py
```

Optional flags:

- `--repo-root <PATH>` — override the azure-sdk-for-python repo root.
- `--workers <N>` — number of concurrent PyPI lookups (default `16`).
- `--skip-sync` — skip syncing the local SDK repo to `origin/main` before scanning.

The script will:
1. Resolve the azure-sdk-for-python repo root (`.env` → `LOCAL_AZURE_SDK_REPO`, else `C:/dev/azure-sdk-for-python`).
2. Sync the local clone to `origin/main` (hard reset + clean + fetch + pull) so the scan reflects the latest state. Skipped with `--skip-sync`.
3. Discover all `sdk/*/azure-mgmt-*/CHANGELOG.md` files.
4. Parse each CHANGELOG's latest version header (`## <version> (<date>)`).
5. Query the PyPI JSON API to check whether that version is already published.
6. Collect the packages whose latest version is **missing** from PyPI, skipping
   `azure-mgmt-core` and any package whose latest CHANGELOG entry is older than 6 months.
7. Print progress to **stderr** and a Markdown table to **stdout**.

## Output

Present the Markdown table from **stdout** to the user directly — **do not write a file**. The table
has columns: `SDK Name`, `Unreleased Version`, `CHANGELOG` (GitHub link), `PyPI` (release history link),
preceded by a total count. Example:

```
# Unreleased azure-mgmt-* Packages

Total: 4 package(s) with an unreleased latest CHANGELOG version.

| SDK Name | Unreleased Version | CHANGELOG | PyPI |
| --- | --- | --- | --- |
| azure-mgmt-alertprocessingrules | 1.0.0b1 | [CHANGELOG.md](...) | [release history](...) |
```

## Rules

- Always run the bundled script — do not scan CHANGELOGs / query PyPI step by step manually.
- The script syncs the local clone to `origin/main` by default (hard reset + `git clean -fd`), which
  discards local changes in the SDK repo. If the user has uncommitted work there, run with `--skip-sync`.
- If the resolved repo root does not exist, the script exits with an error; tell the user to clone
  azure-sdk-for-python or set `LOCAL_AZURE_SDK_REPO` in `.env`, then stop.
- Scope is **azure-mgmt-*** management-plane packages only (matches the reference PR).
- A version counts as "unreleased" when the package's latest CHANGELOG version string is not present
  in the package's PyPI `releases`. Packages never published to PyPI are also reported as unreleased.
- `azure-mgmt-core` is always excluded, and packages whose latest CHANGELOG entry is dated more than
  6 months ago are skipped as stale (entries with no/unparseable date are kept).
