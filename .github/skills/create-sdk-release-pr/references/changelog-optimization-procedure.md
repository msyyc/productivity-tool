# Changelog Optimization Subagent Procedure

Reusable subagent procedure for applying [changelog-optimization.md](changelog-optimization.md) rules to a Python SDK package's `CHANGELOG.md`. Used by skills that have already produced a generated changelog and want to clean it up before (or after) PR creation.

## Why a subagent

This work is independent of the rest of the calling skill's workflow and benefits from a focused context (the changelog text + the rules doc + the package's `_models.py`). Delegate it.

## Inputs (callers must supply)

- `package_name` — SDK package name (e.g., `azure-mgmt-securityinsights`).
- `worktree_path` — absolute path to the SDK repo or worktree containing `CHANGELOG.md`.
- `changelog_path` — absolute path to the `CHANGELOG.md` (optional; subagent can search if unknown).
- `commit_message` — commit message for the optimization patch.
- `push_target` — exact `git push` invocation the subagent must run (e.g., `git push` for a tracked branch, or `git push <fork> HEAD` for a fork-based PR branch).
- `skip_rules` *(optional)* — list of rule numbers from `changelog-optimization.md` to skip (e.g., when an earlier step has already applied a specific rule).

## Subagent prompt template

Fill in placeholders from session state and launch the subagent with this prompt:

> You are optimizing the CHANGELOG.md for the Python SDK package `<package_name>`.
>
> **Worktree path:** `<worktree_path>`
>
> **Instructions:**
>
> 1. **Find the CHANGELOG.md** in the SDK package directory. If `<changelog_path>` is provided, use it directly. Otherwise the path is typically:
>    ```
>    <worktree_path>/sdk/<service-dir>/<package_name>/CHANGELOG.md
>    ```
>    Search if unknown:
>    ```
>    Get-ChildItem -Path <worktree_path> -Recurse -Filter CHANGELOG.md | Where-Object { $_.FullName -like "*<package_name>*" }
>    ```
>
> 2. **Read only the latest version section** of the CHANGELOG.md (everything from the first `## ` heading to the next `## ` heading).
>
> 3. **Read the optimization rules** from `<rules-doc-path>` (the absolute path to `create-sdk-release-pr/references/changelog-optimization.md`) and apply ALL rules to the latest version section, EXCEPT the rules listed in `<skip_rules>` (if any). The rules cover:
>    - Operation group naming corrections
>    - Parameter default value changes
>    - Entries to remove (overloads, internal properties)
>    - Parameter renaming
>    - Renaming of properties that conflict with base model methods
>    - Grouping moved instance variables under a new container property (requires reading `_models.py` in the package to identify container types)
>    - Hybrid model migration note
>    - Hybrid operation migration note
>    - Consolidating unused list models
>    - Grouping parameter kind changes
>    - Consolidating renames and combined enums (rule 11)
>
> 4. **Write the updated CHANGELOG.md** using the edit tool.
>
> 5. **Commit and push:**
>    ```
>    cd <worktree_path>
>    git add <changelog-path>
>    git commit -m "<commit_message>"
>    <push_target>
>    ```
>
> 6. **Return** a summary of all changelog changes made (which rules were applied and what was changed). If no changes were needed, say so.

## Caller responsibilities

After the subagent returns:

- Surface the subagent's summary to the user.
- Decide whether to proceed with subsequent workflow steps based on the summary.
