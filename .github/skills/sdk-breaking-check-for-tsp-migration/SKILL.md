---
name: sdk-breaking-check-for-tsp-migration
description: Use when the user mentions checking breaking changes for a TypeSpec migration with an SDK package name or a spec PR URL, or asks to compare swagger vs typespec SDK output for a service.
---

# SDK Breaking Change Check for TypeSpec Migration

Check for breaking changes when a service migrates from Swagger to TypeSpec by comparing the pre-migration and post-migration SDK output.

## Overview

When a service migrates its API spec from Swagger to TypeSpec, the generated Python SDK may have unintended breaking changes. This skill orchestrates a multi-step workflow to detect and mitigate those breaking changes.

Each package gets its own isolated git worktrees so the main repos stay clean.

## Input Modes

The skill supports two input modes:

1. **Package name** (e.g., `azure-mgmt-securityinsights`): The existing flow — user provides the SDK package name directly.
2. **Spec PR URL** (e.g., `https://github.com/Azure/azure-rest-api-specs/pull/40023`): The package name is extracted automatically from the PR's changed `tspconfig.yaml`. Steps 3 and 5 are adjusted to work against the PR's head commit and source branch.

When a PR URL is provided, run the **Pre-Step** before Step 0 to extract the package name and PR metadata.

## Time Estimates

Typical wall-clock times observed per step (may vary by package size and network):

| Step | Typical Duration | Notes |
|------|-----------------|-------|
| Step 0 | ~8 min | Dominated by git worktree checkout of large repos + venv setup |
| Step 1 | ~10 sec | Fast git log search |
| Step 1.5 | ~5 sec | Reads readme.md via git show (no checkout needed) |
| Step 2 | ~3 min | Swagger SDK generation + code report |
| Step 3 | ~4.5 min | TypeSpec SDK generation + code report |
| Step 4 | ~15 sec | Report comparison + changelog generation |
| Step 4.5 | ~30 sec | Changelog rename consolidation |
| Step 5 | ~2 min | Classification + PR creation |
| Step 6 | ~1 min | Changelog optimization (subagent) |
| Step 7 | ~1 min | Mitigate any new renames surfaced by Step 6 (often a no-op) |
| **Total** | **~20 min** | End-to-end for a typical package |

## Prerequisites

- **Python** must be installed and available on PATH.
- **GitHub CLI** (`gh`) must be installed and authenticated.

## General Rules

- All scripts (Steps 1–5) must be invoked using the `.venv` Python environment created in the SDK worktree during Step 0. **Always activate the venv first** rather than calling the interpreter by full path (full-path invocation may be blocked by sandbox restrictions):
  - Linux/Mac: `cd <sdk_worktree> && source .venv/bin/activate && python <script>`
  - Windows: `cd <sdk_worktree> && .venv\Scripts\Activate.ps1 && python <script>`

## Workflow (Multi-Step)

This is a long-running workflow. Execute only the step the user requests, then stop and report results.

### Pre-Step: Extract Package from PR (PR mode only)

When the user provides a spec PR URL instead of a package name, run this step first to extract the package name and PR metadata. This step uses `gh` CLI only — no worktree or venv needed.

**Input:** Spec PR URL (e.g., `https://github.com/Azure/azure-rest-api-specs/pull/40023`) or PR number

**Run the bundled script:**

```
python <skill-dir>/scripts/extract_package_from_pr.py <pr-url-or-number>
```

**Parse the `=== SESSION_STATE ===` block** to extract:
- `package_name` — the Python SDK package name (e.g., `azure-mgmt-securityinsights`)
- `pr_number` — the spec PR number
- `pr_head_ref` — the PR's source branch name
- `pr_head_owner` — the fork owner (GitHub username)

**Store to SQL session state:**

```sql
CREATE TABLE IF NOT EXISTS session_state (key TEXT PRIMARY KEY, value TEXT);
INSERT OR REPLACE INTO session_state (key, value) VALUES
  ('package_name', '<parsed value>'),
  ('pr_number', '<parsed value>'),
  ('pr_head_ref', '<parsed value>'),
  ('pr_head_owner', '<parsed value>');
```

Then proceed to Step 0 with the extracted `package_name`.

### Step 0: Setup Worktrees

Create isolated git worktrees for the spec repo and SDK repo.

**Input:** SDK package name (e.g., `azure-mgmt-securityinsights`)

**PyPI release check:** Before creating worktrees, verify the package has been published to PyPI:

```
pip index versions <package-name> --pre
```

The `--pre` flag is required because some packages only have pre-release versions (e.g., `1.0.0b1`), which `pip index versions` excludes by default.

If the package is **not found on PyPI**, or the **only published version is `0.0.0`** (a placeholder, not a real release), inform the user that the package has never been released, so there are no existing consumers to break — breaking change validation is unnecessary. **Stop the workflow** unless the user explicitly asks to continue.

**TypeSpec migration check:** Before creating worktrees, check whether the SDK package folder on the `main` branch of the local `azure-sdk-for-python` repo already contains a `tsp-location.yaml` file:

```
# Find the package folder and check for tsp-location.yaml
# The package folder is typically at sdk/<service>/<package-name>/
git -C <sdk-repo-path> show main:sdk/**/<package-name>/tsp-location.yaml
```

Or more reliably, use `git ls-tree` to search:

```
git -C <sdk-repo-path> ls-tree -r --name-only main | Select-String "sdk/.*/<package-name>/tsp-location.yaml"
```

If `tsp-location.yaml` **already exists** in the package folder, the SDK has already been migrated to TypeSpec — there is no Swagger-to-TypeSpec migration to validate. Inform the user that the package is already TypeSpec-based and breaking change validation for migration is unnecessary. **Stop the workflow** unless the user explicitly asks to continue.

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
- `swagger_spec_folder`

**Store to SQL session state:**

```sql
INSERT OR REPLACE INTO session_state (key, value) VALUES
  ('tspconfig_path', '<parsed value>'),
  ('pre_migration_commit', '<parsed value>'),
  ('spec_folder', '<parsed value>'),
  ('swagger_spec_folder', '<parsed value>');
```

**Report to user:**
- The pre-migration commit SHA and date
- A browsable link to the swagger spec folder: `https://github.com/Azure/azure-rest-api-specs/tree/<pre_migration_commit>/<swagger_spec_folder>` (this points to the `resource-manager` folder which exists at the pre-migration commit, unlike the TypeSpec folder path)

### Step 1.5: Extract Swagger Default Tag and API Version

Extract the default tag from the swagger `readme.md` at the pre-migration commit and determine which API versions are used under that tag.

**Read session state:**

```sql
SELECT key, value FROM session_state
WHERE key IN ('package_name', 'pre_migration_commit', 'swagger_spec_folder', 'spec_worktree');
```

**Run the bundled script:**

```
python <skill-dir>/scripts/extract_swagger_api_version.py <package_name> --spec-dir <spec_worktree> --commit <pre_migration_commit> --swagger-spec-folder <swagger_spec_folder>
```

The script reads `readme.md` via `git show` (no worktree checkout needed). It finds the default `tag:` in the first non-conditional yaml block, then extracts the `input-file` list for that tag and parses API versions from the file paths.

**Parse the `=== SESSION_STATE ===` block** to extract:
- `default_tag` — the default swagger tag name (e.g., `package-2025-11`)
- `swagger_api_versions` — comma-separated sorted unique API versions (e.g., `2025-11-01` or `2019-11-01,2021-06-01,2025-03-01`)

**Store to SQL session state:**

```sql
INSERT OR REPLACE INTO session_state (key, value) VALUES
  ('default_tag', '<parsed value>'),
  ('swagger_api_versions', '<parsed value>');
```

**Report to user:**
- The default tag name
- If a single API version: report the version (e.g., "API version: `2025-11-01`")
- If multiple API versions: report all of them (e.g., "Default tag `package-2025-03` contains multiple API versions: `2019-11-01` / `2021-06-01` / `2025-03-01`")

### Step 2: Generate Swagger SDK and Code Report

Generate the Python SDK from the pre-migration Swagger spec and produce a breaking change code report.

**Read session state:**

```sql
SELECT key, value FROM session_state
WHERE key IN ('package_name', 'pre_migration_commit', 'spec_worktree', 'sdk_worktree');
```

**Run the bundled script:**

```
python <skill-dir>/scripts/generate_swagger_sdk.py <package_name> <pre_migration_commit> --spec-dir <spec_worktree> --sdk-dir <sdk_worktree>
```

The script has built-in cache detection: it searches commit history for `generated from swagger:<pre_migration_commit>` and reuses the cached commit if found, skipping regeneration automatically.

