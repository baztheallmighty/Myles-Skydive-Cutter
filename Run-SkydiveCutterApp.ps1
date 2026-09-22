[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$appPython = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $appPython -PathType Leaf)) {
    throw "Required application Python is missing: $appPython. Use the repository .venv."
}
$env:YOLO_CONFIG_DIR = Join-Path $PSScriptRoot '.ultralytics'
$appLogDirectory = Join-Path $PSScriptRoot 'app\logs'
New-Item -ItemType Directory -Path $appLogDirectory -Force | Out-Null
$appLogStamp = Get-Date -Format 'yyyyMMdd_HHmmss_fff'
$appStdout = Join-Path $appLogDirectory "$appLogStamp.stdout.log"
$appStderr = Join-Path $appLogDirectory "$appLogStamp.stderr.log"
$appProcess = Start-Process -FilePath $appPython -ArgumentList @('-s', '-B', '-m', 'app.main') -WorkingDirectory $PSScriptRoot -WindowStyle Normal -RedirectStandardOutput $appStdout -RedirectStandardError $appStderr -PassThru
Write-Output "Skydive Cutter started (PID $($appProcess.Id)). Startup errors: $appStderr"
