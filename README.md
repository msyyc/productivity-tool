# productivity-tool
A repo to collect productivity tool

## timer.ps1
A simple PowerShell timer script for tracking time during tasks.

### Usage
```powershell
# Interactive mode (prompts for minutes and link)
.\timer.ps1

# With command-line parameters 
.\timer.ps1 25 https://github.com/Azure/typespec-azure/pull/3839
```

## clone_github_folder.py
A Python script to clone a specific folder from a GitHub repository using git sparse-checkout. Only the target folder is downloaded, not its parent folders.

### Usage
```bash
# Basic usage
python clone_github_folder.py <github_folder_url>

# With optional output directory
python clone_github_folder.py <github_folder_url> <output_dir>

# Example
python clone_github_folder.py https://github.com/Azure/azure-rest-api-specs/tree/6de816d0d889ec2b769015125e20f0f9aa58db2b/specification/azurefleet/resource-manager/Microsoft.AzureFleet/AzureFleet
```

## http_client_python_release.py
A Python script to automate bumping dependencies and releasing a new version of the http-client-python package in the TypeSpec repository. It handles the full release workflow including dependency updates, version bumping, building, and PR creation.

### Usage
```bash
# Basic usage
python http_client_python_release.py <path_to_typespec_repo>

# Skip PR creation (for testing)
python http_client_python_release.py <path_to_typespec_repo> --skip-pr

# Skip build step (for testing)
python http_client_python_release.py <path_to_typespec_repo> --skip-build

# Example
python http_client_python_release.py C:\dev\typespec
```

### Requirements
- Node.js and npm
- GitHub CLI (`gh`) for PR creation
- Git configured with repository access

## typespec_python_release.py
A Python script to automate bumping the `@typespec/http-client-python` dependency and releasing new versions for the Azure/autorest.python repository. It handles the full release workflow including dependency updates, version bumping, building, and PR creation.

### Usage
```bash
# Basic usage
python typespec_python_release.py <path_to_autorest_python_repo>

# Specify a different base branch
python typespec_python_release.py <path_to_autorest_python_repo> --base-branch feature-branch

# Skip PR creation (for testing)
python typespec_python_release.py <path_to_autorest_python_repo> --skip-pr

# Skip build step (for testing)
python typespec_python_release.py <path_to_autorest_python_repo> --skip-build

# Example
python typespec_python_release.py C:\dev\autorest.python --base-branch my-feature-branch
```

### Requirements
- Node.js and pnpm
- GitHub CLI (`gh`) for PR creation
- Git configured with repository access

## emitter_package_update.py
A Python script to automate bumping `@azure-tools/typespec-python` version in `emitter-package.json` for the Azure SDK for Python repository. It handles the full workflow including version detection, lock file regeneration, and PR creation.

### Usage
```bash
# Basic usage
python emitter_package_update.py <path_to_azure_sdk_for_python_repo>

# Skip PR creation (for testing)
python emitter_package_update.py <path_to_azure_sdk_for_python_repo> --skip-pr

# Specify version manually (skips auto-detection)
python emitter_package_update.py <path_to_azure_sdk_for_python_repo> --version 0.46.4

# Example
python emitter_package_update.py C:\dev\azure-sdk-for-python
```

### Requirements
- Node.js and npm
- `npm-check-updates` (auto-installed if missing)
- `tsp-client` / `@azure-tools/typespec-client-generator-cli` (auto-installed if missing)
- GitHub CLI (`gh`) for PR creation
- Git configured with repository access
