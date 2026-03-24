"""
Extract Python SDK package name and PR metadata from a spec PR.

Usage:
    python extract_package_from_pr.py <pr-url-or-number>

Example:
    python extract_package_from_pr.py https://github.com/Azure/azure-rest-api-specs/pull/40023
    python extract_package_from_pr.py 40023

Uses `gh` CLI only (no worktree or venv needed). Run before Step 0.
"""

import argparse
import json
import re
import subprocess
import sys


OWNER = "Azure"
REPO = "azure-rest-api-specs"


def run_cmd(cmd, check=True):
    """Run a shell command and return the result."""
    print(f"\n  $ {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        for line in result.stderr.strip().split("\n"):
            print(f"  [stderr] {line}")
    if check and result.returncode != 0:
        print(f"\nError: Command failed with exit code {result.returncode}")
        sys.exit(1)
    return result


def parse_pr_number(pr_input: str) -> str:
    """Extract PR number from a URL or return as-is if already a number."""
    match = re.search(r"/pull/(\d+)", pr_input)
    if match:
        return match.group(1)
    if pr_input.strip().isdigit():
        return pr_input.strip()
    print(f"Error: Cannot parse PR number from '{pr_input}'")
    sys.exit(1)


def get_pr_metadata(pr_number: str) -> dict:
    """Get PR head ref, owner, and SHA via gh api."""
    result = run_cmd(
        f"gh api repos/{OWNER}/{REPO}/pulls/{pr_number} "
        f'--jq "{{ref: .head.ref, owner: .head.user.login, sha: .head.sha, repo_name: .head.repo.name}}"'
    )
    return json.loads(result.stdout.strip())


def get_pr_changed_files(pr_number: str) -> list[str]:
    """Get list of changed file paths in a PR."""
    result = run_cmd(f"gh api repos/{OWNER}/{REPO}/pulls/{pr_number}/files --paginate --jq .[].filename")
    return [f.strip() for f in result.stdout.strip().splitlines() if f.strip()]


def fetch_file_content(path: str, ref: str) -> str:
    """Fetch raw file content from GitHub at a specific ref."""
    result = run_cmd(
        f'gh api -H "Accept: application/vnd.github.raw" ' f'"repos/{OWNER}/{REPO}/contents/{path}?ref={ref}"'
    )
    return result.stdout


def extract_package_name(content: str) -> str | None:
    """Extract Python package name from tspconfig.yaml content.

    The package name is the last path segment of `emitter-output-dir`
    under `options.@azure-tools/typespec-python`.
    """
    try:
        import yaml

        config = yaml.safe_load(content)
        python_opts = config.get("options", {}).get("@azure-tools/typespec-python", {})
        emitter_dir = python_opts.get("emitter-output-dir", "")
        if emitter_dir:
            return emitter_dir.rstrip("/").rsplit("/", 1)[-1]
    except ImportError:
        pass
    except Exception as e:
        print(f"  Warning: YAML parsing failed ({e}), falling back to line parser")

    # Fallback: line-by-line parsing (no pyyaml dependency)
    in_python_section = False
    for line in content.splitlines():
        if "@azure-tools/typespec-python" in line:
            in_python_section = True
            continue
        if in_python_section:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            # Left the section if we hit a non-indented line
            if not line[0].isspace():
                in_python_section = False
                continue
            if "emitter-output-dir" in stripped:
                value = stripped.split(":", 1)[1].strip().strip('"').strip("'")
                return value.rstrip("/").rsplit("/", 1)[-1]

    return None


def main():
    parser = argparse.ArgumentParser(description="Extract Python SDK package name from a spec PR")
    parser.add_argument(
        "pr_input",
        help="PR URL (e.g. https://github.com/Azure/azure-rest-api-specs/pull/40023) or PR number",
    )
    args = parser.parse_args()

    pr_number = parse_pr_number(args.pr_input)
    print(f"PR number: {pr_number}")

    # 1. Get PR metadata
    print("\n" + "=" * 60)
    print("Step 1: Get PR metadata")
    print("=" * 60)
    metadata = get_pr_metadata(pr_number)
    head_ref = metadata["ref"]
    head_owner = metadata["owner"]
    head_sha = metadata["sha"]
    print(f"Head ref:   {head_ref}")
    print(f"Head owner: {head_owner}")
    print(f"Head SHA:   {head_sha}")

    # 2. Find tspconfig.yaml in changed files
    print("\n" + "=" * 60)
    print("Step 2: Find tspconfig.yaml in changed files")
    print("=" * 60)
    files = get_pr_changed_files(pr_number)
    tspconfig_files = [f for f in files if f.endswith("tspconfig.yaml")]

    if not tspconfig_files:
        print("Error: No tspconfig.yaml found in PR changed files")
        print(f"Changed files ({len(files)}):")
        for f in files[:20]:
            print(f"  {f}")
        if len(files) > 20:
            print(f"  ... and {len(files) - 20} more")
        sys.exit(1)

    if len(tspconfig_files) > 1:
        print(f"Warning: Multiple tspconfig.yaml files found:")
        for f in tspconfig_files:
            print(f"  {f}")
        print(f"Using first: {tspconfig_files[0]}")
    else:
        print(f"Found: {tspconfig_files[0]}")

    tspconfig_path = tspconfig_files[0]

    # 3. Fetch tspconfig.yaml content and extract package name
    print("\n" + "=" * 60)
    print("Step 3: Extract package name from tspconfig.yaml")
    print("=" * 60)
    content = fetch_file_content(tspconfig_path, head_sha)
    package_name = extract_package_name(content)

    if not package_name:
        print("Error: Could not extract Python package name from tspconfig.yaml")
        print("No @azure-tools/typespec-python emitter-output-dir found")
        sys.exit(1)

    print(f"Package name: {package_name}")

    # Output for session state parsing
    print("\n" + "=" * 60)
    print("=== SESSION_STATE ===")
    print(f"package_name={package_name}")
    print(f"pr_number={pr_number}")
    print(f"pr_head_ref={head_ref}")
    print(f"pr_head_owner={head_owner}")
    print("=" * 60)
    print("\nDone! Package name extracted from PR.")


if __name__ == "__main__":
    main()
