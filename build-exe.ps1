$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$env:PIP_DISABLE_PIP_VERSION_CHECK = "1"
python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    python -m pip install pyinstaller
}

$distExe = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "dist\Flowz.exe"))
Get-Process -Name "Flowz" -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and ([System.IO.Path]::GetFullPath($_.Path) -eq $distExe) } |
    Stop-Process -Force

$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
python -m PyInstaller `
    --noconsole `
    --onefile `
    --name Flowz `
    --icon "assets\flowz.ico" `
    --add-data "assets\flowz.ico;assets" `
    --hidden-import flowz_ui `
    --clean `
    freeflow_win.py
$pyInstallerExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorActionPreference
if ($pyInstallerExitCode -ne 0) {
    throw "PyInstaller failed with exit code $pyInstallerExitCode."
}

Write-Host "Built: $PSScriptRoot\dist\Flowz.exe"