**Parse the `=== SESSION_STATE ===` block** to extract:
- `sdk_package_path` — relative path to the SDK package directory
- `swagger_code_report` — absolute path to `code_report_swagger.json`
- `swagger_readme_dir` — relative path to the swagger readme directory (e.g., `specification/frontdoor/resource-manager`)

The script automatically commits with the message `generated from swagger:<pre_migration_commit>` (used for its internal cache detection on re-runs).

**Store to SQL session state:**

```sql
INSERT OR REPLACE INTO session_state (key, value) VALUES
  ('sdk_package_path', '<parsed value>'),
  ('swagger_code_report', '<parsed value>'),
  ('swagger_readme_dir', '<parsed value>');
```

### Step 3: Generate TypeSpec SDK and Code Report

Generate the Python SDK from the post-migration TypeSpec spec and produce a breaking change code report.

**Read session state:**

```sql
SELECT key, value FROM session_state
WHERE key IN ('package_name', 'spec_folder', 'spec_worktree', 'sdk_worktree', 'github_username',
              'swagger_api_versions', 'pr_number');
```

**Run the bundled script:**

If `swagger_api_versions` exists in session state (from Step 1.5), append `--swagger-api-versions <swagger_api_versions>` to the command. This enables automatic apiVersion resolution: the script reads `main.tsp` in the TypeSpec folder, and if the swagger default tag has a single API version that also appears in the TypeSpec `enum Versions`, it uses that version; otherwise it uses the latest version from `enum Versions`. The resolved version is set as `"apiVersion"` in the generation input JSON.

- **Package name mode** (no `pr_number` in session state):
  ```
  python <skill-dir>/scripts/generate_typespec_sdk.py <package_name> <spec_folder> --spec-dir <spec_worktree> --sdk-dir <sdk_worktree> [--swagger-api-versions <swagger_api_versions>]
  ```

- **PR mode** (when `pr_number` exists in session state):
  ```
  python <skill-dir>/scripts/generate_typespec_sdk.py <package_name> <spec_folder> --spec-dir <spec_worktree> --sdk-dir <sdk_worktree> --pr-number <pr_number> [--swagger-api-versions <swagger_api_versions>]
  ```

In package name mode, the script checks out `origin/main`. In PR mode, it fetches `pull/<pr_number>/head` and checks out the PR's head commit instead. In both modes, it uses the latest commit that touched the service's spec folder for its cache key. It searches commit history for `generated from typespec:<head_sha>` and reuses the cached commit if found, skipping regeneration automatically. If the script reports a cache hit, Steps 4 and 5 can also be skipped since the spec has not changed since the last generation.

**Parse the `=== SESSION_STATE ===` block** to extract:
- `typespec_code_report` — absolute path to `code_report_typespec.json`
- `head_sha` — latest commit SHA that touched the service's spec folder
- `api_version` — (optional) the resolved API version used for generation (e.g., `2025-11-01`)
- `api_version_source` — (optional) `swagger` if matched from swagger default tag, or `typespec-latest` if using the latest version from main.tsp

The script automatically commits with the message `generated from typespec:<head_sha>` (used for its internal cache detection on re-runs).

**Store to SQL session state:**

```sql
INSERT OR REPLACE INTO session_state (key, value) VALUES
  ('typespec_code_report', '<parsed value>'),
  ('head_sha', '<parsed value>');
-- Only if present in output:
INSERT OR REPLACE INTO session_state (key, value) VALUES
  ('api_version', '<parsed value>'),
  ('api_version_source', '<parsed value>');
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

### Step 4.5: Optimize Changelog (Consolidate Renames)

Consolidate noisy `Deleted or renamed model` + `Added model/enum` pairs into clearer `Renamed X to Y` (1‑1) or `Combined enum X/Y/... to Z` (many‑1) entries.

**Read session state:**

```sql
SELECT key, value FROM session_state
WHERE key IN ('package_name', 'sdk_package_path', 'sdk_worktree', 'changelog_path', 'has_breaking_changes');
```

If `has_breaking_changes` is `false`, skip this step.

**Procedure:** Follow [references/optimize-changelog-consolidate-renames.md](references/optimize-changelog-consolidate-renames.md) using the session state values above as inputs. Include the report sections from that doc in the final report at Step 5.

### Step 5: Analyze Breaking Changes and Create Spec PR

Analyze the changelog from step 4, classify each breaking change, generate mitigations in the spec repo, and create a PR.

**Read session state:**

```sql
SELECT key, value FROM session_state
WHERE key IN ('package_name', 'spec_folder', 'has_breaking_changes', 'sdk_package_path',
              'changelog_path', 'spec_worktree', 'spec_branch', 'github_username',
              'pre_migration_commit', 'swagger_spec_folder',
              'default_tag', 'swagger_api_versions',
              'api_version', 'api_version_source',
              'pr_number', 'pr_head_ref', 'pr_head_owner');
