#!/usr/bin/env python
"""Find azure-mgmt-* packages whose latest CHANGELOG version is not yet on PyPI.

Steps:
  1. Resolve the local azure-sdk-for-python clone (via `.env` at the
     productivity-tool repo root, falling back to ``C:/dev/azure-sdk-for-python``).
  2. Sync the local clone to ``origin/main`` (skip with ``--skip-sync``).
  3. Discover all CHANGELOG.md files matching ``sdk/*/azure-mgmt-*/CHANGELOG.md``.
  4. Parse the latest version section header (``## <version> (<date>)``) and check
     whether that version exists on PyPI.
  5. Print the results (unreleased versions only) as a Markdown table to stdout.

Usage:
    python check_unreleased_mgmt.py [--repo-root PATH] [--workers N] [--skip-sync]
"""

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Tuple

# Matches a CHANGELOG section header, e.g. "## 26.0.0b1 (2026-06-08)".
VERSION_HEADER_RE = re.compile(r"^##\s+([0-9][\w.+-]*)\s*(?:\(([^)]*)\))?\s*$")

GITHUB_BLOB_BASE = "https://github.com/Azure/azure-sdk-for-python/blob/main"
PYPI_JSON_URL = "https://pypi.org/pypi/{package}/json"
PYPI_PROJECT_URL = "https://pypi.org/project/{package}/#history"

# Packages excluded from the unreleased-version scan.
SKIP_PACKAGES = {"azure-mgmt-core"}

# Skip packages whose latest CHANGELOG entry is older than this many months.
MAX_AGE_MONTHS = 6


def _read_env_file(env_path: Path) -> dict:
    """Parse a simple KEY=VALUE .env file."""
    env_vars = {}
    try:
        with env_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    env_vars[key.strip()] = value.strip().strip("\"'")
    except OSError:
        pass
    return env_vars


def resolve_sdk_repo() -> Path:
    """Resolve the local azure-sdk-for-python clone path.

    Order:
      1. `.env` at the productivity-tool repo root with `LOCAL_AZURE_SDK_REPO`.
      2. Default to `C:/dev/azure-sdk-for-python`.
    """
    # scripts -> unreleased-sdk -> skills -> .github -> repo root
    repo_root = Path(__file__).resolve().parents[4]
    env_vars = _read_env_file(repo_root / ".env") if (repo_root / ".env").is_file() else {}
    sdk_val = env_vars.get("LOCAL_AZURE_SDK_REPO")
    return Path(sdk_val) if sdk_val else Path("C:/dev/azure-sdk-for-python")


def sync_repo(repo_root: Path) -> None:
    """Reset and fast-forward the local SDK repo to origin/main before scanning."""
    cmd = (
        "git reset HEAD && git checkout . && git clean -fd && "
        "git fetch origin main && git checkout origin/main && git pull origin main"
    )
    print(f"$ ({repo_root}) {cmd}", file=sys.stderr)
    proc = subprocess.run(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        shell=True,
    )
    if proc.stdout:
        print(proc.stdout.rstrip(), file=sys.stderr)
    if proc.returncode != 0:
        print(f"WARNING: SDK repo sync failed (exit {proc.returncode})", file=sys.stderr)
        if proc.stderr:
            print(proc.stderr.rstrip(), file=sys.stderr)


def find_changelogs(repo_root: Path):
    """Yield CHANGELOG.md paths matching sdk/*/azure-mgmt-*/CHANGELOG.md."""
    return sorted(repo_root.glob("sdk/*/azure-mgmt-*/CHANGELOG.md"))


def parse_latest_version(changelog: Path) -> Optional[Tuple[str, Optional[str]]]:
    """Return the (version, date) of the first (latest) CHANGELOG section, or None.

    ``date`` is the raw string captured from the header (e.g. "2026-06-08") or None
    when the header has no date.
    """
    try:
        with changelog.open("r", encoding="utf-8") as handle:
            for line in handle:
                match = VERSION_HEADER_RE.match(line.strip())
                if match:
                    return match.group(1), match.group(2)
    except OSError:
        return None
    return None


