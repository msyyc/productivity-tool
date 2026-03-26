#!/usr/bin/env python3
"""
Azure DevOps Build Monitor & Approver

Monitors an Azure DevOps pipeline build and automatically approves all pending
release stages once the build stages complete successfully.

Usage:
    python ado_build_approve.py <build-url>
    python ado_build_approve.py <build-url> --target azure-mgmt-frontdoor
    python ado_build_approve.py <build-url> --poll-interval 60
    python ado_build_approve.py <build-url> --dry-run

Examples:
    python ado_build_approve.py "https://dev.azure.com/azure-sdk/internal/_build/results?buildId=6065389&view=results"
    python ado_build_approve.py "https://dev.azure.com/azure-sdk/internal/_build/results?buildId=6065389" --target azure-mgmt-frontdoor
"""

import argparse
import json
import subprocess
import sys
import time
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


DEFAULT_POLL_INTERVAL = 30  # seconds
PYPI_POLL_INTERVAL = 30  # seconds
PYPI_POLL_TIMEOUT = 600  # 10 minutes

# Exit codes
EXIT_OK = 0
EXIT_BUILD_FAILED = 1
EXIT_CONFIG_ERROR = 2


def parse_build_url(url: str) -> tuple[str, str, int]:
    """Extract org, project, and buildId from an Azure DevOps build URL.

    Expected format:
        https://dev.azure.com/{org}/{project}/_build/results?buildId={id}

    Returns:
        Tuple of (org_url, project, build_id).
    """
    parsed = urlparse(url)
    # Expected path: /{org}/{project}/_build/results or /{project}/_build/results
    path_parts = [p for p in parsed.path.split("/") if p]
    params = parse_qs(parsed.query)

    if "buildId" not in params:
        raise ValueError(f"URL missing 'buildId' query parameter: {url}")

    build_id = int(params["buildId"][0])
    org_url = f"{parsed.scheme}://{parsed.hostname}"

    # path_parts: [org, project, '_build', 'results'] or [project, '_build', 'results']
    # Find _build and take the part before it as project
    try:
        build_idx = path_parts.index("_build")
    except ValueError:
        raise ValueError(f"URL does not contain '_build' path segment: {url}")

    project = path_parts[build_idx - 1]
    # org may be embedded in the path (e.g., dev.azure.com/azure-sdk/...)
    if build_idx >= 2:
        org_url = f"{org_url}/{path_parts[build_idx - 2]}"

    return org_url, project, build_id


def get_az_token() -> str:
    """Get an Azure DevOps access token using the az CLI."""
    try:
        result = subprocess.run(
            [
                "az",
                "account",
                "get-access-token",
                "--resource",
                "499b84ac-1321-427f-aa17-267ca6975798",
                "--query",
                "accessToken",
                "-o",
                "tsv",
            ],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "Azure CLI (az) is not installed. " "Install from https://learn.microsoft.com/cli/azure/install-azure-cli"
        )
    if result.returncode != 0:
        raise RuntimeError("Failed to get az token. Run 'az login' first.\n" + result.stderr)
    return result.stdout.strip()


