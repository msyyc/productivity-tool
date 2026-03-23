"""Tests for find_last_commit_without_file.py"""

import os
import subprocess
from unittest.mock import MagicMock, call, mock_open, patch

import pytest

import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from find_last_commit_without_file import (
    derive_service_spec_folder,
    extract_search_keyword,
    find_earliest_tspconfig_commit,
    find_last_service_commit_before,
    find_swagger_spec_folder,
    find_tspconfig_path,
    git_cmd,
)


SPEC_DIR = "/fake/spec/dir"


# ---------------------------------------------------------------------------
# extract_search_keyword
# ---------------------------------------------------------------------------
class TestExtractSearchKeyword:
    def test_strips_azure_mgmt_prefix(self):
        assert extract_search_keyword("azure-mgmt-securityinsights") == "securityinsights"

    def test_strips_azure_prefix(self):
        assert extract_search_keyword("azure-storage-blob") == "storage-blob"

    def test_no_prefix(self):
        assert extract_search_keyword("somepackage") == "somepackage"

    def test_case_insensitive(self):
        assert extract_search_keyword("Azure-Mgmt-Compute") == "compute"

    def test_azure_mgmt_takes_priority_over_azure(self):
        assert extract_search_keyword("azure-mgmt-network") == "network"


# ---------------------------------------------------------------------------
# git_cmd
# ---------------------------------------------------------------------------
class TestGitCmd:
    @patch("find_last_commit_without_file.subprocess.run")
    def test_basic_call(self, mock_run):
        mock_run.return_value = MagicMock(stdout="output\n", stderr="", returncode=0)
        result = git_cmd(["status"], cwd=SPEC_DIR)
        assert result == "output"
        mock_run.assert_called_once_with(["git", "status"], capture_output=True, text=True, cwd=SPEC_DIR)

    @patch("find_last_commit_without_file.subprocess.run")
    def test_raises_on_failure(self, mock_run):
        mock_run.return_value = MagicMock(stdout="", stderr="fatal: error", returncode=1)
        with pytest.raises(RuntimeError, match="failed"):
            git_cmd(["bad-command"], cwd=SPEC_DIR)


# ---------------------------------------------------------------------------
# find_tspconfig_path
# ---------------------------------------------------------------------------
class TestFindTspconfigPath:
    @patch("find_last_commit_without_file.git_cmd")
    def test_single_match(self, mock_git):
        mock_git.return_value = (
            "specification/securityinsights/resource-manager/tspconfig.yaml\n" "specification/other/tspconfig.yaml"
        )
        result = find_tspconfig_path("azure-mgmt-securityinsights", SPEC_DIR)
        assert result == "specification/securityinsights/resource-manager/tspconfig.yaml"

    @patch("find_last_commit_without_file.git_cmd")
    def test_no_files_found(self, mock_git):
        mock_git.return_value = ""
        result = find_tspconfig_path("azure-mgmt-nonexistent", SPEC_DIR)
        assert result is None

    @patch("find_last_commit_without_file.git_cmd")
    def test_no_keyword_match(self, mock_git):
        mock_git.return_value = "specification/compute/tspconfig.yaml"
        result = find_tspconfig_path("azure-mgmt-nonexistent", SPEC_DIR)
        assert result is None

    @patch("builtins.open", mock_open(read_data="package-name: azure-mgmt-securityinsights"))
    @patch("find_last_commit_without_file.git_cmd")
    def test_multiple_matches_exact_package_name(self, mock_git):
        mock_git.return_value = (
            "specification/security/securityinsights/tspconfig.yaml\n"
            "specification/securityinsights/resource-manager/tspconfig.yaml"
        )
        result = find_tspconfig_path("azure-mgmt-securityinsights", SPEC_DIR)
        # Both match keyword; first one checked for exact package name match in content
        assert result == "specification/security/securityinsights/tspconfig.yaml"

    @patch("find_last_commit_without_file.git_cmd")
    def test_multiple_matches_keyword_fallback(self, mock_git):
        mock_git.return_value = (
            "specification/securityinsights/a/tspconfig.yaml\n" "specification/securityinsights/b/tspconfig.yaml"
        )

        call_count = {"n": 0}

        def fake_open(path, *args, **kwargs):
            call_count["n"] += 1
            m = MagicMock()
            # First pass (exact match): neither contains the full package name
            # Second pass (keyword): first contains the keyword
            if call_count["n"] <= 2:
                m.read.return_value = "unrelated content"
            else:
                m.read.return_value = "contains securityinsights keyword"
            m.__enter__ = lambda s: m
            m.__exit__ = MagicMock(return_value=False)
            return m

        with patch("builtins.open", side_effect=fake_open):
            result = find_tspconfig_path("azure-mgmt-securityinsights", SPEC_DIR)
        assert result == "specification/securityinsights/a/tspconfig.yaml"


# ---------------------------------------------------------------------------
# derive_service_spec_folder
# ---------------------------------------------------------------------------
class TestDeriveServiceSpecFolder:
    def test_extracts_top_level_folder(self):
        path = "specification/frontdoor/resource-manager/Microsoft.Network/FrontDoor/tspconfig.yaml"
        assert derive_service_spec_folder(path) == "specification/frontdoor"

    def test_simple_path(self):
        path = "specification/securityinsights/Securityinsights.Management/tspconfig.yaml"
        assert derive_service_spec_folder(path) == "specification/securityinsights"

    def test_handles_backslashes(self):
        path = "specification\\compute\\resource-manager\\tspconfig.yaml"
        assert derive_service_spec_folder(path) == "specification/compute"


