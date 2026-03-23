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
    result = subprocess.run(["git"] + args, capture_output=True, text=True, cwd=cwd)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def extract_search_keyword(package_name: str) -> str:
    """Strip common prefixes to get a search-friendly keyword."""
    name = package_name.lower()
    for prefix in ("azure-mgmt-", "azure-"):
        if name.startswith(prefix):
            name = name[len(prefix) :]
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


def derive_service_spec_folder(tspconfig_path: str) -> str:
    """Extract the top-level specification folder (e.g., specification/frontdoor)."""
    parts = tspconfig_path.replace("\\", "/").split("/")
    return f"{parts[0]}/{parts[1]}"


def find_earliest_tspconfig_commit(spec_folder: str, spec_dir: str) -> tuple[str, str, str, str] | None:
    """Find the earliest commit adding any tspconfig.yaml under the spec folder.

    Searches git history for ALL tspconfig.yaml paths ever committed under the
    service folder (including paths that were later renamed/moved), then returns
    the earliest addition.

    Returns (sha, date, message, file_path) or None.
    """
    try:
        output = git_cmd(
            [
                "log",
                "--diff-filter=A",
                "--name-only",
                "--format=",
                "--",
                f"{spec_folder}/**/tspconfig.yaml",
                f"{spec_folder}/*/tspconfig.yaml",
            ],
            cwd=spec_dir,
        )
    except RuntimeError:
        return None

    if not output:
        return None

    paths = sorted(set(line.strip() for line in output.splitlines() if line.strip()))
    if not paths:
        return None

    print(f"  Found {len(paths)} historical tspconfig.yaml path(s):")
    for p in paths:
        print(f"    {p}")

    # For each path, find the earliest commit that added it
    earliest = None
    for path in paths:
        try:
            result = git_cmd(
                ["log", "--diff-filter=A", "--reverse", "--format=%H%n%aI%n%s", "--", path],
                cwd=spec_dir,
            )
        except RuntimeError:
            continue
        if not result:
            continue
        lines = result.splitlines()
        if len(lines) < 3:
            continue
        sha, date, message = lines[0], lines[1], lines[2]
        if earliest is None or date < earliest[1]:
            earliest = (sha, date, message, path)

    return earliest


def find_swagger_spec_folder(sha: str, spec_folder: str, spec_dir: str) -> str:
    """Find the swagger resource-manager folder at a given commit.

    At the pre-migration commit, swagger files live under
    specification/<service>/resource-manager/. Returns that path if it exists,
    otherwise falls back to the top-level service folder.
    """
    rm_folder = f"{spec_folder}/resource-manager"
    try:
        output = git_cmd(["ls-tree", sha, rm_folder], cwd=spec_dir)
        if output:
            return rm_folder
    except RuntimeError:
        pass
    return spec_folder


def find_last_service_commit_before(sha: str, spec_folder: str, spec_dir: str) -> tuple[str, str, str] | None:
    """Find the last commit that touched the service spec folder before the given commit.

    This gives the true "last commit without tspconfig.yaml" for the service,
    rather than just the git parent (which may be an unrelated commit).

    Returns (sha, date, message) or None.
    """
    try:
        output = git_cmd(
            ["log", "-1", "--format=%H%n%aI%n%s", f"{sha}^", "--", f"{spec_folder}/"],
            cwd=spec_dir,
        )
    except RuntimeError:
        return None
    if not output:
        return None
    lines = output.splitlines()
    if len(lines) < 3:
        return None
    return lines[0], lines[1], lines[2]


def main():
    parser = argparse.ArgumentParser(description="Find last commit without tspconfig.yaml for a package")
    parser.add_argument("package_name", help="Full package name (e.g. azure-mgmt-securityinsights)")
    parser.add_argument("--spec-dir", required=True, help="Path to the spec repo worktree")
    args = parser.parse_args()

    spec_dir = os.path.abspath(args.spec_dir)
    package_name = args.package_name
    print(f"Package: {package_name}")
    print(f"Spec dir: {spec_dir}\n")

    # Step 1: Find the current tspconfig.yaml path (for output metadata)
    file_path = find_tspconfig_path(package_name, spec_dir)
    if not file_path:
        sys.exit(1)

    # Step 2: Derive the service's top-level spec folder
    spec_folder = derive_service_spec_folder(file_path)
    print(f"\nService spec folder: {spec_folder}")

    # Step 3: Find the earliest commit that introduced ANY tspconfig.yaml for this service.
    # This searches all historical paths, not just the current one (which may have
    # been created by a folder restructure rather than the original migration).
    print(f"\nSearching git history for tspconfig.yaml additions under {spec_folder}/...")
    migration = find_earliest_tspconfig_commit(spec_folder, spec_dir)
    if not migration:
        print(f"No commits found that added tspconfig.yaml under {spec_folder}/")
        sys.exit(1)

    m_sha, m_date, m_message, m_path = migration
    print(f"\nEarliest migration commit (first tspconfig.yaml addition):")
    print(f"  SHA:     {m_sha}")
    print(f"  Date:    {m_date}")
    print(f"  Message: {m_message}")
    print(f"  Path:    {m_path}\n")

    # Step 4: Find the last commit touching this service's spec folder BEFORE
    # the migration.  This is the true "last commit without tspconfig.yaml" for
    # the service — not just the git parent (which may be unrelated).
    result = find_last_service_commit_before(m_sha, spec_folder, spec_dir)
    if not result:
        print("No prior commits found touching the service spec folder.")
        sys.exit(1)

    p_sha, p_date, p_message = result
    print(f"Last commit WITHOUT tspconfig.yaml (last service commit before migration):")
    print(f"  SHA:     {p_sha}")
    print(f"  Date:    {p_date}")
    print(f"  Message: {p_message}")

    # Step 5: Find the swagger resource-manager folder at the pre-migration commit
    # so users can browse the swagger files directly.
    swagger_folder = find_swagger_spec_folder(p_sha, spec_folder, spec_dir)

    folder_path = file_path.rsplit("/", 1)[0] if "/" in file_path else file_path
    print(f"\n  Commit URL: https://github.com/{OWNER}/{REPO}/commit/{p_sha}")
    print(f"  Folder URL: https://github.com/{OWNER}/{REPO}/tree/{p_sha}/{swagger_folder}")

    # Output for session state parsing
    print("\n" + "=" * 60)
    print("=== SESSION_STATE ===")
    print(f"tspconfig_path={file_path}")
    print(f"pre_migration_commit={p_sha}")
    print(f"spec_folder={folder_path}")
    print(f"swagger_spec_folder={swagger_folder}")
    print("=" * 60)


if __name__ == "__main__":
    main()
