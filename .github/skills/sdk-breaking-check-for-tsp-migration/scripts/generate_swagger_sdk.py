"""
Generate Swagger SDK and breaking change code report.

Usage:
    python generate_swagger_sdk.py <package-name> <pre-migration-commit> --spec-dir <dir> --sdk-dir <dir>

Example:
    python generate_swagger_sdk.py azure-mgmt-securityinsights abc123 --spec-dir /dev/worktrees/spec-azure-mgmt-securityinsights --sdk-dir /dev/worktrees/sdk-azure-mgmt-securityinsights
"""

import argparse
import glob
import json
import os
import platform
import shutil
import subprocess
import sys

IS_WINDOWS = platform.system() == "Windows"


def get_activate_path(venv_path):
    if IS_WINDOWS:
        return os.path.join(venv_path, "Scripts", "activate.bat")
    return os.path.join(venv_path, "bin", "activate")


def venv_cmd(activate, cmd):
    """Wrap a command with venv activation, cross-platform."""
    if IS_WINDOWS:
        return f'call "{activate}" && {cmd}'
    return f'. "{activate}" && {cmd}'


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


def strip_mgmt_prefix(package_name):
    name = package_name.lower()
    for prefix in ("azure-mgmt-", "azure-"):
        if name.startswith(prefix):
            return name[len(prefix) :]
    return name


