"""Offline cache and identity resolution tests for github-alias-to-teams-alias."""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


HELPER = Path(__file__).resolve().parents[1] / "lookup-github-teams.ps1"
PWSH = shutil.which("pwsh")
pytestmark = pytest.mark.skipif(not PWSH, reason="PowerShell 7.1+ is required")

USER = {
    "displayName": "Example Person",
    "mail": "person@microsoft.com",
    "mailNickname": "person",
    "userPrincipalName": "person-login@microsoft.com",
}


@pytest.fixture
def lookup(tmp_path):
    cache = tmp_path / "identities.json"

    def run(alias="example", **options):
        config = {
            "profile": {
                "id": 123,
                "login": "example",
                "name": "Example Person",
                "email": "person@microsoft.com",
            },
            "commits": {"items": [], "incomplete_results": False},
            "users": [USER],
            "parameters": {"GithubAlias": alias, "CachePath": str(cache)},
            **options,
        }
        config["parameters"] = {
            "GithubAlias": alias,
            "CachePath": str(cache),
            **options.get("parameters", {}),
        }
        result = subprocess.run(
            [PWSH, "-NoProfile", "-NonInteractive", "-Command", r"""
$ErrorActionPreference = 'Stop'
. $env:IDENTITY_HELPER
$script:config = $env:IDENTITY_CONFIG | ConvertFrom-Json -AsHashtable
$script:events = [System.Collections.Generic.List[string]]::new()
function Invoke-GithubIdentityApi {
    param($Endpoint)
    $script:events.Add("github:$Endpoint")
    if ($script:config.apiError) { throw 'GitHub access denied' }
    if ($Endpoint.StartsWith('users/')) { return $script:config.profile }
    return $script:config.commits
}
function Find-DirectoryIdentity {
    param($Property, $Values)
    $script:events.Add("directory:$Property")
    if ($script:config.directoryError) { throw 'Directory unavailable' }
    return $script:config.users
}
$failure = $null
$output = $null
$heldLock = $null
try {
    if ($script:config.locked) {
        $heldLock = [IO.File]::Open(
            "$($script:config.parameters.CachePath).lock", 'OpenOrCreate', 'ReadWrite', 'None')
    }
    $parameters = $script:config.parameters
    $output = Invoke-GithubTeamsLookup @parameters
}
catch { $failure = $_.Exception.Message }
finally { if ($heldLock) { $heldLock.Dispose() } }
@{ error = $failure; output = $output; events = @($script:events.ToArray()) } |
    ConvertTo-Json -Depth 30 -Compress
"""],
            env={
                **os.environ,
                "IDENTITY_HELPER": str(HELPER),
                "IDENTITY_CONFIG": json.dumps(config),
            },
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(next(line for line in reversed(result.stdout.splitlines()) if line.startswith("{")))

    run.cache = cache
    return run


def commit(email="person@microsoft.com", login="example"):
    return {
        "author": {"login": login},
        "commit": {"author": {"email": email}},
        "html_url": "https://github.com/example/repo/commit/abc",
    }


def test_new_lookup_then_case_insensitive_offline_cache_hit(lookup):
    first = lookup()
    assert first["error"] is None
    assert first["output"]["source"] == "lookup"
    record = first["output"]["record"]
    assert record["status"] == "corroborated"
    assert record["identity"] == {"displayName": USER["displayName"], "mail": USER["mail"]}
    assert record["checkedAt"]
    assert record["evidence"][0]["kind"] == "github_profile"
    assert json.loads(lookup.cache.read_text()) == {
        "schemaVersion": 2,
        "entries": {
            "example": {
                "githubAlias": "example",
                "teamsAlias": "Example Person",
                "emailAddress": USER["mail"],
            }
        },
    }
    saved = lookup.cache.read_bytes()
    second = lookup(" EXAMPLE ", apiError=True, directoryError=True)
    assert second["error"] is None
    assert second["output"]["source"] == "cache"
    assert second["output"]["record"]["identity"] == record["identity"]
    assert "checkedAt" not in second["output"]["record"]
    assert second["events"] == []
    assert lookup.cache.read_bytes() == saved


def test_refresh_queries_and_updates(lookup):
    lookup()
    result = lookup(parameters={"Refresh": True}, users=[{**USER, "displayName": "New Name"}])
    assert result["error"] is None
    assert result["events"]
    assert result["output"]["record"]["identity"]["displayName"] == "New Name"


@pytest.mark.parametrize("failure", ["apiError", "directoryError"])
def test_failed_refresh_preserves_previous_cache(lookup, failure):
    lookup()
    saved = lookup.cache.read_bytes()
    result = lookup(parameters={"Refresh": True}, **{failure: True})
    assert result["error"]
    assert result["output"] is None
    assert lookup.cache.read_bytes() == saved


def test_commit_fallback(lookup):
    result = lookup(
        profile={"id": 123, "login": "example", "email": None},
        commits={"items": [commit()], "incomplete_results": False},
    )
    assert result["error"] is None
    assert result["output"]["record"]["status"] == "corroborated"
    assert result["output"]["record"]["evidence"][0]["kind"] == "github_commit"


@pytest.mark.parametrize(
    "commits", [[commit(login="someone-else")], [commit(email="123@users.noreply.github.com")]]
)
def test_unrelated_or_noreply_commit_is_not_identity_evidence(lookup, commits):
    result = lookup(
        profile={"id": 123, "login": "example", "name": "Example Person"},
        commits={"items": commits},
    )
    assert result["output"]["record"]["status"] == "candidate"
    assert result["output"]["record"]["identity"] is None
    assert result["output"]["record"]["evidence"] == []
    assert "directory:displayName" in result["events"]


def test_conflicting_commit_emails_are_ambiguous(lookup):
    result = lookup(
        profile={"id": 123, "login": "example"},
        commits={"items": [commit(), commit(email="other@microsoft.com")]},
    )
    assert result["output"]["record"]["status"] == "ambiguous"
    assert result["output"]["record"]["identity"] is None


@pytest.mark.parametrize(
    "users,status",
    [
        ([], "not_found"),
        ([{**USER, "mail": "different@microsoft.com"}], "not_found"),
        ([USER, {**USER, "userPrincipalName": "other@microsoft.com"}], "ambiguous"),
        ([{**USER, "displayName": None}], "candidate"),
    ],
)
def test_unresolved_results_are_not_persisted_as_identities(lookup, users, status):
    first = lookup(users=users)
    assert first["error"] is None
    assert first["output"]["record"]["status"] == status
    assert first["output"]["record"]["identity"] is None
    assert lookup.cache.exists()
    assert json.loads(lookup.cache.read_text())["entries"] == {}
    second = lookup(users=users)
    assert second["output"]["source"] == "lookup"
    assert second["events"]


def test_explicit_workiq_evidence_is_directory_checked_and_saved(lookup):
    result = lookup(
        profile={"id": 123, "login": "example"},
        parameters={
            "EvidenceEmail": USER["mail"],
            "EvidenceUrl": "https://example.com/explicit-contact-table",
        },
    )
    assert result["error"] is None
    assert result["output"]["record"]["status"] == "corroborated"
    assert result["output"]["record"]["evidence"][0]["kind"] == "explicit_mapping"
    assert "directory:mail" in result["events"]


@pytest.mark.parametrize(
    "parameters",
    [
        {"GithubAlias": "https://github.com/example"},
        {"GithubAlias": "../example"},
        {"GithubAlias": ""},
        {"GithubAlias": "a--b"},
        {"EvidenceEmail": USER["mail"]},
        {"EvidenceEmail": USER["mail"], "EvidenceUrl": "file:///private"},
        {"EvidenceEmail": "person@example.com", "EvidenceUrl": "https://example.com"},
    ],
)
def test_invalid_input_does_not_query_or_write(lookup, parameters):
    result = lookup(parameters=parameters)
    assert result["error"]
    assert result["events"] == []
    assert not lookup.cache.exists()


@pytest.mark.parametrize("content", ["not json", "{}", '{"schemaVersion":3,"entries":{}}'])
def test_invalid_cache_is_not_overwritten(lookup, content):
    lookup.cache.write_text(content)
    result = lookup()
    assert result["error"]
    assert result["events"] == []
    assert lookup.cache.read_text() == content


@pytest.mark.parametrize("field,value", [("emailAddress", None), ("teamsAlias", " "), ("githubAlias", "different")])
def test_incomplete_corroborated_cache_fails_closed(lookup, field, value):
    lookup()
    cache = json.loads(lookup.cache.read_text())
    cache["entries"]["example"][field] = value
    lookup.cache.write_text(json.dumps(cache))
    saved = lookup.cache.read_bytes()
    result = lookup()
    assert result["error"]
    assert result["events"] == []
    assert lookup.cache.read_bytes() == saved


def test_busy_lock_fails_without_network_or_cache_changes(lookup):
    result = lookup(locked=True)
    assert "Cannot lock identity cache" in result["error"]
    assert result["events"] == []
    assert not lookup.cache.exists()


def test_new_entry_preserves_other_entries_and_leaves_no_temporary_files(lookup):
    lookup()
    result = lookup(
        "another", profile={"id": 456, "login": "another", "email": USER["mail"]}
    )
    assert result["error"] is None
    assert set(json.loads(lookup.cache.read_text())["entries"]) == {"example", "another"}
    assert list(lookup.cache.parent.glob("*.tmp")) == []


def test_incomplete_search_does_not_record_not_found(lookup):
    result = lookup(
        profile={"id": 123, "login": "example"},
        commits={"items": [], "incomplete_results": True},
    )
    assert "incomplete" in result["error"]
    assert not lookup.cache.exists()


def test_migrate_legacy_cache_without_network(lookup):
    legacy_record = lookup()["output"]["record"]
    legacy_record["identity"] = USER
    unresolved = {**legacy_record, "githubLogin": "unknown", "status": "candidate"}
    lookup.cache.write_text(json.dumps({
        "schemaVersion": 1, "entries": {"example": legacy_record, "unknown": unresolved}
    }))
    result = lookup(apiError=True)
    assert result["error"] is None
    assert result["events"] == []
    assert result["output"]["source"] == "cache"
    cache = json.loads(lookup.cache.read_text())
    assert cache["schemaVersion"] == 2
    assert cache["entries"] == {
        "example": {
            "githubAlias": "example",
            "teamsAlias": USER["displayName"],
            "emailAddress": USER["mail"],
        }
    }


def test_unresolved_refresh_invalidates_old_match(lookup):
    lookup()
    result = lookup(parameters={"Refresh": True}, users=[])
    assert result["error"] is None
    assert result["output"]["record"]["status"] == "not_found"
    assert json.loads(lookup.cache.read_text())["entries"] == {}
    assert lookup(apiError=True)["error"]


def test_extra_personal_fields_in_cache_are_rejected(lookup):
    lookup()
    cache = json.loads(lookup.cache.read_text())
    cache["entries"]["example"]["userPrincipalName"] = "unexpected@microsoft.com"
    lookup.cache.write_text(json.dumps(cache))
    assert lookup()["error"]


def test_directory_only_needs_display_name_and_email(lookup):
    result = lookup(users=[{"displayName": USER["displayName"], "mail": USER["mail"]}])
    assert result["error"] is None
    assert result["output"]["record"]["status"] == "corroborated"


def test_default_cache_is_beside_skill_not_working_directory(tmp_path):
    skill = tmp_path / "skills" / "github-alias-to-teams-alias"
    skill.mkdir(parents=True)
    common = skill.parent / "common"
    common.mkdir()
    shutil.copyfile(HELPER, skill / HELPER.name)
    shutil.copyfile(
        HELPER.parent.parent / "common" / "agency-mcp.ps1",
        common / "agency-mcp.ps1",
    )
    cache = skill / "identity.json"
    cache.write_text(json.dumps({
        "schemaVersion": 2,
        "entries": {
            "example": {
                "githubAlias": "example",
                "teamsAlias": USER["displayName"],
                "emailAddress": USER["mail"],
            }
        },
    }))
    result = subprocess.run(
        [PWSH, "-NoProfile", "-NonInteractive", "-File", str(skill / HELPER.name),
         "-GithubAlias", "example"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["source"] == "cache"
    assert Path(output["cachePath"]) == cache
    assert not (tmp_path / "identity.json").exists()
