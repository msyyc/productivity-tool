[CmdletBinding()]
param(
    [string]$GithubAlias,
    [string]$CachePath = (Join-Path $PSScriptRoot 'identity.json'),
    [switch]$Refresh,
    [string]$EvidenceEmail,
    [string]$EvidenceUrl
)

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\..\common\agency-mcp.ps1"

function Invoke-GithubIdentityApi {
    param([string]$Endpoint)
    $output = & gh api $Endpoint
    if ($LASTEXITCODE -ne 0) {
        throw "GitHub lookup failed for '$Endpoint' (exit $LASTEXITCODE). Check gh authentication/access."
    }
    return ($output -join "`n") | ConvertFrom-Json
}

function Find-DirectoryIdentity {
    param([string]$Property, [string[]]$Values)
    $connection = $null
    try {
        $connection = Start-AgencyMcp -Server 'm365-user' -ClientName 'github-alias-to-teams-alias'
        $result = Invoke-McpTool -BaseUrl $connection.BaseUrl -Name 'GetMultipleUsersDetails' -Arguments @{
            propertyToSearchBy = $Property
            searchValues = $Values
            select = 'displayName,mail'
            top = 50
        }
        $payload = ConvertFrom-ToolContent -ToolResult $result
        if ($null -eq $payload.value) {
            throw 'Directory lookup returned no value collection.'
        }
        if (@($payload.value).Count -ge 50) {
            throw 'Directory lookup reached its result limit; narrow the search before selecting an identity.'
        }
        return @($payload.value)
    }
    finally {
        Stop-AgencyMcp -Connection $connection
    }
}

function Test-WorkEmail {
    param([string]$Email)
    return $Email -match '^[^@\s]+@microsoft\.com$'
}

function Assert-IdentityCache {
    param($Cache)
    if ($Cache -isnot [System.Collections.IDictionary] -or $Cache.schemaVersion -notin @(1, 2) -or
        $Cache.entries -isnot [System.Collections.IDictionary]) {
        throw 'Invalid identity cache schema. Preserve the file and repair it before retrying.'
    }
    foreach ($key in $Cache.entries.Keys) {
        $entry = $Cache.entries[$key]
        if ($Cache.schemaVersion -eq 2) {
            if ($entry -isnot [System.Collections.IDictionary] -or $entry.Count -ne 3 -or
                $key -cnotmatch '^[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?$' -or $key.Contains('--') -or
                $entry.githubAlias -cne $key -or
                $entry.teamsAlias -isnot [string] -or [string]::IsNullOrWhiteSpace($entry.teamsAlias) -or
                -not (Test-WorkEmail $entry.emailAddress)) {
                throw "Invalid identity cache entry '$key'."
            }
            continue
        }
        if ($entry -isnot [System.Collections.IDictionary] -or
            $key -notmatch '^[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?$' -or
            $entry.githubLogin -cne $key -or
            $entry.status -notin @('corroborated', 'candidate', 'ambiguous', 'not_found') -or
            -not $entry.checkedAt) {
            throw "Invalid identity cache entry '$key'."
        }
        # ConvertFrom-Json may deserialize ISO timestamps into local DateTime values.
        $entry.checkedAt = ([DateTimeOffset]$entry.checkedAt).ToUniversalTime().ToString('o')
        if ($entry.status -eq 'corroborated' -and (
            -not (Test-WorkEmail $entry.identity.mail) -or -not $entry.identity.displayName -or
            -not $entry.identity.userPrincipalName -or -not $entry.identity.mailNickname -or
            -not $entry.evidence -or -not $entry.githubId)) {
            throw "Incomplete corroborated identity cache entry '$key'."
        }
    }
}

function Get-LiveGithubIdentity {
    param([string]$Login, [string]$EvidenceEmail, [string]$EvidenceUrl)
    $profile = Invoke-GithubIdentityApi -Endpoint "users/$Login"
    if (-not $profile.id -or $profile.login -ine $Login) {
        throw 'GitHub returned an unexpected user profile.'
    }
    $evidence = [System.Collections.Generic.List[object]]::new()
    if ($EvidenceEmail) {
        $evidence.Add(@{ kind = 'explicit_mapping'; email = $EvidenceEmail; url = $EvidenceUrl })
    }
    if (Test-WorkEmail $profile.email) {
        $evidence.Add(@{
            kind = 'github_profile'
            email = $profile.email
            url = "https://github.com/$Login"
        })
    }
    if ($evidence.Count -eq 0) {
        $commits = Invoke-GithubIdentityApi -Endpoint "search/commits?q=author%3A${Login}&sort=author-date&order=desc&per_page=5"
        if ($null -eq $commits.items -or $commits.incomplete_results) {
            throw 'GitHub commit search returned missing or incomplete results; no identity was saved.'
        }
        foreach ($commit in $commits.items) {
            if ($commit.author.login -ieq $Login -and (Test-WorkEmail $commit.commit.author.email)) {
                $evidence.Add(@{
                    kind = 'github_commit'
                    email = $commit.commit.author.email
                    url = $commit.html_url
                })
            }
        }
    }
    $emails = @($evidence | ForEach-Object { $_.email.ToLowerInvariant() } | Sort-Object -Unique)
    $users = @()
    $status = 'not_found'
    if ($emails.Count) {
        $users = @(Find-DirectoryIdentity -Property 'mail' -Values $emails |
            Where-Object { $_.mail -and $_.mail.ToLowerInvariant() -in $emails })
        if ($users.Count -gt 1 -or $emails.Count -gt 1) {
            $status = 'ambiguous'
        }
        elseif ($users.Count -eq 1) {
            $status = 'candidate'
            if (-not [string]::IsNullOrWhiteSpace($users[0].displayName)) {
                $status = 'corroborated'
            }
        }
    }
    elseif ($profile.name) {
        $users = @(Find-DirectoryIdentity -Property 'displayName' -Values @($profile.name) |
            Where-Object { $_.displayName -ieq $profile.name })
        if ($users.Count -eq 1) { $status = 'candidate' }
        elseif ($users.Count -gt 1) { $status = 'ambiguous' }
    }
    $identities = @($users | ForEach-Object {
        @{
            displayName = $_.displayName
            mail = $_.mail
        }
    })
    return @{
        githubLogin = $Login
        githubId = $profile.id
        status = $status
        checkedAt = [DateTimeOffset]::UtcNow.ToString('o')
        identity = $(if ($status -eq 'corroborated') { $identities[0] } else { $null })
        candidates = $identities
        evidence = @($evidence.ToArray())
    }
}

