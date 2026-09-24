#requires -Version 7.5
# Synthetic MCP responses only; no Agency process, network, or real sleeps.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\scripts\Export-TeamsChannel.ps1') `
    -TeamsChannelId '19:fixture@thread.skype' -StartTime '2026-09-01' -EndTime '2026-09-07'

function Assert($Condition, [string]$Message) {
    if (-not $Condition) { throw "Assertion failed: $Message" }
}

function Set-Scenario([object[]]$Steps) {
    $script:Steps = [Collections.Generic.Queue[object]]::new()
    foreach ($step in $Steps) { $script:Steps.Enqueue($step) }
    $script:Requests = [Collections.Generic.List[object]]::new()
    $script:Delays = [Collections.Generic.List[double]]::new()
    $script:Events = [Collections.Generic.List[string]]::new()
    $script:McpUri = 'http://fixture.invalid/'
    $script:McpHeaders = @{}
    $script:RequestId = 0
}

function Write-Host($Object) {
    $script:Events.Add([string]$Object)
}

function Write-Warning([string]$Message) {
    $script:Events.Add($Message)
    Microsoft.PowerShell.Utility\Write-Warning $Message
}

function Invoke-WebRequest($Uri, $Method, $Headers, $ContentType, $Body, $TimeoutSec, [switch]$SkipHttpErrorCheck) {
    $request = $Body | ConvertFrom-Json -AsHashtable -DateKind String
    $script:Requests.Add($request)
    Assert ($Uri -eq 'http://fixture.invalid/') 'mock endpoint only'
    Assert ($request.method -eq 'tools/call') 'only read tool calls'
    Assert (Test-ReadOnlyAgencyTool $request.params.name) 'read-only allowlist enforced'
    Assert ($TimeoutSec -eq 120) 'outer HTTP timeout unchanged'
    Assert ($script:Events[$script:Events.Count - 1] -match 'request attempt \d/5 in flight') 'in-flight operation emitted before request'
    Assert ($script:Steps.Count -gt 0) 'request budget exceeded fixture'
    $step = $script:Steps.Dequeue()
    if ($step.exception) { throw [IO.IOException]::new($step.exception) }
    $rpc = @{ jsonrpc = '2.0'; id = $request.id; result = $step.result }
    $text = $rpc | ConvertTo-Json -Depth 30 -Compress
    if ($step.sse) { $text = "event: message`ndata: $text`n`n" }
    return @{
        StatusCode = $(if ($step.status) { $step.status } else { 200 })
        Headers = $(if ($step.headers) { $step.headers } else { @{} })
        Content = $text
    }
}

function Start-Sleep([double]$Seconds) {
    Assert ($script:Events[$script:Events.Count - 1].Contains("in $Seconds seconds")) 'visible delay emitted before sleeping'
    $script:Delays.Add($Seconds)
}

function Get-Failure([scriptblock]$Action) {
    try { & $Action | Out-Null } catch { return $_.Exception.Message }
    throw 'Expected failure did not occur.'
}

$timeoutText = 'Error: Error executing tool: Failed to list channels: The request was canceled due to the configured HttpClient.Timeout of 30 seconds elapsing.'
$timeoutResult = @{
    isError = $true
    structuredContent = @{ partialBody = 'SYNTHETIC_SECRET_BODY' }
    content = @(
        @{ type = 'text'; text = "$timeoutText`r`nCorrelationId: fixture-correlation, TimeStamp: 2026-09-23_09:15:15" }
        @{ type = 'text'; text = 'CorrelationId: fixture-correlation, TimeStamp: 2026-09-23_09:15:15' }
    )
}
$timeoutStep = @{ result = $timeoutResult }
$success = @{ result = @{ structuredContent = @{ channels = @(@{ id = 'fixture-channel' }) } } }
$arguments = @{ teamId = '11111111-2222-3333-4444-555555555555' }
$originalArguments = $arguments | ConvertTo-Json -Compress