def _months_ago(reference: date, months: int) -> date:
    """Return the date ``months`` calendar months before ``reference``."""
    month_index = reference.month - 1 - months
    year = reference.year + month_index // 12
    month = month_index % 12 + 1
    # Clamp the day to the last valid day of the target month.
    day = min(
        reference.day,
        [
            31,
            29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
            31,
            30,
            31,
            30,
            31,
            31,
            30,
            31,
            30,
            31,
        ][month - 1],
    )
    return date(year, month, day)


def is_older_than_max_age(date_str: Optional[str]) -> bool:
    """Return True if date_str is a parseable date older than MAX_AGE_MONTHS.

    Unparseable or missing dates return False (kept in the results).
    """
    if not date_str:
        return False
    parsed = None
    for fmt in ("%Y-%m-%d", "%Y-%m", "%m/%d/%Y"):
        try:
            parsed = datetime.strptime(date_str.strip(), fmt).date()
            break
        except ValueError:
            continue
    if parsed is None:
        return False
    return parsed < _months_ago(date.today(), MAX_AGE_MONTHS)


def is_version_on_pypi(package: str, version: str) -> bool:
    """Return True if the given version of package is published on PyPI."""
    url = PYPI_JSON_URL.format(package=package)
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            data = json.load(response)
    except urllib.error.HTTPError as err:
        if err.code == 404:
            # Package itself has never been published.
            return False
        raise
    releases = data.get("releases", {})
    return version in releases


def github_changelog_link(repo_root: Path, changelog: Path) -> str:
    rel = changelog.relative_to(repo_root).as_posix()
    return f"{GITHUB_BLOB_BASE}/{rel}"


def process(repo_root: Path, changelog: Path) -> Optional[Tuple[str, str, str, str]]:
    """Return a result row if the latest version is unreleased, else None."""
    package = changelog.parent.name
    if package in SKIP_PACKAGES:
        return None
    parsed = parse_latest_version(changelog)
    if not parsed:
        return None
    version, date_str = parsed
    # Skip stale entries whose latest CHANGELOG date is older than MAX_AGE_MONTHS.
    if is_older_than_max_age(date_str):
        return None
    if is_version_on_pypi(package, version):
        return None
    changelog_link = github_changelog_link(repo_root, changelog)
    pypi_link = PYPI_PROJECT_URL.format(package=package)
    return (package, version, changelog_link, pypi_link)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Path to the azure-sdk-for-python repo root "
        "(default: resolved from .env LOCAL_AZURE_SDK_REPO or C:/dev/azure-sdk-for-python).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=16,
        help="Number of concurrent PyPI lookups (default: 16).",
    )
    parser.add_argument(
        "--skip-sync",
        action="store_true",
        help="Skip syncing the local SDK repo to origin/main before scanning.",
    )
    args = parser.parse_args()

    repo_root = (args.repo_root or resolve_sdk_repo()).resolve()
    if not repo_root.is_dir():
        print(f"ERROR: azure-sdk-for-python repo not found at {repo_root}", file=sys.stderr)
        return 2

    if not args.skip_sync:
        sync_repo(repo_root)

    changelogs = find_changelogs(repo_root)
    print(f"Repo root: {repo_root}", file=sys.stderr)
    print(f"Found {len(changelogs)} azure-mgmt-* CHANGELOG.md files.", file=sys.stderr)

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(process, repo_root, cl): cl for cl in changelogs}
        for future in as_completed(futures):
            changelog = futures[future]
            try:
                row = future.result()
            except Exception as exc:  # noqa: BLE001 - report and continue
                print(f"  ! Error processing {changelog.parent.name}: {exc}", file=sys.stderr)
                continue
            if row:
                print(f"  - Unreleased: {row[0]} {row[1]}", file=sys.stderr)
                results.append(row)

    results.sort(key=lambda r: r[0])

    lines = [
        "# Unreleased azure-mgmt-* Packages",
        "",
        f"Total: {len(results)} package(s) with an unreleased latest CHANGELOG version.",
        "",
        "| SDK Name | Unreleased Version | CHANGELOG | PyPI |",
        "| --- | --- | --- | --- |",
    ]
    for package, version, changelog_link, pypi_link in results:
        lines.append(f"| {package} | {version} | [CHANGELOG.md]({changelog_link}) | [release history]({pypi_link}) |")

    # Emit the Markdown table on stdout so the agent can present it to the user.
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
