"""Tests for ado_build_approve.py"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ado_build_approve import (
    parse_build_url,
    get_az_token,
    ado_api,
    get_stages,
    classify_stages,
    find_pending_approvals,
    format_duration,
    print_stages_table,
    wait_for_release_stage,
    main,
    EXIT_OK,
    EXIT_BUILD_FAILED,
    EXIT_CONFIG_ERROR,
)


# ── parse_build_url ──────────────────────────────────────────────────────


class TestParseBuildUrl:
    def test_standard_url(self):
        url = "https://dev.azure.com/azure-sdk/internal/_build/results?buildId=6065389&view=results"
        org, project, build_id = parse_build_url(url)
        assert org == "https://dev.azure.com/azure-sdk"
        assert project == "internal"
        assert build_id == 6065389

    def test_url_without_view_param(self):
        url = "https://dev.azure.com/azure-sdk/internal/_build/results?buildId=12345"
        org, project, build_id = parse_build_url(url)
        assert build_id == 12345
        assert project == "internal"

    def test_url_missing_build_id(self):
        url = "https://dev.azure.com/azure-sdk/internal/_build/results"
        with pytest.raises(ValueError, match="buildId"):
            parse_build_url(url)

    def test_url_missing_build_segment(self):
        url = "https://dev.azure.com/azure-sdk/internal/something?buildId=123"
        with pytest.raises(ValueError, match="_build"):
            parse_build_url(url)

    def test_different_org(self):
        url = "https://dev.azure.com/my-org/my-project/_build/results?buildId=99"
        org, project, build_id = parse_build_url(url)
        assert org == "https://dev.azure.com/my-org"
        assert project == "my-project"
        assert build_id == 99


# ── get_az_token ─────────────────────────────────────────────────────────


class TestGetAzToken:
    @patch("ado_build_approve.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="my-token-value\n", stderr="")
        assert get_az_token() == "my-token-value"

    @patch("ado_build_approve.subprocess.run")
    def test_az_not_logged_in(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Please run 'az login'")
        with pytest.raises(RuntimeError, match="az login"):
            get_az_token()


# ── ado_api ──────────────────────────────────────────────────────────────


class TestAdoApi:
    @patch("ado_build_approve.urlopen")
    def test_get_request(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"status": "ok"}'
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = ado_api("token", "https://example.com/api")
        assert result == {"status": "ok"}

    @patch("ado_build_approve.urlopen")
    def test_post_request_with_body(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"id": 1}'
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        body = json.dumps({"key": "value"})
        result = ado_api("token", "https://example.com/api", method="POST", body=body)
        assert result == {"id": 1}

        # Verify the request was constructed with body
        req = mock_urlopen.call_args[0][0]
        assert req.data == body.encode("utf-8")
        assert req.get_method() == "POST"

    @patch("ado_build_approve.urlopen")
    def test_http_error(self, mock_urlopen):
        from urllib.error import HTTPError

        error = HTTPError("https://example.com", 401, "Unauthorized", {}, None)
        error.read = lambda: b"Access denied"
        mock_urlopen.side_effect = error

        with pytest.raises(RuntimeError, match="401"):
            ado_api("bad-token", "https://example.com/api")


# ── get_stages ───────────────────────────────────────────────────────────


class TestGetStages:
    def test_filters_stages(self):
        records = [
            {"type": "Stage", "name": "Build"},
            {"type": "Job", "name": "Job1"},
            {"type": "Stage", "name": "Release: pkg"},
            {"type": "Checkpoint", "name": "cp"},
        ]
        stages = get_stages(records)
        assert len(stages) == 2
        assert stages[0]["name"] == "Build"
        assert stages[1]["name"] == "Release: pkg"

    def test_empty_records(self):
        assert get_stages([]) == []


# ── classify_stages ──────────────────────────────────────────────────────


class TestClassifyStages:
    def test_mixed_stages(self):
        stages = [
            {"name": "Build", "state": "completed"},
            {"name": "Integration", "state": "completed"},
            {"name": "Release: azure-mgmt-frontdoor", "state": "pending"},
            {"name": "Release: azure-mgmt-dns", "state": "pending"},
        ]
        build, release = classify_stages(stages)
        assert len(build) == 2
        assert len(release) == 2
        assert build[0]["name"] == "Build"
        assert release[0]["name"] == "Release: azure-mgmt-frontdoor"

    def test_all_build_stages(self):
        stages = [{"name": "Build"}, {"name": "Integration"}]
        build, release = classify_stages(stages)
        assert len(build) == 2
        assert len(release) == 0

    def test_all_release_stages(self):
        stages = [{"name": "Release: pkg1"}, {"name": "Release: pkg2"}]
        build, release = classify_stages(stages)
        assert len(build) == 0
        assert len(release) == 2

    def test_empty(self):
        build, release = classify_stages([])
        assert build == []
        assert release == []


# ── find_pending_approvals ───────────────────────────────────────────────


class TestFindPendingApprovals:
    def _make_records(self):
        """Create a realistic set of timeline records."""
        return [
            # Stage
            {"id": "stage-1", "type": "Stage", "name": "Release: azure-mgmt-frontdoor", "state": "pending"},
            {"id": "stage-2", "type": "Stage", "name": "Release: azure-mgmt-dns", "state": "pending"},
            # Checkpoints (parent of approval)
            {"id": "cp-1", "type": "Checkpoint", "parentId": "stage-1", "state": "inProgress"},
            {"id": "cp-2", "type": "Checkpoint", "parentId": "stage-2", "state": "inProgress"},
            # Approvals
            {"id": "appr-1", "type": "Checkpoint.Approval", "parentId": "cp-1", "state": "inProgress"},
            {"id": "appr-2", "type": "Checkpoint.Approval", "parentId": "cp-2", "state": "inProgress"},
        ]

    def test_finds_all_approvals(self):
        records = self._make_records()
        release_stages = [r for r in records if r["type"] == "Stage"]
        approvals = find_pending_approvals(records, release_stages)
        assert len(approvals) == 2
        assert approvals[0]["stage_name"] == "Release: azure-mgmt-frontdoor"
        assert approvals[0]["approval_id"] == "appr-1"
        assert approvals[1]["approval_id"] == "appr-2"

    def test_skips_completed_approvals(self):
        records = self._make_records()
        # Mark one approval as already completed
        records[4]["state"] = "completed"
        release_stages = [r for r in records if r["type"] == "Stage"]
        approvals = find_pending_approvals(records, release_stages)
        assert len(approvals) == 1
        assert approvals[0]["stage_name"] == "Release: azure-mgmt-dns"

    def test_no_checkpoint(self):
        """Stage without checkpoint returns no approvals."""
        records = [
            {"id": "stage-1", "type": "Stage", "name": "Release: pkg", "state": "pending"},
        ]
        approvals = find_pending_approvals(records, records)
        assert approvals == []

    def test_empty(self):
        assert find_pending_approvals([], []) == []


# ── format_duration ──────────────────────────────────────────────────────


class TestFormatDuration:
    def test_seconds_only(self):
        assert format_duration(45) == "45s"

    def test_minutes_and_seconds(self):
        assert format_duration(90) == "1m 30s"

    def test_zero(self):
        assert format_duration(0) == "0s"

    def test_exact_minute(self):
        assert format_duration(60) == "1m 0s"

    def test_large_value(self):
        assert format_duration(3661) == "61m 1s"


# ── print_stages_table ───────────────────────────────────────────────────


class TestPrintStagesTable:
    def test_output_format(self, capsys):
        build = [{"name": "Build", "state": "completed", "result": "succeeded"}]
        release = [{"name": "Release: pkg", "state": "pending"}]
        print_stages_table(build, release)
        out = capsys.readouterr().out
        assert "Build" in out
        assert "completed" in out
        assert "succeeded" in out
        assert "Release: pkg" in out
        assert "pending" in out

    def test_unknown_state(self, capsys):
        stages = [{"name": "Mystery", "state": "weird"}]
        print_stages_table(stages, [])
        out = capsys.readouterr().out
        assert "Mystery" in out


# ── main (integration) ───────────────────────────────────────────────────


class TestMain:
    def _mock_build_info(self):
        return {
            "definition": {"name": "python - network"},
            "buildNumber": "20260325.5",
            "sourceBranch": "refs/heads/main",
            "status": "inProgress",
            "result": None,
        }

    def _mock_timeline_records(self):
        return [
            {"id": "s1", "type": "Stage", "name": "Build", "state": "completed", "result": "succeeded"},
            {"id": "s2", "type": "Stage", "name": "Integration", "state": "completed", "result": "succeeded"},
            {"id": "s3", "type": "Stage", "name": "Release: azure-mgmt-frontdoor", "state": "pending", "result": ""},
            {"id": "s4", "type": "Stage", "name": "Release: azure-mgmt-dns", "state": "pending", "result": ""},
            {"id": "cp3", "type": "Checkpoint", "parentId": "s3", "state": "inProgress"},
            {"id": "cp4", "type": "Checkpoint", "parentId": "s4", "state": "inProgress"},
            {"id": "a3", "type": "Checkpoint.Approval", "parentId": "cp3", "state": "inProgress"},
            {"id": "a4", "type": "Checkpoint.Approval", "parentId": "cp4", "state": "inProgress"},
        ]

    @patch("ado_build_approve.approve_stages")
    @patch("ado_build_approve.get_timeline")
    @patch("ado_build_approve.get_build_info")
    @patch("ado_build_approve.get_az_token", return_value="fake-token")
    def test_dry_run_skips_approval(self, mock_token, mock_build, mock_timeline, mock_approve, monkeypatch, capsys):
        """Dry-run finds approvals but does not call approve_stages."""
        mock_build.return_value = self._mock_build_info()
        mock_timeline.return_value = self._mock_timeline_records()
        monkeypatch.setattr(
            "sys.argv",
            [
                "prog",
                "https://dev.azure.com/azure-sdk/internal/_build/results?buildId=123",
                "--dry-run",
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == EXIT_OK
        mock_approve.assert_not_called()
        out = capsys.readouterr().out
        assert "Dry-run" in out

    @patch("ado_build_approve.poll_pypi", return_value=("1.0.0", "https://pypi.org/project/azure-mgmt-frontdoor/"))
    @patch("ado_build_approve.check_pypi", return_value=(None, "https://pypi.org/project/azure-mgmt-frontdoor/"))
    @patch("ado_build_approve.wait_for_release_stage", return_value=True)
    @patch("ado_build_approve.approve_stages")
    @patch("ado_build_approve.get_timeline")
    @patch("ado_build_approve.get_build_info")
    @patch("ado_build_approve.get_az_token", return_value="fake-token")
    def test_target_filters_approvals(
        self,
        mock_token,
        mock_build,
        mock_timeline,
        mock_approve,
        mock_wait,
        mock_check_pypi,
        mock_poll_pypi,
        monkeypatch,
        capsys,
    ):
        """--target filters to only the matching release stage."""
        mock_build.return_value = self._mock_build_info()
        mock_timeline.return_value = self._mock_timeline_records()
        mock_approve.return_value = [{"pipeline": {"name": "python - network"}, "status": "approved"}]
        monkeypatch.setattr(
            "sys.argv",
            [
                "prog",
                "https://dev.azure.com/azure-sdk/internal/_build/results?buildId=123",
                "--target",
                "azure-mgmt-frontdoor",
            ],
        )
        main()
        # approve_stages should be called with only the frontdoor approval
        call_args = mock_approve.call_args[0]
        approvals = call_args[3]  # 4th positional arg
        assert len(approvals) == 1
        assert approvals[0]["stage_name"] == "Release: azure-mgmt-frontdoor"
        # wait_for_release_stage should have been called with target
        mock_wait.assert_called_once()

    @patch("ado_build_approve.get_timeline")
    @patch("ado_build_approve.get_build_info")
    @patch("ado_build_approve.get_az_token", return_value="fake-token")
    def test_target_no_match_exits_config_error(self, mock_token, mock_build, mock_timeline, monkeypatch):
        """--target with no matching stage exits with EXIT_CONFIG_ERROR."""
        mock_build.return_value = self._mock_build_info()
        mock_timeline.return_value = self._mock_timeline_records()
        monkeypatch.setattr(
            "sys.argv",
            [
                "prog",
                "https://dev.azure.com/azure-sdk/internal/_build/results?buildId=123",
                "--target",
                "azure-mgmt-nonexistent",
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == EXIT_CONFIG_ERROR

    @patch("ado_build_approve.get_build_info")
    @patch("ado_build_approve.get_az_token", return_value="fake-token")
    def test_failed_build_exits(self, mock_token, mock_build, monkeypatch):
        """Exit with EXIT_BUILD_FAILED immediately if build has already failed."""
        info = self._mock_build_info()
        info["result"] = "failed"
        mock_build.return_value = info
        monkeypatch.setattr(
            "sys.argv",
            [
                "prog",
                "https://dev.azure.com/azure-sdk/internal/_build/results?buildId=123",
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == EXIT_BUILD_FAILED

    @patch("ado_build_approve.approve_stages")
    @patch("ado_build_approve.get_timeline")
    @patch("ado_build_approve.get_build_info")
    @patch("ado_build_approve.get_az_token", return_value="fake-token")
    def test_no_target_approves_all(self, mock_token, mock_build, mock_timeline, mock_approve, monkeypatch, capsys):
        """Without --target, approve all pending release stages."""
        mock_build.return_value = self._mock_build_info()
        mock_timeline.return_value = self._mock_timeline_records()
        mock_approve.return_value = [
            {"pipeline": {"name": "python - network"}, "status": "approved"},
            {"pipeline": {"name": "python - network"}, "status": "approved"},
        ]
        monkeypatch.setattr(
            "sys.argv",
            [
                "prog",
                "https://dev.azure.com/azure-sdk/internal/_build/results?buildId=123",
            ],
        )
        main()
        call_args = mock_approve.call_args[0]
        approvals = call_args[3]
        assert len(approvals) == 2

    @patch("ado_build_approve.time.sleep")
    @patch("ado_build_approve.get_timeline")
    @patch("ado_build_approve.get_build_info")
    @patch("ado_build_approve.get_az_token", return_value="fake-token")
    def test_build_stage_failure_aborts(self, mock_token, mock_build, mock_timeline, mock_sleep, monkeypatch):
        """Exit 1 when a build stage fails during monitoring."""
        mock_build.return_value = self._mock_build_info()
        failed_records = [
            {"id": "s1", "type": "Stage", "name": "Build", "state": "completed", "result": "failed"},
            {"id": "s2", "type": "Stage", "name": "Release: pkg", "state": "pending", "result": ""},
        ]
        mock_timeline.return_value = failed_records
        monkeypatch.setattr(
            "sys.argv",
            [
                "prog",
                "https://dev.azure.com/azure-sdk/internal/_build/results?buildId=123",
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == EXIT_BUILD_FAILED
        mock_sleep.assert_not_called()

    @patch("ado_build_approve.time.sleep")
    @patch("ado_build_approve.get_timeline")
    @patch("ado_build_approve.get_build_info")
    @patch("ado_build_approve.get_az_token", return_value="fake-token")
    def test_target_release_stage_failure_aborts(
        self, mock_token, mock_build, mock_timeline, mock_sleep, monkeypatch, capsys
    ):
        """Exit 1 when the target release stage fails during monitoring, even if build stages are still running."""
        mock_build.return_value = self._mock_build_info()
        records = [
            {"id": "s1", "type": "Stage", "name": "Build", "state": "inProgress", "result": ""},
            {"id": "s2", "type": "Stage", "name": "Integration", "state": "pending", "result": ""},
            {
                "id": "s3",
                "type": "Stage",
                "name": "Release: azure-mgmt-frontdoor",
                "state": "completed",
                "result": "failed",
            },
            {"id": "s4", "type": "Stage", "name": "Release: azure-mgmt-dns", "state": "pending", "result": ""},
        ]
        mock_timeline.return_value = records
        monkeypatch.setattr(
            "sys.argv",
            [
                "prog",
                "https://dev.azure.com/azure-sdk/internal/_build/results?buildId=123",
                "--target",
                "azure-mgmt-frontdoor",
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == EXIT_BUILD_FAILED
        mock_sleep.assert_not_called()
        out = capsys.readouterr().out
        assert "Target release stage failed" in out

    @patch("ado_build_approve.time.sleep")
    @patch("ado_build_approve.get_timeline")
    @patch("ado_build_approve.get_build_info")
    @patch("ado_build_approve.get_az_token", return_value="fake-token")
    def test_polls_until_build_done(self, mock_token, mock_build, mock_timeline, mock_sleep, monkeypatch, capsys):
        """Poll multiple times until build stages complete, then exit 0."""
        mock_build.return_value = self._mock_build_info()

        in_progress_records = [
            {"id": "s1", "type": "Stage", "name": "Build", "state": "inProgress", "result": ""},
            {"id": "s2", "type": "Stage", "name": "Release: pkg", "state": "pending", "result": ""},
        ]
        completed_records = [
            {"id": "s1", "type": "Stage", "name": "Build", "state": "completed", "result": "succeeded"},
            {"id": "s2", "type": "Stage", "name": "Release: pkg", "state": "pending", "result": ""},
        ]
        mock_timeline.side_effect = [in_progress_records, completed_records]

        monkeypatch.setattr(
            "sys.argv",
            [
                "prog",
                "https://dev.azure.com/azure-sdk/internal/_build/results?buildId=123",
                "--poll-interval",
                "5",
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == EXIT_OK
        assert mock_sleep.call_count == 1


# ── wait_for_release_stage ──────────────────────────────────────────────


class TestWaitForReleaseStage:
    @patch("ado_build_approve.time.sleep")
    @patch("ado_build_approve.get_timeline")
    def test_succeeds_when_stage_completes(self, mock_timeline, mock_sleep):
        from ado_build_approve import wait_for_release_stage

        mock_timeline.return_value = [
            {"type": "Stage", "name": "Release: azure-mgmt-foo", "state": "completed", "result": "succeeded"},
        ]
        result = wait_for_release_stage("token", "org", "proj", 123, "azure-mgmt-foo", 5)
        assert result is True
        mock_sleep.assert_not_called()

    @patch("ado_build_approve.time.sleep")
    @patch("ado_build_approve.get_timeline")
    def test_returns_false_on_stage_failure(self, mock_timeline, mock_sleep):
        from ado_build_approve import wait_for_release_stage

        mock_timeline.return_value = [
            {"type": "Stage", "name": "Release: azure-mgmt-foo", "state": "completed", "result": "failed"},
        ]
        result = wait_for_release_stage("token", "org", "proj", 123, "azure-mgmt-foo", 5)
        assert result is False

    @patch("ado_build_approve.RELEASE_STAGE_TIMEOUT", 0)
    @patch("ado_build_approve.time.sleep")
    @patch("ado_build_approve.get_timeline")
    def test_timeout_returns_false(self, mock_timeline, mock_sleep):
        from ado_build_approve import wait_for_release_stage

        mock_timeline.return_value = [
            {"type": "Stage", "name": "Release: azure-mgmt-foo", "state": "inProgress", "result": ""},
        ]
        result = wait_for_release_stage("token", "org", "proj", 123, "azure-mgmt-foo", 5)
        assert result is False

    @patch("ado_build_approve.time.sleep")
    @patch("ado_build_approve.get_timeline")
    def test_polls_until_complete(self, mock_timeline, mock_sleep):
        from ado_build_approve import wait_for_release_stage

        in_progress = [
            {"type": "Stage", "name": "Release: azure-mgmt-foo", "state": "inProgress", "result": ""},
        ]
        completed = [
            {"type": "Stage", "name": "Release: azure-mgmt-foo", "state": "completed", "result": "succeeded"},
        ]
        mock_timeline.side_effect = [in_progress, completed]
        result = wait_for_release_stage("token", "org", "proj", 123, "azure-mgmt-foo", 5)
        assert result is True
        assert mock_sleep.call_count == 1


# ── ado_api retry ───────────────────────────────────────────────────────


class TestAdoApiRetry:
    @patch("ado_build_approve.time.sleep")
    @patch("ado_build_approve.urlopen")
    def test_retries_on_503(self, mock_urlopen, mock_sleep):
        from urllib.error import HTTPError

        error = HTTPError("https://example.com", 503, "Service Unavailable", {}, None)
        error.read = lambda: b"Unavailable"

        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"ok": true}'
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        mock_urlopen.side_effect = [error, mock_resp]
        result = ado_api("token", "https://example.com/api")
        assert result == {"ok": True}
        assert mock_sleep.call_count == 1

    @patch("ado_build_approve.time.sleep")
    @patch("ado_build_approve.urlopen")
    def test_raises_after_max_retries(self, mock_urlopen, mock_sleep):
        from urllib.error import HTTPError

        error = HTTPError("https://example.com", 503, "Service Unavailable", {}, None)
        error.read = lambda: b"Unavailable"
        mock_urlopen.side_effect = [error, error, error]

        with pytest.raises(RuntimeError, match="failed after"):
            ado_api("token", "https://example.com/api")

    @patch("ado_build_approve.urlopen")
    def test_no_retry_on_401(self, mock_urlopen):
        from urllib.error import HTTPError

        error = HTTPError("https://example.com", 401, "Unauthorized", {}, None)
        error.read = lambda: b"Access denied"
        mock_urlopen.side_effect = error

        with pytest.raises(RuntimeError, match="401"):
            ado_api("bad-token", "https://example.com/api")