# ---------------------------------------------------------------------------
# find_earliest_tspconfig_commit
# ---------------------------------------------------------------------------
class TestFindEarliestTspconfigCommit:
    @patch("find_last_commit_without_file.git_cmd")
    def test_finds_earliest_across_multiple_paths(self, mock_git):
        # First call: git log --diff-filter=A --name-only to discover paths
        # Subsequent calls: git log --diff-filter=A --reverse for each path
        def side_effect(args, cwd):
            if "--name-only" in args:
                return (
                    "specification/svc/Old.Management/tspconfig.yaml\n"
                    "specification/svc/New.Management/tspconfig.yaml"
                )
            path = args[-1]
            if "Old.Management" in path:
                return "old_sha\n2025-01-01T00:00:00+00:00\nold migration"
            else:
                return "new_sha\n2026-03-01T00:00:00+00:00\nfolder restructure"

        mock_git.side_effect = side_effect
        result = find_earliest_tspconfig_commit("specification/svc", "/spec")
        assert result is not None
        sha, date, message, path = result
        assert sha == "old_sha"
        assert "old migration" in message
        assert "Old.Management" in path

    @patch("find_last_commit_without_file.git_cmd")
    def test_single_path(self, mock_git):
        def side_effect(args, cwd):
            if "--name-only" in args:
                return "specification/svc/Mgmt/tspconfig.yaml"
            return "abc123\n2025-06-15T00:00:00+00:00\nmigration commit"

        mock_git.side_effect = side_effect
        result = find_earliest_tspconfig_commit("specification/svc", "/spec")
        assert result == (
            "abc123",
            "2025-06-15T00:00:00+00:00",
            "migration commit",
            "specification/svc/Mgmt/tspconfig.yaml",
        )

    @patch("find_last_commit_without_file.git_cmd")
    def test_no_tspconfig_found(self, mock_git):
        mock_git.return_value = ""
        result = find_earliest_tspconfig_commit("specification/svc", "/spec")
        assert result is None

    @patch("find_last_commit_without_file.git_cmd")
    def test_git_error_returns_none(self, mock_git):
        mock_git.side_effect = RuntimeError("git failed")
        result = find_earliest_tspconfig_commit("specification/svc", "/spec")
        assert result is None

    @patch("find_last_commit_without_file.git_cmd")
    def test_skips_paths_with_no_add_commits(self, mock_git):
        def side_effect(args, cwd):
            if "--name-only" in args:
                return "specification/svc/a/tspconfig.yaml\n" "specification/svc/b/tspconfig.yaml"
            path = args[-1]
            if "/a/" in path:
                return ""  # no commits found for this path
            return "sha_b\n2025-03-01T00:00:00+00:00\nmigration b"

        mock_git.side_effect = side_effect
        result = find_earliest_tspconfig_commit("specification/svc", "/spec")
        assert result is not None
        assert result[0] == "sha_b"


# ---------------------------------------------------------------------------
# find_swagger_spec_folder
# ---------------------------------------------------------------------------
class TestFindSwaggerSpecFolder:
    @patch("find_last_commit_without_file.git_cmd")
    def test_finds_resource_manager(self, mock_git):
        # git ls-tree returns an entry when resource-manager exists
        mock_git.return_value = "040000 tree abc123\tspecification/frontdoor/resource-manager"
        result = find_swagger_spec_folder("pre_sha", "specification/frontdoor", "/spec")
        assert result == "specification/frontdoor/resource-manager"
        mock_git.assert_called_once_with(
            ["ls-tree", "pre_sha", "specification/frontdoor/resource-manager"],
            cwd="/spec",
        )

    @patch("find_last_commit_without_file.git_cmd")
    def test_falls_back_to_spec_folder(self, mock_git):
        # git ls-tree returns empty when resource-manager doesn't exist
        mock_git.return_value = ""
        result = find_swagger_spec_folder("pre_sha", "specification/svc", "/spec")
        assert result == "specification/svc"

    @patch("find_last_commit_without_file.git_cmd")
    def test_falls_back_on_git_error(self, mock_git):
        mock_git.side_effect = RuntimeError("git failed")
        result = find_swagger_spec_folder("pre_sha", "specification/svc", "/spec")
        assert result == "specification/svc"


# ---------------------------------------------------------------------------
# find_last_service_commit_before
# ---------------------------------------------------------------------------
class TestFindLastServiceCommitBefore:
    @patch("find_last_commit_without_file.git_cmd")
    def test_finds_last_service_commit(self, mock_git):
        mock_git.return_value = "pre_sha\n2025-10-21T10:00:00+00:00\nAdd new api version"
        result = find_last_service_commit_before("migration_sha", "specification/frontdoor", "/spec")
        assert result == ("pre_sha", "2025-10-21T10:00:00+00:00", "Add new api version")
        mock_git.assert_called_once_with(
            ["log", "-1", "--format=%H%n%aI%n%s", "migration_sha^", "--", "specification/frontdoor/"],
            cwd="/spec",
        )

    @patch("find_last_commit_without_file.git_cmd")
    def test_no_prior_commits(self, mock_git):
        mock_git.return_value = ""
        result = find_last_service_commit_before("sha", "specification/svc", "/spec")
        assert result is None

    @patch("find_last_commit_without_file.git_cmd")
    def test_git_error_returns_none(self, mock_git):
        mock_git.side_effect = RuntimeError("no parent")
        result = find_last_service_commit_before("sha", "specification/svc", "/spec")
        assert result is None

    @patch("find_last_commit_without_file.git_cmd")
    def test_incomplete_output_returns_none(self, mock_git):
        mock_git.return_value = "sha_only"  # missing date and message lines
        result = find_last_service_commit_before("sha", "specification/svc", "/spec")
        assert result is None
