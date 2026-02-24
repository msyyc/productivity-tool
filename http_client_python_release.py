#!/usr/bin/env python3
"""
HTTP Client Python Bump and Release Script

Creates a PR to bump dependencies and release a new version of the http-client-python package.
"""

import argparse
import json
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


def check_npm_check_updates() -> None:
    """Verify that npm-check-updates is available, install if needed."""
    print("\n[Step 0] Checking npm-check-updates availability...")

    result = run_command("npx npm-check-updates --version", check=False)

    if result.returncode != 0:
        print("  npm-check-updates not found, installing globally...")
        run_command("npm install -g npm-check-updates")
        print("  npm-check-updates installed successfully.")
    else:
        print("  npm-check-updates is available.")


def reset_and_sync(repo_path: Path) -> None:
    """Reset local changes and sync with main branch."""
    print("\n[Step 1] Resetting and syncing with main...")

    run_command("git reset HEAD", cwd=repo_path, check=False)
    run_command("git checkout .", cwd=repo_path)
    run_command("git checkout origin/main", cwd=repo_path)
    run_command("git pull origin main", cwd=repo_path)


def create_release_branch(repo_path: Path) -> str:
    """Create a new release branch with current date."""
    print("\n[Step 2] Creating release branch...")

    date_str = datetime.now().strftime("%m-%d")
    branch_name = f"publish/python-release-{date_str}"

    run_command(f"git checkout -b {branch_name}", cwd=repo_path)
    print(f"  Created branch: {branch_name}")

    return branch_name


def is_newer_version(new_ver: str, old_ver: str) -> bool:
    """
    Compare two version strings and return True if new_ver is newer than old_ver.
    Handles semver with pre-release tags like '0.1.0-alpha.32-dev.1'.
    """
    try:
        return version.parse(new_ver) > version.parse(old_ver)
    except Exception:
        # Fallback to string comparison if parsing fails
        return new_ver > old_ver


def update_dependencies(package_dir: Path) -> None:
    """Update @typespec/* and @azure-tools/* dependencies."""
    print("\n[Step 3] Updating dependencies with npm-check-updates...")

    package_json_path = package_dir / "package.json"

    # Save current versions before running npm-check-updates
    with open(package_json_path, "r", encoding="utf-8") as f:
        original_package_data = json.load(f)

    original_deps = {
        **original_package_data.get("dependencies", {}),
        **original_package_data.get("devDependencies", {}),
    }

    run_command(
        "npx npm-check-updates -u --filter @typespec/*,@azure-tools/* --packageFile package.json", cwd=package_dir
    )

    # Restore versions where the original was newer (e.g., dev versions)
    with open(package_json_path, "r", encoding="utf-8") as f:
        updated_package_data = json.load(f)

    for dep_type in ["dependencies", "devDependencies"]:
        if dep_type not in updated_package_data:
            continue
        for pkg, new_version_range in updated_package_data[dep_type].items():
            if pkg not in original_deps:
                continue

            original_version = original_deps[pkg].lstrip("^~")
            new_version = new_version_range.lstrip("^~")

            if is_newer_version(original_version, new_version):
                # Original version was newer, restore it
                updated_package_data[dep_type][pkg] = original_deps[pkg]
                print(f"  Keeping {pkg}: {original_deps[pkg]} (newer than {new_version_range})")

    with open(package_json_path, "w", encoding="utf-8") as f:
        json.dump(updated_package_data, f, indent=2)
        f.write("\n")


def update_peer_dependencies(package_dir: Path) -> None:
    """Update peerDependencies in package.json based on updated dependencies."""
    print("\n[Step 4] Updating peerDependencies...")

    package_json_path = package_dir / "package.json"

    with open(package_json_path, "r", encoding="utf-8") as f:
        package_data = json.load(f)

    dependencies = package_data.get("dependencies", {})
    dev_dependencies = package_data.get("devDependencies", {})
    peer_dependencies = package_data.get("peerDependencies", {})

    # Merge dependencies to get latest versions
    all_deps = {**dependencies, **dev_dependencies}

    updated_peer_deps = {}
    for pkg, version_range in peer_dependencies.items():
        if pkg in all_deps:
            new_version = all_deps[pkg].lstrip("^~")

            # Check the format of the peer dependency
            if version_range.startswith(">=") and "<" in version_range:
                # Format: ">=0.a.b <1.0.0" - update only the first version part
                # Extract the upper bound (e.g., "<1.0.0")
                parts = version_range.split("<")
                if len(parts) == 2:
                    upper_bound = "<" + parts[1].strip()
                    updated_peer_deps[pkg] = f">={new_version} {upper_bound}"
                    print(f"  {pkg}: '{version_range}' -> '>={new_version} {upper_bound}'")
                else:
                    updated_peer_deps[pkg] = version_range
            elif version_range.startswith("^"):
                # Format: "^1.a.b" - update to latest version
                updated_peer_deps[pkg] = f"^{new_version}"
                print(f"  {pkg}: '{version_range}' -> '^{new_version}'")
            else:
                # Keep unchanged for other formats
                updated_peer_deps[pkg] = version_range
                print(f"  {pkg}: kept unchanged '{version_range}'")
        else:
            updated_peer_deps[pkg] = version_range
            print(f"  {pkg}: not found in dependencies, keeping '{version_range}'")

    package_data["peerDependencies"] = updated_peer_deps

    with open(package_json_path, "w", encoding="utf-8") as f:
        json.dump(package_data, f, indent=2)
        f.write("\n")  # Add trailing newline

    print("  peerDependencies updated in package.json")


