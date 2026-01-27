#!/usr/bin/env python3
"""
Clone a specific folder from a GitHub repository using git sparse-checkout.
Only the target folder is kept, not its parent folders.

Usage:
    python clone_github_folder.py <github_folder_url>

Example:
    python clone_github_folder.py "https://github.com/Azure/azure-rest-api-specs/tree/6de816d0d889ec2b769015125e20f0f9aa58db2b/specification/azurefleet/resource-manager/Microsoft.AzureFleet/AzureFleet"
"""

import os
import sys
import re
import shutil
import subprocess
import tempfile


def parse_github_url(url):
    """
    Parse GitHub URL to extract owner, repo, ref (branch/commit), and path.
    
    Supports formats:
    - https://github.com/{owner}/{repo}/tree/{ref}/{path}
    - https://github.com/{owner}/{repo}/blob/{ref}/{path}
    """
    pattern = r'https://github\.com/([^/]+)/([^/]+)/(tree|blob)/([^/]+)/(.+)'
    match = re.match(pattern, url)
    
    if not match:
        raise ValueError(f"Invalid GitHub URL format: {url}")
    
    owner = match.group(1)
    repo = match.group(2)
    branch_or_commit = match.group(4)
    path = match.group(5).rstrip('/')
    
    return owner, repo, branch_or_commit, path


def get_folder_name(path):
    """Extract the folder name from the path."""
    return path.rstrip('/').split('/')[-1]


def run_git_command(args, cwd=None, check=True):
    """Run a git command and return the result."""
    result = subprocess.run(
        ['git'] + args,
        cwd=cwd,
        capture_output=True,
        text=True
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"Git command failed: git {' '.join(args)}\n{result.stderr}")
    return result


def clone_github_folder(url, output_dir=None):
    """
    Clone a specific folder from GitHub using git sparse-checkout.
    
    Args:
        url: GitHub URL pointing to a folder
        output_dir: Optional output directory (defaults to current directory)
    """
    print(f"Parsing URL: {url}")
    owner, repo, ref, path = parse_github_url(url)
    
    folder_name = get_folder_name(path)
    repo_url = f"https://github.com/{owner}/{repo}.git"
    
    print(f"Repository: {owner}/{repo}")
    print(f"Ref: {ref}")
    print(f"Path: {path}")
    print(f"Target folder: {folder_name}")
    print()
    
    # Determine destination directory
    if output_dir:
        dest_dir = os.path.abspath(output_dir)
    else:
        dest_dir = os.getcwd()
    
    final_dest = os.path.join(dest_dir, folder_name)
    
    # Check if destination already exists
    if os.path.exists(final_dest):
        print(f"Warning: {final_dest} already exists. Removing...")
        shutil.rmtree(final_dest)
    
    # Create a temporary directory for the sparse checkout
    temp_dir = tempfile.mkdtemp(prefix='github_clone_')
    
    try:
        print(f"Using temporary directory: {temp_dir}")
        print("-" * 50)
        
        # Initialize a new git repository
        print("Initializing git repository...")
        run_git_command(['init'], cwd=temp_dir)
        
        # Add the remote
        print("Adding remote...")
        run_git_command(['remote', 'add', 'origin', repo_url], cwd=temp_dir)
        
        # Enable sparse-checkout
        print("Enabling sparse-checkout...")
        run_git_command(['config', 'core.sparseCheckout', 'true'], cwd=temp_dir)
        
        # Configure sparse-checkout to only include our target path
        print(f"Setting sparse-checkout path: {path}")
        sparse_checkout_file = os.path.join(temp_dir, '.git', 'info', 'sparse-checkout')
        os.makedirs(os.path.dirname(sparse_checkout_file), exist_ok=True)
        with open(sparse_checkout_file, 'w') as f:
            f.write(f"{path}\n")
        
        # Fetch only the specific ref with depth 1 (shallow clone)
        print(f"Fetching ref: {ref} (shallow clone)...")
        run_git_command(['fetch', '--depth', '1', 'origin', ref], cwd=temp_dir)
        
        # Checkout the fetched ref
        print("Checking out files...")
        run_git_command(['checkout', 'FETCH_HEAD'], cwd=temp_dir)
        
        print("-" * 50)
        
        # Move the target folder to the destination
        source_path = os.path.join(temp_dir, path)
        
        if not os.path.exists(source_path):
            raise RuntimeError(f"Target folder not found: {source_path}")
        
        print(f"Moving {folder_name} to {dest_dir}...")
        shutil.move(source_path, final_dest)
        
        print("-" * 50)
        print(f"Successfully cloned '{folder_name}' to {final_dest}")
        
        # Update tspconfig.yaml if it exists
        from pathlib import Path
        tspconfig_path = Path(final_dest) / "tspconfig.yaml"
        if tspconfig_path.exists():
            content = tspconfig_path.read_text(encoding="utf-8")
            content = content.replace("@azure-tools/typespec-python", "@typespec/http-client-python")
            tspconfig_path.write_text(content, encoding="utf-8")
            print(f"Updated {tspconfig_path}")
        
        print(" === Run the following command to compile the typespec file: === ")
        print(f"tsp compile {final_dest}/client.tsp --emit @typespec/http-client-python --config {final_dest}/tspconfig.yaml")
        
        return True
        
    except Exception as e:
        print(f"Error: {e}")
        return False
        
    finally:
        # Clean up temporary directory
        print("Cleaning up temporary files...")
        try:
            shutil.rmtree(temp_dir)
        except Exception:
            pass


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("Error: Please provide a GitHub folder URL")
        sys.exit(1)
    
    url = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else None
    
    try:
        success = clone_github_folder(url, output_dir)
        sys.exit(0 if success else 1)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
