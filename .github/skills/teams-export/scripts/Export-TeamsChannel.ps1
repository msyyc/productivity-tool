#requires -Version 7.5
<#
.SYNOPSIS
Exports channel posts created in [StartTime, EndTime), with all available replies.
.DESCRIPTION
Requires Agency, PowerShell 7.5+, and Python 3.10+. Uses direct Teams MCP calls,
not an AI agent. Date-only and offset-free timestamps use TimeZone (the machine
local zone by default). Explicit ISO 8601 offsets identify absolute instants.
One combined Markdown file is written directly in OutputDir, with a matching
.data directory containing the manifest and raw threads.

All channel post pages are scanned: activity ordering makes creation-date
early termination unsafe. Linked files, edit history and deleted bodies are
not recovered. Existing export artifacts are never overwritten.
.EXAMPLE
.\Export-TeamsChannel.ps1 -TeamsChannelId '19:example@thread.skype' `
    -StartTime '2026-09-01' -EndTime '2026-09-24' `
    -TimeZone 'China Standard Time'
#>
[CmdletBinding(DefaultParameterSetName = 'Url')]
param(
    [Parameter(Mandatory, ParameterSetName = 'Url')]
    [ValidateNotNullOrEmpty()][string]$ChannelUrl,
    [Parameter(Mandatory, ParameterSetName = 'Id')]
    [ValidateNotNullOrEmpty()][string]$TeamsChannelId,
    [Parameter(Mandatory, ParameterSetName = 'Url')]
    [Parameter(Mandatory, ParameterSetName = 'Id')]
    [ValidateNotNullOrEmpty()][string]$StartTime,
    [Parameter(Mandatory, ParameterSetName = 'Url')]
    [Parameter(Mandatory, ParameterSetName = 'Id')]
    [ValidateNotNullOrEmpty()][string]$EndTime,
    [Parameter(Mandatory, ParameterSetName = 'Input')]
    [ValidateNotNullOrEmpty()][string]$InputPath,
    [Parameter(ParameterSetName = 'Id')][string]$TeamId,
    [Parameter(ParameterSetName = 'Url')][Parameter(ParameterSetName = 'Id')]
    [string]$OutputDir = '.\teams-export',
    [Parameter(ParameterSetName = 'Url')][Parameter(ParameterSetName = 'Id')]
    [string]$TimeZone = [TimeZoneInfo]::Local.Id,
    [string]$SummaryPath
)

$ErrorActionPreference = 'Stop'
$script:ExportLogPath = $null
$script:SummaryOwned = $false
$script:ExportResult = $null

function Write-ExportProgress([string]$Message, [string]$Level = 'INFO', [string]$Phase) {
    if ($Phase -and $script:ExportResult) { $script:ExportResult.phase = $Phase }
    $line = "[$([DateTimeOffset]::Now.ToString('yyyy-MM-ddTHH:mm:sszzz'))] [$Level] $Message"
    if ($script:ExportLogPath) {
        [IO.File]::AppendAllText($script:ExportLogPath, "$line`n", [Text.UTF8Encoding]::new($false))
    }
    if ($Level -eq 'WARN') { Write-Warning $line } else { Write-Host $line }
    if ($script:SummaryOwned -and $script:ExportResult) {
        Write-ExportJson $script:SummaryFile $script:ExportResult
    }
}

function Read-ExportInput([string]$Path) {
    $values = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json -AsHashtable -DateKind String
    if ($values -isnot [Collections.IDictionary]) { throw 'InputPath must contain a JSON object.' }
    foreach ($key in $values.Keys) {
        if ($key -notin @('ChannelUrl', 'StartTime', 'EndTime', 'OutputDir', 'TimeZone') -or
            $values[$key] -isnot [string] -or [string]::IsNullOrWhiteSpace($values[$key])) {
            throw "Unsupported or invalid input field '$key'; only nonempty string export inputs are allowed."
        }
    }
    foreach ($key in @('ChannelUrl', 'StartTime', 'EndTime', 'OutputDir')) {
        if (-not $values.Contains($key)) { throw "Missing required input field '$key'." }
    }
    if (-not [IO.Path]::IsPathFullyQualified($values.OutputDir)) {
        throw 'InputPath OutputDir must be an absolute filesystem path.'
    }
    return $values
}

