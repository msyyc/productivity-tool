#!/usr/bin/env python3
"""
Typespec Azure Python Bump Script

Bump the "@typespec/http-client-python" dependency in Azure/typespec-azure pnpm-workspace.yaml
and sync test cases from upstream.
"""

import argparse
import re
import subprocess
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

from packaging import version


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


def reset_and_sync(repo_path: Path) -> None:
    """Reset local changes and sync with main branch."""
    print("\n[Step 1] Resetting and syncing with main...")

    run_command("git reset HEAD", cwd=repo_path, check=False)
    run_command("git restore .", cwd=repo_path)
    run_command("git checkout main", cwd=repo_path)
    run_command("git pull origin main", cwd=repo_path)

    # Initialize and update submodules recursively
    print("  Initializing and updating submodules...")
    run_command("git submodule update --init --recursive", cwd=repo_path)


def create_release_branch(repo_path: Path) -> str:
    """Create a new release branch with current date."""
    print("\n[Step 2] Creating release branch...")

    date_str = datetime.now().strftime("%m-%d")
    branch_name = f"bump/http-client-python-{date_str}"

    run_command(f"git checkout -b {branch_name}", cwd=repo_path)
    print(f"  Created branch: {branch_name}")

    return branch_name


def get_current_version(repo_path: Path) -> str:
    """Get the current version of @typespec/http-client-python from pnpm-workspace.yaml."""
    workspace_file = repo_path / "pnpm-workspace.yaml"
    try:
        content = workspace_file.read_text(encoding="utf-8")
    except (OSError, IOError) as e:
        raise RuntimeError(f"Failed to read pnpm-workspace.yaml: {e}")
    
    # Match pattern like "@typespec/http-client-python": ^0.31.1
    match = re.search(r'"@typespec/http-client-python":\s*\^?([\d.]+)', content)
    if match:
        return match.group(1)
    
    raise ValueError("Could not find @typespec/http-client-python version in pnpm-workspace.yaml")


def get_latest_npm_version() -> str:
    """Get the latest version of @typespec/http-client-python from npm."""
    print("\n  Checking latest npm version...")
    result = run_command("npm view @typespec/http-client-python version", check=False)
    if result.returncode == 0:
        return result.stdout.strip()
    raise RuntimeError("Failed to get latest npm version")


def update_version(repo_path: Path, new_version: str) -> None:
    """Update the @typespec/http-client-python version in pnpm-workspace.yaml."""
    print(f"\n[Step 3] Updating version to ^{new_version}...")

    workspace_file = repo_path / "pnpm-workspace.yaml"
    try:
        content = workspace_file.read_text(encoding="utf-8")
    except (OSError, IOError) as e:
        raise RuntimeError(f"Failed to read pnpm-workspace.yaml: {e}")
    
    # Replace the version
    new_content = re.sub(
        r'("@typespec/http-client-python":\s*)\^?[\d.]+',
        f'\\1^{new_version}',
        content
    )
    
    try:
        workspace_file.write_text(new_content, encoding="utf-8")
    except (OSError, IOError) as e:
        raise RuntimeError(f"Failed to write pnpm-workspace.yaml: {e}")
    print(f"  Updated pnpm-workspace.yaml")


def install_dependencies(repo_path: Path) -> None:
    """Run pnpm install to update the lock file."""
    print("\n[Step 4] Installing dependencies...")

    run_command("pnpm install --no-frozen-lockfile", cwd=repo_path)


def sync_test_cases(repo_path: Path) -> None:
    """Run pnpm sync to sync test cases from upstream."""
    print("\n[Step 5] Syncing test cases...")

    package_dir = repo_path / "packages" / "typespec-python"
    run_command("pnpm run sync", cwd=package_dir)


