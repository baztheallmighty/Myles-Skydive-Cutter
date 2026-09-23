<#
.SYNOPSIS
Run the install test on a genuinely clean Windows: Windows Sandbox.

.DESCRIPTION
A development PC is never a clean machine: it already has the Visual C++ runtimes, drivers, Python and whatever else
earlier work installed, so an install test there can pass for reasons a stranger's PC will not share. Windows Sandbox
starts from a fresh copy of Windows every time and throws it away afterwards.

This writes a Sandbox configuration that maps the release ZIP in read-only and a results folder read-write, then runs
install_test.ps1 inside it in processor mode (the Sandbox has no NVIDIA driver). Results and the setup logs land in
the results folder. Close the Sandbox window when it says it has finished.

Needs Windows 10/11 Pro or Enterprise with the "Windows Sandbox" feature switched on (Turn Windows features on or off;
this needs an administrator and a restart, so it is left to you).

    powershell -ExecutionPolicy Bypass -File release\tests\Start-SandboxInstallTest.ps1 -Zip release\dist\Skydive-Cutter-2.4.2-windows.zip
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Zip,
    [string]$Results = (Join-Path $PSScriptRoot '..\..\build\sandbox-results')
)
$ErrorActionPreference = 'Stop'
$sandbox = Join-Path $env:WINDIR 'System32\WindowsSandbox.exe'
if (-not (Test-Path $sandbox)) {
    throw 'Windows Sandbox is not switched on. Turn Windows features on or off > Windows Sandbox, restart, and run this again.'
}
$zipPath = (Resolve-Path $Zip).Path
New-Item -ItemType Directory -Force $Results | Out-Null
$resultsPath = (Resolve-Path $Results).Path
$testsPath = (Resolve-Path $PSScriptRoot).Path
$zipName = Split-Path -Leaf $zipPath

# Inside the Sandbox: run the same install test a stranger's PC gets, then copy what it learned out.
$inside = @"
`$ErrorActionPreference = 'Continue'
Start-Transcript -Path C:\results\sandbox-console.log | Out-Null
& powershell -NoProfile -ExecutionPolicy Bypass -File C:\tests\install_test.ps1 -Zip 'C:\zip\$zipName' -Folder C:\SkydiveCutter -Mode CPU -KeepFolder
`$code = `$LASTEXITCODE
Copy-Item C:\SkydiveCutter\install_test.json C:\results\ -ErrorAction SilentlyContinue
Get-ChildItem C:\SkydiveCutter -Directory | ForEach-Object { Copy-Item (Join-Path `$_.FullName 'logs') C:\results\logs -Recurse -Force -ErrorAction SilentlyContinue }
Set-Content C:\results\exit-code.txt `$code
Stop-Transcript | Out-Null
Write-Host ''
Write-Host "Finished with exit code `$code. Results are in the results folder; close this Sandbox window." -ForegroundColor Cyan
"@
Set-Content -LiteralPath (Join-Path $resultsPath 'run-inside.ps1') -Value $inside -Encoding UTF8
Remove-Item (Join-Path $resultsPath 'exit-code.txt') -ErrorAction SilentlyContinue

$configuration = @"
<Configuration>
  <VGpu>Disable</VGpu>
  <Networking>Enable</Networking>
  <MappedFolders>
    <MappedFolder><HostFolder>$(Split-Path -Parent $zipPath)</HostFolder><SandboxFolder>C:\zip</SandboxFolder><ReadOnly>true</ReadOnly></MappedFolder>
    <MappedFolder><HostFolder>$testsPath</HostFolder><SandboxFolder>C:\tests</SandboxFolder><ReadOnly>true</ReadOnly></MappedFolder>
    <MappedFolder><HostFolder>$resultsPath</HostFolder><SandboxFolder>C:\results</SandboxFolder><ReadOnly>false</ReadOnly></MappedFolder>
  </MappedFolders>
  <LogonCommand>
    <Command>powershell.exe -NoExit -ExecutionPolicy Bypass -File C:\results\run-inside.ps1</Command>
  </LogonCommand>
</Configuration>
"@
$wsb = Join-Path $resultsPath 'install-test.wsb'
Set-Content -LiteralPath $wsb -Value $configuration -Encoding UTF8
Write-Host "Starting Windows Sandbox. Results will be written to $resultsPath"
Start-Process $sandbox -ArgumentList "`"$wsb`""
