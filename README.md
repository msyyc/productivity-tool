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