function Convert-UrlComponent([string]$Value) {
    if ($Value -match '%(?![0-9A-Fa-f]{2})') { throw 'Malformed percent encoding in channel URL.' }
    $decoded = [regex]::Replace($Value, '(?:%[0-9A-Fa-f]{2})+', {
        param($match)
        $bytes = [byte[]]@([regex]::Matches($match.Value, '%([0-9A-Fa-f]{2})') |
            ForEach-Object { [Convert]::ToByte($_.Groups[1].Value, 16) })
        [Text.UTF8Encoding]::new($false, $true).GetString($bytes)
    })
    if ($decoded -match '[\p{Cc}\p{Cf}]') { throw 'Control characters are not allowed in channel URLs.' }
    return $decoded
}

function Assert-ChannelId([string]$Value) {
    if ($Value -cnotmatch '^19:[A-Za-z0-9._~+/=-]+@(?:thread\.(?:skype|tacv2)|unq\.gbl\.spaces)$') {
        throw "Invalid Teams channel ID '$Value'."
    }
}

function Assert-TeamsGuid([string]$Value, [string]$Name) {
    if ($Value -notmatch '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' -or
        [guid]$Value -eq [guid]::Empty) {
        throw "Invalid or missing $Name; expected a nonzero GUID."
    }
}

function Convert-TeamsChannelUrl([string]$Value) {
    $url = $Value.Trim()
    if ($url.StartsWith('[')) {
        if ($url -notmatch '^\[[^\r\n]*\]\((https://[^\s]+)\)$') {
            throw 'Malformed Markdown channel link; use [channel name](https://...).'
        }
        $url = $Matches[1]
    }
    # Match the original path, not a URI-normalized path that could hide traversal.
    if ($url -notmatch '^https://(?:teams\.microsoft\.com|teams\.cloud\.microsoft)(?::443)?/l/channel/([^/?#\s]+)/([^/?#\s]+)/?\?([^#\s]+)$') {
        throw 'Use an HTTPS Teams channel URL with /l/channel/<id>/<name>?groupId=...&tenantId=... on teams.microsoft.com or teams.cloud.microsoft.'
    }
    $channel = Convert-UrlComponent $Matches[1]
    $name = Convert-UrlComponent $Matches[2]
    $query = $Matches[3]
    Assert-ChannelId $channel
    if ([string]::IsNullOrWhiteSpace($name) -or $name -in @('.', '..')) {
        throw 'Channel display name must not be empty or a dot path segment.'
    }
    $values = @{}
    foreach ($part in ($query -split '&')) {
        $pair = $part -split '=', 2
        if ($pair.Count -ne 2 -or -not $pair[0]) { throw 'Malformed channel URL query parameter.' }
        $key = Convert-UrlComponent ($pair[0].Replace('+', ' '))
        $value = Convert-UrlComponent ($pair[1].Replace('+', ' '))
        if (-not $key -or $values.ContainsKey($key)) { throw "Duplicate or empty channel URL query key '$key'." }
        $values[$key] = $value
    }
    Assert-TeamsGuid $values.groupId 'groupId'
    Assert-TeamsGuid $values.tenantId 'tenantId'
    return @{
        channelId = $channel; teamId = $values.groupId; tenantId = $values.tenantId
        displayName = $name; url = $url
    }
}

function Get-ExportStem([string]$Name, [string]$FirstDay, [string]$LastDay) {
    $safe = ($Name -replace '[<>:"/\\|?*\x00-\x1F\x7F]', '_').TrimEnd(' ', '.')
    if ([string]::IsNullOrWhiteSpace($safe)) { $safe = 'channel' }
    if ($safe.Length -gt 120) {
        $safe = $safe.Substring(0, 120).TrimEnd(' ', '.')
        if ([char]::IsHighSurrogate($safe[$safe.Length - 1])) { $safe = $safe.Substring(0, $safe.Length - 1) }
    }
    return "${safe}_${FirstDay}_${LastDay}"
}

function Convert-ExportTime([string]$Value, [TimeZoneInfo]$Zone) {
    if ($Value -notmatch '^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,7})?)?(?:Z|[+-]\d{2}:\d{2})?)?$') {
        throw "Invalid date '$Value'. Use YYYY-MM-DD or an ISO 8601 timestamp."
    }
    if ($Value -match '(Z|[+-]\d{2}:\d{2})$') {
        return [DateTimeOffset]::Parse($Value, [Globalization.CultureInfo]::InvariantCulture)
    }
    $local = [DateTime]::SpecifyKind(
        [DateTime]::Parse($Value, [Globalization.CultureInfo]::InvariantCulture),
        [DateTimeKind]::Unspecified)
    if ($Zone.IsInvalidTime($local) -or $Zone.IsAmbiguousTime($local)) {
        throw "Time '$Value' is ambiguous or invalid in '$($Zone.Id)'; supply an explicit offset."
    }
    return [DateTimeOffset]::new($local, $Zone.GetUtcOffset($local))
}

