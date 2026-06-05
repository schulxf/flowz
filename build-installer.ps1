param(
    [string]$Version = "0.1.0",
    [switch]$BuildExe,
    [switch]$ZipOnly
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$distExe = Join-Path $PSScriptRoot "dist\Flowz.exe"
$releaseDir = Join-Path $PSScriptRoot "release"
$issPath = Join-Path $PSScriptRoot "packaging\flowz.iss"

if ($BuildExe -or -not (Test-Path -LiteralPath $distExe)) {
    & (Join-Path $PSScriptRoot "build-exe.ps1")
}

if (-not (Test-Path -LiteralPath $distExe)) {
    throw "Missing $distExe. Run .\build-exe.ps1 first."
}

New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null

function Get-InnoSetupCompiler {
    $candidates = @()

    if ($env:ISCC_PATH) {
        $candidates += $env:ISCC_PATH
    }

    $command = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
    if ($command) {
        $candidates += $command.Source
    }

    $candidates += @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 5\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 5\ISCC.exe"
    )

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }

    return $null
}

function New-ZipPackage {
    param(
        [Parameter(Mandatory)]
        [string]$PackageVersion
    )

    $safeVersion = $PackageVersion -replace '[^\w\.-]', '-'
    $stagingRoot = Join-Path $PSScriptRoot "build\installer-package"
    $stagingDir = Join-Path $stagingRoot "Flowz-$safeVersion"
    $stagingDist = Join-Path $stagingDir "dist"
    $zipPath = Join-Path $releaseDir "FlowzPackage-$safeVersion.zip"

    $resolvedBuildDir = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "build"))
    $resolvedStagingRoot = [System.IO.Path]::GetFullPath($stagingRoot)
    if (-not $resolvedStagingRoot.StartsWith($resolvedBuildDir, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean unexpected staging path: $resolvedStagingRoot"
    }

    Remove-Item -LiteralPath $stagingRoot -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $stagingDist | Out-Null

    Copy-Item -LiteralPath $distExe -Destination (Join-Path $stagingDist "Flowz.exe") -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "install.ps1") -Destination $stagingDir -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "uninstall.ps1") -Destination $stagingDir -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "README.md") -Destination $stagingDir -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "config.example.json") -Destination $stagingDir -Force

    if (Test-Path -LiteralPath $zipPath) {
        Remove-Item -LiteralPath $zipPath -Force
    }

    Compress-Archive -LiteralPath $stagingDir -DestinationPath $zipPath -Force
    return $zipPath
}

function Get-IExpressPackager {
    $candidates = @(
        "$env:WINDIR\System32\iexpress.exe",
        "$env:WINDIR\SysWOW64\iexpress.exe"
    )

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }

    return $null
}

function New-IExpressPackage {
    param(
        [Parameter(Mandatory)]
        [string]$PackageVersion
    )

    $safeVersion = $PackageVersion -replace '[^\w\.-]', '-'
    $stagingRoot = Join-Path $PSScriptRoot "build\iexpress-package"
    $stagingDir = Join-Path $stagingRoot "Flowz-$safeVersion"
    $setupPath = Join-Path $releaseDir "FlowzSetup-$safeVersion.exe"
    $sedPath = Join-Path $stagingRoot "flowz-iexpress.sed"

    $resolvedBuildDir = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "build"))
    $resolvedStagingRoot = [System.IO.Path]::GetFullPath($stagingRoot)
    if (-not $resolvedStagingRoot.StartsWith($resolvedBuildDir, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean unexpected staging path: $resolvedStagingRoot"
    }

    Remove-Item -LiteralPath $stagingRoot -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $stagingDir | Out-Null

    Copy-Item -LiteralPath $distExe -Destination (Join-Path $stagingDir "Flowz.exe") -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "README.md") -Destination $stagingDir -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "config.example.json") -Destination $stagingDir -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "uninstall.ps1") -Destination $stagingDir -Force

    $installScript = @'
$ErrorActionPreference = "Stop"

$sourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$sourceExe = Join-Path $sourceDir "Flowz.exe"
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
Copy-Item -LiteralPath (Join-Path $sourceDir "README.md") -Destination $installDir -Force -ErrorAction SilentlyContinue
Copy-Item -LiteralPath (Join-Path $sourceDir "config.example.json") -Destination $installDir -Force -ErrorAction SilentlyContinue
Copy-Item -LiteralPath (Join-Path $sourceDir "uninstall.ps1") -Destination $installDir -Force -ErrorAction SilentlyContinue

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

New-Item -Path $runKey -Force | Out-Null
Remove-ItemProperty -Path $runKey -Name "FreeFlowWin" -ErrorAction SilentlyContinue

Write-Host "Installed Flowz to $targetExe"
'@
    $installScript | Set-Content -LiteralPath (Join-Path $stagingDir "install-iexpress.ps1") -Encoding UTF8

    $targetName = $setupPath
    $sourceDir = $stagingDir
    $sed = @"
[Version]
Class=IEXPRESS
SEDVersion=3

[Options]
PackagePurpose=InstallApp
ShowInstallProgramWindow=1
HideExtractAnimation=1
UseLongFileName=1
InsideCompressed=0
CAB_FixedSize=0
CAB_ResvCodeSigning=0
RebootMode=N
InstallPrompt=
DisplayLicense=
FinishMessage=
TargetName=%TargetName%
FriendlyName=%FriendlyName%
AppLaunched=%AppLaunched%
PostInstallCmd=<None>
AdminQuietInstCmd=%AppLaunched%
UserQuietInstCmd=%AppLaunched%
SourceFiles=SourceFiles

[SourceFiles]
SourceFiles0=%SourceDir%

[SourceFiles0]
%FILE0%=
%FILE1%=
%FILE2%=
%FILE3%=
%FILE4%=

[Strings]
TargetName=$targetName
FriendlyName=Flowz Setup
AppLaunched=powershell.exe -NoProfile -ExecutionPolicy Bypass -File install-iexpress.ps1
SourceDir=$sourceDir
FILE0="Flowz.exe"
FILE1="install-iexpress.ps1"
FILE2="README.md"
FILE3="config.example.json"
FILE4="uninstall.ps1"
"@

    $sed | Set-Content -LiteralPath $sedPath -Encoding ASCII

    if (Test-Path -LiteralPath $setupPath) {
        Remove-Item -LiteralPath $setupPath -Force
    }

    $iexpress = Get-IExpressPackager
    if (-not $iexpress) {
        throw "iexpress.exe was not found."
    }

    & $iexpress /N /Q $sedPath

    $deadline = (Get-Date).AddSeconds(45)
    while (-not (Test-Path -LiteralPath $setupPath) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 200
    }

    if (-not (Test-Path -LiteralPath $setupPath)) {
        throw "IExpress completed but did not create $setupPath"
    }

    return $setupPath
}

$iscc = Get-InnoSetupCompiler

if ($iscc -and -not $ZipOnly) {
    Write-Host "Using Inno Setup compiler: $iscc"
    & $iscc "/DAppVersion=$Version" $issPath

    $safeVersion = $Version -replace '[^\w\.-]', '-'
    $setupPath = Join-Path $releaseDir "FlowzSetup-$safeVersion.exe"
    if (Test-Path -LiteralPath $setupPath) {
        Write-Host "Built installer: $setupPath"
    }
    else {
        Write-Host "Inno Setup completed. Check output directory: $releaseDir"
    }
}
else {
    if ($ZipOnly) {
        Write-Host "ZipOnly requested; skipping Inno Setup."
        $zipPath = New-ZipPackage -PackageVersion $Version
        Write-Host "Built ZIP package: $zipPath"
    }
    else {
        $iexpress = Get-IExpressPackager
        if ($iexpress) {
            Write-Host "ISCC.exe was not found; creating IExpress installer fallback."
            $setupPath = New-IExpressPackage -PackageVersion $Version
            Write-Host "Built installer: $setupPath"
        }
        else {
            Write-Host "ISCC.exe and iexpress.exe were not found; creating ZIP package fallback."
            $zipPath = New-ZipPackage -PackageVersion $Version
            Write-Host "Built ZIP package: $zipPath"
        }
    }
}