```

If `has_breaking_changes` is `false`, report that no mitigations are needed and stop.

**Extract latest changelog section:**

Read the CHANGELOG.md at `changelog_path` and extract only the content under the **first** `##` version heading — everything from that heading up to (but not including) the next `##` heading, or to end-of-file if there is no next heading. This is the latest version section containing the breaking changes detected in Step 4. Store this extracted text for the subagent prompt.

**Analyze breaking changes and generate mitigations:**

1. Read the classification guide at `<skill-dir>/references/breaking-changes-guide.md` and follow the link inside to read the full guide
2. For each breaking change item in the extracted changelog section:
   - Classify it using the guide's Action Matrix
   - **ACCEPT** → note it (no code change needed)
   - **MITIGATE** → search for the TypeSpec type definition in `<spec_worktree>/<spec_folder>/` and generate the appropriate `@@clientName` or `@@override` decorator
3. Generate mitigations in the spec worktree:
   - Create or update `client.tsp` in `<spec_worktree>/<spec_folder>/` with:
     ```tsp
     import "./main.tsp";
     import "@azure-tools/typespec-client-generator-core";

     using Azure.ClientGenerator.Core;

     @@clientName(...);
     ```
4. **Format the edited TypeSpec files.** After creating or editing `client.tsp`, run `tsv` (TypeSpec validate/format) from the **root of the spec worktree** against the folder containing `client.tsp`:

   ```
   cd <spec_worktree>
   npm ci
   npx tsv <spec_folder>
   ```

   `<spec_folder>` is the directory that contains `client.tsp` (the same `spec_folder` stored in session state). Running `tsv` ensures the file matches the repo's TypeSpec formatting conventions so the mitigation PR doesn't fail style checks. `npm ci` only needs to be run once per worktree, but it is safe to re-run.
5. Produce a structured summary listing each breaking change, its classification (ACCEPT/MITIGATE), and any mitigations applied

Use this classification summary to proceed with PR creation.

**Push spec mitigations** — the approach depends on whether a PR was provided:

#### Package name mode (no `pr_number` in session state):

Create a new spec PR (not draft):

```
cd <spec_worktree>
git add <spec_folder>/client.tsp && git commit -m "Mitigate Python SDK breaking changes for {package}"
git push <github_username> HEAD
```

> **Important:** Stage only `client.tsp` (the file the agent intentionally edits for mitigations). Do **not** use `git add .` here — the SDK generation script in Step 3 may have side-effect modifications to `tspconfig.yaml` (e.g. YAML reformatting from a non-round-trip dump) in the spec worktree, and a blanket `git add .` would commit them into the mitigation PR, producing noisy unrelated diffs. If additional mitigation files are intentionally created (e.g. a new `client.tsp` in a subfolder), add them by explicit path.

Write the PR body to a temporary file first, then create the PR with `--body-file`. **Always add the required labels** via `--label` (one flag per label):

```
gh pr create --repo Azure/azure-rest-api-specs --head <github_username>:<spec_branch> --base main --title "[Python] Mitigate breaking changes for {package_name}" --body-file <temp-file> --label "BreakingChange-Go-Sdk-Approved" --label "BreakingChange-JavaScript-Sdk-Approved" --label "BreakingChange-Python-Sdk-Approved" --label "PublishToCustomers" --label "ARMSignedOff"
```

Keep the spec PR body **brief** — a one-line purpose statement plus a short bullet list of mitigations is sufficient. Do not duplicate the full breaking-change analysis report here (that goes in the SDK PR body).

#### PR mode (when `pr_number` exists in session state):

Create a new spec PR (not draft) targeting the input PR's source branch:

```
cd <spec_worktree>
git add <spec_folder>/client.tsp && git commit -m "Mitigate Python SDK breaking changes for {package}"
git push <github_username> HEAD
```

> **Important:** Same rule as Package name mode — stage only `client.tsp` (or other explicitly-authored mitigation files) by path. Never use `git add .` in the spec worktree, or unrelated side-effect changes (e.g. `tspconfig.yaml` reformatting from the generation script) will leak into the mitigation PR.

Write the PR body to a temporary file first, then create the PR with `--body-file`. **Always add the required labels** via `--label` (one flag per label):

