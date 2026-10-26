import base64
import json
import os
import sys
from dataclasses import replace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import detect_unmerged_pr as report

REPO = "Azure/azure-sdk-for-python"
PLAN = "https://dashboard.example.net/?releaseplan=35774"
PATH = "sdk/example/azure-mgmt-example/azure/mgmt/example/_version.py"


def review(login="maintainer", state="APPROVED", date="2026-08-02T12:00:00Z", commit="head", id=1):
    return {
        "id": id, "user": {"login": login}, "state": state,
        "submitted_at": date, "commit_id": commit,
    }


def row(**changes):
    original = report.ActionPR(
        number=42, url=f"https://github.com/{REPO}/pull/42",
        sdk_name="azure-mgmt-example", version="2.0.0",
        created="2026-08-01T12:00:00Z", needs_label=False, owners=("@maintainer",),
        approval=review(), newer_commits=False, release_plan=PLAN,
    )
    return replace(original, **changes)


def test_list_ignores_drafts_and_non_autoprs(monkeypatch, capsys):
    def fake_run(args):
        assert "--state" in args and args[args.index("--state") + 1] == "open"
        assert args[args.index("--json") + 1] == "number,title,url,createdAt,isDraft"
        return json.dumps([
            {"number": 1, "title": "[AutoPR azure-mgmt-a]-generated", "isDraft": True},
            {"number": 2, "title": "Other azure-mgmt-a", "isDraft": False},
            {"number": 3, "title": "[AutoPR azure-mgmt-b]-generated", "isDraft": False},
        ])

    monkeypatch.setattr(report, "run_gh", fake_run)
    assert [pr["number"] for pr in report.list_autopr_prs(REPO, 3)] == [3]
    assert "reached --limit 3" in capsys.readouterr().err


def test_api_pages_uses_slurp_and_flattens_all_pages(monkeypatch):
    def fake_run(args):
        assert args == ["api", "--paginate", "--slurp", "endpoint?per_page=100"]
        return '[[{"number": 1}], [{"number": 2}]]'

    monkeypatch.setattr(report, "run_gh", fake_run)
    assert report.api_pages("endpoint?per_page=100") == [{"number": 1}, {"number": 2}]


def test_run_gh_preserves_failure(monkeypatch):
    import subprocess

    monkeypatch.setattr(
        report.subprocess, "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 1, "", "HTTP 403: access denied"),
    )
    with pytest.raises(report.GhError, match="HTTP 403: access denied"):
        report.run_gh(["api", "endpoint"])


def test_sdk_version_prefers_package_version_over_changelog():
    files = [
        {"filename": "sdk/example/azure-mgmt-example/CHANGELOG.md", "patch": "+## 9.0.0\n"},
        {"filename": PATH, "patch": '-VERSION = "1.0.0"\n+VERSION = "2.0.0"\n'},
        {"filename": "sdk/other/azure-mgmt-other/_version.py", "patch": '+VERSION = "3.0.0"\n'},
    ]
    selected = report.sdk_files(files, "azure-mgmt-example")
    assert len(selected) == 2
    assert report.sdk_version(selected) == "2.0.0"


def test_sdk_version_falls_back_to_added_changelog_heading():
    assert report.sdk_version([
        {"filename": "sdk/example/CHANGELOG.md", "patch": " ## 1.0.0\n+## 2.0.0 (2026-08-01)\n"},
    ]) == "2.0.0"
    assert report.sdk_version([{"filename": PATH}]) is None


def test_sdk_files_includes_files_renamed_out_of_the_package():
    renamed = {"filename": "sdk/other/new.py", "previous_filename": PATH, "status": "renamed"}
    assert report.sdk_files([renamed], "azure-mgmt-example") == [renamed]


