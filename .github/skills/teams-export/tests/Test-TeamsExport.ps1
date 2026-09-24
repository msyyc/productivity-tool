#requires -Version 7.5
# Offline fixture tests; never starts Agency or reads Microsoft 365 data.
$ErrorActionPreference = 'Stop'
$scripts = Join-Path (Split-Path $PSScriptRoot -Parent) 'scripts'
. (Join-Path $scripts 'Export-TeamsChannel.ps1') `
    -TeamsChannelId '19:fixture@thread.skype' -StartTime '2026-09-01' -EndTime '2026-09-24'

function Assert($Condition, [string]$Message) {
    if (-not $Condition) { throw "Assertion failed: $Message" }
}
function Assert-Throws([scriptblock]$Action, [string]$Message) {
    $threw = $false
    try { & $Action } catch { $threw = $true }
    Assert $threw $Message
}
function New-Message([string]$Id, [string]$Created, [string]$Content = '<p>Message</p>') {
    return @{
        id = $Id; createdDateTime = $Created; lastModifiedDateTime = $Created
        from = @{ displayName = 'Fixture Author'; id = 'fixture-author' }
        body = @{ contentType = 'Html'; content = $Content }
    }
}

Assert ($TimeZone -eq [TimeZoneInfo]::Local.Id) 'machine-local default timezone'
$teamGuid = '11111111-2222-3333-4444-555555555555'
$tenantGuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
$url = "https://teams.microsoft.com/l/channel/19%3Afixture%40thread.skype/Fixture%20Channel?groupId=$teamGuid&tenantId=$tenantGuid"
$parsed = Convert-TeamsChannelUrl $url
Assert ($parsed.channelId -eq '19:fixture@thread.skype') 'decoded channel ID'
Assert ($parsed.teamId -eq $teamGuid -and $parsed.tenantId -eq $tenantGuid) 'URL team and tenant IDs'
Assert ($parsed.displayName -eq 'Fixture Channel') 'decoded channel display name'
Assert ((Convert-TeamsChannelUrl "[Fixture Channel]($url)").channelId -eq $parsed.channelId) 'Markdown wrapper'
Assert ((Convert-TeamsChannelUrl ($url.Replace('teams.microsoft.com', 'teams.cloud.microsoft'))).teamId -eq $teamGuid) 'cloud host'
Assert ((Convert-TeamsChannelUrl ($url.Replace('thread.skype', 'thread.tacv2'))).channelId -eq '19:fixture@thread.tacv2') 'modern channel ID'
Assert ((Convert-TeamsChannelUrl ($url.Replace('Fixture%20Channel', '%E6%B5%8B%E8%AF%95'))).displayName.Length -eq 2) 'UTF8 name'
Assert ((Convert-TeamsChannelUrl ($url.Replace('Fixture%20Channel?', 'Fixture%20Channel/?'))).teamId -eq $teamGuid) 'trailing slash'
Assert ((Convert-TeamsChannelUrl ($url + '&context=%7B%22channel%22%3Atrue%7D')).teamId -eq $teamGuid) 'extra Teams context'
foreach ($invalid in @(
    $url.Replace('https:', 'http:'),
    $url.Replace('teams.microsoft.com', 'teams.microsoft.com.evil.example'),
    $url.Replace('teams.microsoft.com', 'user@teams.microsoft.com'),
    $url.Replace('teams.microsoft.com', 'teams.microsoft.com:1234'),
    $url.Replace('/l/channel/', '/l/message/'),
    $url.Replace('/l/channel/', '/x/../l/channel/'),
    $url.Replace('19%3Afixture', 'fixture'),
    $url.Replace('thread.skype', 'example.com'),
    $url.Replace('Fixture%20Channel', ''),
    $url.Replace('Fixture%20Channel', '%20'),
    $url.Replace('Fixture%20Channel', '..'),
    $url.Replace('Fixture%20Channel', '%GG'),
    $url.Replace('Fixture%20Channel', '%C3%28'),
    $url.Replace('Fixture%20Channel', '%0A'),
    $url.Replace('Fixture%20Channel', 'Fixture Channel'),
    $url.Replace("&tenantId=$tenantGuid", ''),
    $url.Replace("groupId=$teamGuid", 'groupId='),
    $url.Replace($teamGuid, 'not-a-guid'),
    $url.Replace($tenantGuid, '00000000-0000-0000-0000-000000000000'),
    "$url&groupId=$teamGuid",
    "$url&%67roupId=$teamGuid",
    "$url&bad",
    "$url#fragment",
    "[Fixture]($url",
    "$url&unknown=%FF"
)) {
    Assert-Throws { Convert-TeamsChannelUrl $invalid } "reject invalid URL $invalid"
}
Assert ((Get-ExportStem 'API Spec Review' '2026-09-01' '2026-09-23') -eq 'API Spec Review_2026-09-01_2026-09-23') 'exact human-readable filename stem'
Assert ((Get-ExportStem 'A:B/C\D*E?F"G<H>I|J. ' '2026-09-01' '2026-09-23') -eq 'A_B_C_D_E_F_G_H_I_J_2026-09-01_2026-09-23') 'Windows filename sanitization'
$localStart = Convert-ExportTime '2026-09-01' ([TimeZoneInfo]::Local)
Assert ($localStart.Offset -eq [TimeZoneInfo]::Local.GetUtcOffset([datetime]::new(2026, 9, 1))) 'default zone date interpretation'
$zone = [TimeZoneInfo]::FindSystemTimeZoneById('China Standard Time')
$start = Convert-ExportTime '2026-09-01' $zone
$end = Convert-ExportTime '2026-09-24' $zone
Assert ($start.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') -eq '2026-08-31T16:00:00Z') 'date timezone conversion'
Assert ((Convert-ExportTime '2026-09-01T00:00:00Z' $zone).Offset -eq [TimeSpan]::Zero) 'explicit offset'
Assert-Throws { Convert-ExportTime '09/01/2026' $zone } 'reject locale-dependent dates'
Assert-Throws { Convert-ExportTime '2026-11-01T01:30:00' ([TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time')) } 'ambiguous DST'
Assert-Throws { Convert-ExportTime '2026-03-08T02:30:00' ([TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time')) } 'invalid DST'
Assert ((Convert-ExportTime '2026-11-01T01:30:00-04:00' ([TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time'))).Offset.TotalHours -eq -4) 'explicit offset resolves DST ambiguity'
Assert-Throws { Get-NextPage @{ hasMoreResults = $true } } 'missing pagination link'
Assert-Throws { Get-NextPage @{} } 'unknown completeness'
Assert-Throws { Get-NextPage @{ hasMoreResults = $false; nextLink = 'unexpected' } } 'contradictory pagination'
Assert-Throws { Get-PageItems @{} 'messages' } 'missing message array'

$script:Calls = [Collections.Generic.List[string]]::new()
$root1 = New-Message '100' '2026-08-31T16:00:00Z' '<p>Hello <at id="0">Colleague</at>. <a href="https://example.com/a">Link</a></p>'
$root2 = New-Message '200' '2026-09-02T01:00:00Z' '<p>Second post</p>'
$old = New-Message 'old' '2026-08-01T00:00:00Z'
$old.lastModifiedDateTime = '2026-09-22T00:00:00Z'
$excluded = New-Message 'end' '2026-09-23T16:00:00Z'
$script:Pages = @{
    roots1 = @{ messages = @($old, $root2); hasMoreResults = $true; nextLink = 'roots2' }
    roots2 = @{ messages = @($root2, $excluded, $root1); hasMoreResults = $false }
    reply100 = @{
        replies = @((New-Message 'r2' '2026-10-01T00:00:00Z' '<p>Reply after end</p>'))
        parentMessageId = '100'; hasMoreResults = $true; nextLink = 'reply100page2'
    }
    reply100page2 = @{
        replies = @((New-Message 'r1' '2026-09-02T00:00:00Z'), (New-Message 'r2' '2026-10-01T00:00:00Z' '<p>Reply after end</p>'))
        hasMoreResults = $false; parentMessageId = '100'
    }
    reply200 = @{ replies = @(); hasMoreResults = $false; parentMessageId = '200' }
    replyend = @{ replies = @(); hasMoreResults = $false; parentMessageId = 'end' }
}
function Invoke-AgencyTool([string]$Name, [hashtable]$Arguments) {
    $script:Calls.Add($Name)
    if ($Name -eq 'ListTeams') {
        return @{ teams = @(@{ id = $teamGuid; displayName = 'Fixture Team'; tenantId = $tenantGuid }) }
    }
    if ($Name -eq 'ListChannels') {
        Assert ($Arguments.teamId -eq $teamGuid) 'resolved team ID passed to ListChannels'
        return @{ channels = @(@{
            id = '19:fixture@thread.skype'; displayName = 'Fixture Channel'
            webUrl = 'https://teams.microsoft.com/fixture'; tenantId = $tenantGuid
        }) }
    }
    if ($Name -eq 'ListChannelMessages') {
        $key = if ($Arguments.nextLink) { $Arguments.nextLink } else { 'roots1' }
    } elseif ($Name -eq 'ListChannelMessageReplies') {
        $key = if ($Arguments.nextLink) { $Arguments.nextLink } else { "reply$($Arguments.messageId)" }
    } else { throw "Unexpected tool $Name" }
    if (-not $script:Pages.ContainsKey($key)) { throw "Unexpected page $key" }
    return $script:Pages[$key]
}

$script:TestLogs = [Collections.Generic.List[string]]::new()
$fixtureDir = Join-Path ([IO.Path]::GetTempPath()) "teams-export-fixture-$([guid]::NewGuid())"
$dataDir = Join-Path $fixtureDir 'Fixture Channel_2026-09-01_2026-09-23.data'
$null = New-Item -ItemType Directory -Path (Join-Path $dataDir 'threads') -Force
try {
    $accessible = Resolve-ExportChannel $parsed.channelId $parsed.teamId
    Assert ($accessible.channel.displayName -eq 'Fixture Channel') 'actual accessible metadata'
    Assert-Throws { Resolve-ExportChannel $parsed.channelId '99999999-2222-3333-4444-555555555555' } 'inaccessible team'
    Assert-Throws { Resolve-ExportChannel '19:missing@thread.skype' $teamGuid } 'inaccessible channel'
    Assert ((Resolve-ExportChannel $parsed.channelId '').team.id -eq $teamGuid) 'explicit channel without team resolves'
    $resolved = @{ team = @{ id = 'fixture-team' }; channel = @{ id = '19:fixture@thread.skype' } }
    $manifest = @{
        status = 'in_progress'; teamId = 'fixture-team'; channelId = $resolved.channel.id
        channelName = 'Fixture Channel'; timeZone = $zone.Id
        firstCoveredDate = '2026-09-01'; lastCoveredDate = '2026-09-23'
        startTimeInclusive = $start.ToUniversalTime().ToString('o')
        endTimeExclusive = $end.ToUniversalTime().ToString('o')
        markdownFile = 'Fixture Channel_2026-09-01_2026-09-23.md'
        counts = @{ postsScanned = 0; posts = 0; replies = 0; postPages = 0; replyPages = 0 }
    }
    $manifestPath = Join-Path $dataDir 'manifest.json'
    Save-SelectedThreads $resolved $start $end $zone (Join-Path $dataDir 'threads') $manifest $manifestPath
    Assert ($manifest.counts.postsScanned -eq 4) 'deduplicate channel pages'
    Assert ($manifest.counts.posts -eq 2) 'start inclusive, end exclusive, no early cutoff'
    Assert ($manifest.counts.replies -eq 2) 'reply pagination and deduplication'
    Assert ($manifest.counts.postPages -eq 2 -and $manifest.counts.replyPages -eq 3) 'all pages consumed'
    & python (Join-Path $scripts 'teams_export_markdown.py') --export-dir $dataDir
    Assert ($LASTEXITCODE -eq 0) 'renderer success'
    $markdown = Get-Content -LiteralPath (Join-Path $fixtureDir $manifest.markdownFile) -Raw
    Assert ($markdown.Contains('Reply after end')) 'include out-of-window replies'
    Assert ($markdown.Contains('@Colleague')) 'preserve mentions'
    Assert ($markdown.Contains('[Link](https://example.com/a)')) 'preserve links'
    Assert ($markdown.IndexOf('`r1`') -lt $markdown.IndexOf('`r2`')) 'replies chronological'
    Assert ($markdown.IndexOf('`100`') -lt $markdown.IndexOf('`200`')) 'roots chronological across dates'
    Assert ($markdown.Contains('Second post')) 'second date in combined file'
    Assert (@(Get-ChildItem -LiteralPath $fixtureDir -Filter '*.md').Count -eq 1) 'exactly one combined file'
    $stats = @{ replyPages = 0 }
    $script:Pages.reply200 = @{ replies = @(); hasMoreResults = $true; nextLink = 'reply200' }
    Assert-Throws { Get-ThreadReplies 'fixture-team' $resolved.channel.id '200' $stats } 'pagination loop detection'
    $script:Pages.reply200 = @{ replies = @(); hasMoreResults = $false; parentMessageId = 'wrong' }
    Assert-Throws { Get-ThreadReplies 'fixture-team' $resolved.channel.id '200' $stats } 'wrong parent rejection'

    $script:Pages.reply200 = @{ replies = @(); hasMoreResults = $false; parentMessageId = '200' }
    function Start-AgencyProxy([string]$LogDir) {
        $script:TestLogs.Add($LogDir)
        $script:ProxyProcess = [pscustomobject]@{ HasExited = $false; KillCalls = 0; WaitCalls = 0 }
        $script:ProxyProcess | Add-Member ScriptMethod Kill {
            param($EntireTree)
            Assert $EntireTree 'stop owned child process tree'
            $this.KillCalls++
            $this.HasExited = $true
        }
        $script:ProxyProcess | Add-Member ScriptMethod WaitForExit { $this.WaitCalls++ }
    }
    $OutputDir = Join-Path $fixtureDir 'complete-run'
    $TimeZone = 'China Standard Time'
    $ChannelUrl = $url.Replace('Fixture%20Channel', 'Outdated%20URL%20Name')
    Invoke-ChannelExport
    Assert ($script:ProxyProcess.KillCalls -eq 1 -and $script:ProxyProcess.WaitCalls -eq 1) 'owned process stopped on success'
    $completedPath = @(Get-ChildItem -LiteralPath $OutputDir -Filter 'manifest.json' -Recurse -File)[0].FullName
    $completed = Get-Content -LiteralPath $completedPath -Raw | ConvertFrom-Json -DateKind String
    Assert ($completed.status -eq 'complete' -and $completed.files.Count -eq 1) 'complete manifest'
    Assert ($completed.channelName -eq 'Fixture Channel' -and $completed.requestedChannelUrl.displayName -eq 'Outdated URL Name') 'actual metadata wins over URL label'
    Assert ($completed.requestedChannelUrl.tenantId -eq $tenantGuid -and $completed.team.tenantId -eq $tenantGuid) 'tenant metadata retained'
    Assert ($completed.timeZone -eq 'China Standard Time') 'explicit timezone retained'
    Assert ($completed.counts.posts -eq 2 -and $completed.counts.replies -eq 2) 'complete manifest counts'
    Assert (Test-Path -LiteralPath (Join-Path $OutputDir 'Fixture Channel_2026-09-01_2026-09-23.md')) 'exact output filename at OutputDir root'
    Assert ((Split-Path (Split-Path $completedPath) -Leaf) -eq 'Fixture Channel_2026-09-01_2026-09-23.data') 'filename-scoped sidecars'
    $originalManifest = Get-Content -LiteralPath $completedPath -Raw
    Assert-Throws { Invoke-ChannelExport } 'existing export refused'
    Assert ((Get-Content -LiteralPath $completedPath -Raw) -eq $originalManifest) 'existing export untouched'

    $OutputDir = Join-Path $fixtureDir 'markdown-collision'
    $null = New-Item -ItemType Directory -Path $OutputDir
    $collision = Join-Path $OutputDir 'Fixture Channel_2026-09-01_2026-09-23.md'
    [IO.File]::WriteAllText($collision, 'existing file')
    Assert-Throws { Invoke-ChannelExport } 'existing Markdown alone refused'
    Assert ((Get-Content -LiteralPath $collision -Raw) -eq 'existing file') 'existing Markdown untouched'
    Assert (@(Get-ChildItem -LiteralPath $OutputDir).Count -eq 1) 'collision does not create sidecars'

    $OutputDir = Join-Path $fixtureDir 'wrong-tenant'
    $ChannelUrl = $url.Replace($tenantGuid, 'bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee')
    Assert-Throws { Invoke-ChannelExport } 'tenant mismatch rejected'
    Assert (-not (Test-Path -LiteralPath $OutputDir)) 'tenant mismatch creates no export'

    Remove-Variable ChannelUrl
    $TeamId = $teamGuid
    $OutputDir = Join-Path $fixtureDir 'local-zone'
    $TimeZone = [TimeZoneInfo]::Local.Id
    Invoke-ChannelExport
    $localManifestPath = @(Get-ChildItem -LiteralPath $OutputDir -Filter 'manifest.json' -Recurse -File)[0].FullName
    $localManifest = Get-Content -LiteralPath $localManifestPath -Raw | ConvertFrom-Json -DateKind String
    Assert ($localManifest.timeZone -eq [TimeZoneInfo]::Local.Id) 'local timezone exported'
    Assert ($localManifest.startTimeInclusive -eq $localStart.ToUniversalTime().ToString('o')) 'machine-local start persisted'
    Assert ($null -eq $localManifest.requestedChannelUrl) 'explicit channel/team mode'

    $OutputDir = Join-Path $fixtureDir 'utc-override'
    $TimeZone = 'UTC'
    Invoke-ChannelExport
    $utcPath = @(Get-ChildItem -LiteralPath $OutputDir -Filter 'manifest.json' -Recurse -File)[0].FullName
    $utc = Get-Content -LiteralPath $utcPath -Raw | ConvertFrom-Json -DateKind String
    Assert ($utc.timeZone -eq 'UTC' -and $utc.startTimeInclusive.StartsWith('2026-09-01T00:00:00')) 'UTC override changes absolute boundary'
    Assert ($utc.counts.posts -eq 2 -and $utc.counts.replies -eq 0) 'UTC override changes selected roots'
    $utcMarkdown = Get-Content -LiteralPath (Join-Path $OutputDir $utc.markdownFile) -Raw
    Assert ($utcMarkdown.Contains('`end`') -and -not $utcMarkdown.Contains('`100`')) 'override selection differs from China timezone'

    $OutputDir = Join-Path $fixtureDir 'absolute-times'
    $TimeZone = 'China Standard Time'
    $StartTime = '2026-08-31T16:00:00Z'
    $EndTime = '2026-09-23T04:00:00Z'
    Invoke-ChannelExport
    Assert (Test-Path -LiteralPath (Join-Path $OutputDir 'Fixture Channel_2026-09-01_2026-09-23.md')) 'absolute bounds and partial final date filename'
    $StartTime = '2026-09-01'
    $EndTime = '2026-09-24'

    $OutputDir = Join-Path $fixtureDir 'empty-run'
    $script:Pages.roots1 = @{ messages = @(); hasMoreResults = $false }
    Invoke-ChannelExport
    $emptyPath = @(Get-ChildItem -LiteralPath $OutputDir -Filter 'manifest.json' -Recurse -File)[0].FullName
    $empty = Get-Content -LiteralPath $emptyPath -Raw | ConvertFrom-Json -DateKind String
    Assert ($empty.status -eq 'complete' -and $empty.counts.posts -eq 0 -and $empty.files.Count -eq 1) 'empty export complete with one file'
    Assert (@(Get-ChildItem -LiteralPath $OutputDir -Filter '*.md').Count -eq 1) 'empty export writes one Markdown'

    Push-Location -LiteralPath $fixtureDir
    try {
        $OutputDir = '.\relative-output'
        Invoke-ChannelExport
        Assert (Test-Path -LiteralPath (Join-Path $fixtureDir 'relative-output\Fixture Channel_2026-09-01_2026-09-23.md')) 'OutputDir follows PowerShell working location'
    } finally {
        Pop-Location
    }

    $OutputDir = Join-Path $fixtureDir 'failed-run'
    $script:Pages.roots1 = @{ hasMoreResults = $false }
    Assert-Throws { Invoke-ChannelExport } 'retrieval failure propagates'
    $failedPath = @(Get-ChildItem -LiteralPath $OutputDir -Filter 'manifest.json' -Recurse -File)[0].FullName
    $failed = Get-Content -LiteralPath $failedPath -Raw | ConvertFrom-Json -DateKind String
    Assert ($failed.status -eq 'incomplete' -and $failed.errors.Count -eq 1) 'incomplete manifest with error'
    Assert ($script:ProxyProcess.KillCalls -eq 1 -and $script:ProxyProcess.WaitCalls -eq 1) 'owned process stopped on failure'
    Assert (@(Get-ChildItem -LiteralPath $OutputDir -Filter '*.md').Count -eq 0) 'retrieval failure does not write Markdown'
    $pwsh = (Get-Process -Id $PID).Path
    $failureSummary = Join-Path $fixtureDir 'invalid-input.result.json'
    $failureOutput = & $pwsh -NoProfile -File (Join-Path $scripts 'Export-TeamsChannel.ps1') `
        -ChannelUrl 'https://invalid.example/' -StartTime '2026-09-01' -EndTime '2026-09-24' `
        -SummaryPath $failureSummary 2>&1
    Assert ($LASTEXITCODE -ne 0) 'entrypoint invalid input returns nonzero'
    $failedInput = Get-Content -LiteralPath $failureSummary -Raw | ConvertFrom-Json -DateKind String
    Assert ($failedInput.status -eq 'failed' -and $failedInput.phase -eq 'input') 'entrypoint failed input summary'
    $inputLog = Get-Content -LiteralPath $failedInput.diagnosticsPath -Raw
    Remove-Item -LiteralPath $failedInput.diagnosticsPath
    Assert (($failureOutput -join "`n").Contains('Check the Teams channel URL')) 'entrypoint visible actionable diagnostic'
    Assert ($inputLog.Contains('Use an HTTPS Teams channel URL')) 'entrypoint original details preserved in local log'
    Write-Host 'PowerShell export fixture tests passed.'
} finally {
    # Remove individually resolved fixture files and then empty directories.
    Get-ChildItem -LiteralPath $fixtureDir -File -Recurse | ForEach-Object { Remove-Item -LiteralPath $_.FullName }
    Get-ChildItem -LiteralPath $fixtureDir -Directory -Recurse |
        Sort-Object { $_.FullName.Length } -Descending | ForEach-Object { Remove-Item -LiteralPath $_.FullName }
    Remove-Item -LiteralPath $fixtureDir
    foreach ($log in $script:TestLogs) {
        if (Test-Path -LiteralPath $log) { Remove-Item -LiteralPath $log }
    }
}
