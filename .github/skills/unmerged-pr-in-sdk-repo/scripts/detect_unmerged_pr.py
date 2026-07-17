#!/usr/bin/env python3
"""Detect unmerged AutoPR SDK pull requests approved by a reviewer.

Selection criteria (a PR is reported only if ALL hold):
  1. Title starts with ``[AutoPR azure-mgmt-``.
  2. The PR is open (not merged / not closed).
  3. The PR has been APPROVED by the given reviewer (default: ``msyyc``).
  4. The SDK version in the PR is NOT the excluded version (default: ``1.0.0b1``).

The SDK version is read from the added line of the package ``_version.py`` in the
PR diff. If that is unavailable, it falls back to the latest version heading in
``CHANGELOG.md``.

Output: a markdown table with columns
  PR link | sdk name | PR created time | PR approved time

All GitHub access goes through the GitHub CLI (``gh``).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Optional

TITLE_PREFIX = "[AutoPR azure-mgmt-"
SDK_NAME_RE = re.compile(r"^\[AutoPR\s+(azure-mgmt-[^\]]+)\]")
VERSION_ADD_RE = re.compile(r'^\+\s*VERSION\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
CHANGELOG_HEADING_RE = re.compile(r"^##\s+([0-9][^\s(]*)", re.MULTILINE)


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
    approvals = [
        r["submittedAt"]
        for r in reviews
        if r.get("author", {}).get("login") == reviewer and r.get("state") == "APPROVED" and r.get("submittedAt")
    ]
    return max(approvals) if approvals else None


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
        "| PR link | sdk name | sdk version | PR created time | PR approved time |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        lines.append(f"| {r['url']} | {r['sdk_name']} | {r['version']} | {r['created']} | {r['approved']} |")
    return "\n".join(lines)


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

        approved = approved_time(args.repo, number, args.reviewer)
        if not approved:
            print(f"#  PR #{number} {sdk_name}: not approved by {args.reviewer}, skip", file=sys.stderr)
            continue

        version = sdk_version(args.repo, number)
        if version == args.exclude_version:
            print(f"#  PR #{number} {sdk_name}: version {version} excluded, skip", file=sys.stderr)
            continue

        rows.append(
            {
                "url": pr["url"],
                "sdk_name": sdk_name,
                "version": version or "unknown",
                "created": iso_to_date(pr["createdAt"]),
                "approved": iso_to_date(approved),
            }
        )
        print(f"#  PR #{number} {sdk_name}: MATCH (version={version})", file=sys.stderr)

    rows.sort(key=lambda r: r["approved"], reverse=True)
    print(build_markdown(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
