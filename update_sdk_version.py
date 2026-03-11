#!/usr/bin/env python3
"""
Update SDK Version Script

Updates _version.py, CHANGELOG.md, and pyproject.toml for an Azure SDK for Python
package based on a PR link, then commits and pushes to the PR branch.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def run_command(
    cmd: str | list[str], cwd: str | Path | None = None, check: bool = True
) -> subprocess.CompletedProcess:
    """Run a shell command and return the result."""
    if isinstance(cmd, str):
        print(f"  Running: {cmd}")
        result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    else:
        print(f"  Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)

    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr)

    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed with return code {result.returncode}")

    return result


def reset_and_sync(repo_path: Path) -> None:
    """Reset local changes and sync with main branch."""
    print("\n[Step 1] Resetting and syncing with main...")

    run_command("git reset HEAD", cwd=repo_path, check=False)
    run_command("git checkout .", cwd=repo_path)
    run_command("git clean -fd", cwd=repo_path)
    run_command("git checkout origin/main", cwd=repo_path)
    run_command("git pull origin main", cwd=repo_path)


def parse_pr_link(pr_link: str) -> tuple[str, str, int]:
    """Parse a GitHub PR URL into (owner, repo, pr_number)."""
    match = re.match(r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)", pr_link)
    if not match:
        raise ValueError(f"Invalid PR link format: {pr_link}")
    return match.group(1), match.group(2), int(match.group(3))


def checkout_pr(repo_path: Path, pr_link: str, owner: str, repo: str) -> tuple[str, str]:
    """Checkout the PR branch using git checkout. Handles forks by adding fork owner as remote.

    Returns (branch_name, remote_name).
    """
    print(f"\n[Step 2] Checking out PR branch...")

    # Get PR branch info including fork details
    result = run_command(
        f"gh pr view {pr_link} --json headRefName,headRepositoryOwner",
        cwd=repo_path,
    )
    pr_info = json.loads(result.stdout)
    branch = pr_info["headRefName"]
    head_owner = pr_info["headRepositoryOwner"]["login"]

    if head_owner.lower() != owner.lower():
        # PR is from a fork — add fork owner as remote if not already present
        fork_url = f"https://github.com/{head_owner}/{repo}.git"
        remotes_result = run_command("git remote", cwd=repo_path)
        if head_owner not in remotes_result.stdout.strip().splitlines():
            run_command(f"git remote add {head_owner} {fork_url}", cwd=repo_path)
        remote = head_owner
    else:
        remote = "origin"

    run_command(f"git fetch {remote} {branch}", cwd=repo_path)
    run_command(f"git checkout {branch}", cwd=repo_path)

    print(f"  Checked out branch: {branch}")
    return branch, remote


def get_pr_files(repo_path: Path, owner: str, repo: str, pr_number: int) -> list[str]:
    """Get the list of files changed in a PR using gh CLI."""
    print(f"\n[Step 3] Getting files changed in PR #{pr_number}...")

    result = run_command(
        f'gh pr view {pr_number} --repo {owner}/{repo} --json files --jq ".files[].path"',
        cwd=repo_path,
    )
    files = [f.strip() for f in result.stdout.strip().splitlines() if f.strip()]
    if not files:
        raise RuntimeError(f"No files found in PR #{pr_number}")

    print(f"  Found {len(files)} changed files")
    return files


def determine_sdk_folder(files: list[str]) -> str:
    """Determine the SDK package folder from the list of changed files.

    Expects files under sdk/<service>/<package-name>/.
    Errors if multiple distinct package folders are found.
    """
    sdk_folders = set()
    for f in files:
        parts = f.split("/")
        if len(parts) >= 3 and parts[0] == "sdk":
            sdk_folders.add("/".join(parts[:3]))

    if not sdk_folders:
        raise RuntimeError(
            "No SDK package folder found in the changed files. "
            "Expected files under sdk/<service>/<package-name>/."
        )

    if len(sdk_folders) > 1:
        folder_list = "\n  - ".join(sorted(sdk_folders))
        raise RuntimeError(
            f"Multiple SDK folders found in the PR. Please ensure the PR only "
            f"changes one package:\n  - {folder_list}"
        )

    folder = sdk_folders.pop()
    print(f"  SDK folder: {folder}")
    return folder


SKIP_DIRS = {".tox", ".venv", "venv", "dist", "build", "__pycache__", ".eggs", "node_modules", ".git"}


def find_version_file(sdk_folder_path: Path) -> Path:
    """Find the _version.py file inside the SDK package folder, skipping cached/build dirs."""
    version_files = [
        f for f in sdk_folder_path.rglob("_version.py")
        if not (SKIP_DIRS & set(f.relative_to(sdk_folder_path).parts))
    ]
    if not version_files:
        raise RuntimeError(f"No _version.py found under {sdk_folder_path}")
    if len(version_files) > 1:
        filtered = [
            f for f in version_files
            if "test" not in str(f).lower() and "sample" not in str(f).lower()
        ]
        if len(filtered) == 1:
            return filtered[0]
        raise RuntimeError(
            f"Multiple _version.py files found: {[str(f) for f in version_files]}"
        )
    return version_files[0]


def update_version_file(version_file: Path, new_version: str) -> None:
    """Update the VERSION string in _version.py."""
    print(f"\n[Step 5] Updating {version_file.name}...")

    content = version_file.read_text(encoding="utf-8")
    new_content = re.sub(
        r'VERSION\s*=\s*"[^"]*"',
        f'VERSION = "{new_version}"',
        content,
    )

    if content == new_content:
        print(f"  Warning: VERSION string not found or already set to {new_version}")
    else:
        version_file.write_text(new_content, encoding="utf-8")
        print(f"  Updated VERSION to \"{new_version}\"")


def update_changelog(changelog_path: Path, new_version: str) -> None:
    """Update the top version entry in CHANGELOG.md."""
    print(f"\n[Step 6] Updating CHANGELOG.md...")

    if not changelog_path.exists():
        print("  Warning: CHANGELOG.md not found, skipping")
        return

    content = changelog_path.read_text(encoding="utf-8")

    # Match the first ## version header, with either (Unreleased) or a date like (2026-03-11)
    new_content = re.sub(
        r"(## )\S+( \([^)]+\))",
        rf"\g<1>{new_version}\2",
        content,
        count=1,
    )

    if content == new_content:
        print(f"  Warning: Could not find version header to update")
    else:
        changelog_path.write_text(new_content, encoding="utf-8")
        print(f"  Updated version header to \"{new_version}\"")


def update_pyproject_toml(pyproject_path: Path, new_version: str) -> None:
    """Update is_stable and Development Status classifier in pyproject.toml."""
    print(f"\n[Step 7] Updating pyproject.toml...")

    if not pyproject_path.exists():
        print("  Warning: pyproject.toml not found, skipping")
        return

    content = pyproject_path.read_text(encoding="utf-8")
    is_beta = "b" in new_version

    # Update is_stable
    if "is_stable" in content:
        new_stable_value = "false" if is_beta else "true"
        content = re.sub(
            r"(is_stable\s*=\s*)\S+",
            rf"\g<1>{new_stable_value}",
            content,
        )
        print(f"  Set is_stable = {new_stable_value}")

    # Update Development Status classifier
    if "Development Status" in content:
        if is_beta:
            new_status = "Development Status :: 4 - Beta"
        else:
            new_status = "Development Status :: 5 - Production/Stable"

        content = re.sub(
            r'"Development Status :: \d+ - [^"]*"',
            f'"{new_status}"',
            content,
        )
        print(f"  Set classifier to \"{new_status}\"")

    pyproject_path.write_text(content, encoding="utf-8")


def commit_and_push(repo_path: Path, sdk_folder: str, new_version: str, remote: str) -> None:
    """Stage, commit, and push the changes."""
    print(f"\n[Step 8] Committing and pushing changes...")

    run_command(f"git add {sdk_folder}", cwd=repo_path)

    # Check if there are staged changes
    result = run_command("git diff --cached --quiet", cwd=repo_path, check=False)
    if result.returncode == 0:
        print("  No changes to commit")
        return

    package_name = sdk_folder.split("/")[-1]
    commit_msg = f"update {package_name} version to {new_version}"
    run_command(f'git commit -m "{commit_msg}"', cwd=repo_path)

    run_command(f"git push {remote} HEAD", cwd=repo_path)

    print("  Changes pushed successfully")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Update Azure SDK package version based on a PR",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python update_sdk_version.py https://github.com/Azure/azure-sdk-for-python/pull/45605 C:\\dev\\azure-sdk-for-python 1.2.0
  python update_sdk_version.py https://github.com/Azure/azure-sdk-for-python/pull/45605 C:\\dev\\azure-sdk-for-python 1.0.0b1
""",
    )
    parser.add_argument("pr_link", type=str, help="GitHub PR link (e.g., https://github.com/Azure/azure-sdk-for-python/pull/12345)")
    parser.add_argument("repo_path", type=str, help="Path to the local Azure SDK for Python repository")
    parser.add_argument("version", type=str, help="Version number to set (e.g., 1.2.0 or 1.0.0b1)")

    args = parser.parse_args()

    repo_path = Path(args.repo_path).resolve()
    if not repo_path.exists():
        print(f"Error: Repository path does not exist: {repo_path}", file=sys.stderr)
        sys.exit(1)

    owner, repo, pr_number = parse_pr_link(args.pr_link)
    print(f"PR: {owner}/{repo}#{pr_number}")
    print(f"Repository path: {repo_path}")
    print(f"Target version: {args.version}")

    try:
        # Step 1: Reset and sync
        reset_and_sync(repo_path)

        # Step 2: Checkout PR branch (handles forks automatically)
        branch, remote = checkout_pr(repo_path, args.pr_link, owner, repo)

        # Step 3: Get PR changed files and determine SDK folder
        files = get_pr_files(repo_path, owner, repo, pr_number)
        sdk_folder = determine_sdk_folder(files)

        # Step 4: Update _version.py
        sdk_folder_path = repo_path / sdk_folder
        version_file = find_version_file(sdk_folder_path)
        update_version_file(version_file, args.version)

        # Step 5: Update CHANGELOG.md
        changelog_path = sdk_folder_path / "CHANGELOG.md"
        update_changelog(changelog_path, args.version)

        # Step 6: Update pyproject.toml
        pyproject_path = sdk_folder_path / "pyproject.toml"
        update_pyproject_toml(pyproject_path, args.version)

        # Step 7: Commit and push
        commit_and_push(repo_path, sdk_folder, args.version, remote)

        print("\n" + "=" * 50)
        print("Version update completed successfully!")
        print(f"Package: {sdk_folder}")
        print(f"Version: {args.version}")
        print(f"Branch: {branch}")
        print("=" * 50)

    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
