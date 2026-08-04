import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import detect_unmerged_pr


def test_has_commits_after_approval_returns_yes_when_newer_commit(monkeypatch):
    def fake_run_gh(args):
        assert args == [
            "pr",
            "view",
            "42",
            "--repo",
            "Azure/azure-sdk-for-python",
            "--json",
            "commits",
        ]
        return '{"commits":[{"committedDate":"2026-08-04T10:00:00Z"},{"committedDate":"2026-08-04T12:00:00Z"}]}'

    monkeypatch.setattr(detect_unmerged_pr, "run_gh", fake_run_gh)

    result = detect_unmerged_pr.has_commits_after_approval(
        "Azure/azure-sdk-for-python",
        42,
        "2026-08-04T11:00:00Z",
    )

    assert result == "Yes"


def test_has_commits_after_approval_returns_no_when_no_newer_commit(monkeypatch):
    def fake_run_gh(args):
        return '{"commits":[{"committedDate":"2026-08-04T10:00:00Z"}]}'

    monkeypatch.setattr(detect_unmerged_pr, "run_gh", fake_run_gh)

    result = detect_unmerged_pr.has_commits_after_approval(
        "Azure/azure-sdk-for-python",
        42,
        "2026-08-04T11:00:00Z",
    )

    assert result == "No"


def test_pr_details_fetches_reviews_commits_and_body_in_one_call(monkeypatch):
    def fake_run_gh(args):
        assert args == [
            "pr",
            "view",
            "42",
            "--repo",
            "Azure/azure-sdk-for-python",
            "--json",
            "reviews,commits,body",
        ]
        return '{"reviews":[],"commits":[],"body":"Release plan link: https://example.test/123"}'

    monkeypatch.setattr(detect_unmerged_pr, "run_gh", fake_run_gh)

    assert detect_unmerged_pr.pr_details("Azure/azure-sdk-for-python", 42) == {
        "reviews": [],
        "commits": [],
        "body": "Release plan link: https://example.test/123",
    }


def test_build_markdown_includes_new_commit_after_approval_column():
    markdown = detect_unmerged_pr.build_markdown(
        [
            {
                "url": "https://github.com/Azure/azure-sdk-for-python/pull/42",
                "sdk_name": "azure-mgmt-example",
                "version": "2.0.0",
                "created": "2026-08-01",
                "approved": "2026-08-02",
                "new_commit_after_approval": "Yes",
                "release_plan": "unknown",
            }
        ]
    )

    assert "new commit after approval" in markdown.splitlines()[0]
    assert "release plan" in markdown.splitlines()[0]
    assert markdown.splitlines()[0].startswith("| id |")
    assert markdown.splitlines()[2].startswith("| 1 |")
    assert markdown.splitlines()[2].endswith("| Yes | unknown |")


def test_extract_release_plan_from_labeled_line_link():
    body = """Generated SDK PR.

Release plan: https://github.com/Azure/azure-sdk-for-python/pull/123

Other notes.
"""

    assert detect_unmerged_pr.extract_release_plan(body) == "https://github.com/Azure/azure-sdk-for-python/pull/123"


def test_extract_release_plan_from_release_plan_link_markdown():
    body = """Configurations: 'specification/example/tspconfig.yaml'.

**Release plan link:** [https://azsdk-releaseplan-dashboard.example.net/?releaseplan=35774](https://azsdk-releaseplan-dashboard.example.net/?releaseplan=35774)

**Submitted by**: user@example.com
"""

    assert (
        detect_unmerged_pr.extract_release_plan(body)
        == "https://azsdk-releaseplan-dashboard.example.net/?releaseplan=35774"
    )


def test_extract_release_plan_from_inline_release_plan_link_markdown():
    body = "Configurations: 'specification/example/tspconfig.yaml'. Pipeline run: https://dev.azure.com/example. **Release plan link:** [https://azsdk-releaseplan-dashboard.example.net/?releaseplan=35774](https://azsdk-releaseplan-dashboard.example.net/?releaseplan=35774) **Submitted by**: user@example.com"

    assert (
        detect_unmerged_pr.extract_release_plan(body)
        == "https://azsdk-releaseplan-dashboard.example.net/?releaseplan=35774"
    )


def test_extract_release_plan_from_heading_section_link():
    body = """Generated SDK PR.

## Release plan
Release tracking PR: https://github.com/Azure/azure-sdk-for-python/pull/456

## Checklist
- [ ] done
"""

    assert detect_unmerged_pr.extract_release_plan(body) == "https://github.com/Azure/azure-sdk-for-python/pull/456"


def test_extract_release_plan_returns_unknown_when_no_link():
    body = """Generated SDK PR.

## Release plan
Public preview first.
Stable after service GA.

## Checklist
- [ ] done
"""

    assert detect_unmerged_pr.extract_release_plan(body) == "unknown"


