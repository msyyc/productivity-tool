#!/usr/bin/env python3
"""
Emitter Package Update Script

Automates bumping @azure-tools/typespec-python version in emitter-package.json
for the Azure SDK for Python repository and creates a PR.
"""

import argparse
import json
import re
import subprocess
import sys
import urllib.request
import webbrowser
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


def check_prerequisites() -> None:
    """Verify that all required tools are available."""
    print("\n[Step 0] Checking prerequisites...")

    # Check npm-check-updates
    result = run_command("npx --yes npm-check-updates --version", check=False)
    if result.returncode != 0:
        print("  npm-check-updates not found, installing globally...")
        run_command("npm install -g npm-check-updates")
        print("  npm-check-updates installed successfully.")
    else:
        print("  npm-check-updates is available.")

    # Check tsp-client
    result = run_command("tsp-client --version", check=False)
    if result.returncode != 0:
        print("  tsp-client not found, installing globally...")
        run_command("npm install -g @azure-tools/typespec-client-generator-cli")
        print("  tsp-client installed successfully.")
    else:
        print("  tsp-client is available.")

    # Check GitHub CLI
    result = run_command("gh --version", check=False)
    if result.returncode != 0:
        raise RuntimeError(
            "GitHub CLI (gh) is not installed. Please install it from https://cli.github.com/"
        )
    else:
        print("  GitHub CLI is available.")


def reset_and_sync(repo_path: Path) -> None:
    """Reset local changes and sync with main branch."""
    print("\n[Step 1] Resetting and syncing with main...")

    run_command("git reset HEAD", cwd=repo_path, check=False)
    run_command("git checkout .", cwd=repo_path)
    run_command("git clean -fd", cwd=repo_path)
    run_command("git checkout origin/main", cwd=repo_path)
    run_command("git pull origin main", cwd=repo_path)


def get_latest_version(repo_path: Path) -> str:
    """Determine the latest @azure-tools/typespec-python version."""
    print("\n[Step 2] Determining latest version...")

    result = run_command("npx npm-check-updates --packageFile eng/emitter-package.json", cwd=repo_path)

    # Parse the output to extract the version
    # Example output line: "@azure-tools/typespec-python  0.45.0  →  0.46.4"
    output = result.stdout + result.stderr
    match = re.search(r"@azure-tools/typespec-python\s+[\d.]+\s+→\s+([\d.]+)", output)

    if not match:
        # Try alternative pattern (may vary by npm-check-updates version)
        match = re.search(r"@azure-tools/typespec-python.*?([\d]+\.[\d]+\.[\d]+)\s*$", output, re.MULTILINE)

    if not match:
        raise RuntimeError(
            "Could not determine latest version of @azure-tools/typespec-python. "
            "Check if there are updates available."
        )

    version = match.group(1)
    print(f"  Latest version: {version}")

    return version


def create_feature_branch(repo_path: Path, version: str) -> str:
    """Create a new feature branch for the version bump."""
    print("\n[Step 3] Creating feature branch...")

    branch_name = f"bump-typespec-python-{version}"

    run_command(f"git checkout -b {branch_name}", cwd=repo_path)
    print(f"  Created branch: {branch_name}")

    return branch_name


def update_dependencies(repo_path: Path) -> None:
    """Apply the version update using npm-check-updates."""
    print("\n[Step 4] Updating dependencies...")

    run_command("npx npm-check-updates --packageFile eng/emitter-package.json -u", cwd=repo_path)
    print("  emitter-package.json updated.")


def align_openai_typespec_version(repo_path: Path) -> None:
    """Align @azure-tools/openai-typespec with the version pinned in azure-rest-api-specs."""
    print("\n[Step 5] Aligning @azure-tools/openai-typespec with spec repo...")

    spec_package_url = "https://raw.githubusercontent.com/Azure/azure-rest-api-specs/main/package.json"
    try:
        with urllib.request.urlopen(spec_package_url) as response:
            spec_package = json.loads(response.read().decode())
    except Exception as e:
        raise RuntimeError(f"Failed to fetch spec repo package.json: {e}")

    spec_version = spec_package.get("devDependencies", {}).get("@azure-tools/openai-typespec")
    if not spec_version:
        print("  @azure-tools/openai-typespec not found in spec repo, skipping.")
        return

    print(f"  Spec repo pins @azure-tools/openai-typespec at: {spec_version}")

    emitter_package_path = repo_path / "eng" / "emitter-package.json"
    with open(emitter_package_path, "r") as f:
        emitter_package = json.load(f)

    # Update in devDependencies if present, otherwise in dependencies
    updated = False
    for section in ("devDependencies", "dependencies", "overrides"):
        if section in emitter_package and "@azure-tools/openai-typespec" in emitter_package[section]:
            old_version = emitter_package[section]["@azure-tools/openai-typespec"]
            if old_version != spec_version:
                emitter_package[section]["@azure-tools/openai-typespec"] = spec_version
                print(f"  Updated {section}/@azure-tools/openai-typespec: {old_version} -> {spec_version}")
                updated = True
            else:
                print(f"  {section}/@azure-tools/openai-typespec already at {spec_version}, no change needed.")

    if updated:
        with open(emitter_package_path, "w") as f:
            json.dump(emitter_package, f, indent=2)
            f.write("\n")
        print("  emitter-package.json updated with aligned openai-typespec version.")
    else:
        print("  No openai-typespec version change required.")


