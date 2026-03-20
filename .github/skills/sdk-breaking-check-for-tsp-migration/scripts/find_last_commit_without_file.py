"""
Find the last commit where tspconfig.yaml did NOT exist for a given Python SDK package.

Usage:
    python find_last_commit_without_file.py <package-name> --spec-dir <spec-worktree>
    python find_last_commit_without_file.py azure-mgmt-securityinsights --spec-dir /workspaces/worktrees/spec-azure-mgmt-securityinsights

Uses local git commands on the spec worktree — no network access needed.
"""

import argparse
import os
import subprocess
import sys


OWNER = "Azure"
REPO = "azure-rest-api-specs"


def git_cmd(args: list[str], cwd: str) -> str:
    result = subprocess.run(
        ["git"] + args, capture_output=True, text=True, cwd=cwd
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def extract_search_keyword(package_name: str) -> str:
    """Strip common prefixes to get a search-friendly keyword."""
    name = package_name.lower()
    for prefix in ("azure-mgmt-", "azure-"):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return name


def find_tspconfig_path(package_name: str, spec_dir: str) -> str | None:
    """Search the local spec repo for a tspconfig.yaml matching the given package name."""
    keyword = extract_search_keyword(package_name)

    # List all tspconfig.yaml files under specification/
    all_files = git_cmd(["ls-files", "specification/**/tspconfig.yaml"], cwd=spec_dir)
    if not all_files:
        print(f"No tspconfig.yaml found in specification/")
        return None

    candidates = [f for f in all_files.splitlines() if keyword in f.lower()]
    if not candidates:
        print(f"No tspconfig.yaml found matching keyword '{keyword}'")
        return None

    if len(candidates) == 1:
        print(f"Found tspconfig.yaml: {candidates[0]}")
        return candidates[0]

    # Multiple matches — check file content for the package name
    print(f"Found {len(candidates)} tspconfig.yaml candidates, checking Python emitter config...")
    for path in candidates:
        try:
            full_path = os.path.join(spec_dir, path)
            content = open(full_path, encoding="utf-8").read()
            if package_name.lower() in content.lower():
                print(f"  Matched: {path}")
                return path
        except Exception as e:
            print(f"  Warning: Failed to check {path}: {e}")
            continue

    # Fallback: match with keyword
    for path in candidates:
        try:
            full_path = os.path.join(spec_dir, path)
            content = open(full_path, encoding="utf-8").read()
            if keyword in content.lower():
                print(f"  Keyword-matched: {path}")
                return path
        except Exception as e:
            print(f"  Warning: Failed to check {path}: {e}")
            continue

    print("Could not find a matching tspconfig.yaml")
    return None


def find_first_commit_with_file(file_path: str, spec_dir: str) -> tuple[str, str, str] | None:
    """Return (sha, date, message) of the earliest commit that introduced the file."""
    # --diff-filter=A finds only commits that Added the file; --reverse gives oldest first
    output = git_cmd(
        ["log", "--diff-filter=A", "--reverse", "--format=%H%n%aI%n%s", "--", file_path],
        cwd=spec_dir,
    )
    if not output:
        print(f"No commits found that added {file_path}")
        return None
    lines = output.splitlines()
    return lines[0], lines[1], lines[2]


def get_parent_commit(sha: str, spec_dir: str) -> str | None:
    """Return the first parent SHA of a given commit."""
    try:
        return git_cmd(["rev-parse", f"{sha}^"], cwd=spec_dir)
    except RuntimeError:
        return None


def get_commit_info(sha: str, spec_dir: str) -> tuple[str, str]:
    """Return (date, message) for a commit."""
    output = git_cmd(["log", "-1", "--format=%aI%n%s", sha], cwd=spec_dir)
    lines = output.splitlines()
    return lines[0], lines[1]


def main():
    parser = argparse.ArgumentParser(description="Find last commit without tspconfig.yaml for a package")
    parser.add_argument("package_name", help="Full package name (e.g. azure-mgmt-securityinsights)")
    parser.add_argument("--spec-dir", required=True, help="Path to the spec repo worktree")
    args = parser.parse_args()

    spec_dir = os.path.abspath(args.spec_dir)
    package_name = args.package_name
    print(f"Package: {package_name}")
    print(f"Spec dir: {spec_dir}\n")

    # Step 1: Find the tspconfig.yaml path
    file_path = find_tspconfig_path(package_name, spec_dir)
    if not file_path:
        sys.exit(1)

    # Step 2: Find the first commit that introduced the file
    print(f"\nSearching for the first commit that introduced:\n  {file_path}\n")
    result = find_first_commit_with_file(file_path, spec_dir)
    if not result:
        sys.exit(1)

    sha, date, message = result
    print(f"First commit with the file:")
    print(f"  SHA:     {sha}")
    print(f"  Date:    {date}")
    print(f"  Message: {message}\n")

    # Step 3: Get the parent commit (last commit without the file)
    parent_sha = get_parent_commit(sha, spec_dir)
    if not parent_sha:
        print("The file was introduced in the very first commit — no parent exists.")
        sys.exit(1)

    p_date, p_message = get_commit_info(parent_sha, spec_dir)
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
