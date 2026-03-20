"""
Generate TypeSpec SDK and breaking change code report.

Usage:
    python generate_typespec_sdk.py <package-name> <spec-folder> --spec-dir <dir> --sdk-dir <dir> [--remote <username>]

Example:
    python generate_typespec_sdk.py azure-mgmt-securityinsights specification/securityinsights/resource-manager/Microsoft.SecurityInsights/SecurityInsights --spec-dir /dev/worktrees/spec-azure-mgmt-securityinsights --sdk-dir /dev/worktrees/sdk-azure-mgmt-securityinsights
"""

import argparse
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
    parser = argparse.ArgumentParser(description="Generate TypeSpec SDK and code report")
    parser.add_argument("package_name", help="Full package name (e.g. azure-mgmt-securityinsights)")
    parser.add_argument("spec_folder", help="TypeSpec project folder in spec repo")
    parser.add_argument("--spec-dir", required=True, help="Path to spec repo (or worktree)")
    parser.add_argument("--sdk-dir", required=True, help="Path to SDK repo (or worktree)")
    parser.add_argument(
        "--remote", default=None, help="Git remote name to push to (auto-detected from gh CLI if not specified)"
    )
    args = parser.parse_args()

    package_name = args.package_name
    spec_folder = args.spec_folder

    if args.remote:
        remote = args.remote
    else:
        detect = subprocess.run("gh api user --jq .login", shell=True, capture_output=True, text=True)
        if detect.returncode != 0:
            print("Error: Could not detect GitHub username. Specify --remote explicitly.")
            sys.exit(1)
        remote = detect.stdout.strip()
        print(f"Auto-detected remote: {remote}")

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
    print(f"Spec folder:   {spec_folder}")
    print(f"Remote:        {remote}")

    # 1. Clean REST repo and checkout origin/main
    print("\n" + "=" * 60)
    print("Step 1: Clean REST repo -> checkout origin/main")
    print("=" * 60)
    run_cmd("git checkout . && git clean -fd && git checkout origin/main && git pull origin main", cwd=rest_repo)

    # Get HEAD SHA
    result = run_cmd("git rev-parse HEAD", cwd=rest_repo)
    head_sha = result.stdout.strip()
    print(f"HeadSha: {head_sha}")

    # 2. Clean SDK repo and ensure on migration branch
    print("\n" + "=" * 60)
    print("Step 2: Clean SDK repo -> ensure migration branch")
    print("=" * 60)
    run_cmd("git checkout . && git clean -fd", cwd=sdk_repo)
    result = run_cmd("git rev-parse --abbrev-ref HEAD", cwd=sdk_repo)
    current_branch = result.stdout.strip()
    if current_branch != branch_name:
        print(f"Current branch '{current_branch}' != '{branch_name}', switching...")
        run_cmd(f"git checkout {branch_name}", cwd=sdk_repo)
    else:
        print(f"Already on branch '{branch_name}'")

    # 3. Create generate_input_typespec.json
    print("\n" + "=" * 60)
    print("Step 3: Create generate_input_typespec.json")
    print("=" * 60)
    input_data = {
        "specFolder": rest_repo.replace("\\", "/"),
        "headSha": head_sha,
        "runMode": "auto-release",
        "repoHttpsUrl": "https://github.com/Azure/azure-rest-api-specs",
        "enableChangelog": False,
        "relatedTypeSpecProjectFolder": [spec_folder],
    }
    input_path = os.path.join(venv_path, "generate_input_typespec.json")
    with open(input_path, "w", encoding="utf-8") as f:
        json.dump(input_data, f, indent=2)
    print(json.dumps(input_data, indent=2))

    # 4. Install tsp-client dependencies
    print("\n" + "=" * 60)
    print("Step 4: Install tsp-client dependencies")
    print("=" * 60)
    tsp_client_dir = os.path.join(sdk_repo, "eng", "common", "tsp-client")
    if os.path.isdir(tsp_client_dir):
        node_modules = os.path.join(tsp_client_dir, "node_modules")
        if not os.path.isdir(node_modules):
            print("Installing tsp-client npm dependencies...")
            run_cmd("npm ci", cwd=tsp_client_dir)
        else:
            print("tsp-client node_modules already exists, skipping install")
    else:
        print(f"Warning: tsp-client directory not found at {tsp_client_dir}")

    # 5. Run sdk_generator
    print("\n" + "=" * 60)
    print("Step 5: Run sdk_generator")
    print("=" * 60)
    run_cmd(
        venv_cmd(activate, "sdk_generator .venv/generate_input_typespec.json .venv/generate_output.json"),
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

    # 7. Run tox breaking change report
    print("\n" + "=" * 60)
    print("Step 7: Run breaking change code report")
    print("=" * 60)
    tox_dir = os.path.join(pkg_dir, ".tox")
    if os.path.isdir(tox_dir):
        print("Cleaning .tox directory...")
        shutil.rmtree(tox_dir)

    run_cmd(
        venv_cmd(activate, "tox run -c ../../../eng/tox/tox.ini --root . -e breaking -- --code-report"),
        cwd=pkg_dir,
    )

    # 8. Rename code_report.json -> code_report_typespec.json
    print("\n" + "=" * 60)
    print("Step 8: Rename code_report.json -> code_report_typespec.json")
    print("=" * 60)
    report_src = os.path.join(pkg_dir, "code_report.json")
    report_dst = os.path.join(pkg_dir, "code_report_typespec.json")
    if os.path.isfile(report_src):
        os.rename(report_src, report_dst)
        print(f"Renamed: {report_dst}")
    else:
        print(f"Warning: code_report.json not found at {report_src}")

    # 9. Git status and commit
    print("\n" + "=" * 60)
    print("Step 9: Git status and commit")
    print("=" * 60)
    run_cmd("git status", cwd=sdk_repo)
    run_cmd("git add .", cwd=sdk_repo)
    result = run_cmd('git commit -m "generate from typespec"', cwd=sdk_repo, check=False)
    if result.returncode != 0:
        print("No changes to commit, skipping")

    # 10. Push
    print("\n" + "=" * 60)
    print(f"Step 10: Push to {remote}")
    print("=" * 60)
    run_cmd(f"git push {remote} HEAD", cwd=sdk_repo)

    # Output for session state parsing
    print("\n" + "=" * 60)
    print("=== SESSION_STATE ===")
    print(f"typespec_code_report={report_dst.replace(os.sep, '/')}")
    print(f"head_sha={head_sha}")
    print("=" * 60)
    print("\nDone! TypeSpec SDK generated, committed, and pushed.")


if __name__ == "__main__":
    main()