def commit_changes(repo_path: Path, new_version: str) -> None:
    """Commit all changes."""
    print("\n[Step 6] Committing changes...")

    run_command("git add -A", cwd=repo_path)
    run_command(f'git commit -m "Bump @typespec/http-client-python to ^{new_version} and sync tests"', cwd=repo_path)


def push_and_create_pr(repo_path: Path, branch_name: str, new_version: str) -> str | None:
    """Push the branch and create a PR. Returns the PR URL if successful."""
    print("\n[Step 7] Pushing branch...")

    run_command("git push -u origin HEAD", cwd=repo_path)

    print("\n[Step 8] Creating PR...")
    pr_title = f"[python] Bump @typespec/http-client-python to ^{new_version}"
    pr_body = f"Bump @typespec/http-client-python to ^{new_version} and sync test cases from upstream."
    
    result = run_command(
        f'gh pr create --title "{pr_title}" --body "{pr_body}" --base main',
        cwd=repo_path
    )
    print("  PR created successfully!")

    # Extract PR URL from output
    pr_url = None
    output = result.stdout + "\n" + result.stderr
    url_match = re.search(r"https://github\.com/[^\s]+/pull/\d+", output)
    if url_match:
        pr_url = url_match.group(0)

    return pr_url


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bump @typespec/http-client-python in Azure/typespec-azure and sync tests",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python typespec_azure_python_bump.py <path_to_typespec_azure_repo>
  python typespec_azure_python_bump.py <path_to_typespec_azure_repo> --version 0.32.0
  python typespec_azure_python_bump.py <path_to_typespec_azure_repo> --skip-pr
  python typespec_azure_python_bump.py C:\\dev\\typespec-azure
""",
    )
    parser.add_argument("repo_path", type=str, help="Path to the root of the Azure/typespec-azure repository")
    parser.add_argument("--version", type=str, help="Specific version to bump to (default: latest from npm)")
    parser.add_argument("--skip-pr", action="store_true", help="Skip creating the PR (useful for testing)")

    args = parser.parse_args()

    repo_path = Path(args.repo_path).resolve()

    if not repo_path.exists():
        print(f"Error: Repository path does not exist: {repo_path}", file=sys.stderr)
        sys.exit(1)

    workspace_file = repo_path / "pnpm-workspace.yaml"
    if not workspace_file.exists():
        print(f"Error: pnpm-workspace.yaml not found at: {workspace_file}", file=sys.stderr)
        sys.exit(1)

    print(f"Repository path: {repo_path}")

    try:
        # Step 1: Reset and sync
        reset_and_sync(repo_path)

        # Determine target version
        current_version = get_current_version(repo_path)
        print(f"\n  Current version: {current_version}")

        if args.version:
            new_version = args.version.lstrip("^")
        else:
            new_version = get_latest_npm_version()

        print(f"  Target version: {new_version}")

        # Use semantic version comparison
        try:
            if version.parse(current_version) >= version.parse(new_version):
                print(f"\n  Already at version {current_version} (>= {new_version}). Nothing to do.")
                sys.exit(0)
        except version.InvalidVersion:
            # Fall back to string comparison if parsing fails
            if current_version == new_version:
                print(f"\n  Already at version {new_version}. Nothing to do.")
                sys.exit(0)

        # Step 2: Create release branch
        branch_name = create_release_branch(repo_path)

        # Step 3: Update version
        update_version(repo_path, new_version)

        # Step 4: Install dependencies
        install_dependencies(repo_path)

        # Step 5: Sync test cases
        sync_test_cases(repo_path)

        # Step 6: Commit changes
        commit_changes(repo_path, new_version)

        # Step 7-8: Push and create PR
        if args.skip_pr:
            print("\n[Step 7-8] Skipping PR creation (--skip-pr flag)")
        else:
            pr_url = push_and_create_pr(repo_path, branch_name, new_version)
            if pr_url:
                show_pr_link_window(pr_url)

        print("\n" + "=" * 50)
        print("Bump workflow completed successfully!")
        print("=" * 50)

    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
