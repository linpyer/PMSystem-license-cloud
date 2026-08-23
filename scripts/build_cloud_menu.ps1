[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptRoot '..'))
$buildScript = [System.IO.Path]::GetFullPath((Join-Path $scriptRoot 'build_cloud_release.ps1'))
$artifactScript = [System.IO.Path]::GetFullPath((Join-Path $scriptRoot 'cloud_build_artifacts.ps1'))

foreach ($requiredScript in @($buildScript, $artifactScript)) {
    if (-not (Test-Path -LiteralPath $requiredScript -PathType Leaf)) {
        Write-Host "错误：找不到云端构建脚本：$requiredScript" -ForegroundColor Red
        exit 2
    }
}
. $artifactScript

$versionPath = Join-Path $projectRoot 'VERSION'
if (-not (Test-Path -LiteralPath $versionPath -PathType Leaf)) {
    Write-Host "错误：找不到统一版本文件：$versionPath" -ForegroundColor Red
    exit 2
}
$releaseVersion = (Get-Content -LiteralPath $versionPath -Raw -Encoding UTF8).Trim()
if ($releaseVersion -notmatch '^\d+\.\d+\.\d+$') {
    Write-Host "错误：VERSION 格式非法：$releaseVersion" -ForegroundColor Red
    exit 2
}

function Show-Menu {
    $branch = (& git -C $projectRoot branch --show-current 2>$null).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($branch)) {
        $branch = '无法读取'
    }

    Write-Host ''
    Write-Host '========================================'
    Write-Host ' DD Rec 云端授权系统生产打包'
    Write-Host '========================================'
    Write-Host '[1] License-Production API'
    Write-Host '[2] License-Production Admin'
    Write-Host '[3] License-Production 全部服务'
    Write-Host '[0] 退出'
    Write-Host '========================================'
    Write-Host "项目路径：$projectRoot"
    Write-Host "Git 分支：$branch"
}

$choices = @{
    '1' = @{ Environment = 'production'; Service = 'api' }
    '2' = @{ Environment = 'production'; Service = 'admin' }
    '3' = @{ Environment = 'production'; Service = 'all' }
}

while ($true) {
    Show-Menu
    $selection = (Read-Host '请选择 0-3').Trim()
    if ($selection -eq '0') {
        Write-Host '已退出。'
        exit 0
    }
    if (-not $choices.ContainsKey($selection)) {
        Write-Host '输入无效，请输入 0 到 3。' -ForegroundColor Yellow
        continue
    }

    $choice = $choices[$selection]
    $target = Get-CloudBuildTarget `
        -ProjectRoot $projectRoot `
        -Environment $choice.Environment `
        -Service $choice.Service `
        -Version $releaseVersion
    $decision = Get-CloudBuildDecision -Target $target
    if (-not $decision.ShouldBuild) {
        Write-Host ''
        Write-Host '已取消打包，现有云端构建产物保持不变。' -ForegroundColor Yellow
        exit 0
    }

    Write-Host ''
    Write-Host "构建环境：$($choice.Environment)"
    Write-Host "构建服务：$($choice.Service)"
    try {
        $buildArguments = @{
            Environment = $choice.Environment
            Service = $choice.Service
        }
        if ($decision.UseClean) {
            $buildArguments.Clean = $true
        }
        & $buildScript @buildArguments
        $exitCode = 0
    } catch {
        Write-Host "错误：$($_.Exception.Message)" -ForegroundColor Red
        $exitCode = 1
    }
    if ($exitCode -ne 0) {
        Write-Host '构建失败' -ForegroundColor Red
        Write-Host "环境：$($choice.Environment)"
        Write-Host "服务：$($choice.Service)"
        Write-Host "退出代码：$exitCode"
        exit $exitCode
    }

    Write-Host '构建成功' -ForegroundColor Green
    Write-Host "构建环境：$($choice.Environment)"
    Write-Host "构建服务：$($choice.Service)"
    exit 0
}
