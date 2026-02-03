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


def prepare_branch(repo_path: Path, base_branch: str, current_date: str) -> str:
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
        branch_name = base_branch
        print(f"  Checked out branch: {branch_name}")

    return branch_name


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


def run_version_tool(repo_path: Path) -> None:
    """Run pnpm change version command."""
    print("\n[Step 3] Running version tool...")

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
    print("\n[Step 4] Checking for minor version bump...")

    # Run git diff to inspect CHANGELOG.md files
    result = run_command("git diff", cwd=repo_path)
    diff_output = result.stdout

    # Check if any CHANGELOG.md contains "### Features"
    needs_minor_bump = "### Features" in diff_output

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
    print("\n[Step 5] Installing dependencies and building...")

    run_command("pnpm install", cwd=repo_path)
    run_command("pnpm build", cwd=repo_path)

    print("  Staging changes...")
    run_command("git add -u", cwd=repo_path)


def commit_and_push(repo_path: Path) -> None:
    """Commit and push changes."""
    print("\n[Step 6] Committing and pushing...")

    run_command('git commit -m "bump version"', cwd=repo_path)
    run_command("git push origin HEAD", cwd=repo_path)


def create_pr_if_needed(repo_path: Path, base_branch: str) -> str | None:
    """Create a PR if one doesn't already exist for the current branch. Returns PR URL if created."""
    print("\n[Step 7] Checking for existing PR...")

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
        description="Bump @typespec/http-client-python dependency and release new versions for Azure/autorest.python"
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
        # Step 1: Prepare branch
        branch_name = prepare_branch(repo_path, base_branch, current_date)

        # Step 2: Get latest version and update dependencies
        version = get_latest_npm_version("@typespec/http-client-python")
        update_http_client_python_dependency(repo_path, version)

        # Step 3: Run version tool
        run_version_tool(repo_path)

        # Step 4: Check for minor version bump
        check_and_fix_minor_version(repo_path)

        # Step 5: Build and stage
        if args.skip_build:
            print("\n[Step 5] Skipping build (--skip-build flag)")
            run_command("git add -u", cwd=repo_path)
        else:
            build_and_stage(repo_path)

        # Step 6: Commit and push
        commit_and_push(repo_path)

        # Step 7: Create PR
        if args.skip_pr:
            print("\n[Step 7] Skipping PR creation (--skip-pr flag)")
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