Set-Scenario @($timeoutStep, $success)
$captured = @(Invoke-AgencyTool 'ListChannels' $arguments 3>&1)
$warnings = @($captured | Where-Object { $_ -is [Management.Automation.WarningRecord] })
$result = $captured | Where-Object { $_ -isnot [Management.Automation.WarningRecord] }
Assert ($result.channels[0].id -eq 'fixture-channel') 'timeout then success returns actual data'
Assert ($script:Requests.Count -eq 2 -and ($script:Delays -join ',') -eq '2') 'one retry after two seconds'
Assert (($warnings -join "`n") -match 'ListChannels.*retry 1/4 in 2 seconds') 'visible retry tool, attempt and delay'
Assert (($arguments | ConvertTo-Json -Compress) -eq $originalArguments) 'caller arguments not mutated'
Assert (($script:Requests[0] | ConvertTo-Json -Depth 10 -Compress) -eq
    ($script:Requests[1] | ConvertTo-Json -Depth 10 -Compress)) 'same read request retried'

Set-Scenario @($timeoutStep, $timeoutStep, $timeoutStep, $timeoutStep, $timeoutStep)
$failure = Get-Failure { Invoke-AgencyTool 'ListChannels' $arguments }
Assert ($script:Requests.Count -eq 5) 'exhaustion bounded to five total attempts'
Assert (($script:Delays -join ',') -eq '2,4,8,16') 'bounded exponential backoff'
Assert ($failure.Contains($timeoutText) -and $failure.Contains('fixture-correlation') -and
    $failure.Contains('2026-09-23_09:15:15')) 'exhaustion preserves original error and correlation details'
Assert (($script:Events -join "`n").Contains('retry budget/wait limit exhausted')) 'exhaustion visibly reported'
Assert (-not ($script:Events -join "`n").Contains('SYNTHETIC_SECRET_BODY')) 'error progress never includes partial message bodies'
Assert ($script:Events[0] -match '^\[\d{4}-\d{2}-\d{2}T.+\] \[INFO\]') 'retry operations timestamped'

foreach ($text in @(
    'Forbidden: insufficient permissions to list channels.',
    'Unauthorized: token expired.',
    'Invalid argument: teamId must be a GUID.',
    'An unexpected error occurred.',
    'The request was canceled.',
    'Gateway timeout.',
    "AccessDenied: missing permission. $timeoutText"
    "InvalidAuthenticationToken: $timeoutText"
)) {
    Set-Scenario @(@{ result = @{ isError = $true; content = @(@{ type = 'text'; text = $text }) } })
    $failure = Get-Failure { Invoke-AgencyTool 'ListChannels' $arguments }
    Assert ($script:Requests.Count -eq 1 -and $script:Delays.Count -eq 0) 'nonretryable tool error tried once'
    Assert ($failure.Contains($text)) 'nonretryable error preserved'
    Assert (($script:Events -join "`n").Contains('nonretryable tool error')) 'nonretryable failure visible'
}

$mixed = @{
    isError = $true
    structuredContent = @{ channels = @(@{ id = 'partial-do-not-return' }) }
    content = @(@{ type = 'image'; data = 'synthetic' }, @{ type = 'text' },
        @{ type = 'text'; text = $timeoutText })
}
Set-Scenario @(@{ result = $mixed; sse = $true }, $success)
$result = Invoke-AgencyTool 'ListChannels' $arguments
Assert ($script:Requests.Count -eq 2 -and $result.channels[0].id -eq 'fixture-channel') 'mixed SSE content retries without accepting partial data'

Set-Scenario @(
    @{ result = @{ isError = $true; structuredContent = @{ error = @{ message = $timeoutText } } } }
    @{ result = @{ content = @(@{ type = 'text'; text = '{"channels":[{"id":"text-success"}]}' }) } }
)
$result = Invoke-AgencyTool 'ListChannels' $arguments
Assert ($script:Requests.Count -eq 2 -and $result.channels[0].id -eq 'text-success') 'structured error and text success shapes'

