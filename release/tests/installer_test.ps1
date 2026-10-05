# Install the test build of the installer without anyone at the keyboard, check what it put on the PC, uninstall it,
# and check what is left. Build the installer first:
#
#     python release\build_installer.py --test-build
#     powershell -NoProfile -ExecutionPolicy Bypass -File release\tests\installer_test.ps1
#
# The test build has its own name, identifier and folder, so a real install of Skydive Cutter on this PC is not touched.
# By default the downloads are skipped (/NORUNTIME=1) and the test takes under a minute. -Full runs the package's
# setup as well (2 to 5 GB) and then asks the launcher whether everything is in place.
[CmdletBinding()]
param(
    [string]$Installer,
    [switch]$Full
)
$ErrorActionPreference = 'Stop'
$name = 'Skydive Cutter (test build)'
$uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{C4A91F60-0D2E-4B7A-8F35-9A1E7B6C2D58}_is1'
$shortcut = Join-Path ([Environment]::GetFolderPath('Programs')) "$name.lnk"
$failures = New-Object System.Collections.Generic.List[string]

function Check([string]$what, [bool]$passed) {
    if ($passed) { Write-Host "  ok    $what" } else { Write-Host "  FAIL  $what"; $failures.Add($what) }
}

if (-not $Installer) {
    $Installer = Get-ChildItem (Join-Path $PSScriptRoot '..\dist') -Filter 'Skydive-Cutter-*-Setup-test.exe' |
        Sort-Object LastWriteTime | Select-Object -Last 1 -ExpandProperty FullName
}
if (-not $Installer -or -not (Test-Path -LiteralPath $Installer)) {
    throw 'No test installer found. Build one with: python release\build_installer.py --test-build'
}
if (Test-Path $uninstallKey) { throw "$name is already installed. Uninstall it before running this test." }

$work = Join-Path ([IO.Path]::GetTempPath()) ('skydive-cutter-installer-test-' + [Guid]::NewGuid().ToString('N').Substring(0, 8))
$target = Join-Path $work 'Skydive Cutter test'   # a space in the path, as a real install has
New-Item -ItemType Directory -Force $work | Out-Null
Write-Host "Installer: $Installer"
Write-Host "Installing to: $target"

$arguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/DIR=`"$target`"", "/LOG=`"$work\install.log`"")
if (-not $Full) { $arguments += '/NORUNTIME=1' }
$started = Get-Date
$install = Start-Process -FilePath $Installer -ArgumentList $arguments -Wait -PassThru
Check "the installer finished without an error (exit code $($install.ExitCode))" ($install.ExitCode -eq 0)
Write-Host ("  took {0:n0} seconds" -f ((Get-Date) - $started).TotalSeconds)

$listing = Join-Path $target 'PACKAGE_FILES.json'
Check 'the list of package files is installed' (Test-Path -LiteralPath $listing)
if (Test-Path -LiteralPath $listing) {
    $expected = (Get-Content -LiteralPath $listing -Raw | ConvertFrom-Json).sha256
    $wrong = @()
    foreach ($entry in $expected.PSObject.Properties) {
        $file = Join-Path $target ($entry.Name -replace '/', '\')
        if (-not (Test-Path -LiteralPath $file) -or
            (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ne $entry.Value.ToUpper()) { $wrong += $entry.Name }
    }
    $count = @($expected.PSObject.Properties).Count
    Check "all $count package files are installed unchanged ($($wrong.Count) wrong: $(($wrong | Select-Object -First 5) -join ', '))" ($wrong.Count -eq 0)
}
if (-not $Full) {   # setup's own check of the app writes default settings
    Check 'no settings file is installed' (-not (Test-Path -LiteralPath (Join-Path $target 'app\settings.json')))
}
Check 'the uninstaller is installed' (Test-Path -LiteralPath (Join-Path $target 'unins000.exe'))
Check 'the Start menu shortcut exists' (Test-Path -LiteralPath $shortcut)
if (Test-Path -LiteralPath $shortcut) {
    $link = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcut)
    Check 'the shortcut starts the launcher without a window' ($link.Arguments -like '*-WindowStyle Hidden*Skydive-Cutter.ps1*-Quiet*')
    Check 'the shortcut points into the install folder' ($link.Arguments -like "*$target\Skydive-Cutter.ps1*")
    Check 'the shortcut uses the app icon' ($link.IconLocation -like "$target\skydive-cutter.ico*")
}
Check 'Windows lists it under installed apps' (Test-Path $uninstallKey)
if (Test-Path $uninstallKey) {
    $entry = Get-ItemProperty $uninstallKey
    Check "the listed version matches the package ($($entry.DisplayVersion))" ($Installer -like "*-$($entry.DisplayVersion)-Setup*")
    Check 'it is installed for this user only' ($entry.InstallLocation.TrimEnd('\') -eq $target)
}
if ($Full) {
    Check 'setup recorded what it installed' (Test-Path -LiteralPath (Join-Path $target 'installation.json'))
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $target 'Skydive-Cutter.ps1') -CheckOnly
    Check "the launcher finds everything in place (exit code $LASTEXITCODE)" ($LASTEXITCODE -eq 0)
    # Start it the way the Start menu does and wait for the app's own process to appear.
    Start-Process -FilePath $shortcut
    $app = $null
    foreach ($second in 1..90) {
        $app = Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" |
            Where-Object { $_.ExecutablePath -like "$target\*" } | Select-Object -First 1
        if ($app) { break }
        Start-Sleep -Seconds 1
    }
    Check 'the Start menu shortcut opens the app' ($null -ne $app)
    if ($app) {
        Start-Sleep -Seconds 10   # long enough for the window to be up, or for a crash on start to show
        $alive = Get-Process -Id $app.ProcessId -ErrorAction SilentlyContinue
        Check 'the app is still open ten seconds later' ($null -ne $alive)
        $mark = $null
        $held = [Threading.Mutex]::TryOpenExisting('SkydiveCutterRunning', [ref]$mark)
        Check 'the open app can be seen by an installer' $held
        if ($mark) { $mark.Dispose() }
        if ($alive) { Stop-Process -Id $app.ProcessId -Force; Start-Sleep -Seconds 2 }
    }
} else {
    # Stand-ins for what setup and a first run leave behind, to see what the uninstaller does with them.
    New-Item -ItemType Directory -Force (Join-Path $target '.runtime\cpu'), (Join-Path $target 'cache'), (Join-Path $target 'logs'), (Join-Path $target 'Ultralytics') | Out-Null
    Set-Content -LiteralPath (Join-Path $target '.runtime\cpu\python.exe') -Value 'stand-in'
    Set-Content -LiteralPath (Join-Path $target 'cache\something.bin') -Value 'stand-in'
    Set-Content -LiteralPath (Join-Path $target 'installation.json') -Value '{}'
    Set-Content -LiteralPath (Join-Path $target 'Ultralytics\settings.json') -Value '{}'
    Set-Content -LiteralPath (Join-Path $target 'yolo26x.pt') -Value 'stand-in'
}
Set-Content -LiteralPath (Join-Path $target 'app\settings.json') -Value '{"test": true}'

Write-Host 'Uninstalling'
$uninstall = Start-Process -FilePath (Join-Path $target 'unins000.exe') -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait -PassThru
Check "the uninstaller finished without an error (exit code $($uninstall.ExitCode))" ($uninstall.ExitCode -eq 0)
foreach ($second in 1..60) {   # the uninstaller finishes from a copy of itself, a moment after the first one returns
    if (-not (Test-Path -LiteralPath (Join-Path $target 'unins000.exe')) -and -not (Test-Path $uninstallKey)) { break }
    Start-Sleep -Seconds 1
}
Check 'Windows no longer lists it' (-not (Test-Path $uninstallKey))
Check 'the Start menu shortcut is gone' (-not (Test-Path -LiteralPath $shortcut))
Check 'the downloaded runtime is gone' (-not (Test-Path -LiteralPath (Join-Path $target '.runtime')))
Check 'the cache is gone' (-not (Test-Path -LiteralPath (Join-Path $target 'cache')))
Check 'the app code is gone' (-not (Test-Path -LiteralPath (Join-Path $target 'app\main.py')))
Check 'your settings are kept' (Test-Path -LiteralPath (Join-Path $target 'app\settings.json'))
$left = @(Get-ChildItem -LiteralPath $target -Recurse -File -Force -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName.Substring($target.Length + 1) })
Check "nothing but the settings is left behind ($($left -join ', '))" (($left.Count -eq 1) -and ($left[0] -eq 'app\settings.json'))

if ($failures.Count -eq 0) {
    Remove-Item -LiteralPath $work -Recurse -Force
    Write-Host 'PASS: the installer installs, lists and removes the app correctly.'
    exit 0
}
Write-Host "FAIL: $($failures.Count) check(s) failed. The install log and what is left are in $work"
exit 1
