"""Tests for find_service_name.py"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from find_service_name import find_locally, find_via_github, main


# ── find_locally ──────────────────────────────────────────────────────────


class TestFindLocally:
    def test_package_found(self, tmp_path):
        """Find a package in the local SDK repo."""
        sdk_dir = tmp_path / "sdk" / "network" / "azure-mgmt-frontdoor"
        sdk_dir.mkdir(parents=True)
        result = find_locally("azure-mgmt-frontdoor", str(tmp_path))
        assert result == "network"

    def test_package_not_found(self, tmp_path):
        """Return None when package does not exist."""
        (tmp_path / "sdk" / "compute").mkdir(parents=True)
        result = find_locally("azure-mgmt-frontdoor", str(tmp_path))
        assert result is None

    def test_sdk_dir_missing(self, tmp_path):
        """Return None when the sdk/ subdirectory does not exist."""
        result = find_locally("azure-mgmt-frontdoor", str(tmp_path / "nonexistent"))
        assert result is None

    def test_multiple_services(self, tmp_path):
        """Return correct service when multiple services exist."""
        (tmp_path / "sdk" / "compute" / "azure-mgmt-compute").mkdir(parents=True)
        (tmp_path / "sdk" / "network" / "azure-mgmt-network").mkdir(parents=True)
        (tmp_path / "sdk" / "network" / "azure-mgmt-frontdoor").mkdir(parents=True)
        assert find_locally("azure-mgmt-frontdoor", str(tmp_path)) == "network"
        assert find_locally("azure-mgmt-compute", str(tmp_path)) == "compute"

    def test_file_not_dir(self, tmp_path):
        """Ignore files that match the package name (only dirs count)."""
        (tmp_path / "sdk" / "network").mkdir(parents=True)
        (tmp_path / "sdk" / "network" / "azure-mgmt-frontdoor").write_text("")
        result = find_locally("azure-mgmt-frontdoor", str(tmp_path))
        assert result is None


# ── find_via_github ───────────────────────────────────────────────────────


class TestFindViaGithub:
    @patch("find_service_name.subprocess.run")
    def test_success(self, mock_run):
        """Parse service name from gh search code output."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps([{"path": "sdk/network/azure-mgmt-frontdoor/setup.py"}]),
        )
        result = find_via_github("azure-mgmt-frontdoor")
        assert result == "network"

    @patch("find_service_name.subprocess.run")
    def test_gh_command_failure(self, mock_run):
        """Return None when gh command fails."""
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        result = find_via_github("azure-mgmt-frontdoor")
        assert result is None

    @patch("find_service_name.subprocess.run")
    def test_empty_results(self, mock_run):
        """Return None when gh returns empty JSON array."""
        mock_run.return_value = MagicMock(returncode=0, stdout="[]")
        result = find_via_github("azure-mgmt-frontdoor")
        assert result is None

    @patch("find_service_name.subprocess.run")
    def test_empty_stdout(self, mock_run):
        """Return None when gh returns empty stdout."""
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        result = find_via_github("azure-mgmt-frontdoor")
        assert result is None

    @patch("find_service_name.subprocess.run")
    def test_malformed_json(self, mock_run):
        """Return None on invalid JSON output."""
        mock_run.return_value = MagicMock(returncode=0, stdout="not json")
        result = find_via_github("azure-mgmt-frontdoor")
        assert result is None

    @patch("find_service_name.subprocess.run")
    def test_unexpected_path_format(self, mock_run):
        """Return None when path does not match sdk/<service>/<pkg> pattern."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps([{"path": "other/path/setup.py"}]),
        )
        result = find_via_github("azure-mgmt-frontdoor")
        assert result is None

    @patch("find_service_name.subprocess.run")
    def test_missing_path_key(self, mock_run):
        """Return None when JSON item lacks 'path' key."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps([{"name": "setup.py"}]),
        )
        result = find_via_github("azure-mgmt-frontdoor")
        assert result is None


# ── main ──────────────────────────────────────────────────────────────────


class TestMain:
    @patch("find_service_name.find_locally", return_value="network")
    def test_found_locally(self, mock_local, capsys, monkeypatch):
        """Exit 0 and print SESSION_STATE when found locally."""
        monkeypatch.setattr("sys.argv", ["prog", "azure-mgmt-frontdoor", "--sdk-dir", "/fake"])
        main()
        out = capsys.readouterr().out
        assert "=== SESSION_STATE ===" in out
        assert "service_name=network" in out
        assert "package_name=azure-mgmt-frontdoor" in out

    @patch("find_service_name.find_via_github", return_value="network")
    @patch("find_service_name.find_locally", return_value=None)
    def test_fallback_to_github(self, mock_local, mock_gh, capsys, monkeypatch):
        """Fall back to GitHub search when local search fails."""
        monkeypatch.setattr("sys.argv", ["prog", "azure-mgmt-frontdoor", "--sdk-dir", "/fake"])
        main()
        out = capsys.readouterr().out
        assert "service_name=network" in out
        mock_gh.assert_called_once_with("azure-mgmt-frontdoor")

    @patch("find_service_name.find_via_github", return_value=None)
    @patch("find_service_name.find_locally", return_value=None)
    def test_not_found_exits_1(self, mock_local, mock_gh, monkeypatch):
        """Exit 1 when package is not found anywhere."""
        monkeypatch.setattr("sys.argv", ["prog", "azure-mgmt-nonexistent", "--sdk-dir", "/fake"])
        with pytest.raises(SystemExit, match="1"):
            main()
