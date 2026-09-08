#requires -Version 7.1
[CmdletBinding(SupportsShouldProcess)]
param(
    [Alias('Recipient')]
    [ValidateNotNullOrEmpty()]
    [string[]]$To = @('me'),

    [ValidateNotNullOrEmpty()]
    [string[]]$Cc,

    [ValidateNotNullOrEmpty()]
    [string[]]$Bcc,

    [ValidateNotNullOrEmpty()]
    [string]$Message,

    [ValidateNotNullOrEmpty()]
    [string]$Subject,

    [ValidateNotNullOrEmpty()]
    [string]$Body
)

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\..\common\agency-mcp.ps1"

if (-not $PSBoundParameters.ContainsKey('Subject')) {
    $Subject = if ($PSBoundParameters.ContainsKey('Message')) { $Message } else { $Body }
}
if (-not $PSBoundParameters.ContainsKey('Body')) {
    $Body = if ($PSBoundParameters.ContainsKey('Message')) { $Message } else { $Subject }
}
if ([string]::IsNullOrWhiteSpace($Subject) -or [string]::IsNullOrWhiteSpace($Body)) {
    throw 'Provide Message, Subject, or Body. Any missing subject or body uses the same text.'
}

function Assert-EmailAddress {
    param([string]$Value)
    $parsed = $null
    if (
        [string]::IsNullOrWhiteSpace($Value) -or
        $Value -match '[\r\n]' -or
        -not [System.Net.Mail.MailAddress]::TryCreate($Value, [ref]$parsed) -or
        $parsed.Address -cne $Value -or
        $Value -notmatch '^[^@\s]+@[^@\s]+\.[^@\s]+$'
    ) {
        throw "Invalid email address '$Value'. Supply a bare email address or a person's name."
    }
}

function Resolve-EmailRecipients {
    param([string[]]$Values)
    foreach ($value in $Values) {
        $needle = $value.Trim()
        if (-not $needle) {
            throw 'Recipients cannot be blank.'
        }
        if ($needle.Contains('@')) {
            Assert-EmailAddress -Value $needle
            $needle
            continue
        }
        if (-not $script:userConnection) {
            $script:userConnection = Start-AgencyMcp -Server 'm365-user' -ClientName 'email-send-message'
        }
        if ($needle -in @('me', 'myself', 'self')) {
            $result = Invoke-McpTool -BaseUrl $script:userConnection.BaseUrl -Name 'GetMyDetails' `
                -Arguments @{ select = 'displayName,mail,userPrincipalName' }
            $target = ConvertFrom-ToolContent -ToolResult $result
        }
        else {
            $result = Invoke-McpTool -BaseUrl $script:userConnection.BaseUrl -Name 'GetMultipleUsersDetails' `
                -Arguments @{
                    searchValues = @($needle)
                    select = 'displayName,mail,userPrincipalName'
                    top = 999
                }
            $payload = ConvertFrom-ToolContent -ToolResult $result
            $users = @(ConvertTo-EntityList -Payload $payload -CollectionNames @('value', 'users', 'results'))
            if ($users.Count -ge 999 -or $payload.'@odata.nextLink' -or $payload.nextLink) {
                throw "Recipient search for '$needle' is incomplete. Supply an explicit email address."
            }
            $matches = @($users | Where-Object {
                $_.displayName -ieq $needle -or
                ($_.mail -and ($_.mail -split '@', 2)[0] -ieq $needle) -or
                ($_.userPrincipalName -and ($_.userPrincipalName -split '@', 2)[0] -ieq $needle)
            })
            if ($matches.Count -eq 1) {
                $target = $matches[0]
            }
            elseif ($users.Count -eq 0) {
                throw "No user matched '$needle'. Supply an explicit email address."
            }
            else {
                $candidates = $users | Select-Object displayName, mail, userPrincipalName |
                    ConvertTo-Json -Compress
                throw "Recipient '$needle' is ambiguous or not an exact match. Choose a candidate: $candidates"
            }
        }
        if (-not $target.mail) {
            throw "Recipient '$needle' has no mailbox address. Supply an explicit email address; a UPN is not assumed to be an email."
        }
        Assert-EmailAddress -Value $target.mail
        $target.mail
    }
}

$script:userConnection = $null
$mailConnection = $null
try {
    $arguments = @{
        to = @(Resolve-EmailRecipients -Values $To | Select-Object -Unique)
        cc = @(Resolve-EmailRecipients -Values $Cc | Select-Object -Unique)
        bcc = @(Resolve-EmailRecipients -Values $Bcc | Select-Object -Unique)
        subject = $Subject
        body = $Body
        contentType = 'Text'
    }
    if (-not $PSCmdlet.ShouldProcess(($arguments.to -join ', '), 'Send email')) {
        [pscustomobject]@{ status = 'not-sent'; email = $arguments } | ConvertTo-Json -Depth 10
        return
    }
    $mailConnection = Start-AgencyMcp -Server 'mail' -ClientName 'email-send-message'
    # Never retry a send: a lost response can still mean the email was sent.
    $result = Invoke-McpTool -BaseUrl $mailConnection.BaseUrl -Name 'SendEmailWithAttachments' -Arguments $arguments
    $sent = ConvertFrom-ToolContent -ToolResult $result
    if ($sent.data.sent -ne $true -or -not $sent.data.messageId) {
        throw 'Mail did not confirm sending with a message ID. Delivery is unconfirmed; check Sent Items before retrying.'
    }
    [pscustomobject]@{
        status = 'sent'
        to = $arguments.to
        cc = $arguments.cc
        bcc = $arguments.bcc
        subject = $Subject
        messageId = $sent.data.messageId
        webLink = $sent.data.webLink
    } | ConvertTo-Json -Depth 10 -Compress
}
finally {
    Stop-AgencyMcp -Connection $mailConnection
    Stop-AgencyMcp -Connection $script:userConnection
}
