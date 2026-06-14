param(
    [switch]$SkipInstall,
    [switch]$SkipTests,
    [switch]$SkipSmoke,
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
    $started = Start-Process -FilePath $DistExe -PassThru
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
