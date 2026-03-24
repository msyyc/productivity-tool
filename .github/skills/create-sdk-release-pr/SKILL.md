---
name: create-sdk-release-pr
description: Use when the user wants to trigger the SDK generation pipeline for a Python SDK package, poll for the generated PR, checkout it in a git worktree, and optimize the changelog before committing.
---

# Create SDK Release PR

Trigger the Azure DevOps "SDK Generation - Python" pipeline for a package, wait for the generated PR, then checkout and optimize its changelog in a git worktree.

## Prerequisites

- **Azure CLI** installed and authenticated (`az login`)
- `azure-rest-api-specs` and `azure-sdk-for-python` repos cloned under the work folder (default: `C:/dev`)
- User should run this skill from the `azure-rest-api-specs` repo directory

## Input

- **SDK package name** (required): e.g., `azure-mgmt-frontdoor`
- **api-version** (optional): e.g., `2020-01-01`
- **release-type** (optional): `beta` or `stable` (default: `beta`)

## Workflow

### Step 1: Find Config Path

Run the bundled script to locate the `tspconfig.yaml` for the package:

```
python <skill-dir>/scripts/find_config_path.py <package-name> --spec-dir <spec-repo-path>
```

**Parse the `=== SESSION_STATE ===` block** to extract `config_path`.

**Store to SQL session state:**

```sql
CREATE TABLE IF NOT EXISTS session_state (key TEXT PRIMARY KEY, value TEXT);
INSERT OR REPLACE INTO session_state (key, value) VALUES
  ('package_name', '<package-name>'),
  ('config_path', '<parsed config_path>');
```

### Step 2: Trigger Pipeline

Trigger the "SDK Generation - Python" pipeline (definitionId=7423):

```
az pipelines run --id 7423 --org https://dev.azure.com/azure-sdk --project internal --branch main --parameters ConfigPath=<config_path> SdkReleaseType=<release_type> CreatePullRequest=true ApiVersion=<api_version> --output json
```

- If `api-version` is not provided, omit the `ApiVersion=` parameter entirely.
- If `release-type` is not provided, default to `beta`.

**Parse the JSON output** to extract:
- `id` — the build ID
- `url` or construct the build link: `https://dev.azure.com/azure-sdk/internal/_build/results?buildId=<id>&view=results`

**Store to SQL session state:**

```sql
INSERT OR REPLACE INTO session_state (key, value) VALUES
  ('build_id', '<build_id>'),
  ('build_url', '<build_url>');
```

**Report to user:** the pipeline link.

### Step 3: Poll Pipeline

Poll the pipeline every **2 minutes** until it completes:

```
az pipelines runs show --id <build_id> --org https://dev.azure.com/azure-sdk --project internal --query "{status:status, result:result}" --output json
```

- `status == "completed"` means the build finished.
- `result == "succeeded"` means success — proceed to Step 4.
- `result == "failed"` or `"canceled"` — report the failure and stop.

Use `Start-Sleep -Seconds 120` between polls.

### Step 4: Get SDK PR

Search for the generated PR using the build ID:

```
gh pr list --repo Azure/azure-sdk-for-python --search "SDK Generation - Python-<build_id>" --json number,title,url --limit 5 --state all
```

If no result, try searching by package name:

```
gh pr list --repo Azure/azure-sdk-for-python --search "[AutoPR <package_name>]" --json number,title,url --limit 5 --state all
```

**Parse** the PR number and URL.

**Store to SQL session state:**

```sql
INSERT OR REPLACE INTO session_state (key, value) VALUES
  ('pr_number', '<pr_number>'),
  ('pr_url', '<pr_url>');
```

**Report to user:** the SDK PR link.

### Step 5: Create Worktree and Checkout PR

Determine the work folder (default `C:/dev`) and worktree path:

```
worktree_path = <work_folder>/worktrees/sdk-<package_name>
```

**Create the worktree** if it doesn't exist:

```
cd <work_folder>/azure-sdk-for-python
git fetch origin main
git worktree add -B sdk-<package_name> <worktree_path> origin/main
```

If the worktree already exists, skip creation.

**Checkout the SDK PR** in the worktree:

```
cd <worktree_path>
gh pr checkout <pr_number> --repo Azure/azure-sdk-for-python
```

**Store to SQL session state:**

```sql
INSERT OR REPLACE INTO session_state (key, value) VALUES
  ('worktree_path', '<worktree_path>');
```

### Step 6: Update Changelog

1. **Find the CHANGELOG.md** in the SDK package directory. The path is typically:
   ```
   <worktree_path>/sdk/<service-dir>/<package_name>/CHANGELOG.md
   ```
   Search for it if the exact path is unknown:
   ```
   Get-ChildItem -Path <worktree_path> -Recurse -Filter CHANGELOG.md | Where-Object { $_.FullName -like "*<package_name>*" }
   ```

2. **Read only the latest version section** of the CHANGELOG.md (everything from the first `## ` heading to the next `## ` heading).

3. **Apply the optimization rules** from [references/changelog-optimization.md](references/changelog-optimization.md). Read that file for the full set of 9 rules covering:
   - Operation group naming
   - Parameter default value changes
   - Entries to remove (overloads, internal properties)
   - Parameter renaming
   - Grouping moved instance variables
   - Hybrid model migration note
   - Hybrid operation migration note
   - Consolidating unused list models
   - Grouping parameter kind changes

4. **Write the updated CHANGELOG.md** using the edit tool.

5. **Commit and push:**
   ```
   cd <worktree_path>
   git add .
   git commit -m "Optimize changelog for <package_name>"
   git push
   ```

**Report to user:** summary of changelog changes made.

## Rules

- Use `az pipelines` CLI for pipeline operations, `gh` CLI for GitHub operations.
- Always use `--output json` with az CLI commands for reliable parsing.
- Use forward slashes in all file paths passed to scripts.
- If `find_config_path.py` finds multiple matching configs, ask the user which one to use.
- If the pipeline fails, report the build URL and stop — do not proceed to worktree/changelog steps.
- **PR body must be written to a temporary file** and passed via `--body-file` if creating PRs, to avoid shell encoding issues with backtick-escaped sequences.
- When committing changelog changes, push to the PR's source branch so the changes appear on the existing PR.
