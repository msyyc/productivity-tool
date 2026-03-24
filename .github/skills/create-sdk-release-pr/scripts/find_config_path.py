"""
Find the tspconfig.yaml path for a given SDK package name in the spec repo.

Usage:
    python find_config_path.py <package-name> [--spec-dir <dir>]

Example:
    python find_config_path.py azure-mgmt-frontdoor --spec-dir C:/dev/azure-rest-api-specs
"""

import argparse
import os
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


def main():
    parser = argparse.ArgumentParser(description="Find tspconfig.yaml path for a package")
    parser.add_argument("package_name", help="SDK package name (e.g. azure-mgmt-frontdoor)")
    parser.add_argument("--spec-dir", default=".", help="Path to azure-rest-api-specs repo")
    args = parser.parse_args()

    matches = find_config_path(args.package_name, args.spec_dir)

    if not matches:
        print(f"Error: No tspconfig.yaml found containing package '{args.package_name}'")
        sys.exit(1)

    if len(matches) == 1:
        print(f"Found config path: {matches[0]}")
    else:
        print(f"Found {len(matches)} matching configs:")
        for m in matches:
            print(f"  - {m}")

    print("\n=== SESSION_STATE ===")
    print(f"config_path={matches[0]}")
    print("=====================")


if __name__ == "__main__":
    main()