function Invoke-GithubTeamsLookup {
    param(
        [string]$GithubAlias,
        [string]$CachePath,
        [switch]$Refresh,
        [string]$EvidenceEmail,
        [string]$EvidenceUrl
    )
    $login = $GithubAlias.Trim().ToLowerInvariant()
    if ($login -notmatch '^[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?$' -or $login.Contains('--')) {
        throw 'Provide a GitHub username, not a URL or email address.'
    }
    if ([bool]$EvidenceEmail -ne [bool]$EvidenceUrl) {
        throw 'EvidenceEmail and EvidenceUrl must be provided together.'
    }
    if ($EvidenceEmail) {
        $uri = $null
        if (-not (Test-WorkEmail $EvidenceEmail) -or
            -not [Uri]::TryCreate($EvidenceUrl, [UriKind]::Absolute, [ref]$uri) -or
            $uri.Scheme -ne 'https') {
            throw 'Explicit mapping evidence requires a Microsoft work email and an HTTPS source URL.'
        }
    }
    $path = [IO.Path]::GetFullPath($CachePath)
    $null = [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($path))
    $lock = $null
    $temporary = $null
    try {
        try {
            $lock = [IO.File]::Open("$path.lock", [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
        }
        catch [IO.IOException] {
            throw "Cannot lock identity cache '$path'. Another lookup may be running. $($_.Exception.Message)"
        }
        $cache = @{ schemaVersion = 2; entries = @{} }
        if (Test-Path -LiteralPath $path) {
            $cache = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json -AsHashtable
            Assert-IdentityCache $cache
        }
        $migrated = $cache.schemaVersion -eq 1
        if ($migrated) {
            $entries = @{}
            foreach ($key in $cache.entries.Keys) {
                $old = $cache.entries[$key]
                if ($old.status -eq 'corroborated') {
                    $entries[$key] = @{
                        githubAlias = $key
                        teamsAlias = $old.identity.displayName
                        emailAddress = $old.identity.mail
                    }
                }
                else {
                    Write-Warning "Removed unresolved legacy cache entry '$key'; it will be searched again when requested."
                }
            }
            $cache = @{ schemaVersion = 2; entries = $entries }
            Assert-IdentityCache $cache
        }
        $cached = $cache.entries[$login]
        $source = 'lookup'
        if ($cached -and -not $Refresh -and -not $EvidenceEmail) {
            $source = 'cache'
            $record = @{
                githubLogin = $login
                status = 'corroborated'
                identity = @{ displayName = $cached.teamsAlias; mail = $cached.emailAddress }
            }
            if (-not $migrated) {
                return @{ source = $source; cachePath = $path; record = $record }
            }
        }
        else {
            $record = Get-LiveGithubIdentity -Login $login -EvidenceEmail $EvidenceEmail -EvidenceUrl $EvidenceUrl
            if ($record.status -eq 'corroborated') {
                $cache.entries[$login] = @{
                    githubAlias = $login
                    teamsAlias = $record.identity.displayName
                    emailAddress = $record.identity.mail
                }
            }
            else {
                # A completed refresh that no longer corroborates an identity invalidates the old match.
                $null = $cache.entries.Remove($login)
            }
        }
        Assert-IdentityCache $cache
        $temporary = "$path.$([Guid]::NewGuid().ToString('N')).tmp"
        $cache | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $temporary -Encoding utf8
        [IO.File]::Move($temporary, $path, $true)
        return @{ source = $source; cachePath = $path; record = $record }
    }
    finally {
        if ($temporary -and (Test-Path -LiteralPath $temporary)) {
            Remove-Item -LiteralPath $temporary
        }
        if ($lock) { $lock.Dispose() }
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    Invoke-GithubTeamsLookup -GithubAlias $GithubAlias -CachePath $CachePath -Refresh:$Refresh `
        -EvidenceEmail $EvidenceEmail -EvidenceUrl $EvidenceUrl | ConvertTo-Json -Depth 20
}
