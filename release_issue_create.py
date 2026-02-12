#!/usr/bin/env python3
"""
Release Issue Create Script

Searches for a package in the Azure REST API specs repo, generates a release
request issue title and body, creates the issue under Azure/sdk-release-request,
applies labels, cleans up bot comments, and reopens if auto-closed.
"""

import argparse
import json
import subprocess
import sys
import webbrowser
from datetime import datetime, timedelta


REST_REPO = "Azure/azure-rest-api-specs"
ISSUE_REPO = "Azure/sdk-release-request"
LABELS = "ManagementPlane,Python,assigned,auto-link,auto-ask-check"


def run_command(cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a shell command and return the result."""
    print(f"  Running: {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout.strip())
    if result.stderr:
        print(result.stderr.strip(), file=sys.stderr)
    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed with return code {result.returncode}")
    return result


def show_issue_link_window(issue_url: str) -> None:
    """Display a window with a clickable issue hyperlink."""
    try:
        import tkinter as tk
        from tkinter import font as tkfont

        root = tk.Tk()
        root.title("Issue Created Successfully")
        root.geometry("600x120")
        root.resizable(False, False)

        root.update_idletasks()
        x = (root.winfo_screenwidth() // 2) - (600 // 2)
        y = (root.winfo_screenheight() // 2) - (120 // 2)
        root.geometry(f"+{x}+{y}")
        root.attributes("-topmost", True)

        label = tk.Label(root, text="Issue created successfully! Click the link below:", pady=10)
        label.pack()

        link_font = tkfont.Font(family="TkDefaultFont", underline=True)
        link_label = tk.Label(root, text=issue_url, fg="blue", cursor="hand2", font=link_font)
        link_label.pack(pady=5)

        def open_link(event=None):
            webbrowser.open(issue_url)
            root.destroy()

        link_label.bind("<Button-1>", open_link)

        close_btn = tk.Button(root, text="Close", command=root.destroy, width=10)
        close_btn.pack(pady=10)

        root.mainloop()

    except ImportError:
        print(f"\nIssue URL: {issue_url}")
        print("(tkinter not available - please open the URL manually)")


def search_readme_python(package_name: str) -> str:
    """
    Search the REST API specs repo for a readme.python.md that contains
    the given package name. Returns the GitHub URL of the matching file.
    """
    print(f"\n[Step 1] Searching for readme.python.md containing '{package_name}'...")

    # Use GitHub search API via gh CLI to find readme.python.md files containing the package name
    result = run_command(
        f'gh search code "{package_name}" --repo {REST_REPO} --filename readme.python.md --json path,repository --limit 20'
    )

    items = json.loads(result.stdout.strip())
    if not items:
        raise RuntimeError(
            f"No readme.python.md found containing '{package_name}' in {REST_REPO}"
        )

    # Filter for resource-manager paths (management plane)
    matching_path = None
    for item in items:
        path = item.get("path", "")
        if "resource-manager" in path and path.endswith("readme.python.md"):
            matching_path = path
            break

    if not matching_path:
        # Fall back to first match
        matching_path = items[0].get("path", "")

    readme_url = f"https://github.com/{REST_REPO}/blob/main/{matching_path}"
    print(f"  Found: {readme_url}")
    return readme_url


def extract_service_name(readme_url: str) -> str:
    """
    Extract the SERVICE-NAME from the readme URL.
    SERVICE-NAME is the path segment right after 'specification/'.
    """
    parts = readme_url.split("/")
    try:
        spec_idx = parts.index("specification")
        service_name = parts[spec_idx + 1]
    except (ValueError, IndexError):
        raise RuntimeError(f"Could not extract service name from URL: {readme_url}")
    print(f"  Service name: {service_name}")
    return service_name


def get_target_url(readme_url: str) -> str:
    """Get the parent directory of the readme URL."""
    target_url = readme_url.rsplit("/", 1)[0]
    print(f"  Target URL: {target_url}")
    return target_url


def build_issue_title(service_name: str) -> str:
    """Build the issue title from the template."""
    title = f"[resource manager] Python: Release request for {service_name} (Python only)"
    print(f"\n[Step 2] Issue title: {title}")
    return title


def build_issue_body(target_url: str, tag: str, service_name: str, current_date: str) -> str:
    """Build the issue body from the template."""
    body = (
        f"{target_url}\n"
        f"->Readme Tag: {tag}\n"
        f"## Release request for <i>Release for {service_name}</i>\n"
        f"**Requested by @msyyc**\n"
        f"**Link**: [{target_url}]({target_url})  \n"
        f"**Namespace Approval Issue**:\n"
        f"**Readme Tag**: {tag}\n"
        f"**Target release date**: No later than {current_date} "
    )
    print(f"\n[Step 3] Issue body:\n{body}")
    return body


def create_issue(title: str, body: str) -> str:
    """Create a GitHub issue and return the issue URL."""
    print(f"\n[Step 4] Creating issue under {ISSUE_REPO}...")
    cmd = [
        "gh", "issue", "create",
        "--repo", ISSUE_REPO,
        "--title", title,
        "--body", body,
    ]
    print(f"  Running: gh issue create --repo {ISSUE_REPO} --title \"{title}\" --body <body>")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout.strip())
    if result.stderr:
        print(result.stderr.strip(), file=sys.stderr)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed with return code {result.returncode}")
    issue_url = result.stdout.strip().splitlines()[-1]
    print(f"  Issue created: {issue_url}")
    return issue_url


def add_labels(issue_url: str) -> None:
    """Add labels to the created issue."""
    print(f"\n[Step 5] Adding labels: {LABELS}...")
    # Extract issue number from URL
    issue_number = issue_url.rstrip("/").split("/")[-1]
    label_args = " ".join(f'--add-label "{l.strip()}"' for l in LABELS.split(","))
    run_command(
        f"gh issue edit {issue_number} --repo {ISSUE_REPO} {label_args}"
    )
    print("  Labels added.")


def delete_bot_comments(issue_url: str) -> None:
    """Delete comments from github-actions bot on the issue."""
    print("\n[Step 6] Deleting github-actions bot comments...")
    issue_number = issue_url.rstrip("/").split("/")[-1]

    # List comments on the issue
    result = run_command(
        f"gh api repos/{ISSUE_REPO}/issues/{issue_number}/comments --jq '.[] | select(.user.login == \"github-actions[bot]\" or .user.login == \"github-actions\") | .id'",
        check=False,
    )

    comment_ids = result.stdout.strip().splitlines()
    if not comment_ids or comment_ids == [""]:
        print("  No github-actions comments found.")
        return

    for cid in comment_ids:
        cid = cid.strip()
        if cid:
            print(f"  Deleting comment {cid}...")
            run_command(
                f"gh api repos/{ISSUE_REPO}/issues/comments/{cid} -X DELETE",
                check=False,
            )
    print("  Bot comments deleted.")


def reopen_if_closed(issue_url: str) -> None:
    """Check if the issue was auto-closed and reopen it."""
    print("\n[Step 7] Checking if issue is still open...")
    issue_number = issue_url.rstrip("/").split("/")[-1]

    result = run_command(
        f"gh issue view {issue_number} --repo {ISSUE_REPO} --json state"
    )
    state_info = json.loads(result.stdout.strip())
    state = state_info.get("state", "OPEN")

    if state != "OPEN":
        print(f"  Issue is {state}. Reopening...")
        run_command(f"gh issue reopen {issue_number} --repo {ISSUE_REPO}")
        print("  Issue reopened.")
    else:
        print("  Issue is already open.")


def main():
    parser = argparse.ArgumentParser(
        description="Create a release request issue for a Python SDK package."
    )
    parser.add_argument(
        "--sdk-name",
        required=True,
        help='The SDK package name, e.g. "azure-mgmt-authorization".',
    )
    parser.add_argument(
        "--tag",
        required=True,
        help="The readme tag for the release.",
    )
    args = parser.parse_args()

    package_name = args.sdk_name
    tag = args.tag

    # Current date + 4 days
    target_date = datetime.now() + timedelta(days=4)
    current_date = target_date.strftime("%m/%d/%Y")
    print(f"Target release date: {current_date}")

    # Step 1: Search for readme.python.md
    readme_url = search_readme_python(package_name)

    # Step 2: Extract service name and target URL
    service_name = extract_service_name(readme_url)
    target_url = get_target_url(readme_url)

    # Step 3-4: Build issue title and body
    title = build_issue_title(service_name)
    body = build_issue_body(target_url, tag, service_name, current_date)

    # Step 5: Create the issue
    issue_url = create_issue(title, body)

    # Step 6: Add labels
    add_labels(issue_url)

    # Step 7: Delete github-actions bot comments
    delete_bot_comments(issue_url)

    # Step 8: Reopen if closed
    reopen_if_closed(issue_url)

    # Step 9: Show the issue link
    print(f"\n✅ Issue URL: {issue_url}")
    show_issue_link_window(issue_url)


if __name__ == "__main__":
    main()