function Write-ExportJson([string]$Path, $Value) {
    $temporary = "$Path.tmp"
    [IO.File]::WriteAllText($temporary, ($Value | ConvertTo-Json -Depth 100),
        [Text.UTF8Encoding]::new($false))
    [IO.File]::Move($temporary, $Path, $true)
}

function Get-PageItems($Page, [string]$Property) {
    if (-not $Page.Contains($Property) -or $null -eq $Page[$Property]) {
        throw "Agency returned no '$Property' collection."
    }
    if ($Page[$Property] -isnot [System.Collections.IList]) {
        throw "Agency '$Property' is not an array."
    }
    return ,@($Page[$Property])
}

function Get-NextPage($Page) {
    if (-not $Page.Contains('hasMoreResults') -or $Page.hasMoreResults -isnot [bool]) {
        throw 'Agency did not provide an explicit hasMoreResults boolean; completeness is unknown.'
    }
    if ($Page.hasMoreResults) {
        if (-not $Page.nextLink) { throw 'Agency reported more results without a nextLink.' }
        return [string]$Page.nextLink
    }
    if ($Page.nextLink) { throw 'Agency returned contradictory pagination metadata.' }
    return $null
}

function Test-ReadOnlyAgencyTool([string]$Name) {
    return $Name -in @('ListTeams', 'ListChannels', 'ListChannelMessages', 'ListChannelMessageReplies')
}

function Test-AgencyTimeout($Result) {
    if ($Result.isError -isnot [bool] -or -not $Result.isError) { return $false }
    $messages = @(
        foreach ($block in $Result.content) {
            if ($block.type -eq 'text' -and $block.text -is [string]) { $block.text }
        }
        if ($Result.structuredContent.error -is [string]) {
            $Result.structuredContent.error
        } else {
            $Result.structuredContent.error.message
            $Result.structuredContent.error.code
        }
    ) -join "`n"
    if ($messages -match '\b(authentication|authorization|unauthorized|unauthenticated|forbidden|access\s*denied|permissions?|invalid\s+(input|argument|parameter)|BadRequest|InvalidArgument|InvalidAuthenticationToken|Authorization_RequestDenied)\b') {
        return $false
    }
    return $messages -match 'The request was canceled due to the configured HttpClient\.Timeout of \d+(?:\.\d+)? seconds elapsing\.'
}

