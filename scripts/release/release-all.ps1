[CmdletBinding()]
param(
    [ValidateSet('Menu','Standard','LicenseProduction','BothClients','Cloud','CloudStandard','CloudBoth','DryRun','Status','Resume')]
    [string]$Mode = 'Menu',
    [ValidateSet('Standard','LicenseProduction','BothClients','Cloud','CloudStandard','CloudBoth')]
    [string]$DryRunScope = 'CloudBoth',
    [ValidateSet('','auto','manual')]
    [string]$ClientUploadMode = '',
    [string]$ConfigPath = (Join-Path $PSScriptRoot 'production-config.json'),
    [string]$ResumeSessionId,
    [switch]$NonInteractive,
    [switch]$MenuPerf
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
$sessionState = $null
$menuPerfEnabled = $MenuPerf -or $env:DDREC_MENU_PERF -eq '1'

function Write-Header {
    param([string]$Title)
    Write-Host ''
    Write-Host ('=' * 58) -ForegroundColor Cyan
    Write-Host ("{0,-46}" -f $Title).PadLeft(54) -ForegroundColor Cyan
    Write-Host ('=' * 58) -ForegroundColor Cyan
}

function Get-MenuClientVersion {
    return Get-DDRECClientApplicationVersion -ClientRoot $context.ClientRoot
}

function Initialize-ReleaseMenuCache {
    $measure=[Diagnostics.Stopwatch]::StartNew()
    $clientVersion=Get-MenuClientVersion
    $clientInfoMs=$measure.Elapsed.TotalMilliseconds
    $measure.Restart()
    $clientHead=Get-DDRECLocalGitHead -Repository $context.ClientRoot
    $clientGitMs=$measure.Elapsed.TotalMilliseconds
    $measure.Restart()
    $cloudHead=Get-DDRECLocalGitHead -Repository $context.CloudRoot
    $cloudGitMs=$measure.Elapsed.TotalMilliseconds
    $measure.Restart()
    $overview=Get-DDRECMenuProductionOverview -Context $context
    $productionMs=$measure.Elapsed.TotalMilliseconds
    $measure.Stop()
    if($menuPerfEnabled){
        Write-Host ('[PERF] Initialize ClientInfo={0:N1} ms ClientGit={1:N1} ms CloudGit={2:N1} ms ProductionOverview={3:N1} ms' -f $clientInfoMs,$clientGitMs,$cloudGitMs,$productionMs) -ForegroundColor DarkGray
    }
    return [pscustomobject]@{
        ClientVersion=$clientVersion
        ClientHead=$clientHead
        CloudHead=$cloudHead
        ProductionApi=$overview.Api
        ProductionRelease=$overview.Release
        LastProductionCheck=$overview.CheckedAt
    }
}

function Update-ReleaseMenuLocalCache {
    param([Parameter(Mandatory)]$Cache)
    # Local-only refresh is deliberately completed before the Enter prompt. It
    # never performs git status/fetch/origin or any production network request.
    try{$Cache.ClientHead=Get-DDRECLocalGitHead -Repository $context.ClientRoot}catch{}
    try{$Cache.CloudHead=Get-DDRECLocalGitHead -Repository $context.CloudRoot}catch{}
}

function Show-DDRECReleaseMenu {
    param([Parameter(Mandatory)]$Cache)
    Write-Header 'DD Rec 生产发布工具'
    Write-Host "Client:`nVersion : $($Cache.ClientVersion)`nGit     : $($Cache.ClientHead)"
    Write-Host "`nCloud:`nGit     : $($Cache.CloudHead)"
    Write-Host "`nProduction:`nAPI     : $($Cache.ProductionApi)`nRelease : $($Cache.ProductionRelease)"
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
[9] 继续未完成发布 / Resume Release
[0] 退出
'@
}

function Read-ReleaseMenuMode {
    Sync-DDRECConsoleOutput
    while($true){
        $result=Get-DDRECMainMenuAction -InputText (Read-Host '请选择 [0-9]')
        if($result -ne 'Invalid'){return $result}
        Write-Host '菜单选择无效，请输入 0～9。' -ForegroundColor Yellow
    }
}

function Select-DryRunScope {
    if ($NonInteractive) { return $DryRunScope }
    Write-Host "`nDry Run 范围："
    Write-Host ''
    Write-Host '[1] Standard'
    Write-Host '[2] License-Production'
    Write-Host '[3] Standard + License-Production'
    Write-Host '[4] Cloud'
    Write-Host '[5] Cloud + Standard'
    Write-Host '[6] Cloud + Standard + License-Production'
    Write-Host ''
    Sync-DDRECConsoleOutput
    $result = switch ((Read-Host '请选择 [1-6]').Trim()) {
        '1' { 'Standard' }
        '2' { 'LicenseProduction' }
        '3' { 'BothClients' }
        '4' { 'Cloud' }
        '5' { 'CloudStandard' }
        default { 'CloudBoth' }
    }
    return $result
}

function Invoke-ReleaseMenuLoop {
    $pwsh=Join-Path $PSHOME 'pwsh.exe'
    if(-not (Test-Path -LiteralPath $pwsh -PathType Leaf)){throw "PowerShell 7 运行文件不存在：$pwsh"}
    try{
        $menuCache=Initialize-ReleaseMenuCache
    }catch{
        throw "无法初始化本地发布菜单：$($_.Exception.Message)"
    }
    $enterReturnWatch=$null
    while($true){
        $renderWatch=[Diagnostics.Stopwatch]::StartNew()
        Show-DDRECReleaseMenu -Cache $menuCache
        $renderWatch.Stop()
        if($menuPerfEnabled){
            $returnMs=if($null -eq $enterReturnWatch){0}else{$enterReturnWatch.Elapsed.TotalMilliseconds}
            Write-Host ('[PERF] MenuRender={0:N1} ms EnterReturn={1:N1} ms' -f $renderWatch.Elapsed.TotalMilliseconds,$returnMs) -ForegroundColor DarkGray
        }
        $enterReturnWatch=$null
        $selectedMode=Read-ReleaseMenuMode
        if($selectedMode -eq 'Exit'){return}
        $arguments=@('-NoLogo','-NoProfile','-ExecutionPolicy','Bypass','-File',$PSCommandPath,'-Mode',$selectedMode,'-ConfigPath',$ConfigPath)
        $taskExitCode=0
        Invoke-DDRECConsoleTask -PwshPath $pwsh -Arguments $arguments -ExitCode ([ref]$taskExitCode) -MenuCache $menuCache
        Update-ReleaseMenuLocalCache -Cache $menuCache
        Write-DDRECLog -Context $context -Message "菜单任务结束：Mode=$selectedMode ExitCode=$taskExitCode"
        Write-Header '本次任务已结束'
        $modeDisplay=switch($selectedMode){
            'Status'{'Production Status'}
            'DryRun'{'Dry Run'}
            'Resume'{'Resume Release'}
            default{$selectedMode}
        }
        Write-Host "Mode     ：$modeDisplay"
        Write-Host "ExitCode ：$taskExitCode"
        if($taskExitCode -eq 0){
            Write-Host '结果     ：成功' -ForegroundColor Green
        }else{
            Write-Host '结果     ：本次任务已停止或失败' -ForegroundColor Yellow
            Write-Host '生产状态请参考以上报告。'
        }
        [void](Read-Host '按 Enter 返回主菜单')
        $enterReturnWatch=[Diagnostics.Stopwatch]::StartNew()
    }
}

function Select-ClientUploadMode {
    param([string]$CurrentMode='')
    if($NonInteractive){
        if($ClientUploadMode -notin @('auto','manual')){throw '非交互客户端发布必须明确指定 -ClientUploadMode auto 或 manual。'}
        return $ClientUploadMode
    }
    Write-Header '客户端安装包上传方式'
    if($CurrentMode -in @('auto','manual')){
        $display=if($CurrentMode -eq 'auto'){'自动'}else{'手动'}
        Write-Host "当前 Session 上传模式：$display（客户端尚未完成时可切换）`n"
    }
    Write-Host @'
[1] 自动上传
    脚本自动将安装包上传到服务器并完成校验

[2] 手动上传
    使用 WinSCP / SFTP 手动上传，脚本负责后续校验

[0] 取消
'@
    Write-Host ''
    Sync-DDRECConsoleOutput
    while($true){
        $selection=Get-DDRECClientUploadModeAction -InputText (Read-Host '请选择 [1/2/0]')
        if($selection -ne 'invalid'){return $selection}
        Write-Host '必须明确选择 1、2 或 0；直接按 Enter 不会启动网络传输。' -ForegroundColor Yellow
    }
}

function Select-Installer {
    param(
        [ValidateSet('standard','license-production')][string]$Lane,
        [string]$ClientCommit,
        [string]$ClientVersion,
        [bool]$DryRun
    )
    $candidate = Get-DDRECInstallerCandidate -ClientRoot $context.ClientRoot -Lane $Lane
    if (-not $candidate) {
        if ($DryRun -or $NonInteractive) { throw "$Lane 未找到安装包候选。" }
        Add-Type -AssemblyName System.Windows.Forms
        $dialog=[Windows.Forms.OpenFileDialog]::new();$dialog.Filter='DD Rec Setup (*.exe)|*.exe';$dialog.Multiselect=$false
        if ($dialog.ShowDialog() -ne [Windows.Forms.DialogResult]::OK) { throw '用户取消选择安装包。' }
        $candidate=Get-Item -LiteralPath $dialog.FileName
    }
    $metadata=Get-DDRECInstallerMetadata -InstallerPath $candidate.FullName -Lane $Lane -ExpectedCommit $ClientCommit -ExpectedVersion $ClientVersion
    Write-Host "`n$Lane 安装包" -ForegroundColor Green
    Write-Host ''
    Show-DDRECPackageMetadata -Metadata $metadata
    if (-not $DryRun -and -not $NonInteractive) {
        Write-Host ''
        Sync-DDRECConsoleOutput
        $answer=(Read-Host '[Y] 使用 / [N] 手动选择其它安装包').Trim()
        if ($answer -notmatch '^(?i)y$') {
            Add-Type -AssemblyName System.Windows.Forms
            $dialog=[Windows.Forms.OpenFileDialog]::new();$dialog.Filter='DD Rec Setup (*.exe)|*.exe';$dialog.Multiselect=$false
            if ($dialog.ShowDialog() -ne [Windows.Forms.DialogResult]::OK) { throw '用户取消选择安装包。' }
            $metadata=Get-DDRECInstallerMetadata -InstallerPath $dialog.FileName -Lane $Lane -ExpectedCommit $ClientCommit -ExpectedVersion $ClientVersion
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
}

function Show-Plan {
    param($Plan,$ClientState,$CloudState,$RemoteState,$MigrationPlan,$Packages,$Targets)
    Write-Header '生产修改计划'
    if($Plan.Cloud){
        Write-Host "Cloud Git       : $($CloudState.Head)"
        Write-Host "目标 Release    : $($Packages.Version)-$($CloudState.Head.Substring(0,7))"
        Write-Host "当前 Release    : $($RemoteState.Current)"
        Write-Host "Migration       : $($MigrationPlan.Current) -> $($MigrationPlan.Head)（$(@($MigrationPlan.Pending).Count) 个）"
        Write-Host "备份             : $($config.RemoteRoot)/backups/release-$($context.SessionId)"
        Write-Host 'Admin            : 部署（临时目录校验后原子替换）'
        Write-Host 'Nginx            : 配置无变化不 reload；变化默认阻止'
        if($Packages){Write-Host "Cloud Package    : $($Packages.FileName) / $($Packages.SHA256)"}
    }
    foreach($item in $Targets){
        Write-Host "`n$($item.Metadata.Edition) Build $($item.Metadata.BuildNumber)"
        Write-Host "Git              : $($item.Metadata.GitCommit)"
        Write-Host "目标 URL         : $($item.Target.Url)"
        Write-Host "SHA256           : $($item.Metadata.SHA256)"
    }
}

function Get-SessionClientItem {
    param($State,[string]$Lane)
    if($Lane -eq 'standard'){return $State.Standard}
    return $State.License
}

function Save-ReleaseSession {
    param($State,[string]$CompletedStage)
    if($null -eq $State){return}
    Update-DDRECReleaseSessionFromContext -Context $context -State $State -CompletedStage $CompletedStage | Out-Null
}

function Invoke-ClientPackageStages {
    param([object[]]$Targets,$State,[Parameter(Mandatory)][ValidateSet('auto','manual')][string]$UploadMode)
    $activeMode=$UploadMode
    Set-DDRECSessionUploadMode -State $State -Mode $activeMode|Out-Null
    Save-ReleaseSession -State $State -CompletedStage $State.CompletedStage
    foreach($item in $Targets){
        $stateItem=Get-SessionClientItem -State $State -Lane $item.Lane
        $script:stage="客户端安装包上传：$($item.Lane)"
        $remote=Test-DDRECRemoteClientTarget -Context $context -Target $item.Target -Metadata $item.Metadata
        if($remote.Exists){
            $stateItem.Uploaded=$true; $stateItem.Installed=$true
            Write-DDRECLog -Context $context -Message "$($item.Lane) 最终不可变文件已存在且 size/SHA 一致，幂等复用。"
        } else {
            while($true){
                if($activeMode -eq 'manual'){
                    $upload=Wait-DDRECManualClientUpload -Context $context -Metadata $item.Metadata -Lane $item.Lane -NonInteractive:$NonInteractive
                    if($upload.Action -ne 'Verified'){
                        Save-ReleaseSession -State $State -CompletedStage "Awaiting-$($item.Lane)-Upload"
                        Write-DDRECLog -Context $context -Level WARN -Message "Cloud部署：成功；客户端发布：未完成；线上API：正常。已保存 Session，可使用 Resume Release 继续。"
                        return $false
                    }
                    break
                }
                $upload=Invoke-DDRECAutomaticClientUpload -Context $context -Metadata $item.Metadata
                if($upload.Action -eq 'Verified'){
                    Write-Host "自动上传验证 PASS：$($upload.Status.SelectedFileName) / $($upload.Status.ExpectedSize) bytes / $($upload.Status.ExpectedSHA256)" -ForegroundColor Green
                    break
                }
                Write-Host "`n自动上传失败：$($upload.Reason)" -ForegroundColor Yellow
                if($NonInteractive){
                    Save-ReleaseSession -State $State -CompletedStage "Awaiting-$($item.Lane)-Upload"
                    return $false
                }
                Write-Host '[1] 重试自动上传'
                Write-Host '[2] 切换为人工上传'
                Write-Host '[3] 保存 Session 并返回主菜单'
                Write-Host ''
                Sync-DDRECConsoleOutput
                $failureAction=Get-DDRECAutoUploadFailureAction -InputText (Read-Host '请选择 [1/2/3]')
                if($failureAction -eq 'Retry'){continue}
                if($failureAction -eq 'Manual'){
                    $activeMode='manual'
                    Set-DDRECSessionUploadMode -State $State -Mode manual|Out-Null
                    Save-ReleaseSession -State $State -CompletedStage "Awaiting-$($item.Lane)-Upload"
                    Write-DDRECLog -Context $context -Message '客户端上传模式已从 auto 切换为 manual；不会重新执行 Cloud 部署。'
                    continue
                }
                if($failureAction -eq 'Save'){
                    Save-ReleaseSession -State $State -CompletedStage "Awaiting-$($item.Lane)-Upload"
                    return $false
                }
                Write-Host '请输入 1、2 或 3。' -ForegroundColor Yellow
            }
            $stateItem.Uploaded=$true
            Save-ReleaseSession -State $State -CompletedStage "$($item.Lane)-IncomingVerified"
            Install-DDRECVerifiedClientPackage -Context $context -Metadata $item.Metadata -Target $item.Target | Out-Null
            $stateItem.Installed=$true
        }
        $script:stage="客户端最终下载验证：$($item.Lane)"
        $final=Test-DDRECRemoteClientTarget -Context $context -Target $item.Target -Metadata $item.Metadata
        if(-not $final.Exists){throw '客户端最终不可变文件在安装后不存在。'}
        $probe=Test-DDRECDownloadUrl -Url $item.Target.Url -ExpectedLength $item.Metadata.FileSize -TimeoutSeconds ([int]$config.HttpTimeoutSeconds)
        Write-DDRECLog -Context $context -Message "$($item.Lane) 下载验证 PASS：HTTP=$($probe.StatusCode) Range=$($probe.RangeStatusCode) Size=$($probe.ContentLength) SHA=$($final.SHA256)"
        $item.Signed=Invoke-DDRECManifestSigning -Context $context -Metadata $item.Metadata
        $stateItem.Verified=$true
        Save-ReleaseSession -State $State -CompletedStage "$($item.Lane)-DownloadVerified"
        Add-DDRECStage -Context $context -Stage "$($item.Lane) $activeMode 上传/SHA/原子安装/HTTP 200/Range 206/签名"
    }
    Merge-DDRECReleaseSessionContext -Context $context -State $State | Out-Null
    return $true
}

function Invoke-ClientDraftAndPublishStages {
    param([object[]]$Targets,$State)
    if($Targets.Count -eq 0){return}
    $script:stage='OWNER 登录'
    $login=Start-DDRECAdminLogin -Context $context
    Add-DDRECStage -Context $context -Stage 'OWNER 登录'
    $script:stage='OWNER TOTP 验证'
    $auth=Complete-DDRECAdminTotp -Context $context -Login $login
    Add-DDRECStage -Context $context -Stage 'OWNER TOTP 验证'
    foreach($item in $Targets){
        $script:stage=if($item.Lane -eq 'standard'){'Standard Draft 创建'}else{'License Draft 创建'}
        $item.Draft=New-DDRECClientDraft -Context $context -Auth $auth -Metadata $item.Metadata -Target $item.Target -Signed $item.Signed
        Test-UpdateIsolation -Draft $item.Draft
        $stateItem=Get-SessionClientItem -State $State -Lane $item.Lane
        $stateItem.DraftId=$item.Draft.id; $stateItem.DraftStatus=$item.Draft.status
        if($item.Draft.status -eq 'published'){$stateItem.Published=$true}
        Save-ReleaseSession -State $State -CompletedStage 'DraftReady'
        Add-DDRECStage -Context $context -Stage $script:stage
    }
    Add-DDRECStage -Context $context -Stage 'Draft 创建/幂等复用与更新通道隔离验证'
    Write-Header '发布确认'
    foreach($item in $Targets){Write-Host "$($item.Lane): V$($item.Metadata.Version) Build $($item.Metadata.BuildNumber) / $($item.Metadata.SHA256) / $($item.Draft.status.ToUpperInvariant())"}
    $publishable=@(for($i=0;$i -lt $Targets.Count;$i++){if($Targets[$i].Draft.status -eq 'draft'){$i}})
    if($publishable.Count -eq 0){
        Write-DDRECLog -Context $context -Message '相同 Build 已 Published；幂等完成，没有创建重复记录。'
        Save-ReleaseSession -State $State -CompletedStage 'Completed'
        return
    }
    Write-Host "`n默认保持 Draft。只有先选择目标并再次输入 PUBLISH 才会发布。"
    Write-Host ''
    $publishSelection=if($publishable.Count -eq 1){
        Write-Host '[1] 发布唯一 Draft'
        Write-Host '[4] 保持 Draft'
        Write-Host '[0] 退出'
        Write-Host ''
        Sync-DDRECConsoleOutput
        if((Read-Host '请选择 [0/1/4]') -eq '1'){@($publishable[0])}else{@()}
    }else{
        Write-Host '[1] Standard'
        Write-Host '[2] License-Production'
        Write-Host '[3] 两个'
        Write-Host '[4] 全部保持 Draft'
        Write-Host '[0] 退出'
        Write-Host ''
        Sync-DDRECConsoleOutput
        switch(Read-Host '请选择 [0-4]'){'1'{@(0)}'2'{@(1)}'3'{@(0,1)}default{@()}}
    }
    if($publishSelection.Count -gt 0){Sync-DDRECConsoleOutput}
    if($publishSelection.Count -gt 0 -and (Read-Host '请输入 PUBLISH 二次确认') -ceq 'PUBLISH'){
        $script:stage='Published API'
        foreach($index in $publishSelection){
            Publish-DDRECClientDraft -Context $context -Auth $auth -Draft $Targets[$index].Draft | Out-Null
            (Get-SessionClientItem -State $State -Lane $Targets[$index].Lane).Published=$true
        }
        Add-DDRECStage -Context $context -Stage 'Published（最后一步）'
        Save-ReleaseSession -State $State -CompletedStage 'Completed'
    } else {
        Write-DDRECLog -Context $context -Level WARN -Message '所有目标保持 Draft；没有 Published。'
        Save-ReleaseSession -State $State -CompletedStage 'DraftReady'
    }
}

function Get-ResumeTargets {
    param($State)
    $items=[Collections.Generic.List[object]]::new()
    $entries=@(
        [pscustomobject]@{Lane='standard';SessionItem=$State.Standard},
        [pscustomobject]@{Lane='license-production';SessionItem=$State.License}
    )
    foreach($entry in $entries){
        $lane=[string]$entry.Lane;$sessionItem=$entry.SessionItem
        if($null -eq $sessionItem){continue}
        $metadata=Get-DDRECInstallerMetadata -InstallerPath ([string]$sessionItem.Path) -Lane $lane -ExpectedCommit ([string]$State.ClientGitCommit) -ExpectedVersion ([string]$sessionItem.Version)
        Assert-DDRECSessionClientMetadata -SessionItem $sessionItem -Metadata $metadata | Out-Null
        $target=Get-DDRECClientTarget -Metadata $metadata -Config $config
        if($target.RemotePath -cne [string]$sessionItem.RemoteFinalPath -or $target.Url -cne [string]$sessionItem.DownloadUrl){throw 'Resume 阻止：客户端最终路径或 URL 与 Session 不一致。'}
        $items.Add([pscustomobject]@{Lane=$lane;Metadata=$metadata;Target=$target;Remote=$null;Signed=$null;Draft=$null})
    }
    return $items
}

if($Mode -eq 'Menu'){
    Invoke-ReleaseMenuLoop
    exit $exitCodes.Success
}

try {
    $stage='读取 Git 状态'
    $clientState=Get-DDRECGitState -Repository $context.ClientRoot
    $cloudState=Get-DDRECGitState -Repository $context.CloudRoot
    $clientVersion=Get-DDRECClientApplicationVersion -ClientRoot $context.ClientRoot
    $stage='读取生产状态'
    $remoteState=Get-DDRECRemoteState -Context $context

    if($Mode -eq 'Resume'){
        if([string]::IsNullOrWhiteSpace($ResumeSessionId)){
            $latest=Get-DDRECLatestIncompleteSessionState -Context $context
            if($null -eq $latest){throw '没有可恢复的未完成发布 Session。'}
            $ResumeSessionId=[string]$latest.SessionId
        }
        $context=New-DDRECReleaseContext -WorkspaceRoot $workspaceRoot -Config $config -SessionId $ResumeSessionId
        Write-DDRECLog -Context $context -Message "Resume Release Session：$($context.SessionId)"
        $stage='读取并验证 Resume Session'
        $sessionState=Read-DDRECReleaseSessionState -Context $context -SessionId $ResumeSessionId
        Assert-DDRECClientReleaseState -State $clientState -ClientVersion $clientVersion | Out-Null
        Assert-DDRECResumeProductionState -State $sessionState -RemoteState $remoteState | Out-Null
        if(-not (Test-Path -LiteralPath $config.UpdatePrivateKey -PathType Leaf)){throw '本地更新签名私钥不存在。'}
        Merge-DDRECReleaseSessionContext -Context $context -State $sessionState | Out-Null
        Write-Header '继续未完成发布'
        [pscustomobject]@{
            Session=$sessionState.SessionId;Cloud='已部署成功';Current=$remoteState.Current;ApiCommit=$remoteState.BuildCommit
            ClientUploaded=$context.ClientUploaded
            DraftCreated=$sessionState.DraftCreated;Published=$sessionState.Published;CompletedStage=$sessionState.CompletedStage
        }|Format-List
        $resumeUploadMode=Get-DDRECSessionUploadMode -State $sessionState
        $resumeUploadModeDisplay=if($resumeUploadMode -eq 'auto'){'自动'}else{'手动'}
        Write-Host "客户端上传模式：$resumeUploadModeDisplay"
        Write-DDRECLog -Context $context -Message "Resume 使用 Session 固定的客户端 GitCommit=$($sessionState.ClientGitCommit) 重新验证原安装包；不会使用当前 HEAD 替换 Session 包。"
        Write-DDRECLog -Context $context -Message 'Resume 仅从客户端上传/Draft 阶段继续；不会重新构建、上传或部署 Cloud。'
        $targets=Get-ResumeTargets -State $sessionState
        $incompleteClientItems=@(@($sessionState.Standard,$sessionState.License)|Where-Object{$null -ne $_ -and -not ([bool]$_.Installed -and [bool]$_.Verified)})
        if($incompleteClientItems.Count -gt 0){
            $resumeUploadMode=Select-ClientUploadMode -CurrentMode $resumeUploadMode
            if($resumeUploadMode -eq 'cancel'){
                Write-DDRECLog -Context $context -Level WARN -Message '用户取消 Resume 客户端上传；Session 已保留。'
                exit $exitCodes.Cancelled
            }
            Set-DDRECSessionUploadMode -State $sessionState -Mode $resumeUploadMode|Out-Null
            Save-ReleaseSession -State $sessionState -CompletedStage $sessionState.CompletedStage
        }
        if(-not (Invoke-ClientPackageStages -Targets $targets -State $sessionState -UploadMode $resumeUploadMode)){exit $exitCodes.Cancelled}
        Invoke-ClientDraftAndPublishStages -Targets $targets -State $sessionState
        Write-DDRECLog -Context $context -Message "Resume 流程完成。日志：$($context.LogPath)"
        exit $exitCodes.Success
    }
    Write-DDRECLog -Context $context -Message "发布 Session：$($context.SessionId)"
    if($Mode -eq 'Status'){
        Show-ProductionStatus -RemoteState $remoteState -CloudState $cloudState
        Add-DDRECStage -Context $context -Stage 'Production Status（只读）'
        exit $exitCodes.Success
    }
    $dryRun=$Mode -eq 'DryRun'
    if($dryRun){$Mode=Select-DryRunScope}
    $plan=Get-DDRECModePlan -Mode $Mode

    $stage='Preflight / Git 安全检查'
    if($plan.Lanes.Count -gt 0){Assert-DDRECClientReleaseState -State $clientState -ClientVersion $clientVersion|Out-Null}
    if($plan.Cloud){Assert-DDRECGitReleaseState -State $cloudState -RequiredBranch $config.RequiredCloudBranch|Out-Null}
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
        $metadata=Select-Installer -Lane $lane -ClientCommit $clientState.Head -ClientVersion $clientVersion -DryRun $dryRun
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

    $package=$null
    if($plan.Cloud){
        $stage='Cloud 生产发布包识别与真实性校验'
        $cloudVersion=(Get-Content -LiteralPath (Join-Path $context.CloudRoot 'VERSION') -Raw -Encoding UTF8).Trim()
        $packageState=Get-DDRECCloudPackageState -CloudRoot $context.CloudRoot -ExpectedCommit $cloudState.Head -ExpectedVersion $cloudVersion -ExpectedBranch $config.RequiredCloudBranch
        if($packageState.IsValid){
            Write-Host "`nCloud 生产发布包" -ForegroundColor Green
            Show-DDRECCloudPackageMetadata -Metadata $packageState.Metadata
        }
        $decision=Get-DDRECCloudPackageDecision -State $packageState -DryRun:$dryRun -NonInteractive:$NonInteractive
        if($decision.Action -eq 'Cancel'){
            Write-DDRECLog -Context $context -Level WARN -Message '用户取消 Cloud 发布包准备；生产未修改。'
            exit $exitCodes.Cancelled
        }
        if($decision.Action -eq 'Use'){
            $package=$packageState.Metadata
        } else {
            $stage='构建 Cloud 生产发布包（本地）'
            $package=Invoke-DDRECCloudBuild -Context $context -ExpectedCommit $cloudState.Head -ExpectedVersion $cloudVersion -Clean:($decision.Action -eq 'Rebuild')
            Write-Host "`nCloud 生产发布包" -ForegroundColor Green
            Show-DDRECCloudPackageMetadata -Metadata $package
        }
        Add-DDRECStage -Context $context -Stage 'Cloud 本地发布包准备与验证'
    }

    if($dryRun){
        Show-Plan -Plan $plan -ClientState $clientState -CloudState $cloudState -RemoteState $remoteState -MigrationPlan $migrationPlan -Packages $package -Targets $targets
        Write-Header 'Dry Run 结果'
        Write-Host 'PASS：未上传、未备份、未部署、未 Migration、未修改数据库、未创建 Draft、未 Published、未 reload。' -ForegroundColor Green
        Add-DDRECStage -Context $context -Stage 'Dry Run（只读）'
        exit $exitCodes.Success
    }

    $selectedClientUploadMode=''
    if($targets.Count -gt 0){
        $selectedClientUploadMode=Select-ClientUploadMode
        if($selectedClientUploadMode -eq 'cancel'){
            Write-DDRECLog -Context $context -Level WARN -Message '用户取消客户端上传方式选择；生产未修改。'
            exit $exitCodes.Cancelled
        }
    }

    Show-Plan -Plan $plan -ClientState $clientState -CloudState $cloudState -RemoteState $remoteState -MigrationPlan $migrationPlan -Packages $package -Targets $targets
    Sync-DDRECConsoleOutput
    if($NonInteractive -or (Read-Host '请输入 DEPLOY 才允许生产写操作') -cne 'DEPLOY'){
        Write-DDRECLog -Context $context -Level WARN -Message '用户取消 DEPLOY；生产未修改。'
        exit $exitCodes.Cancelled
    }

    $approveMigration=$false
    if($plan.Cloud -and @($migrationPlan.Pending).Count -gt 0){
        Write-Host "发现数据库 Migration：$($migrationPlan.Current) -> $($migrationPlan.Head)" -ForegroundColor Yellow
        Sync-DDRECConsoleOutput
        if((Read-Host '是否执行 Migration？[Y/N]') -notmatch '^(?i)y$'){throw '用户拒绝 pending Migration，部署停止。'}
        $approveMigration=$true
    }
    if($targets.Count -gt 0){
        $sessionCloudCommit=if($plan.Cloud){$cloudState.Head}else{$remoteState.BuildCommit}
        $sessionCloudRelease=if($plan.Cloud){"$($config.RemoteRoot)/release/$cloudVersion-$($cloudState.Head.Substring(0,7))"}else{$remoteState.Current}
        $sessionState=New-DDRECReleaseSessionState -Context $context -CloudGitCommit $sessionCloudCommit -CloudRelease $sessionCloudRelease -ClientGitCommit $clientState.Head -DbRevision $remoteState.DbRevision -Targets $targets -CloudDeployed:(-not $plan.Cloud) -ClientUploadMode $selectedClientUploadMode
        if(-not $plan.Cloud){$sessionState.CurrentSwitched=$true}
        Write-DDRECReleaseSessionState -Context $context -State $sessionState | Out-Null
    }
    if($plan.Cloud){
        $stage='Cloud 备份/部署/Migration/Admin/Health'
        Invoke-DDRECCloudDeploy -Context $context -Package $package -CloudCommit $cloudState.Head -ApproveMigration $approveMigration|Out-Null
        $postCloud=Get-DDRECRemoteState -Context $context
        Assert-DDRECHealthSnapshot -Snapshot ([pscustomobject]@{ApiStatus=$postCloud.ApiStatus;Database=$postCloud.Database;AdminHttp=$postCloud.AdminHttp;ApiContainerHealthy=$postCloud.ApiContainer -eq 'healthy';PostgresHealthy=$postCloud.PostgresContainer -eq 'healthy';BuildCommit=$postCloud.BuildCommit}) -ExpectedCommit $cloudState.Head|Out-Null
        Assert-DDRECCoreCounts -Before $remoteState.Counts -After $postCloud.Counts|Out-Null
        Add-DDRECStage -Context $context -Stage 'Cloud 生产部署与健康检查'
        if($null -ne $sessionState){
            $sessionState.CloudDeployed=$true
            $sessionState.CloudRelease=$postCloud.Current
            Save-ReleaseSession -State $sessionState -CompletedStage 'CloudDeployed'
        }
    }

    if($targets.Count -gt 0){
        if(-not (Invoke-ClientPackageStages -Targets $targets -State $sessionState -UploadMode $selectedClientUploadMode)){exit $exitCodes.Cancelled}
        Invoke-ClientDraftAndPublishStages -Targets $targets -State $sessionState
    }
    Write-DDRECLog -Context $context -Message "流程完成。日志：$($context.LogPath)"
    exit $exitCodes.Success
}
catch {
    if($null -ne $sessionState){
        try{Save-ReleaseSession -State $sessionState -CompletedStage "Failed:$stage"}catch{}
    }
    $report=Get-DDRECFailureReport -Context $context -Stage $stage -ErrorRecord $_
    Write-Header '发布停止'
    Write-DDRECLog -Context $context -Level ERROR -Message ($report|ConvertTo-Json -Depth 6)
    $code=Get-DDRECFailureExitCode -Stage $stage
    exit $code
}
