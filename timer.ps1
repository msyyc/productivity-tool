# Check if parameters were provided via command line
param(
    [string]$MinutesParam,
    [string]$LinkParam
)

Add-Type -AssemblyName System.Windows.Forms

# Handle timer duration
if ($MinutesParam) {
    # Use command-line parameter
    $minutes = $MinutesParam
    if (-not [int]::TryParse($minutes, [ref]$null)) {
        Write-Host "Invalid input for minutes parameter. Please enter a valid number."
        exit
    }
} else {
    # Prompt user for timer duration in minutes
    $minutes = [Microsoft.VisualBasic.Interaction]::InputBox("Time (minutes) to set:", "Set Timer", "1")
    if (-not [int]::TryParse($minutes, [ref]$null)) {
        [System.Windows.Forms.MessageBox]::Show("Invalid input. Please enter a valid number.")
        exit
    }
    if (-not $minutes) { [System.Windows.Forms.Application]::Exit() }
}

# Convert minutes to seconds
$seconds = [int]$minutes * 60

# Handle hyperlink
if ($LinkParam) {
    # Use command-line parameter
    $link = $LinkParam
} else {
    # Prompt user for hyperlink
    $link = [Microsoft.VisualBasic.Interaction]::InputBox("Enter hyperlink (URL):", "Set Hyperlink", "https://")
    if (-not $link) { [System.Windows.Forms.Application]::Exit() }
}

# Function to check if link is a GitHub PR and extract repo/PR number
function Get-GitHubPRInfo {
    param([string]$url)
    if ($url -match 'https://github\.com/([^/]+/[^/]+)/pull/(\d+)') {
        return @{
            Repo = $matches[1]
            PRNumber = $matches[2]
        }
    }
    return $null
}

# Function to check PR status
function Test-PRMerged {
    param([string]$repo, [string]$prNumber)
    try {
        $state = gh pr view $prNumber --json state --template '{{.state}}' --repo $repo 2>$null
        return $state -eq "MERGED"
    } catch {
        return $false
    }
}

# Function to check CI status
function Get-CIStatus {
    param([string]$repo, [string]$prNumber)
    try {
        $checksJson = gh pr checks $prNumber --repo $repo --json name,state 2>$null
        if (-not $checksJson) { return "UNKNOWN" }
        $checks = $checksJson | ConvertFrom-Json
        if (-not $checks -or $checks.Count -eq 0) { return "UNKNOWN" }
        
        # If PR is in Azure/azure-rest-api-specs, only watch the specific CI item
        if ($repo -eq "Azure/azure-rest-api-specs") {
            $checks = @($checks | Where-Object { $_.name -eq "SDK Validation - Python" })
            # If the target check isn't present yet, treat as in progress
            if (-not $checks -or $checks.Count -eq 0) { return "IN_PROGRESS" }
        }
        
        # Check if any failed
        foreach ($check in $checks) {
            if ($check.state -eq "FAILURE") {
                return "FAILURE"
            }
        }
        
        # Check if all are SUCCESS or NEUTRAL
        $allComplete = $true
        foreach ($check in $checks) {
            if ($check.state -notin @("SUCCESS", "NEUTRAL")) {
                $allComplete = $false
                break
            }
        }
        if ($allComplete) {
            return "ALL_COMPLETE"
        }
        
        return "IN_PROGRESS"
    } catch {
        return "UNKNOWN"
    }
}

# Check if link is a GitHub PR
$prInfo = Get-GitHubPRInfo -url $link
$checkIntervalSeconds = 300  # 5 minutes

if ($prInfo) {
    Write-Host "Detected GitHub PR: $($prInfo.Repo) #$($prInfo.PRNumber)"
    Write-Host "Will check PR status every 5 minutes..."
    
    $startTime = Get-Date
    $endTime = $startTime.AddSeconds($seconds)
    
    while ((Get-Date) -lt $endTime) {
        # Check if PR is merged
        Write-Host "Checking PR status..."
        if (Test-PRMerged -repo $prInfo.Repo -prNumber $prInfo.PRNumber) {
            Write-Host "PR is MERGED! Showing notification..."
            break
        }
        
        # Check CI status
        $ciStatus = Get-CIStatus -repo $prInfo.Repo -prNumber $prInfo.PRNumber
        Write-Host "CI Status: $ciStatus"
        
        if ($ciStatus -eq "FAILURE") {
            Write-Host "CI has FAILURE! Showing notification..."
            break
        }
        
        # For Azure/azure-rest-api-specs and microsoft/typespec, only exit early on failure, wait for timer otherwise
        # For other repos, exit when all CI checks pass
        if ($ciStatus -eq "ALL_COMPLETE" -and $prInfo.Repo -ne "Azure/azure-rest-api-specs" -and $prInfo.Repo -ne "microsoft/typespec") {
            Write-Host "All CI checks passed! Showing notification..."
            break
        }
        
        # Calculate remaining time
        $remainingSeconds = ($endTime - (Get-Date)).TotalSeconds
        if ($remainingSeconds -le 0) {
            Write-Host "Timer expired. Showing notification..."
            break
        }
        
        # Wait for next check interval or remaining time, whichever is smaller
        $waitSeconds = [Math]::Min($checkIntervalSeconds, $remainingSeconds)
        Write-Host "Next check in $([Math]::Round($waitSeconds / 60, 1)) minutes..."
        Start-Sleep -Seconds $waitSeconds
    }
} else {
    # Not a GitHub PR link, use original behavior
    Start-Sleep -Seconds ([int]$seconds)
}

# Display clickable hyperlink after timer expires
$form = New-Object System.Windows.Forms.Form
$form.Text = "Timer Alert"
$form.Size = New-Object System.Drawing.Size(400,150)
$form.StartPosition = "CenterScreen"

$linkLabel = New-Object System.Windows.Forms.LinkLabel
$linkLabel.Text = $link
$linkLabel.AutoSize = $true
$linkLabel.Location = New-Object System.Drawing.Point(20,50)
$linkLabel.add_Click({ 
    Start-Process $link
    $form.Close()
})

$form.Controls.Add($linkLabel)
$form.TopMost = $true
$form.Add_Load({ $form.TopMost = $true; $form.BringToFront(); $form.Focus(); Start-Sleep -Milliseconds 100; $form.TopMost = $false })
$form.Add_Shown({ $form.TopMost = $true; $form.Show(); $form.BringToFront(); $form.Focus(); $form.TopMost = $false })
$form.add_FormClosed({ [System.Windows.Forms.Application]::Exit() })
[void]$form.ShowDialog()
