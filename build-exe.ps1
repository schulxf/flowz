$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$env:PIP_DISABLE_PIP_VERSION_CHECK = "1"
python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    python -m pip install pyinstaller
}

$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
python -m PyInstaller `
    --noconsole `
    --onefile `
    --name Flowz `
    --clean `
    freeflow_win.py
$pyInstallerExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorActionPreference
if ($pyInstallerExitCode -ne 0) {
    throw "PyInstaller failed with exit code $pyInstallerExitCode."
}

Write-Host "Built: $PSScriptRoot\dist\Flowz.exe"
