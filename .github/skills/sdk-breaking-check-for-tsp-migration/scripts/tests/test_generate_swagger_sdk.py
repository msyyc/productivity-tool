"""Tests for generate_swagger_sdk.py"""

import os
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
# main — integration-style tests with mocked subprocess/fs
# ---------------------------------------------------------------------------
class TestGenerateSwaggerMain:
    @patch("generate_swagger_sdk.run_cmd")
    @patch("generate_swagger_sdk.glob.glob")
    @patch("generate_swagger_sdk.os.path.exists")
    @patch("generate_swagger_sdk.os.path.isdir")
    @patch("generate_swagger_sdk.os.path.isfile")
    @patch("builtins.open", create=True)
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
