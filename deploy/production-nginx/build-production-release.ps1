[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$Version,

    [switch]$AllowDirty
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Invoke-Checked {
    param([Parameter(Mandatory = $true)][string]$FilePath, [string[]]$Arguments = @())
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $FilePath $($Arguments -join ' ')"
    }
}

function Get-RelativeUnixPath {
    param([string]$Base, [string]$Path)
    $baseFull = [System.IO.Path]::GetFullPath($Base).TrimEnd('\') + '\'
    $pathFull = [System.IO.Path]::GetFullPath($Path)
    $relative = ([Uri]$baseFull).MakeRelativeUri([Uri]$pathFull).ToString()
    return [Uri]::UnescapeDataString($relative).Replace('\', '/')
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptRoot '..\..'))
$actualRoot = (& git -C $projectRoot rev-parse --show-toplevel).Trim().Replace('\', '/')
if ($actualRoot -ne $projectRoot.Replace('\', '/')) {
    throw "Unexpected Git root: $actualRoot"
}

$dirtyLines = @(& git -C $projectRoot status --porcelain)
$isDirty = $dirtyLines.Count -gt 0
if ($isDirty -and -not $AllowDirty) {
    throw 'The worktree is dirty. Review it, then rerun with -AllowDirty to create a clearly marked development release.'
}
if ($isDirty) {
    Write-Warning "Building from a dirty worktree ($($dirtyLines.Count) status entries). BUILD-STATUS.txt will record this."
}

$docker = (Get-Command docker.exe -ErrorAction Stop).Source
$node = (Get-Command node.exe -ErrorAction Stop).Source
$npm = (Get-Command npm.cmd -ErrorAction Stop).Source
$tar = (Get-Command tar.exe -ErrorAction Stop).Source
Invoke-Checked $docker @('version')
Invoke-Checked $docker @('compose', 'version')
Invoke-Checked $docker @('buildx', 'version')
Invoke-Checked $node @('--version')
Invoke-Checked $npm @('--version')
Invoke-Checked $tar @('--version')

$commit = (& git -C $projectRoot rev-parse HEAD).Trim()
$adminRoot = Join-Path $projectRoot 'license-admin'
$serverRoot = Join-Path $projectRoot 'license-server'
$releaseParent = Join-Path $projectRoot 'release'
$releaseName = "PMSystem-License-Production-$Version"
$releaseRoot = [System.IO.Path]::GetFullPath((Join-Path $releaseParent $releaseName))
$archivePath = [System.IO.Path]::GetFullPath((Join-Path $releaseParent "$releaseName.tar.gz"))
$releaseParentFull = [System.IO.Path]::GetFullPath($releaseParent)
if (-not $releaseRoot.StartsWith($releaseParentFull + [System.IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Unsafe release path: $releaseRoot"
}
if (Test-Path -LiteralPath $releaseRoot) { Remove-Item -LiteralPath $releaseRoot -Recurse -Force }
if (Test-Path -LiteralPath $archivePath) { Remove-Item -LiteralPath $archivePath -Force }
New-Item -ItemType Directory -Path $releaseRoot, (Join-Path $releaseRoot 'images'), (Join-Path $releaseRoot 'admin') -Force | Out-Null

$apiImage = "pmsystem-license-api:$Version"
Write-Host "Building $apiImage for linux/amd64..."
Invoke-Checked $docker @('buildx', 'build', '--platform', 'linux/amd64', '--load', '--tag', $apiImage, $serverRoot)

function Ensure-LinuxAmd64Image([string]$Image) {
    $inspect = & $docker image inspect $Image --format '{{.Os}}/{{.Architecture}}' 2>$null
    if ($LASTEXITCODE -ne 0 -or $inspect.Trim() -ne 'linux/amd64') {
        Write-Host "Pulling local build dependency $Image for linux/amd64..."
        Invoke-Checked $docker @('pull', '--platform', 'linux/amd64', $Image)
        $inspect = & $docker image inspect $Image --format '{{.Os}}/{{.Architecture}}'
    }
    if ($inspect.Trim() -ne 'linux/amd64') { throw "$Image is not linux/amd64: $inspect" }
}
Ensure-LinuxAmd64Image $apiImage
Ensure-LinuxAmd64Image 'postgres:17.5-alpine'

Write-Host 'Building the production admin application...'
Push-Location $adminRoot
try {
    Invoke-Checked $npm @('ci', '--ignore-scripts')
    $env:VITE_API_BASE_URL = 'https://license.aixcc.top/api/v1'
    $env:VITE_APP_ENVIRONMENT = 'production'
    $env:VITE_APP_ENV_LABEL = '生产环境'
    $env:VITE_APP_TITLE = 'PMSystem授权管理'
    $env:VITE_BASE_PATH = '/admin/'
    Invoke-Checked $npm @('run', 'build:production')
} finally {
    Remove-Item Env:VITE_API_BASE_URL, Env:VITE_APP_ENVIRONMENT, Env:VITE_APP_ENV_LABEL, Env:VITE_APP_TITLE, Env:VITE_BASE_PATH -ErrorAction SilentlyContinue
    Pop-Location
}
$adminDist = Join-Path $adminRoot 'dist'
if (-not (Test-Path -LiteralPath (Join-Path $adminDist 'index.html'))) { throw 'Admin build did not produce dist/index.html' }
Copy-Item -Path (Join-Path $adminDist '*') -Destination (Join-Path $releaseRoot 'admin') -Recurse -Force

foreach ($item in @('compose.yml', 'env.production.example', 'README.md', 'SERVER-PREPARATION.md', 'DISASTER_RECOVERY.md')) {
    Copy-Item -LiteralPath (Join-Path $scriptRoot $item) -Destination (Join-Path $releaseRoot $item)
}
Copy-Item -LiteralPath (Join-Path $scriptRoot 'nginx') -Destination $releaseRoot -Recurse
Copy-Item -LiteralPath (Join-Path $scriptRoot 'scripts') -Destination $releaseRoot -Recurse
[System.IO.File]::WriteAllText((Join-Path $releaseRoot 'BUILD-COMMIT.txt'), "$commit`n", [Text.UTF8Encoding]::new($false))
$buildStatus = if ($isDirty) { "DIRTY ($($dirtyLines.Count) status entries)" } else { 'CLEAN' }
[System.IO.File]::WriteAllText((Join-Path $releaseRoot 'BUILD-STATUS.txt'), "$buildStatus`n", [Text.UTF8Encoding]::new($false))
[System.IO.File]::WriteAllText((Join-Path $releaseRoot 'RELEASE-VERSION.txt'), "$Version`n", [Text.UTF8Encoding]::new($false))

$imageTar = Join-Path $releaseRoot "images\pmsystem-production-images-$Version.tar"
Invoke-Checked $docker @('save', '--output', $imageTar, $apiImage, 'postgres:17.5-alpine')
Invoke-Checked $docker @('load', '--input', $imageTar)

$manifest = @(
    "Release: $releaseName",
    "Release version: $Version",
    "Build commit: $commit",
    "Build status: $buildStatus",
    'Target platform: linux/amd64',
    "API image: $apiImage",
    'API service version: 0.2.0',
    'PostgreSQL image: postgres:17.5-alpine',
    'Admin base path: /admin/',
    'API base path: /api/v1',
    "Created UTC: $([DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ'))"
)
[System.IO.File]::WriteAllLines((Join-Path $releaseRoot 'RELEASE-MANIFEST.txt'), $manifest, [Text.UTF8Encoding]::new($false))

$blockedDirectories = @('.git', 'node_modules', '.venv', 'venv', '__pycache__')
$blockedExtensions = @('.sqlite', '.sqlite3', '.db', '.dump', '.bak', '.mp4', '.avi', '.mkv', '.mov')
$blockedFiles = Get-ChildItem -LiteralPath $releaseRoot -Recurse -Force | Where-Object {
    ($_.PSIsContainer -and $blockedDirectories -contains $_.Name) -or
    (-not $_.PSIsContainer -and (
        $_.Name -in @('.env', '.env.production') -or
        $_.Name -match '(?i)private.*\.(pem|key)$' -or
        $blockedExtensions -contains $_.Extension.ToLowerInvariant()
    ))
}
if ($blockedFiles) { throw "Blocked files found in release: $($blockedFiles.FullName -join ', ')" }
$privateMarkers = Get-ChildItem -LiteralPath $releaseRoot -Recurse -File | Where-Object { $_.Extension -notin @('.tar', '.gz') } | Select-String -SimpleMatch '-----BEGIN PRIVATE KEY-----' -ErrorAction SilentlyContinue
if ($privateMarkers) { throw 'Private key material was found in the release directory' }

$checksumPath = Join-Path $releaseRoot 'SHA256SUMS.txt'
$checksumLines = Get-ChildItem -LiteralPath $releaseRoot -Recurse -File | Where-Object { $_.FullName -ne $checksumPath } | Sort-Object FullName | ForEach-Object {
    $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $(Get-RelativeUnixPath $releaseRoot $_.FullName)"
}
[System.IO.File]::WriteAllText(
    $checksumPath,
    (($checksumLines -join "`n") + "`n"),
    [Text.UTF8Encoding]::new($false)
)

Push-Location $releaseParent
try { Invoke-Checked $tar @('-czf', $archivePath, $releaseName) } finally { Pop-Location }
$archiveHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
$archiveHashPath = "$archivePath.sha256.txt"
[System.IO.File]::WriteAllText($archiveHashPath, "$archiveHash  $releaseName.tar.gz`n", [Text.UTF8Encoding]::new($false))

Write-Host "Release directory: $releaseRoot"
Write-Host "Image archive: $imageTar ($([math]::Round((Get-Item $imageTar).Length / 1MB, 2)) MiB)"
Write-Host "Release archive: $archivePath ($([math]::Round((Get-Item $archivePath).Length / 1MB, 2)) MiB)"
Write-Host "Release SHA256: $archiveHash"
