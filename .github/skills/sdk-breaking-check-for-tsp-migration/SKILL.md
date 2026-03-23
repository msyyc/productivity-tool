---
name: sdk-breaking-check-for-tsp-migration
description: Use when the user mentions checking breaking changes for a TypeSpec migration with an SDK package name, or asks to compare swagger vs typespec SDK output for a service.
---

# SDK Breaking Change Check for TypeSpec Migration

Check for breaking changes when a service migrates from Swagger to TypeSpec by comparing the pre-migration and post-migration SDK output.

## Overview

When a service migrates its API spec from Swagger to TypeSpec, the generated Python SDK may have unintended breaking changes. This skill orchestrates a multi-step workflow to detect and mitigate those breaking changes.

Each package gets its own isolated git worktrees so the main repos stay clean.

## Time Estimates

Typical wall-clock times observed per step (may vary by package size and network):

| Step | Typical Duration | Notes |
|------|-----------------|-------|
| Step 0 | ~8 min | Dominated by git worktree checkout of large repos + venv setup |
| Step 1 | ~10 sec | Fast git log search |
| Step 2 | ~3 min | Swagger SDK generation + code report |
| Step 3 | ~4.5 min | TypeSpec SDK generation + code report |
| Step 4 | ~15 sec | Report comparison + changelog generation |
| Step 5 | ~2 min | Classification + PR creation |
| **Total** | **~18 min** | End-to-end for a typical package |

## Prerequisites

- **Python** must be installed and available on PATH.
- **GitHub CLI** (`gh`) must be installed and authenticated.

## General Rules

- All scripts (Steps 1–5) must be invoked using the `.venv` Python environment created in the SDK worktree during Step 0. **Always activate the venv first** rather than calling the interpreter by full path (full-path invocation may be blocked by sandbox restrictions):
  - Linux/Mac: `cd <sdk_worktree> && source .venv/bin/activate && python <script>`
  - Windows: `cd <sdk_worktree> && .venv\Scripts\Activate.ps1 && python <script>`

## Workflow (Multi-Step)

This is a long-running workflow. Execute only the step the user requests, then stop and report results.

### Step 0: Setup Worktrees

Create isolated git worktrees for the spec repo and SDK repo.

**Input:** SDK package name (e.g., `azure-mgmt-securityinsights`)

**Prerequisites:** `azure-rest-api-specs` and `azure-sdk-for-python` must exist under the same parent directory (defaults to `C:/dev` on Windows, `/workspaces` on Linux).

**Run the bundled script:**

```
python <skill-dir>/scripts/setup_worktrees.py <package-name> [--base-dir <dir>] [--worktrees-dir <dir>]
```

This creates:
- `<worktrees-dir>/spec-<package-name>/` — worktree of azure-rest-api-specs on branch `spec-<package-name>`
- `<worktrees-dir>/sdk-<package-name>/` — worktree of azure-sdk-for-python on branch `sdk-<package-name>`
- A `.venv` with `azure-sdk-tools` installed in the SDK worktree

**Parse the `=== SESSION_STATE ===` block** to extract:
- `spec_worktree`, `sdk_worktree`, `spec_branch`, `sdk_branch`

**Store to SQL session state:**

```sql
CREATE TABLE IF NOT EXISTS session_state (key TEXT PRIMARY KEY, value TEXT);
INSERT OR REPLACE INTO session_state (key, value) VALUES
  ('package_name', '<package-name>'),
  ('spec_worktree', '<parsed value>'),
  ('sdk_worktree', '<parsed value>'),
  ('spec_branch', '<parsed value>'),
  ('sdk_branch', '<parsed value>'),
  ('github_username', '<parsed value>');
```

### Step 1: Find Pre-Migration Commit

Find the last commit in the spec repo before `tspconfig.yaml` was added for the target service.

**Run the bundled script:**

```
python <skill-dir>/scripts/find_last_commit_without_file.py <package-name> --spec-dir <spec_worktree>
```

**Parse the `=== SESSION_STATE ===` block** to extract:
- `tspconfig_path`
- `pre_migration_commit`
- `spec_folder`

**Store to SQL session state:**

