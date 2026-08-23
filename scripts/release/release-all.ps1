[CmdletBinding()]
param(
    [ValidateSet('Menu','Standard','LicenseProduction','BothClients','Cloud','CloudStandard','CloudBoth','DryRun','Status')]
    [string]$Mode = 'Menu',
    [ValidateSet('Standard','LicenseProduction','BothClients','Cloud','CloudStandard','CloudBoth')]
    [string]$DryRunScope = 'CloudBoth',
    [string]$ConfigPath = (Join-Path $PSScriptRoot 'production-config.json'),
    [switch]$NonInteractive
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$utf8 = [Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8
Import-Module (Join-Path $PSScriptRoot 'DDREC.Release.psm1') -Force
$exitCodes = Get-DDRECExitCodes
$cloudRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$workspaceRoot = (Resolve-Path (Join-Path $cloudRoot '..')).Path
$config = Import-DDRECReleaseConfig -Path $ConfigPath -WorkspaceRoot $workspaceRoot
$context = New-DDRECReleaseContext -WorkspaceRoot $workspaceRoot -Config $config
$stage = '初始化'

function Write-Header {
    param([string]$Title)
    Write-Host ''
    Write-Host ('=' * 58) -ForegroundColor Cyan
    Write-Host ("{0,-46}" -f $Title).PadLeft(54) -ForegroundColor Cyan
    Write-Host ('=' * 58) -ForegroundColor Cyan
}

function Get-ModePlan {
    param([string]$SelectedMode)
    $result = switch ($SelectedMode) {
        'Standard'          { [pscustomobject]@{Cloud=$false;Lanes=@('standard')} }
        'LicenseProduction' { [pscustomobject]@{Cloud=$false;Lanes=@('license-production')} }
        'BothClients'       { [pscustomobject]@{Cloud=$false;Lanes=@('standard','license-production')} }
        'Cloud'             { [pscustomobject]@{Cloud=$true; Lanes=@()} }
        'CloudStandard'     { [pscustomobject]@{Cloud=$true; Lanes=@('standard')} }
        'CloudBoth'         { [pscustomobject]@{Cloud=$true; Lanes=@('standard','license-production')} }
        default             { throw "未知发布模式：$SelectedMode" }
    }
    return $result
}

function Select-MenuMode {
    param($ClientState,$CloudState,$RemoteState)
    Write-Header 'DD Rec 生产发布工具'
    $version = (& (Join-Path $context.ClientRoot '.venv\Scripts\python.exe') -c 'from app.core.version import APP_VERSION; print(APP_VERSION)' 2>$null | Select-Object -Last 1)
    Write-Host "Client:`nVersion : $version`nGit     : $($ClientState.Head)"
    Write-Host "`nCloud:`nGit     : $($CloudState.Head)"
    Write-Host "`nProduction:`nAPI     : $($RemoteState.ApiStatus)`nRelease : $($RemoteState.Current)"
    Write-Host @'

请选择操作：

[1] 仅发布 Standard 客户端
[2] 仅发布 License-Production 客户端
[3] 发布 Standard + License-Production
[4] 仅部署 DD Rec 云端服务
[5] 云端服务 + Standard
[6] 云端服务 + Standard + License-Production
[7] Dry Run / 发布预检
[8] 查看当前生产状态
[0] 退出
'@
    $result = switch ((Read-Host '选择').Trim()) {
        '1' { 'Standard' }
        '2' { 'LicenseProduction' }
        '3' { 'BothClients' }
        '4' { 'Cloud' }
        '5' { 'CloudStandard' }
        '6' { 'CloudBoth' }
        '7' { 'DryRun' }
        '8' { 'Status' }
        '0' { 'Exit' }
        default { throw '菜单选择无效。' }
    }
    return $result
}

function Select-DryRunScope {
    if ($NonInteractive) { return $DryRunScope }
    Write-Host "`nDry Run 范围： [1] Standard [2] License [3] 两客户端 [4] Cloud [5] Cloud+Standard [6] 完整"
    $result = switch ((Read-Host '选择').Trim()) {
        '1' { 'Standard' }
        '2' { 'LicenseProduction' }
        '3' { 'BothClients' }
        '4' { 'Cloud' }
        '5' { 'CloudStandard' }
        default { 'CloudBoth' }
    }
    return $result
}

function Select-Installer {
    param([ValidateSet('standard','license-production')][string]$Lane,[string]$ClientCommit,[bool]$DryRun)
    $candidate = Get-DDRECInstallerCandidate -ClientRoot $context.ClientRoot -Lane $Lane
    if (-not $candidate) {
        if ($DryRun -or $NonInteractive) { throw "$Lane 未找到安装包候选。" }
        Add-Type -AssemblyName System.Windows.Forms
        $dialog=[Windows.Forms.OpenFileDialog]::new();$dialog.Filter='DD Rec Setup (*.exe)|*.exe';$dialog.Multiselect=$false
        if ($dialog.ShowDialog() -ne [Windows.Forms.DialogResult]::OK) { throw '用户取消选择安装包。' }
        $candidate=Get-Item -LiteralPath $dialog.FileName
    }
    $metadata=Get-DDRECInstallerMetadata -InstallerPath $candidate.FullName -Lane $Lane -ExpectedCommit $ClientCommit
    Write-Host "`n$Lane 安装包" -ForegroundColor Green
    $metadata | Select-Object FileName,ProductVersion,BuildNumber,GitCommit,Edition,Environment,UpdaterVersion,Size,SHA256 | Format-List
    if (-not $DryRun -and -not $NonInteractive) {
        $answer=(Read-Host '[Y] 使用 / [N] 手动选择其它安装包').Trim()
        if ($answer -notmatch '^(?i)y$') {
            Add-Type -AssemblyName System.Windows.Forms
            $dialog=[Windows.Forms.OpenFileDialog]::new();$dialog.Filter='DD Rec Setup (*.exe)|*.exe';$dialog.Multiselect=$false
            if ($dialog.ShowDialog() -ne [Windows.Forms.DialogResult]::OK) { throw '用户取消选择安装包。' }
            $metadata=Get-DDRECInstallerMetadata -InstallerPath $dialog.FileName -Lane $Lane -ExpectedCommit $ClientCommit
        }
    }
    return $metadata
}

function Show-ProductionStatus {
    param($RemoteState,$CloudState)
    Write-Header '当前生产状态（只读）'
    [pscustomobject]@{
        SSH='OK';CurrentRelease=$RemoteState.Current;ApiVersion=$RemoteState.Version;ApiCommit=$RemoteState.BuildCommit
        CloudLocalHead=$CloudState.Head
        ApiStatus=$RemoteState.ApiStatus;Database=$RemoteState.Database;DockerApi=$RemoteState.ApiContainer
        PostgreSQL=$RemoteState.PostgresContainer;AdminHttp=$RemoteState.AdminHttp;DownloadRoot=$RemoteState.DownloadRoot
        DownloadDomainRootHttp=$RemoteState.DownloadHttp;DiskAvailableGB=[math]::Round($RemoteState.DiskAvailable/1GB,2)
        DbRevision=$RemoteState.DbRevision;CodeHead=$RemoteState.CodeHead
    } | Format-List
    Write-Host '数据库核心数量：'
    $RemoteState.Counts | Format-List
    Write-Host '最新 Published（公开更新 API）：'
    foreach($lane in @('standard','license-production')){
        $release=Get-DDRECPublicRelease -Lane $lane -Config $config
        if($release.updateAvailable){
            [pscustomobject]@{Lane=$lane;Version=$release.version;Build=$release.buildNumber;Git=$release.gitCommit;Url=$release.installer.downloadUrl}|Format-List
        } else { Write-Host "$lane : 无公开更新或查询失败" -ForegroundColor Yellow }
    }
}

function Test-UpdateIsolation {
    param([Parameter(Mandatory)]$Draft)
    $lane = if($Draft.edition -eq 'standard'){'standard'}else{'license-production'}
    $public=Get-DDRECPublicRelease -Lane $lane -Config $config
    if($public.updateAvailable -and [int]$public.buildNumber -eq [int]$Draft.buildNumber -and $Draft.status -eq 'draft'){
        throw 'Draft 意外出现在正式更新 API。'
    }
    $localUrl="$($config.ApiBaseUrl)/client-updates/latest?product=DDREC&edition=license&environment=local&arch=x64&channel=dev&version=0.0.0&buildNumber=1"
    $local=Invoke-RestMethod -Uri $localUrl -TimeoutSec ([int]$config.HttpTimeoutSeconds)
    if($local.updateAvailable -and $local.environment -eq 'production'){throw 'license-local 意外获得 production stable 更新。'}
}

function Show-Plan {
    param($Plan,$ClientState,$CloudState,$RemoteState,$MigrationPlan,$Packages,$Targets)
    Write-Header '生产修改计划'
    if($Plan.Cloud){
        Write-Host "Cloud Git       : $($CloudState.Head)"
        Write-Host "目标 Release    : 1.3.0-$($CloudState.Head.Substring(0,7))"
        Write-Host "当前 Release    : $($RemoteState.Current)"
        Write-Host "Migration       : $($MigrationPlan.Current) -> $($MigrationPlan.Head)（$(@($MigrationPlan.Pending).Count) 个）"
        Write-Host "备份             : $($config.RemoteRoot)/backups/release-$($context.SessionId)"
        Write-Host 'Admin            : 部署（临时目录校验后原子替换）'
        Write-Host 'Nginx            : 配置无变化不 reload；变化默认阻止'
        if($Packages){Write-Host "Cloud Package    : $($Packages.Name) / $($Packages.SHA256)"}
    }
    foreach($item in $Targets){
        Write-Host "`n$($item.Metadata.Edition) Build $($item.Metadata.BuildNumber)"
        Write-Host "Git              : $($item.Metadata.GitCommit)"
        Write-Host "目标 URL         : $($item.Target.Url)"
        Write-Host "SHA256           : $($item.Metadata.SHA256)"
    }
}

try {
    Write-DDRECLog -Context $context -Message "发布 Session：$($context.SessionId)"
    $stage='读取 Git 状态'
    $clientState=Get-DDRECGitState -Repository $context.ClientRoot
    $cloudState=Get-DDRECGitState -Repository $context.CloudRoot
    $stage='读取生产状态'
    $remoteState=Get-DDRECRemoteState -Context $context

    if($Mode -eq 'Menu'){$Mode=Select-MenuMode -ClientState $clientState -CloudState $cloudState -RemoteState $remoteState}
    if($Mode -eq 'Exit'){exit $exitCodes.Success}
    if($Mode -eq 'Status'){
        Show-ProductionStatus -RemoteState $remoteState -CloudState $cloudState
        Add-DDRECStage -Context $context -Stage 'Production Status（只读）'
        exit $exitCodes.Success
    }
    $dryRun=$Mode -eq 'DryRun'
    if($dryRun){$Mode=Select-DryRunScope}
    $plan=Get-ModePlan $Mode

    $stage='Preflight / Git 安全检查'
    if($plan.Lanes.Count -gt 0){Assert-DDRECGitReleaseState -State $clientState -RequiredBranch $config.RequiredBranch|Out-Null}
    if($plan.Cloud){Assert-DDRECGitReleaseState -State $cloudState -RequiredBranch $config.RequiredBranch|Out-Null}
    Assert-DDRECDiskSpace -AvailableBytes $remoteState.DiskAvailable -RequiredBytes ([int64]$config.MinimumFreeBytes)|Out-Null
    if($remoteState.ApiStatus -ne 'ok' -or $remoteState.Database -ne 'ok' -or $remoteState.AdminHttp -ne 200 -or $remoteState.ApiContainer -ne 'healthy' -or $remoteState.PostgresContainer -ne 'healthy'){
        throw '生产 API、Admin、Docker 或 PostgreSQL 预检失败。'
    }
    if($remoteState.DownloadRoot -ne $config.DownloadRoot){throw "Nginx 下载 root 与配置不一致：$($remoteState.DownloadRoot)"}
    if($plan.Lanes.Count -gt 0 -and -not (Test-Path -LiteralPath $config.UpdatePrivateKey -PathType Leaf)){throw '本地更新签名私钥不存在。'}
    Add-DDRECStage -Context $context -Stage 'Preflight'

    $stage='客户端安装包识别与真实性校验'
    $targets=[Collections.Generic.List[object]]::new()
    foreach($lane in $plan.Lanes){
        $metadata=Select-Installer -Lane $lane -ClientCommit $clientState.Head -DryRun $dryRun
        $target=Get-DDRECClientTarget -Metadata $metadata -Config $config
        $remoteTarget=Test-DDRECRemoteClientTarget -Context $context -Target $target -Metadata $metadata
        $targets.Add([pscustomobject]@{Lane=$lane;Metadata=$metadata;Target=$target;Remote=$remoteTarget;Signed=$null;Draft=$null})
    }
    if($plan.Lanes.Count -gt 0){Add-DDRECStage -Context $context -Stage '客户端安装包验证'}

    $migrationPlan=$null
    if($plan.Cloud){
        $stage='Migration 分析'
        $migrationPlan=Get-DDRECLocalMigrationPlan -CloudRoot $context.CloudRoot -CurrentRevision $remoteState.DbRevision
        if($migrationPlan.Destructive){throw "发现破坏性 Migration，默认停止：$($migrationPlan.DestructiveMatches -join ', ')"}
        Add-DDRECStage -Context $context -Stage 'Migration 只读分析'
    }

    if($dryRun){
        Show-Plan -Plan $plan -ClientState $clientState -CloudState $cloudState -RemoteState $remoteState -MigrationPlan $migrationPlan -Packages $null -Targets $targets
        Write-Header 'Dry Run 结果'
        Write-Host 'PASS：未上传、未备份、未部署、未 Migration、未修改数据库、未创建 Draft、未 Published、未 reload。' -ForegroundColor Green
        Add-DDRECStage -Context $context -Stage 'Dry Run（只读）'
        exit $exitCodes.Success
    }

    $package=$null
    if($plan.Cloud){
        $stage='构建 Cloud 生产发布包（本地）'
        $package=Invoke-DDRECCloudBuild -Context $context
        Add-DDRECStage -Context $context -Stage 'Cloud 本地发布包准备'
    }
    Show-Plan -Plan $plan -ClientState $clientState -CloudState $cloudState -RemoteState $remoteState -MigrationPlan $migrationPlan -Packages $package -Targets $targets
    if($NonInteractive -or (Read-Host '请输入 DEPLOY 才允许生产写操作') -cne 'DEPLOY'){
        Write-DDRECLog -Context $context -Level WARN -Message '用户取消 DEPLOY；生产未修改。'
        exit $exitCodes.Cancelled
    }

    $approveMigration=$false
    if($plan.Cloud -and @($migrationPlan.Pending).Count -gt 0){
        Write-Host "发现数据库 Migration：$($migrationPlan.Current) -> $($migrationPlan.Head)" -ForegroundColor Yellow
        if((Read-Host '是否执行 Migration？[Y/N]') -notmatch '^(?i)y$'){throw '用户拒绝 pending Migration，部署停止。'}
        $approveMigration=$true
    }
    if($plan.Cloud){
        $stage='Cloud 备份/部署/Migration/Admin/Health'
        Invoke-DDRECCloudDeploy -Context $context -Package $package -CloudCommit $cloudState.Head -ApproveMigration $approveMigration|Out-Null
        $context.MigrationExecuted=$approveMigration
        $postCloud=Get-DDRECRemoteState -Context $context
        Assert-DDRECHealthSnapshot -Snapshot ([pscustomobject]@{ApiStatus=$postCloud.ApiStatus;Database=$postCloud.Database;AdminHttp=$postCloud.AdminHttp;ApiContainerHealthy=$postCloud.ApiContainer -eq 'healthy';PostgresHealthy=$postCloud.PostgresContainer -eq 'healthy';BuildCommit=$postCloud.BuildCommit}) -ExpectedCommit $cloudState.Head|Out-Null
        Assert-DDRECCoreCounts -Before $remoteState.Counts -After $postCloud.Counts|Out-Null
        Add-DDRECStage -Context $context -Stage 'Cloud 生产部署与健康检查'
    }

    foreach($item in $targets){
        $stage="客户端上传：$($item.Lane)"
        Invoke-DDRECClientUpload -Context $context -Metadata $item.Metadata -Target $item.Target|Out-Null
        Test-DDRECDownloadUrl -Url $item.Target.Url -ExpectedLength $item.Metadata.Size -TimeoutSeconds ([int]$config.HttpTimeoutSeconds)|Out-Null
        $item.Signed=Invoke-DDRECManifestSigning -Context $context -Metadata $item.Metadata
        Add-DDRECStage -Context $context -Stage "$($item.Lane) 上传/SHA/下载/Range/签名"
    }

    if($targets.Count -gt 0){
        $stage='OWNER 登录与 Draft 创建'
        $auth=Connect-DDRECAdminApi -Context $context
        foreach($item in $targets){
            $item.Draft=New-DDRECClientDraft -Context $context -Auth $auth -Metadata $item.Metadata -Target $item.Target -Signed $item.Signed
            Test-UpdateIsolation -Draft $item.Draft
        }
        Add-DDRECStage -Context $context -Stage 'Draft 创建与更新通道隔离验证'
        Write-Header '发布确认'
        foreach($item in $targets){
            Write-Host "$($item.Lane): V$($item.Metadata.ProductVersion) Build $($item.Metadata.BuildNumber) / $($item.Metadata.SHA256) / $($item.Draft.status.ToUpperInvariant())"
        }
        $publishable=@(for($i=0;$i -lt $targets.Count;$i++){if($targets[$i].Draft.status -eq 'draft'){$i}})
        if($publishable.Count -eq 0){Write-DDRECLog -Context $context -Message '相同 Build 已 Published；幂等完成，没有创建重复记录。';exit $exitCodes.Success}
        Write-Host "`n默认保持 Draft。只有先选择目标并再次输入 PUBLISH 才会发布。"
        $publishSelection=if($publishable.Count -eq 1){ if((Read-Host '[1] 发布唯一 Draft / [4] 保持 Draft / [0] 退出') -eq '1'){@($publishable[0])}else{@()} } else {
            switch(Read-Host '[1] Standard [2] License-Production [3] 两个 [4] 全部保持 Draft [0] 退出'){'1'{@(0)}'2'{@(1)}'3'{@(0,1)}default{@()}}
        }
        if($publishSelection.Count -gt 0 -and (Read-Host '请输入 PUBLISH 二次确认') -ceq 'PUBLISH'){
            $stage='Published API'
            foreach($index in $publishSelection){Publish-DDRECClientDraft -Context $context -Auth $auth -Draft $targets[$index].Draft|Out-Null}
            Add-DDRECStage -Context $context -Stage 'Published（最后一步）'
        } else {Write-DDRECLog -Context $context -Level WARN -Message '所有目标保持 Draft；没有 Published。'}
    }
    Write-DDRECLog -Context $context -Message "流程完成。日志：$($context.LogPath)"
    exit $exitCodes.Success
}
catch {
    $report=Get-DDRECFailureReport -Context $context -Stage $stage -ErrorRecord $_
    Write-Header '发布停止'
    Write-DDRECLog -Context $context -Level ERROR -Message ($report|ConvertTo-Json -Depth 6)
    $code=if($stage -match '安装包|客户端'){$exitCodes.ClientValidation}elseif($stage -match 'Migration'){$exitCodes.Migration}elseif($stage -match 'Health'){$exitCodes.Health}elseif($stage -match 'Draft|Published|OWNER'){$exitCodes.PublishApi}elseif($stage -match '上传'){$exitCodes.Upload}else{$exitCodes.Preflight}
    exit $code
}
