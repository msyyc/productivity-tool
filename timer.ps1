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

# Wait for specified seconds
Start-Sleep -Seconds ([int]$seconds)

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