def main():
    parser = argparse.ArgumentParser(description="Generate Swagger SDK and code report")
    parser.add_argument("package_name", help="Full package name (e.g. azure-mgmt-securityinsights)")
    parser.add_argument("pre_migration_commit", help="REST repo commit SHA (pre-migration)")
    parser.add_argument("--spec-dir", required=True, help="Path to spec repo (or worktree)")
    parser.add_argument("--sdk-dir", required=True, help="Path to SDK repo (or worktree)")
    args = parser.parse_args()

    package_name = args.package_name
    commit = args.pre_migration_commit

    package = strip_mgmt_prefix(package_name)
    rest_repo = os.path.abspath(args.spec_dir)
    sdk_repo = os.path.abspath(args.sdk_dir)
    venv_path = os.path.join(sdk_repo, ".venv")
    branch_name = f"sdk-{package_name}"
    activate = get_activate_path(venv_path)

    for path, label in [
        (rest_repo, "REST repo"),
        (sdk_repo, "SDK repo"),
        (venv_path, "Virtual environment"),
        (activate, "Activate script"),
    ]:
        if not os.path.exists(path):
            print(f"Error: {label} not found at {path}")
            sys.exit(1)

    print(f"Package:       {package_name}")
    print(f"Short name:    {package}")
    print(f"Branch:        {branch_name}")
    print(f"REST repo:     {rest_repo}")
    print(f"SDK repo:      {sdk_repo}")
    print(f"Commit:        {commit}")

    # 1. Setup SDK repo branch
    print("\n" + "=" * 60)
    print("Step 1: Setup SDK repo branch")
    print("=" * 60)
    result = run_cmd("git rev-parse --abbrev-ref HEAD", cwd=sdk_repo)
    current_branch = result.stdout.strip()
    if current_branch != branch_name:
        print(f"Current branch '{current_branch}' != '{branch_name}', creating new branch...")
        run_cmd("git fetch origin main", cwd=sdk_repo)
        run_cmd(f"git checkout -B {branch_name} origin/main", cwd=sdk_repo)
    else:
        print(f"Already on branch '{branch_name}'")

    # Cache check: skip generation if matching commit already exists
    # (done BEFORE spec repo checkout to avoid slow git operations on cache hit)
    commit_msg = f"generated from swagger:{commit}"
    print("\n" + "=" * 60)
    print(f"Cache check: searching for '{commit_msg}'")
    print("=" * 60)
    result = run_cmd(f'git log --oneline --grep="{commit_msg}"', cwd=sdk_repo, check=False)
    if result.stdout.strip():
        cached_line = result.stdout.strip().split("\n")[0]
        cached_sha = cached_line.split()[0]
        print(f"Cache hit! Found: {cached_line}")
        run_cmd(f"git reset --hard {cached_sha}", cwd=sdk_repo)

        reports = glob.glob(os.path.join(sdk_repo, "**", "code_report_swagger.json"), recursive=True)
        if reports:
            report_dst = reports[0]
            sdk_pkg_path = os.path.relpath(os.path.dirname(report_dst), sdk_repo).replace("\\", "/")
            print("\n" + "=" * 60)
            print("=== SESSION_STATE ===")
            print(f"sdk_package_path={sdk_pkg_path}")
            print(f"swagger_code_report={report_dst.replace(os.sep, '/')}")
            print("=" * 60)
            print("\nDone! Using cached swagger generation.")
            return
        print("Warning: report not found in cached commit, regenerating...")

    # 2. Clean REST repo and checkout pre-migration commit
    print("\n" + "=" * 60)
    print("Step 2: Clean REST repo -> checkout pre-migration commit")
    print("=" * 60)
    run_cmd(f"git checkout . && git clean -fd && git checkout {commit}", cwd=rest_repo)

    # 3. Find readme.python.md containing the package name
    print("\n" + "=" * 60)
    print(f"Step 3: Search readme.python.md for '{package_name}'")
    print("=" * 60)
    pattern = os.path.join(rest_repo, "specification", "**", "readme.python.md")
    readme_files = glob.glob(pattern, recursive=True)
    print(f"Found {len(readme_files)} readme.python.md files, searching...")

    target_readme_dir = None
    for readme_file in readme_files:
        with open(readme_file, "r", encoding="utf-8") as f:
            content = f.read()
        if package_name in content:
            rel_path = os.path.relpath(readme_file, rest_repo).replace("\\", "/")
            target_readme_dir = os.path.dirname(rel_path)
            print(f"Match: {rel_path}")
            break

    if not target_readme_dir:
        print(f"Error: No readme.python.md contains '{package_name}'")
        sys.exit(1)

    # 4. Create generate_input_swagger.json
    print("\n" + "=" * 60)
    print("Step 4: Create generate_input_swagger.json")
    print("=" * 60)
    input_data = {
        "specFolder": rest_repo.replace("\\", "/"),
        "headSha": commit,
        "runMode": "auto-release",
        "repoHttpsUrl": "https://github.com/Azure/azure-rest-api-specs",
        "enableChangelog": False,
        "relatedReadmeMdFiles": [f"{target_readme_dir}/readme.md"],
    }
    input_path = os.path.join(venv_path, "generate_input_swagger.json")
    with open(input_path, "w", encoding="utf-8") as f:
        json.dump(input_data, f, indent=2)
    print(json.dumps(input_data, indent=2))

    # 5. Run sdk_generator
    print("\n" + "=" * 60)
    print("Step 5: Run sdk_generator")
    print("=" * 60)
    run_cmd(
        venv_cmd(activate, "sdk_generator .venv/generate_input_swagger.json .venv/generate_output.json"),
        cwd=sdk_repo,
    )

    # 6. Parse generate_output.json
    print("\n" + "=" * 60)
    print("Step 6: Parse generate_output.json")
    print("=" * 60)
    output_path = os.path.join(venv_path, "generate_output.json")
    with open(output_path, "r", encoding="utf-8") as f:
        output_data = json.load(f)

    if "packages" in output_data:
        pkg_info = output_data["packages"][0]
        pkg_path = pkg_info.get("path", [])
        if isinstance(pkg_path, list):
            pkg_path = pkg_path[0] if pkg_path else ""
        pkg_package_name = pkg_info.get("packageName", "")
    else:
        pkg_path = output_data.get("path", "")
        if isinstance(pkg_path, list):
            pkg_path = pkg_path[0] if pkg_path else ""
        pkg_package_name = output_data.get("packageName", "")

    print(f"path:        {pkg_path}")
    print(f"packageName: {pkg_package_name}")

    pkg_dir = os.path.join(sdk_repo, pkg_path, pkg_package_name)
    if not os.path.isdir(pkg_dir):
        print(f"Error: Package directory not found at {pkg_dir}")
        sys.exit(1)

    # 7. Run breaking change code report
    print("\n" + "=" * 60)
    print("Step 7: Run breaking change code report")
    print("=" * 60)
    tox_dir = os.path.join(pkg_dir, ".tox")
    if os.path.isdir(tox_dir):
        print(f"Removing stale .tox directory: {tox_dir}")
        shutil.rmtree(tox_dir)
    run_cmd(
        venv_cmd(activate, "azpysdk breaking . --code-report"),
        cwd=pkg_dir,
    )

    # 8. Rename code_report.json -> code_report_swagger.json
    print("\n" + "=" * 60)
    print("Step 8: Rename code_report.json -> code_report_swagger.json")
    print("=" * 60)
    report_src = os.path.join(pkg_dir, "code_report.json")
    report_dst = os.path.join(pkg_dir, "code_report_swagger.json")
    if os.path.isfile(report_src):
        os.replace(report_src, report_dst)
        print(f"Renamed: {report_dst}")
    else:
        print(f"Warning: code_report.json not found at {report_src}")

    # 9. Git commit
    print("\n" + "=" * 60)
    print("Step 9: Git status and commit")
    print("=" * 60)
    run_cmd("git status", cwd=sdk_repo)
    run_cmd("git add .", cwd=sdk_repo)
    result = run_cmd(f'git commit -m "generated from swagger:{commit}"', cwd=sdk_repo, check=False)
    if result.returncode != 0:
        print("No changes to commit, skipping")

    # Output for session state parsing
    sdk_pkg_path = f"{pkg_path}/{pkg_package_name}"
    print("\n" + "=" * 60)
    print("=== SESSION_STATE ===")
    print(f"sdk_package_path={sdk_pkg_path}")
    print(f"swagger_code_report={report_dst.replace(os.sep, '/')}")
    print(f"swagger_readme_dir={target_readme_dir}")
    print("=" * 60)
    print("\nDone! Swagger SDK generated and committed.")


if __name__ == "__main__":
    main()