def test_release_plan_reads_pr_body(monkeypatch):
    def fake_run_gh(args):
        assert args == [
            "pr",
            "view",
            "42",
            "--repo",
            "Azure/azure-sdk-for-python",
            "--json",
            "body",
        ]
        return '{"body":"Release plan: https://github.com/Azure/azure-sdk-for-python/pull/789"}'

    monkeypatch.setattr(detect_unmerged_pr, "run_gh", fake_run_gh)

    assert (
        detect_unmerged_pr.release_plan("Azure/azure-sdk-for-python", 42)
        == "https://github.com/Azure/azure-sdk-for-python/pull/789"
    )


def test_build_markdown_displays_pr_number_for_http_link_cells():
    markdown = detect_unmerged_pr.build_markdown(
        [
            {
                "url": "https://github.com/Azure/azure-sdk-for-python/pull/42",
                "sdk_name": "azure-mgmt-example",
                "version": "2.0.0",
                "created": "2026-08-01",
                "approved": "2026-08-02",
                "new_commit_after_approval": "No",
                "release_plan": "https://github.com/Azure/azure-sdk-for-python/pull/123",
            }
        ]
    )

    assert markdown.splitlines()[2] == (
        "| 1 | [42](https://github.com/Azure/azure-sdk-for-python/pull/42) | azure-mgmt-example | 2.0.0 | "
        "2026-08-01 | 2026-08-02 | No | [123](https://github.com/Azure/azure-sdk-for-python/pull/123) |"
    )


def test_build_markdown_displays_release_plan_number_from_query():
    markdown = detect_unmerged_pr.build_markdown(
        [
            {
                "url": "https://github.com/Azure/azure-sdk-for-python/pull/42",
                "sdk_name": "azure-mgmt-example",
                "version": "2.0.0",
                "created": "2026-08-01",
                "approved": "2026-08-02",
                "new_commit_after_approval": "No",
                "release_plan": "https://azsdk-releaseplan-dashboard.example.net/?releaseplan=35774",
            }
        ]
    )

    assert markdown.splitlines()[2].endswith(
        "| [35774](https://azsdk-releaseplan-dashboard.example.net/?releaseplan=35774) |"
    )


def test_build_markdown_displays_release_plan_number_from_camel_case_query():
    markdown = detect_unmerged_pr.build_markdown(
        [
            {
                "url": "https://github.com/Azure/azure-sdk-for-python/pull/42",
                "sdk_name": "azure-mgmt-example",
                "version": "2.0.0",
                "created": "2026-08-01",
                "approved": "-",
                "new_commit_after_approval": "-",
                "release_plan": "https://azsdk-releaseplan-dashboard.example.net/?releasePlan=2130",
            }
        ]
    )

    assert markdown.splitlines()[2].endswith(
        "| [2130](https://azsdk-releaseplan-dashboard.example.net/?releasePlan=2130) |"
    )


def test_sort_rows_orders_by_pr_created_time_new_to_old():
    rows = [
        {"created": "2026-08-01", "approved": "2026-08-04"},
        {"created": "2026-08-03", "approved": "-"},
        {"created": "2026-07-31", "approved": "2026-08-05"},
    ]

    assert detect_unmerged_pr.sort_rows(rows) == [
        {"created": "2026-08-03", "approved": "-"},
        {"created": "2026-08-01", "approved": "2026-08-04"},
        {"created": "2026-07-31", "approved": "2026-08-05"},
    ]


def test_main_includes_unapproved_pr_with_dash_approval(monkeypatch, capsys):
    monkeypatch.setattr(
        detect_unmerged_pr,
        "list_autopr_prs",
        lambda repo, limit: [
            {
                "number": 42,
                "title": "[AutoPR azure-mgmt-example]-generated",
                "url": "https://github.com/Azure/azure-sdk-for-python/pull/42",
                "createdAt": "2026-08-01T00:00:00Z",
            }
        ],
    )
    monkeypatch.setattr(
        detect_unmerged_pr,
        "pr_details",
        lambda repo, number: {
            "reviews": [],
            "commits": [{"committedDate": "2026-08-01T01:00:00Z"}],
            "body": "Release plan link: https://azsdk-releaseplan-dashboard.example.net/?releaseplan=35774",
        },
    )
    monkeypatch.setattr(detect_unmerged_pr, "sdk_version", lambda repo, number: "2.0.0")
    monkeypatch.setattr("sys.argv", ["detect_unmerged_pr.py"])

    assert detect_unmerged_pr.main() == 0

    stdout = capsys.readouterr().out
    assert (
        "| 1 | [42](https://github.com/Azure/azure-sdk-for-python/pull/42) | azure-mgmt-example | 2.0.0 | 2026-08-01 | - | - | [35774](https://azsdk-releaseplan-dashboard.example.net/?releaseplan=35774) |"
        in stdout
    )
