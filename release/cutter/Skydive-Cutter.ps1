[CmdletBinding()]
param(
    [ValidateSet('app', 'review')][string]$Open = 'app',
    [ValidateSet('Auto', 'CPU', 'NVIDIA')][string]$Mode = 'Auto',
    [switch]$Repair,
    [switch]$SkipCheck,
    [switch]$CheckOnly
)
# The only thing you run. It checks what this folder has, installs anything missing, then opens the app.
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath($PSScriptRoot)

function Test-Part {
    param([string]$Name, [scriptblock]$Test)
    if (& $Test) { return $null }
    return $Name
}

function Get-MissingParts {
    $missing = @()
    $installedPath = Join-Path $root 'installation.json'
    if (-not (Test-Path -LiteralPath $installedPath)) { return @('the app runtime') }
    try { $installed = Get-Content -LiteralPath $installedPath -Raw | ConvertFrom-Json }
    catch { return @('the app runtime') }
    $python = Join-Path $root $installed.python
    $pythonw = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
    if (-not (Test-Path -LiteralPath $pythonw)) { return @('the app runtime') }
    $site = Join-Path (Split-Path -Parent $python) 'Lib\site-packages'
    foreach ($package in @('torch', 'torchvision', 'PySide6', 'numpy', 'librosa', 'soundfile', 'sklearn', 'ultralytics')) {
        # A library is a folder for most packages, a single .py file for a few (soundfile).
        $missing += Test-Part "the $package library" {
            (Test-Path -LiteralPath (Join-Path $site $package)) -or
            (Test-Path -LiteralPath (Join-Path $site ($package + '.py')))
        }
    }
    foreach ($tool in @('ffmpeg.exe', 'ffprobe.exe')) {
        $missing += Test-Part "FFmpeg" { Test-Path -LiteralPath (Join-Path $root "bin\$tool") }
    }
    $missing += Test-Part 'the person detection model' { Test-Path -LiteralPath (Join-Path $root 'yolo11n.pt') }
    # Name and size only, never a checksum: this runs on every start and must not read gigabytes.
    $modelsPath = Join-Path $root 'cutter_v4\models\MODELS.json'
    if (Test-Path -LiteralPath $modelsPath) {
        $models = (Get-Content -LiteralPath $modelsPath -Raw | ConvertFrom-Json).models
        foreach ($name in $models.PSObject.Properties.Name) {
            $model = $models.$name
            $file = Join-Path $root ('cutter_v4\models\' + $model.file)
            $missing += Test-Part "the $name model" {
                (Test-Path -LiteralPath $file) -and ((Get-Item -LiteralPath $file).Length -eq $model.bytes)
            }
        }
    } else {
        $missing += 'the jump phase models'
    }
    return @($missing | Where-Object { $_ } | Select-Object -Unique)
}

$missing = if ($SkipCheck) { @() } else { Get-MissingParts }
if ($CheckOnly) {
    if ($missing.Count -eq 0) { Write-Host 'Everything this app needs is installed.'; exit 0 }
    Write-Host 'Missing:'
    foreach ($item in $missing) { Write-Host "  - $item" }
    exit 1
}
if ($Repair -or $missing.Count -gt 0) {
    if ($missing.Count -gt 0 -and -not $Repair) {
        Write-Host ''
        Write-Host 'Skydive Cutter needs a few things before it can start:' -ForegroundColor Yellow
        foreach ($item in $missing) { Write-Host "  - $item" }
        Write-Host 'Installing them now. This is a one-time download; leave this window open.'
    }
    & (Join-Path $root 'Setup.ps1') -Mode $Mode -Repair:$Repair
    $missing = Get-MissingParts
    if ($missing.Count -gt 0) {
        throw ('Setup finished but these are still missing: ' + ($missing -join ', ') +
               '. Run Repair.cmd, or see the logs folder.')
    }
}

$installed = Get-Content -LiteralPath (Join-Path $root 'installation.json') -Raw | ConvertFrom-Json
$python = Join-Path $root $installed.python
$pythonw = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
foreach ($name in 'numba', 'matplotlib', 'torch', 'ultralytics') {
    New-Item -ItemType Directory -Force (Join-Path $root "cache\$name") | Out-Null
}
$env:NUMBA_CACHE_DIR = Join-Path $root 'cache\numba'
$env:MPLCONFIGDIR = Join-Path $root 'cache\matplotlib'
$env:TORCH_HOME = Join-Path $root 'cache\torch'
$env:YOLO_CONFIG_DIR = Join-Path $root 'cache\ultralytics'
$env:PYTHONDONTWRITEBYTECODE = '1'
$logs = Join-Path $root 'logs'
New-Item -ItemType Directory -Force $logs | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$arguments = @('-s', '-B', '-m', 'app.main')
if ($Open -eq 'review') { $arguments += '--review' }
Start-Process -FilePath $pythonw -ArgumentList $arguments -WorkingDirectory $root `
    -RedirectStandardOutput (Join-Path $logs "app-$stamp.stdout.log") `
    -RedirectStandardError (Join-Path $logs "app-$stamp.stderr.log") | Out-Null
Write-Host "Skydive Cutter started. If no window appears, see logs\app-$stamp.stderr.log"
