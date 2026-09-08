"""Exercise the PowerShell helpers with mocked Agency transport; never send mail."""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


SKILLS = Path(__file__).resolve().parents[2]
PWSH = shutil.which("pwsh")
pytestmark = pytest.mark.skipif(not PWSH, reason="PowerShell 7.1+ is required")


@pytest.fixture
def run_helper(tmp_path):
    common = tmp_path / "common"
    common.mkdir()
    real_common = str(SKILLS / "common" / "agency-mcp.ps1").replace("'", "''")
    (common / "agency-mcp.ps1").write_text(
        f". '{real_common}'\n"
        + r"""
function Start-AgencyMcp {
    param($Server, $ClientName)
    $global:events.Add("start:$Server")
    return @{ BaseUrl = $Server }
}
function Stop-AgencyMcp {
    param($Connection)
    if ($Connection) { $global:events.Add("stop:$($Connection.BaseUrl)") }
}
function Invoke-McpCall {
    param($BaseUrl, $Method, $Params, $Id)
    $global:events.Add($Params.name)
    switch ($Params.name) {
        'GetMyDetails' { $payload = $global:config.me }
        'GetMultipleUsersDetails' { $payload = @{ value = @($global:config.users) } }
        'ListTeams' { $payload = @{ value = @(@{ id = 'team1'; displayName = 'Team' }) } }
        'ListChannels' { $payload = @{ value = @(@{ id = 'channel1'; displayName = 'Channel' }) } }
        { $_ -in @('SendEmailWithAttachments', 'SendMessageToSelf', 'SendMessageToUser', 'SendMessageToChannel') } {
            $global:sentArguments = $Params.arguments
            if ($global:config.sendError) { throw 'Simulated send timeout' }
            if ($global:config.toolError) {
                return @{ isError = $true; content = @(@{ type = 'text'; text = 'Denied' }) }
            }
            $payload = $global:config.sendResult
        }
        default { throw "Unexpected tool: $($Params.name)" }
    }
    return @{
        content = @(
            @{ type = 'text'; text = "Tool result:`n$($payload | ConvertTo-Json -Depth 20 -Compress)" }
            @{ type = 'text'; text = 'CorrelationId: hidden' }
        )
    }
}
""",
        encoding="utf-8",
    )

    def run(parameters, *, skill="email-send-message", **config):
        skill_dir = tmp_path / skill
        skill_dir.mkdir(exist_ok=True)
        filename = (
            "send-email-message.ps1"
            if skill == "email-send-message"
            else "send-teams-message.ps1"
        )
        helper = skill_dir / filename
        shutil.copyfile(SKILLS / skill / filename, helper)
        settings = {
            "parameters": parameters,
            "me": {
                "id": "self",
                "displayName": "Signed In",
                "mail": "self@example.com",
                "userPrincipalName": "login@example.com",
            },
            "users": [],
            "sendResult": {"data": {"sent": True, "messageId": "mail-id"}},
            **config,
        }
        env = {
            **os.environ,
            "EMAIL_TEST_CONFIG": json.dumps(settings),
            "EMAIL_TEST_HELPER": str(helper),
        }
        result = subprocess.run(
            [
                PWSH,
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                r"""
$ErrorActionPreference = 'Stop'
$global:config = $env:EMAIL_TEST_CONFIG | ConvertFrom-Json -AsHashtable
$global:events = [System.Collections.Generic.List[string]]::new()
$global:sentArguments = $null
function global:Get-Command { param($Name, $ErrorAction) return @{ Source = 'mock-agency' } }
$parameters = $global:config.parameters
$failure = $null
try { $output = & $env:EMAIL_TEST_HELPER @parameters }
catch { $failure = $_.Exception.Message }
$summary = @{
    error = $failure
    output = ($output -join "`n")
    arguments = $global:sentArguments
    events = @($global:events.ToArray())
}
Write-Output ("RESULT:" + ($summary | ConvertTo-Json -Depth 30 -Compress))
""",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        summary = next(
            line.removeprefix("RESULT:")
            for line in result.stdout.splitlines()
            if line.startswith("RESULT:")
        )
        return json.loads(summary)

    return run


@pytest.mark.parametrize(
    "parameters,subject,body",
    [
        ({"Message": "same"}, "same", "same"),
        ({"Subject": "subject only"}, "subject only", "subject only"),
        ({"Body": "body only"}, "body only", "body only"),
        ({"Subject": "title", "Body": "content"}, "title", "content"),
        ({"Message": "same", "Subject": "title"}, "title", "same"),
        ({"Message": "same", "Body": "content"}, "same", "content"),
        ({"Message": "unused", "Subject": "title", "Body": "content"}, "title", "content"),
        ({"Message": 'quotes " and\nnewlines \u4f60\u597d'}, 'quotes " and\nnewlines \u4f60\u597d', 'quotes " and\nnewlines \u4f60\u597d'),
    ],
)
def test_content_defaults_and_overrides(run_helper, parameters, subject, body):
    result = run_helper(parameters)
    assert result["error"] is None
    assert result["arguments"] == {
        "to": ["self@example.com"],
        "cc": [],
        "bcc": [],
        "subject": subject,
        "body": body,
        "contentType": "Text",
    }
    assert json.loads(result["output"])["status"] == "sent"
    assert result["events"].count("SendEmailWithAttachments") == 1
    assert result["events"][-2:] == ["stop:mail", "stop:m365-user"]


def test_explicit_addresses_skip_identity_lookup(run_helper):
    result = run_helper(
        {"To": ["first@example.com", "second@example.com"], "Message": "test"}
    )
    assert result["error"] is None
    assert "start:m365-user" not in result["events"]


def test_named_recipients_cc_bcc_and_alias(run_helper):
    result = run_helper(
        {
            "Recipient": ["Jane Doe", "external@example.com"],
            "Cc": ["jane"],
            "Bcc": ["me"],
            "Message": "test",
        },
        users=[{"displayName": "Jane Doe", "mail": "jane@example.com"}],
    )
    assert result["error"] is None
    assert result["arguments"]["to"] == ["jane@example.com", "external@example.com"]
    assert result["arguments"]["cc"] == ["jane@example.com"]
    assert result["arguments"]["bcc"] == ["self@example.com"]


@pytest.mark.parametrize(
    "users",
    [
        [],
        [{"displayName": "Jane Other", "mail": "other@example.com"}],
        [
            {"displayName": "Jane", "mail": "one@example.com"},
            {"displayName": "Jane", "mail": "two@example.com"},
        ],
    ],
)
def test_unresolved_cc_blocks_entire_send(run_helper, users):
    result = run_helper(
        {"To": ["known@example.com"], "Cc": ["Jane"], "Message": "test"},
        users=users,
    )
    assert result["error"]
    assert result["arguments"] is None
    assert "start:mail" not in result["events"]
    assert "stop:m365-user" in result["events"]


def test_missing_mail_does_not_fall_back_to_upn(run_helper):
    result = run_helper({"Message": "test"}, me={"userPrincipalName": "login@example.com"})
    assert "no mailbox" in result["error"]
    assert result["arguments"] is None


@pytest.mark.parametrize(
    "parameters",
    [
        {},
        {"Message": " "},
        {"Message": "test", "Subject": " "},
        {"Message": "test", "To": ["bad@@example.com"]},
        {"Message": "test", "To": ["Name <name@example.com>"]},
        {"Message": "test", "Bcc": [" "]},
    ],
)
def test_invalid_inputs_never_send(run_helper, parameters):
    result = run_helper(parameters)
    assert result["error"]
    assert "start:mail" not in result["events"]


def test_whatif_resolves_without_sending(run_helper):
    result = run_helper({"Message": "preview", "WhatIf": True})
    assert result["error"] is None
    assert "GetMyDetails" in result["events"]
    assert "start:mail" not in result["events"]
    assert json.loads(result["output"])["status"] == "not-sent"


@pytest.mark.parametrize(
    "config",
    [
        {"sendError": True},
        {"toolError": True},
        {"sendResult": {"data": {"sent": False, "messageId": "draft-id"}}},
        {"sendResult": {"data": {"sent": True}}},
    ],
)
def test_unconfirmed_sends_are_not_retried(run_helper, config):
    result = run_helper({"Message": "test"}, **config)
    assert result["error"]
    assert result["events"].count("SendEmailWithAttachments") == 1
    assert result["events"][-2:] == ["stop:mail", "stop:m365-user"]


@pytest.mark.parametrize(
    "parameters,tool",
    [
        ({"Recipient": "me", "Message": "test"}, "SendMessageToSelf"),
        ({"Recipient": "Jane", "Message": "test"}, "SendMessageToUser"),
        ({"Team": "Team", "Channel": "Channel", "Message": "test"}, "SendMessageToChannel"),
    ],
)
def test_teams_still_uses_shared_transport(run_helper, parameters, tool):
    result = run_helper(
        parameters,
        skill="teams-send-message",
        users=[{"id": "jane", "displayName": "Jane", "userPrincipalName": "jane@example.com"}],
        sendResult={"id": "teams-id"},
    )
    assert result["error"] is None
    assert tool in result["events"]
    assert json.loads(result["output"])["status"] == "sent"


def test_shared_transport_parses_json_and_sse():
    common = str(SKILLS / "common" / "agency-mcp.ps1").replace("'", "''")
    result = subprocess.run(
        [
            PWSH, "-NoProfile", "-NonInteractive", "-Command",
            f". '{common}'\n" + r"""
$ErrorActionPreference = 'Stop'
function Invoke-WebRequest { return @{ Content = $global:response } }
foreach ($global:response in @(
    '{"jsonrpc":"2.0","id":1,"result":{"ok":true}}',
    "data: {`"method`":`"notification`"}`n`ndata: {`"id`":1,`"result`":{`"ok`":true}}`n"
)) {
    $result = Invoke-McpCall -BaseUrl 'http://unused/' -Method 'initialize'
    if ($result.ok -ne $true) { throw 'Response was not parsed' }
}
$global:response = '{"id":1,"error":{"message":"Denied"}}'
try {
    Invoke-McpCall -BaseUrl 'http://unused/' -Method 'initialize'
    throw 'Expected RPC failure'
}
catch {
    if ($_.Exception.Message -notlike '*Agency MCP error: Denied*') { throw }
}
$parsed = ConvertFrom-ToolContent -ToolResult @{
    content = @(@{ type = 'text'; text = 'not JSON {oops' }, @{ type = 'text'; text = 'prefix {"id":"ok"}' })
}
if ($parsed.id -ne 'ok') { throw 'Text JSON was not parsed' }
$parsed = ConvertFrom-ToolContent -ToolResult @{ structuredContent = @{ id = 'structured' } }
if ($parsed.id -ne 'structured') { throw 'Structured JSON was not parsed' }
""",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
