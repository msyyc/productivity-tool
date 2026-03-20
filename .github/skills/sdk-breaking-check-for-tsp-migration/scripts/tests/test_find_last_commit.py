"""Tests for find_last_commit_without_file.py"""

import base64
import json
import subprocess
from unittest.mock import MagicMock, call, patch

import pytest

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from find_last_commit_without_file import (
    extract_search_keyword,
    find_first_commit_with_file,
    find_tspconfig_path,
    get_parent_commit,
    gh_api,
)


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
# gh_api
# ---------------------------------------------------------------------------
class TestGhApi:
    @patch("find_last_commit_without_file.subprocess.run")
    def test_basic_call(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout='{"login": "testuser"}',
            stderr="",
            returncode=0,
        )
        result = gh_api("/user")
        assert result == {"login": "testuser"}
        mock_run.assert_called_once_with(
            ["gh", "api", "/user"], capture_output=True, text=True, check=True
        )

    @patch("find_last_commit_without_file.subprocess.run")
    def test_paginate_merges_arrays(self, mock_run):
        # Simulate --paginate output: two JSON arrays concatenated
        mock_run.return_value = MagicMock(
            stdout='[{"a":1}]\n[{"b":2}]',
            stderr="",
            returncode=0,
        )
        result = gh_api("/some/endpoint", paginate=True)
        assert result == [{"a": 1}, {"b": 2}]

    @patch("find_last_commit_without_file.subprocess.run")
    def test_paginate_single_array(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout='[{"a":1},{"b":2}]',
            stderr="",
            returncode=0,
        )
        result = gh_api("/some/endpoint", paginate=True)
        assert result == [{"a": 1}, {"b": 2}]

    @patch("find_last_commit_without_file.subprocess.run")
    def test_paginate_adjacent_brackets(self, mock_run):
        # No newline between arrays
        mock_run.return_value = MagicMock(
            stdout='[{"a":1}][{"b":2}]',
            stderr="",
            returncode=0,
        )
        result = gh_api("/some/endpoint", paginate=True)
        assert result == [{"a": 1}, {"b": 2}]


# ---------------------------------------------------------------------------
# find_tspconfig_path
# ---------------------------------------------------------------------------
class TestFindTspconfigPath:
    @patch("find_last_commit_without_file.gh_api")
    def test_single_match(self, mock_gh_api):
        mock_gh_api.return_value = {
            "items": [{"path": "specification/securityinsights/resource-manager/tspconfig.yaml"}]
        }
        result = find_tspconfig_path("azure-mgmt-securityinsights")
        assert result == "specification/securityinsights/resource-manager/tspconfig.yaml"

    @patch("find_last_commit_without_file.gh_api")
    def test_no_match(self, mock_gh_api):
        mock_gh_api.return_value = {"items": []}
        result = find_tspconfig_path("azure-mgmt-nonexistent")
        assert result is None

    @patch("find_last_commit_without_file.gh_api")
    def test_multiple_matches_exact_package_name(self, mock_gh_api):
        tspconfig_content = base64.b64encode(
            b'options:\n  "@azure-tools/typespec-python":\n    package-name: azure-mgmt-securityinsights'
        ).decode()

        def side_effect(endpoint, **kwargs):
            if "/search/code" in endpoint:
                return {
                    "items": [
                        {"path": "specification/security/tspconfig.yaml"},
                        {"path": "specification/securityinsights/tspconfig.yaml"},
                    ]
                }
            if "securityinsights/tspconfig.yaml" in endpoint:
                return {"content": tspconfig_content}
            # First candidate doesn't match
            return {"content": base64.b64encode(b"unrelated content").decode()}

        mock_gh_api.side_effect = side_effect
        result = find_tspconfig_path("azure-mgmt-securityinsights")
        assert result == "specification/securityinsights/tspconfig.yaml"

    @patch("find_last_commit_without_file.gh_api")
    def test_multiple_matches_keyword_fallback(self, mock_gh_api):
        keyword_content = base64.b64encode(b"contains securityinsights keyword").decode()
        no_match_content = base64.b64encode(b"no match here").decode()

        call_count = {"n": 0}

        def side_effect(endpoint, **kwargs):
            if "/search/code" in endpoint:
                return {
                    "items": [
                        {"path": "specification/a/tspconfig.yaml"},
                        {"path": "specification/b/tspconfig.yaml"},
                    ]
                }
            call_count["n"] += 1
            # First pass (exact match): neither matches
            # Second pass (keyword): second matches
            if call_count["n"] <= 2:
                return {"content": no_match_content}
            if "specification/a" in endpoint:
                return {"content": no_match_content}
            return {"content": keyword_content}

        mock_gh_api.side_effect = side_effect
        result = find_tspconfig_path("azure-mgmt-securityinsights")
        assert result == "specification/b/tspconfig.yaml"


# ---------------------------------------------------------------------------
# find_first_commit_with_file
# ---------------------------------------------------------------------------
class TestFindFirstCommitWithFile:
    @patch("find_last_commit_without_file.gh_api")
    def test_returns_earliest_commit(self, mock_gh_api):
        commits = [
            {"sha": "newest", "commit": {"message": "latest"}},
            {"sha": "middle", "commit": {"message": "middle"}},
            {"sha": "oldest", "commit": {"message": "first"}},
        ]
        mock_gh_api.return_value = commits
        result = find_first_commit_with_file("specification/foo/tspconfig.yaml")
        assert result["sha"] == "oldest"

    @patch("find_last_commit_without_file.gh_api")
    def test_no_commits(self, mock_gh_api):
        mock_gh_api.return_value = []
        result = find_first_commit_with_file("specification/foo/tspconfig.yaml")
        assert result is None

    @patch("find_last_commit_without_file.gh_api")
    def test_single_commit(self, mock_gh_api):
        commits = [{"sha": "only", "commit": {"message": "only commit"}}]
        mock_gh_api.return_value = commits
        result = find_first_commit_with_file("specification/foo/tspconfig.yaml")
        assert result["sha"] == "only"


# ---------------------------------------------------------------------------
# get_parent_commit
# ---------------------------------------------------------------------------
class TestGetParentCommit:
    @patch("find_last_commit_without_file.gh_api")
    def test_returns_first_parent(self, mock_gh_api):
        mock_gh_api.return_value = {
            "parents": [
                {"sha": "parent1"},
                {"sha": "parent2"},
            ]
        }
        result = get_parent_commit("abc123")
        assert result == "parent1"

    @patch("find_last_commit_without_file.gh_api")
    def test_no_parents(self, mock_gh_api):
        mock_gh_api.return_value = {"parents": []}
        result = get_parent_commit("abc123")
        assert result is None

    @patch("find_last_commit_without_file.gh_api")
    def test_missing_parents_key(self, mock_gh_api):
        mock_gh_api.return_value = {}
        result = get_parent_commit("abc123")
        assert result is None
