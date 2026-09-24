#requires -Version 7.5
# Full entrypoint orchestration with synthetic read tools; never contacts Agency.
$ErrorActionPreference = 'Stop'
$skillRoot = Split-Path $PSScriptRoot -Parent
$exporter = Join-Path $skillRoot 'scripts\Export-TeamsChannel.ps1'
. $exporter -InputPath 'unused.json'

function Assert($Condition, [string]$Message) {
    if (-not $Condition) { throw "Assertion failed: $Message" }
}

$fixture = Join-Path ([IO.Path]::GetTempPath()) "teams-skill-fixture-$([guid]::NewGuid())"
$null = New-Item -ItemType Directory -Path $fixture
$script:Logs = [Collections.Generic.List[string]]::new()
$script:ProxyDirs = [Collections.Generic.List[string]]::new()
$script:Tools = [Collections.Generic.List[string]]::new()
$script:Mode = 'success'
$script:Body = 'SYNTHETIC_BODY_MUST_NOT_APPEAR_IN_PROGRESS_OR_SUMMARY'
$team = '11111111-2222-3333-4444-555555555555'
$url = "https://teams.microsoft.com/l/channel/19%3Afixture%40thread.skype/Ignore%24%28throw%20%27injection%27%29?groupId=$team&tenantId=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

function Start-AgencyProxy([string]$LogDir) {
    $script:ProxyDirs.Add($LogDir)
    Write-ExportProgress 'Fixture proxy connection ready.' -Phase 'connection'
}

function New-Post([string]$Id, [string]$Time) {
    return @{ id = $Id; createdDateTime = $Time; body = @{ contentType = 'text'; content = $script:Body } }
}

function Invoke-AgencyTool([string]$Name, [hashtable]$Arguments) {
    $script:Tools.Add($Name)
    Assert (Test-ReadOnlyAgencyTool $Name) 'no write tools'
    switch ($Name) {
        'ListTeams' { return @{ teams = @(@{ id = $team; displayName = 'Synthetic team' }) } }
        'ListChannels' {
            return @{ channels = @(@{ id = '19:fixture@thread.skype'; displayName = 'Synthetic channel' }) }
        }
        'ListChannelMessages' {
            Assert ($script:ExportResult.phase -eq 'message_download') 'phase visible before slow root request'
            if ($script:Mode -eq 'failure') { throw "Synthetic backend failure: $script:Body" }
            if (-not $Arguments.nextLink) {
                return @{ messages = @((New-Post 'old' '2026-08-01T00:00:00Z')); hasMoreResults = $true; nextLink = 'page2' }
            }
            $posts = if ($script:Mode -eq 'empty') { @() } else { @((New-Post 'selected' '2026-09-03T12:00:00Z')) }
            return @{ messages = @($posts); hasMoreResults = $false }
        }
        'ListChannelMessageReplies' {
            return @{ replies = @((New-Post 'late-reply' '2026-10-01T00:00:00Z')); hasMoreResults = $false }
        }
    }
    throw "Unexpected tool $Name"
}

function Set-Inputs([string]$Case) {
    $script:InputPath = Join-Path $fixture "$Case.input.json"
    $script:SummaryPath = Join-Path $fixture "$Case.result.json"
    $script:Inputs = @{
        ChannelUrl = $url; StartTime = '2026-09-01'; EndTime = '2026-09-07'
        OutputDir = Join-Path $fixture "$Case output"
    }
    [IO.File]::WriteAllText($script:InputPath, ($script:Inputs | ConvertTo-Json))
}

function Run-Case {
    $captured = @(Invoke-ExportMain 6>&1 3>&1)
    $script:Logs.Add($script:ExportLogPath)
    $code = @($captured | Where-Object { $_ -is [int] })
    Assert ($code.Count -eq 1) 'one entrypoint exit code'
    $script:Progress = ($captured | Where-Object { $_ -isnot [int] }) -join "`n"
    Assert (-not $script:Progress.Contains($script:Body)) 'visible progress excludes message bodies'
    if (Test-Path -LiteralPath $script:SummaryPath) {
        $raw = Get-Content -LiteralPath $script:SummaryPath -Raw
        Assert (-not $raw.Contains($script:Body)) 'metadata summary excludes message bodies'
        $script:Result = $raw | ConvertFrom-Json -AsHashtable -DateKind String
    }
    return $code[0]
}

