param(
    [switch]$Build,
    [switch]$StartWithWindows,
    [switch]$Launch
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

if ($Build -or -not (Test-Path -LiteralPath ".\dist\Flowz.exe")) {
    & ".\build-exe.ps1"
}

$sourceExe = Join-Path $PSScriptRoot "dist\Flowz.exe"
$installDir = Join-Path $env:LOCALAPPDATA "Flowz"
$targetExe = Join-Path $installDir "Flowz.exe"
$startMenuDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Flowz"
$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"

New-Item -ItemType Directory -Force -Path $installDir | Out-Null
New-Item -ItemType Directory -Force -Path $startMenuDir | Out-Null

Get-Process -Name "Flowz" -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -eq $targetExe } |
    Stop-Process -Force
Get-Process -Name "FreeFlowWin" -ErrorAction SilentlyContinue | Stop-Process -Force

Copy-Item -LiteralPath $sourceExe -Destination $targetExe -Force

$shell = New-Object -ComObject WScript.Shell
$appShortcut = $shell.CreateShortcut((Join-Path $startMenuDir "Flowz.lnk"))
$appShortcut.TargetPath = $targetExe
$appShortcut.WorkingDirectory = $installDir
$appShortcut.Save()

$settingsShortcut = $shell.CreateShortcut((Join-Path $startMenuDir "Flowz Settings.lnk"))
$settingsShortcut.TargetPath = $targetExe
$settingsShortcut.Arguments = "--settings"
$settingsShortcut.WorkingDirectory = $installDir
$settingsShortcut.Save()

if ($StartWithWindows) {
    New-Item -Path $runKey -Force | Out-Null
    Set-ItemProperty -Path $runKey -Name "Flowz" -Value "`"$targetExe`""
    Remove-ItemProperty -Path $runKey -Name "FreeFlowWin" -ErrorAction SilentlyContinue
}

Write-Host "Installed: $targetExe"
Write-Host "Start Menu: $startMenuDir"
if ($StartWithWindows) {
    Write-Host "Startup: enabled"
}

if ($Launch) {
    Start-Process -FilePath $targetExe
}
