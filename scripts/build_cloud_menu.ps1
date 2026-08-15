[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptRoot '..'))
$buildScript = [System.IO.Path]::GetFullPath((Join-Path $scriptRoot 'build_cloud_release.ps1'))

if (-not (Test-Path -LiteralPath $buildScript -PathType Leaf)) {
    Write-Host "错误：找不到统一构建脚本：$buildScript" -ForegroundColor Red
    exit 2
}

function Show-Menu {
    $branch = (& git -C $projectRoot branch --show-current 2>$null).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($branch)) {
        $branch = '无法读取'
    }

    Write-Host ''
    Write-Host '========================================'
    Write-Host ' DD Rec 云端授权系统一键打包'
    Write-Host '========================================'
    Write-Host '1. 本地环境 - 授权后端 API'
    Write-Host '2. 本地环境 - 管理后台前端'
    Write-Host '3. 本地环境 - 全部服务'
    Write-Host '4. 生产环境 - 授权后端 API'
    Write-Host '5. 生产环境 - 管理后台前端'
    Write-Host '6. 生产环境 - 全部服务'
    Write-Host '7. 退出'
    Write-Host '========================================'
    Write-Host "项目路径：$projectRoot"
    Write-Host "Git 分支：$branch"
}

$choices = @{
    '1' = @{ Environment = 'local'; Service = 'api' }
    '2' = @{ Environment = 'local'; Service = 'admin' }
    '3' = @{ Environment = 'local'; Service = 'all' }
    '4' = @{ Environment = 'production'; Service = 'api' }
    '5' = @{ Environment = 'production'; Service = 'admin' }
    '6' = @{ Environment = 'production'; Service = 'all' }
}

while ($true) {
    Show-Menu
    $selection = (Read-Host '请选择 1-7').Trim()
    if ($selection -eq '7') {
        Write-Host '已退出。'
        exit 0
    }
    if (-not $choices.ContainsKey($selection)) {
        Write-Host '输入无效，请输入 1 到 7。' -ForegroundColor Yellow
        continue
    }

    $choice = $choices[$selection]
    Write-Host ''
    Write-Host "构建环境：$($choice.Environment)"
    Write-Host "构建服务：$($choice.Service)"
    try {
        & $buildScript -Environment $choice.Environment -Service $choice.Service
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
