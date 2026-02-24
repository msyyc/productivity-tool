#!/usr/bin/env python3
"""
Typespec Python Bump and Release Script

Bump the "@typespec/http-client-python" dependency and create a release PR
for the Azure/autorest.python repository.
"""

import argparse
import json
import re
import subprocess
import sys
import webbrowser
from datetime import datetime
from pathlib import Path


def show_pr_link_window(pr_url: str) -> None:
    """Display a window with a clickable PR hyperlink."""
    try:
        import tkinter as tk
        from tkinter import font as tkfont

        root = tk.Tk()
        root.title("PR Created Successfully")
        root.geometry("500x120")
        root.resizable(False, False)

        # Center the window on screen
        root.update_idletasks()
        x = (root.winfo_screenwidth() // 2) - (500 // 2)
        y = (root.winfo_screenheight() // 2) - (120 // 2)
        root.geometry(f"+{x}+{y}")

        # Keep window on top
        root.attributes("-topmost", True)

        # Label
        label = tk.Label(root, text="PR created successfully! Click the link below:", pady=10)
        label.pack()

        # Hyperlink label
        link_font = tkfont.Font(family="TkDefaultFont", underline=True)
        link_label = tk.Label(root, text=pr_url, fg="blue", cursor="hand2", font=link_font)
        link_label.pack(pady=5)

        def open_link(event=None):
            webbrowser.open(pr_url)
            root.destroy()

        link_label.bind("<Button-1>", open_link)

        # Close button
        close_btn = tk.Button(root, text="Close", command=root.destroy, width=10)
        close_btn.pack(pady=10)

        root.mainloop()

    except ImportError:
        print(f"\nPR URL: {pr_url}")
        print("(tkinter not available - please open the URL manually)")


def run_command(cmd: str | list[str], cwd: str | Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run a shell command and return the result."""
    if isinstance(cmd, str):
        print(f"  Running: {cmd}")
        result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    else:
        print(f"  Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)

    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)

    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed with return code {result.returncode}")

    return result


def prepare_branch(repo_path: Path, base_branch: str, current_date: str) -> None:
    """Prepare the working branch based on BASE_BRANCH."""
    print("\n[Step 1] Preparing branch...")

    run_command("git reset HEAD", cwd=repo_path, check=False)
    run_command("git checkout .", cwd=repo_path)

    if base_branch == "main":
        run_command("git checkout origin/main", cwd=repo_path)
        run_command("git pull origin main", cwd=repo_path)
        branch_name = f"publish/release-{current_date}"
        run_command(f"git checkout -b {branch_name}", cwd=repo_path)
        print(f"  Created branch: {branch_name}")
    else:
        run_command(f"git fetch origin {base_branch}", cwd=repo_path)
        run_command(f"git checkout {base_branch}", cwd=repo_path)
        print(f"  Checked out branch: {base_branch}")


def get_latest_npm_version(package_name: str) -> str:
    """Get the latest version of a package from npm."""
    print(f"\n[Step 2a] Getting latest version of {package_name}...")

    result = run_command(f"npm view {package_name} version")
    version = result.stdout.strip()
    print(f"  Latest version: {version}")

    return version


def update_http_client_python_dependency(repo_path: Path, version: str) -> None:
    """Update @typespec/http-client-python version in package.json files."""
    print("\n[Step 2b] Updating @typespec/http-client-python dependency...")

    package_files = [
        repo_path / "packages" / "autorest.python" / "package.json",
        repo_path / "packages" / "typespec-python" / "package.json",
    ]

    new_version = f"~{version}"

    for package_file in package_files:
        if not package_file.exists():
            raise RuntimeError(f"Package file not found: {package_file}")

        with open(package_file, "r", encoding="utf-8") as f:
            package_data = json.load(f)

        # Update in dependencies
        if "dependencies" in package_data and "@typespec/http-client-python" in package_data["dependencies"]:
            old_version = package_data["dependencies"]["@typespec/http-client-python"]
            package_data["dependencies"]["@typespec/http-client-python"] = new_version
            print(f"  {package_file.relative_to(repo_path)}: '{old_version}' -> '{new_version}'")

        # Update in devDependencies if present
        if "devDependencies" in package_data and "@typespec/http-client-python" in package_data["devDependencies"]:
            old_version = package_data["devDependencies"]["@typespec/http-client-python"]
            package_data["devDependencies"]["@typespec/http-client-python"] = new_version
            print(f"  {package_file.relative_to(repo_path)} (devDependencies): '{old_version}' -> '{new_version}'")

        with open(package_file, "w", encoding="utf-8") as f:
            json.dump(package_data, f, indent=2)
            f.write("\n")  # Add trailing newline


def check_prerequisites() -> None:
    """Verify that npm-check-updates is available."""
    print("\n[Prerequisites] Checking npm-check-updates...")

    result = run_command("npx npm-check-updates --version", check=False)
    if result.returncode != 0:
        print("  npm-check-updates not found, installing globally...")
        run_command("npm install -g npm-check-updates")
    else:
        print("  npm-check-updates is available")


def save_spec_dev_dependencies(repo_path: Path) -> dict[str, str]:
    """Save original devDependencies versions for spec packages before ncu update."""
    package_file = repo_path / "packages" / "typespec-python" / "package.json"

    with open(package_file, "r", encoding="utf-8") as f:
        package_data = json.load(f)

    saved = {}
    dev_deps = package_data.get("devDependencies", {})
    for pkg in ["@typespec/http-specs", "@azure-tools/azure-http-specs"]:
        if pkg in dev_deps:
            saved[pkg] = dev_deps[pkg]

    return saved


def update_typespec_dependencies(repo_path: Path) -> None:
    """Run npm-check-updates to update @typespec/* and @azure-tools/* dependencies."""
    print("\n[Step 3] Updating @typespec/* and @azure-tools/* dependencies...")

    run_command(
        "npx npm-check-updates -u --filter @typespec/*,@azure-tools/* "
        "--packageFile packages/typespec-python/package.json",
        cwd=repo_path,
    )


def _get_latest_npm_version_silent(package_name: str) -> str | None:
    """Get the latest version of a package from npm without verbose output."""
    result = subprocess.run(
        f"npm view {package_name} version",
        shell=True,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def update_peer_dependencies(repo_path: Path) -> None:
    """Update peerDependencies in packages/typespec-python/package.json."""
    print("\n[Step 4] Updating peerDependencies...")

    package_file = repo_path / "packages" / "typespec-python" / "package.json"

    with open(package_file, "r", encoding="utf-8") as f:
        package_data = json.load(f)

    peer_deps = package_data.get("peerDependencies", {})
    if not peer_deps:
        print("  No peerDependencies found")
        return

    for pkg_name, current_value in list(peer_deps.items()):
        # Pattern 1: ">=0.a.b <1.0.0"
        range_match = re.match(r"^>=(0\.\d+\.\d+)\s+(<\d+\.\d+\.\d+)$", current_value)
        if range_match:
            upper_bound = range_match.group(2)
            latest = _get_latest_npm_version_silent(pkg_name)
            if latest:
                new_value = f">={latest} {upper_bound}"
                if new_value != current_value:
                    print(f"  {pkg_name}: '{current_value}' -> '{new_value}'")
                    peer_deps[pkg_name] = new_value
            continue

        # Pattern 2: "^1.a.b"
        caret_match = re.match(r"^\^(\d+\.\d+\.\d+)$", current_value)
        if caret_match:
            latest = _get_latest_npm_version_silent(pkg_name)
            if latest:
                new_value = f"^{latest}"
                if new_value != current_value:
                    print(f"  {pkg_name}: '{current_value}' -> '{new_value}'")
                    peer_deps[pkg_name] = new_value
            continue

    with open(package_file, "w", encoding="utf-8") as f:
        json.dump(package_data, f, indent=2)
        f.write("\n")


def _parse_version_tuple(version: str) -> tuple:
    """Parse a version string into a comparable tuple.

    Handles versions like "0.1.0-alpha.12-dev.5", "0.1.0-alpha.12", "1.2.3".
    Ordering: 0.1.0-alpha.11 < 0.1.0-alpha.12-dev.5 < 0.1.0-alpha.12
    """
    v = version.lstrip("~^")

    dev_num = None
    if "-dev." in v:
        v, dev_str = v.rsplit("-dev.", 1)
        dev_num = int(dev_str)

    alpha_num = None
    if "-alpha." in v:
        v, alpha_str = v.rsplit("-alpha.", 1)
        alpha_num = int(alpha_str)

    parts = tuple(int(x) for x in v.split("."))
    alpha = alpha_num if alpha_num is not None else float("inf")
    if dev_num is not None:
        return (*parts, alpha, 0, dev_num)
    else:
        return (*parts, alpha, 1, 0)


def verify_spec_dev_dependencies(repo_path: Path, saved_versions: dict[str, str]) -> None:
    """Verify devDependencies versions for spec packages after ncu update."""
    print("\n[Step 5] Verifying devDependencies versions for specs...")

    if not saved_versions:
        print("  No spec devDependencies to verify")
        return

    package_file = repo_path / "packages" / "typespec-python" / "package.json"

    with open(package_file, "r", encoding="utf-8") as f:
        package_data = json.load(f)

    dev_deps = package_data.get("devDependencies", {})
    changed = False

    for pkg_name, original_version in saved_versions.items():
        if pkg_name not in dev_deps:
            continue

        updated_version = dev_deps[pkg_name]

        if original_version == updated_version:
            print(f"  {pkg_name}: unchanged ({original_version})")
            continue

        if _parse_version_tuple(original_version) > _parse_version_tuple(updated_version):
            print(f"  {pkg_name}: keeping original '{original_version}' (newer than updated '{updated_version}')")
            dev_deps[pkg_name] = original_version
            changed = True
        else:
            print(f"  {pkg_name}: keeping updated '{updated_version}' (step 3 works as expected)")

    if changed:
        with open(package_file, "w", encoding="utf-8") as f:
            json.dump(package_data, f, indent=2)
            f.write("\n")


def run_version_tool(repo_path: Path) -> None:
    """Run pnpm change version command."""
    print("\n[Step 6] Running version tool...")

    run_command("pnpm change version", cwd=repo_path)

    # Verify expected files are changed
    print("  Verifying changed files...")
    result = run_command("git status --porcelain", cwd=repo_path)

    expected_files = [
        "packages/autorest.python/package.json",
        "packages/autorest.python/CHANGELOG.md",
        "packages/typespec-python/package.json",
        "packages/typespec-python/CHANGELOG.md",
    ]

    changed_files = result.stdout.strip().split("\n") if result.stdout.strip() else []
    changed_count = 0

    for expected in expected_files:
        for changed in changed_files:
            if expected in changed:
                changed_count += 1
                break

    print(f"  Found {changed_count}/4 expected files changed")

    if changed_count < 4:
        print("  Warning: Less than 4 expected files were changed")


def check_and_fix_minor_version(repo_path: Path) -> None:
    """Check if minor version bump is needed and apply it if necessary."""
    print("\n[Step 7] Checking for minor version bump...")

    # Run git diff to inspect CHANGELOG.md files
    result = run_command("git diff", cwd=repo_path)
    diff_output = result.stdout
    print(" === diff output begins ===")
    print(diff_output)
    print(" === diff output ends ===")

    # Check if any CHANGELOG.md contains "### Features" in newly added lines only
    needs_minor_bump = any(
        line.startswith("+") and "### Features" in line
        for line in diff_output.splitlines()
    )

    if not needs_minor_bump:
        print("  No '### Features' found in CHANGELOGs, keeping patch version")
        return

    print("  Found '### Features' in CHANGELOG, upgrading to minor version...")

    # Files to update
    files_to_update = [
        ("packages/autorest.python/package.json", "version"),
        ("packages/autorest.python/CHANGELOG.md", "changelog"),
        ("packages/typespec-python/package.json", "version"),
        ("packages/typespec-python/CHANGELOG.md", "changelog"),
    ]

    for rel_path, file_type in files_to_update:
        file_path = repo_path / rel_path

        if not file_path.exists():
            print(f"  Warning: File not found: {file_path}")
            continue

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        if file_type == "version":
            # Update version in package.json
            # Match pattern like "version": "1.2.3"
            version_match = re.search(r'"version":\s*"(\d+)\.(\d+)\.(\d+)"', content)
            if version_match:
                major, minor, patch = version_match.groups()
                old_version = f"{major}.{minor}.{patch}"
                # Convert patch to minor: increment minor, reset patch to 0
                new_version = f"{major}.{int(minor) + 1}.0"
                content = content.replace(f'"version": "{old_version}"', f'"version": "{new_version}"')
                print(f"  {rel_path}: '{old_version}' -> '{new_version}'")

        elif file_type == "changelog":
            # Update version in CHANGELOG.md
            # Match pattern like ## 1.2.3 (date)
            version_match = re.search(r"## (\d+)\.(\d+)\.(\d+)", content)
            if version_match:
                major, minor, patch = version_match.groups()
                old_version = f"{major}.{minor}.{patch}"
                new_version = f"{major}.{int(minor) + 1}.0"
                content = re.sub(rf"## {re.escape(old_version)}", f"## {new_version}", content, count=1)
                print(f"  {rel_path}: '{old_version}' -> '{new_version}'")

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)


def build_and_stage(repo_path: Path) -> None:
    """Install dependencies, build, and stage changes."""
    print("\n[Step 8] Installing dependencies and building...")

    run_command("pnpm install", cwd=repo_path)
    run_command("pnpm build", cwd=repo_path)

    print("  Staging changes...")
    run_command("git add -u", cwd=repo_path)


def commit_and_push(repo_path: Path) -> None:
    """Commit and push changes."""
    print("\n[Step 9] Committing and pushing...")

    run_command('git commit -m "bump version"', cwd=repo_path)
    run_command("git push -u origin HEAD", cwd=repo_path)


def create_pr_if_needed(repo_path: Path, base_branch: str) -> str | None:
    """Create a PR if one doesn't already exist for the current branch. Returns PR URL if created."""
    print("\n[Step 10] Checking for existing PR...")

    # Check if PR already exists for current branch
    result = run_command("gh pr view --json url", cwd=repo_path, check=False)

    if result.returncode == 0:
        # PR already exists
        try:
            pr_data = json.loads(result.stdout)
            pr_url = pr_data.get("url")
            print(f"  PR already exists: {pr_url}")
            return pr_url
        except json.JSONDecodeError:
            pass

    # Create new PR
    print("  Creating new PR...")
    result = run_command(
        f'gh pr create --title "[python] release new version" --body "" --base {base_branch}', cwd=repo_path
    )
    print("  PR created successfully!")

    # Extract PR URL from output
    pr_url = None
    output = result.stdout + result.stderr
    url_match = re.search(r"https://github\.com/[^\s]+/pull/\d+", output)
    if url_match:
        pr_url = url_match.group(0)

    return pr_url


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bump @typespec/http-client-python dependency and release new versions for Azure/autorest.python",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python typespec_python_release.py <path_to_autorest_python_repo>
  python typespec_python_release.py <path_to_autorest_python_repo> --base-branch feature-branch
  python typespec_python_release.py <path_to_autorest_python_repo> --skip-pr
  python typespec_python_release.py <path_to_autorest_python_repo> --skip-build
  python typespec_python_release.py C:\\dev\\autorest.python --base-branch my-feature-branch
""",
    )
    parser.add_argument("repo_path", type=str, help="Path to the root of the Azure/autorest.python repository")
    parser.add_argument("--base-branch", type=str, default="main", help="The branch to base changes on (default: main)")
    parser.add_argument(
        "--date", type=str, default=None, help="Current date in YYYY-MM-DD format (default: today's date)"
    )
    parser.add_argument("--skip-pr", action="store_true", help="Skip creating the PR (useful for testing)")
    parser.add_argument("--skip-build", action="store_true", help="Skip the build step (useful for testing)")

    args = parser.parse_args()

    repo_path = Path(args.repo_path).resolve()
    base_branch = args.base_branch
    current_date = args.date or datetime.now().strftime("%Y-%m-%d")

    if not repo_path.exists():
        print(f"Error: Repository path does not exist: {repo_path}", file=sys.stderr)
        sys.exit(1)

    # Verify expected directories exist
    autorest_dir = repo_path / "packages" / "autorest.python"
    typespec_dir = repo_path / "packages" / "typespec-python"

    if not autorest_dir.exists():
        print(f"Error: autorest.python package directory not found: {autorest_dir}", file=sys.stderr)
        sys.exit(1)

    if not typespec_dir.exists():
        print(f"Error: typespec-python package directory not found: {typespec_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Repository path: {repo_path}")
    print(f"Base branch: {base_branch}")
    print(f"Current date: {current_date}")

    try:
        # Prerequisites check
        if base_branch == "main":
            check_prerequisites()

        # Step 1: Prepare branch
        prepare_branch(repo_path, base_branch, current_date)

        # Step 2: Get latest version and update dependencies
        version = get_latest_npm_version("@typespec/http-client-python")
        update_http_client_python_dependency(repo_path, version)

        # Steps 3-5: Update dependencies (only if BASE_BRANCH is "main")
        if base_branch == "main":
            saved_dev_deps = save_spec_dev_dependencies(repo_path)
            update_typespec_dependencies(repo_path)
            update_peer_dependencies(repo_path)
            verify_spec_dev_dependencies(repo_path, saved_dev_deps)

        # Step 6: Run version tool
        run_version_tool(repo_path)

        # Step 7: Check for minor version bump
        check_and_fix_minor_version(repo_path)

        # Step 8: Build and stage
        if args.skip_build:
            print("\n[Step 8] Skipping build (--skip-build flag)")
            run_command("git add -u", cwd=repo_path)
        else:
            build_and_stage(repo_path)

        # Step 9: Commit and push
        commit_and_push(repo_path)

        # Step 10: Create PR
        if args.skip_pr:
            print("\n[Step 10] Skipping PR creation (--skip-pr flag)")
        else:
            pr_url = create_pr_if_needed(repo_path, base_branch)
            if pr_url:
                show_pr_link_window(pr_url)

        print("\n" + "=" * 50)
        print("Bump and release workflow completed successfully!")
        print("=" * 50)

    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
