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
        [int]$Id = 1,
        [int]$TimeoutSec = 60
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
        -Headers @{ Accept = 'application/json, text/event-stream' } `
        -ContentType 'application/json' `
        -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) `
        -TimeoutSec $TimeoutSec

    if ($response.Content.TrimStart().StartsWith('{')) {
        $envelope = $response.Content | ConvertFrom-Json
    }
    else {
        $envelope = $null
        foreach ($line in ($response.Content -split "`n")) {
            if ($line -like 'data: *') {
                $candidate = $line.Substring(6) | ConvertFrom-Json
                if ($candidate.id -eq $Id) {
                    $envelope = $candidate
                    break
                }
            }
        }
    }
    if (-not $envelope -or $envelope.id -ne $Id) {
        throw 'Agency MCP returned no matching response.'
    }
    if ($envelope.error) {
        throw "Agency MCP error: $($envelope.error.message)"
    }
    return $envelope.result
}

function Start-AgencyMcp {
    param(
        [Parameter(Mandatory)]
        [string]$Server,
        [string]$ClientName = 'teams-send-message'
    )

    $agency = Get-Command agency -ErrorAction SilentlyContinue
    if (-not $agency) {
        throw @'
Agency is required but was not found.
Install it after reviewing the Microsoft-hosted installer:
  iex "& { $(irm aka.ms/InstallTool.ps1)} agency"
Then rerun this command.
'@
    }

    $port = Get-FreeTcpPort
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $agency.Source
    foreach ($argument in @('mcp', $Server, '--transport', 'http', '--port', [string]$port)) {
        $startInfo.ArgumentList.Add($argument)
    }
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true

    $process = [System.Diagnostics.Process]::Start($startInfo)
    # Drain both streams while the proxy runs so logging cannot block a tool call.
    $stdout = $process.StandardOutput.ReadToEndAsync()
    $stderr = $process.StandardError.ReadToEndAsync()
    $connection = @{ BaseUrl = "http://localhost:$port/"; Process = $process }
    $ready = $false
    $lastError = 'No initialize response.'
    try {
        for ($attempt = 1; $attempt -le 20; $attempt++) {
            Start-Sleep -Milliseconds ([Math]::Min(250 * $attempt, 1500))
            if ($process.HasExited) {
                throw "Agency MCP server '$Server' exited during startup. $($stderr.GetAwaiter().GetResult().Trim())"
            }
            try {
                $result = Invoke-McpCall -BaseUrl $connection.BaseUrl -Method 'initialize' -TimeoutSec 5 -Params @{
                    protocolVersion = '2024-11-05'
                    capabilities = @{}
                    clientInfo = @{ name = $ClientName; version = '1.0' }
                }
                if (-not $result.protocolVersion) {
                    throw "Agency MCP server '$Server' returned an invalid initialize response."
                }
                $ready = $true
                return $connection
            }
            catch [System.Net.Http.HttpRequestException], [System.Threading.Tasks.TaskCanceledException] {
                $lastError = $_.Exception.Message
                Write-Verbose "Agency MCP startup pending: $lastError"
            }
        }
        throw "Agency MCP server '$Server' did not become ready. $lastError"
    }
    finally {
        if (-not $ready) {
            Stop-AgencyMcp -Connection $connection
        }
    }
}

function Stop-AgencyMcp {
    param(
        [AllowNull()]
        [hashtable]$Connection
    )
    if ($Connection) {
        if (-not $Connection.Process.HasExited) {
            $Connection.Process.Kill($true)
            $Connection.Process.WaitForExit()
        }
        $Connection.Process.Dispose()
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
    if ($null -ne $ToolResult.structuredContent) {
        return $ToolResult.structuredContent
    }
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
            catch [System.ArgumentException] {
                Write-Verbose "Skipping non-JSON tool text: $($_.Exception.Message)"
            }
        }
    }
    throw 'Agency tool response did not contain valid JSON.'
}

function ConvertTo-EntityList {
    param(
        [Parameter(Mandatory)]
        $Payload,
        [string[]]$CollectionNames = @('value', 'results')
    )
    if ($Payload -is [array]) {
        return @($Payload)
    }
    foreach ($collectionName in $CollectionNames) {
        if ($null -ne $Payload.$collectionName) {
            return @($Payload.$collectionName)
        }
    }
    return @($Payload)
}
