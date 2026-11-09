param(
    [switch]$SkipInstall,
    [switch]$SkipTests,
    [switch]$SkipSmoke,
    [switch]$SkipCompanion,
    [switch]$CopyEnv
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $Root "venv\Scripts\python.exe"
$DistExe = Join-Path $Root "dist\AI-Live.exe"
$SourceEnv = Join-Path $Root ".env"
$DistEnv = Join-Path $Root "dist\.env"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message"
}

function Ensure-Venv {
    if (Test-Path $VenvPython) {
        return
    }

    Write-Step "Creating virtual environment"
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        & py -3 -m venv (Join-Path $Root "venv")
    } else {
        & python -m venv (Join-Path $Root "venv")
    }
}

function Get-AILiveDistProcesses {
    if (-not (Test-Path $DistExe)) {
        return @()
    }

    $target = [System.IO.Path]::GetFullPath($DistExe)
    return @(
        Get-Process -Name "AI-Live" -ErrorAction SilentlyContinue | Where-Object {
            try {
                $_.Path -and ([System.IO.Path]::GetFullPath($_.Path) -ieq $target)
            } catch {
                $false
            }
        }
    )
}

function Stop-AILiveDistProcesses {
    $processes = Get-AILiveDistProcesses
    if (-not $processes) {
        return
    }

    Write-Step "Stopping running AI-Live executable processes"
    $processes | Stop-Process -Force
    Start-Sleep -Seconds 2
}

Set-Location $Root

Ensure-Venv

if (-not $SkipInstall) {
    Write-Step "Installing runtime and build dependencies"
    & $VenvPython -m pip install -r requirements.txt
    & $VenvPython -m pip install -r requirements-dev.txt
}

if (-not $SkipTests) {
    Write-Step "Running unit tests"
    & $VenvPython -m unittest discover -s tests
    if ($LASTEXITCODE -ne 0) { throw "Tests failed" }
}

Stop-AILiveDistProcesses

Write-Step "Building one-file Windows executable"
& $VenvPython -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name AI-Live `
    --add-data "assets;assets" `
    ai_live.py

if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

if (-not $SkipCompanion) {
    Write-Step "Building VS Code Project Guide companion"
    Push-Location (Join-Path $Root "vscode-project-guide")
    try {
        & npm ci --ignore-scripts
        if ($LASTEXITCODE -ne 0) { throw "Companion dependency installation failed" }
        & npm test
        if ($LASTEXITCODE -ne 0) { throw "Companion tests failed" }
        & npm run package
        if ($LASTEXITCODE -ne 0) { throw "Companion packaging failed" }
        $CompanionPackage = Get-Content -LiteralPath "package.json" -Raw | ConvertFrom-Json
        $CompanionVsix = "$($CompanionPackage.name)-$($CompanionPackage.version).vsix"
        Copy-Item -LiteralPath $CompanionVsix -Destination (Join-Path $Root "dist") -Force
    } finally { Pop-Location }
}

if (-not (Test-Path $DistExe)) {
    throw "Build completed without producing $DistExe"
}

if ($CopyEnv) {
    if (-not (Test-Path $SourceEnv)) {
        throw "Cannot copy .env because $SourceEnv does not exist."
    }

    Write-Step "Copying .env beside executable"
    Copy-Item -LiteralPath $SourceEnv -Destination $DistEnv -Force
}

if (-not $SkipSmoke) {
    Write-Step "Smoke launching executable"
    $started = Start-Process -FilePath $DistExe -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 15

    $running = Get-AILiveDistProcesses
    if (-not $running) {
        throw "AI-Live.exe was not running after startup wait. Initial PID was $($started.Id)."
    }

    $running | Select-Object Id, ProcessName, Path | Format-Table -AutoSize
    $running | Stop-Process -Force
    Start-Sleep -Seconds 2

    $leftover = Get-AILiveDistProcesses
    if ($leftover) {
        $leftover | Select-Object Id, ProcessName, Path | Format-Table -AutoSize
        throw "AI-Live.exe process still running after smoke cleanup."
    }
}

$artifact = Get-Item $DistExe
$sizeMb = [math]::Round($artifact.Length / 1MB, 2)

Write-Step "Build complete"
Write-Host "Executable: $($artifact.FullName)"
Write-Host "Size: $sizeMb MB"
if ($CopyEnv) {
    Write-Host "Environment file: $DistEnv"
} else {
    Write-Host "Use -CopyEnv to copy .env beside the executable, or set the Azure environment variables before running it."
}
