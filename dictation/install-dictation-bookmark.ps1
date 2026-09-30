[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$PythonPath,
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'
$registryPath = 'Software\Classes\dictation-helper'
$owner = 'productivity-tool/correct-dictation'
$existing = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($registryPath)
try {
    if ($existing -and $existing.GetValue('LauncherOwner') -ne $owner) {
        throw 'dictation-helper is already registered by another application. No changes were made.'
    }
} finally {
    if ($existing) { $existing.Dispose() }
}

if ($Uninstall) {
    if ($PSCmdlet.ShouldProcess('HKCU\' + $registryPath, 'Remove dictation URL handler')) {
        [Microsoft.Win32.Registry]::CurrentUser.DeleteSubKeyTree($registryPath, $false)
        Write-Output 'Removed the dictation URL handler. You can delete the browser bookmark.'
    }
    return
}

$appPath = Join-Path $PSScriptRoot 'correct_dictation.pyw'
$clientPath = Join-Path $PSScriptRoot 'dictation_client.py'
$skillPath = Join-Path (Split-Path $PSScriptRoot -Parent) '.github\skills\correct-dictation\SKILL.md'
foreach ($requiredPath in @($appPath, $clientPath, $skillPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required file not found: $requiredPath"
    }
}

if (-not $PythonPath) {
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        $pythonCommand = Get-Command py.exe -ErrorAction SilentlyContinue
    }
    if (-not $pythonCommand) {
        throw 'Install Python with Tkinter, or pass -PythonPath with the full path to python.exe.'
    }
    $PythonPath = $pythonCommand.Source
}

$runtime = & $PythonPath -c 'import sys, tkinter; root = tkinter.Tk(); root.withdraw(); root.destroy(); print(sys.executable)'
if ($LASTEXITCODE -ne 0 -or -not $runtime) {
    throw 'Python with working Tkinter is required. Pass -PythonPath with the full path to python.exe.'
}
$pythonw = Join-Path (Split-Path ([string]$runtime).Trim()) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw -PathType Leaf)) {
    throw "Windowed Python launcher not found: $pythonw"
}
if (-not (Get-Command copilot.exe -ErrorAction SilentlyContinue)) {
    Write-Warning 'copilot.exe is not on PATH. Install GitHub Copilot CLI and run copilot login before correcting text.'
}

$launchCommand = '"{0}" "{1}"' -f $pythonw, $appPath
if ($PSCmdlet.ShouldProcess('HKCU\' + $registryPath, "Register URL handler: $launchCommand")) {
    $key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey($registryPath)
    try {
        $key.SetValue('', 'URL:Correct Dictation')
        $key.SetValue('URL Protocol', '')
        $key.SetValue('LauncherOwner', $owner)
        $commandKey = $key.CreateSubKey('shell\open\command')
        try {
            $commandKey.SetValue('', $launchCommand)
        } finally {
            $commandKey.Dispose()
        }
    } finally {
        $key.Dispose()
    }
    Write-Output 'Registered for your Windows account. No administrator privileges required.'
    Write-Output 'Add a browser favorite named Correct Dictation with URL: dictation-helper://open'
    Write-Output 'The browser may request confirmation before opening the window.'
}