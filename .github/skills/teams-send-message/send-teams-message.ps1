[CmdletBinding(DefaultParameterSetName = 'DefaultChannel')]
param(
    [Parameter(Mandatory, ParameterSetName = 'User')]
    [ValidateNotNullOrEmpty()]
    [string]$Recipient,

    [Parameter(Mandatory, ParameterSetName = 'DefaultPerson')]
    [switch]$ToPerson,

    [Parameter(Mandatory, ParameterSetName = 'Channel')]
    [ValidateNotNullOrEmpty()]
    [string]$Team,

    [Parameter(Mandatory, ParameterSetName = 'Channel')]
    [ValidateNotNullOrEmpty()]
    [string]$Channel,

    [Parameter(Mandatory, ParameterSetName = 'ChannelLink')]
    [ValidateNotNullOrEmpty()]
    [string]$ChannelLink,

    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$Message,

    [ValidateSet('text', 'html')]
    [string]$ContentType = 'text',

    [ValidateSet('normal', 'high', 'urgent')]
    [string]$Importance = 'normal',

    [Parameter(ParameterSetName = 'DefaultChannel')]
    [Parameter(ParameterSetName = 'Channel')]
    [Parameter(ParameterSetName = 'ChannelLink')]
    [ValidateNotNullOrEmpty()]
    [string]$Subject,

    [Parameter(ParameterSetName = 'DefaultChannel')]
    [Parameter(ParameterSetName = 'Channel')]
    [Parameter(ParameterSetName = 'ChannelLink')]
    [ValidateNotNullOrEmpty()]
    [string]$Mentions,

    [Parameter(ParameterSetName = 'DefaultChannel')]
    [Parameter(ParameterSetName = 'Channel')]
    [Parameter(ParameterSetName = 'ChannelLink')]
    [ValidateNotNullOrEmpty()]
    [string]$AdaptiveCardJson,

    [Parameter(ParameterSetName = 'DefaultChannel')]
    [Parameter(ParameterSetName = 'Channel')]
    [Parameter(ParameterSetName = 'ChannelLink')]
    [ValidateNotNullOrEmpty()]
    [string]$AttachmentsJson
)

$ErrorActionPreference = 'Stop'
$defaultRecipient = 'Yuchao Yan'
$defaultChannelLink = 'https://teams.microsoft.com/l/channel/19%3AWURrTJg444lI3dCe0-sYsQp71m5ZFGQYh9oBf9OA5bo1%40thread.tacv2/TaskDone-YuchaoYan?groupId=7ccc31f0-b371-450b-a73c-48f5a31a9b96&tenantId=72f988bf-86f1-41af-91ab-2d7cd011db47&ngc=true'

if ($AdaptiveCardJson -and $AttachmentsJson) {
    throw 'AdaptiveCardJson and AttachmentsJson cannot be combined.'
}

$agency = Get-Command agency -ErrorAction SilentlyContinue

if (-not $agency) {
    throw @'
Agency is required but was not found.
Install it after reviewing the Microsoft-hosted installer:
  iex "& { $(irm aka.ms/InstallTool.ps1)} agency"
Then rerun this command.
'@
}

. "$PSScriptRoot\..\common\agency-mcp.ps1"

function Resolve-NamedEntity {
    param(
        [Parameter(Mandatory)]
        [object[]]$Entities,

        [Parameter(Mandatory)]
        [string]$Value,

        [Parameter(Mandatory)]
        [string]$EntityType
    )

    $needle = $Value.Trim()
    $exactMatches = @($Entities | Where-Object {
        $_.id -ieq $needle -or $_.displayName -ieq $needle
    })

    if ($exactMatches.Count -eq 1) {
        return $exactMatches[0]
    }
    if ($exactMatches.Count -gt 1) {
        $candidates = $exactMatches |
            Select-Object displayName |
            ConvertTo-Json -Compress
        throw "$EntityType '$Value' is ambiguous. Candidates: $candidates"
    }
    if ($Entities.Count -eq 0) {
        throw "No Teams $EntityType is available to match '$Value'."
    }

    throw "No Teams $EntityType matched '$Value'."
}

