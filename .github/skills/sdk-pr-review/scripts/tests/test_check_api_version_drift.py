"""Tests for check_api_version_drift.py."""

import base64
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import check_api_version_drift as checker


FIRST_REVISION = "2c1967498ba39393cd21c550173bcaaa86f80059"
LATEST_REVISION = "c5065a49f27dee7b615e1cb286211bcd1d276f3f"
PACKAGE_PATH = "sdk/relay/azure-mgmt-relay"


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
                    {"oid": FIRST_REVISION},
                    {"oid": LATEST_REVISION},
                ]
            }
        )

    monkeypatch.setattr(checker, "run_gh", fake_run_gh)

    commits = checker.get_ordered_commits("48443", checker.DEFAULT_REPOSITORY)

    assert commits == [FIRST_REVISION, LATEST_REVISION]
    assert calls == [
        [
            "pr",
            "view",
            "48443",
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
        lambda pr, repository: [FIRST_REVISION, LATEST_REVISION],
    )

    def fake_get_api_version(repository, metadata_path, revision):
        requested_revisions.append(revision)
        return "2026-07-01-preview"

    monkeypatch.setattr(checker, "get_api_version", fake_get_api_version)

    report = checker.build_report("48443", checker.DEFAULT_REPOSITORY, [PACKAGE_PATH])

    assert report["firstRevision"] == FIRST_REVISION
    assert report["latestRevision"] == LATEST_REVISION
    assert requested_revisions == [FIRST_REVISION, LATEST_REVISION]
    assert report["results"][0]["status"] == "unchanged"


def test_check_package_reports_changed_version(monkeypatch):
    versions = {
        FIRST_REVISION: "2024-01-01",
        LATEST_REVISION: "2026-07-01-preview",
    }
    monkeypatch.setattr(
        checker,
        "get_api_version",
        lambda repository, metadata_path, revision: versions[revision],
    )

    result = checker.check_package(
        checker.DEFAULT_REPOSITORY,
        PACKAGE_PATH,
        FIRST_REVISION,
        LATEST_REVISION,
    )

    assert result.status == "changed"
    assert result.first_api_version == "2024-01-01"
    assert result.latest_api_version == "2026-07-01-preview"


def test_check_package_reports_missing_metadata_as_unverified(monkeypatch):
    def unavailable(repository, metadata_path, revision):
        raise checker.CheckUnavailableError("metadata not found")

    monkeypatch.setattr(checker, "get_api_version", unavailable)

    result = checker.check_package(
        checker.DEFAULT_REPOSITORY,
        PACKAGE_PATH,
        FIRST_REVISION,
        LATEST_REVISION,
    )

    assert result.status == "unverified"
    assert result.error == "metadata not found"


def test_get_api_version_parses_base64_json(monkeypatch):
    monkeypatch.setattr(
        checker,
        "run_gh",
        lambda arguments: encoded_metadata("2026-07-01-preview"),
    )

    api_version = checker.get_api_version(
        checker.DEFAULT_REPOSITORY,
        f"{PACKAGE_PATH}/_metadata.json",
        FIRST_REVISION,
    )

    assert api_version == "2026-07-01-preview"


def test_get_ordered_commits_rejects_empty_list(monkeypatch):
    monkeypatch.setattr(checker, "run_gh", lambda arguments: '{"commits": []}')

    with pytest.raises(checker.CheckUnavailableError, match="empty commit list"):
        checker.get_ordered_commits("48443", checker.DEFAULT_REPOSITORY)
