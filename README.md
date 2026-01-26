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

### Features
- Checks and installs npm-check-updates if needed
- Resets and syncs with the main branch
- Creates a dated release branch
- Updates `@typespec/*` and `@azure-tools/*` dependencies
- Updates peerDependencies in package.json
- Runs the version change script
- Builds the package and commits changes
- Pushes the branch and creates a PR via GitHub CLI

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
