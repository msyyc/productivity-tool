"""Tests for generate_swagger_sdk.py"""

import os
import re
from unittest.mock import MagicMock, patch

import pytest

import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from generate_swagger_sdk import strip_mgmt_prefix


# ---------------------------------------------------------------------------
# strip_mgmt_prefix
# ---------------------------------------------------------------------------
class TestStripMgmtPrefix:
    def test_strips_azure_mgmt(self):
        assert strip_mgmt_prefix("azure-mgmt-securityinsights") == "securityinsights"

    def test_strips_azure(self):
        assert strip_mgmt_prefix("azure-storage-blob") == "storage-blob"

    def test_no_prefix(self):
        assert strip_mgmt_prefix("somepackage") == "somepackage"

    def test_case_insensitive(self):
        assert strip_mgmt_prefix("Azure-Mgmt-Compute") == "compute"

    def test_azure_mgmt_takes_priority(self):
        assert strip_mgmt_prefix("azure-mgmt-network") == "network"

    def test_empty_after_prefix(self):
        assert strip_mgmt_prefix("azure-mgmt-") == ""

    def test_empty_string(self):
        assert strip_mgmt_prefix("") == ""


# ---------------------------------------------------------------------------
# Package-name regex matching (word-boundary to avoid substring matches)
# ---------------------------------------------------------------------------
def _build_pkg_pattern(package_name):
    """Reproduce the regex from main() for unit testing."""
    return re.compile(rf"package-name:\s*{re.escape(package_name)}\b", re.IGNORECASE)


class TestPackageNameMatching:
    """Verify that readme matching uses word boundaries to avoid substring hits."""

    def test_exact_match(self):
        pattern = _build_pkg_pattern("azure-mgmt-compute")
        assert pattern.search("package-name: azure-mgmt-compute")

    def test_no_substring_match(self):
        """azure-mgmt-compute must NOT match azure-mgmt-computefleet."""
        pattern = _build_pkg_pattern("azure-mgmt-compute")
        assert pattern.search("package-name: azure-mgmt-computefleet") is None

    def test_no_substring_match_scheduler(self):
        """azure-mgmt-scheduler must NOT match azure-mgmt-schedulerx."""
        pattern = _build_pkg_pattern("azure-mgmt-scheduler")
        assert pattern.search("package-name: azure-mgmt-schedulerx") is None

    def test_match_at_end_of_line(self):
        pattern = _build_pkg_pattern("azure-mgmt-network")
        assert pattern.search("package-name: azure-mgmt-network\n")

    def test_match_with_no_space_after_colon(self):
        pattern = _build_pkg_pattern("azure-mgmt-network")
        assert pattern.search("package-name:azure-mgmt-network")

    def test_match_with_multiple_spaces(self):
        pattern = _build_pkg_pattern("azure-mgmt-network")
        assert pattern.search("package-name:   azure-mgmt-network")

    def test_case_insensitive(self):
        pattern = _build_pkg_pattern("azure-mgmt-compute")
        assert pattern.search("package-name: Azure-Mgmt-Compute")

    def test_embedded_in_larger_file(self):
        content = (
            "```yaml $(python)\n"
            "azure-arm: true\n"
            "package-name: azure-mgmt-frontdoor\n"
            "license-header: MICROSOFT_MIT\n"
            "```\n"
        )
        pattern = _build_pkg_pattern("azure-mgmt-frontdoor")
        assert pattern.search(content)

    def test_no_match_different_package(self):
        content = "package-name: azure-mgmt-network\n"
        pattern = _build_pkg_pattern("azure-mgmt-compute")
        assert pattern.search(content) is None

    def test_longer_package_does_not_match_shorter(self):
        """azure-mgmt-computefleet must NOT match content with azure-mgmt-compute."""
        pattern = _build_pkg_pattern("azure-mgmt-computefleet")
        assert pattern.search("package-name: azure-mgmt-compute") is None


# ---------------------------------------------------------------------------
# main — integration-style tests with mocked subprocess/fs
# ---------------------------------------------------------------------------
class TestGenerateSwaggerMain:
    @patch("generate_swagger_sdk.run_cmd")
    @patch("generate_swagger_sdk.glob.glob")
    @patch("generate_swagger_sdk.os.path.exists")
    @patch("generate_swagger_sdk.os.path.isdir")
    @patch("generate_swagger_sdk.os.path.isfile")
    @patch("generate_swagger_sdk.open", create=True)
    def test_exits_when_no_readme_found(self, mock_open, mock_isfile, mock_isdir, mock_exists, mock_glob, mock_run_cmd):
        """main() should sys.exit(1) when no readme.python.md matches the package name."""
        mock_exists.return_value = True
        mock_isdir.return_value = True

        # glob returns readme files but none contain the package name
        mock_glob.return_value = ["/spec/specification/foo/readme.python.md"]

        from io import StringIO

        mock_open.return_value.__enter__ = lambda s: StringIO("unrelated content")
        mock_open.return_value.__exit__ = MagicMock(return_value=False)

        mock_run_cmd.side_effect = [
            MagicMock(stdout="", returncode=0),  # git checkout . && git clean -fd && git checkout {commit}
            MagicMock(stdout="main", returncode=0),  # git rev-parse --abbrev-ref HEAD
            MagicMock(stdout="", returncode=0),  # git fetch origin main
            MagicMock(stdout="", returncode=0),  # git checkout -B {branch}
            MagicMock(stdout="", returncode=0),  # git log --oneline --grep (cache check, no hit)
        ]

        with pytest.raises(SystemExit) as exc_info:
            sys.argv = [
                "generate_swagger_sdk.py",
                "azure-mgmt-securityinsights",
                "abc123",
                "--spec-dir",
                "/spec",
                "--sdk-dir",
                "/sdk",
            ]
            from generate_swagger_sdk import main

            main()
        assert exc_info.value.code == 1
