"""Tests for check_api_version_drift.py."""

import base64
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import check_api_version_drift as checker


UNCHANGED_PR = "https://github.com/Azure/azure-sdk-for-python/pull/48405"
UNCHANGED_FIRST_REVISION = "780302405ff99212539a2efbbf0341f6ef7145f3"
UNCHANGED_LATEST_REVISION = "ddc9572b5e848690b9138649a6f2ca54d9aa2fcc"
UNCHANGED_PACKAGE_PATH = "sdk/computerecommender/azure-mgmt-computerecommender"
CHANGED_PR = "https://github.com/Azure/azure-sdk-for-python/pull/48445"
CHANGED_FIRST_REVISION = "0460802fc4d70c65570c94e45f32ae60693b0946"
CHANGED_LATEST_REVISION = "e87bc1c4db2c0c0c4ff5da198d69fbea4a116c55"
CHANGED_PACKAGE_PATH = "sdk/containerservice/azure-mgmt-containerservice"


def encoded_metadata(api_version: str) -> str:
    content = json.dumps({"apiVersion": api_version}).encode("utf-8")
    return json.dumps(
        {
            "encoding": "base64",
            "content": base64.b64encode(content).decode("ascii"),
        }
    )


def test_get_ordered_commits_uses_pr_metadata(monkeypatch):
    calls = []

    def fake_run_gh(arguments):
        calls.append(arguments)
        return json.dumps(
            {
                "commits": [
                    {"oid": UNCHANGED_FIRST_REVISION},
                    {"oid": UNCHANGED_LATEST_REVISION},
                ]
            }
        )

    monkeypatch.setattr(checker, "run_gh", fake_run_gh)

    commits = checker.get_ordered_commits(UNCHANGED_PR, checker.DEFAULT_REPOSITORY)

    assert commits == [UNCHANGED_FIRST_REVISION, UNCHANGED_LATEST_REVISION]
    assert calls == [
        [
            "pr",
            "view",
            UNCHANGED_PR,
            "--repo",
            checker.DEFAULT_REPOSITORY,
            "--json",
            "commits",
        ]
    ]


def test_build_report_compares_first_and_latest_pr_commits(monkeypatch):
    requested_revisions = []
    monkeypatch.setattr(
        checker,
        "get_ordered_commits",
        lambda pr, repository: [UNCHANGED_FIRST_REVISION, UNCHANGED_LATEST_REVISION],
    )

    def fake_get_api_version(repository, metadata_path, revision):
        requested_revisions.append(revision)
        return "2026-05-05-preview"

    monkeypatch.setattr(checker, "get_api_version", fake_get_api_version)

    report = checker.build_report(
        UNCHANGED_PR,
        checker.DEFAULT_REPOSITORY,
        [UNCHANGED_PACKAGE_PATH],
    )
    result = report["results"][0]

    assert report["pullRequest"] == UNCHANGED_PR
    assert report["firstRevision"] == UNCHANGED_FIRST_REVISION
    assert report["latestRevision"] == UNCHANGED_LATEST_REVISION
    assert requested_revisions == [UNCHANGED_FIRST_REVISION, UNCHANGED_LATEST_REVISION]
    assert result["package_path"] == UNCHANGED_PACKAGE_PATH
    assert result["status"] == "unchanged"
    assert result["first_api_version"] == "2026-05-05-preview"
    assert result["latest_api_version"] == "2026-05-05-preview"


def test_build_report_detects_api_version_change_from_pr_48445(monkeypatch):
    versions = {
        CHANGED_FIRST_REVISION: "2026-05-02-preview",
        CHANGED_LATEST_REVISION: "2026-05-01",
    }
    monkeypatch.setattr(
        checker,
        "get_ordered_commits",
        lambda pr, repository: [CHANGED_FIRST_REVISION, CHANGED_LATEST_REVISION],
    )
    monkeypatch.setattr(
        checker,
        "get_api_version",
        lambda repository, metadata_path, revision: versions[revision],
    )

    report = checker.build_report(
        CHANGED_PR,
        checker.DEFAULT_REPOSITORY,
        [CHANGED_PACKAGE_PATH],
    )
    result = report["results"][0]

    assert report["pullRequest"] == CHANGED_PR
    assert report["firstRevision"] == CHANGED_FIRST_REVISION
    assert report["latestRevision"] == CHANGED_LATEST_REVISION
    assert result["package_path"] == CHANGED_PACKAGE_PATH
    assert result["status"] == "changed"
    assert result["first_api_version"] == "2026-05-02-preview"
    assert result["latest_api_version"] == "2026-05-01"

    table = checker.format_report_table(report)
    assert "| Package | Status | First revision | First API version |" in table
    assert (
        f"| {CHANGED_PACKAGE_PATH} | changed | {CHANGED_FIRST_REVISION} | "
        f"2026-05-02-preview | {CHANGED_LATEST_REVISION} | 2026-05-01 | - |"
    ) in table


def test_format_report_table_escapes_error_column():
    report = {
        "repository": checker.DEFAULT_REPOSITORY,
        "pullRequest": UNCHANGED_PR,
        "firstRevision": UNCHANGED_FIRST_REVISION,
        "latestRevision": UNCHANGED_LATEST_REVISION,
        "results": [
            {
                "package_path": UNCHANGED_PACKAGE_PATH,
                "metadata_path": f"{UNCHANGED_PACKAGE_PATH}/_metadata.json",
                "status": "unverified",
                "first_api_version": None,
                "latest_api_version": None,
                "error": "missing file | missing field",
            }
        ],
    }

    table = checker.format_report_table(report)

    assert "| unverified |" in table
    assert "| - |" in table
    assert "missing file \\| missing field" in table


def test_check_package_reports_missing_metadata_as_unverified(monkeypatch):
    def unavailable(repository, metadata_path, revision):
        raise checker.CheckUnavailableError("metadata not found")

    monkeypatch.setattr(checker, "get_api_version", unavailable)

    result = checker.check_package(
        checker.DEFAULT_REPOSITORY,
        UNCHANGED_PACKAGE_PATH,
        UNCHANGED_FIRST_REVISION,
        UNCHANGED_LATEST_REVISION,
    )

    assert result.status == "unverified"
    assert result.error == "metadata not found"


def test_get_api_version_parses_base64_json(monkeypatch):
    monkeypatch.setattr(
        checker,
        "run_gh",
        lambda arguments: encoded_metadata("2026-05-05-preview"),
    )

    api_version = checker.get_api_version(
        checker.DEFAULT_REPOSITORY,
        f"{UNCHANGED_PACKAGE_PATH}/_metadata.json",
        UNCHANGED_FIRST_REVISION,
    )

    assert api_version == "2026-05-05-preview"


def test_get_ordered_commits_rejects_empty_list(monkeypatch):
    monkeypatch.setattr(checker, "run_gh", lambda arguments: '{"commits": []}')

    with pytest.raises(checker.CheckUnavailableError, match="empty commit list"):
        checker.get_ordered_commits(UNCHANGED_PR, checker.DEFAULT_REPOSITORY)
