#!/usr/bin/env python3
"""
Find Service Name for a Python SDK Package

Searches the local azure-sdk-for-python repo to find which service folder
contains the given package, then outputs the service name for pipeline lookup.

Usage:
    python find_service_name.py <package-name> [--sdk-dir <path>]

Examples:
    python find_service_name.py azure-mgmt-frontdoor
    python find_service_name.py azure-mgmt-network --sdk-dir C:/dev/azure-sdk-for-python
"""

import argparse
import json
import os
import re
import subprocess
import sys


DEFAULT_SDK_DIR = "C:/dev/azure-sdk-for-python"
PACKAGE_NAME_PATTERN = re.compile(r"^azure(-[a-z0-9]+)+$")


def find_locally(package_name: str, sdk_dir: str) -> str | None:
    """Search local SDK repo for the package and return its service name."""
    sdk_path = os.path.join(sdk_dir, "sdk")
    if not os.path.isdir(sdk_path):
        return None

    for service_name in os.listdir(sdk_path):
        candidate = os.path.join(sdk_path, service_name, package_name)
        if os.path.isdir(candidate):
            return service_name
    return None


def find_via_github(package_name: str) -> str | None:
    """Fallback: search GitHub for the package path."""
    try:
        result = subprocess.run(
            [
                "gh",
                "search",
                "code",
                package_name,
                "--repo",
                "Azure/azure-sdk-for-python",
                "--filename",
                "setup.py",
                "--limit",
                "1",
                "--json",
                "path",
            ],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        print("  WARNING: GitHub CLI (gh) is not installed. Skipping GitHub search.", file=sys.stderr)
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None

    try:
        items = json.loads(result.stdout)
        if items:
            # path like "sdk/network/azure-mgmt-frontdoor/setup.py"
            parts = items[0]["path"].split("/")
            if len(parts) >= 3 and parts[0] == "sdk":
                return parts[1]
    except (json.JSONDecodeError, KeyError, IndexError):
        pass
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find the service name for a Python SDK package.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("package_name", help="SDK package name (e.g. azure-mgmt-frontdoor)")
    parser.add_argument(
        "--sdk-dir",
        default=DEFAULT_SDK_DIR,
        help=f"Path to azure-sdk-for-python clone (default: {DEFAULT_SDK_DIR})",
    )
    args = parser.parse_args()

    if not PACKAGE_NAME_PATTERN.match(args.package_name):
        print(
            f"ERROR: Invalid package name '{args.package_name}'. "
            "Must match pattern 'azure-*' (e.g. azure-mgmt-frontdoor).",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Searching for '{args.package_name}' in {args.sdk_dir}...")
    service_name = find_locally(args.package_name, args.sdk_dir)

    if not service_name:
        print("  Not found locally, searching GitHub...")
        service_name = find_via_github(args.package_name)

    if not service_name:
        print(f"ERROR: Could not find service name for '{args.package_name}'", file=sys.stderr)
        sys.exit(1)

    print(f"  Found: sdk/{service_name}/{args.package_name}")

    print("\n=== SESSION_STATE ===")
    print(f"service_name={service_name}")
    print(f"package_name={args.package_name}")
    print("=== END SESSION_STATE ===")


if __name__ == "__main__":
    main()