@pytest.mark.parametrize(("pattern", "path", "matches"), [
    ("/**/*mgmt*/", PATH, True),
    ("/**/*mgmt*/", "sdk/example/azure-example/file.py", False),
    ("/sdk/**/ci.yml", "sdk/ci.yml", True),
    ("/sdk/**/ci.yml", "sdk/example/nested/ci.yml", True),
    ("/sdk/**/ci.yml", "other/sdk/example/ci.yml", False),
    ("/sdk/*/azure-mgmt-example/", PATH, True),
    ("/sdk/*/azure-mgmt-example/", "sdk/a/b/azure-mgmt-example/file.py", False),
    ("*.py", PATH, True),
    ("/README.md", "sdk/README.md", False),
    ("docs/", "nested/docs/guide.md", True),
    ("/docs/", "nested/docs/guide.md", False),
    ("file?.py", "sdk/file1.py", True),
    ("file?.py", "sdk/file12.py", False),
])
def test_codeowners_pattern(pattern, path, matches):
    assert bool(report.codeowners_pattern(pattern).search(path)) is matches


def test_codeowners_last_match_empty_owner_and_comments():
    rules = report.parse_codeowners("""
# Catch all
* @general
/sdk/ @sdk
/**/*mgmt*/ @maintainer @Org/reviewers # Management Libraries
!invalid @ignored
/bad/[abc]/ @ignored
/sdk/example/azure-mgmt-example/secret/
""")
    owners, issues = report.owners_for_files([{"filename": PATH}], rules)
    assert owners == ("@maintainer", "@Org/reviewers")
    assert issues == ()
    owners, issues = report.owners_for_files([{"filename": "sdk/example/azure-mgmt-example/secret/a"}], rules)
    assert owners == ()
    assert "No CODEOWNERS configured" in issues[0]


def test_owners_union_package_rules_and_base_path_of_renames():
    rules = report.parse_codeowners("/sdk/old/ @old\n/sdk/new/ @new\n")
    owners, issues = report.owners_for_files([
        {"filename": "sdk/new/a", "previous_filename": "sdk/old/a", "status": "renamed"},
        {"filename": "sdk/new/b"},
    ], rules)
    assert owners == ("@new", "@old")
    assert not issues
    assert report.owners_for_files([], rules)[1]


def test_load_codeowners_precedence_and_base_ref(monkeypatch):
    calls = []

    def fake_run(args):
        calls.append(args[-1])
        if "/.github/" in args[-1]:
            raise report.GhError(args, 1, "Not Found (HTTP 404)")
        return json.dumps({
            "encoding": "base64",
            "content": base64.b64encode(b"/sdk/ @maintainer\n").decode(),
        })

    monkeypatch.setattr(report, "run_gh", fake_run)
    rules = report.load_codeowners(REPO, "base-sha")
    assert len(rules) == 1
    assert calls == [
        f"repos/{REPO}/contents/.github/CODEOWNERS?ref=base-sha",
        f"repos/{REPO}/contents/CODEOWNERS?ref=base-sha",
    ]


@pytest.mark.parametrize("stderr", ["Forbidden (HTTP 403)", "Not Found (HTTP 404)"])
def test_load_codeowners_errors_are_not_silent(monkeypatch, stderr):
    def fail(args):
        raise report.GhError(args, 1, stderr)

    monkeypatch.setattr(report, "run_gh", fail)
    with pytest.raises(RuntimeError, match="HTTP 403|No CODEOWNERS file"):
        report.load_codeowners(REPO, "base")


def test_resolve_maintainers_expands_and_caches_teams(monkeypatch):
    calls = []

    def pages(endpoint):
        calls.append(endpoint)
        return [{"login": "TeamMember"}]

    monkeypatch.setattr(report, "api_pages", pages)
    cache = {}
    for _ in range(2):
        maintainers, issues = report.resolve_maintainers(("@Direct", "@Org/reviewers"), cache)
        assert maintainers == {"direct", "teammember"}
        assert not issues
    assert calls == ["orgs/Org/teams/reviewers/members?per_page=100"]


def test_unreadable_team_is_unknown_not_missing_approval(monkeypatch):
    def fail(endpoint):
        raise report.GhError(["api", endpoint], 1, "Forbidden (HTTP 403)")

    monkeypatch.setattr(report, "api_pages", fail)
    maintainers, issues = report.resolve_maintainers(("@maintainer", "@Org/private"), {})
    assert maintainers == {"maintainer"}
    assert "HTTP 403" in issues[0]
    text = report.build_report(REPO, [row(approval=None, ownership_issues=issues)])
    assert "## 2." in text
    assert "approval verification incomplete" in text
    assert "no SDK-maintainer approval" not in text
    assert "HTTP 403" in text