```
gh pr create --repo <pr_head_owner>/azure-rest-api-specs --head <github_username>:<spec_branch> --base <pr_head_ref> --title "[Python] Mitigate breaking changes for {package_name}" --body-file <temp-file> --label "BreakingChange-Go-Sdk-Approved" --label "BreakingChange-JavaScript-Sdk-Approved" --label "BreakingChange-Python-Sdk-Approved" --label "PublishToCustomers" --label "ARMSignedOff"
```

Keep the spec PR body **brief** — a one-line purpose statement plus a short bullet list of mitigations is sufficient. Do not duplicate the full breaking-change analysis report here (that goes in the SDK PR body).

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
- **Spec source** (varies by input mode):
  - **PR mode** (`pr_number` exists in session state): `Spec PR: https://github.com/Azure/azure-rest-api-specs/pull/<pr_number>` (link to the original spec PR the user provided)
  - **Package name mode** (no `pr_number`): `TypeSpec folder: [<spec_folder>](https://github.com/Azure/azure-rest-api-specs/tree/main/<spec_folder>)` (link to the spec typespec folder containing `tspconfig.yaml`)
- Pre-migration swagger source: `[<swagger_spec_folder>@<pre_migration_commit[:8]>](https://github.com/Azure/azure-rest-api-specs/tree/<pre_migration_commit>/<swagger_spec_folder>)` (clickable link to browse the swagger files at the pre-migration commit)
- **Swagger API version** (from `default_tag` and `swagger_api_versions` in session state):
  - If `swagger_api_versions` contains a single version (no comma): `Swagger API version: <version> (default tag: <default_tag>)`
  - If `swagger_api_versions` contains multiple versions (comma-separated): `Default tag \`<default_tag>\` contains multiple API versions: \`<v1>\` / \`<v2>\` / ...`
  - If `swagger_api_versions` is empty or not set: omit this line
- **TypeSpec generation apiVersion** (from `api_version` and `api_version_source` in session state):
  - If `api_version_source` is `swagger`: `Generated with apiVersion: \`<api_version>\` (matched from swagger default tag)`
  - If `api_version_source` is `typespec-latest`: `Generated with apiVersion: \`<api_version>\` (latest in TypeSpec enum Versions)`
  - If `api_version` is not set: omit this line
- Summary of classifications (accepted vs mitigated)
- List of accepted breaking changes that will remain
- The spec mitigation PR URL (if mitigations were created)

**Report to user:**
- Summary of classifications (accepted vs mitigated)
- The spec PR URL (if any — in PR mode, link to the newly created mitigation PR)
- The SDK draft PR URL
- List of accepted breaking changes that will remain

### Step 6: Optimize Changelog

After the SDK PR is created in Step 5, apply the general changelog optimization rules to clean up noisy auto-generated entries. The push in this step updates the existing draft PR.

**Read session state:**

```sql
SELECT key, value FROM session_state
WHERE key IN ('package_name', 'sdk_worktree', 'changelog_path', 'has_breaking_changes', 'github_username');
```

If `has_breaking_changes` is `false`, skip this step.

This step is **independent** — delegate it to a **subagent** following the shared procedure.

**Procedure:** [../create-sdk-release-pr/references/changelog-optimization-procedure.md](../create-sdk-release-pr/references/changelog-optimization-procedure.md)

