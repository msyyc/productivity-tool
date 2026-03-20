"""
Find the last commit where tspconfig.yaml did NOT exist for a given Python SDK package.

Usage:
    python find_last_commit_without_file.py <package-name>
    python find_last_commit_without_file.py azure-mgmt-securityinsights

Uses `gh api` to query the GitHub API — no local clone needed.
"""

import argparse
import base64
import subprocess
import json
import sys
import re
import urllib.parse


OWNER = "Azure"
REPO = "azure-rest-api-specs"


def gh_api(endpoint: str, paginate: bool = False) -> dict | list:
    cmd = ["gh", "api", endpoint]
    if paginate:
        cmd.append("--paginate")
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    raw = result.stdout.strip()
    if paginate and raw.startswith("["):
        # --paginate may concatenate multiple JSON arrays; merge them
        raw = raw.replace("]\n[", ",").replace("][", ",")
    return json.loads(raw)


def extract_search_keyword(package_name: str) -> str:
    """Strip common prefixes to get a search-friendly keyword."""
    name = package_name.lower()
    for prefix in ("azure-mgmt-", "azure-"):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return name


def find_tspconfig_path(package_name: str) -> str | None:
    """Search the spec repo for a tspconfig.yaml matching the given package name."""
    keyword = extract_search_keyword(package_name)
    query = urllib.parse.quote(f"{keyword} filename:tspconfig.yaml path:specification repo:{OWNER}/{REPO}")
    endpoint = f"/search/code?q={query}&per_page=20"
    results = gh_api(endpoint)

    items = results.get("items", [])
    if not items:
        print(f"No tspconfig.yaml found matching keyword '{keyword}'")
        return None

    if len(items) == 1:
        path = items[0]["path"]
        print(f"Found tspconfig.yaml: {path}")
        return path

    # Multiple matches — fetch each and check for the package name in Python emitter config
    print(f"Found {len(items)} tspconfig.yaml candidates, checking Python emitter config...")
    for item in items:
        path = item["path"]
        try:
            content_endpoint = f"/repos/{OWNER}/{REPO}/contents/{urllib.parse.quote(path, safe='/')}"
            file_info = gh_api(content_endpoint)
            content = base64.b64decode(file_info["content"]).decode("utf-8")
            if package_name.lower() in content.lower():
                print(f"  Matched: {path}")
                return path
        except Exception as e:
            print(f"  Warning: Failed to check {path}: {e}")
            continue

    # Fallback: if no exact match, try matching with the keyword
    for item in items:
        path = item["path"]
        try:
            content_endpoint = f"/repos/{OWNER}/{REPO}/contents/{urllib.parse.quote(path, safe='/')}"
            file_info = gh_api(content_endpoint)
            content = base64.b64decode(file_info["content"]).decode("utf-8")
            if keyword in content.lower():
                print(f"  Keyword-matched: {path}")
                return path
        except Exception as e:
            print(f"  Warning: Failed to check {path}: {e}")
            continue

    print("Could not find a matching tspconfig.yaml")
    return None


def find_first_commit_with_file(file_path: str) -> dict | None:
    """Return the earliest commit that touched the file."""
    endpoint = f"/repos/{OWNER}/{REPO}/commits?path={urllib.parse.quote(file_path, safe='/')}&per_page=100"
    commits = gh_api(endpoint, paginate=True)
    if not commits:
        print(f"No commits found that touch {file_path}")
        return None
    # GitHub returns newest-first; the last element is the earliest commit
    return commits[-1]


def get_parent_commit(sha: str) -> str | None:
    """Return the first parent SHA of a given commit."""
    endpoint = f"/repos/{OWNER}/{REPO}/commits/{sha}"
    commit = gh_api(endpoint)
    parents = commit.get("parents", [])
    if parents:
        return parents[0]["sha"]
    return None


def check_tool(name):
    """Check if a command-line tool is available."""
    result = subprocess.run(f"{name} --version", shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error: '{name}' is not installed or not in PATH")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Find last commit without tspconfig.yaml for a package")
    parser.add_argument("package_name", help="Full package name (e.g. azure-mgmt-securityinsights)")
    args = parser.parse_args()

    check_tool("gh")

    package_name = args.package_name
    print(f"Package: {package_name}\n")

    # Step 1: Find the tspconfig.yaml path
    file_path = find_tspconfig_path(package_name)
    if not file_path:
        sys.exit(1)

    # Step 2: Find the first commit that introduced the file
    print(f"\nSearching for the first commit that introduced:\n  {file_path}\n")
    first_commit = find_first_commit_with_file(file_path)
    if not first_commit:
        sys.exit(1)

    sha = first_commit["sha"]
    message = first_commit["commit"]["message"].split("\n")[0]
    date = first_commit["commit"]["committer"]["date"]
    print(f"First commit with the file:")
    print(f"  SHA:     {sha}")
    print(f"  Date:    {date}")
    print(f"  Message: {message}\n")

    # Step 3: Get the parent commit (last commit without the file)
    parent_sha = get_parent_commit(sha)
    if not parent_sha:
        print("The file was introduced in the very first commit — no parent exists.")
        sys.exit(1)

    parent = gh_api(f"/repos/{OWNER}/{REPO}/commits/{parent_sha}")
    p_message = parent["commit"]["message"].split("\n", 1)[0]
    p_date = parent["commit"]["committer"]["date"]
    print(f"Last commit WITHOUT the file (parent of above):")
    print(f"  SHA:     {parent_sha}")
    print(f"  Date:    {p_date}")
    print(f"  Message: {p_message}")
    folder_path = file_path.rsplit("/", 1)[0] if "/" in file_path else file_path
    print(f"\n  Commit URL: https://github.com/{OWNER}/{REPO}/commit/{parent_sha}")
    print(f"  Folder URL: https://github.com/{OWNER}/{REPO}/tree/{parent_sha}/{folder_path}")

    # Output for session state parsing
    print("\n" + "=" * 60)
    print("=== SESSION_STATE ===")
    print(f"tspconfig_path={file_path}")
    print(f"pre_migration_commit={parent_sha}")
    print(f"spec_folder={folder_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
