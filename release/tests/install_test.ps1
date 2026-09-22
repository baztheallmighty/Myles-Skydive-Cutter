<#
.SYNOPSIS
What a stranger gets: extract the ZIP, run it once, and check the install behaves.

.DESCRIPTION
Run this on a machine that has never had the app. It extracts the release ZIP into a fresh folder, lets the launcher
install everything, then checks the health check's answers, the repair path, and that a missing piece is reported
rather than ignored. Nothing here touches a model's accuracy; it is about the install and the launcher.

    powershell -ExecutionPolicy Bypass -File install_test.ps1 -Zip <path to the zip> -Folder <empty folder>
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Zip,
    [Parameter(Mandatory = $true)][string]$Folder,
    [ValidateSet('Auto', 'CPU', 'NVIDIA')][string]$Mode = 'Auto',
    [switch]$KeepFolder
)

$ErrorActionPreference = 'Stop'
$results = [ordered]@{}
$failures = @()

function Check([string]$name, [scriptblock]$test) {
    try {
        $value = & $test
        $results[$name] = $value
        if ($value -is [bool] -and -not $value) {
            $script:failures += $name
            Write-Host "  FAILED  $name" -ForegroundColor Red
        } else {
            Write-Host "  ok      $name : $value"
        }
    } catch {
        $script:failures += $name
        $results[$name] = "error: $_"
        Write-Host "  FAILED  $name : $_" -ForegroundColor Red
    }
}

if (Test-Path $Folder) { Remove-Item $Folder -Recurse -Force }
New-Item -ItemType Directory -Path $Folder -Force | Out-Null
$Folder = (Resolve-Path $Folder).Path

Write-Host "Extracting $Zip into $Folder"
Expand-Archive -LiteralPath $Zip -DestinationPath $Folder -Force
$root = (Get-ChildItem $Folder -Directory | Select-Object -First 1).FullName
Write-Host "Package root: $root"

Write-Host ''
Write-Host 'Before setup' -ForegroundColor Cyan
Check 'the launcher is the only thing to run' {
    (Get-ChildItem $root -Filter *.cmd | Measure-Object).Count -le 2
}
Check 'no runtime is shipped' { -not (Test-Path (Join-Path $root '.runtime')) }
Check 'no person detector is shipped' { -not (Test-Path (Join-Path $root 'yolo11n.pt')) }
Check 'the health check reports an unusable install' {
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'Skydive-Cutter.ps1') -CheckOnly | Out-Null
    $LASTEXITCODE -ne 0
}

Write-Host ''
Write-Host 'Installing (this downloads several GB the first time)' -ForegroundColor Cyan
$began = Get-Date
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'Setup.ps1') -Mode $Mode
$setupSeconds = [math]::Round(((Get-Date) - $began).TotalSeconds)
Check 'setup finished' { $LASTEXITCODE -eq 0 }
$results['setup seconds'] = $setupSeconds

Write-Host ''
Write-Host 'After setup' -ForegroundColor Cyan
Check 'the person detector was installed with everything else' { Test-Path (Join-Path $root 'yolo11n.pt') }
Check 'the install check passes' {
    $installed = Get-Content (Join-Path $root 'installation.json') -Raw | ConvertFrom-Json
    $python = Join-Path $root $installed.python
    & $python -s -B (Join-Path $root 'verify_install.py') --device $installed.device | Out-Null
    $LASTEXITCODE -eq 0
}
Check 'a healthy install starts without reinstalling' {
    $began = Get-Date
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'Skydive-Cutter.ps1') -CheckOnly | Out-Null
    $seconds = ((Get-Date) - $began).TotalSeconds
    $results['health check seconds'] = [math]::Round($seconds, 2)
    ($LASTEXITCODE -eq 0) -and ($seconds -lt 10)
}

Write-Host ''
Write-Host 'When something goes missing' -ForegroundColor Cyan
$weights = Join-Path $root 'yolo11n.pt'
Move-Item $weights "$weights.hidden"
Check 'a missing detector is named, not ignored' {
    $output = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'Skydive-Cutter.ps1') -CheckOnly
    ($LASTEXITCODE -ne 0) -and ($output -join ' ') -match 'person detection model'
}
Check 'the app itself refuses to process without it' {
    $installed = Get-Content (Join-Path $root 'installation.json') -Raw | ConvertFrom-Json
    $python = Join-Path $root $installed.python
    $probe = @'
import json, sys
from app.health import blocking, check_install
from app.settings import Settings
stoppers = blocking(check_install(Settings(), cuda_available=False))
print(json.dumps([c.key for c in stoppers]))
'@
    $probe | Out-File -Encoding utf8 (Join-Path $root 'health_probe.py')
    $answer = & $python -s -B (Join-Path $root 'health_probe.py')
    Remove-Item (Join-Path $root 'health_probe.py')
    $answer -match 'people'
}
Move-Item "$weights.hidden" $weights
Check 'putting it back clears the problem' {
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'Skydive-Cutter.ps1') -CheckOnly | Out-Null
    $LASTEXITCODE -eq 0
}

Write-Host ''
Write-Host 'Repairing' -ForegroundColor Cyan
Check 'the setup log holds what pip printed' {
    $log = Get-ChildItem (Join-Path $root 'logs') -Filter 'setup-*.log' | Sort-Object LastWriteTime | Select-Object -Last 1
    (Get-Content $log.FullName -Raw) -match 'Successfully installed'
}
Check 'Repair.cmd passes on what is typed after it' {
    (Get-Content (Join-Path $root 'Repair.cmd') -Raw) -match '-Repair %\*'
}
$installed = Get-Content (Join-Path $root 'installation.json') -Raw | ConvertFrom-Json
$python = Join-Path $root $installed.python
$damaged = Join-Path (Split-Path -Parent $python) 'Lib\site-packages\numpy\__init__.py'
Remove-Item $damaged
Check 'a damaged library is noticed' {
    $ErrorActionPreference = 'Continue'   # Python's traceback on stderr is the expected result, not a failure
    & $python -s -B -c 'import numpy' 2>&1 | Out-Null
    $LASTEXITCODE -ne 0
}
$began = Get-Date
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'Setup.ps1') -Mode $Mode -Repair
$results['repair seconds'] = [math]::Round(((Get-Date) - $began).TotalSeconds)
Check 'repair puts it back' { ($LASTEXITCODE -eq 0) -and (Test-Path $damaged) }
Check 'the install check passes after repair' {
    $installed = Get-Content (Join-Path $root 'installation.json') -Raw | ConvertFrom-Json
    & (Join-Path $root $installed.python) -s -B (Join-Path $root 'verify_install.py') --device $installed.device | Out-Null
    $LASTEXITCODE -eq 0
}

Write-Host ''
if ($failures.Count) {
    Write-Host ("FAILED: " + ($failures -join ', ')) -ForegroundColor Red
} else {
    Write-Host "All install checks passed (setup took $setupSeconds s)." -ForegroundColor Green
}
$results | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $Folder 'install_test.json') -Encoding UTF8
Write-Host "Results: $(Join-Path $Folder 'install_test.json')"
if (-not $KeepFolder -and $failures.Count -eq 0) { Write-Host "Folder kept at $Folder for inspection." }
exit $failures.Count
