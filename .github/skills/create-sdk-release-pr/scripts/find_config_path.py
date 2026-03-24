"""
Find the tspconfig.yaml path and latest API version for a given SDK package name.

Usage:
    python find_config_path.py <package-name> [--spec-dir <dir>]

Example:
    python find_config_path.py azure-mgmt-frontdoor --spec-dir C:/dev/azure-rest-api-specs
"""

import argparse
import os
import re
import sys


def find_config_path(package_name, spec_dir):
    """Search for tspconfig.yaml files that reference the given package name."""
    spec_dir = os.path.abspath(spec_dir)
    specification_dir = os.path.join(spec_dir, "specification")

    if not os.path.isdir(specification_dir):
        print(f"Error: specification directory not found at {specification_dir}")
        sys.exit(1)

    matches = []
    for root, dirs, files in os.walk(specification_dir):
        if "tspconfig.yaml" in files:
            tspconfig_path = os.path.join(root, "tspconfig.yaml")
            try:
                with open(tspconfig_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except (IOError, UnicodeDecodeError):
                continue
            if package_name in content:
                rel_path = os.path.relpath(tspconfig_path, spec_dir).replace("\\", "/")
                matches.append(rel_path)

    return matches


def extract_latest_api_version(main_tsp_path):
    """Extract the latest API version from main.tsp's enum Versions block.

    Parses patterns like:
        enum Versions {
          v2024_01_01: "2024-01-01",
          v2025_10_01: "2025-10-01",
        }
    Returns the last version string found (the latest).
    """
    try:
        with open(main_tsp_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (IOError, UnicodeDecodeError):
        return None

    # Match all quoted version strings inside enum Versions { ... }
    enum_match = re.search(r"enum\s+\w*[Vv]ersion\w*\s*\{([^}]+)\}", content, re.DOTALL)
    if not enum_match:
        return None

    enum_body = enum_match.group(1)
    versions = re.findall(r'"([^"]+)"', enum_body)
    return versions[-1] if versions else None


def main():
    parser = argparse.ArgumentParser(description="Find tspconfig.yaml path for a package")
    parser.add_argument("package_name", help="SDK package name (e.g. azure-mgmt-frontdoor)")
    parser.add_argument("--spec-dir", default=".", help="Path to azure-rest-api-specs repo")
    args = parser.parse_args()

    spec_dir = os.path.abspath(args.spec_dir)
    matches = find_config_path(args.package_name, spec_dir)

    if not matches:
        print(f"Error: No tspconfig.yaml found containing package '{args.package_name}'")
        sys.exit(1)

    if len(matches) == 1:
        print(f"Found config path: {matches[0]}")
    else:
        print(f"Found {len(matches)} matching configs:")
        for m in matches:
            print(f"  - {m}")

    config_path = matches[0]

    # Look for main.tsp in the same directory as tspconfig.yaml
    config_dir = os.path.dirname(os.path.join(spec_dir, config_path))
    main_tsp_path = os.path.join(config_dir, "main.tsp")
    api_version = ""
    if os.path.isfile(main_tsp_path):
        version = extract_latest_api_version(main_tsp_path)
        if version:
            api_version = version
            print(f"Latest API version: {api_version}")
        else:
            print("Warning: Could not parse API version from main.tsp")
    else:
        print("Warning: main.tsp not found next to tspconfig.yaml")

    print("\n=== SESSION_STATE ===")
    print(f"config_path={config_path}")
    print(f"api_version={api_version}")
    print("=====================")


if __name__ == "__main__":
    main()
