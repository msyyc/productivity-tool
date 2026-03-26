"""Tests for extract_swagger_api_version.py"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from extract_swagger_api_version import (
    extract_api_versions,
    find_readme_path,
    parse_default_tag,
    parse_input_files,
)


SPEC_DIR = "/fake/spec/dir"


# ---------------------------------------------------------------------------
# find_readme_path
# ---------------------------------------------------------------------------
class TestFindReadmePath:
    @patch("extract_swagger_api_version.git_cmd")
    def test_single_readme(self, mock_git):
        mock_git.return_value = "specification/frontdoor/resource-manager/Microsoft.Network/FrontDoor/readme.md"
        result = find_readme_path(
            "azure-mgmt-frontdoor",
            "abc123",
            "specification/frontdoor/resource-manager",
            SPEC_DIR,
        )
        assert result == "specification/frontdoor/resource-manager/Microsoft.Network/FrontDoor/readme.md"

    @patch("extract_swagger_api_version.git_cmd")
    def test_no_files(self, mock_git):
        mock_git.return_value = ""
        result = find_readme_path(
            "azure-mgmt-frontdoor",
            "abc123",
            "specification/frontdoor/resource-manager",
            SPEC_DIR,
        )
        assert result is None

    @patch("extract_swagger_api_version.git_cmd")
    def test_no_readme_md(self, mock_git):
        mock_git.return_value = (
            "specification/svc/resource-manager/readme.python.md\n" "specification/svc/resource-manager/swagger.json"
        )
        result = find_readme_path("azure-mgmt-svc", "abc123", "specification/svc/resource-manager", SPEC_DIR)
        assert result is None

    @patch("extract_swagger_api_version.git_cmd")
    def test_multiple_readmes_resolved_by_python_readme(self, mock_git):
        ls_tree_output = (
            "specification/svc/resource-manager/A/readme.md\n"
            "specification/svc/resource-manager/B/readme.md\n"
            "specification/svc/resource-manager/A/readme.python.md\n"
            "specification/svc/resource-manager/B/readme.python.md"
        )

        def side_effect(args, cwd):
            if "ls-tree" in args:
                return ls_tree_output
            # git show for readme.python.md
            path = args[-1]
            if "B/readme.python.md" in path:
                return "package-name: azure-mgmt-svc\n"
            return "package-name: azure-mgmt-other\n"

        mock_git.side_effect = side_effect
        result = find_readme_path("azure-mgmt-svc", "abc123", "specification/svc/resource-manager", SPEC_DIR)
        assert result == "specification/svc/resource-manager/B/readme.md"

    @patch("extract_swagger_api_version.git_cmd")
    def test_multiple_readmes_fallback_to_tag_line(self, mock_git):
        ls_tree_output = (
            "specification/svc/resource-manager/A/readme.md\n" "specification/svc/resource-manager/B/readme.md"
        )

        def side_effect(args, cwd):
            if "ls-tree" in args:
                return ls_tree_output
            # git show for readme.md content
            path = args[-1]
            if "A/readme.md" in path:
                return "no tag here"
            return "tag: package-2024-01\n"

        mock_git.side_effect = side_effect
        result = find_readme_path("azure-mgmt-svc", "abc123", "specification/svc/resource-manager", SPEC_DIR)
        assert result == "specification/svc/resource-manager/B/readme.md"

    @patch("extract_swagger_api_version.git_cmd")
    def test_git_ls_tree_error(self, mock_git):
        mock_git.side_effect = RuntimeError("git failed")
        with pytest.raises(RuntimeError):
            find_readme_path(
                "azure-mgmt-svc",
                "abc123",
                "specification/svc/resource-manager",
                SPEC_DIR,
            )


# ---------------------------------------------------------------------------
# parse_default_tag
# ---------------------------------------------------------------------------
class TestParseDefaultTag:
    def test_basic_tag(self):
        content = """## Configuration

### Basic Information

``` yaml
title: FrontDoorManagementClient
openapi-type: arm
tag: package-2025-11
```
"""
        assert parse_default_tag(content) == "package-2025-11"

    def test_tag_without_title(self):
        content = """### Basic Information

``` yaml
openapi-type: arm
tag: package-2025-09-01
```
"""
        assert parse_default_tag(content) == "package-2025-09-01"

    def test_skips_conditional_blocks(self):
        content = """``` yaml
tag: package-default
```

``` yaml $(tag) == 'package-2025-11'
input-file:
  - stable/2025-11-01/openapi.json
```
"""
        assert parse_default_tag(content) == "package-default"

    def test_no_tag_found(self):
        content = """``` yaml
openapi-type: arm
```
"""
        assert parse_default_tag(content) is None

    def test_no_yaml_blocks(self):
        assert parse_default_tag("Just some markdown text") is None

    def test_tag_with_preview(self):
        content = """``` yaml
tag: package-preview-2025-07-01
```
"""
        assert parse_default_tag(content) == "package-preview-2025-07-01"


# ---------------------------------------------------------------------------
# parse_input_files
# ---------------------------------------------------------------------------
class TestParseInputFiles:
    def test_single_input_file(self):
        content = """### Tag: package-2025-11