Set-Scenario @(@{ result = @{ isError = $false; structuredContent = @{ message = $timeoutText } } })
$result = Invoke-AgencyTool 'ListChannels' $arguments
Assert ($script:Requests.Count -eq 1 -and $result.message -eq $timeoutText) 'successful data is never classified as an error'

Set-Scenario @(@{ result = @{ isError = $true; content = @(@{ type = 'image'; data = 'synthetic' }) } })
$null = Get-Failure { Invoke-AgencyTool 'ListChannels' $arguments }
Assert ($script:Requests.Count -eq 1 -and $script:Delays.Count -eq 0) 'unrecognized error shape is not retried'

Set-Scenario @(
    @{ exception = 'Synthetic connection reset' }
    @{ status = 503 }
    $timeoutStep
    @{ status = 429; headers = @{ 'Retry-After' = @('1') } }
    $timeoutStep
)
$failure = Get-Failure { Invoke-AgencyTool 'ListChannels' $arguments }
Assert ($script:Requests.Count -eq 5 -and ($script:Delays -join ',') -eq '2,4,8,1') 'transport, HTTP and tool failures share one budget'
Assert ($failure.Contains($timeoutText)) 'mixed exhaustion retains last tool error'

foreach ($status in @(400, 401, 403)) {
    Set-Scenario @(@{ status = $status })
    $failure = Get-Failure { Invoke-AgencyTool 'ListChannels' $arguments }
    Assert ($script:Requests.Count -eq 1 -and $script:Delays.Count -eq 0) 'HTTP permission/validation failure tried once'
    Assert ($failure.Contains("HTTP $status")) 'HTTP failure status retained'
}

Set-Scenario @(@{ result = $timeoutResult; headers = @{ 'Retry-After' = @('7') } }, $success)
$null = Invoke-AgencyTool 'ListChannels' $arguments
Assert (($script:Delays -join ',') -eq '7') 'explicit HTTP Retry-After honored for tool timeout'
Assert ((Get-McpRetryDelay 0 'not-a-date') -eq 2) 'invalid delay falls back to backoff'
Assert ((Get-McpRetryDelay 0 '-1') -eq 2) 'negative delay falls back to backoff'
$date = [DateTimeOffset]::UtcNow.AddSeconds(30).ToString('r')
$dateDelay = Get-McpRetryDelay 0 $date
Assert ($dateDelay -ge 28 -and $dateDelay -le 30) 'HTTP-date retry delay honored'

Set-Scenario @(@{ result = $timeoutResult; headers = @{ 'Retry-After' = @('121') } })
$failure = Get-Failure { Invoke-AgencyTool 'ListChannels' $arguments }
Assert ($script:Requests.Count -eq 1 -and $script:Delays.Count -eq 0) 'excessive server delay stops instead of retrying early'
Assert ($failure.Contains($timeoutText)) 'excessive delay preserves tool error'

foreach ($name in @('ListTeams', 'ListChannels', 'ListChannelMessages', 'ListChannelMessageReplies')) {
    Set-Scenario @($timeoutStep, @{ result = @{ structuredContent = @{ fixture = $true } } })
    $null = Invoke-AgencyTool $name @{}
    Assert ($script:Requests.Count -eq 2) 'all allowlisted reads can recover'
}
Set-Scenario @()
$null = Get-Failure { Invoke-AgencyTool 'SendMessage' @{} }
$null = Get-Failure { Invoke-McpRequest 'tools/call' @{ name = 'SendMessage'; arguments = @{} } }
Assert ($script:Requests.Count -eq 0 -and $script:Delays.Count -eq 0) 'write tools rejected before any network call'

Microsoft.PowerShell.Utility\Write-Host 'PowerShell MCP retry fixture tests passed.'
