#!/usr/bin/env python3
"""
Clone a specific folder from a GitHub repository.
Only the target folder is kept, not its parent folders.

Usage:
    python clone_github_folder.py <github_folder_url>

Example:
    python clone_github_folder.py "https://github.com/Azure/azure-rest-api-specs/tree/6de816d0d889ec2b769015125e20f0f9aa58db2b/specification/azurefleet/resource-manager/Microsoft.AzureFleet/AzureFleet"
"""

import os
import sys
import re
import urllib.request
import json
import base64
from urllib.error import HTTPError


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
    ref = match.group(3)  # 'tree' or 'blob'
    branch_or_commit = match.group(4)
    path = match.group(5).rstrip('/')
    
    return owner, repo, branch_or_commit, path


def get_folder_name(path):
    """Extract the folder name from the path."""
    return path.rstrip('/').split('/')[-1]


def fetch_github_api(url):
    """Fetch data from GitHub API."""
    request = urllib.request.Request(url)
    request.add_header('Accept', 'application/vnd.github.v3+json')
    request.add_header('User-Agent', 'Python-GitHub-Folder-Clone')
    
    # Add token if available for higher rate limits
    token = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
    if token:
        request.add_header('Authorization', f'token {token}')
    
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode('utf-8'))
    except HTTPError as e:
        if e.code == 403:
            print("Error: GitHub API rate limit exceeded. Set GITHUB_TOKEN environment variable for higher limits.")
        elif e.code == 404:
            print(f"Error: Resource not found at {url}")
        else:
            print(f"Error: HTTP {e.code} - {e.reason}")
        raise


def download_file(url, dest_path):
    """Download a file from URL to destination path."""
    request = urllib.request.Request(url)
    request.add_header('User-Agent', 'Python-GitHub-Folder-Clone')
    
    token = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
    if token:
        request.add_header('Authorization', f'token {token}')
    
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    
    with urllib.request.urlopen(request) as response:
        with open(dest_path, 'wb') as f:
            f.write(response.read())


def clone_folder_recursive(owner, repo, ref, path, dest_dir, base_path):
    """
    Recursively clone a folder from GitHub.
    
    Args:
        owner: Repository owner
        repo: Repository name
        ref: Branch or commit SHA
        path: Path in the repository
        dest_dir: Local destination directory
        base_path: The original requested path (to calculate relative paths)
    """
    api_url = f'https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={ref}'
    
    try:
        contents = fetch_github_api(api_url)
    except HTTPError:
        return False
    
    if not isinstance(contents, list):
        contents = [contents]
    
    for item in contents:
        item_path = item['path']
        # Calculate relative path from the base folder
        relative_path = item_path[len(base_path):].lstrip('/')
        local_path = os.path.join(dest_dir, relative_path) if relative_path else dest_dir
        
        if item['type'] == 'dir':
            os.makedirs(local_path, exist_ok=True)
            print(f"Creating directory: {relative_path or get_folder_name(base_path)}/")
            clone_folder_recursive(owner, repo, ref, item_path, dest_dir, base_path)
        elif item['type'] == 'file':
            print(f"Downloading: {relative_path}")
            download_url = item['download_url']
            if download_url:
                download_file(download_url, local_path)
            else:
                # For large files, use the API to get content
                file_data = fetch_github_api(item['url'])
                content = base64.b64decode(file_data['content'])
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                with open(local_path, 'wb') as f:
                    f.write(content)
    
    return True


def clone_github_folder(url, output_dir=None):
    """
    Clone a specific folder from GitHub.
    
    Args:
        url: GitHub URL pointing to a folder
        output_dir: Optional output directory (defaults to current directory)
    """
    print(f"Parsing URL: {url}")
    owner, repo, ref, path = parse_github_url(url)
    
    folder_name = get_folder_name(path)
    print(f"Repository: {owner}/{repo}")
    print(f"Ref: {ref}")
    print(f"Path: {path}")
    print(f"Target folder: {folder_name}")
    print()
    
    # Determine destination directory
    if output_dir:
        dest_dir = os.path.join(output_dir, folder_name)
    else:
        dest_dir = os.path.join(os.getcwd(), folder_name)
    
    # Create destination directory
    os.makedirs(dest_dir, exist_ok=True)
    print(f"Cloning to: {dest_dir}")
    print("-" * 50)
    
    # Clone the folder
    success = clone_folder_recursive(owner, repo, ref, path, dest_dir, path)
    
    if success:
        print("-" * 50)
        print(f"Successfully cloned '{folder_name}' to {dest_dir}")
    else:
        print("Failed to clone folder")
        return False
    
    return True


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("Error: Please provide a GitHub folder URL")
        sys.exit(1)
    
    url = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else None
    
    try:
        clone_github_folder(url, output_dir)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
