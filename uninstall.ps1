param(
    [switch]$RemoveConfig
)

$ErrorActionPreference = "Stop"

$installDir = Join-Path $env:LOCALAPPDATA "Flowz"
$targetExe = Join-Path $installDir "Flowz.exe"
$startMenuDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Flowz"
$configDir = Join-Path $env:APPDATA "Flowz"
$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"

Get-Process -Name "Flowz" -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -eq $targetExe } |
    Stop-Process -Force
Get-Process -Name "FreeFlowWin" -ErrorAction SilentlyContinue | Stop-Process -Force

Remove-ItemProperty -Path $runKey -Name "Flowz" -ErrorAction SilentlyContinue
Remove-ItemProperty -Path $runKey -Name "FreeFlowWin" -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $startMenuDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $installDir -Recurse -Force -ErrorAction SilentlyContinue

if ($RemoveConfig) {
    Remove-Item -LiteralPath $configDir -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "Uninstalled Flowz."
if (-not $RemoveConfig) {
    Write-Host "Config preserved: $configDir"
}