function Get-McpRetryDelay([int]$Attempt, [string]$RetryAfter) {
    $delay = [Math]::Pow(2, $Attempt + 1)
    $seconds = 0
    $retryDate = [DateTimeOffset]::MinValue
    if ([int]::TryParse($RetryAfter, [ref]$seconds) -and $seconds -ge 0) {
        $delay = $seconds
    } elseif ([DateTimeOffset]::TryParseExact($RetryAfter, 'r',
        [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::None, [ref]$retryDate)) {
        $delay = [Math]::Max(0, [Math]::Ceiling(($retryDate - [DateTimeOffset]::UtcNow).TotalSeconds))
    }
    if ($delay -gt 120) {
        Write-ExportProgress 'Retry-After exceeds the 120-second automatic wait limit; stopping rather than retrying too early.' 'WARN'
        return $null
    }
    return $delay
}

function Invoke-McpRequest([string]$Method, $Params, [switch]$Notification) {
    if ($Method -eq 'tools/call' -and -not (Test-ReadOnlyAgencyTool $Params.name)) {
        throw "Tool '$($Params.name)' is not in the read-only allowlist."
    }
    $payload = @{ jsonrpc = '2.0'; method = $Method; params = $Params }
    if (-not $Notification) { $payload.id = ++$script:RequestId }
    $body = $payload | ConvertTo-Json -Depth 30 -Compress
    $operation = if ($Method -eq 'tools/call') { $Params.name } else { $Method }
    for ($attempt = 0; ; $attempt++) {
        Write-ExportProgress "$operation request attempt $($attempt + 1)/5 in flight (HTTP timeout: 120 seconds)."
        try {
            $response = Invoke-WebRequest -Uri $script:McpUri -Method Post `
                -Headers $script:McpHeaders -ContentType 'application/json' `
                -Body $body -TimeoutSec 120 -SkipHttpErrorCheck
        } catch {
            # Only read-only calls are made, so a transport retry cannot duplicate writes.
            if ($attempt -ge 4) {
                Write-ExportProgress "$operation transport retries exhausted after 5 attempts. Check network/Agency availability; see the diagnostic log." 'ERROR'
                throw
            }
            $delay = Get-McpRetryDelay $attempt ''
            Write-ExportProgress "$operation MCP transport failed; retry $($attempt + 1)/4 in $delay seconds." 'WARN'
            Start-Sleep -Seconds $delay
            continue
        }
        $status = [int]$response.StatusCode
        if ($status -in @(429, 502, 503, 504) -and $attempt -lt 4) {
            $retryAfter = [string]($response.Headers['Retry-After'] | Select-Object -First 1)
            $delay = Get-McpRetryDelay $attempt $retryAfter
            if ($null -ne $delay) {
                Write-ExportProgress "$operation MCP HTTP $status; retry $($attempt + 1)/4 in $delay seconds." 'WARN'
                Start-Sleep -Seconds $delay
                continue
            }
        }
        if ($status -lt 200 -or $status -ge 300) {
            Write-ExportProgress "$operation HTTP $status failed (attempt $($attempt + 1)/5); no further retry. Check service availability or account access; see the diagnostic log." 'ERROR'
            throw "MCP HTTP ${status}: $($response.Content)"
        }
        if ($Method -eq 'initialize') {
            $session = $response.Headers['mcp-session-id'] | Select-Object -First 1
            if ($session) { $script:McpHeaders['Mcp-Session-Id'] = [string]$session }
        }
        if ($Notification) { return }
        $text = [string]$response.Content
        if ($text.TrimStart().StartsWith('{')) {
            $rpc = $text | ConvertFrom-Json -AsHashtable -Depth 100 -DateKind String
        } else {
            $rpc = $null
            foreach ($event in ($text -split '\r?\n\r?\n')) {
                $data = @($event -split '\r?\n' |
                    Where-Object { $_.StartsWith('data:') } |
                    ForEach-Object { $_.Substring(5).TrimStart() })
                if ($data.Count -eq 0) { continue }
                $candidate = ($data -join "`n") | ConvertFrom-Json -AsHashtable -Depth 100 -DateKind String
                if ($candidate.id -eq $payload.id) { $rpc = $candidate }
            }
        }
        if (-not $rpc -or $rpc.id -ne $payload.id) { throw 'Missing matching MCP response.' }
        if ($rpc.error) {
            Write-ExportProgress "$operation returned a JSON-RPC error; not retrying an unclassified error." 'ERROR'
            throw ($rpc.error | ConvertTo-Json -Compress -Depth 20)
        }
        if (-not $rpc.Contains('result')) { throw 'MCP result is missing.' }
        # Tool and transport failures share this one budget: at most five HTTP requests.
        if ($Method -eq 'tools/call' -and $attempt -lt 4 -and (Test-AgencyTimeout $rpc.result)) {
            $retryAfter = [string]($response.Headers['Retry-After'] | Select-Object -First 1)
            $delay = Get-McpRetryDelay $attempt $retryAfter
            if ($null -ne $delay) {
                Write-ExportProgress "Agency $($Params.name) internal HttpClient timeout; retry $($attempt + 1)/4 in $delay seconds." 'WARN'
                Start-Sleep -Seconds $delay
                continue
            }
        }
        return $rpc.result
    }
}

function Invoke-AgencyTool([string]$Name, [hashtable]$Arguments) {
    if (-not (Test-ReadOnlyAgencyTool $Name)) {
        throw "Tool '$Name' is not in the read-only allowlist."
    }
    $result = Invoke-McpRequest 'tools/call' @{ name = $Name; arguments = $Arguments }
    if ($result.isError) {
        $reason = if (Test-AgencyTimeout $result) { 'internal timeout retry budget/wait limit exhausted' } else { 'nonretryable tool error' }
        Write-ExportProgress "Agency $Name failed: $reason. Check Agency availability, account access and inputs; see the diagnostic log." 'ERROR'
        throw "Agency $Name failed: $($result | ConvertTo-Json -Compress -Depth 100)"
    }
    if ($result.structuredContent) { return $result.structuredContent }
    foreach ($block in $result.content) {
        if ($block.type -eq 'text' -and $block.text.TrimStart().StartsWith('{')) {
            return ($block.text | ConvertFrom-Json -AsHashtable -Depth 100 -DateKind String)
        }
    }
    throw "Agency $Name returned no structured JSON data."
}

function Start-AgencyProxy([string]$LogDir) {
    Write-ExportProgress 'Starting owned Agency Teams proxy; connecting with the installed Agency account.' -Phase 'connection'
    $agency = (Get-Command agency -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
    $script:ProxyProcess = Start-Process -FilePath $agency `
        -ArgumentList @('mcp', 'teams', '--transport', 'http') -PassThru -NoNewWindow `
        -RedirectStandardOutput (Join-Path $LogDir 'agency.stdout.log') `
        -RedirectStandardError (Join-Path $LogDir 'agency.stderr.log')
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds(90)
    while ([DateTimeOffset]::UtcNow -lt $deadline) {
        $stdout = Get-Content -LiteralPath (Join-Path $LogDir 'agency.stdout.log') -Raw
        if ($stdout -match '(?m)^\s*(\d{1,5})\s*$') {
            $port = [int]$Matches[1]
            if ($port -lt 1 -or $port -gt 65535) { throw 'Agency returned an invalid port.' }
            $script:McpUri = "http://localhost:$port/"
            $script:McpHeaders = @{ Accept = 'application/json, text/event-stream' }
            $script:RequestId = 0
            $null = Invoke-McpRequest 'initialize' @{
                protocolVersion = '2024-11-05'; capabilities = @{}
                clientInfo = @{ name = 'teams-channel-export'; version = '1.0' }
            }
            Invoke-McpRequest 'notifications/initialized' @{} -Notification
            Write-ExportProgress 'Agency MCP connection initialized.'
            return
        }
        if ($script:ProxyProcess.HasExited) {
            throw "Agency exited: $(Get-Content -LiteralPath (Join-Path $LogDir 'agency.stderr.log') -Raw)"
        }
        Start-Sleep -Milliseconds 200
    }
    throw "Agency startup timed out. See logs in $LogDir."
}

function Resolve-ExportChannel([string]$ChannelId, [string]$RequestedTeamId) {
    Write-ExportProgress 'Discovering accessible teams.' -Phase 'channel_resolution'
    $teams = Get-PageItems (Invoke-AgencyTool 'ListTeams' @{}) 'teams'
    if ($RequestedTeamId) {
        $null = [guid]::Parse($RequestedTeamId)
        $teams = @($teams | Where-Object { $_.id -eq $RequestedTeamId })
        if ($teams.Count -ne 1) { throw 'TeamId was not found in accessible teams.' }
    }
    foreach ($team in $teams) {
        Write-ExportProgress 'Discovering channels in the candidate team.'
        $channels = Get-PageItems (Invoke-AgencyTool 'ListChannels' @{ teamId = $team.id }) 'channels'
        foreach ($channel in $channels) {
            if ($channel.id -eq $ChannelId) { return @{ team = $team; channel = $channel } }
        }
    }
    throw "Channel '$ChannelId' was not found in accessible teams."
}

function Get-ThreadReplies([string]$ResolvedTeamId, [string]$ChannelId, [string]$MessageId, $Stats) {
    $arguments = @{
        teamId = $ResolvedTeamId; channelId = $ChannelId; messageId = $MessageId
        maxReplies = 50; include = 'attachments,reactions'
    }
    $seenLinks = [Collections.Generic.HashSet[string]]::new()
    $replies = [ordered]@{}
    $threadPage = 0
    do {
        Write-ExportProgress "Fetching reply page $($threadPage + 1) for selected thread; total reply pages completed=$($Stats.replyPages)."
        $page = Invoke-AgencyTool 'ListChannelMessageReplies' $arguments
        $Stats.replyPages++
        $threadPage++
        if ($page.parentMessageId -and $page.parentMessageId -ne $MessageId) {
            throw 'Agency returned replies for the wrong parent message.'
        }
        foreach ($reply in (Get-PageItems $page 'replies')) {
            if (-not $reply.id -or -not $reply.createdDateTime) { throw 'Reply identity/time is missing.' }
            $replies[[string]$reply.id] = $reply
        }
        $next = Get-NextPage $page
        Write-ExportProgress "Reply page $threadPage received; unique replies for this thread=$($replies.Count); total reply pages=$($Stats.replyPages)."
        if ($next) {
            if (-not $seenLinks.Add($next)) { throw 'Repeated reply pagination link.' }
            $arguments.nextLink = $next
        }
    } while ($next)
    return ,@($replies.Values | Sort-Object { [DateTimeOffset]$_.createdDateTime }, { $_.id })
}

function Save-SelectedThreads($Resolved, [DateTimeOffset]$Start, [DateTimeOffset]$End,
    [TimeZoneInfo]$Zone, [string]$ThreadDir, $Manifest, [string]$ManifestPath) {
    $arguments = @{
        teamId = $Resolved.team.id; channelId = $Resolved.channel.id
        top = 50; include = 'attachments,reactions'
    }
    $seenLinks = [Collections.Generic.HashSet[string]]::new()
    $seenPosts = [Collections.Generic.HashSet[string]]::new()
    do {
        Write-ExportProgress "Scanning root page $($Manifest.counts.postPages + 1); roots scanned=$($Manifest.counts.postsScanned), threads completed=$($Manifest.counts.posts), replies saved=$($Manifest.counts.replies)." -Phase 'message_download'
        $page = Invoke-AgencyTool 'ListChannelMessages' $arguments
        $Manifest.counts.postPages++
        foreach ($post in (Get-PageItems $page 'messages')) {
            if (-not $post.id -or -not $post.createdDateTime) { throw 'Post identity/time is missing.' }
            if (-not $seenPosts.Add([string]$post.id)) { continue }
            $Manifest.counts.postsScanned++
            $created = [DateTimeOffset]::Parse($post.createdDateTime, [Globalization.CultureInfo]::InvariantCulture)
            if ($created -lt $Start -or $created -ge $End) { continue }
            Write-ExportProgress "Selected thread $($Manifest.counts.posts + 1); retrieving all reply pages (completed threads=$($Manifest.counts.posts))."
            $replies = Get-ThreadReplies $Resolved.team.id $Resolved.channel.id $post.id $Manifest.counts
            foreach ($message in @($post) + @($replies)) {
                $message.exportCreatedTime = [TimeZoneInfo]::ConvertTime(
                    [DateTimeOffset]::Parse($message.createdDateTime), $Zone).ToString('o')
                if ($message.lastModifiedDateTime) {
                    $message.exportModifiedTime = [TimeZoneInfo]::ConvertTime(
                        [DateTimeOffset]::Parse($message.lastModifiedDateTime), $Zone).ToString('o')
                }
            }
            $day = [TimeZoneInfo]::ConvertTime($created, $Zone).ToString('yyyy-MM-dd')
            $Manifest.counts.posts++
            $Manifest.counts.replies += $replies.Count
            $thread = @{ day = $day; post = $post; replies = @($replies) }
            Write-ExportJson (Join-Path $ThreadDir "$($Manifest.counts.posts).json") $thread
            Write-ExportJson $ManifestPath $Manifest
            Write-ExportProgress "Thread saved; completed threads=$($Manifest.counts.posts), replies saved=$($Manifest.counts.replies)."
        }
        $next = Get-NextPage $page
        Write-ExportProgress "Root page $($Manifest.counts.postPages) scanned; roots scanned=$($Manifest.counts.postsScanned), selected/completed=$($Manifest.counts.posts), replies saved=$($Manifest.counts.replies); more pages=$([bool]$next)."
        if ($next) {
            if (-not $seenLinks.Add($next)) { throw 'Repeated channel pagination link.' }
            $arguments.nextLink = $next
        }
        Write-ExportJson $ManifestPath $Manifest
    } while ($next)
}

function Invoke-ChannelExport {
    $script:ExportResult = [ordered]@{
        status = 'in_progress'; phase = 'input'; outputPath = $null; manifestPath = $null
        dataDirectory = $null; counts = $null; timeZone = $null
        startTimeInclusive = $null; endTimeExclusive = $null
        diagnosticsPath = $script:ExportLogPath; error = $null
    }
    Write-ExportProgress 'Validating channel input and inclusive-start/exclusive-end interval.' -Phase 'input'
    if ($InputPath) {
        $values = Read-ExportInput $InputPath
        $ChannelUrl = $values.ChannelUrl
        $StartTime = $values.StartTime
        $EndTime = $values.EndTime
        $OutputDir = $values.OutputDir
        $TimeZone = if ($values.Contains('TimeZone')) { $values.TimeZone } else { [TimeZoneInfo]::Local.Id }
    }
    $requestedUrl = $null
    if ($ChannelUrl) {
        $requestedUrl = Convert-TeamsChannelUrl $ChannelUrl
        $channelId = $requestedUrl.channelId
        $requestedTeamId = $requestedUrl.teamId
    } else {
        Assert-ChannelId $TeamsChannelId
        if ($TeamId) { Assert-TeamsGuid $TeamId 'TeamId' }
        $channelId = $TeamsChannelId
        $requestedTeamId = $TeamId
    }
    $zone = [TimeZoneInfo]::FindSystemTimeZoneById($TimeZone)
    $start = Convert-ExportTime $StartTime $zone
    $end = Convert-ExportTime $EndTime $zone
    if ($start -ge $end) { throw 'StartTime must be earlier than EndTime.' }
    $script:ExportResult.timeZone = $zone.Id
    $script:ExportResult.startTimeInclusive = $start.ToUniversalTime().ToString('o')
    $script:ExportResult.endTimeExclusive = $end.ToUniversalTime().ToString('o')
    Write-ExportProgress "Checking Python and renderer dependencies; timezone=$($zone.Id)." -Phase 'dependencies'
    $python = (Get-Command python -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
    & $python -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.10 or newer is required.' }
    $renderer = Join-Path $PSScriptRoot 'teams_export_markdown.py'
    if (-not (Test-Path -LiteralPath $renderer -PathType Leaf)) { throw "Missing renderer: $renderer" }
    $logDir = Join-Path ([IO.Path]::GetTempPath()) "teams-export-$([guid]::NewGuid())"
    $null = New-Item -ItemType Directory -Path $logDir
    $manifest = $null
    $manifestPath = $null
    $script:ProxyProcess = $null
    try {
        Start-AgencyProxy $logDir
        $resolved = Resolve-ExportChannel $channelId $requestedTeamId
        Write-ExportProgress 'Accessible channel resolved; preparing exclusive output artifacts.' -Phase 'output_claim'
        if ([string]::IsNullOrWhiteSpace($resolved.channel.displayName)) {
            throw 'Accessible channel metadata has no display name.'
        }
        foreach ($metadata in @($resolved.team, $resolved.channel)) {
            if ($requestedUrl -and $metadata.tenantId -and $metadata.tenantId -ne $requestedUrl.tenantId) {
                throw 'URL tenantId does not match accessible Teams metadata.'
            }
        }
        $firstDay = [TimeZoneInfo]::ConvertTime($start, $zone).ToString('yyyy-MM-dd')
        $lastDay = [TimeZoneInfo]::ConvertTime($end.AddTicks(-1), $zone).ToString('yyyy-MM-dd')
        $stem = Get-ExportStem $resolved.channel.displayName $firstDay $lastDay
        $outputPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputDir)
        $markdownPath = Join-Path $outputPath "$stem.md"
        $directory = Join-Path $outputPath "$stem.data"
        if ((Test-Path -LiteralPath $markdownPath) -or (Test-Path -LiteralPath $directory)) {
            throw "Export artifacts already exist for '$stem'. Choose another OutputDir; existing exports are never overwritten."
        }
        $null = New-Item -ItemType Directory -Path $outputPath -Force
        # This exclusive directory claim serializes writers for the same filename stem.
        $null = New-Item -ItemType Directory -Path $directory
        $manifestPath = Join-Path $directory 'manifest.json'
        $threadDir = Join-Path $directory 'threads'
        $manifest = [ordered]@{
            schemaVersion = 2; status = 'in_progress'
            exportStartedAt = [DateTimeOffset]::UtcNow.ToString('o')
            exportCompletedAt = $null
            teamId = $resolved.team.id; teamName = $resolved.team.displayName
            channelId = $resolved.channel.id; channelName = $resolved.channel.displayName
            channelUrl = $resolved.channel.webUrl
            team = $resolved.team; channel = $resolved.channel
            requestedChannelUrl = $requestedUrl
            startTimeInclusive = $start.ToUniversalTime().ToString('o')
            endTimeExclusive = $end.ToUniversalTime().ToString('o')
            timeZone = $zone.Id
            firstCoveredDate = $firstDay; lastCoveredDate = $lastDay
            markdownFile = "$stem.md"; dataDirectory = "$stem.data"
            selection = 'Root posts created in [start,end), with all available replies'
            counts = [ordered]@{ postsScanned = 0; posts = 0; replies = 0; postPages = 0; replyPages = 0 }
            files = @(); errors = @()
            limitations = @(
                'Live enumeration is not an atomic snapshot; messages may change during export.'
                'Linked files, deleted bodies and previous edit versions are not downloaded.'
                'Only fields exposed by the Agency Teams tools are available.'
            )
        }
        $script:ExportResult.outputPath = $markdownPath
        $script:ExportResult.manifestPath = $manifestPath
        $script:ExportResult.dataDirectory = $directory
        $script:ExportResult.counts = $manifest.counts
        Write-ExportJson $manifestPath $manifest
        $null = New-Item -ItemType Directory -Path $threadDir
        Save-SelectedThreads $resolved $start $end $zone $threadDir $manifest $manifestPath
        Write-ExportProgress "Rendering one combined Markdown file; threads=$($manifest.counts.posts), replies=$($manifest.counts.replies)." -Phase 'rendering'
        & $python $renderer --export-dir $directory | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Markdown renderer failed with exit code $LASTEXITCODE." }
        if (-not (Test-Path -LiteralPath $markdownPath -PathType Leaf)) {
            throw 'Markdown renderer did not create the expected combined file.'
        }
        $manifest.files = @("$stem.md")
        $manifest.status = 'complete'
        $manifest.exportCompletedAt = [DateTimeOffset]::UtcNow.ToString('o')
        Write-ExportJson $manifestPath $manifest
    } catch {
        $failure = $_
        if ($manifest -and $manifestPath) {
            $manifest.status = 'incomplete'
            $manifest.exportCompletedAt = [DateTimeOffset]::UtcNow.ToString('o')
            $manifest.errors = @($failure.Exception.Message)
            Write-ExportJson $manifestPath $manifest
            $script:ExportResult.status = 'incomplete'
        }
        Write-ExportProgress "Export stopped; Agency diagnostic logs are in $logDir." 'ERROR'
        throw $failure
    } finally {
        Write-ExportProgress 'Stopping the owned Agency process and cleaning successful proxy logs.'
        if ($script:ProxyProcess -and -not $script:ProxyProcess.HasExited) {
            $script:ProxyProcess.Kill($true)
            $script:ProxyProcess.WaitForExit()
        }
        if ($manifest -and $manifest.status -eq 'complete') {
            foreach ($name in @('agency.stdout.log', 'agency.stderr.log')) {
                $log = Join-Path $logDir $name
                if (Test-Path -LiteralPath $log) { Remove-Item -LiteralPath $log }
            }
            Remove-Item -LiteralPath $logDir
        }
    }
    $script:ExportResult.status = 'complete'
    Write-ExportProgress "Complete: $($manifest.counts.posts) posts and $($manifest.counts.replies) replies. Markdown: $markdownPath" -Phase 'complete'
}

function Invoke-ExportMain {
    $script:ExportLogPath = Join-Path ([IO.Path]::GetTempPath()) "teams-export-run-$([guid]::NewGuid()).log"
    $log = [IO.File]::Open($script:ExportLogPath, [IO.FileMode]::CreateNew)
    $log.Dispose()
    $script:SummaryOwned = $false
    $script:ExportResult = $null
    try {
        if ($SummaryPath) {
            $script:SummaryFile = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($SummaryPath)
            $summary = [IO.File]::Open($script:SummaryFile, [IO.FileMode]::CreateNew)
            $summary.Dispose()
            $script:SummaryOwned = $true
        }
        Write-ExportProgress "Diagnostic log: $script:ExportLogPath"
        Invoke-ChannelExport
        return 0
    } catch {
        $failure = $_
        [IO.File]::AppendAllText($script:ExportLogPath, $failure.Exception.ToString(), [Text.UTF8Encoding]::new($false))
        if ($script:ExportResult) {
            if ($script:ExportResult.status -ne 'incomplete') { $script:ExportResult.status = 'failed' }
            $script:ExportResult.error = "Failed during $($script:ExportResult.phase) ($($failure.Exception.GetType().Name))."
        }
        $phase = if ($script:ExportResult) { $script:ExportResult.phase } else { 'summary initialization' }
        $advice = switch ($phase) {
            'input' { 'Check the Teams channel URL, required JSON fields, dates and timezone; EndTime is exclusive.' }
            'dependencies' { 'Ensure PowerShell 7.5+, Python 3.10+ and the bundled renderer are available.' }
            'connection' { 'Check Agency installation, sign-in and service/network availability.' }
            'channel_resolution' { 'Check Agency sign-in, team/channel access and service availability.' }
            'output_claim' { 'Check output write access or choose a new OutputDir; existing artifacts are never overwritten.' }
            'message_download' { 'Check Agency/service access; preserve partial artifacts and use a new OutputDir for a fresh attempt.' }
            'rendering' { 'Inspect the local diagnostic log and raw sidecars; the export is incomplete.' }
            default { 'Check that SummaryPath is new, its parent exists and it is writable.' }
        }
        Write-ExportProgress "Failed during $phase. $advice Details: $script:ExportLogPath" 'ERROR'
        return 1
    } finally {
        $script:SummaryOwned = $false
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    exit (Invoke-ExportMain)
}