def generate_lock_file(repo_path: Path) -> None:
    """Regenerate the lock file using tsp-client."""
    print("\n[Step 6] Regenerating lock file...")

    run_command("tsp-client generate-lock-file", cwd=repo_path)
    print("  emitter-package-lock.json regenerated.")


def commit_changes(repo_path: Path, version: str) -> None:
    """Stage and commit the changes."""
    print("\n[Step 7] Committing changes...")

    run_command("git add eng/emitter-package.json eng/emitter-package-lock.json", cwd=repo_path)
    run_command(f'git commit -m "bump typespec-python {version}"', cwd=repo_path)
    print("  Changes committed.")


def push_and_create_pr(repo_path: Path, branch_name: str, version: str) -> str | None:
    """Push the branch and create a PR. Returns the PR URL if successful."""
    print("\n[Step 8] Pushing branch...")

    run_command(f"git push -u origin {branch_name}", cwd=repo_path)

    print("\n[Step 9] Creating PR...")

    title = f"bump typespec-python {version}"
    body = f"Bump @azure-tools/typespec-python to version {version}"

    result = run_command(f'gh pr create --title "{title}" --body "{body}"', cwd=repo_path)
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
        description="Bump @azure-tools/typespec-python version in emitter-package.json and create a PR",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python emitter_package_update.py <path_to_azure_sdk_for_python_repo>
  python emitter_package_update.py <path_to_azure_sdk_for_python_repo> --skip-pr
  python emitter_package_update.py <path_to_azure_sdk_for_python_repo> --version 0.46.4
  python emitter_package_update.py C:\\dev\\azure-sdk-for-python
""",
    )
    parser.add_argument("repo_path", type=str, help="Path to the root of the Azure SDK for Python repository")
    parser.add_argument("--skip-pr", action="store_true", help="Skip creating the PR (useful for testing)")
    parser.add_argument(
        "--version", type=str, default=None, help="Specify a version to bump to (skips version detection)"
    )

    args = parser.parse_args()

    repo_path = Path(args.repo_path).resolve()
    emitter_package_path = repo_path / "eng" / "emitter-package.json"

    if not repo_path.exists():
        print(f"Error: Repository path does not exist: {repo_path}", file=sys.stderr)
        sys.exit(1)

    if not emitter_package_path.exists():
        print(f"Error: emitter-package.json does not exist: {emitter_package_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Repository path: {repo_path}")
    print(f"Emitter package: {emitter_package_path}")

    try:
        # Prerequisites
        check_prerequisites()

        # Step 1: Reset and sync
        reset_and_sync(repo_path)

        # Step 2: Determine latest version
        if args.version:
            version = args.version
            print(f"\n[Step 2] Using specified version: {version}")
        else:
            version = get_latest_version(repo_path)

        # Step 3: Create feature branch
        branch_name = create_feature_branch(repo_path, version)

        # Step 4: Update dependencies
        update_dependencies(repo_path)

        # Step 5: Align openai-typespec with spec repo
        align_openai_typespec_version(repo_path)

        # Step 6: Generate lock file
        generate_lock_file(repo_path)

        # Step 7: Commit changes
        commit_changes(repo_path, version)

        # Step 8-9: Push and create PR
        if args.skip_pr:
            print("\n[Step 8-9] Skipping PR creation (--skip-pr flag)")
        else:
            pr_url = push_and_create_pr(repo_path, branch_name, version)
            if pr_url:
                show_pr_link_window(pr_url)

        print("\n" + "=" * 50)
        print("Emitter package update completed successfully!")
        print(f"Version: {version}")
        print("=" * 50)

    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
