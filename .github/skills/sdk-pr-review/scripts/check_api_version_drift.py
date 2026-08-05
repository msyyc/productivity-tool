"""Check _metadata.json apiVersion drift between the first and latest PR commits."""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from typing import Any


DEFAULT_REPOSITORY = "Azure/azure-sdk-for-python"


class CheckUnavailableError(RuntimeError):
    """Raised when required pull request or metadata evidence is unavailable."""


@dataclass(frozen=True)
class PackageResult:
    package_path: str
    metadata_path: str
    status: str
    first_api_version: str | None = None
    latest_api_version: str | None = None
    error: str | None = None


def run_gh(arguments: list[str]) -> str:
    """Run a GitHub CLI command and return stdout."""
    try:
        result = subprocess.run(
            ["gh", *arguments],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as error:
        raise CheckUnavailableError("GitHub CLI (gh) is not installed or not on PATH") from error

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown GitHub CLI error"
        raise CheckUnavailableError(detail)
    return result.stdout


def get_ordered_commits(pr: str, repository: str) -> list[str]:
    """Return commit OIDs in the order supplied by pull request metadata."""
    output = run_gh(["pr", "view", pr, "--repo", repository, "--json", "commits"])
    try:
        payload = json.loads(output)
        commits = [commit["oid"] for commit in payload["commits"]]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise CheckUnavailableError("Pull request metadata did not contain an ordered commit list") from error

    if not commits:
        raise CheckUnavailableError("Pull request metadata returned an empty commit list")
    return commits


def get_api_version(repository: str, metadata_path: str, revision: str) -> str:
    """Read apiVersion from a metadata file at an exact Git revision."""
    output = run_gh(
        [
            "api",
            "-X",
            "GET",
            f"repos/{repository}/contents/{metadata_path}",
            "-f",
            f"ref={revision}",
        ]
    )
    try:
        response = json.loads(output)
        if response.get("encoding") != "base64":
            raise CheckUnavailableError(
                f"{metadata_path} at {revision} did not use base64 content encoding"
            )
        content = base64.b64decode(response["content"]).decode("utf-8")
        api_version = json.loads(content)["apiVersion"]
    except CheckUnavailableError:
        raise
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, UnicodeDecodeError) as error:
        raise CheckUnavailableError(
            f"Could not read apiVersion from {metadata_path} at {revision}"
        ) from error

    if not isinstance(api_version, str) or not api_version:
        raise CheckUnavailableError(
            f"apiVersion in {metadata_path} at {revision} is missing or is not a string"
        )
    return api_version


def check_package(
    repository: str,
    package_path: str,
    first_revision: str,
    latest_revision: str,
) -> PackageResult:
    """Compare one package's API version at the first and latest PR revisions."""
    normalized_package_path = package_path.strip().strip("/\\").replace("\\", "/")
    metadata_path = f"{normalized_package_path}/_metadata.json"
    try:
        first_api_version = get_api_version(repository, metadata_path, first_revision)
        latest_api_version = get_api_version(repository, metadata_path, latest_revision)
    except CheckUnavailableError as error:
        return PackageResult(
            package_path=normalized_package_path,
            metadata_path=metadata_path,
            status="unverified",
            error=str(error),
        )

    return PackageResult(
        package_path=normalized_package_path,
        metadata_path=metadata_path,
        status="unchanged" if first_api_version == latest_api_version else "changed",
        first_api_version=first_api_version,
        latest_api_version=latest_api_version,
    )


def build_report(pr: str, repository: str, package_paths: list[str]) -> dict[str, Any]:
    """Build a structured drift report for all requested packages."""
    commits = get_ordered_commits(pr, repository)
    first_revision = commits[0]
    latest_revision = commits[-1]
    results = [
        check_package(repository, package_path, first_revision, latest_revision)
        for package_path in package_paths
    ]
    return {
        "repository": repository,
        "pullRequest": pr,
        "firstRevision": first_revision,
        "latestRevision": latest_revision,
        "results": [asdict(result) for result in results],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check SDK _metadata.json apiVersion drift within a pull request"
    )
    parser.add_argument("pr", help="Pull request URL or number")
    parser.add_argument(
        "package_paths",
        nargs="+",
        help="Package paths such as sdk/relay/azure-mgmt-relay",
    )
    parser.add_argument(
        "--repo",
        default=DEFAULT_REPOSITORY,
        help=f"GitHub owner/repository (default: {DEFAULT_REPOSITORY})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = build_report(args.pr, args.repo, args.package_paths)
    except CheckUnavailableError as error:
        print(json.dumps({"status": "unverified", "error": str(error)}, indent=2))
        return 2

    print(json.dumps(report, indent=2))
    statuses = {result["status"] for result in report["results"]}
    if "changed" in statuses:
        return 1
    if "unverified" in statuses:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