``` yaml $(tag) == 'package-2025-11'
input-file:
  - stable/2025-11-01/openapi.json
```
"""
        result = parse_input_files(content, "package-2025-11")
        assert result == ["stable/2025-11-01/openapi.json"]

    def test_multiple_input_files(self):
        content = """``` yaml $(tag) == 'package-2025-03'
input-file:
  - stable/2025-03-01/network.json
  - stable/2025-03-01/webapplicationfirewall.json
  - stable/2021-06-01/frontdoor.json
  - stable/2019-11-01/networkexperiment.json
```
"""
        result = parse_input_files(content, "package-2025-03")
        assert result == [
            "stable/2025-03-01/network.json",
            "stable/2025-03-01/webapplicationfirewall.json",
            "stable/2021-06-01/frontdoor.json",
            "stable/2019-11-01/networkexperiment.json",
        ]

    def test_input_files_with_suppressions(self):
        content = """``` yaml $(tag) == 'package-2025-09-01'
input-file:
  - stable/2025-09-01/AlertRules.json
  - stable/2025-09-01/Incidents.json
suppressions:
  - code: AvoidAdditionalProperties
```
"""
        result = parse_input_files(content, "package-2025-09-01")
        assert result == [
            "stable/2025-09-01/AlertRules.json",
            "stable/2025-09-01/Incidents.json",
        ]

    def test_tag_not_found(self):
        content = """``` yaml $(tag) == 'package-2025-11'
input-file:
  - stable/2025-11-01/openapi.json
```
"""
        result = parse_input_files(content, "package-nonexistent")
        assert result == []

    def test_empty_content(self):
        assert parse_input_files("", "package-2025-11") == []

    def test_no_input_files_key(self):
        content = """``` yaml $(tag) == 'package-2025-11'
directive:
  - some-directive
```
"""
        result = parse_input_files(content, "package-2025-11")
        assert result == []

    def test_mixed_api_versions(self):
        content = """``` yaml $(tag) == 'package-composite'
input-file:
  - Microsoft.Svc/stable/2024-01-01/a.json
  - Microsoft.Svc/preview/2023-06-01-preview/b.json
  - Microsoft.Svc/stable/2024-01-01/c.json
```
"""
        result = parse_input_files(content, "package-composite")
        assert result == [
            "Microsoft.Svc/stable/2024-01-01/a.json",
            "Microsoft.Svc/preview/2023-06-01-preview/b.json",
            "Microsoft.Svc/stable/2024-01-01/c.json",
        ]

    def test_special_chars_in_tag_name(self):
        content = """``` yaml $(tag) == 'package-2025-09-01'
input-file:
  - stable/2025-09-01/file.json
```
"""
        result = parse_input_files(content, "package-2025-09-01")
        assert result == ["stable/2025-09-01/file.json"]


# ---------------------------------------------------------------------------
# extract_api_versions
# ---------------------------------------------------------------------------
class TestExtractApiVersions:
    def test_single_version(self):
        files = [
            "stable/2025-11-01/openapi.json",
        ]
        assert extract_api_versions(files) == ["2025-11-01"]

    def test_single_version_multiple_files(self):
        files = [
            "stable/2025-09-01/AlertRules.json",
            "stable/2025-09-01/Incidents.json",
            "stable/2025-09-01/Metadata.json",
        ]
        assert extract_api_versions(files) == ["2025-09-01"]

    def test_multiple_versions(self):
        files = [
            "stable/2025-03-01/network.json",
            "stable/2021-06-01/frontdoor.json",
            "stable/2019-11-01/networkexperiment.json",
        ]
        assert extract_api_versions(files) == [
            "2019-11-01",
            "2021-06-01",
            "2025-03-01",
        ]

    def test_preview_version(self):
        files = [
            "preview/2025-07-01-preview/openapi.json",
        ]
        assert extract_api_versions(files) == ["2025-07-01-preview"]

    def test_mixed_stable_and_preview(self):
        files = [
            "Microsoft.Svc/stable/2024-01-01/a.json",
            "Microsoft.Svc/preview/2023-06-01-preview/b.json",
        ]
        assert extract_api_versions(files) == [
            "2023-06-01-preview",
            "2024-01-01",
        ]

    def test_empty_list(self):
        assert extract_api_versions([]) == []

    def test_no_version_in_path(self):
        files = ["some/random/path.json"]
        assert extract_api_versions(files) == []

    def test_deduplicates(self):
        files = [
            "stable/2025-01-01/a.json",
            "stable/2025-01-01/b.json",
            "stable/2025-01-01/c.json",
        ]
        assert extract_api_versions(files) == ["2025-01-01"]

    def test_prefixed_paths(self):
        files = [
            "Microsoft.Network/stable/2025-03-01/network.json",
            "Microsoft.Network/stable/2025-03-01/waf.json",
        ]
        assert extract_api_versions(files) == ["2025-03-01"]