```sql
INSERT OR REPLACE INTO session_state (key, value) VALUES
  ('tspconfig_path', '<parsed value>'),
  ('pre_migration_commit', '<parsed value>'),
  ('spec_folder', '<parsed value>');
```

**Report to user:**
- The pre-migration commit SHA and date
- The spec folder URL: `https://github.com/Azure/azure-rest-api-specs/tree/<commit-sha>/<spec-folder>`

### Step 2: Generate Swagger SDK and Code Report

Generate the Python SDK from the pre-migration Swagger spec and produce a breaking change code report.

**Read session state:**

```sql
SELECT key, value FROM session_state
WHERE key IN ('package_name', 'pre_migration_commit', 'spec_worktree', 'sdk_worktree');
```

**Check for cached generation:** Before running the script, check if the SDK worktree already has a commit with the same spec commit:

```
cd <sdk_worktree>
git log -1 --format=%B
```

If the last commit message matches the format `generated from swagger:<pre_migration_commit>`, skip regeneration and reuse the existing code report. Parse `sdk_package_path` and `swagger_code_report` from session state (they should already be stored from the previous run).

**Run the bundled script** (only if cache miss):

```
python <skill-dir>/scripts/generate_swagger_sdk.py <package_name> <pre_migration_commit> --spec-dir <spec_worktree> --sdk-dir <sdk_worktree>
```

**Parse the `=== SESSION_STATE ===` block** to extract:
- `sdk_package_path` — relative path to the SDK package directory
- `swagger_code_report` — absolute path to `code_report_swagger.json`

The script automatically commits with the message `generated from swagger:<pre_migration_commit>` (used for cache detection on re-runs).

**Store to SQL session state:**

```sql
INSERT OR REPLACE INTO session_state (key, value) VALUES
  ('sdk_package_path', '<parsed value>'),
  ('swagger_code_report', '<parsed value>');
```

### Step 3: Generate TypeSpec SDK and Code Report

Generate the Python SDK from the post-migration TypeSpec spec (HEAD of main) and produce a breaking change code report.

**Read session state:**

```sql
SELECT key, value FROM session_state
WHERE key IN ('package_name', 'spec_folder', 'spec_worktree', 'sdk_worktree', 'github_username');
```

**Determine current spec HEAD:**

```
cd <spec_worktree>
git rev-parse HEAD
```

**Check for cached generation:** Before running the script, check if the SDK worktree already has a commit with the same spec commit:

```
cd <sdk_worktree>
git log -1 --format=%B
```

If the last commit message matches the format `generated from typespec:<head_sha>` where `<head_sha>` matches the current HEAD of the spec worktree, skip regeneration. Since there are no code changes, Steps 4 and 5 can also be skipped. Inform the user that the spec has not changed since the last generation and no further action is needed.

**Run the bundled script** (only if cache miss):

```
python <skill-dir>/scripts/generate_typespec_sdk.py <package_name> <spec_folder> --spec-dir <spec_worktree> --sdk-dir <sdk_worktree>
```

**Parse the `=== SESSION_STATE ===` block** to extract:
- `typespec_code_report` — absolute path to `code_report_typespec.json`
- `head_sha` — HEAD commit of spec repo main branch

The script automatically commits with the message `generated from typespec:<head_sha>` (used for cache detection on re-runs).

**Store to SQL session state:**

```sql
INSERT OR REPLACE INTO session_state (key, value) VALUES
  ('typespec_code_report', '<parsed value>'),
  ('head_sha', '<parsed value>');
```

### Step 4: Compare Reports and Generate Changelog

Compare the swagger and typespec code reports to detect breaking changes and generate a changelog.

**Read session state:**

```sql
SELECT key, value FROM session_state
WHERE key IN ('package_name', 'sdk_package_path', 'sdk_worktree');
```

**Run the bundled script:**

```
python <skill-dir>/scripts/compare_reports.py <package_name> <sdk_package_path> --sdk-dir <sdk_worktree>
```

**Parse the `=== SESSION_STATE ===` block** to extract:
- `changelog_path` — absolute path to the updated CHANGELOG.md
- `has_breaking_changes` — `true` or `false`

The script automatically commits the changelog update.

**Store to SQL session state:**