**Inputs to pass:**
- `package_name` — from session state
- `worktree_path` — `<sdk_worktree>` from session state
- `changelog_path` — from session state
- `commit_message` — `Optimize changelog for <package_name>`
- `push_target` — `git push <github_username> HEAD` (the SDK PR was pushed to the user's fork in Step 5)
- `skip_rules` — `[11]` (rule 11 — consolidating renames and combined enums — was already applied in Step 4.5)

**Report to user:** the summary returned by the subagent.

### Step 7: Mitigate New Renames Surfaced by Step 6

The changelog optimization in Step 6 may surface additional model/enum **rename** breaking changes that were not visible in the raw changelog used by Step 5 (for example, renames revealed after consolidating list-model removals, grouping operations, or other rule rewrites). These new renames must be mitigated with `@clientName` decorators and committed to the **same spec mitigation PR** created in Step 5.

**Read session state:**

```sql
SELECT key, value FROM session_state
WHERE key IN ('package_name', 'spec_folder', 'has_breaking_changes', 'sdk_package_path',
              'changelog_path', 'spec_worktree', 'spec_branch', 'github_username',
              'sdk_worktree', 'pr_number', 'pr_head_ref', 'pr_head_owner');
```

If `has_breaking_changes` is `false`, skip this step.

**Detect new renames:**

1. Read the CHANGELOG.md at `changelog_path` and extract the latest version section (from the first `## ` heading to the next `## ` heading, or end-of-file).
2. Scan for **model/enum rename** entries that affect public surface, specifically lines matching patterns such as:
   - `Renamed model <Old> to <New>`
   - `Renamed enum <Old> to <New>`

   Ignore `Combined enum ...` entries — those do not require mitigation in this step.
3. Cross-reference each rename against the spec mitigations already committed in Step 5 (inspect `<spec_worktree>/<spec_folder>/client.tsp`). Any rename **not** already covered by an existing `@@clientName` is a new mitigation candidate.

If no new renames remain, report "No additional mitigations needed" and stop.

**Generate mitigations:**

For each new rename:

1. Classify it per `<skill-dir>/references/breaking-changes-guide.md` (renames are typically **MITIGATE**).
2. Locate the TypeSpec model/enum definition in `<spec_worktree>/<spec_folder>/`.
3. Append the appropriate `@@clientName(...)` decorator to `<spec_worktree>/<spec_folder>/client.tsp` (do not create a second `client.tsp`).
4. Format the edits:

   ```
   cd <spec_worktree>
   npx tsv <spec_folder>
   ```

   (`npm ci` was already run in Step 5; no need to repeat.)

**Commit and push:**

```
cd <spec_worktree>
git add <spec_folder>/client.tsp
git commit -m "Mitigate additional Python SDK model/enum renames for {package_name}"
git push <github_username> HEAD
```

> **Important:** Stage only `client.tsp` by explicit path — same rule as Step 5. Never use `git add .` in the spec worktree.

**Determine whether a spec PR already exists:**

A spec mitigation PR exists from Step 5 only if Step 5 actually generated mitigations. Detect this by querying for an open PR from `<github_username>:<spec_branch>`:

```
gh pr list --repo Azure/azure-rest-api-specs --head <github_username>:<spec_branch> --state open --json url --jq ".[0].url"
```

In PR mode, replace the repo with `<pr_head_owner>/azure-rest-api-specs`.

- **If a PR URL is returned:** The push above automatically appends the new commit to that existing PR. **Do not create a new PR.**
- **If no PR is returned** (Step 5 had no mitigations to create): create a new spec PR now, following the same `gh pr create` command and labels documented in Step 5 (use Package name mode or PR mode based on whether `pr_number` is in session state).

**Report to user:**
- List of additional renames mitigated (with old → new names)
- The spec PR URL (either the existing one updated, or the newly created one)
- Note that the SDK draft PR will need to be regenerated once the spec mitigation PR is merged (or once Step 3 is re-run against the updated spec)

## Rules

- Always use `gh` CLI for GitHub operations, not the GitHub MCP server tools.
- Run only the step the user asks for. Do not proceed to the next step automatically.
- If the script fails, show the full error output to the user.
- Use forward slashes in all file paths.
- All spec repo operations use the `spec_worktree` path, all SDK operations use the `sdk_worktree` path.
- **PR body must be written to a temporary file avoiding PowerShell string processing**, then passed via `gh pr create --body-file <file>` instead of `--body "<text>"`. PowerShell interprets backticks (`` ` ``) as escape characters, corrupting markdown code spans even inside file-writing commands: `` `azure` `` becomes `\u0007zure` (`` `a ``→bell), `` `blob` `` becomes backspace+`lob` (`` `b ``→backspace), etc. The corruption is intermittent — it only triggers when the character after a backtick is one of PowerShell's special escape letters (`a`, `b`, `e`, `f`, `n`, `r`, `t`, `v`, `0`). **Safe method:** Use the `create` tool to write the body file directly (bypasses PowerShell entirely), then run `gh pr create --body-file <path>`. Never use `Set-Content`, `Out-File`, `>`, heredocs, or inline `--body` for PR body text.
- **Pre-migration swagger source link**: Use `swagger_spec_folder` from session state (output by both Step 1 and Step 2) to construct a browsable tree URL: `https://github.com/Azure/azure-rest-api-specs/tree/<pre_migration_commit>/<swagger_spec_folder>`. This points to the `resource-manager` folder which exists at the pre-migration commit, unlike the TypeSpec `spec_folder` path.
