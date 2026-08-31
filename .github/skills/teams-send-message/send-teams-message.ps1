[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$Recipient,

    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$Message,

    [ValidateSet('text', 'html')]
    [string]$ContentType = 'text',

    [ValidateSet('normal', 'high', 'urgent')]
    [string]$Importance = 'normal'
)

$ErrorActionPreference = 'Stop'
$agency = Get-Command agency -ErrorAction SilentlyContinue

if (-not $agency) {
    throw @'
Agency is required but was not found.
Install it after reviewing the Microsoft-hosted installer:
  iex "& { $(irm aka.ms/InstallTool.ps1)} agency"
Then rerun this command.
'@
}

function Get-FreeTcpPort {
    $listener = [System.Net.Sockets.TcpListener]::new(
        [System.Net.IPAddress]::Loopback,
        0
    )
    $listener.Start()
    try {
        return ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
    }
    finally {
        $listener.Stop()
    }
}

function Invoke-McpCall {
    param(
        [Parameter(Mandatory)]
        [string]$BaseUrl,

        [Parameter(Mandatory)]
        [string]$Method,

        [hashtable]$Params = @{},

        [int]$Id = 1
    )

    $body = @{
        jsonrpc = '2.0'
        id = $Id
        method = $Method
        params = $Params
    } | ConvertTo-Json -Depth 20 -Compress

    $response = Invoke-WebRequest `
        -Uri $BaseUrl `
        -Method Post `
        -ContentType 'application/json' `
        -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) `
        -TimeoutSec 60

    $dataLine = $response.Content -split "`n" |
        Where-Object { $_ -like 'data: *' } |
        Select-Object -First 1

    if (-not $dataLine) {
        throw "Agency MCP returned no response data."
    }

    $envelope = $dataLine.Substring(6) | ConvertFrom-Json
    if ($envelope.error) {
        throw "Agency MCP error: $($envelope.error.message)"
    }

    return $envelope.result
}

function Start-AgencyMcp {
    param(
        [Parameter(Mandatory)]
        [string]$Server
    )

    $port = Get-FreeTcpPort
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $agency.Source
    $startInfo.ArgumentList.Add('mcp')
    $startInfo.ArgumentList.Add($Server)
    $startInfo.ArgumentList.Add('--transport')
    $startInfo.ArgumentList.Add('http')
    $startInfo.ArgumentList.Add('--port')
    $startInfo.ArgumentList.Add([string]$port)
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true

    $process = [System.Diagnostics.Process]::Start($startInfo)
    $baseUrl = "http://localhost:$port/"
    $waitMilliseconds = 250

    for ($attempt = 1; $attempt -le 20; $attempt++) {
        Start-Sleep -Milliseconds $waitMilliseconds

        if ($process.HasExited) {
            $details = $process.StandardError.ReadToEnd().Trim()
            throw "Agency MCP server '$Server' exited during startup. $details"
        }

        try {
            $result = Invoke-McpCall -BaseUrl $baseUrl -Method 'initialize' -Params @{
                protocolVersion = '2024-11-05'
                capabilities = @{}
                clientInfo = @{
                    name = 'teams-send-message'
                    version = '1.0'
                }
            }

            if ($result.protocolVersion) {
                return @{
                    BaseUrl = $baseUrl
                    Process = $process
                }
            }
        }
        catch {
            # The proxy may still be starting or waiting for cached authentication.
        }

        $waitMilliseconds = [Math]::Min($waitMilliseconds + 250, 1500)
    }

    if (-not $process.HasExited) {
        $process.Kill($true)
        $process.WaitForExit()
    }
    throw "Agency MCP server '$Server' did not become ready."
}

function Stop-AgencyMcp {
    param(
        [AllowNull()]
        [hashtable]$Connection
    )

    if ($Connection -and -not $Connection.Process.HasExited) {
        $Connection.Process.Kill($true)
        $Connection.Process.WaitForExit()
    }
}

function Invoke-McpTool {
    param(
        [Parameter(Mandatory)]
        [string]$BaseUrl,

        [Parameter(Mandatory)]
        [string]$Name,

        [hashtable]$Arguments = @{}
    )

    $result = Invoke-McpCall -BaseUrl $BaseUrl -Method 'tools/call' -Params @{
        name = $Name
        arguments = $Arguments
    } -Id 10

    if ($result.isError) {
        $details = $result.content |
            ForEach-Object { $_.text } |
            Where-Object { $_ } |
            Select-Object -First 1
        throw "Agency tool '$Name' failed: $details"
    }

    return $result
}

function ConvertFrom-ToolContent {
    param(
        [Parameter(Mandatory)]
        $ToolResult
    )

    foreach ($item in $ToolResult.content) {
        if ($item.type -ne 'text' -or -not $item.text) {
            continue
        }

        $text = $item.text.Trim()
        $candidateIndexes = @($text.IndexOf('{'), $text.IndexOf('[')) |
            Where-Object { $_ -ge 0 } |
            Sort-Object

        foreach ($index in $candidateIndexes) {
            try {
                return $text.Substring($index) | ConvertFrom-Json
            }
            catch {
                continue
            }
        }
    }

    throw 'Agency tool response did not contain valid JSON.'
}

function ConvertTo-UserList {
    param(
        [Parameter(Mandatory)]
        $Payload
    )

    if ($Payload -is [array]) {
        return @($Payload)
    }
    if ($null -ne $Payload.value) {
        return @($Payload.value)
    }
    if ($null -ne $Payload.users) {
        return @($Payload.users)
    }
    if ($null -ne $Payload.results) {
        return @($Payload.results)
    }
    return @($Payload)
}

$userConnection = $null
$teamsConnection = $null

try {
    $userConnection = Start-AgencyMcp -Server 'm365-user'

    $meResult = Invoke-McpTool `
        -BaseUrl $userConnection.BaseUrl `
        -Name 'GetMyDetails' `
        -Arguments @{ select = 'id,displayName,userPrincipalName,mail' }
    $me = ConvertFrom-ToolContent -ToolResult $meResult

    $selfNames = @('me', 'myself', 'self')
    if ($selfNames -contains $Recipient.Trim().ToLowerInvariant()) {
        $target = $me
    }
    else {
        $lookupResult = Invoke-McpTool `
            -BaseUrl $userConnection.BaseUrl `
            -Name 'GetMultipleUsersDetails' `
            -Arguments @{
                searchValues = @($Recipient)
                select = 'id,displayName,userPrincipalName,mail'
                top = 20
            }
        $users = ConvertTo-UserList (
            ConvertFrom-ToolContent -ToolResult $lookupResult
        )

        $needle = $Recipient.Trim()
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
            throw "No Teams user matched '$Recipient'."
        }
        else {
            $candidates = $users |
                Select-Object displayName, userPrincipalName |
                ConvertTo-Json -Compress
            throw "Recipient '$Recipient' is ambiguous. Candidates: $candidates"
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
finally {
    Stop-AgencyMcp -Connection $teamsConnection
    Stop-AgencyMcp -Connection $userConnection
}