function ConvertFrom-TeamsChannelLink {
    param(
        [Parameter(Mandatory)]
        [string]$Link
    )

    try {
        $uri = [uri]$Link
    }
    catch {
        throw "Invalid Teams channel link: $Link"
    }

    if ($uri.Scheme -ne 'https' -or $uri.Host -ne 'teams.microsoft.com') {
        throw 'ChannelLink must be an https://teams.microsoft.com channel URL.'
    }

    $pathParts = @($uri.AbsolutePath.Trim('/') -split '/')
    if (
        $pathParts.Count -lt 4 -or
        $pathParts[0] -ne 'l' -or
        $pathParts[1] -ne 'channel'
    ) {
        throw 'ChannelLink does not contain a Teams channel ID.'
    }

    $channelId = [uri]::UnescapeDataString($pathParts[2])
    $groupIdMatch = [regex]::Match(
        $uri.Query.TrimStart('?'),
        '(?:^|&)groupId=([^&]+)',
        [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
    )
    $teamId = if ($groupIdMatch.Success) {
        [uri]::UnescapeDataString($groupIdMatch.Groups[1].Value)
    }
    $parsedTeamId = [guid]::Empty
    if (
        -not $teamId -or
        -not [guid]::TryParse($teamId, [ref]$parsedTeamId) -or
        $channelId -notlike '*@thread.tacv2'
    ) {
        throw 'ChannelLink does not contain valid team and channel IDs.'
    }

    return @{
        TeamId = $parsedTeamId.ToString()
        ChannelId = $channelId
    }
}

$userConnection = $null
$teamsConnection = $null

try {
    if ($PSCmdlet.ParameterSetName -notin @('User', 'DefaultPerson')) {
        $teamsConnection = Start-AgencyMcp -Server 'teams'
        $teamsResult = Invoke-McpTool `
            -BaseUrl $teamsConnection.BaseUrl `
            -Name 'ListTeams'
        $teams = ConvertTo-EntityList `
            -Payload (ConvertFrom-ToolContent -ToolResult $teamsResult) `
            -CollectionNames @('value', 'teams', 'results')

        if ($PSCmdlet.ParameterSetName -eq 'Channel') {
            $targetTeam = Resolve-NamedEntity `
                -Entities $teams `
                -Value $Team `
                -EntityType 'team'
            $channelValue = $Channel
        }
        else {
            $link = if ($PSCmdlet.ParameterSetName -eq 'ChannelLink') {
                $ChannelLink
            }
            else {
                $defaultChannelLink
            }
            $channelTarget = ConvertFrom-TeamsChannelLink -Link $link
            $targetTeam = Resolve-NamedEntity `
                -Entities $teams `
                -Value $channelTarget.TeamId `
                -EntityType 'team'
            $channelValue = $channelTarget.ChannelId
        }

        $channelsResult = Invoke-McpTool `
            -BaseUrl $teamsConnection.BaseUrl `
            -Name 'ListChannels' `
            -Arguments @{ teamId = $targetTeam.id }
        $channels = ConvertTo-EntityList `
            -Payload (ConvertFrom-ToolContent -ToolResult $channelsResult) `
            -CollectionNames @('value', 'channels', 'results')
        $targetChannel = Resolve-NamedEntity `
            -Entities $channels `
            -Value $channelValue `
            -EntityType 'channel'

        $messageArguments = @{
            teamId = $targetTeam.id
            channelId = $targetChannel.id
            content = $Message
            contentType = $ContentType
            importance = $Importance
        }
        foreach ($optionalArgument in @(
            'Subject',
            'Mentions',
            'AdaptiveCardJson',
            'AttachmentsJson'
        )) {
            if ($PSBoundParameters.ContainsKey($optionalArgument)) {
                $argumentName = $optionalArgument.Substring(0, 1).ToLowerInvariant() +
                    $optionalArgument.Substring(1)
                $messageArguments[$argumentName] = $PSBoundParameters[$optionalArgument]
            }
        }

        $sendResult = Invoke-McpTool `
            -BaseUrl $teamsConnection.BaseUrl `
            -Name 'SendMessageToChannel' `
            -Arguments $messageArguments
        $sent = ConvertFrom-ToolContent -ToolResult $sendResult
        if (-not $sent.id) {
            throw 'Teams did not return a message ID.'
        }

        [pscustomobject]@{
            status = 'sent'
            team = $targetTeam.displayName
            channel = $targetChannel.displayName
            messageId = $sent.id
            createdDateTime = $sent.createdDateTime
        } | ConvertTo-Json -Compress
    }
    else {
        $recipientValue = if ($PSCmdlet.ParameterSetName -eq 'DefaultPerson') {
            $defaultRecipient
        }
        else {
            $Recipient
        }
        $userConnection = Start-AgencyMcp -Server 'm365-user'

        $meResult = Invoke-McpTool `
            -BaseUrl $userConnection.BaseUrl `
            -Name 'GetMyDetails' `
            -Arguments @{ select = 'id,displayName,userPrincipalName,mail' }
        $me = ConvertFrom-ToolContent -ToolResult $meResult

        $selfNames = @('me', 'myself', 'self')
        if ($selfNames -contains $recipientValue.Trim().ToLowerInvariant()) {
            $target = $me
        }
        else {
            $lookupResult = Invoke-McpTool `
                -BaseUrl $userConnection.BaseUrl `
                -Name 'GetMultipleUsersDetails' `
                -Arguments @{
                    searchValues = @($recipientValue)
                    select = 'id,displayName,userPrincipalName,mail'
                    top = 20
                }
            $users = ConvertTo-EntityList `
                -Payload (ConvertFrom-ToolContent -ToolResult $lookupResult) `
                -CollectionNames @('value', 'users', 'results')

            $needle = $recipientValue.Trim()
            $exactMatches = @($users | Where-Object {
                $upnAlias = if ($_.userPrincipalName) {
                    ($_.userPrincipalName -split '@', 2)[0]
                }
                $mailAlias = if ($_.mail) {
                    ($_.mail -split '@', 2)[0]
                }

                $_.displayName -ieq $needle -or
                $_.userPrincipalName -ieq $needle -or
                $_.mail -ieq $needle -or
                $upnAlias -ieq $needle -or
                $mailAlias -ieq $needle
            })

            if ($exactMatches.Count -eq 1) {
                $target = $exactMatches[0]
            }
            elseif ($users.Count -eq 1) {
                $target = $users[0]
            }
            elseif ($users.Count -eq 0) {
                throw "No Teams user matched '$recipientValue'."
            }
            else {
                $candidates = $users |
                    Select-Object displayName, userPrincipalName |
                    ConvertTo-Json -Compress
                throw "Recipient '$recipientValue' is ambiguous. Candidates: $candidates"
            }
        }

        $teamsConnection = Start-AgencyMcp -Server 'teams'
        $messageArguments = @{
            content = $Message
            contentType = $ContentType
            importance = $Importance
        }

        if ($target.id -eq $me.id) {
            $sendResult = Invoke-McpTool `
                -BaseUrl $teamsConnection.BaseUrl `
                -Name 'SendMessageToSelf' `
                -Arguments $messageArguments
        }
        else {
            $messageArguments.userIdOrUpn = $target.userPrincipalName
            $sendResult = Invoke-McpTool `
                -BaseUrl $teamsConnection.BaseUrl `
                -Name 'SendMessageToUser' `
                -Arguments $messageArguments
        }

        $sent = ConvertFrom-ToolContent -ToolResult $sendResult
        if (-not $sent.id) {
            throw 'Teams did not return a message ID.'
        }

        [pscustomobject]@{
            status = 'sent'
            recipient = $target.displayName
            messageId = $sent.id
            createdDateTime = $sent.createdDateTime
        } | ConvertTo-Json -Compress
    }
}
finally {
    Stop-AgencyMcp -Connection $teamsConnection
    Stop-AgencyMcp -Connection $userConnection
}
