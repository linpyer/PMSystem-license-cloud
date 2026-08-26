[CmdletBinding()]
param(
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
Import-Module (Join-Path $PSScriptRoot 'release\DDREC.Release.psm1') -Force
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$PublicKey = Join-Path $ProjectRoot "app\assets\license\production_ed25519_public.pem"

function Invoke-Checked {
    param([scriptblock]$Command, [string]$Description)
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE"
    }
}

function Remove-BuildDirectory {
    param([string]$Path)
    $FullPath = [System.IO.Path]::GetFullPath($Path)
    $RequiredPrefix = $ProjectRoot.TrimEnd('\') + '\'
    if (-not $FullPath.StartsWith($RequiredPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove path outside project root: $FullPath"
    }
    if (Test-Path -LiteralPath $FullPath) {
        Remove-Item -LiteralPath $FullPath -Recurse -Force
    }
}

function Assert-RealExecutable {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required executable is missing: $Path"
    }
    $Info = Get-Item -LiteralPath $Path
    if ($Info.Length -lt 1048576) {
        throw "Executable is unexpectedly small and may be a Git LFS pointer: $Path"
    }
    $Stream = [System.IO.File]::OpenRead($Path)
    try {
        $Buffer = New-Object byte[] 128
        $Read = $Stream.Read($Buffer, 0, $Buffer.Length)
        $Header = [System.Text.Encoding]::ASCII.GetString($Buffer, 0, $Read)
    }
    finally {
        $Stream.Dispose()
    }
    if ($Header.StartsWith("version https://git-lfs.github.com/spec/")) {
        throw "Git LFS pointer was found instead of an executable: $Path"
    }
}

Set-Location -LiteralPath $ProjectRoot
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Project Python 3.12 virtual environment is missing: $Python"
}
$ActualVersion = (& $Python -c "from app.core.version import APP_VERSION; print(APP_VERSION)").Trim()
$AppName = (& $Python -c "from app.core.version import APP_NAME; print(APP_NAME)").Trim()
$GitBranch = (git branch --show-current).Trim()
$ExpectedVersion = Get-DDRECExpectedClientVersion -Branch $GitBranch
if ($ActualVersion -cne $ExpectedVersion) {
    throw "Client branch/version mismatch: $GitBranch requires $ExpectedVersion, actual $ActualVersion"
}
if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = $ActualVersion
}
if ($ActualVersion -ne $Version) {
    throw "Requested version $Version does not match application version $ActualVersion"
}
$ReleaseRoot = Join-Path $ProjectRoot "release\client\$Version"
$Installer = Join-Path $ReleaseRoot "DDREC-Setup.exe"

$Ffmpeg = Join-Path $ProjectRoot "tools\ffmpeg\ffmpeg.exe"
$Ffprobe = Join-Path $ProjectRoot "tools\ffmpeg\ffprobe.exe"
Assert-RealExecutable $Ffmpeg
Assert-RealExecutable $Ffprobe
Invoke-Checked { & $Ffmpeg -version } "ffmpeg validation"
Invoke-Checked { & $Ffprobe -version } "ffprobe validation"
Invoke-Checked {
    & $Python scripts\check_production_license_config.py
} "production license configuration validation"

Remove-BuildDirectory (Join-Path $ProjectRoot "build")
Remove-BuildDirectory (Join-Path $ProjectRoot "dist")
Remove-BuildDirectory $ReleaseRoot
New-Item -ItemType Directory -Path $ReleaseRoot -Force | Out-Null

Invoke-Checked { & $Python -m compileall -q main.py app scripts } "Python syntax check"
Invoke-Checked { & $Python -m pytest -q tests } "client pytest suite"
Invoke-Checked { & $Python -m PyInstaller --noconfirm --clean DDREC.spec } "PyInstaller"

$DistDirectories = @(Get-ChildItem -LiteralPath (Join-Path $ProjectRoot "dist") -Directory)
if ($DistDirectories.Count -ne 1) {
    throw "Expected exactly one PyInstaller onedir output, found $($DistDirectories.Count)"
}
$DistRoot = $DistDirectories[0].FullName
$MainExecutables = @(
    Get-ChildItem -LiteralPath $DistRoot -Filter "*.exe" -File |
        Where-Object { $_.Name -ne "DDRECLicenseHelper.exe" }
)
if ($MainExecutables.Count -ne 1) {
    throw "Expected exactly one main executable, found $($MainExecutables.Count)"
}
$MainExe = $MainExecutables[0].FullName
$PackagedFfmpeg = Join-Path $DistRoot "_internal\tools\ffmpeg\ffmpeg.exe"
$PackagedFfprobe = Join-Path $DistRoot "_internal\tools\ffmpeg\ffprobe.exe"
$PackagedPublicKey = Join-Path $DistRoot "_internal\app\assets\license\production_ed25519_public.pem"
foreach ($Required in @($MainExe, $PackagedFfmpeg, $PackagedFfprobe, $PackagedPublicKey)) {
    if (-not (Test-Path -LiteralPath $Required -PathType Leaf)) {
        throw "PyInstaller output is incomplete: $Required"
    }
}
Assert-RealExecutable $PackagedFfmpeg
Assert-RealExecutable $PackagedFfprobe
Invoke-Checked {
    & $Python scripts\check_client_release_security.py $DistRoot
} "client dist security scan"

$IsccCandidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)
$Iscc = $IsccCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $Iscc) {
    throw "Inno Setup 6 compiler ISCC.exe was not found"
}
Invoke-Checked {
    & $Iscc "/DMyAppVersion=$Version" (Join-Path $ProjectRoot "installer\DDREC.iss")
} "Inno Setup"
if (-not (Test-Path -LiteralPath $Installer -PathType Leaf)) {
    throw "Installer output is missing: $Installer"
}
Invoke-Checked {
    & $Python scripts\check_client_release_security.py $Installer
} "installer security scan"

$GitCommit = (git rev-parse HEAD).Trim()
$BuildTime = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
$PythonVersion = (& $Python --version 2>&1).ToString().Trim()
$PyInstallerVersion = (& $Python -m PyInstaller --version).Trim()
$InnoUninstaller = Join-Path (Split-Path -Parent $Iscc) "unins000.exe"
$InnoVersion = if (Test-Path -LiteralPath $InnoUninstaller) {
    (Get-Item -LiteralPath $InnoUninstaller).VersionInfo.ProductVersion
} else {
    (Get-Item -LiteralPath $Iscc).VersionInfo.ProductVersion
}
$PublicKeySha = (Get-FileHash -LiteralPath $PublicKey -Algorithm SHA256).Hash
$InstallerHash = (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash
$InstallerSize = (Get-Item -LiteralPath $Installer).Length

Set-Content -LiteralPath "$Installer.sha256.txt" -Encoding ASCII -Value "$InstallerHash  DDREC-Setup.exe"
$Manifest = @"
ProductName=DDREC / $AppName
Version=$Version
BuildTimeUtc=$BuildTime
GitCommit=$GitCommit
GitBranch=$GitBranch
PythonVersion=$PythonVersion
PyInstallerVersion=$PyInstallerVersion
InnoSetupVersion=$InnoVersion
LicenseApiBaseUrl=https://license.aixcc.top/api/v1
LicenseSigningKeyId=production-2026-01
ProductionPublicKeySha256=$PublicKeySha
InstallerSha256=$InstallerHash
InstallerSizeBytes=$InstallerSize
CodeSigned=NO (unsigned)
OnlineActivationAcceptance=NOT COMPLETED - production HTTPS is not available yet
"@
Set-Content -LiteralPath (Join-Path $ReleaseRoot "RELEASE-MANIFEST.txt") -Encoding UTF8 -Value $Manifest
$Report = @"
# DDREC $Version Production Client Build Report

- Build result: succeeded
- Build time (UTC): $BuildTime
- Branch: $GitBranch
- Commit: $GitCommit
- Python: $PythonVersion
- PyInstaller: $PyInstallerVersion
- Inno Setup: $InnoVersion
- Packaging mode: PyInstaller onedir
- License environment: production (locked in frozen client)
- License API: https://license.aixcc.top/api/v1
- Signing key ID: production-2026-01
- Public key SHA256: $PublicKeySha
- Installer SHA256: $InstallerHash
- Code signing: not performed; the installer is unsigned

## Automated checks

- Python compilation: passed
- Existing pytest suite: passed
- Production URL, TLS and public-key checks: passed
- FFmpeg and ffprobe executable checks: passed
- Client artifact secret scan: passed

## Pending acceptance

- Real HTTPS activation was not tested because domain filing and the HTTPS certificate are not complete.
- Real camera, recording and user-data workflows are outside this build run.
- Installation smoke-test results are recorded separately after this build.
"@
Set-Content -LiteralPath (Join-Path $ReleaseRoot "BUILD-REPORT.md") -Encoding UTF8 -Value $Report

Write-Host "Production client build completed"
Write-Host "Installer: $Installer"
Write-Host "Size: $InstallerSize bytes"
Write-Host "SHA256: $InstallerHash"
