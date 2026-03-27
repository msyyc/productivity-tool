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
- **api-version** (optional): e.g., `2020-01-01`. If not provided, auto-detected from `main.tsp` in Step 1.
- **release-type** (optional): `beta` or `stable`. If not provided, inferred from api-version: `beta` if it contains `preview`, otherwise `stable`.

## Workflow

### Step 1: Find Config Path

Run the bundled script to locate the `tspconfig.yaml` for the package:

```
python <skill-dir>/scripts/find_config_path.py <package-name> --spec-dir <spec-repo-path>
```

**Parse the `=== SESSION_STATE ===` block** to extract:
- `config_path` — relative path to `tspconfig.yaml`
- `api_version` — latest API version extracted from `main.tsp` (e.g., `2025-10-01`)

If the user provided an explicit api-version, use that instead of the auto-detected one.

**Store to SQL session state:**

```sql
CREATE TABLE IF NOT EXISTS session_state (key TEXT PRIMARY KEY, value TEXT);
INSERT OR REPLACE INTO session_state (key, value) VALUES
  ('package_name', '<package-name>'),
  ('config_path', '<parsed config_path>'),
  ('api_version', '<user-provided or parsed api_version>');
```

### Step 2: Trigger Pipeline

Trigger the "SDK Generation - Python" pipeline (definitionId=7423) using the helper script:

```python
import subprocess, json, sys
sys.path.insert(0, "<skill-dir>/scripts")
from build_pipeline_command import build_pipeline_command

cmd = build_pipeline_command("<config_path>", "<release_type>", "<api_version>")
result = subprocess.run(cmd, capture_output=True, text=True)
output = json.loads(result.stdout)
```

Alternatively, you may run the equivalent `az` command directly — but each `key=value` after `--parameters` **must** be a separate token:

```
az pipelines run --id 7423 --org https://dev.azure.com/azure-sdk --project internal --branch main `
  --parameters `
    ConfigPath="<config_path>" `
    ConfigType=TypeSpec `
    SdkReleaseType=<release_type> `
    CreatePullRequest=true `
    ApiVersion=<api_version> `
  --output json
```

> **Important:** Do NOT wrap all parameters in a single quoted string — `az pipelines run` would treat the entire string as ConfigPath's value.

- `ConfigType=TypeSpec` is required for TypeSpec-based configs.
- `ApiVersion` is required. Use the user-provided value, or the auto-detected value from Step 1.
- If `release-type` is not provided, infer it from the API version: if the version string contains `preview`, use `beta`; otherwise use `stable`.

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

**If the worktree already exists**, clean it before checkout:

```
cd <worktree_path>
git checkout . && git clean -fd
```

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

### Step 7: Run Live Tests

Run live tests on the SDK package in the worktree. This step uses the bundled `run_live_tests.py` script in two phases.

**Prerequisites:**
- A `.env` file at the work folder root (e.g., `C:/dev/.env`) with these variables:
  ```
  AZURE_TEST_RUN_LIVE=true
  AZURE_TEST_USE_CLI_AUTH=true
  AZURE_SKIP_LIVE_RECORDING=true
  AZURE_TENANT_ID=<your-tenant-id>
  AZURE_SUBSCRIPTION_ID=<your-subscription-id>
  ```

#### Phase 1: Prepare Tests

Run the script with `--prepare-only` to copy and transform generated tests, then stop for review:

```
python <skill-dir>/scripts/run_live_tests.py <package_name> --worktree-dir <worktree_path> --work-dir <work_folder> --prepare-only
```

This will:
1. Locate the SDK package directory under `<worktree_path>/sdk/`
2. Run a pre-flight check: if the CHANGELOG version is `1.0.0b1`, verify the `pyproject.toml` title contains "Mgmt". If it does not, the script fails — report the error and stop. If it does, **ask the user** whether to continue before proceeding.
3. Copy test files from `generated_tests/` to `tests/`:
   - Skip entirely if `*_test.py` files already exist in `tests/`
   - Only copy files that contain `list` method calls
   - Rename to `*_test.py` suffix
   - Apply transformations: `@pytest.mark.skip` → `@pytest.mark.live_test_only`, placeholder comments → `assert result == []`, remove `# ...` lines, strip `api_version=` from `list*()` calls

**Parse the `=== SESSION_STATE ===` block** to extract:
- `sdk_dir` — absolute path to the SDK package directory
- `files_updated` — number of test files copied

**Report to user:** the list of copied/transformed test files. Ask the user to review before continuing.

#### Phase 2: Full Run

After the user confirms, run the script without `--prepare-only`:

```
python <skill-dir>/scripts/run_live_tests.py <package_name> --worktree-dir <worktree_path> --work-dir <work_folder>
```

This will:
1. Repeat the test preparation (idempotent — skips if `*_test.py` already exist)
2. Set up a virtual environment at `<worktree_path>/.venv`:
   - Reuse if it already exists
   - Otherwise create it and install `eng/tools/azure-sdk-tools[ghtools,sdkgenerator]`
   - Always install `azure-mgmt-resource` and `black` (regardless of whether the venv is new or reused)
3. Load environment variables from `<work_folder>/.env`
4. Install `dev_requirements.txt` and the package in editable mode
5. Run `pytest tests`
6. Format `generated_tests/`, `generated_samples/`, and `tests/` with `black -l 120`

**Parse the `=== SESSION_STATE ===` block** to extract:
- `sdk_dir` — absolute path to the SDK package directory
- `files_updated` — number of test files updated (will be `0` if Phase 1 already copied them; use the Phase 1 value for reporting)
- `test_result` — `passed` or `failed`
- `test_summary_path` — path to the generated markdown summary file

**Commit and push:**

```
cd <worktree_path>
git add .
git reset -- <test_summary_path>
git diff --staged --quiet || (git commit -m "Add live tests for <package_name>" && git push)
```

**Post test results as a PR comment:**

Use the generated summary file to comment on the PR:

```
gh pr comment <pr_number> --repo Azure/azure-sdk-for-python --body-file <test_summary_path>
```

The summary file contains a structured markdown report with:
- Overall pass/fail status with emoji
- Pytest summary line (e.g., "3 passed, 1 failed in 5.23s")
- For each failed test: the test name and extracted root cause (exception message and relevant traceback)

**Clean up** the temporary summary file after posting:

```
Remove-Item <test_summary_path>
```

**Report to user:** test results, whether changes were committed, and that the PR comment was posted.

## Rules

- Use `az pipelines` CLI for pipeline operations, `gh` CLI for GitHub operations.
- Always use `--output json` with az CLI commands for reliable parsing.
- Use forward slashes in all file paths passed to scripts.
- If `find_config_path.py` finds multiple matching configs, ask the user which one to use.
- If the pipeline fails, report the build URL and stop — do not proceed to worktree/changelog steps.
- **PR body must be written to a temporary file** and passed via `--body-file` if creating PRs, to avoid shell encoding issues with backtick-escaped sequences.
- When committing changelog changes, push to the PR's source branch so the changes appear on the existing PR.
