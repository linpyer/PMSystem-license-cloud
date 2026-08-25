[CmdletBinding()]
param(
    [switch]$PlanOnly
)

$ErrorActionPreference = 'Stop'
$cloudRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$workspaceRoot = (Resolve-Path (Join-Path $cloudRoot '..')).Path
$clientRoot = Join-Path $workspaceRoot 'client'
$licenseServerRoot = Join-Path $cloudRoot 'license-server'
$adminRoot = Join-Path $cloudRoot 'license-admin'
$clientPython = Join-Path $clientRoot '.venv\Scripts\python.exe'
$cloudPython = Join-Path $cloudRoot '.venv\Scripts\python.exe'

$requiredPaths = @(
    $clientRoot,
    $licenseServerRoot,
    $adminRoot,
    $clientPython,
    $cloudPython
)
foreach ($path in $requiredPaths) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "测试入口缺少必需路径：$path"
    }
}

$sitePackages = Join-Path $cloudRoot '.venv\Lib\site-packages'
Get-ChildItem -LiteralPath $sitePackages -Filter '*.pth' -File -ErrorAction SilentlyContinue | ForEach-Object {
    $content = Get-Content -LiteralPath $_.FullName -Raw -ErrorAction Stop
    if ($content -match '(?i)E:\\AI-Project\\PMSystem\\cloud-license') {
        throw "检测到旧 PMSystem editable 路径，请重建当前 Cloud 虚拟环境：$($_.FullName)"
    }
}

$editablePath = Join-Path $sitePackages '_editable_impl_ddrec_license_server.pth'
if (Test-Path -LiteralPath $editablePath) {
    $configuredSource = (Get-Content -LiteralPath $editablePath -Raw).Trim()
    $expectedSource = (Resolve-Path -LiteralPath $licenseServerRoot).Path
    if (-not [string]::Equals(
        [IO.Path]::GetFullPath($configuredSource),
        [IO.Path]::GetFullPath($expectedSource),
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "license-server editable 路径不属于当前工作区：$configuredSource"
    }
}

$plan = @(
    [pscustomobject]@{ Name = 'Client'; WorkingDirectory = $clientRoot; Command = $clientPython; Arguments = @('-m', 'pytest', '-q') }
    [pscustomobject]@{ Name = 'Cloud Python'; WorkingDirectory = $cloudRoot; Command = $clientPython; Arguments = @('-m', 'pytest', '-q', 'tests') }
    [pscustomobject]@{ Name = 'License Server'; WorkingDirectory = $licenseServerRoot; Command = $cloudPython; Arguments = @('-m', 'pytest', '-q') }
    [pscustomobject]@{ Name = 'Pester'; WorkingDirectory = $cloudRoot; Command = 'Invoke-Pester'; Arguments = @('tests') }
    [pscustomobject]@{ Name = 'Admin Vitest'; WorkingDirectory = $adminRoot; Command = 'npm.cmd'; Arguments = @('run', 'test:unit', '--', '--run') }
    [pscustomobject]@{ Name = 'Admin TypeCheck'; WorkingDirectory = $adminRoot; Command = 'npm.cmd'; Arguments = @('run', 'type-check') }
    [pscustomobject]@{ Name = 'Admin E2E'; WorkingDirectory = $adminRoot; Command = 'npm.cmd'; Arguments = @('run', 'test:e2e') }
)

if ($PlanOnly) {
    $plan | Select-Object Name, WorkingDirectory, Command, @{ Name = 'Arguments'; Expression = { $_.Arguments -join ' ' } }
    return
}

function Invoke-DDRECTestStep {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$WorkingDirectory,
        [Parameter(Mandatory)][scriptblock]$Action
    )

    Write-Host "`n=== $Name ===" -ForegroundColor Cyan
    $stopwatch = [Diagnostics.Stopwatch]::StartNew()
    $exitCode = 0
    Push-Location -LiteralPath $WorkingDirectory
    try {
        & $Action
        if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) {
            $exitCode = [int]$LASTEXITCODE
        }
    } catch {
        Write-Warning $_
        $exitCode = 1
    } finally {
        Pop-Location
        $stopwatch.Stop()
    }
    [pscustomobject]@{
        Name = $Name
        Status = if ($exitCode -eq 0) { 'PASS' } else { 'FAIL' }
        ExitCode = $exitCode
        Seconds = [math]::Round($stopwatch.Elapsed.TotalSeconds, 2)
    }
}

$savedPythonPath = $env:PYTHONPATH
$savedPythonHome = $env:PYTHONHOME
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue

try {
    $results = [Collections.Generic.List[object]]::new()
    $results.Add((Invoke-DDRECTestStep -Name 'Client' -WorkingDirectory $clientRoot -Action {
        & $clientPython -m pytest -q
    }))
    $results.Add((Invoke-DDRECTestStep -Name 'Cloud Python' -WorkingDirectory $cloudRoot -Action {
        & $clientPython -m pytest -q tests
    }))
    $results.Add((Invoke-DDRECTestStep -Name 'License Server' -WorkingDirectory $licenseServerRoot -Action {
        & $cloudPython -m pytest -q
    }))
    $results.Add((Invoke-DDRECTestStep -Name 'Pester' -WorkingDirectory $cloudRoot -Action {
        $pesterResult = Invoke-Pester -Path (Join-Path $cloudRoot 'tests') -PassThru
        if ($pesterResult.FailedCount -ne 0) {
            throw "Pester failed: $($pesterResult.FailedCount)"
        }
    }))
    $results.Add((Invoke-DDRECTestStep -Name 'Admin Vitest' -WorkingDirectory $adminRoot -Action {
        & npm.cmd run test:unit -- --run
    }))
    $results.Add((Invoke-DDRECTestStep -Name 'Admin TypeCheck' -WorkingDirectory $adminRoot -Action {
        & npm.cmd run type-check
    }))
    $results.Add((Invoke-DDRECTestStep -Name 'Admin E2E' -WorkingDirectory $adminRoot -Action {
        & npm.cmd run test:e2e
    }))
} finally {
    if ($null -eq $savedPythonPath) {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    } else {
        $env:PYTHONPATH = $savedPythonPath
    }
    if ($null -eq $savedPythonHome) {
        Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
    } else {
        $env:PYTHONHOME = $savedPythonHome
    }
}

Write-Host "`n=== DDREC Test Summary ===" -ForegroundColor Cyan
$results | Format-Table Name, Status, ExitCode, Seconds -AutoSize
if ($results.Where({ $_.ExitCode -ne 0 }).Count -ne 0) {
    exit 1
}
