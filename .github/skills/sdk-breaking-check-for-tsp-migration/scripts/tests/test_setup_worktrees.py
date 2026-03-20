"""Tests for setup_worktrees.py"""

import os
import subprocess
from unittest.mock import MagicMock, call, patch

import pytest

import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from setup_worktrees import run_cmd, get_github_username, ensure_fork_and_remote


# ---------------------------------------------------------------------------
# run_cmd
# ---------------------------------------------------------------------------
class TestRunCmd:
    @patch("setup_worktrees.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(stdout="output\n", stderr="", returncode=0)
        result = run_cmd("echo hello")
        assert result.returncode == 0
        mock_run.assert_called_once()

    @patch("setup_worktrees.subprocess.run")
    def test_failure_with_check_true(self, mock_run):
        mock_run.return_value = MagicMock(stdout="", stderr="error msg", returncode=1)
        with pytest.raises(SystemExit) as exc_info:
            run_cmd("bad command", check=True)
        assert exc_info.value.code == 1

    @patch("setup_worktrees.subprocess.run")
    def test_failure_with_check_false(self, mock_run):
        mock_run.return_value = MagicMock(stdout="", stderr="error msg", returncode=1)
        result = run_cmd("bad command", check=False)
        assert result.returncode == 1

    @patch("setup_worktrees.subprocess.run")
    def test_passes_cwd(self, mock_run):
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
        run_cmd("ls", cwd="/some/dir")
        mock_run.assert_called_once_with("ls", cwd="/some/dir", shell=True, capture_output=True, text=True)


# ---------------------------------------------------------------------------
# get_github_username
# ---------------------------------------------------------------------------
class TestGetGithubUsername:
    @patch("setup_worktrees.run_cmd")
    def test_returns_username(self, mock_run_cmd):
        mock_run_cmd.return_value = MagicMock(stdout="testuser\n")
        result = get_github_username()
        assert result == "testuser"
        mock_run_cmd.assert_called_once_with("gh api user --jq .login")


# ---------------------------------------------------------------------------
# ensure_fork_and_remote
# ---------------------------------------------------------------------------
class TestEnsureForkAndRemote:
    @patch("setup_worktrees.run_cmd")
    def test_fork_exists_remote_exists(self, mock_run_cmd):
        # Fork check succeeds, remote check succeeds
        mock_run_cmd.side_effect = [
            MagicMock(returncode=0, stdout="testuser/azure-rest-api-specs"),
            MagicMock(returncode=0, stdout="https://github.com/testuser/azure-rest-api-specs.git"),
        ]
        result = ensure_fork_and_remote(
            "/dev/spec", "/dev/worktrees/spec-pkg", "Azure", "azure-rest-api-specs", "testuser"
        )
        assert result == "testuser"
        assert mock_run_cmd.call_count == 2

    @patch("setup_worktrees.run_cmd")
    def test_fork_missing_creates_fork(self, mock_run_cmd):
        mock_run_cmd.side_effect = [
            MagicMock(returncode=1),  # fork check fails
            MagicMock(returncode=0),  # fork creation
            MagicMock(returncode=1),  # remote check fails
            MagicMock(returncode=0),  # remote add
        ]
        result = ensure_fork_and_remote(
            "/dev/spec", "/dev/worktrees/spec-pkg", "Azure", "azure-rest-api-specs", "testuser"
        )
        assert result == "testuser"
        # Should have called gh repo fork
        fork_call = mock_run_cmd.call_args_list[1]
        assert "gh repo fork" in fork_call.args[0]

    @patch("setup_worktrees.run_cmd")
    def test_remote_missing_adds_remote(self, mock_run_cmd):
        mock_run_cmd.side_effect = [
            MagicMock(returncode=0, stdout="testuser/repo"),  # fork exists
            MagicMock(returncode=1),  # remote doesn't exist
            MagicMock(returncode=0),  # remote add succeeds
        ]
        result = ensure_fork_and_remote(
            "/dev/spec", "/dev/worktrees/spec-pkg", "Azure", "azure-rest-api-specs", "testuser"
        )
        assert result == "testuser"
        add_call = mock_run_cmd.call_args_list[2]
        assert "git remote add testuser" in add_call.args[0]
