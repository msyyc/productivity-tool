#!/usr/bin/env python3
"""Detect unmerged AutoPR SDK pull requests approved by a reviewer.

Selection criteria (a PR is reported only if ALL hold):
  1. Title starts with ``[AutoPR azure-mgmt-``.
  2. The PR is open (not merged / not closed).
    3. The SDK version in the PR is NOT the excluded version (default: ``1.0.0b1``).

The SDK version is read from the added line of the package ``_version.py`` in the
PR diff. If that is unavailable, it falls back to the latest version heading in
``CHANGELOG.md``.

Output: a markdown table with columns
    id | PR link | sdk name | sdk version | PR created time | PR approved time | new commit after approval | release plan

All GitHub access goes through the GitHub CLI (``gh``).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Optional
from urllib.parse import parse_qs, urlparse

TITLE_PREFIX = "[AutoPR azure-mgmt-"
SDK_NAME_RE = re.compile(r"^\[AutoPR\s+(azure-mgmt-[^\]]+)\]")
VERSION_ADD_RE = re.compile(r'^\+\s*VERSION\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
CHANGELOG_HEADING_RE = re.compile(r"^##\s+([0-9][^\s(]*)", re.MULTILINE)
RELEASE_PLAN_LABEL_RE = re.compile(
    r"(?:\*\*)?release plan(?:\s+link)?(?:\*\*)?\s*[:：-]\s*(.+)", re.IGNORECASE | re.DOTALL
)
RELEASE_PLAN_SECTION_RE = re.compile(
    r"^#{1,6}\s*release plan\s*\n(.*?)(?=\n#{1,6}\s+|\Z)", re.IGNORECASE | re.MULTILINE | re.DOTALL
)
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]*\]\((https?://[^)\s]+)\)", re.IGNORECASE)
HTTP_LINK_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def run_gh(args: list[str]) -> str:
    """Run a ``gh`` command and return stdout, raising on failure."""
    proc = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed (exit {proc.returncode}):\n{proc.stderr.strip()}")
    return proc.stdout


def list_autopr_prs(repo: str, limit: int) -> list[dict]:
    """List open AutoPR azure-mgmt PRs, filtered by title prefix."""
    out = run_gh(
        [
            "pr",
            "list",
            "--repo",
            repo,
            "--search",
            "AutoPR azure-mgmt in:title",
            "--state",
            "open",
            "--json",
            "number,title,url,createdAt",
            "--limit",
            str(limit),
        ]
    )
    prs = json.loads(out)
    return [pr for pr in prs if pr["title"].startswith(TITLE_PREFIX)]


def sdk_name_from_title(title: str) -> Optional[str]:
    m = SDK_NAME_RE.match(title)
    return m.group(1) if m else None


def approved_time(repo: str, number: int, reviewer: str) -> Optional[str]:
    """Return the latest APPROVED review submittedAt for ``reviewer`` (ISO), or None."""
    out = run_gh(
        [
            "pr",
            "view",
            str(number),
            "--repo",
            repo,
            "--json",
            "reviews",
        ]
    )
    reviews = json.loads(out).get("reviews", [])
    return approved_time_from_reviews(reviews, reviewer)


def approved_time_from_reviews(reviews: list[dict], reviewer: str) -> Optional[str]:
    """Return the latest APPROVED review submittedAt for ``reviewer`` from review data."""
    approvals = [
        r["submittedAt"]
        for r in reviews
        if r.get("author", {}).get("login") == reviewer and r.get("state") == "APPROVED" and r.get("submittedAt")
    ]
    return max(approvals) if approvals else None


def pr_details(repo: str, number: int) -> dict:
    """Read PR reviews, commits, and body in one GitHub CLI call."""
    out = run_gh(
        [
            "pr",
            "view",
            str(number),
            "--repo",
            repo,
            "--json",
            "reviews,commits,body",
        ]
    )
    return json.loads(out)


def sdk_version(repo: str, number: int) -> Optional[str]:
    """Determine the SDK version from the PR diff (_version.py, then CHANGELOG.md)."""
    out = run_gh(
        [
            "api",
            "--paginate",
            f"repos/{repo}/pulls/{number}/files?per_page=100",
        ]
    )
    files = _parse_paginated_json(out)

    # Prefer the package _version.py
    for f in files:
        if f.get("filename", "").endswith("/_version.py") and f.get("patch"):
            m = VERSION_ADD_RE.search(f["patch"])
            if m:
                return m.group(1)

    # Fall back to CHANGELOG.md latest heading
    for f in files:
        if f.get("filename", "").endswith("/CHANGELOG.md") and f.get("patch"):
            added = "\n".join(line[1:] for line in f["patch"].splitlines() if line.startswith("+"))
            m = CHANGELOG_HEADING_RE.search(added)
            if m:
                return m.group(1)
    return None


def has_commits_after_approval(repo: str, number: int, approved_iso: str) -> str:
    """Return Yes when the PR has any commit after the approval timestamp."""
    out = run_gh(
        [
            "pr",
            "view",
            str(number),
            "--repo",
            repo,
            "--json",
            "commits",
        ]
    )
    commits = json.loads(out).get("commits", [])
    return has_commits_after_approval_from_commits(commits, approved_iso)


def has_commits_after_approval_from_commits(commits: list[dict], approved_iso: str) -> str:
    """Return Yes when any commit data is newer than the approval timestamp."""
    for commit in commits:
        committed_at = commit.get("committedDate")
        if committed_at and committed_at > approved_iso:
            return "Yes"
    return "No"


def release_plan(repo: str, number: int) -> str:
    """Extract release plan from the PR description."""
    out = run_gh(
        [
            "pr",
            "view",
            str(number),
            "--repo",
            repo,
            "--json",
            "body",
        ]
    )
    return extract_release_plan(json.loads(out).get("body") or "")


def extract_release_plan(body: str) -> str:
    """Extract a release plan link from a labeled line or markdown section."""
    label_match = RELEASE_PLAN_LABEL_RE.search(body)
    if label_match:
        return _first_http_link(label_match.group(1)) or "unknown"

    section_match = RELEASE_PLAN_SECTION_RE.search(body)
    if section_match:
        return _first_http_link(section_match.group(1)) or "unknown"

    return "unknown"


def _first_http_link(text: str) -> Optional[str]:
    markdown_match = MARKDOWN_LINK_RE.search(text)
    if markdown_match:
        return markdown_match.group(1)

    match = HTTP_LINK_RE.search(text)
    return match.group(0).rstrip(".,);]") if match else None


def _parse_paginated_json(text: str) -> list[dict]:
    """Parse output of ``gh api --paginate`` which may concatenate JSON arrays."""
    text = text.strip()
    if not text:
        return []
    # gh --paginate concatenates arrays as ``][`` between pages.
    normalized = text.replace("][", ",")
    return json.loads(normalized)


def iso_to_date(iso: Optional[str]) -> str:
    """Convert an ISO timestamp to ``YYYY-MM-DD`` (empty string if None)."""
    if not iso:
        return ""
    return iso[:10]


def build_markdown(rows: list[dict]) -> str:
    lines = [
        "| id | PR link | sdk name | sdk version | PR created time | PR approved time | new commit after approval | release plan |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for index, r in enumerate(rows, start=1):
        lines.append(
            "| "
            + " | ".join(
                [str(index)]
                + [
                    _format_markdown_cell(r[key])
                    for key in [
                        "url",
                        "sdk_name",
                        "version",
                        "created",
                        "approved",
                        "new_commit_after_approval",
                        "release_plan",
                    ]
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def sort_rows(rows: list[dict]) -> list[dict]:
    """Sort report rows by PR created date, newest first."""
    return sorted(rows, key=lambda row: row["created"], reverse=True)


def _format_markdown_cell(value: object) -> str:
    text = str(value)
    if HTTP_LINK_RE.fullmatch(text):
        return f"[{_link_label(text)}]({text})"
    return text.replace("|", r"\|")


def _link_label(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    release_plan_ids = query.get("releaseplan") or query.get("releasePlan")
    if release_plan_ids and release_plan_ids[0].isdigit():
        return release_plan_ids[0]

    last_segment = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    return last_segment if last_segment.isdigit() else "..."


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        default="Azure/azure-sdk-for-python",
        help="Target SDK repo (default: Azure/azure-sdk-for-python)",
    )
    parser.add_argument(
        "--reviewer",
        default="msyyc",
        help="Reviewer whose approval is required (default: msyyc)",
    )
    parser.add_argument(
        "--exclude-version",
        default="1.0.0b1",
        help="SDK version to exclude (default: 1.0.0b1)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Max PRs to fetch from the initial listing (default: 500)",
    )
    args = parser.parse_args()

    prs = list_autopr_prs(args.repo, args.limit)
    print(f"# Found {len(prs)} open AutoPR azure-mgmt PRs; filtering...", file=sys.stderr)

    rows: list[dict] = []
    for pr in prs:
        number = pr["number"]
        sdk_name = sdk_name_from_title(pr["title"])
        if not sdk_name:
            continue

        details = pr_details(args.repo, number)
        approved = approved_time_from_reviews(details.get("reviews", []), args.reviewer)

        version = sdk_version(args.repo, number)
        if version == args.exclude_version:
            print(f"#  PR #{number} {sdk_name}: version {version} excluded, skip", file=sys.stderr)
            continue

        new_commit_after_approval = (
            has_commits_after_approval_from_commits(details.get("commits", []), approved) if approved else "-"
        )
        plan = extract_release_plan(details.get("body") or "")

        rows.append(
            {
                "url": pr["url"],
                "sdk_name": sdk_name,
                "version": version or "unknown",
                "created": iso_to_date(pr["createdAt"]),
                "approved": iso_to_date(approved) if approved else "-",
                "new_commit_after_approval": new_commit_after_approval,
                "release_plan": plan,
            }
        )
        print(
            f"#  PR #{number} {sdk_name}: MATCH (version={version}, approved={iso_to_date(approved) if approved else '-'}, new_commit_after_approval={new_commit_after_approval}, release_plan={plan})",
            file=sys.stderr,
        )

    print(build_markdown(sort_rows(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
