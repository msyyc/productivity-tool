import re
import json
import subprocess
from typing import Optional


def parse_github_pr_url(url: str) -> Optional[tuple[str, int]]:
    """Extract (repo, pr_number) from a GitHub PR URL."""
    m = re.match(r"https://github\.com/([^/]+/[^/]+)/pull/(\d+)", url.split("?")[0].split("#")[0])
    if m:
        return m.group(1), int(m.group(2))
    return None


def check_pr_state(repo: str, pr_number: int) -> str:
    """Check if PR is open, merged, or closed."""
    try:
        result = subprocess.run(
            ["gh", "pr", "view", str(pr_number), "--repo", repo, "--json", "state", "--template", "{{.state}}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout.strip() if result.returncode == 0 else "UNKNOWN"
    except Exception:
        return "UNKNOWN"


def check_ci_status(repo: str, pr_number: int) -> str:
    """
    Check CI status of a PR.
    Returns: FAILURE, ALL_COMPLETE, IN_PROGRESS, or UNKNOWN.
    Special handling for Azure/azure-rest-api-specs (only watches SDK Validation - Python).
    """
    try:
        result = subprocess.run(
            ["gh", "pr", "checks", str(pr_number), "--repo", repo, "--json", "name,state"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return "UNKNOWN"

        checks = json.loads(result.stdout)
        if not checks:
            return "UNKNOWN"

        # Special filter for azure-rest-api-specs
        if repo == "Azure/azure-rest-api-specs":
            checks = [c for c in checks if c["name"] == "SDK Validation - Python"]
            if not checks:
                return "IN_PROGRESS"

        # Check for any failure
        for check in checks:
            if check.get("state") == "FAILURE":
                return "FAILURE"

        # Check if all complete
        if all(c.get("state") in ("SUCCESS", "NEUTRAL") for c in checks):
            return "ALL_COMPLETE"

        return "IN_PROGRESS"
    except Exception:
        return "UNKNOWN"