def run_version_change(package_dir: Path) -> None:
    """Run the version change script."""
    print("\n[Step 5] Running version change script...")

    run_command("npm run change:version", cwd=package_dir)


def build_and_commit(package_dir: Path) -> None:
    """Install dependencies, build, and commit changes."""
    print("\n[Step 6] Installing dependencies and building...")

    run_command("npm install", cwd=package_dir)
    run_command("npm run build", cwd=package_dir)

    print("\n[Step 7] Committing changes...")
    run_command("git add -u", cwd=package_dir)
    run_command('git commit -m "bump version"', cwd=package_dir)


def push_and_create_pr(repo_path: Path, branch_name: str) -> str | None:
    """Push the branch and create a PR. Returns the PR URL if successful."""
    print("\n[Step 8] Pushing branch...")

    # Use -u to set upstream tracking branch
    run_command("git push -u origin HEAD", cwd=repo_path)

    print("\n[Step 9] Creating PR...")
    result = run_command('gh pr create --title "[python] release new version" --body "" --base main', cwd=repo_path)
    print("  PR created successfully!")

    # Extract PR URL from output
    pr_url = None
    output = result.stdout + result.stderr
    # gh pr create typically outputs the PR URL
    url_match = re.search(r"https://github\.com/[^\s]+/pull/\d+", output)
    if url_match:
        pr_url = url_match.group(0)

    return pr_url


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bump dependencies and release a new version of http-client-python",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python http_client_python_release.py <path_to_typespec_repo>
  python http_client_python_release.py <path_to_typespec_repo> --skip-pr
  python http_client_python_release.py <path_to_typespec_repo> --skip-build
  python http_client_python_release.py C:\\dev\\typespec
""",
    )
    parser.add_argument("repo_path", type=str, help="Path to the root of the microsoft/typespec repository")
    parser.add_argument("--skip-pr", action="store_true", help="Skip creating the PR (useful for testing)")
    parser.add_argument("--skip-build", action="store_true", help="Skip the build step (useful for testing)")

    args = parser.parse_args()

    repo_path = Path(args.repo_path).resolve()
    package_dir = repo_path / "packages" / "http-client-python"

    if not repo_path.exists():
        print(f"Error: Repository path does not exist: {repo_path}", file=sys.stderr)
        sys.exit(1)

    if not package_dir.exists():
        print(f"Error: Package directory does not exist: {package_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Repository path: {repo_path}")
    print(f"Package directory: {package_dir}")

    try:
        # Prerequisites
        check_npm_check_updates()

        # Step 1: Reset and sync
        reset_and_sync(repo_path)

        # Step 2: Create release branch
        branch_name = create_release_branch(repo_path)

        # Step 3: Update dependencies
        update_dependencies(package_dir)

        # Step 4: Update peer dependencies
        update_peer_dependencies(package_dir)

        # Step 5: Run version change
        run_version_change(package_dir)

        # Step 6-7: Build and commit
        if args.skip_build:
            print("\n[Step 6-7] Skipping build (--skip-build flag)")
            run_command("git add -u", cwd=package_dir)
            run_command('git commit -m "bump version"', cwd=package_dir)
        else:
            build_and_commit(package_dir)

        # Step 8-9: Push and create PR
        if args.skip_pr:
            print("\n[Step 8-9] Skipping PR creation (--skip-pr flag)")
        else:
            pr_url = push_and_create_pr(repo_path, branch_name)
            if pr_url:
                show_pr_link_window(pr_url)

        print("\n" + "=" * 50)
        print("Release workflow completed successfully!")
        print("=" * 50)

    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