def test_non_login_owner_is_explicit():
    assert "Cannot resolve" in report.resolve_maintainers(("owner@example.com",), {})[1][0]


def test_approval_from_any_owner_case_insensitive_not_unrelated_reviewers():
    reviews = [review("MAINTAINER"), review("stranger", date="2026-08-03T00:00:00Z", id=2)]
    assert report.latest_maintainer_approval(reviews, {"maintainer"}) == reviews[0]
    assert report.latest_maintainer_approval(reviews, {"other"}) is None


@pytest.mark.parametrize("later_state", ["DISMISSED", "CHANGES_REQUESTED"])
def test_later_opinionated_review_invalidates_approval(later_state):
    reviews = [review(), review(state=later_state, date="2026-08-03T00:00:00Z", id=2)]
    assert report.latest_maintainer_approval(reviews, {"maintainer"}) is None


def test_comments_and_pending_reviews_do_not_revoke_approval():
    approval = review()
    assert report.latest_maintainer_approval([
        review(state="COMMENTED", date="2026-08-03T00:00:00Z", id=2),
        approval,
        {"id": 3, "user": {"login": "maintainer"}, "state": "PENDING", "submitted_at": None},
        {"id": 4, "user": None, "state": "COMMENTED", "submitted_at": "2026-08-04T00:00:00Z"},
    ], {"maintainer"}) == approval


def test_latest_effective_approval_from_multiple_maintainers():
    newer = review("second", date="2026-08-03T00:00:00Z", id=2)
    reviews = [review(), newer, review(state="CHANGES_REQUESTED", date="2026-08-04T00:00:00Z", id=3)]
    assert report.latest_maintainer_approval(reviews, {"maintainer", "second"}) == newer


@pytest.mark.parametrize(("date", "head", "expected"), [
    ("2026-08-02T11:00:00Z", "head", False),
    ("2026-08-02T12:00:00Z", "head", False),
    ("2026-08-02T13:00:00Z", "head", True),
    ("2026-08-02T11:00:00Z", "rebased-head", True),
    ("2026-08-02T14:00:00+02:00", "head", False),
])
def test_newer_commits_use_timestamps_and_reviewed_head(date, head, expected):
    assert report.has_newer_commits([{"commit": {"committer": {"date": date}}}], review(), head) is expected


@pytest.mark.parametrize("body", [
    f"Release plan: {PLAN}",
    f"**Release plan link:** [{PLAN}]({PLAN})",
    f"Pipeline run: https://pipeline.example.net/1. **Release plan link:** [{PLAN}]({PLAN}) **Submitted by**: me",
    f"## Release plan\n[Plan]({PLAN})\n\n## Checklist\nOther stuff",
    f"## Release plan\r\n{PLAN}\r\n\r\n## Checklist\r\nOther stuff",
    f"See <{PLAN}> for tracking.",
    "Release plan link: https://example.test/123",
])
def test_extract_release_plan_supported_formats(body):
    expected = "https://example.test/123" if body.endswith("https://example.test/123") else PLAN
    assert report.extract_release_plan(body) == expected


@pytest.mark.parametrize("body", [
    "",
    "Release plan: not available\nPipeline: https://pipeline.example.net/42",
    "Release plan:\n\n## Pipeline\nhttps://pipeline.example.net/42",
    "## Release plan\nNot yet created.\n\n## Checklist\nhttps://example.test/42",
    "Pipeline: https://example.test/42",
])
def test_release_plan_does_not_consume_unrelated_sections(body):
    assert report.extract_release_plan(body) is None


def test_release_plan_chooses_first_link_not_later_markdown():
    assert report.extract_release_plan("Release plan: https://first.test/1 then [other](https://other.test/2)") == (
        "https://first.test/1"
    )


