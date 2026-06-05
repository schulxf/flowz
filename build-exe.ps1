$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

python -m pip install pyinstaller

python -m PyInstaller `
    --noconsole `
    --onefile `
    --name Flowz `
    --clean `
    freeflow_win.py

Write-Host "Built: $PSScriptRoot\dist\Flowz.exe"
