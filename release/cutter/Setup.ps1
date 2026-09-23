[CmdletBinding()]
param(
    [ValidateSet('Auto','CPU','NVIDIA')][string]$Mode = 'Auto',
    [switch]$Repair,        # install everything again over the top; Skydive Cutter must be closed
    [switch]$PauseAtEnd,    # keep the window open at the end (the app starts setup this way)
    [switch]$AllowOneDrive  # install inside a OneDrive folder anyway
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') {
    throw 'This package needs 64-bit Windows on an Intel or AMD PC.'
}
$setupRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$setupDownloads = Join-Path $setupRoot '.downloads'
$setupCache = Join-Path $setupRoot 'cache'
$setupLogs = Join-Path $setupRoot 'logs'
foreach ($setupFolder in @($setupDownloads,$setupCache,$setupLogs)) {
    New-Item -ItemType Directory -Path $setupFolder -Force | Out-Null
}
# Keep downloads, pip build scratch, and scientific-library caches in this folder.
$env:TEMP = Join-Path $setupCache 'temp'
$env:TMP = $env:TEMP
$env:PIP_CACHE_DIR = Join-Path $setupCache 'pip'
$env:NUMBA_CACHE_DIR = Join-Path $setupCache 'numba'
$env:MPLCONFIGDIR = Join-Path $setupCache 'matplotlib'
$env:TORCH_HOME = Join-Path $setupCache 'torch'
$env:PYTHONDONTWRITEBYTECODE = '1'
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
$setupLog = Join-Path $setupLogs ('setup-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
Start-Transcript -Path $setupLog | Out-Null
$setupLock = $null
$setupFailed = $true
try {
    try {
        $setupLock = [IO.File]::Open((Join-Path $setupRoot '.setup.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    } catch { throw 'Another setup is already running in this folder. Let it finish first.' }

    # --- where it is being installed ------------------------------------------------------------------------------
    # The deepest file the libraries install is about 152 characters below this folder, and Windows stops at 260
    # unless long paths are switched on. Check now, rather than failing half way through a 5 GB download.
    $setupLongPaths = $false
    try {
        $setupLongPaths = (Get-ItemProperty -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Name LongPathsEnabled -ErrorAction Stop).LongPathsEnabled -eq 1
    } catch { }
    if ($setupRoot.Length -gt 100 -and -not $setupLongPaths) {
        throw ("This folder's path is $($setupRoot.Length) characters long, and Windows limits the files inside it to 260. " +
               'Move the Skydive Cutter folder somewhere shorter, for example C:\SkydiveCutter, and run it from there.')
    }
    # A OneDrive folder would upload the 10 GB runtime, and "free up space" would turn it into placeholders.
    foreach ($setupSync in @($env:OneDrive, $env:OneDriveCommercial, $env:OneDriveConsumer)) {
        if ($setupSync -and -not $AllowOneDrive -and
            $setupRoot.StartsWith([IO.Path]::GetFullPath($setupSync).TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw ('This folder is inside OneDrive, which would upload the 10 GB the app installs and could remove it ' +
                   'from this PC to save space. Move the Skydive Cutter folder out of OneDrive, for example to C:\SkydiveCutter.')
        }
    }

    # --- which runtime ------------------------------------------------------------------------------------------
    # CUDA builds need a driver at least this new (NVIDIA's minor-version compatibility minimums for Windows).
    $setupMinimumDriver = @{ cu118 = [version]'452.39'; cu128 = [version]'528.33' }
    $setupGpuProfile = $null
    $setupSmi = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
    if ($Mode -ne 'CPU' -and $setupSmi) {
        $setupGpuText = & $setupSmi.Source --query-gpu=compute_cap,driver_version --format=csv,noheader 2>$null
        if ($LASTEXITCODE -eq 0 -and $setupGpuText) {
            # Match CUDA's first visible device, which the inference runner uses.
            $setupFields = @($setupGpuText)[0] -split ','
            $setupCapability = 0.0
            $setupDriver = $null
            [void][double]::TryParse($setupFields[0].Trim(), [Globalization.NumberStyles]::Float, [Globalization.CultureInfo]::InvariantCulture, [ref]$setupCapability)
            if ($setupFields.Count -gt 1) { [void][version]::TryParse($setupFields[1].Trim(), [ref]$setupDriver) }
            $setupWanted = if ($setupCapability -ge 10.0) { 'cu128' } elseif ($setupCapability -ge 5.0) { 'cu118' } else { $null }
            if ($setupWanted -and $setupDriver -and $setupDriver -lt $setupMinimumDriver[$setupWanted]) {
                $setupMessage = "Your NVIDIA driver ($setupDriver) is too old for the GPU build; it needs $($setupMinimumDriver[$setupWanted]) or newer."
                if ($Mode -eq 'NVIDIA') { throw "$setupMessage Update it from nvidia.com, then run Repair.cmd again." }
                Write-Host "$setupMessage Using the processor instead. Update the driver and run Repair.cmd to use the GPU." -ForegroundColor Yellow
            } elseif ($setupWanted) {
                $setupGpuProfile = $setupWanted
            }
        }
    }
    if ($Mode -eq 'NVIDIA' -and -not $setupGpuProfile) {
        throw 'No supported NVIDIA device/driver was detected. Run Repair.cmd -Mode CPU, or install your NVIDIA driver and retry.'
    }
    $setupProfiles = @(@($setupGpuProfile, 'cpu') | Where-Object { $_ })
    if ($Mode -eq 'NVIDIA') { $setupProfiles = @($setupGpuProfile) }

    $setupDrive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($setupRoot))
    $setupRequiredGB = if ($setupGpuProfile) { 20 } else { 8 }
    if ($setupDrive.AvailableFreeSpace -lt ($setupRequiredGB * 1GB)) { throw "Please free at least $setupRequiredGB GB on this drive before setup." }
    Write-Host ''
    Write-Host $(if ($Repair) { 'Skydive Cutter - repairing this install' } else { 'Skydive Cutter - one-time setup' }) -ForegroundColor Cyan
    Write-Host "Install folder: $setupRoot"
    Write-Host "Runtime profile: $($setupProfiles[0])"
    Write-Host 'Downloads Python, the model libraries, the person detector and FFmpeg into this folder.'
    Write-Host 'The person detector is Ultralytics YOLO, licensed under AGPL-3.0 and downloaded from PyPI:'
    Write-Host '  https://github.com/ultralytics/ultralytics/blob/main/LICENSE'
    Write-Host 'No administrator access, system Python installation, PATH changes or video uploads.'
    Write-Host 'Your videos never leave this PC: after setup the app works offline.'
    Write-Host 'CPU downloads are smaller; NVIDIA downloads can be several GB. Please leave this window open.'
    Write-Host ''
    $setupManifest = Get-Content -LiteralPath (Join-Path $setupRoot 'downloads.json') -Raw | ConvertFrom-Json

    function Get-SetupDownload {
        # Each address in turn, until one gives the file with the pinned checksum.
        param($Item)
        $setupDestination = Join-Path $setupDownloads $Item.filename
        if (Test-Path -LiteralPath $setupDestination -PathType Leaf) {
            if ((Get-FileHash -LiteralPath $setupDestination -Algorithm SHA256).Hash -eq $Item.sha256) { return $setupDestination }
            Remove-Item -LiteralPath $setupDestination -Force
        }
        $setupTemporary = $setupDestination + '.download'
        foreach ($setupUrl in @($Item.urls)) {
            # A dropped connection is usually brief, so each address gets three tries; a wrong file gets one.
            foreach ($setupAttempt in 1..3) {
                Write-Host "Downloading $($Item.filename) from $(([Uri]$setupUrl).Host)..."
                try {
                    Invoke-WebRequest -Uri $setupUrl -OutFile $setupTemporary -UseBasicParsing -TimeoutSec 3600
                    if ((Get-FileHash -LiteralPath $setupTemporary -Algorithm SHA256).Hash -eq $Item.sha256) {
                        Move-Item -LiteralPath $setupTemporary -Destination $setupDestination -Force
                        return $setupDestination
                    }
                    Write-Host "  That copy did not match its checksum." -ForegroundColor Yellow
                    Remove-Item -LiteralPath $setupTemporary -Force -ErrorAction SilentlyContinue
                    break
                } catch {
                    Write-Host "  $($_.Exception.Message)" -ForegroundColor Yellow
                    Remove-Item -LiteralPath $setupTemporary -Force -ErrorAction SilentlyContinue
                    if ($setupAttempt -lt 3) { Start-Sleep -Seconds (10 * $setupAttempt) }
                }
            }
        }
        throw "Could not download $($Item.filename) from any source. Check the internet connection and run setup again."
    }

    function Invoke-SetupPython {
        # Everything pip says goes to the window and, through Write-Host, into the setup log: PowerShell 5.1's
        # transcript leaves out a program's own output otherwise, and the log is what people send when it fails.
        param([string]$Python, [string[]]$Arguments)
        $previous = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'   # pip's warnings on stderr are not failures; its exit code decides
        try {
            & $Python -s @Arguments 2>&1 | ForEach-Object { Write-Host "$_" }
            $code = $LASTEXITCODE
        } finally { $ErrorActionPreference = $previous }
        if ($code -ne 0) { throw "Setup command failed (exit $code). See $setupLog" }
    }

    function Install-SetupRuntime {
        # Python and every library for one build (cpu, cu118 or cu128), from the hash-pinned locks. Returns the path of python.exe.
        param([string]$Build)
        $runtime = Join-Path $setupRoot ('.runtime\' + $Build)
        $python = Join-Path $runtime 'python.exe'
        if ($Repair -and (Test-Path -LiteralPath $runtime)) {
            # Renaming fails at once, before anything is deleted, if the app still has these files open.
            $retired = "$runtime.old-$(Get-Date -Format 'yyyyMMddHHmmss')"
            try { Rename-Item -LiteralPath $runtime -NewName (Split-Path -Leaf $retired) }
            catch { throw 'Close Skydive Cutter before repairing: it is using the files this would replace.' }
            Remove-Item -LiteralPath $retired -Recurse -Force -ErrorAction SilentlyContinue
        }
        if (-not (Test-Path -LiteralPath $python)) {
            $archive = Get-SetupDownload $setupManifest.python
            New-Item -ItemType Directory -Path $runtime -Force | Out-Null
            Expand-Archive -LiteralPath $archive -DestinationPath $runtime -Force
        }
        # Embedded Python has isolated paths; explicitly enable only this app and its own packages.
        @('python312.zip','.', 'Lib', 'Lib\site-packages','..\..','import site') |
            Set-Content -LiteralPath (Join-Path $runtime 'python312._pth') -Encoding Ascii
        $site = Join-Path $runtime 'Lib\site-packages'
        if (-not (Test-Path -LiteralPath (Join-Path $site 'pip\__main__.py'))) {
            $wheel = Get-SetupDownload $setupManifest.pip
            New-Item -ItemType Directory -Path $site -Force | Out-Null
            Add-Type -AssemblyName System.IO.Compression.FileSystem
            [IO.Compression.ZipFile]::ExtractToDirectory($wheel, $site)
        }
        # Wheels only, each checked against its pinned hash, and nothing the locks do not list.
        $pip = @('-B','-m','pip','install','--disable-pip-version-check','--no-warn-script-location',
                 '--only-binary=:all:','--require-hashes','--no-deps')
        Invoke-SetupPython $python ($pip + @('-r',(Join-Path $setupRoot "torch-$Build.txt"),
                                             '--index-url',"https://download.pytorch.org/whl/$Build"))
        Invoke-SetupPython $python ($pip + @('-r',(Join-Path $setupRoot 'requirements-windows.txt'),
                                             '--index-url','https://pypi.org/simple'))
        Invoke-SetupPython $python @('-B','-m','pip','check')
        return $python
    }

    # --- FFmpeg and the person detector's model: the same for every profile ---------------------------------------
    $setupBin = Join-Path $setupRoot 'bin'
    if ($Repair -or -not (Test-Path -LiteralPath (Join-Path $setupBin 'ffprobe.exe')) -or
        -not (Test-Path -LiteralPath (Join-Path $setupBin 'ffmpeg.exe'))) {
        $setupFfmpegZip = Get-SetupDownload $setupManifest.ffmpeg
        $setupExpanded = Join-Path $setupDownloads 'ffmpeg-expanded'
        Remove-Item -LiteralPath $setupExpanded -Recurse -Force -ErrorAction SilentlyContinue
        Expand-Archive -LiteralPath $setupFfmpegZip -DestinationPath $setupExpanded -Force
        $setupFfmpegSource = Get-ChildItem -LiteralPath $setupExpanded -Directory | Select-Object -First 1
        New-Item -ItemType Directory -Path $setupBin -Force | Out-Null
        foreach ($setupTool in @('ffmpeg.exe','ffprobe.exe')) {
            Copy-Item -LiteralPath (Join-Path $setupFfmpegSource.FullName ('bin\' + $setupTool)) -Destination (Join-Path $setupBin $setupTool) -Force
        }
        $setupLicenses = Join-Path $setupRoot 'third_party\ffmpeg'
        New-Item -ItemType Directory -Path $setupLicenses -Force | Out-Null
        foreach ($setupNotice in @('LICENSE','README.txt')) {
            $setupNoticePath = Join-Path $setupFfmpegSource.FullName $setupNotice
            if (Test-Path -LiteralPath $setupNoticePath) { Copy-Item -LiteralPath $setupNoticePath -Destination $setupLicenses -Force }
        }
        Remove-Item -LiteralPath $setupExpanded -Recurse -Force -ErrorAction SilentlyContinue
    }
    $setupWeights = Join-Path $setupRoot 'yolo11n.pt'
    if (-not (Test-Path -LiteralPath $setupWeights) -or
        (Get-FileHash -LiteralPath $setupWeights -Algorithm SHA256).Hash -ne $setupManifest.people.sha256) {
        Copy-Item -LiteralPath (Get-SetupDownload $setupManifest.people) -Destination $setupWeights -Force
    }

    # --- the runtime: the GPU build first, and the processor build if the GPU cannot be used -------------------------
    # Only a GPU build that installed but then failed its check on this GPU falls back to the processor. A download or
    # install that fails stops setup instead: falling back then would leave a PC with a good GPU on the processor
    # for good, reported as a GPU problem. Running setup again continues from the files already downloaded.
    $setupEnvironment = $null
    foreach ($setupProfile in $setupProfiles) {
        $setupDevice = if ($setupProfile -eq 'cpu') { 'cpu' } else { 'cuda' }
        $setupPython = Install-SetupRuntime $setupProfile
        # Ultralytics sends anonymous usage statistics unless told not to; Skydive Cutter stays offline.
        # The quotes matter: PowerShell strips double quotes out of an argument, so Python must see single ones.
        $env:YOLO_CONFIG_DIR = Join-Path $setupCache 'ultralytics'
        & $setupPython -s -B -c "from ultralytics import settings; settings.update({'sync': False})" | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Could not switch off Ultralytics' usage statistics (exit $LASTEXITCODE)." }
        try {
            Invoke-SetupPython $setupPython @('-B',(Join-Path $setupRoot 'verify_install.py'),'--device',$setupDevice)
            $setupEnvironment = @{ profile = $setupProfile; device = $setupDevice; python = $setupPython }
            break
        } catch {
            if ($setupDevice -eq 'cpu' -or $Mode -eq 'NVIDIA') { throw }
            Write-Host ''
            Write-Host "The NVIDIA build could not use this GPU: $($_.Exception.Message)" -ForegroundColor Yellow
            Write-Host 'Installing the processor build instead. It is slower but gives the same results.' -ForegroundColor Yellow
            Write-Host 'Update the NVIDIA driver and run Repair.cmd to try the GPU again.' -ForegroundColor Yellow
            Write-Host ''
        }
    }
    $setupInstalled = [ordered]@{schema_version=1; profile=$setupEnvironment.profile
                                 python=('.runtime/' + $setupEnvironment.profile + '/python.exe')
                                 device=$setupEnvironment.device; installed_at=(Get-Date -Format o)}
    $setupInstalled | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $setupRoot 'installation.json') -Encoding UTF8
    & $setupEnvironment.python -s -B -m pip freeze |
        Set-Content -LiteralPath (Join-Path $setupLogs ('installed-' + $setupEnvironment.profile + '.txt')) -Encoding UTF8
    Write-Host ''
    Write-Host 'Setup passed. Skydive Cutter opens next.' -ForegroundColor Green
    $setupFailed = $false
} catch {
    Write-Host ''
    Write-Host "Setup stopped: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "The full log is $setupLog"
    throw
} finally {
    if ($setupLock) { $setupLock.Dispose() }
    Stop-Transcript | Out-Null
    if ($PauseAtEnd) {
        Write-Host ''
        Read-Host $(if ($setupFailed) { 'Press Enter to close this window' } else { 'Done. Press Enter to close this window' }) | Out-Null
    }
}
