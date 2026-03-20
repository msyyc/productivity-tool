"""
Compare swagger and typespec code reports to produce a breaking change changelog.

Usage:
    python compare_reports.py <package-name> <sdk-package-path> [--base-dir <dir>]

Example:
    python compare_reports.py azure-mgmt-securityinsights sdk/securityinsight/azure-mgmt-securityinsight --base-dir C:/dev
"""

import argparse
import os
import re
import subprocess
import sys


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


def parse_changelog(output):
    """Extract changelog content between the start/end markers."""
    match = re.search(
        r"===== changelog start =====\s*\n(.*?)===== changelog end =====",
        output,
        re.DOTALL,
    )
    if match:
        return match.group(1).strip()
    return None


def update_changelog(changelog_path, changelog_content):
    """Insert changelog content under the first ## version heading in CHANGELOG.md."""
    if not os.path.isfile(changelog_path):
        print(f"Warning: CHANGELOG.md not found at {changelog_path}, creating new one")
        with open(changelog_path, "w", encoding="utf-8") as f:
            f.write("# Release History\n\n## 1.0.0b1 (Unreleased)\n\n")
            f.write(changelog_content + "\n")
        return

    with open(changelog_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Find the first ## version heading and insert changelog after it
    match = re.search(r"(##\s+\S+.*\n)", content)
    if match:
        insert_pos = match.end()
        # Remove any existing content between this heading and the next ## heading
        next_heading = re.search(r"\n##\s+", content[insert_pos:])
        if next_heading:
            end_pos = insert_pos + next_heading.start()
        else:
            end_pos = len(content)

        new_content = (
            content[:insert_pos]
            + "\n"
            + changelog_content
            + "\n"
            + content[end_pos:]
        )
    else:
        new_content = content + "\n" + changelog_content + "\n"

    with open(changelog_path, "w", encoding="utf-8") as f:
        f.write(new_content)


def main():
    parser = argparse.ArgumentParser(description="Compare code reports and generate changelog")
    parser.add_argument("package_name", help="Full package name (e.g. azure-mgmt-securityinsights)")
    parser.add_argument("sdk_package_path", help="Relative path to SDK package dir (e.g. sdk/securityinsight/azure-mgmt-securityinsight)")
    parser.add_argument("--sdk-dir", required=True,
                        help="Path to SDK repo (or worktree)")
    args = parser.parse_args()

    sdk_repo = os.path.abspath(args.sdk_dir)
    venv_path = os.path.join(sdk_repo, ".venv")
    activate = os.path.join(venv_path, "Scripts", "activate.bat")
    pkg_dir = os.path.join(sdk_repo, args.sdk_package_path)

    for path, label in [
        (sdk_repo, "SDK repo"),
        (activate, "Activate script"),
        (pkg_dir, "Package directory"),
    ]:
        if not os.path.exists(path):
            print(f"Error: {label} not found at {path}")
            sys.exit(1)

    swagger_report = os.path.join(pkg_dir, "code_report_swagger.json")
    typespec_report = os.path.join(pkg_dir, "code_report_typespec.json")
    changelog_path = os.path.join(pkg_dir, "CHANGELOG.md")

    for path, label in [
        (swagger_report, "Swagger code report"),
        (typespec_report, "TypeSpec code report"),
    ]:
        if not os.path.isfile(path):
            print(f"Error: {label} not found at {path}")
            sys.exit(1)

    print(f"Package:        {args.package_name}")
    print(f"Package dir:    {pkg_dir}")
    print(f"Swagger report: {swagger_report}")
    print(f"TypeSpec report: {typespec_report}")

    # 1. Run azpysdk breaking comparison
    print("\n" + "=" * 60)
    print("Step 1: Compare code reports")
    print("=" * 60)
    result = run_cmd(
        f'call "{activate}" && azpysdk breaking --source-report ./code_report_swagger.json --target-report ./code_report_typespec.json --changelog',
        cwd=pkg_dir,
        check=False,
    )

    full_output = result.stdout + "\n" + result.stderr

    # 2. Parse changelog from output
    print("\n" + "=" * 60)
    print("Step 2: Parse changelog")
    print("=" * 60)
    changelog_content = parse_changelog(full_output)
    if not changelog_content:
        print("No changelog content found in output.")
        print("This may mean there are no breaking changes or features added.")
        changelog_content = "### Other Changes\n\n  - Migrated from Swagger to TypeSpec"

    print("Parsed changelog:")
    print(changelog_content)

    # 3. Update CHANGELOG.md
    print("\n" + "=" * 60)
    print("Step 3: Update CHANGELOG.md")
    print("=" * 60)
    update_changelog(changelog_path, changelog_content)
    print(f"Updated: {changelog_path}")

    # 4. Show result and commit
    print("\n" + "=" * 60)
    print("Step 4: Git status and commit")
    print("=" * 60)
    run_cmd("git status", cwd=sdk_repo)
    run_cmd('git add . && git commit -m "changelog from report comparison"', cwd=sdk_repo)

    # Output for session state parsing
    print("\n" + "=" * 60)
    print("=== SESSION_STATE ===")
    print(f"changelog_path={changelog_path.replace(os.sep, '/')}")
    has_breaking = "### Breaking Changes" in changelog_content
    print(f"has_breaking_changes={'true' if has_breaking else 'false'}")
    print("=" * 60)
    print("\nDone! Changelog generated and committed.")


if __name__ == "__main__":
    main()