def ado_api(token: str, url: str, method: str = "GET", body: str | None = None) -> dict:
    """Call an Azure DevOps REST API endpoint."""
    req = Request(url, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    if body:
        req.data = body.encode("utf-8")
    try:
        with urlopen(req) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API {method} {url} returned {e.code}: {error_body}")


def get_build_info(token: str, org: str, project: str, build_id: int) -> dict:
    """Fetch basic build information."""
    url = f"{org}/{project}/_apis/build/builds/{build_id}" f"?api-version=7.0"
    return ado_api(token, url)


def get_timeline(token: str, org: str, project: str, build_id: int) -> list[dict]:
    """Fetch the build timeline records."""
    url = f"{org}/{project}/_apis/build/builds/{build_id}/timeline" f"?api-version=7.0"
    data = ado_api(token, url)
    return data.get("records", [])


def get_stages(records: list[dict]) -> list[dict]:
    """Extract stage records from timeline."""
    return [r for r in records if r.get("type") == "Stage"]


def classify_stages(stages: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split stages into build stages and release stages.

    Release stages are those whose name starts with 'Release:'.
    Everything else is a build stage.
    """
    build_stages = []
    release_stages = []
    for s in stages:
        if s["name"].startswith("Release:"):
            release_stages.append(s)
        else:
            build_stages.append(s)
    return build_stages, release_stages


def find_pending_approvals(records: list[dict], release_stages: list[dict]) -> list[dict]:
    """Map release stages to their pending Checkpoint.Approval records."""
    approvals = []
    for stage in release_stages:
        checkpoint = next(
            (r for r in records if r.get("type") == "Checkpoint" and r.get("parentId") == stage["id"]),
            None,
        )
        if not checkpoint:
            continue
        approval = next(
            (
                r
                for r in records
                if r.get("type") == "Checkpoint.Approval"
                and r.get("parentId") == checkpoint["id"]
                and r.get("state") == "inProgress"
            ),
            None,
        )
        if approval:
            approvals.append(
                {
                    "stage_name": stage["name"],
                    "approval_id": approval["id"],
                }
            )
    return approvals


def approve_stages(token: str, org: str, project: str, approvals: list[dict]) -> list[dict]:
    """Approve all given pipeline approvals. Returns list of results."""
    url = f"{org}/{project}/_apis/pipelines/approvals?api-version=7.1-preview"
    body = json.dumps(
        [
            {"approvalId": a["approval_id"], "status": "approved", "comment": "Approved by ado_build_approve.py"}
            for a in approvals
        ]
    )
    result = ado_api(token, url, method="PATCH", body=body)
    return result.get("value", [])


def check_pypi(package_name: str) -> tuple[str | None, str]:
    """Check PyPI for the latest version of a package.

    Returns:
        Tuple of (version or None, pypi_url).
    """
    pypi_url = f"https://pypi.org/project/{package_name}/"
    api_url = f"https://pypi.org/pypi/{package_name}/json"
    try:
        req = Request(api_url)
        req.add_header("Accept", "application/json")
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            version = data.get("info", {}).get("version")
            return version, pypi_url
    except (HTTPError, URLError, json.JSONDecodeError):
        return None, pypi_url


def poll_pypi(package_name: str, previous_version: str | None) -> tuple[str | None, str]:
    """Poll PyPI until a new version appears or timeout is reached.

    Returns:
        Tuple of (new_version or None, pypi_url).
    """
    start = time.time()
    pypi_url = f"https://pypi.org/project/{package_name}/"
    print(f"\n[Step 7] Polling PyPI for '{package_name}' (timeout {PYPI_POLL_TIMEOUT}s)...")
    if previous_version:
        print(f"  Current version on PyPI: {previous_version}")

    while time.time() - start < PYPI_POLL_TIMEOUT:
        version, pypi_url = check_pypi(package_name)
        if version and version != previous_version:
            return version, pypi_url
        elapsed = format_duration(time.time() - start)
        print(f"  [{elapsed}] No new version yet, retrying in {PYPI_POLL_INTERVAL}s...")
        time.sleep(PYPI_POLL_INTERVAL)

    print("  ⚠️  Timed out waiting for new version on PyPI.")
    return None, pypi_url


def format_duration(seconds: float) -> str:
    """Format seconds into a human-readable duration."""
    m, s = divmod(int(seconds), 60)
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


def print_stages_table(build_stages: list[dict], release_stages: list[dict]) -> None:
    """Print a summary table of all stages."""
    icon = {"completed": "✅", "inProgress": "🔄", "pending": "⏳"}
    for s in build_stages + release_stages:
        state = s.get("state", "unknown")
        result = s.get("result", "")
        marker = icon.get(state, "❓")
        suffix = f" ({result})" if result else ""
        print(f"    {marker} {s['name']}: {state}{suffix}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Monitor an Azure DevOps build and auto-approve release stages.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "url",
        help="Azure DevOps build results URL",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=DEFAULT_POLL_INTERVAL,
        help=f"Seconds between status checks (default: {DEFAULT_POLL_INTERVAL})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be approved without actually approving",
    )
    parser.add_argument(
        "--target",
        help="Only approve the release stage matching this SDK name (e.g. azure-mgmt-frontdoor)",
    )
    args = parser.parse_args()

    # ----- Step 1: Parse URL -----
    print("\n[Step 1] Parsing build URL...")
    org, project, build_id = parse_build_url(args.url)
    print(f"  Org:     {org}")
    print(f"  Project: {project}")
    print(f"  BuildId: {build_id}")

    # ----- Step 2: Authenticate -----
    print("\n[Step 2] Authenticating via az CLI...")
    token = get_az_token()
    print("  Token acquired.")

    # ----- Step 3: Get build info -----
    print("\n[Step 3] Fetching build info...")
    build = get_build_info(token, org, project, build_id)
    pipeline_name = build.get("definition", {}).get("name", "unknown")
    build_number = build.get("buildNumber", "unknown")
    branch = build.get("sourceBranch", "unknown")
    print(f"  Pipeline: {pipeline_name}")
    print(f"  Build #:  {build_number}")
    print(f"  Branch:   {branch}")
    print(f"  Status:   {build.get('status')}")

    if build.get("result") == "failed":
        print("\n  ❌ Build has already failed. Nothing to approve.")
        sys.exit(EXIT_BUILD_FAILED)

    # ----- Step 4: Monitor build stages -----
    print(f"\n[Step 4] Monitoring build stages (polling every {args.poll_interval}s)...")
    start_time = time.time()

    while True:
        records = get_timeline(token, org, project, build_id)
        stages = get_stages(records)
        build_stages, release_stages = classify_stages(stages)

        all_build_done = all(s.get("state") == "completed" for s in build_stages)
        any_build_failed = any(s.get("result") == "failed" for s in build_stages)

        elapsed = format_duration(time.time() - start_time)
        print(f"\n  [{elapsed}] Stage status:")
        print_stages_table(build_stages, release_stages)

        if any_build_failed:
            failed = [s["name"] for s in build_stages if s.get("result") == "failed"]
            print(f"\n  ❌ Build stage(s) failed: {', '.join(failed)}")
            print("  Aborting — will not approve release stages.")
            sys.exit(EXIT_BUILD_FAILED)

        if all_build_done:
            print("\n  ✅ All build stages completed successfully!")
            break

        print(f"  Waiting {args.poll_interval}s before next check...")
        time.sleep(args.poll_interval)

    # ----- Step 5: Find and approve release stages -----
    print("\n[Step 5] Finding pending approvals...")
    approvals = find_pending_approvals(records, release_stages)

    if args.target:
        approvals = [a for a in approvals if args.target in a["stage_name"]]
        if not approvals:
            print(f"  No pending approval found for target '{args.target}'.")
            print("  Available release stages:")
            for s in release_stages:
                print(f"    • {s['name']} ({s.get('state', 'unknown')})")
            sys.exit(EXIT_CONFIG_ERROR)

    if not approvals:
        print("  No pending approvals found. Stages may have already been approved.")
        sys.exit(EXIT_OK)

    print(f"  Found {len(approvals)} pending approval(s):")
    for a in approvals:
        print(f"    • {a['stage_name']} (id: {a['approval_id']})")

    if args.dry_run:
        print("\n  🔍 Dry-run mode — skipping approval.")
        sys.exit(EXIT_OK)

    print("\n[Step 6] Approving release stages...")
    results = approve_stages(token, org, project, approvals)
    for r in results:
        name = r.get("pipeline", {}).get("name", "unknown")
        status = r.get("status", "unknown")
        print(f"    ✅ {name}: {status}")

    print(f"\n  Done! Approved {len(results)} release stage(s).")

    # ----- Step 7: Verify on PyPI -----
    if args.target:
        pre_version, _ = check_pypi(args.target)
        new_version, pypi_url = poll_pypi(args.target, pre_version)

        print("\n=== RELEASE SUMMARY ===")
        if new_version:
            pypi_version_url = f"https://pypi.org/project/{args.target}/{new_version}/"
            print(f"  ✅ {args.target} {new_version} is live on PyPI!")
            print(f"  PyPI: {pypi_version_url}")
        else:
            print(f"  ⚠️  Could not confirm new version on PyPI yet.")
            print(f"  Check manually: {pypi_url}")
        print("=== END RELEASE SUMMARY ===")


if __name__ == "__main__":
    main()
