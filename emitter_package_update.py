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
        raise RuntimeError("GitHub CLI (gh) is not installed. Please install it from https://cli.github.com/")
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


TYPESPEC_PYTHON = "@azure-tools/typespec-python"
EMITTER_PACKAGE_SECTIONS = ("dependencies", "devDependencies", "overrides")


def read_emitter_package(repo_path: Path) -> dict:
    """Read and parse eng/emitter-package.json."""
    emitter_package_path = repo_path / "eng" / "emitter-package.json"
    with open(emitter_package_path, "r") as f:
        return json.load(f)


def get_package_version(emitter_package: dict, package: str) -> str | None:
    """Look up a package version across the known dependency sections."""
    for section in EMITTER_PACKAGE_SECTIONS:
        if package in emitter_package.get(section, {}):
            return emitter_package[section][package]
    return None


def emitter_package_has_changes(repo_path: Path) -> bool:
    """Return True if eng/emitter-package.json differs from HEAD."""
    result = run_command(
        "git diff --quiet -- eng/emitter-package.json", cwd=repo_path, check=False
    )
    # git diff --quiet exits with 1 when there are differences, 0 when there are none.
    return result.returncode != 0


def discard_emitter_package_changes(repo_path: Path) -> None:
    """Revert any local edits to eng/emitter-package.json."""
    run_command("git checkout -- eng/emitter-package.json", cwd=repo_path, check=False)


def pin_package_version(repo_path: Path, package: str, version: str) -> None:
    """Force a specific version for a package in eng/emitter-package.json."""
    emitter_package_path = repo_path / "eng" / "emitter-package.json"
    emitter_package = read_emitter_package(repo_path)

    for section in EMITTER_PACKAGE_SECTIONS:
        if package in emitter_package.get(section, {}):
            emitter_package[section][package] = version
            break
    else:
        emitter_package.setdefault("dependencies", {})[package] = version

    with open(emitter_package_path, "w") as f:
        json.dump(emitter_package, f, indent=2)
        f.write("\n")
    print(f"  Pinned {package} to {version}")


def create_feature_branch(repo_path: Path, branch_name: str) -> str:
    """Create a new feature branch, carrying over the working-tree changes."""
    print("\n[Step 3] Creating feature branch...")

    run_command(f"git checkout -b {branch_name}", cwd=repo_path)
    print(f"  Created branch: {branch_name}")

    return branch_name


def update_dependencies(repo_path: Path) -> None:
    """Apply the version update using npm-check-updates."""
    print("\n[Step 4] Updating dependencies...")

    run_command("npx npm-check-updates --packageFile eng/emitter-package.json -u", cwd=repo_path)
    print("  emitter-package.json updated.")


def align_spec_repo_versions(repo_path: Path) -> None:
    """Align @azure-tools/openai-typespec and @typespec/openapi3 with the versions pinned in azure-rest-api-specs."""
    print("\n[Step 5] Aligning packages with spec repo versions...")

    spec_package_url = "https://raw.githubusercontent.com/Azure/azure-rest-api-specs/main/package.json"
    try:
        with urllib.request.urlopen(spec_package_url) as response:
            spec_package = json.loads(response.read().decode())
    except Exception as e:
        raise RuntimeError(f"Failed to fetch spec repo package.json: {e}")

    packages_to_align = ["@azure-tools/openai-typespec", "@typespec/openapi3"]

    # Collect spec versions for each package
    spec_versions = {}
    for pkg in packages_to_align:
        version = spec_package.get("dependencies", {}).get(pkg) or spec_package.get("devDependencies", {}).get(pkg)
        if version:
            spec_versions[pkg] = version
            print(f"  Spec repo pins {pkg} at: {version}")
        else:
            print(f"  {pkg} not found in spec repo, skipping.")

    if not spec_versions:
        print("  No packages to align.")
        return

    emitter_package_path = repo_path / "eng" / "emitter-package.json"
    with open(emitter_package_path, "r") as f:
        emitter_package = json.load(f)

    updated = False
    for pkg, spec_version in spec_versions.items():
        found = False
        for section in ("devDependencies", "dependencies", "overrides"):
            if section in emitter_package and pkg in emitter_package[section]:
                found = True
                old_version = emitter_package[section][pkg]
                if old_version != spec_version:
                    emitter_package[section][pkg] = spec_version
                    print(f"  Updated {section}/{pkg}: {old_version} -> {spec_version}")
                    updated = True
                else:
                    print(f"  {section}/{pkg} already at {spec_version}, no change needed.")
        if not found:
            # Add to devDependencies if the package doesn't exist yet
            if "devDependencies" not in emitter_package:
                emitter_package["devDependencies"] = {}
            emitter_package["devDependencies"][pkg] = spec_version
            print(f"  Added {pkg}: {spec_version} to devDependencies")
            updated = True

    if updated:
        with open(emitter_package_path, "w") as f:
            json.dump(emitter_package, f, indent=2)
            f.write("\n")
        print("  emitter-package.json updated with aligned versions.")
    else:
        print("  No version changes required.")


