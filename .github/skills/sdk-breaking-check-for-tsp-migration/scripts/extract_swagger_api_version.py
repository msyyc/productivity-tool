"""
Extract the default swagger tag and API versions from readme.md at the pre-migration commit.

Usage:
    python extract_swagger_api_version.py <package-name> --spec-dir <spec-worktree> --commit <sha> --swagger-spec-folder <folder>

Example:
    python extract_swagger_api_version.py azure-mgmt-frontdoor --spec-dir /dev/worktrees/spec-azure-mgmt-frontdoor --commit abc123 --swagger-spec-folder specification/frontdoor/resource-manager

Reads the swagger readme.md at the given commit (without modifying the worktree)
and extracts the default tag and the API versions used in that tag's input-file list.
"""

import argparse
import os
import re
import subprocess
import sys


def git_cmd(args: list[str], cwd: str) -> str:
    result = subprocess.run(["git"] + args, capture_output=True, text=True, cwd=cwd)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def find_readme_path(package_name: str, commit: str, swagger_spec_folder: str, spec_dir: str) -> str | None:
    """Find the main readme.md for the package under swagger_spec_folder at the given commit."""
    output = git_cmd(
        ["ls-tree", "-r", "--name-only", commit, swagger_spec_folder + "/"],
        cwd=spec_dir,
    )
    if not output:
        return None

    all_files = output.splitlines()
    readme_files = [f for f in all_files if f.lower().endswith("/readme.md")]
    if not readme_files:
        return None

    if len(readme_files) == 1:
        return readme_files[0]

    # Multiple readme.md — find via companion readme.python.md mentioning the package
    python_readmes = [f for f in all_files if f.lower().endswith("/readme.python.md")]
    for py_readme in python_readmes:
        try:
            content = git_cmd(["show", f"{commit}:{py_readme}"], cwd=spec_dir)
            if package_name.lower() in content.lower():
                dir_path = py_readme.rsplit("/", 1)[0]
                readme_path = f"{dir_path}/readme.md"
                if readme_path in readme_files:
                    return readme_path
        except RuntimeError:
            continue

    # Fallback: first readme.md that has a tag: line
    for readme in readme_files:
        try:
            content = git_cmd(["show", f"{commit}:{readme}"], cwd=spec_dir)
            if re.search(r"^tag:\s+", content, re.MULTILINE):
                return readme
        except RuntimeError:
            continue

    return readme_files[0]


def parse_default_tag(content: str) -> str | None:
    """Extract the default tag from readme.md content.

    Looks for the first non-conditional yaml code block containing a ``tag:`` line.
    """
    yaml_blocks = re.findall(r"```\s*yaml\s*\n(.*?)```", content, re.DOTALL)
    for block in yaml_blocks:
        if "$(tag)" in block:
            continue
        match = re.search(r"^tag:\s+(.+)$", block, re.MULTILINE)
        if match:
            return match.group(1).strip()
    return None


def parse_input_files(content: str, tag: str) -> list[str]:
    """Extract the input-file list for a specific tag section."""
    escaped_tag = re.escape(tag)
    pattern = rf"```\s*yaml\s+\$\(tag\)\s*==\s*'{escaped_tag}'\s*\n(.*?)```"
    match = re.search(pattern, content, re.DOTALL)
    if not match:
        return []

    block = match.group(1)
    in_input_file = False
    files: list[str] = []
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith("input-file:"):
            in_input_file = True
            value = stripped[len("input-file:") :].strip()
            if value and value.startswith("-"):
                files.append(value.lstrip("- ").strip())
            continue
        if in_input_file:
            if stripped.startswith("-"):
                files.append(stripped.lstrip("- ").strip())
            elif stripped and not stripped.startswith("#"):
                break
    return files


def extract_api_versions(file_paths: list[str]) -> list[str]:
    """Extract unique API versions from swagger file paths.

    Paths follow patterns like:
      - stable/2025-11-01/openapi.json
      - preview/2024-01-01-preview/something.json
      - Microsoft.Network/stable/2024-01-01/file.json
    """
    versions: set[str] = set()
    for path in file_paths:
        match = re.search(r"(?:stable|preview)/(\d{4}-\d{2}-\d{2}(?:-preview)?)", path)
        if match:
            versions.add(match.group(1))
    return sorted(versions)


def main():
    parser = argparse.ArgumentParser(description="Extract default swagger tag and API versions")
    parser.add_argument("package_name", help="Full package name (e.g. azure-mgmt-frontdoor)")
    parser.add_argument("--spec-dir", required=True, help="Path to the spec repo worktree")
    parser.add_argument("--commit", required=True, help="Pre-migration commit SHA")
    parser.add_argument(
        "--swagger-spec-folder",
        required=True,
        help="Swagger spec folder (e.g. specification/frontdoor/resource-manager)",
    )
    args = parser.parse_args()

    spec_dir = os.path.abspath(args.spec_dir)
    package_name = args.package_name
    commit = args.commit
    swagger_spec_folder = args.swagger_spec_folder

    print(f"Package: {package_name}")
    print(f"Spec dir: {spec_dir}")
    print(f"Commit: {commit}")
    print(f"Swagger spec folder: {swagger_spec_folder}\n")

    # 1. Find readme.md
    print(f"Searching for readme.md under {swagger_spec_folder}...")
    readme_path = find_readme_path(package_name, commit, swagger_spec_folder, spec_dir)
    if not readme_path:
        print("Error: No readme.md found")
        sys.exit(1)
    print(f"Found: {readme_path}")

    # 2. Read content at the commit
    content = git_cmd(["show", f"{commit}:{readme_path}"], cwd=spec_dir)

    # 3. Parse default tag
    default_tag = parse_default_tag(content)
    if not default_tag:
        print("Error: Could not find default tag in readme.md")
        sys.exit(1)
    print(f"Default tag: {default_tag}")

    # 4. Parse input files
    input_files = parse_input_files(content, default_tag)
    if not input_files:
        print(f"Warning: No input files found for tag '{default_tag}'")
    else:
        print(f"\nInput files ({len(input_files)}):")
        for f in input_files:
            print(f"  - {f}")

    # 5. Extract API versions
    api_versions = extract_api_versions(input_files)
    if not api_versions:
        print("\nWarning: Could not extract any API versions from input file paths")
    elif len(api_versions) == 1:
        print(f"\nSingle API version: {api_versions[0]}")
    else:
        print(f"\nMultiple API versions ({len(api_versions)}): {', '.join(api_versions)}")

    # Session state output
    versions_str = ",".join(api_versions) if api_versions else ""
    print("\n" + "=" * 60)
    print("=== SESSION_STATE ===")
    print(f"default_tag={default_tag}")
    print(f"swagger_api_versions={versions_str}")
    print("=" * 60)


if __name__ == "__main__":
    main()