@pytest.mark.parametrize(("label", "link"), [
    ("**Release plan**", f"[Release plan #35774]({PLAN})"),
    ("Release plan", "https://example.test/plans/35774"),
    ("**Release plan link**", "[Plan](https://example.test/plans/35774)"),
    ("RELEASE PLAN", "<https://example.test/plans/35774>"),
])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_release_plan_from_sdk_generation_details_table(label, link, newline):
    body = newline.join([
        "<!-- azsdk-autopr-description:v1:start -->",
        "## SDK generation details",
        "",
        "| Detail | Value |",
        "| :--- | :--- |",
        "| **Pipeline run** | [SDK Generation #6996283](https://dev.azure.com/example/6996283) |",
        f"| {label} | {link} |",
        "| **Submitted by** | `user@example.test` |",
        "<!-- azsdk-autopr-description:v1:end -->",
    ])
    expected = PLAN if "releaseplan=" in link else "https://example.test/plans/35774"
    extracted = report.extract_release_plan(body)
    assert extracted == expected
    assert report.build_report(REPO, [row(release_plan=extracted)]) == "No PRs need action."


@pytest.mark.parametrize("value", ["", "Not yet created"])
def test_empty_release_plan_table_cell_does_not_consume_other_links(value):
    body = (
        f"| **Release plan** | {value} | [Unrelated](https://example.test/other) |\n"
        "| **Pipeline run** | [Run](https://example.test/pipeline) |\n"
    )
    assert report.extract_release_plan(body) is None


def test_report_fixed_section_ids_order_and_overlapping_actions():
    output = report.build_report(REPO, [
        row(needs_label=True, approval=None, release_plan=None),
        row(number=43, newer_commits=True),
    ])
    headings = [line for line in output.splitlines() if line.startswith("## ")]
    assert headings == [
        "## 1. Add `mgmt-review-needed`",
        "## 2. SDK maintainer review needed",
        "## 3. SDK maintainer re-review needed",
        "## 4. Release plan needs checking",
    ]
    assert output.count(f"[{REPO}#42]") == 3
    assert output.count(f"[{REPO}#43]") == 1
    assert "manually to trigger Copilot review" in output
    assert "Maintainers: @maintainer" in output
    assert "approved by @maintainer on 2026-08-02" in output
    assert "contact the service team" in output
    assert "update this skill" in output
    assert "| ---" not in output


def test_report_omits_clean_prs_and_empty_sections_without_renumbering():
    assert report.build_report(REPO, [row()]) == "No PRs need action."
    assert report.build_report(REPO, []) == "No PRs need action."
    output = report.build_report(REPO, [row(), row(number=43, release_plan=None)])
    assert output.startswith("## 4. Release plan needs checking")
    assert f"[{REPO}#42]" not in output


def test_report_sorts_by_full_creation_timestamp():
    output = report.build_report(REPO, [
        row(number=42, needs_label=True, created="2026-08-01T01:00:00Z"),
        row(number=43, needs_label=True, created="2026-08-01T13:00:00Z"),
    ])
    assert output.index(f"[{REPO}#43]") < output.index(f"[{REPO}#42]")


def install_fake_github(monkeypatch, *, draft=False, state="open", version="2.0.0"):
    calls = []
    prefix = f"repos/{REPO}/pulls/"

    def fake_run(args):
        calls.append(args)
        if args[:2] == ["pr", "list"]:
            return json.dumps([
                {"number": number, "title": "[AutoPR azure-mgmt-example]-generated",
                 "url": f"https://github.com/{REPO}/pull/{number}",
                 "createdAt": "2026-08-01T00:00:00Z", "isDraft": False}
                for number in (42, 43)
            ])
        endpoint = args[-1]
        if "/contents/" in endpoint:
            return json.dumps({
                "encoding": "base64",
                "content": base64.b64encode(b"/**/*mgmt*/ @maintainer @Org/team\n").decode(),
            })
        if endpoint.startswith("orgs/"):
            return json.dumps([[{"login": "team-reviewer"}]])
        if endpoint.endswith("/files?per_page=100"):
            return json.dumps([[{"filename": PATH, "patch": f'+VERSION = "{version}"'}]])
        if endpoint.endswith("/reviews?per_page=100"):
            return json.dumps([[review("team-reviewer")]])
        if endpoint.endswith("/commits?per_page=100"):
            return json.dumps([[{"commit": {"committer": {"date": "2026-08-01T00:00:00Z"}}}]])
        assert endpoint in (prefix + "42", prefix + "43")
        return json.dumps({
            "draft": draft, "state": state,
            "labels": [{"name": "mgmt-review-needed"}], "body": f"Release plan: {PLAN}",
            "base": {"sha": "base"}, "head": {"sha": "head"},
        })

    monkeypatch.setattr(report, "run_gh", fake_run)
    monkeypatch.setattr(sys, "argv", ["detect_unmerged_pr.py"])
    return calls