def generate_lock_file(repo_path: Path) -> None:
    """Regenerate the lock file using tsp-client."""
    print("\n[Step 6] Regenerating lock file...")

    run_command("tsp-client generate-lock-file", cwd=repo_path)
    print("  emitter-package-lock.json regenerated.")


def commit_changes(repo_path: Path, message: str) -> None:
    """Stage and commit the changes."""
    print("\n[Step 7] Committing changes...")

    run_command("git add eng/emitter-package.json eng/emitter-package-lock.json", cwd=repo_path)
    run_command(f'git commit -m "{message}"', cwd=repo_path)
    print("  Changes committed.")


def push_and_create_pr(repo_path: Path, branch_name: str, title: str, body: str) -> str | None:
    """Push the branch and create a PR. Returns the PR URL if successful."""
    print("\n[Step 8] Pushing branch...")

    run_command(f"git push -u origin {branch_name}", cwd=repo_path)

    print("\n[Step 9] Creating PR...")

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

        # Record the typespec-python version before any updates.
        old_typespec_version = get_package_version(read_emitter_package(repo_path), TYPESPEC_PYTHON)

        # Step 2: Apply updates on the working tree (still on main).
        print("\n[Step 2] Updating dependencies...")
        update_dependencies(repo_path)
        align_spec_repo_versions(repo_path)

        # If a specific version was requested, pin typespec-python to it.
        if args.version:
            pin_package_version(repo_path, TYPESPEC_PYTHON, args.version)

        # Determine whether anything actually changed across all dependencies.
        if not emitter_package_has_changes(repo_path):
            discard_emitter_package_changes(repo_path)
            print("\n" + "=" * 50)
            print("All dependencies are already up to date. Nothing to change.")
            print("=" * 50)
            return

        # Read the (possibly updated) typespec-python version for naming/messages.
        new_typespec_version = get_package_version(read_emitter_package(repo_path), TYPESPEC_PYTHON)
        typespec_bumped = new_typespec_version is not None and new_typespec_version != old_typespec_version

        if typespec_bumped:
            branch_name = f"bump-typespec-python-{new_typespec_version}"
            commit_message = f"bump typespec-python {new_typespec_version}"
            pr_title = f"bump typespec-python {new_typespec_version}"
            pr_body = f"Bump {TYPESPEC_PYTHON} to version {new_typespec_version}"
        else:
            branch_name = "update-emitter-package-dependencies"
            commit_message = "update emitter-package dependencies"
            pr_title = "update emitter-package dependencies"
            pr_body = "Update emitter-package.json dependencies to their latest aligned versions."

        # Step 3: Create feature branch (carries over the working-tree changes).
        create_feature_branch(repo_path, branch_name)

        # Step 6: Generate lock file
        generate_lock_file(repo_path)

        # Step 7: Commit changes
        commit_changes(repo_path, commit_message)

        # Step 8-9: Push and create PR
        if args.skip_pr:
            print("\n[Step 8-9] Skipping PR creation (--skip-pr flag)")
        else:
            pr_url = push_and_create_pr(repo_path, branch_name, pr_title, pr_body)
            if pr_url:
                show_pr_link_window(pr_url)

        print("\n" + "=" * 50)
        print("Emitter package update completed successfully!")
        if typespec_bumped:
            print(f"typespec-python: {old_typespec_version} -> {new_typespec_version}")
        else:
            print("typespec-python unchanged; other dependencies were updated.")
        print("=" * 50)

    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
