[CmdletBinding()]
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot 'production-config.json'),
    [switch]$ConfirmBootstrap
)

$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'DDREC.Release.psm1') -Force
$cloudRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$workspaceRoot = (Resolve-Path (Join-Path $cloudRoot '..')).Path
$config = Import-DDRECReleaseConfig -Path $ConfigPath -WorkspaceRoot $workspaceRoot
$context = New-DDRECReleaseContext -WorkspaceRoot $workspaceRoot -Config $config
$source = Join-Path $cloudRoot 'deploy\production-release'
if (-not (Test-Path -LiteralPath $source -PathType Container)) { throw "服务器工具源码不存在：$source" }

Get-ChildItem -LiteralPath $source -Filter '*.sh' -File | ForEach-Object {
    & bash -n $_.FullName
    if ($LASTEXITCODE -ne 0) { throw "Shell 语法检查失败：$($_.Name)" }
}

Write-Host 'Bootstrap 只安装版本化服务器发布工具，不部署业务、不重启 Docker、不执行 Migration。' -ForegroundColor Yellow
if (-not $ConfirmBootstrap -or (Read-Host '请输入 BOOTSTRAP 确认') -cne 'BOOTSTRAP') {
    Write-Host 'Bootstrap 已取消。'
    exit (Get-DDRECExitCodes).Cancelled
}

$staging = "$($config.RemoteRoot)/incoming/release-tools-$($context.SessionId)"
Invoke-DDRECSsh -Context $context -Command "install -d -m 750 '$staging'" | Out-Null
foreach ($file in Get-ChildItem -LiteralPath $source -Filter '*.sh' -File) {
    $copy = Invoke-DDRECNative scp @('-o','BatchMode=yes',$file.FullName,"$($config.ServerHost):$staging/$($file.Name)") -AllowFailure -Context $context
    if ($copy.ExitCode -ne 0) { throw "Bootstrap 上传失败：$($file.Name)" }
}
$expected = Get-ChildItem -LiteralPath $source -Filter '*.sh' -File | ForEach-Object { "$(($_ | Get-FileHash -Algorithm SHA256).Hash.ToLowerInvariant())  $($_.Name)" }
$encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($expected -join "`n")+"`n"))
$command = @"
set -Eeuo pipefail
stage='$staging'
target='$($config.RemoteRoot)/scripts'
cd "`$stage"
printf '%s' '$encoded' | base64 -d > SHA256SUMS.txt
sha256sum -c SHA256SUMS.txt
for f in *.sh; do bash -n "`$f"; done
backup='$($config.RemoteRoot)/backups/release-tools-$($context.SessionId)'
install -d -m 750 "`$backup" "`$target"
for f in *.sh; do if test -e "`$target/`$f"; then cp -a "`$target/`$f" "`$backup/`$f"; fi; done
for f in *.sh; do install -m 0755 "`$f" "`$target/`$f.new"; done
for f in *.sh; do mv -f "`$target/`$f.new" "`$target/`$f"; done
printf 'installed=%s\nbackup=%s\n' "`$target" "`$backup"
"@
Invoke-DDRECSsh -Context $context -Command $command -NoRetry | Out-Null
Write-DDRECLog -Context $context -Message '服务器发布工具 Bootstrap 完成；未部署任何业务。'