```sql
INSERT OR REPLACE INTO session_state (key, value) VALUES
  ('changelog_path', '<parsed value>'),
  ('has_breaking_changes', '<parsed value>');
```

### Step 5: Analyze Breaking Changes and Create Spec PR

Analyze the changelog from step 4, classify each breaking change, generate mitigations in the spec repo, and create a PR.

**Read session state:**

```sql
SELECT key, value FROM session_state
WHERE key IN ('package_name', 'spec_folder', 'has_breaking_changes', 'sdk_package_path',
              'changelog_path', 'spec_worktree', 'spec_branch', 'github_username');
```

If `has_breaking_changes` is `false`, report that no mitigations are needed and stop.

**Read the changelog** from `changelog_path` to get breaking change items.

**Read the classification guide** at [references/breaking-changes-guide.md](references/breaking-changes-guide.md).

**For each breaking change item:**

1. Classify it using the guide's Action Matrix
2. **ACCEPT** → note it (no code change)
3. **MITIGATE** → generate `@@clientName` or `@@override` decorator

**To find TypeSpec type definitions:** search the `spec_folder` in the spec worktree.

**Generate mitigations** in the spec worktree:

1. Create or update `client.tsp` in `<spec_worktree>/<spec_folder>/` with:
```tsp
import "./main.tsp";
import "@azure-tools/typespec-client-generator-core";

using Azure.ClientGenerator.Core;

@@clientName(...);
```
2. Update `tspconfig.yaml` to use `client.tsp` as entry point if needed

**Create a draft spec PR:**

```
cd <spec_worktree>
git add . && git commit -m "Mitigate Python SDK breaking changes for {package}"
git push <github_username> HEAD
```

Write the PR body to a temporary file first, then create the PR with `--body-file`:

```
gh pr create --repo Azure/azure-rest-api-specs --head <github_username>:<spec_branch> --base main --draft --title "[Python] Mitigate breaking changes for {package_name}" --body-file <temp-file>
```

The PR body should include a summary table of all breaking changes and their classification.

**Create a draft SDK PR:**

Always push the SDK worktree changes and create a draft PR targeting `Azure/azure-sdk-for-python` main:

```
cd <sdk_worktree>
git add . && git commit -m "[Python] TypeSpec migration SDK output for {package_name}"
git push <github_username> HEAD
```

Write the PR body to a temporary file first, then create the PR with `--body-file`:

```
gh pr create --repo Azure/azure-sdk-for-python --head <github_username>:<sdk_branch> --base main --draft --title "[Python] TypeSpec migration for {package_name}" --body-file <temp-file>
```

The PR body (`<report>`) should contain the full breaking change analysis report, including:
- Pre-migration swagger source: `[<pre_migration_commit>](https://github.com/Azure/azure-rest-api-specs/commit/<pre_migration_commit>)` (clickable link to the exact commit used to generate the swagger SDK — use `/commit/` URL, not `/tree/` with spec_folder, since the folder path may not exist at that commit)
- Summary of classifications (accepted vs mitigated)
- List of accepted breaking changes that will remain
- The spec PR URL (if mitigations were created)

**Report to user:**
- Summary of classifications (accepted vs mitigated)
- The spec PR URL (if any)
- The SDK draft PR URL
- List of accepted breaking changes that will remain

## Rules

- Always use `gh` CLI for GitHub operations, not the GitHub MCP server tools.
- Run only the step the user asks for. Do not proceed to the next step automatically.
- If the script fails, show the full error output to the user.
- Use forward slashes in all file paths.
- All spec repo operations use the `spec_worktree` path, all SDK operations use the `sdk_worktree` path.
- **PR body must be written to a temporary file** and passed via `gh pr create --body-file <file>` instead of `--body "<text>"`. Inline `--body` causes shell encoding corruption — backtick-escaped sequences like `` \`vault\` `` get interpreted as control characters (`\v` → vertical tab, `\a` → bell, `\e` → escape, etc.).
- **Pre-migration swagger source link**: The `spec_folder` from session state is the TypeSpec folder path, which may not exist at the `pre_migration_commit` (e.g., when the migration also restructured folders). Use just the commit URL `https://github.com/Azure/azure-rest-api-specs/commit/<pre_migration_commit>` rather than a tree URL with the spec_folder path.
