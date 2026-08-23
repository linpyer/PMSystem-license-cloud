[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidatePattern('^\d{8}-\d{6}$')][string]$SessionId,
    [switch]$WriteState,
    [string]$Confirmation
)

$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'DDREC.Release.psm1') -Force
$cloudRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$workspaceRoot=(Resolve-Path (Join-Path $cloudRoot '..')).Path
$config=Import-DDRECReleaseConfig -Path (Join-Path $PSScriptRoot 'production-config.json') -WorkspaceRoot $workspaceRoot
$context=New-DDRECReleaseContext -WorkspaceRoot $workspaceRoot -Config $config -SessionId $SessionId
$logPath=Join-Path $cloudRoot "artifacts\release-logs\$SessionId.log"
if(-not (Test-Path -LiteralPath $logPath -PathType Leaf)){throw "原发布日志不存在：$logPath"}
$log=Get-Content -LiteralPath $logPath -Raw -Encoding UTF8
if($log -notmatch "release deployed successfully:\s*(?<release>[0-9.]+-[0-9a-f]{7})"){throw '日志不能证明 Cloud release 部署成功。'}
$releaseName=$matches.release
if($log -notmatch 'DDREC_STATE Uploaded=true BackupCreated=true ReleaseInstalled=true ContainerRecreated=true CurrentSwitched=true DatabaseModified=false MigrationExecuted=false AdminReplaced=true'){throw '日志中的 Cloud 部署状态不满足安全恢复条件。'}
if($log -notmatch '"ClientUploaded"\s*:\s*false' -or $log -notmatch '"DraftCreated"\s*:\s*false' -or $log -notmatch '"PublishedCreated"\s*:\s*false'){
    throw '日志不能证明客户端、Draft 和 Published 均未完成。'
}

$remote=Get-DDRECRemoteState -Context $context
$cloudCommit=([string]$remote.BuildCommit).ToLowerInvariant()
$cloudRelease="$($config.RemoteRoot)/release/$releaseName"
if(-not $releaseName.EndsWith($cloudCommit.Substring(0,7),[StringComparison]::Ordinal)){throw '服务器 current release 名称与 API buildCommit 不一致。'}
if($log -notmatch [regex]::Escape($cloudCommit)){throw '原日志未记录当前 API buildCommit，禁止恢复。'}
$clientState=Get-DDRECGitState -Repository $context.ClientRoot
Assert-DDRECGitReleaseState -State $clientState -RequiredBranch $config.RequiredBranch | Out-Null
$targets=[Collections.Generic.List[object]]::new()
foreach($lane in @('standard','license-production')){
    $candidate=Get-DDRECInstallerCandidate -ClientRoot $context.ClientRoot -Lane $lane
    if(-not $candidate){throw "$lane 未找到安装包候选，不能重建恢复状态。"}
    $metadata=Get-DDRECInstallerMetadata -InstallerPath $candidate.FullName -Lane $lane -ExpectedCommit $clientState.Head
    $target=Get-DDRECClientTarget -Metadata $metadata -Config $config
    $remoteFinal=Test-DDRECRemoteClientTarget -Context $context -Target $target -Metadata $metadata
    if($remoteFinal.Exists){throw "$lane 最终 Build 已存在；当前失败日志与服务器事实不再匹配，禁止自动重建状态。"}
    $targets.Add([pscustomobject]@{Lane=$lane;Metadata=$metadata;Target=$target})
}

$context.Uploaded=$true
$context.BackupCreated=$true
$context.ReleaseInstalled=$true
$context.ContainerRecreated=$true
$context.CurrentSwitched=$true
$context.AdminReplaced=$true
$context.PreparedProductionArtifacts=$true
$context.ProductionApplicationModified=$true
$context.ProductionModified=$true
$state=New-DDRECReleaseSessionState -Context $context -CloudGitCommit $cloudCommit -CloudRelease $cloudRelease -ClientGitCommit $clientState.Head -DbRevision $remote.DbRevision -Targets $targets -CloudDeployed:$true
$state.CurrentSwitched=$true
$state.AdminReplaced=$true
$state.CompletedStage='CloudDeployed'
Assert-DDRECResumeProductionState -State $state -RemoteState $remote | Out-Null

Write-Host '恢复状态审核（尚未写入）：' -ForegroundColor Cyan
$state | ConvertTo-Json -Depth 12 | Write-Host
if(-not $WriteState){
    Write-Host '只读审核完成；未生成 Session state。使用 -WriteState -Confirmation RECOVER 才会原子写入。' -ForegroundColor Yellow
    exit 0
}
if($Confirmation -cne 'RECOVER'){throw '写入恢复状态需要精确确认 RECOVER。'}
if(Test-Path -LiteralPath $context.SessionStatePath){throw "Session state 已存在，禁止覆盖：$($context.SessionStatePath)"}
Write-DDRECReleaseSessionState -Context $context -State $state | Out-Null
Write-Host "恢复状态已原子写入：$($context.SessionStatePath)" -ForegroundColor Green
Write-Host '未上传客户端、未创建 Draft、未 Published、未重新部署 Cloud。'