try {
    $skill = Get-Content -LiteralPath (Join-Path $skillRoot 'SKILL.md') -Raw
    Assert ($skill -match '(?s)^---\r?\nname: teams-export\r?\ndescription: .+?\r?\n---') 'discoverable skill frontmatter'
    foreach ($path in @('scripts\Export-TeamsChannel.ps1', 'scripts\teams_export_markdown.py', 'tests\Test-TeamsExport.ps1', 'tests\Test-TeamsRetry.ps1')) {
        Assert (Test-Path -LiteralPath (Join-Path $skillRoot $path) -PathType Leaf) 'relocated skill reference exists'
    }
    Assert (-not $skill.Contains('.\teams_export\')) 'no obsolete standalone path in skill'

    Push-Location -LiteralPath $fixture
    try {
        Set-Inputs 'success'
        Assert ((Run-Case) -eq 0) 'JSON workflow succeeds outside repo cwd'
        Assert ($script:Result.status -eq 'complete' -and $script:Result.phase -eq 'complete') 'final complete status after cleanup'
        Assert ($script:Result.timeZone -eq [TimeZoneInfo]::Local.Id) 'omitted timezone defaults locally'
        Assert ($script:Result.counts.posts -eq 1 -and $script:Result.counts.replies -eq 1) 'metadata summary counts'
        Assert ($script:Result.outputPath -eq (Join-Path $script:Inputs.OutputDir 'Synthetic channel_2026-09-01_2026-09-06.md')) 'exact absolute output path'
        Assert (Test-Path -LiteralPath $script:Result.outputPath) 'combined output exists'
        Assert (Test-Path -LiteralPath $script:Result.manifestPath) 'manifest path returned'
        Assert ($script:Progress -match '\[\d{4}-\d{2}-\d{2}T.*\] \[INFO\]') 'timestamped visible progress'
        Assert ($script:Progress.Contains('Root page 1 scanned; roots scanned=1, selected/completed=0')) 'zero-match page reports progress'
        Assert ($script:Progress.IndexOf('Scanning root page 1') -lt $script:Progress.IndexOf('Root page 1 scanned')) 'request event precedes completion'
        Assert ($script:Progress.IndexOf('Root page 1 scanned') -lt $script:Progress.IndexOf('Selected thread 1')) 'selection occurs on later page'
        Assert ($script:Progress.Contains('Fetching reply page 1') -and $script:Progress.Contains('replies saved=1')) 'reply operation and counters visible'
        Assert ($script:Progress.IndexOf('Rendering one') -lt $script:Progress.IndexOf('Complete:')) 'rendering precedes completion'
        Assert ($script:Progress.IndexOf('Stopping the owned') -lt $script:Progress.IndexOf('Complete:')) 'cleanup precedes reported success'
        Assert ($script:Progress.Contains('Diagnostic log:')) 'live readable log path visible'
        $logged = Get-Content -LiteralPath $script:Result.diagnosticsPath -Raw
        Assert ($logged.Contains('Root page 1 scanned') -and -not $logged.Contains($script:Body)) 'progress is also logged without bodies'
        Assert ($script:Result.Keys.Count -eq 11) 'summary contains only defined metadata fields'

        $original = Get-Content -LiteralPath $script:SummaryPath -Raw
        $calls = $script:Tools.Count
        Assert ((Run-Case) -eq 1) 'existing summary is refused before any export'
        Assert ((Get-Content -LiteralPath $script:SummaryPath -Raw) -eq $original) 'existing complete summary untouched'
        Assert ($script:Tools.Count -eq $calls) 'summary collision makes no tool requests'

        Set-Inputs 'empty'
        $script:Inputs.TimeZone = 'UTC'
        [IO.File]::WriteAllText($script:InputPath, ($script:Inputs | ConvertTo-Json))
        $script:Mode = 'empty'
        Assert ((Run-Case) -eq 0) 'empty export workflow succeeds'
        Assert ($script:Result.timeZone -eq 'UTC' -and $script:Result.startTimeInclusive.StartsWith('2026-09-01T00:00:00')) 'JSON timezone override respected'
        Assert ($script:Result.counts.postPages -eq 2 -and $script:Result.counts.posts -eq 0) 'all zero-match pages scanned'
        Assert ($script:Progress.Contains('Scanning root page 2') -and $script:Progress.Contains('selected/completed=0')) 'progress continues without selected posts'

        Set-Inputs 'failure'
        $script:Mode = 'failure'
        Assert ((Run-Case) -eq 1) 'retrieval failure returns nonzero'
        Assert ($script:Result.status -eq 'incomplete' -and $script:Result.phase -eq 'message_download') 'failure metadata retains correct stage'
        Assert ($script:Progress.Contains('preserve partial artifacts')) 'failure provides actionable next step'
        Assert (-not (Test-Path -LiteralPath $script:Result.outputPath)) 'failure does not fabricate Markdown'
        $privateLog = Get-Content -LiteralPath $script:Result.diagnosticsPath -Raw
        Assert ($privateLog.Contains('Synthetic backend failure:')) 'full diagnostic retained locally'
        $manifest = Get-Content -LiteralPath $script:Result.manifestPath -Raw | ConvertFrom-Json -DateKind String
        Assert ($manifest.status -eq 'incomplete') 'manifest agrees with incomplete result'

        foreach ($kind in @('missing', 'unknown', 'nonstring', 'relative', 'injection')) {
            Set-Inputs $kind
            switch ($kind) {
                'missing' { $script:Inputs.Remove('StartTime') }
                'unknown' { $script:Inputs.Command = 'throw "must not run"' }
                'nonstring' { $script:Inputs.StartTime = 20260901 }
                'relative' { $script:Inputs.OutputDir = '.\relative' }
                'injection' { $script:Inputs.StartTime = '$(throw "must not run")' }
            }
            [IO.File]::WriteAllText($script:InputPath, ($script:Inputs | ConvertTo-Json))
            $calls = $script:Tools.Count
            Assert ((Run-Case) -eq 1) 'invalid data rejected'
            Assert ($script:Result.status -eq 'failed' -and $script:Result.phase -eq 'input') 'invalid data failure is machine readable'
            Assert ($script:Tools.Count -eq $calls) 'invalid input never contacts Teams'
        }

        Set-Inputs 'native-input'
        $script:Inputs.Remove('StartTime')
        [IO.File]::WriteAllText($script:InputPath, ($script:Inputs | ConvertTo-Json))
        $pwsh = (Get-Process -Id $PID).Path
        $nativeOutput = & $pwsh -NoProfile -File $exporter -InputPath $script:InputPath -SummaryPath $script:SummaryPath 2>&1
        Assert ($LASTEXITCODE -eq 1) 'real CLI InputPath parameter set fails safely outside repo cwd'
        $nativeResult = Get-Content -LiteralPath $script:SummaryPath -Raw | ConvertFrom-Json -DateKind String
        $script:Logs.Add($nativeResult.diagnosticsPath)
        Assert ($nativeResult.status -eq 'failed' -and $nativeResult.phase -eq 'input') 'real CLI produces failure metadata'
        Assert (($nativeOutput -join "`n").Contains('Check the Teams channel URL')) 'real CLI keeps actionable progress visible'
    } finally {
        Pop-Location
    }
    Write-Host 'PowerShell skill entrypoint and progress fixture tests passed.'
} finally {
    foreach ($path in $script:Logs) {
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path }
    }
    foreach ($path in $script:ProxyDirs) {
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path }
    }
    Get-ChildItem -LiteralPath $fixture -File -Recurse | ForEach-Object { Remove-Item -LiteralPath $_.FullName }
    Get-ChildItem -LiteralPath $fixture -Directory -Recurse |
        Sort-Object { $_.FullName.Length } -Descending | ForEach-Object { Remove-Item -LiteralPath $_.FullName }
    Remove-Item -LiteralPath $fixture
}