def test_main_end_to_end_clean_team_approvals_and_cached_ownership(monkeypatch, capsys):
    calls = install_fake_github(monkeypatch)
    assert report.main() == 0
    assert capsys.readouterr().out == "No PRs need action.\n"
    assert sum("/contents/" in args[-1] for args in calls) == 1
    assert sum(args[-1].startswith("orgs/") for args in calls) == 1
    assert sum("/reviews?" in args[-1] for args in calls) == 2
    assert sum("/commits?" in args[-1] for args in calls) == 2


@pytest.mark.parametrize(("draft", "state", "version"), [
    (True, "open", "2.0.0"),
    (False, "closed", "2.0.0"),
    (False, "open", "1.0.0b1"),
])
def test_main_ignores_ineligible_prs_before_reading_ownership_and_reviews(monkeypatch, capsys, draft, state, version):
    calls = install_fake_github(monkeypatch, draft=draft, state=state, version=version)
    assert report.main() == 0
    assert capsys.readouterr().out == "No PRs need action.\n"
    assert not any("/contents/" in args[-1] or "/reviews?" in args[-1] for args in calls)


def test_main_unapproved_pr_only_uses_necessary_endpoints(monkeypatch, capsys):
    install_fake_github(monkeypatch)
    original = report.run_gh

    def fake_run(args):
        if "/commits?" in args[-1]:
            pytest.fail("Unapproved PR does not need commits fetched.")
        if "/reviews?" in args[-1]:
            return "[[]]"
        return original(args)

    monkeypatch.setattr(report, "run_gh", fake_run)
    assert report.main() == 0
    output = capsys.readouterr().out
    assert output.startswith("## 2. SDK maintainer review needed")
    assert output.count("no SDK-maintainer approval") == 2


def test_main_reports_overlapping_actions_and_only_stale_approval_needs_rereview(monkeypatch, capsys):
    install_fake_github(monkeypatch)
    original = report.run_gh

    def fake_run(args):
        endpoint = args[-1]
        if endpoint.endswith("/reviews?per_page=100"):
            return json.dumps([[] if "/42/" in endpoint else [review("team-reviewer", commit="older-head")]])
        result = json.loads(original(args))
        if endpoint.endswith("/42"):
            result.update(labels=[], body="")
        return json.dumps(result)

    monkeypatch.setattr(report, "run_gh", fake_run)
    assert report.main() == 0
    text = capsys.readouterr().out
    assert [line for line in text.splitlines() if line.startswith("## ")] == [
        "## 1. Add `mgmt-review-needed`",
        "## 2. SDK maintainer review needed",
        "## 3. SDK maintainer re-review needed",
        "## 4. Release plan needs checking",
    ]
    assert text.count(f"[{REPO}#42]") == 3
    assert text.count(f"[{REPO}#43]") == 1


def test_main_label_matching_is_case_insensitive(monkeypatch, capsys):
    install_fake_github(monkeypatch)
    original = report.run_gh

    def fake_run(args):
        result = json.loads(original(args))
        if isinstance(result, dict) and "labels" in result:
            result["labels"] = [{"name": "Mgmt-Review-Needed"}]
        return json.dumps(result)

    monkeypatch.setattr(report, "run_gh", fake_run)
    assert report.main() == 0
    assert capsys.readouterr().out == "No PRs need action.\n"


def test_main_unknown_version_warns_and_does_not_silently_exclude(monkeypatch, capsys):
    install_fake_github(monkeypatch)
    monkeypatch.setattr(report, "sdk_version", lambda files: None)
    monkeypatch.setattr(report, "extract_release_plan", lambda body: None)
    assert report.main() == 0
    captured = capsys.readouterr()
    assert "SDK version could not be determined" in captured.err
    assert "`unknown`" in captured.out


def test_main_rejects_nonpositive_limit(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["detect_unmerged_pr.py", "--limit", "0"])
    with pytest.raises(SystemExit) as error:
        report.main()
    assert error.value.code == 2
