param(
    [switch]$NoBundleFFmpeg,
    [switch]$RequireBundledFFmpeg
)

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
$pyInstallerArgs = @(
    "--noconsole",
    "--onefile",
    "--name", "Flowz",
    "--icon", "assets\flowz.ico",
    "--add-data", "assets\flowz.ico;assets",
    "--hidden-import", "flowz_ui",
    "--clean"
)

if (-not $NoBundleFFmpeg) {
    $ffmpeg = Get-Command "ffmpeg.exe" -ErrorAction SilentlyContinue
    if ($ffmpeg -and $ffmpeg.Source -and (Test-Path -LiteralPath $ffmpeg.Source)) {
        Write-Host "Bundling FFmpeg: $($ffmpeg.Source)"
        $pyInstallerArgs += @("--add-binary", "$($ffmpeg.Source);ffmpeg")
    }
    elseif ($RequireBundledFFmpeg) {
        throw "FFmpeg was not found on PATH. Install FFmpeg or rerun without -RequireBundledFFmpeg."
    }
    else {
        Write-Warning "FFmpeg was not found on PATH; packaged app will require ffmpeg_path or PATH configuration."
    }
}

$pyInstallerArgs += "freeflow_win.py"
python -m PyInstaller @pyInstallerArgs
$pyInstallerExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorActionPreference
if ($pyInstallerExitCode -ne 0) {
    throw "PyInstaller failed with exit code $pyInstallerExitCode."
}

Write-Host "Built: $PSScriptRoot\dist\Flowz.exe"
