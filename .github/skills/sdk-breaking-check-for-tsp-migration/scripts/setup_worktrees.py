"""
Set up git worktrees for spec repo and SDK repo for a given package.

Usage:
    python setup_worktrees.py <package-name> [--base-dir <dir>] [--worktrees-dir <dir>]

Example:
    python setup_worktrees.py azure-mgmt-securityinsights --base-dir C:/dev --worktrees-dir C:/dev/worktrees
"""

import argparse
import json
import os
import subprocess
import sys


def run_cmd(cmd, cwd=None, check=True):
    """Run a shell command, print it, and return the result."""
    print(f"\n  $ {cmd}")
    result = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        for line in result.stderr.strip().split("\n"):
            print(f"  [stderr] {line}")
    if check and result.returncode != 0:
        print(f"\nError: Command failed with exit code {result.returncode}")
        sys.exit(1)
    return result


def get_github_username():
    """Get the authenticated GitHub username via gh CLI."""
    result = run_cmd("gh api user --jq .login")
    return result.stdout.strip()


def ensure_fork_and_remote(repo_dir, worktree_dir, upstream_owner, repo_name, username):
    """Ensure the user has a fork and the worktree has a remote pointing to it."""
    fork_url = f"https://github.com/{username}/{repo_name}.git"

    # Check if fork exists
    check = run_cmd(f"gh api repos/{username}/{repo_name} --jq .full_name", check=False)
    if check.returncode != 0:
        print(f"Fork not found. Creating fork of {upstream_owner}/{repo_name}...")
        run_cmd(f"gh repo fork {upstream_owner}/{repo_name} --clone=false")

    # Add remote to worktree (worktrees share remotes with main repo, so add to main)
    existing = run_cmd(f"git remote get-url {username}", cwd=repo_dir, check=False)
    if existing.returncode != 0:
        print(f"Adding remote '{username}' -> {fork_url}")
        run_cmd(f"git remote add {username} {fork_url}", cwd=repo_dir)
    else:
        print(f"Remote '{username}' already exists: {existing.stdout.strip()}")

    return username


def main():
    parser = argparse.ArgumentParser(description="Set up git worktrees for migration check")
    parser.add_argument("package_name", help="Full package name (e.g. azure-mgmt-securityinsights)")
    parser.add_argument("--base-dir", default="C:/dev",
                        help="Parent dir containing azure-rest-api-specs and azure-sdk-for-python")
    parser.add_argument("--worktrees-dir", default="C:/dev/worktrees",
                        help="Directory to create worktrees in")
    args = parser.parse_args()

    package_name = args.package_name
    base_dir = os.path.abspath(args.base_dir)
    worktrees_dir = os.path.abspath(args.worktrees_dir)

    spec_repo = os.path.join(base_dir, "azure-rest-api-specs")
    sdk_repo = os.path.join(base_dir, "azure-sdk-for-python")

    for path, label in [
        (spec_repo, "REST repo"),
        (sdk_repo, "SDK repo"),
    ]:
        if not os.path.isdir(path):
            print(f"Error: {label} not found at {path}")
            sys.exit(1)

    spec_branch = f"spec-{package_name}"
    sdk_branch = f"sdk-{package_name}"
    spec_worktree = os.path.join(worktrees_dir, spec_branch)
    sdk_worktree = os.path.join(worktrees_dir, sdk_branch)

    print(f"Package:         {package_name}")
    print(f"Spec repo:       {spec_repo}")
    print(f"SDK repo:        {sdk_repo}")
    print(f"Worktrees dir:   {worktrees_dir}")
    print(f"Spec worktree:   {spec_worktree}")
    print(f"SDK worktree:    {sdk_worktree}")

    # 0. Detect GitHub username and ensure forks exist
    print("\n" + "=" * 60)
    print("Step 0: Detect GitHub user and ensure forks")
    print("=" * 60)
    username = get_github_username()
    print(f"GitHub user: {username}")

    ensure_fork_and_remote(spec_repo, spec_worktree, "Azure", "azure-rest-api-specs", username)
    ensure_fork_and_remote(sdk_repo, sdk_worktree, "Azure", "azure-sdk-for-python", username)

    # Ensure worktrees directory exists
    os.makedirs(worktrees_dir, exist_ok=True)

    # 1. Create spec worktree
    print("\n" + "=" * 60)
    print("Step 1: Create spec repo worktree")
    print("=" * 60)
    if os.path.isdir(spec_worktree):
        print(f"Worktree already exists at {spec_worktree}, removing...")
        run_cmd(f'git worktree remove "{spec_worktree}" --force', cwd=spec_repo)

    run_cmd("git fetch origin main", cwd=spec_repo)
    run_cmd(
        f'git worktree add -B {spec_branch} "{spec_worktree}" origin/main',
        cwd=spec_repo,
    )

    # 2. Create SDK worktree
    print("\n" + "=" * 60)
    print("Step 2: Create SDK repo worktree")
    print("=" * 60)
    if os.path.isdir(sdk_worktree):
        print(f"Worktree already exists at {sdk_worktree}, removing...")
        run_cmd(f'git worktree remove "{sdk_worktree}" --force', cwd=sdk_repo)

    run_cmd("git fetch origin main", cwd=sdk_repo)
    run_cmd(
        f'git worktree add -B {sdk_branch} "{sdk_worktree}" origin/main',
        cwd=sdk_repo,
    )

    # 3. Set up venv in SDK worktree
    print("\n" + "=" * 60)
    print("Step 3: Set up virtual environment in SDK worktree")
    print("=" * 60)
    venv_path = os.path.join(sdk_worktree, ".venv")
    if os.path.isdir(venv_path):
        print("Virtual environment already exists, skipping creation")
    else:
        run_cmd(f'python -m venv "{venv_path}"', cwd=sdk_worktree)

    activate = os.path.join(venv_path, "Scripts", "activate.bat")
    run_cmd(
        f'call "{activate}" && pip install -e tools/azure-sdk-tools',
        cwd=sdk_worktree,
    )

    # Output for session state parsing
    print("\n" + "=" * 60)
    print("=== SESSION_STATE ===")
    print(f"spec_worktree={spec_worktree.replace(os.sep, '/')}")
    print(f"sdk_worktree={sdk_worktree.replace(os.sep, '/')}")
    print(f"spec_branch={spec_branch}")
    print(f"sdk_branch={sdk_branch}")
    print(f"github_username={username}")
    print("=" * 60)
    print("\nDone! Worktrees created and ready.")


if __name__ == "__main__":
    main()
