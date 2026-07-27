---
name: find-new-spector-case
description: Detect newly published TypeSpec Spector/spec test case changes for the Python emitter, create GitHub issues directly, and report created/skipped issues. Use when the user asks to find new Spector cases, detect spec test changes, or recreate the disabled python-check-spec-tests GitHub Action.
---

# Find New Spector Case

Detect newly published TypeSpec spec test package changes that may need Python emitter test coverage, create GitHub issues for each relevant merged spec PR, then report what was created or skipped.

This replaces the disabled `python-check-spec-tests.yml` workflow behavior with an on-demand skill.

## Prerequisites

- **GitHub CLI (`gh`)** installed and authenticated with permission to read source PRs and create issues in `microsoft/typespec`.
- **Python 3** available on `PATH`.
- Network access to GitHub raw content and the npm registry.

## Default Inputs

- TypeSpec package file: `https://raw.githubusercontent.com/microsoft/typespec/main/packages/http-client-python/package.json`
- npm registry for publish times: `https://pkgs.dev.azure.com/azure-sdk/public/_packaging/azure-sdk-for-js/npm/registry/`
- Issue repo: `microsoft/typespec`
- Test-writing skill URL used in issue bodies: `https://github.com/microsoft/typespec/blob/main/.github/skills/python-sdk-spector-mock-api-tests/SKILL.md`
- Packages checked:
  - `@typespec/http-specs` in `microsoft/typespec`, specs path `packages/http-specs/specs`
  - `@azure-tools/azure-http-specs` in `Azure/typespec-azure`, specs path `packages/azure-http-specs/specs`

## Workflow

Run the bundled script. It creates issues directly by default.

```powershell
$env:PYTHONIOENCODING = 'utf-8'
python <skill-dir>/scripts/find_new_spector_case.py
```

Optional overrides:

```powershell
python <skill-dir>/scripts/find_new_spector_case.py `
  --issue-repo microsoft/typespec `
  --skill-url https://github.com/microsoft/typespec/blob/main/.github/skills/python-sdk-spector-mock-api-tests/SKILL.md `
  --npm-registry https://pkgs.dev.azure.com/azure-sdk/public/_packaging/azure-sdk-for-js/npm/registry/ `
  --limit 200
```

Use `--dry-run` only when the user explicitly asks to preview without creating issues.

## What The Script Does

For each configured spec package:

1. Fetches `packages/http-client-python/package.json` from `microsoft/typespec` `main`.
2. Reads the pinned package version from `devDependencies`.
3. Reads npm publish timestamps from the Azure SDK public npm feed and finds the most recently published version, including prerelease/dev versions.
4. If the latest published version is newer than the pinned version, searches merged PRs in the source repo by merge date.
5. Checks each merged PR's changed files and keeps PRs touching the configured specs path.
6. For each matching PR, checks whether an issue already exists whose title contains the PR URL.
7. Creates a GitHub issue directly when missing:
   - Title: `[python] add test case for <PR URL>`
   - Body: `follow skill <skill-url> to write test case for <PR URL>`
   - Label: `emitter:client:python`
   - Assignee: `copilot-swe-agent[bot]`
   - Agent assignment target repo: `microsoft/typespec`, base branch `main`
8. Prints a markdown summary report to stdout.

## Output

Report the markdown printed on stdout to the user. It includes totals and a table of source PRs with action/status:

```markdown
# New Python Spector Case Issues

Created: 2 issue(s)
Skipped existing: 1 issue(s)

| Package | Source PR | Action | Issue / Reason |
| --- | --- | --- | --- |
```

Progress and diagnostics are printed to stderr.

## Rules

- Always run the bundled script for this workflow; do not manually recreate the GitHub/npm queries step by step.
- By default, create issues directly before reporting, matching the original GitHub Action behavior.
- If `gh` is not authenticated or lacks permissions, stop and tell the user to run `gh auth login` or use a token with issue creation permission.
- If an issue already exists for a source PR, do not create another issue; report it as skipped.
- If the pinned version is already up to date for a package, report that package as skipped/up-to-date.