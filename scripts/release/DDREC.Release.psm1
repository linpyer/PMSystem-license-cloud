Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:ExitCodes = [ordered]@{
    Success = 0; Preflight = 10; Upload = 20; Backup = 30; Deployment = 40
    Migration = 50; Health = 60; ClientValidation = 70; PublishApi = 80
    Cancelled = 90
}
$script:ClientReleaseVersions = [ordered]@{
    'v1.3' = '1.3.0'
    'v1.3.1' = '1.3.1'
    'v1.4' = '1.4.0'
}
$script:CurrentProduct = 'iVRec'
$script:LegacyProduct = 'DDREC'

function Get-DDRECExitCodes { return $script:ExitCodes }

function ConvertTo-ExpandedPath {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$WorkspaceRoot)
    $expanded = [Environment]::ExpandEnvironmentVariables($Path)
    if (-not [IO.Path]::IsPathRooted($expanded)) { $expanded = Join-Path $WorkspaceRoot $expanded }
    return [IO.Path]::GetFullPath($expanded)
}

function Import-DDRECReleaseConfig {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$WorkspaceRoot)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "发布配置不存在：$Path" }
    $config = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$config.Product -cne $script:CurrentProduct) { throw '当前发布 Product 必须为 iVRec。' }
    foreach ($name in @('RequiredCloudBranch','ServerHost','ApiBaseUrl','AdminUrl','DownloadBaseUrl','RemoteRoot','DownloadRoot','RemoteExecutor')) {
        if ([string]::IsNullOrWhiteSpace([string]$config.$name)) { throw "发布配置缺少：$name" }
    }
    if ([string]$config.RemoteRoot -ne '/opt/pmsystem-license') {
        throw '生产技术目录必须保持 /opt/pmsystem-license。'
    }
    $config.UpdatePrivateKey = ConvertTo-ExpandedPath -Path ([string]$config.UpdatePrivateKey) -WorkspaceRoot $WorkspaceRoot
    $config.UpdatePublicKey = ConvertTo-ExpandedPath -Path ([string]$config.UpdatePublicKey) -WorkspaceRoot $WorkspaceRoot
    return $config
}

function New-DDRECReleaseContext {
    param(
        [Parameter(Mandatory)][string]$WorkspaceRoot,
        [Parameter(Mandatory)]$Config,
        [string]$SessionId = (Get-Date -Format 'yyyyMMdd-HHmmss')
    )
    $logRoot = Join-Path $WorkspaceRoot 'cloud-license\artifacts\release-logs'
    New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
    $context = [pscustomobject]@{
        WorkspaceRoot = [IO.Path]::GetFullPath($WorkspaceRoot)
        ClientRoot = [IO.Path]::GetFullPath((Join-Path $WorkspaceRoot 'client'))
        CloudRoot = [IO.Path]::GetFullPath((Join-Path $WorkspaceRoot 'cloud-license'))
        SessionId = $SessionId
        LogPath = Join-Path $logRoot "$SessionId.log"
        SessionStatePath = Join-Path (Join-Path $WorkspaceRoot 'cloud-license\artifacts\release-sessions') "$SessionId.json"
        Config = $Config
        CompletedStages = [Collections.Generic.List[string]]::new()
        ProductionModified = $false
        MigrationExecuted = $false
        RollbackAttempted = $false
        RollbackHealthy = $false
        PreparedProductionArtifacts = $false
        ProductionApplicationModified = $false
        DatabaseModified = $false
        CurrentSwitched = $false
        Uploaded = $false
        BackupCreated = $false
        ReleaseInstalled = $false
        ContainerRecreated = $false
        DeploymentIdentityVerified = $false
        DeploymentSucceeded = $false
        AdminReplaced = $false
        ClientUploaded = $false
        DraftCreated = $false
        PublishedCreated = $false
        Drafts = [Collections.Generic.List[object]]::new()
        Published = [Collections.Generic.List[object]]::new()
    }
    return $context
}

function Write-DDRECReleaseSessionState {
    param([Parameter(Mandatory)]$Context,[Parameter(Mandatory)]$State)
    $path = [string]$Context.SessionStatePath
    $directory = [IO.Path]::GetDirectoryName($path)
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    if ($State.PSObject.Properties['UpdatedAt']) {
        $State.UpdatedAt = [DateTimeOffset]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
    } else {
        Add-Member -InputObject $State -NotePropertyName UpdatedAt -NotePropertyValue ([DateTimeOffset]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffZ'))
    }
    $temporary = "$path.$([guid]::NewGuid().ToString('N')).tmp"
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes(($State | ConvertTo-Json -Depth 12))
    try {
        $stream = [IO.FileStream]::new($temporary,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
        try {
            $stream.Write($bytes,0,$bytes.Length)
            $stream.Flush($true)
        } finally {
            $stream.Dispose()
        }
        [IO.File]::Move($temporary,$path,$true)
    } finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
    }
    return $path
}

function Read-DDRECReleaseSessionState {
    param([Parameter(Mandatory)]$Context,[string]$SessionId=$Context.SessionId)
    if ($SessionId -notmatch '^\d{8}-\d{6}$') { throw "无效发布 SessionId：$SessionId" }
    $path = Join-Path (Join-Path $Context.CloudRoot 'artifacts\release-sessions') "$SessionId.json"
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "发布 Session 状态不存在：$path" }
    $state = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$state.SessionId -cne $SessionId -or [int]$state.SchemaVersion -ne 1) { throw '发布 Session 状态标识或版本无效。' }
    return $state
}

function Get-DDRECLatestIncompleteSessionState {
    param([Parameter(Mandatory)]$Context)
    $root = Join-Path $Context.CloudRoot 'artifacts\release-sessions'
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { return $null }
    foreach ($file in @(Get-ChildItem -LiteralPath $root -Filter '*.json' -File | Sort-Object Name -Descending)) {
        try {
            $state = Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($state.CloudDeployed -and -not $state.Published -and $state.CompletedStage -ne 'Completed') { return $state }
        } catch { continue }
    }
    return $null
}

function Get-DDRECClientIncomingPaths {
    param([Parameter(Mandatory)]$Context,[Parameter(Mandatory)]$Metadata)
    Assert-DDRECPackageMetadata -Metadata $Metadata | Out-Null
    if ([string]$Context.SessionId -notmatch '^\d{8}-\d{6}$') { throw '客户端 incoming SessionId 不安全。' }
    if ([IO.Path]::GetFileName([string]$Metadata.FileName) -cne [string]$Metadata.FileName -or $Metadata.FileName -notmatch '^iVRec-[0-9.]+-(standard|license)-Setup\.exe$') {
        throw '客户端安装包文件名不安全。'
    }
    $root = ([string]$Context.Config.RemoteRoot).TrimEnd('/')
    if ($root -cne '/opt/pmsystem-license') { throw '客户端 incoming 根目录不符合生产安全契约。' }
    $directory = Join-DDRECPosixPath -Base $root -Child @('incoming','client',[string]$Context.SessionId)
    $canonicalPath = Join-DDRECPosixPath -Base $directory -Child @([string]$Metadata.FileName)
    $legacyPath = "$canonicalPath.part"
    return [pscustomobject]@{
        Directory = $directory
        FileName = [string]$Metadata.FileName
        Path = $canonicalPath
        LegacyFileName = "$($Metadata.FileName).part"
        LegacyPath = $legacyPath
        AutoFileName = "$($Metadata.FileName).part"
        AutoPath = $legacyPath
    }
}

function New-DDRECClientSessionItem {
    param([Parameter(Mandatory)]$Context,[Parameter(Mandatory)][string]$Lane,[Parameter(Mandatory)]$Metadata,[Parameter(Mandatory)]$Target)
    $incoming = Get-DDRECClientIncomingPaths -Context $Context -Metadata $Metadata
    return [pscustomobject]@{
        Lane=$Lane; Path=$Metadata.Path; FileName=$Metadata.FileName; Version=$Metadata.Version
        BuildNumber=[int]$Metadata.BuildNumber; GitCommit=$Metadata.GitCommit; Edition=$Metadata.Edition
        Environment=$Metadata.Environment; FileSize=[int64]$Metadata.FileSize; SHA256=$Metadata.SHA256
        RemoteIncomingDirectory=$incoming.Directory; RemoteIncomingPath=$incoming.Path
        RemoteIncomingLegacyPath=$incoming.LegacyPath
        RemoteFinalPath=$Target.RemotePath; DownloadUrl=$Target.Url; RelativePath=$Target.RelativePath
        Uploaded=$false; Installed=$false; Verified=$false; DraftId=$null; DraftStatus=$null; Published=$false
    }
}

function New-DDRECReleaseSessionState {
    param(
        [Parameter(Mandatory)]$Context,[Parameter(Mandatory)][string]$CloudGitCommit,
        [Parameter(Mandatory)][string]$CloudRelease,[Parameter(Mandatory)][string]$ClientGitCommit,
        [Parameter(Mandatory)][string]$DbRevision,[object[]]$Targets=@(),[bool]$CloudDeployed=$false,
        [ValidateSet('auto','manual','')][string]$ClientUploadMode=''
    )
    $standard=$null; $license=$null
    foreach ($item in $Targets) {
        $sessionItem=New-DDRECClientSessionItem -Context $Context -Lane $item.Lane -Metadata $item.Metadata -Target $item.Target
        if ($item.Lane -eq 'standard') {$standard=$sessionItem} else {$license=$sessionItem}
    }
    return [pscustomobject]@{
        SchemaVersion=1; SessionId=$Context.SessionId
        CreatedAt=[DateTimeOffset]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffZ'); UpdatedAt=$null
        CloudGitCommit=$CloudGitCommit; CloudRelease=$CloudRelease; CloudDeployed=$CloudDeployed
        CurrentSwitched=$Context.CurrentSwitched; ClientGitCommit=$ClientGitCommit; DbRevision=$DbRevision
        ClientUploadMode=$ClientUploadMode
        DatabaseModified=$Context.DatabaseModified; MigrationExecuted=$Context.MigrationExecuted; AdminReplaced=$Context.AdminReplaced
        CompletedStage=$(if($CloudDeployed){'CloudDeployed'}else{'Prepared'}); Standard=$standard; License=$license
        DraftCreated=$false; Published=$false
    }
}

function Get-DDRECSessionUploadMode {
    param([Parameter(Mandatory)]$State)
    $property=$State.PSObject.Properties['ClientUploadMode']
    $mode=if($null -eq $property){''}else{[string]$property.Value}
    if($mode -in @('auto','manual')){return $mode}
    # Schema v1 sessions created before upload-mode support were manual-only.
    return 'manual'
}

function Set-DDRECSessionUploadMode {
    param([Parameter(Mandatory)]$State,[Parameter(Mandatory)][ValidateSet('auto','manual')][string]$Mode)
    if($null -eq $State.PSObject.Properties['ClientUploadMode']){
        $State|Add-Member -NotePropertyName ClientUploadMode -NotePropertyValue $Mode
    }else{
        $State.ClientUploadMode=$Mode
    }
    return $State
}

function Update-DDRECReleaseSessionFromContext {
    param([Parameter(Mandatory)]$Context,[Parameter(Mandatory)]$State,[string]$CompletedStage)
    $State.CurrentSwitched=[bool]$Context.CurrentSwitched
    $State.DatabaseModified=[bool]$Context.DatabaseModified
    $State.MigrationExecuted=[bool]$Context.MigrationExecuted
    $State.AdminReplaced=[bool]$Context.AdminReplaced
    $State.DraftCreated=[bool]$State.DraftCreated -or [bool]$Context.DraftCreated
    $State.Published=[bool]$State.Published -or [bool]$Context.PublishedCreated
    if ($CompletedStage) {$State.CompletedStage=$CompletedStage}
    Write-DDRECReleaseSessionState -Context $Context -State $State | Out-Null
    return $State
}

function Merge-DDRECReleaseSessionContext {
    param([Parameter(Mandatory)]$Context,[Parameter(Mandatory)]$State)
    $Context.CurrentSwitched=[bool]$Context.CurrentSwitched -or [bool]$State.CurrentSwitched
    $Context.DatabaseModified=[bool]$Context.DatabaseModified -or [bool]$State.DatabaseModified
    $Context.MigrationExecuted=[bool]$Context.MigrationExecuted -or [bool]$State.MigrationExecuted
    $Context.AdminReplaced=[bool]$Context.AdminReplaced -or [bool]$State.AdminReplaced
    $clientItems=@(@($State.Standard,$State.License)|Where-Object{$null -ne $_})
    if($clientItems.Count -gt 0){
        $Context.ClientUploaded=@($clientItems|Where-Object{-not ([bool]$_.Uploaded -and [bool]$_.Installed -and [bool]$_.Verified)}).Count -eq 0
    }
    $Context.DraftCreated=[bool]$Context.DraftCreated -or [bool]$State.DraftCreated -or @($clientItems|Where-Object{$_.DraftId}).Count -gt 0
    $Context.PublishedCreated=[bool]$Context.PublishedCreated -or [bool]$State.Published -or @($clientItems|Where-Object{[bool]$_.Published}).Count -gt 0
    $Context.PreparedProductionArtifacts=$Context.PreparedProductionArtifacts -or [bool]$State.CloudDeployed -or $Context.ClientUploaded
    $Context.ProductionApplicationModified=$Context.ProductionApplicationModified -or $Context.CurrentSwitched -or $Context.AdminReplaced
    $Context.ProductionModified=$Context.PreparedProductionArtifacts -or $Context.ProductionApplicationModified -or $Context.DatabaseModified -or $Context.ClientUploaded -or $Context.DraftCreated -or $Context.PublishedCreated
    return $Context
}

function Protect-DDRECLogText {
    param([AllowEmptyString()][string]$Text)
    if ($null -eq $Text) { return '' }
    $value = $Text
    $patterns = @(
        '(?i)(password|totp|accesskeysecret|private[_ -]?key|authorization|cookie|token)\s*[:=]\s*[^\s,;]+',
        '(?i)bearer\s+[A-Za-z0-9._~+\-/]+=*',
        '-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?-----END [^-]*PRIVATE KEY-----'
    )
    foreach ($pattern in $patterns) { $value = [regex]::Replace($value, $pattern, '$1=[REDACTED]') }
    return $value
}

function Write-DDRECLog {
    param([Parameter(Mandatory)]$Context, [Parameter(Mandatory)][string]$Message, [ValidateSet('INFO','WARN','ERROR')][string]$Level='INFO')
    $safe = Protect-DDRECLogText $Message
    $line = '[{0}] [{1}] {2}' -f ([DateTimeOffset]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')), $Level, $safe
    [IO.File]::AppendAllText($Context.LogPath, $line + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
    $color = if ($Level -eq 'ERROR') {'Red'} elseif ($Level -eq 'WARN') {'Yellow'} else {'Gray'}
    Write-Host $safe -ForegroundColor $color
}

function Add-DDRECStage {
    param([Parameter(Mandatory)]$Context,[Parameter(Mandatory)][string]$Stage)
    $Context.CompletedStages.Add($Stage)
    Write-DDRECLog -Context $Context -Message "完成阶段：$Stage"
}

function Invoke-DDRECNative {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory,
        [switch]$AllowFailure,
        [switch]$NoLogOutput,
        $Context
    )
    $old = Get-Location
    try {
        if ($WorkingDirectory) { Set-Location -LiteralPath $WorkingDirectory }
        $output = @(& $FilePath @Arguments 2>&1)
        $code = $LASTEXITCODE
    } finally { Set-Location -LiteralPath $old }
    $text = ($output | ForEach-Object { [string]$_ }) -join "`n"
    if ($Context -and -not $NoLogOutput -and $text) { Write-DDRECLog -Context $Context -Message $text }
    if ($code -ne 0 -and -not $AllowFailure) {
        throw "命令失败（退出码 $code）：$FilePath $($Arguments -join ' ')`n$text"
    }
    return [pscustomobject]@{ ExitCode=$code; Output=$text }
}

function Invoke-DDRECConsoleTask {
    param(
        [Parameter(Mandatory)][string]$PwshPath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][ref]$ExitCode,
        $MenuCache
    )
    # Process stdout one line at a time so it remains live while the two summary
    # fields already printed by every real preflight can refresh the UI cache.
    # Write directly to the console: returning these lines through the success
    # pipeline lets PowerShell's formatter race with a child Read-Host prompt.
    # Stderr is deliberately not redirected and inherits the current console.
    & $PwshPath @Arguments | ForEach-Object {
        $line=[string]$_
        if($null -ne $MenuCache){
            if($line -match '^current=(.*)$'){
                $MenuCache.ProductionRelease=$matches[1]
                $MenuCache.LastProductionCheck=[DateTimeOffset]::Now
            }elseif($line -match '^\s*CurrentRelease\s*:\s*(.+)$'){
                $MenuCache.ProductionRelease=$matches[1].Trim()
                $MenuCache.LastProductionCheck=[DateTimeOffset]::Now
            }elseif($line -match '^healthJson=(\{.*\})$'){
                try{
                    $health=$matches[1]|ConvertFrom-Json
                    $MenuCache.ProductionApi=[string]$health.status
                    $MenuCache.LastProductionCheck=[DateTimeOffset]::Now
                }catch{}
            }elseif($line -match '^\s*ApiStatus\s*:\s*(.+)$'){
                $MenuCache.ProductionApi=$matches[1].Trim()
                $MenuCache.LastProductionCheck=[DateTimeOffset]::Now
            }
        }
        [Console]::Out.WriteLine($line)
        [Console]::Out.Flush()
    }
    $ExitCode.Value=[int]$LASTEXITCODE
}

function Sync-DDRECConsoleOutput {
    try{[Console]::Out.Flush()}catch{}
    try{[Console]::Error.Flush()}catch{}
}

function Get-DDRECGitState {
    param([Parameter(Mandatory)][string]$Repository)
    $branch = (Invoke-DDRECNative git @('branch','--show-current') $Repository).Output.Trim()
    $head = (Invoke-DDRECNative git @('rev-parse','HEAD') $Repository).Output.Trim()
    $remote = if ([string]::IsNullOrWhiteSpace($branch)) {
        ''
    } else {
        (Invoke-DDRECNative git @('rev-parse',"origin/$branch") $Repository).Output.Trim()
    }
    $status = (Invoke-DDRECNative git @('status','--porcelain=v1','--untracked-files=all') $Repository).Output
    return [pscustomobject]@{
        Repository=$Repository; Branch=$branch; Head=$head; Origin=$remote
        Clean=[string]::IsNullOrWhiteSpace($status); Status=$status
    }
}

function Get-DDRECLocalGitHead {
    param([Parameter(Mandatory)][string]$Repository)
    return (Invoke-DDRECNative git @('rev-parse','HEAD') $Repository).Output.Trim()
}

function Get-DDRECMenuProductionOverview {
    param([Parameter(Mandatory)]$Context,[scriptblock]$NativeInvoker)
    $scriptText=@'
set -Eeuo pipefail
printf 'current=%s\n' "$(readlink -f /opt/pmsystem-license/current 2>/dev/null || true)"
curl -fsS --max-time 2 https://license.aixcc.top/api/v1/health | sed 's/^/healthJson=/'
echo
'@
    $encoded=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($scriptText))
    $command="printf '%s' '$encoded' | base64 -d | bash"
    try{
        $result=if($NativeInvoker){
            & $NativeInvoker
        }else{
            Invoke-DDRECNative ssh @('-o','BatchMode=yes','-o','ConnectTimeout=2',[string]$Context.Config.ServerHost,$command) -AllowFailure -NoLogOutput -Context $Context
        }
        if([int]$result.ExitCode -ne 0){throw "overview exit $($result.ExitCode)"}
        $current='unknown';$api='unknown'
        foreach($line in ([string]$result.Output -split "`r?`n")){
            if($line -match '^current=(.*)$'){$current=$matches[1]}
            elseif($line -match '^healthJson=(\{.*\})$'){
                try{$api=[string](($matches[1]|ConvertFrom-Json).status)}catch{}
            }
        }
        return [pscustomobject]@{Api=$api;Release=$current;CheckedAt=[DateTimeOffset]::Now}
    }catch{
        return [pscustomobject]@{Api='unknown';Release='unknown';CheckedAt=$null}
    }
}

function Assert-DDRECGitReleaseState {
    param([Parameter(Mandatory)]$State,[Parameter(Mandatory)][string]$RequiredBranch)
    if ($State.Branch -cne $RequiredBranch) { throw "Git 分支错误：需要 $RequiredBranch，实际 $($State.Branch)" }
    if (-not $State.Clean) { throw "Git 工作区不干净：$($State.Repository)`n$($State.Status)" }
    if ($State.Head -cne $State.Origin) { throw "Git HEAD 与 origin/$RequiredBranch 不一致：$($State.Head) != $($State.Origin)" }
    return $true
}

function Get-DDRECExpectedClientVersion {
    param([Parameter(Mandatory)][AllowEmptyString()][string]$Branch)
    if (-not $script:ClientReleaseVersions.Contains($Branch)) {
        throw "客户端发布分支不受支持：$Branch"
    }
    return [string]$script:ClientReleaseVersions[$Branch]
}

function Assert-DDRECClientReleaseState {
    param(
        [Parameter(Mandatory)]$State,
        [Parameter(Mandatory)][string]$ClientVersion
    )
    $expectedVersion = Get-DDRECExpectedClientVersion -Branch ([string]$State.Branch)
    if ($ClientVersion -cne $expectedVersion) {
        throw "客户端分支与版本不一致：$($State.Branch) 需要 $expectedVersion，实际 $ClientVersion"
    }
    Assert-DDRECGitReleaseState -State $State -RequiredBranch ([string]$State.Branch) | Out-Null
    return $true
}

function Get-DDRECClientApplicationVersion {
    param([Parameter(Mandatory)][string]$ClientRoot)
    $python = Join-Path $ClientRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "客户端 Python 不存在：$python"
    }
    Push-Location $ClientRoot
    try {
        $version = (& $python -c 'from app.core.version import APP_VERSION; print(APP_VERSION)' 2>$null | Select-Object -Last 1)
    } finally {
        Pop-Location
    }
    if ([string]::IsNullOrWhiteSpace([string]$version)) { throw '无法读取客户端版本。' }
    return ([string]$version).Trim()
}

function Get-DDRECModePlan {
    param(
        [ValidateSet('Standard','LicenseProduction','BothClients','Cloud','CloudStandard','CloudBoth')]
        [Parameter(Mandatory)][string]$Mode
    )
    switch ($Mode) {
        'Standard'          { return [pscustomobject]@{Cloud=$false;Lanes=@('standard')} }
        'LicenseProduction' { return [pscustomobject]@{Cloud=$false;Lanes=@('license-production')} }
        'BothClients'       { return [pscustomobject]@{Cloud=$false;Lanes=@('standard','license-production')} }
        'Cloud'             { return [pscustomobject]@{Cloud=$true; Lanes=@()} }
        'CloudStandard'     { return [pscustomobject]@{Cloud=$true; Lanes=@('standard')} }
        'CloudBoth'         { return [pscustomobject]@{Cloud=$true; Lanes=@('standard','license-production')} }
    }
}

function Get-DDRECMainMenuAction {
    param([AllowEmptyString()][string]$InputText)
    switch(($InputText ?? '').Trim()){
        '1'{return 'Standard'}
        '2'{return 'LicenseProduction'}
        '3'{return 'BothClients'}
        '4'{return 'Cloud'}
        '5'{return 'CloudStandard'}
        '6'{return 'CloudBoth'}
        '7'{return 'DryRun'}
        '8'{return 'Status'}
        '9'{return 'Resume'}
        '0'{return 'Exit'}
        default{return 'Invalid'}
    }
}

function Get-DDRECClientUploadModeAction {
    param([AllowEmptyString()][string]$InputText)
    switch(($InputText ?? '').Trim()){
        '1'{return 'auto'}
        '2'{return 'manual'}
        '0'{return 'cancel'}
        default{return 'invalid'}
    }
}

function Read-DDRECKeyValueFile {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "元数据文件不存在：$Path" }
    $values = @{}
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        if ($line -match '^([^#=]+)=(.*)$') { $values[$matches[1].Trim()] = $matches[2].Trim() }
    }
    return $values
}

function Get-DDRECInstallerCandidate {
    param([Parameter(Mandatory)][string]$ClientRoot,[ValidateSet('standard','license-production')][string]$Lane)
    $root = if ($Lane -eq 'standard') {
        Join-Path $ClientRoot 'artifacts\client\standard'
    } else {
        Join-Path $ClientRoot 'artifacts\client\license\production'
    }
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { return $null }
    return Get-ChildItem -LiteralPath $root -Filter '*.exe' -File -Recurse |
        Sort-Object LastWriteTimeUtc,FullName -Descending | Select-Object -First 1
}

function Assert-DDRECPackageMetadata {
    param([Parameter(Mandatory)]$Metadata)
    if ($Metadata.PSObject.TypeNames -notcontains 'DDREC.PackageMetadata') {
        throw "安装包元数据无效：预期 DDREC.PackageMetadata，实际 $($Metadata.GetType().FullName)"
    }
    foreach ($field in @('Path','FileName','FileSize','SHA256','Product','DisplayName','MainExe','UpdaterExe','Version','BuildNumber','GitCommit','Edition','Environment','UpdaterVersion')) {
        $property = $Metadata.PSObject.Properties[$field]
        if ($null -eq $property -or [string]::IsNullOrWhiteSpace([string]$property.Value)) {
            throw "安装包元数据无效：PackageMetadata 缺少 $field"
        }
    }
    return $true
}

function Assert-DDRECInstallerPolicy {
    param(
        [Parameter(Mandatory)]$Metadata,
        [ValidateSet('standard','license-production')][string]$Lane,
        [Parameter(Mandatory)][string]$ExpectedCommit,
        [Parameter(Mandatory)][string]$ExpectedVersion
    )
    Assert-DDRECPackageMetadata -Metadata $Metadata | Out-Null
    if ($Metadata.Product -cne $script:CurrentProduct -or $Metadata.DisplayName -cne 'iVRec') { throw '安装包 Product/DisplayName 必须为 iVRec。' }
    if ($Metadata.MainExe -cne 'iVRec.exe' -or $Metadata.UpdaterExe -cne 'iVRec-Updater.exe') { throw '安装包 MainExe/UpdaterExe 不符合 iVRec 包身份。' }
    $expectedEdition = if ($Lane -eq 'standard') {'standard'} else {'license'}
    $expectedEnvironment = if ($Lane -eq 'standard') {'none'} else {'production'}
    if ($Metadata.Edition -cne $expectedEdition) { throw "安装包 Edition 错误：$($Metadata.Edition)" }
    if ($Metadata.Environment -cne $expectedEnvironment) { throw "安装包 Environment 错误：$($Metadata.Environment)" }
    if ($Metadata.GitCommit -cne $ExpectedCommit) { throw "安装包 GitCommit 与当前 client HEAD 不一致：$($Metadata.GitCommit) != $ExpectedCommit" }
    if ($Metadata.Version -notmatch '^\d+\.\d+\.\d+$') { throw 'Version 必须为三段式版本号。' }
    if ($Metadata.Version -cne $ExpectedVersion) { throw "安装包 Version 与客户端分支映射不一致：$($Metadata.Version) != $ExpectedVersion" }
    if ([int64]$Metadata.BuildNumber -lt 1) { throw 'BuildNumber 必须大于 0。' }
    if ($Metadata.UpdaterVersion -notmatch '^\d+\.\d+\.\d+$') { throw 'UpdaterVersion 无效或缺失。' }
    return $true
}

function Show-DDRECPackageMetadata {
    param([Parameter(Mandatory)]$Metadata,[scriptblock]$OutputWriter)
    Assert-DDRECPackageMetadata -Metadata $Metadata | Out-Null
    if($null -eq $OutputWriter){$OutputWriter={param($Line) Write-Host $Line}}
    foreach($field in @('Product','DisplayName','MainExe','UpdaterExe','FileName','Version','BuildNumber','GitCommit','Edition','Environment','UpdaterVersion','FileSize','SHA256')){
        [void](& $OutputWriter ('{0,-14} : {1}' -f $field,[string]$Metadata.$field))
    }
    Sync-DDRECConsoleOutput
}

function Read-DDRECColonMetadataFile {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Cloud 发布包 Manifest 不存在：$Path" }
    $values = @{}
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        $separator = $line.IndexOf(':')
        if ($separator -lt 1) { throw "Cloud 发布包 Manifest 行格式无效：$line" }
        $name = $line.Substring(0, $separator).Trim()
        $value = $line.Substring($separator + 1).Trim()
        if ($values.ContainsKey($name)) { throw "Cloud 发布包 Manifest 字段重复：$name" }
        $values[$name] = $value
    }
    return $values
}

function Assert-DDRECCloudPackageMetadata {
    param([Parameter(Mandatory)]$Metadata)
    if ($Metadata.PSObject.TypeNames -notcontains 'DDREC.CloudPackageMetadata') {
        throw "Cloud 发布包元数据无效：预期 DDREC.CloudPackageMetadata，实际 $($Metadata.GetType().FullName)"
    }
    foreach ($field in @(
        'Path','FileName','FileSize','SHA256','Version','GitCommit','Environment','Service',
        'ManifestPath','ChecksumsPath','BuildTime'
    )) {
        $property = $Metadata.PSObject.Properties[$field]
        if ($null -eq $property -or [string]::IsNullOrWhiteSpace([string]$property.Value)) {
            throw "Cloud 发布包元数据无效：CloudPackageMetadata 缺少 $field"
        }
    }
    return $true
}

function Get-DDRECCloudPackageMetadata {
    param(
        [Parameter(Mandatory)][string]$CloudRoot,
        [Parameter(Mandatory)][string]$ExpectedCommit,
        [Parameter(Mandatory)][ValidatePattern('^\d+\.\d+\.\d+$')][string]$ExpectedVersion,
        [Parameter(Mandatory)][string]$ExpectedBranch
    )
    $root = [IO.Path]::GetFullPath((Join-Path $CloudRoot 'artifacts\cloud\production\all'))
    $manifestPath = Join-Path $root 'RELEASE-MANIFEST.txt'
    $checksumsPath = Join-Path $root 'SHA256SUMS.txt'
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "Cloud 发布包 Manifest 不存在：$manifestPath"
    }
    if (-not (Test-Path -LiteralPath $checksumsPath -PathType Leaf)) {
        throw "Cloud 发布包 SHA256SUMS 不存在：$checksumsPath"
    }

    $manifest = Read-DDRECColonMetadataFile -Path $manifestPath
    $required = @(
        'Release version','Environment','Service','Git branch','Git commit','Git worktree clean',
        'Build time UTC','Archive','Archive size bytes','Archive SHA-256'
    )
    foreach ($field in $required) {
        if (-not $manifest.ContainsKey($field) -or [string]::IsNullOrWhiteSpace([string]$manifest[$field])) {
            throw "Cloud 发布包元数据无效：RELEASE-MANIFEST 缺少 $field"
        }
    }

    $archiveName = [string]$manifest['Archive']
    if ([IO.Path]::GetFileName($archiveName) -cne $archiveName) {
        throw "Cloud 发布包 Manifest 的 Archive 必须是文件名：$archiveName"
    }
    $archivePath = Join-Path $root $archiveName
    if (-not (Test-Path -LiteralPath $archivePath -PathType Leaf)) {
        throw "Cloud 发布包不存在：$archivePath"
    }
    $archives = @(Get-ChildItem -LiteralPath $root -Filter '*.tar.gz' -File)
    if ($archives.Count -ne 1 -or $archives[0].FullName -cne ([IO.Path]::GetFullPath($archivePath))) {
        throw "Cloud 正式目录必须且只能包含 Manifest 指定的一个 tar.gz，实际：$($archives.Count)"
    }

    $version = [string]$manifest['Release version']
    $environment = [string]$manifest['Environment']
    $service = [string]$manifest['Service']
    $branch = [string]$manifest['Git branch']
    $commit = [string]$manifest['Git commit']
    if ($version -cne $ExpectedVersion) { throw "Cloud 发布包 Version 与当前版本不一致：$version != $ExpectedVersion" }
    if ($environment -cne 'production') { throw "Cloud 发布包 Environment 错误：$environment；正式发布必须为 production" }
    if ($service -cne 'all') { throw "Cloud 发布包 Service 错误：$service；正式发布必须为 all" }
    if ($branch -cne $ExpectedBranch) { throw "Cloud 发布包 Git branch 错误：$branch != $ExpectedBranch" }
    if ([string]$manifest['Git worktree clean'] -cne 'True') { throw 'Cloud 发布包 Manifest 表明构建工作区不干净。' }
    if ($commit -cne $ExpectedCommit) {
        throw "当前 Cloud 构建产物已过期：`n`nPackage GitCommit : $commit`nCurrent Git HEAD  : $ExpectedCommit"
    }

    $file = Get-Item -LiteralPath $archivePath
    [int64]$manifestSize = 0
    if (-not [int64]::TryParse([string]$manifest['Archive size bytes'], [ref]$manifestSize) -or $manifestSize -lt 1) {
        throw 'Cloud 发布包 Manifest 的 Archive size bytes 无效。'
    }
    if ($file.Length -ne $manifestSize) {
        throw "Cloud 发布包实际大小与 Manifest 不一致：$($file.Length) != $manifestSize"
    }

    $checksumLines = @(Get-Content -LiteralPath $checksumsPath -Encoding UTF8 | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    if ($checksumLines.Count -ne 1 -or $checksumLines[0] -notmatch '^([0-9A-Fa-f]{64})\s{2}(.+)$') {
        throw 'Cloud 发布包 SHA256SUMS 格式无效；必须只有一条 SHA256 记录。'
    }
    $checksumsHash = $matches[1].ToUpperInvariant()
    $checksumsName = $matches[2]
    if ($checksumsName -cne $archiveName) { throw "Cloud 发布包 SHA256SUMS 文件名不匹配：$checksumsName != $archiveName" }
    $manifestHash = [string]$manifest['Archive SHA-256']
    if ($manifestHash -notmatch '^[0-9A-Fa-f]{64}$') { throw 'Cloud 发布包 Manifest 的 Archive SHA-256 无效。' }
    $manifestHash = $manifestHash.ToUpperInvariant()
    $actualHash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToUpperInvariant()
    if ($checksumsHash -cne $manifestHash) { throw 'Cloud 发布包 SHA256SUMS 与 Manifest SHA256 不一致。' }
    if ($actualHash -cne $manifestHash) { throw 'Cloud 发布包实际 SHA256 与 Manifest 不一致。' }

    $buildTime = [string]$manifest['Build time UTC']
    [DateTimeOffset]$parsedBuildTime = [DateTimeOffset]::MinValue
    if (-not [DateTimeOffset]::TryParse($buildTime, [ref]$parsedBuildTime)) { throw "Cloud 发布包 BuildTime 无效：$buildTime" }

    $metadata = [pscustomobject]@{
        Path = $file.FullName
        FileName = $file.Name
        FileSize = [int64]$file.Length
        SHA256 = $actualHash
        Version = $version
        GitCommit = $commit
        Environment = $environment
        Service = $service
        ManifestPath = $manifestPath
        ChecksumsPath = $checksumsPath
        BuildTime = $buildTime
    }
    $metadata.PSObject.TypeNames.Insert(0, 'DDREC.CloudPackageMetadata')
    Assert-DDRECCloudPackageMetadata -Metadata $metadata | Out-Null
    return $metadata
}

function Get-DDRECCloudPackageState {
    param(
        [Parameter(Mandatory)][string]$CloudRoot,
        [Parameter(Mandatory)][string]$ExpectedCommit,
        [Parameter(Mandatory)][string]$ExpectedVersion,
        [Parameter(Mandatory)][string]$ExpectedBranch
    )
    $outputRoot = [IO.Path]::GetFullPath((Join-Path $CloudRoot 'artifacts\cloud\production\all'))
    $scratchRoot = [IO.Path]::GetFullPath((Join-Path $CloudRoot 'artifacts\cloud\.build-production-all'))
    $entries = @()
    foreach ($path in @($outputRoot, $scratchRoot)) {
        if (Test-Path -LiteralPath $path) {
            $entries += @(Get-Item -LiteralPath $path -Force)
            $entries += @(Get-ChildItem -LiteralPath $path -Force -Recurse)
        }
    }
    if ($entries.Count -eq 0) {
        return [pscustomobject]@{ HasExistingOutput=$false; IsValid=$false; Metadata=$null; ValidationError=$null; OutputRoot=$outputRoot; ScratchRoot=$scratchRoot }
    }
    try {
        $metadata = Get-DDRECCloudPackageMetadata -CloudRoot $CloudRoot -ExpectedCommit $ExpectedCommit -ExpectedVersion $ExpectedVersion -ExpectedBranch $ExpectedBranch
        return [pscustomobject]@{ HasExistingOutput=$true; IsValid=$true; Metadata=$metadata; ValidationError=$null; OutputRoot=$outputRoot; ScratchRoot=$scratchRoot }
    } catch {
        return [pscustomobject]@{ HasExistingOutput=$true; IsValid=$false; Metadata=$null; ValidationError=$_.Exception.Message; OutputRoot=$outputRoot; ScratchRoot=$scratchRoot }
    }
}

function Get-DDRECCloudPackageDecision {
    param(
        [Parameter(Mandatory)]$State,
        [switch]$DryRun,
        [switch]$NonInteractive,
        [scriptblock]$InputReader,
        [scriptblock]$OutputWriter
    )
    if (-not $State.HasExistingOutput) { return [pscustomobject]@{Action='Build'} }
    if ($null -eq $OutputWriter) {
        $OutputWriter = { param($Message,$Color) if ($Color) { Write-Host $Message -ForegroundColor $Color } else { Write-Host $Message } }
    }
    if ($State.IsValid) {
        if ($DryRun -or $NonInteractive) { return [pscustomobject]@{Action='Use'} }
        & $OutputWriter '[Y] 使用当前云端发布包' ''
        & $OutputWriter '[R] 清除并重新完整构建' ''
        & $OutputWriter '[N] 取消本次发布（默认）' ''
        $allowed = @('Y','R','N')
    } else {
        & $OutputWriter "当前 Cloud 构建产物无效：`n$($State.ValidationError)" 'Yellow'
        if ($DryRun -or $NonInteractive) { throw $State.ValidationError }
        & $OutputWriter '[R] 清除并重新完整构建' ''
        & $OutputWriter '[N] 取消本次发布（默认）' ''
        $allowed = @('R','N')
    }
    if ($null -eq $InputReader) { $InputReader = { param($Prompt) Read-Host $Prompt } }
    & $OutputWriter '' ''
    Sync-DDRECConsoleOutput
    while ($true) {
        $answer = [string](& $InputReader '请选择 [Y/R/N]')
        if ([string]::IsNullOrWhiteSpace($answer)) { return [pscustomobject]@{Action='Cancel'} }
        $answer = $answer.Trim().ToUpperInvariant()
        if ($answer -eq 'Y' -and $allowed -contains 'Y') { return [pscustomobject]@{Action='Use'} }
        if ($answer -eq 'R') { return [pscustomobject]@{Action='Rebuild'} }
        if ($answer -eq 'N') { return [pscustomobject]@{Action='Cancel'} }
        & $OutputWriter "输入无效；允许的选择：$($allowed -join '/')，直接按 Enter 将取消。" 'Yellow'
    }
}

function Show-DDRECCloudPackageMetadata {
    param([Parameter(Mandatory)]$Metadata)
    Assert-DDRECCloudPackageMetadata -Metadata $Metadata | Out-Null
    $Metadata | Select-Object FileName,Version,GitCommit,Environment,Service,FileSize,SHA256,BuildTime | Format-List | Out-Host
}

function Get-DDRECInstallerMetadata {
    param(
        [Parameter(Mandatory)][string]$InstallerPath,
        [ValidateSet('standard','license-production')][string]$Lane,
        [Parameter(Mandatory)][string]$ExpectedCommit,
        [Parameter(Mandatory)][string]$ExpectedVersion
    )
    $file = Get-Item -LiteralPath $InstallerPath -ErrorAction Stop
    $manifestPath = Join-Path $file.DirectoryName 'RELEASE-MANIFEST.txt'
    $checksumsPath = Join-Path $file.DirectoryName 'SHA256SUMS.txt'
    $m = Read-DDRECKeyValueFile $manifestPath
    $manifestFields = [ordered]@{
        Product='Product'; DisplayName='DisplayName'; MainExe='MainExe'; UpdaterExe='UpdaterExe'
        Version='Version'; BuildNumber='BuildNumber'; GitCommit='GitCommit'; Edition='Edition'
        Environment='LicenseEnvironment'; UpdaterVersion='UpdaterVersion'; Installer='Installer'
        FileSize='SizeBytes'; SHA256='SHA256'
    }
    foreach ($field in $manifestFields.Keys) {
        $manifestName = $manifestFields[$field]
        if (-not $m.ContainsKey($manifestName) -or [string]::IsNullOrWhiteSpace([string]$m[$manifestName])) {
            throw "安装包元数据无效：RELEASE-MANIFEST 缺少 $field"
        }
    }
    if ($file.Name -cne [string]$m['Installer']) { throw '安装包文件名与构建元数据不一致。' }
    if (-not (Test-Path -LiteralPath $checksumsPath -PathType Leaf)) { throw '缺少 SHA256SUMS.txt。' }
    $checksumLine = (Get-Content -LiteralPath $checksumsPath -Encoding UTF8 | Where-Object { $_ -match [regex]::Escape($file.Name) } | Select-Object -First 1)
    if (-not $checksumLine -or $checksumLine -notmatch '^([0-9A-Fa-f]{64})\s+(.+)$') { throw 'SHA256SUMS.txt 没有合法的安装包记录。' }
    if ($matches[2].Trim() -cne $file.Name) { throw 'SHA256SUMS.txt 安装包文件名与实际文件不一致。' }
    $actualHash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToUpperInvariant()
    if ($actualHash -cne ([string]$m['SHA256']).ToUpperInvariant() -or $actualHash -cne $matches[1].ToUpperInvariant()) { throw '安装包 SHA256 与构建元数据不一致。' }
    [int64]$manifestSize = 0
    if (-not [int64]::TryParse([string]$m['SizeBytes'], [ref]$manifestSize)) { throw '安装包元数据无效：FileSize 不是有效整数。' }
    if ($file.Length -ne $manifestSize) { throw '安装包大小与构建元数据不一致。' }
    [int]$buildNumber = 0
    if (-not [int]::TryParse([string]$m['BuildNumber'], [ref]$buildNumber)) { throw '安装包元数据无效：BuildNumber 不是有效整数。' }
    $versionInfo = [Diagnostics.FileVersionInfo]::GetVersionInfo($file.FullName)
    $peProductVersion = ([string]$versionInfo.ProductVersion).Split('+')[0].Trim()
    if ([string]::IsNullOrWhiteSpace($peProductVersion)) { throw '安装包 Windows ProductVersion 缺失。' }
    if (-not $peProductVersion.StartsWith([string]$m['Version'], [StringComparison]::Ordinal)) {
        throw "安装包 Windows ProductVersion 与构建元数据不一致：$peProductVersion"
    }
    $metadata = [pscustomobject]@{
        PSTypeName='DDREC.PackageMetadata'
        Path=$file.FullName; FileName=$file.Name; FileSize=[int64]$file.Length; SHA256=$actualHash
        Product=[string]$m['Product']; DisplayName=[string]$m['DisplayName']
        MainExe=[string]$m['MainExe']; UpdaterExe=[string]$m['UpdaterExe']
        Version=[string]$m['Version']; BuildNumber=$buildNumber; GitCommit=([string]$m['GitCommit']).ToLowerInvariant()
        Edition=([string]$m['Edition']).ToLowerInvariant(); Environment=([string]$m['LicenseEnvironment']).ToLowerInvariant()
        UpdaterVersion=[string]$m['UpdaterVersion']
        ManifestPath=$manifestPath; ChecksumsPath=$checksumsPath; PEProductVersion=$peProductVersion
    }
    Assert-DDRECInstallerPolicy -Metadata $metadata -Lane $Lane -ExpectedCommit $ExpectedCommit -ExpectedVersion $ExpectedVersion | Out-Null
    return $metadata
}

function Get-DDRECClientTarget {
    param([Parameter(Mandatory)]$Metadata,[Parameter(Mandatory)]$Config)
    Assert-DDRECPackageMetadata -Metadata $Metadata | Out-Null
    $lane = if ($Metadata.Edition -eq 'standard') {'standard'} else {'license'}
    $relative = "/releases/stable/$lane/$($Metadata.Version)/$($Metadata.BuildNumber)/$($Metadata.FileName)"
    return [pscustomobject]@{
        RelativePath=$relative
        RemotePath=([string]$Config.DownloadRoot).TrimEnd('/') + $relative
        Url=([string]$Config.DownloadBaseUrl).TrimEnd('/') + $relative
    }
}

function Assert-DDRECHashCompatibility {
    param([string]$ExistingHash,[Parameter(Mandatory)][string]$ExpectedHash)
    if ($ExistingHash -and $ExistingHash.ToUpperInvariant() -cne $ExpectedHash.ToUpperInvariant()) {
        throw "目标不可变文件已存在且 SHA 不同：$ExistingHash != $ExpectedHash"
    }
    return $true
}

function Assert-DDRECDiskSpace {
    param([int64]$AvailableBytes,[int64]$RequiredBytes)
    if ($AvailableBytes -lt $RequiredBytes) { throw "生产磁盘空间不足：$AvailableBytes < $RequiredBytes" }
    return $true
}

function Assert-DDRECBackupResult {
    param($Result)
    if (-not $Result.Success -or [int64]$Result.Size -le 0 -or -not $Result.ChecksumValid -or -not $Result.RestoreListReadable) {
        throw 'PostgreSQL 备份未通过非空、SHA256 与 pg_restore 列表校验。'
    }
    return $true
}

function Get-DDRECMigrationSafety {
    param([string[]]$MigrationTexts)
    $destructive = [Collections.Generic.List[string]]::new()
    foreach ($text in $MigrationTexts) {
        $upgradeMatch = [regex]::Match($text, '(?ms)^def\s+upgrade\s*\([^)]*\)\s*:\s*(?<body>.*?)(?=^def\s+downgrade\s*\(|\z)')
        if (-not $upgradeMatch.Success) {
            $destructive.Add('MISSING_UPGRADE')
            continue
        }
        $upgradeText = $upgradeMatch.Groups['body'].Value
        foreach ($pattern in @(
            'op\.drop_table\s*\(','op\.drop_column\s*\(','op\.drop_constraint\s*\(',
            'op\.alter_column\s*\(','op\.rename_table\s*\(',
            'DROP\s+TABLE','DROP\s+COLUMN','TRUNCATE\s+','DELETE\s+FROM','ALTER\s+TABLE'
        )) {
            if ($upgradeText -match $pattern) { $destructive.Add($pattern) }
        }
    }
    return [pscustomobject]@{ Destructive=($destructive.Count -gt 0); Matches=@($destructive) }
}

function Assert-DDRECHealthSnapshot {
    param($Snapshot,[string]$ExpectedCommit)
    if ($Snapshot.ApiStatus -ne 'ok' -or $Snapshot.Database -ne 'ok' -or $Snapshot.AdminHttp -ne 200 -or -not $Snapshot.ApiContainerHealthy -or -not $Snapshot.PostgresHealthy) {
        throw '生产健康检查失败。'
    }
    if ($ExpectedCommit -and $Snapshot.BuildCommit -cne $ExpectedCommit) { throw '生产 API buildCommit 与目标 Cloud commit 不一致。' }
    return $true
}

function Assert-DDRECCoreCounts {
    param($Before,$After)
    foreach ($name in @('Owners','Licenses','DeviceBindings','LicenseEvents','DeviceTrials','AdminAudit','ClientReleases')) {
        if ([int64]$After.$name -lt [int64]$Before.$name) { throw "生产核心数量异常减少：$name" }
    }
    if ([int64]$After.Owners -lt 1) { throw '生产 OWNER 数量小于 1。' }
    return $true
}

function Assert-DDRECDownloadProbe {
    param($Probe,[int64]$ExpectedLength)
    if ($Probe.StatusCode -ne 200 -or $Probe.RangeStatusCode -ne 206) { throw '客户端下载或 HTTP Range 验证失败（要求 HTTP 200 / Range 206）。' }
    if ([int64]$Probe.ContentLength -ne $ExpectedLength) { throw '客户端下载 Content-Length 不一致。' }
    if (-not $Probe.AcceptRanges) { throw '客户端下载缺少 Accept-Ranges: bytes。' }
    return $true
}

function Assert-DDRECResumeProductionState {
    param([Parameter(Mandatory)]$State,[Parameter(Mandatory)]$RemoteState)
    if(-not $State.CloudDeployed -or -not $State.CurrentSwitched){throw 'Session 未记录 Cloud 部署及 current 切换成功，禁止 Resume。'}
    if([string]$RemoteState.Current -cne [string]$State.CloudRelease){throw "Resume 阻止：current 与 Session 不一致：$($RemoteState.Current) != $($State.CloudRelease)"}
    if(([string]$RemoteState.BuildCommit).ToLowerInvariant() -cne ([string]$State.CloudGitCommit).ToLowerInvariant()){throw "Resume 阻止：API buildCommit 与 Session 不一致。"}
    if($RemoteState.ApiStatus -ne 'ok' -or $RemoteState.Database -ne 'ok' -or $RemoteState.ApiContainer -ne 'healthy' -or $RemoteState.PostgresContainer -ne 'healthy' -or [int]$RemoteState.AdminHttp -ne 200){
        throw 'Resume 阻止：API、PostgreSQL、容器或 Admin 健康检查失败。'
    }
    if([string]$RemoteState.DbRevision -cne [string]$State.DbRevision -or [string]$RemoteState.CodeHead -cne [string]$State.DbRevision){throw 'Resume 阻止：数据库 revision 与 Session 不一致。'}
    return $true
}

function Assert-DDRECSessionClientMetadata {
    param([Parameter(Mandatory)]$SessionItem,[Parameter(Mandatory)]$Metadata)
    foreach($field in @('Path','FileName','Version','BuildNumber','GitCommit','Edition','Environment','FileSize','SHA256')){
        $expected=[string]$SessionItem.$field; $actual=[string]$Metadata.$field
        if($field -eq 'SHA256' -or $field -eq 'GitCommit'){$expected=$expected.ToLowerInvariant();$actual=$actual.ToLowerInvariant()}
        if($expected -cne $actual){throw "Resume 阻止：客户端 $field 与 Session 不一致。"}
    }
    return $true
}

function Assert-DDRECExistingDraftCompatibility {
    param([Parameter(Mandatory)]$Existing,[Parameter(Mandatory)]$Metadata,[Parameter(Mandatory)]$Target)
    $environment=if($Metadata.Edition -eq 'standard'){'production'}else{$Metadata.Environment}
    $expected=[ordered]@{
        product=$script:CurrentProduct;version=$Metadata.Version;buildNumber=[string]$Metadata.BuildNumber;gitCommit=$Metadata.GitCommit
        edition=$Metadata.Edition;environment=$environment;architecture='x64';channel='stable';fileName=$Metadata.FileName
        downloadPath=$Target.RelativePath;fileSize=[string]$Metadata.FileSize;sha256=$Metadata.SHA256
    }
    foreach($field in $expected.Keys){
        $actual=[string]$Existing.$field; $wanted=[string]$expected[$field]
        if($field -in @('sha256','gitCommit')){$actual=$actual.ToLowerInvariant();$wanted=$wanted.ToLowerInvariant()}
        if($actual -cne $wanted){throw "已存在 client release 元数据冲突：$field"}
    }
    if($Existing.status -eq 'withdrawn'){throw '相同 Build 已 withdrawn；禁止覆盖或创建重复记录。'}
    return $true
}

function Assert-DDRECDeployLock { param([bool]$Acquired) if (-not $Acquired) { throw '已有生产发布正在执行。' }; return $true }
function Assert-DDRECApiMutationResult { param($Result,[string]$Operation) if (-not $Result.Success) { throw "$Operation API 失败。" }; return $true }
function Assert-DDRECTransportResult {
    param([int]$ExitCode,[string]$Stage='SSH')
    if ($ExitCode -ne 0) { throw "$Stage 传输失败（退出码 $ExitCode）。" }
    return $true
}
function Assert-DDRECSignatureResult { param([bool]$Valid) if (-not $Valid) { throw 'Ed25519 签名验证失败。' }; return $true }
function Test-DDRECExplicitConfirmation { param([string]$Actual,[string]$Expected) return ($Actual -ceq $Expected) }
function Assert-DDRECReleaseIsolation {
    param([string]$RequestedLane,[string]$ReturnedLane,[string]$Status)
    if ($Status -eq 'draft' -and $ReturnedLane) { throw 'Draft 不得出现在公开更新 API。' }
    if ($ReturnedLane -and $RequestedLane -cne $ReturnedLane) { throw "更新通道隔离失败：$RequestedLane -> $ReturnedLane" }
    return $true
}

function Get-DDRECIdempotencyAction {
    param([string]$ExistingStatus,[string]$ExistingHash,[string]$ExpectedHash)
    Assert-DDRECHashCompatibility -ExistingHash $ExistingHash -ExpectedHash $ExpectedHash | Out-Null
    if ($ExistingStatus -eq 'published') { return 'already-published' }
    if ($ExistingStatus -eq 'draft') { return 'reuse-draft' }
    if ($ExistingHash) { return 'reuse-file' }
    return 'create'
}

function Get-DDRECSshResultKind {
    param([Parameter(Mandatory)][int]$ExitCode)
    if ($ExitCode -eq 0) { return 'Success' }
    if ($ExitCode -eq 255) { return 'TransportFailure' }
    return 'RemoteCommandFailure'
}

function New-DDRECRemoteCommandException {
    param([Parameter(Mandatory)][int]$ExitCode,[AllowEmptyString()][string]$Output)
    $remoteError = if ([string]::IsNullOrWhiteSpace($Output)) {'<no remote output>'} else {$Output.Trim()}
    $exception = [InvalidOperationException]::new("远端发布执行器失败`nRemoteExitCode=$ExitCode`nRemoteError=$remoteError")
    $exception.Data['RemoteExitCode'] = $ExitCode
    $exception.Data['RemoteOutput'] = $Output
    return $exception
}

function Invoke-DDRECSsh {
    param(
        [Parameter(Mandatory)]$Context,
        [Parameter(Mandatory)][string]$Command,
        [switch]$AllowFailure,
        [switch]$NoRetry,
        [scriptblock]$NativeInvoker
    )
    $attempts = if ($NoRetry) {1} else {[int]$Context.Config.SshAttempts}
    for ($attempt=1; $attempt -le $attempts; $attempt++) {
        $result = if ($NativeInvoker) {
            & $NativeInvoker $attempt
        } else {
            Invoke-DDRECNative ssh @('-o','BatchMode=yes','-o','ConnectTimeout=10',[string]$Context.Config.ServerHost,$Command) -AllowFailure -Context $Context
        }
        $kind = Get-DDRECSshResultKind -ExitCode ([int]$result.ExitCode)
        if ($kind -eq 'Success') { return $result }
        if ($kind -eq 'RemoteCommandFailure') {
            if ($AllowFailure) { return $result }
            throw (New-DDRECRemoteCommandException -ExitCode ([int]$result.ExitCode) -Output ([string]$result.Output))
        }
        if ($attempt -lt $attempts) {
            Write-DDRECLog -Context $Context -Level WARN -Message "SSH transport 第 $attempt 次失败，$($Context.Config.SshRetrySeconds) 秒后重试。"
            Start-Sleep -Seconds ([int]$Context.Config.SshRetrySeconds)
        }
    }
    if ($AllowFailure) { return $result }
    throw "SSH transport failure：连续 $attempts 次连接失败。"
}

function ConvertTo-DDRECShellSingleQuote {
    param([Parameter(Mandatory)][string]$Value)
    $replacement = "'" + '"' + "'" + '"' + "'"
    return "'" + $Value.Replace("'", $replacement) + "'"
}

function Join-DDRECPosixPath {
    param(
        [Parameter(Mandatory)][string]$Base,
        [Parameter(Mandatory)][string[]]$Child
    )
    if($Base -notmatch '^/' -or $Base.Contains('\')){throw "POSIX 基础路径无效：$Base"}
    $result=$Base.TrimEnd('/')
    foreach($segment in $Child){
        if([string]::IsNullOrWhiteSpace($segment) -or $segment -in @('.','..') -or $segment.Contains('/') -or $segment.Contains('\')){
            throw "POSIX 路径片段无效：$segment"
        }
        $result="$result/$segment"
    }
    return $result
}

function Get-DDRECRemoteState {
    param([Parameter(Mandatory)]$Context)
    $root = ConvertTo-DDRECShellSingleQuote ([string]$Context.Config.RemoteRoot)
    $downloadRoot = ConvertTo-DDRECShellSingleQuote ([string]$Context.Config.DownloadRoot)
    $scriptText = @'
set -Eeuo pipefail
root=__ROOT__
download_root=__DOWNLOAD_ROOT__
api=$(docker ps --filter name=license-api --format '{{.Names}}' | head -1)
pg=$(docker ps --filter name=postgres --format '{{.Names}}' | head -1)
printf 'current=%s\n' "$(readlink -f "$root/current" 2>/dev/null || true)"
printf 'diskAvailable=%s\n' "$(df -PB1 "$root" | awk 'NR==2{print $4}')"
printf 'apiContainer=%s\n' "$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$api")"
printf 'postgresContainer=%s\n' "$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$pg")"
printf 'dbRevision=%s\n' "$(docker exec "$api" alembic current 2>/dev/null | sed -n 's/ .*//p' | tail -1)"
printf 'codeHead=%s\n' "$(docker exec "$api" alembic heads 2>/dev/null | sed -n 's/ .*//p' | tail -1)"
printf 'downloadRoot=%s\n' "$(nginx -T 2>/dev/null | awk '/server_name[[:space:]]+download\.aixcc\.top/{s=1} s && /root \/var\/www\//{gsub(/;|^[[:space:]]*root[[:space:]]+/,""); print; exit}')"
printf 'adminHttp=%s\n' "$(curl -sS -o /dev/null -w '%{http_code}' https://license.aixcc.top/admin/)"
printf 'downloadHttp=%s\n' "$(curl -sS -o /dev/null -w '%{http_code}' https://download.aixcc.top/)"
curl -fsS https://license.aixcc.top/api/v1/health | sed 's/^/healthJson=/'
echo
sql=$(cat <<'SQL'
SELECT 'owners',count(*) FROM admin_users WHERE role='OWNER'
UNION ALL SELECT 'licenses',count(*) FROM licenses
UNION ALL SELECT 'deviceBindings',count(*) FROM device_bindings
UNION ALL SELECT 'licenseEvents',count(*) FROM license_events
UNION ALL SELECT 'deviceTrials',count(*) FROM device_trials
UNION ALL SELECT 'adminAudit',count(*) FROM admin_audit_events
UNION ALL SELECT 'clientReleases',count(*) FROM client_releases;
SQL
)
printf '%s' "$sql" | docker exec -i "$pg" sh -lc 'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -F "="' | sed 's/^/count./'
'@
    $scriptText = $scriptText.Replace('__ROOT__',$root).Replace('__DOWNLOAD_ROOT__',$downloadRoot)
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($scriptText))
    $command = "printf '%s' '$encoded' | base64 -d | bash"
    $raw = (Invoke-DDRECSsh -Context $Context -Command $command).Output
    $values = @{}
    foreach ($line in $raw -split "`n") { if ($line -match '^([^=]+)=(.*)$') { $values[$matches[1]]=$matches[2].Trim() } }
    $health = if ($values.healthJson) { $values.healthJson | ConvertFrom-Json } else { $null }
    return [pscustomobject]@{
        Current=$values.current; DiskAvailable=[int64]($values.diskAvailable ?? 0)
        ApiContainer=$values.apiContainer; PostgresContainer=$values.postgresContainer
        DbRevision=$values.dbRevision; CodeHead=$values.codeHead; DownloadRoot=$values.downloadRoot
        AdminHttp=[int]($values.adminHttp ?? 0); DownloadHttp=[int]($values.downloadHttp ?? 0)
        ApiStatus=$health.status; Database=$health.database; Version=$health.version; BuildCommit=$health.buildCommit
        Counts=[pscustomobject]@{
            Owners=[int64]($values['count.owners'] ?? 0); Licenses=[int64]($values['count.licenses'] ?? 0)
            DeviceBindings=[int64]($values['count.deviceBindings'] ?? 0); LicenseEvents=[int64]($values['count.licenseEvents'] ?? 0)
            DeviceTrials=[int64]($values['count.deviceTrials'] ?? 0); AdminAudit=[int64]($values['count.adminAudit'] ?? 0)
            ClientReleases=[int64]($values['count.clientReleases'] ?? 0)
        }
        Raw=$raw
    }
}

function Get-DDRECPublicRelease {
    param([ValidateSet('standard','license-production')][string]$Lane,[Parameter(Mandatory)]$Config)
    $edition = if ($Lane -eq 'standard') {'standard'} else {'license'}
    $query = "product=$($script:CurrentProduct)&edition=$edition&environment=production&arch=x64&channel=stable&version=0.0.0&buildNumber=1"
    try { return Invoke-RestMethod -Uri "$($Config.ApiBaseUrl)/client-updates/latest?$query" -TimeoutSec ([int]$Config.HttpTimeoutSeconds) }
    catch { return [pscustomobject]@{ updateAvailable=$false; error=$_.Exception.Message } }
}

function Test-DDRECRemoteClientTarget {
    param([Parameter(Mandatory)]$Context,[Parameter(Mandatory)]$Target,[Parameter(Mandatory)]$Metadata)
    $path = ConvertTo-DDRECShellSingleQuote $Target.RemotePath
    $scriptText=@'
set -Eeuo pipefail
path=__PATH__
if test -e "$path"; then
  test -f "$path" && test ! -L "$path" || exit 40
  printf 'size=%s\nsha256=%s\n' "$(stat -c %s -- "$path")" "$(sha256sum -- "$path" | awk '{print $1}')"
fi
'@
    $scriptText=$scriptText.Replace('__PATH__',$path)
    $encoded=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($scriptText))
    $command="printf '%s' '$encoded' | base64 -d | bash"
    $raw = (Invoke-DDRECSsh -Context $Context -Command $command -NoRetry).Output.Trim()
    $values=@{};foreach($line in $raw -split "`r?`n"){if($line -match '^([^=]+)=(.*)$'){$values[$matches[1]]=$matches[2]}}
    $existing=[string]$values['sha256']
    Assert-DDRECHashCompatibility -ExistingHash $existing -ExpectedHash $Metadata.SHA256 | Out-Null
    if($existing -and [int64]$values['size'] -ne [int64]$Metadata.FileSize){throw "目标不可变文件已存在且大小不同：$($values['size']) != $($Metadata.FileSize)"}
    return [pscustomobject]@{ Exists=[bool]$existing; SHA256=$existing; Size=$(if($values.ContainsKey('size')){[int64]$values['size']}else{[int64]0}) }
}

function Get-DDRECLocalMigrationPlan {
    param([Parameter(Mandatory)][string]$CloudRoot,[string]$CurrentRevision)
    $files = Get-ChildItem -LiteralPath (Join-Path $CloudRoot 'license-server\alembic\versions') -Filter '*.py' -File
    $nodes = @{}
    foreach ($file in $files) {
        $text = Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8
        $revision = if ($text -match '(?m)^revision\s*(?::[^=]+)?=\s*[''"]([^''"]+)[''"]') {$matches[1]} else {$null}
        $down = if ($text -match '(?m)^down_revision\s*(?::[^=]+)?=\s*[''"]([^''"]+)[''"]') {$matches[1]} else {$null}
        if ($revision) { $nodes[$revision]=[pscustomobject]@{Revision=$revision;Down=$down;Path=$file.FullName;Text=$text} }
    }
    $parents = @($nodes.Values | ForEach-Object Down | Where-Object {$_})
    $heads = @($nodes.Keys | Where-Object {$_ -notin $parents})
    if ($heads.Count -ne 1) { throw "无法确定唯一 Alembic head：$($heads -join ', ')" }
    $head = $heads[0]
    $pending = [Collections.Generic.List[object]]::new(); $cursor=$head
    while ($cursor -and $cursor -ne $CurrentRevision) {
        if (-not $nodes.ContainsKey($cursor)) { throw "数据库 revision $CurrentRevision 不在本地迁移链中。" }
        $pending.Insert(0,$nodes[$cursor]); $cursor=$nodes[$cursor].Down
    }
    if ($CurrentRevision -and $cursor -ne $CurrentRevision) { throw "数据库 revision $CurrentRevision 与本地迁移链不兼容。" }
    $safety = Get-DDRECMigrationSafety -MigrationTexts @($pending | ForEach-Object Text)
    return [pscustomobject]@{ Current=$CurrentRevision; Head=$head; Pending=@($pending); Destructive=$safety.Destructive; DestructiveMatches=$safety.Matches }
}

function New-DDRECManifest {
    param([Parameter(Mandatory)]$Metadata)
    Assert-DDRECPackageMetadata -Metadata $Metadata | Out-Null
    return [ordered]@{
        product=$script:CurrentProduct; version=$Metadata.Version; buildNumber=$Metadata.BuildNumber
        edition=$Metadata.Edition; environment=($(if($Metadata.Edition -eq 'standard'){'production'}else{$Metadata.Environment}))
        architecture='x64'; channel='stable'; fileName=$Metadata.FileName; fileSize=$Metadata.FileSize
        sha256=$Metadata.SHA256; publishedAt=[DateTimeOffset]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
    }
}

function Invoke-DDRECManifestSigning {
    param([Parameter(Mandatory)]$Context,[Parameter(Mandatory)]$Metadata)
    Assert-DDRECPackageMetadata -Metadata $Metadata | Out-Null
    if (-not (Test-Path -LiteralPath $Context.Config.UpdatePrivateKey -PathType Leaf)) { throw '本地 Ed25519 更新私钥不存在。' }
    if (-not (Test-Path -LiteralPath $Context.Config.UpdatePublicKey -PathType Leaf)) { throw 'Ed25519 更新公钥不存在。' }
    $sessionDir = Join-Path (Split-Path $Context.LogPath -Parent) $Context.SessionId
    New-Item -ItemType Directory -Path $sessionDir -Force | Out-Null
    $manifestPath = Join-Path $sessionDir "$($Metadata.Edition)-$($Metadata.BuildNumber)-manifest.json"
    $signaturePath = Join-Path $sessionDir "$($Metadata.Edition)-$($Metadata.BuildNumber)-signature.txt"
    New-DDRECManifest -Metadata $Metadata | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding utf8NoBOM
    $python = if (Test-Path (Join-Path $Context.CloudRoot '.venv\Scripts\python.exe')) { Join-Path $Context.CloudRoot '.venv\Scripts\python.exe' } else {'python'}
    $tool = Join-Path $Context.CloudRoot 'scripts\release\signing.py'
    $sign = Invoke-DDRECNative $python @($tool,'sign','--manifest',$manifestPath,'--private-key',$Context.Config.UpdatePrivateKey) -NoLogOutput -Context $Context
    $signature = $sign.Output.Trim()
    [IO.File]::WriteAllText($signaturePath,$signature,[Text.UTF8Encoding]::new($false))
    Invoke-DDRECNative $python @($tool,'verify','--manifest',$manifestPath,'--signature',$signature,'--public-key',$Context.Config.UpdatePublicKey) -NoLogOutput -Context $Context | Out-Null
    return [pscustomobject]@{ ManifestPath=$manifestPath; SignaturePath=$signaturePath; Signature=$signature; Manifest=(Get-Content $manifestPath -Raw | ConvertFrom-Json) }
}

function Initialize-DDRECClientIncomingDirectory {
    param([Parameter(Mandatory)]$Context,[Parameter(Mandatory)]$Metadata)
    $paths=Get-DDRECClientIncomingPaths -Context $Context -Metadata $Metadata
    $rootQ=ConvertTo-DDRECShellSingleQuote ([string]$Context.Config.RemoteRoot)
    $directoryQ=ConvertTo-DDRECShellSingleQuote $paths.Directory
    $command=@"
set -Eeuo pipefail
root=$rootQ
directory=$directoryQ
case "`$directory" in "`$root/incoming/client/"*) ;; *) echo 'unsafe client incoming path' >&2; exit 40;; esac
test ! -L "`$root/incoming" || { echo 'incoming root must not be symlink' >&2; exit 40; }
install -d -o root -g root -m 0750 "`$root/incoming" "`$root/incoming/client" "`$directory"
test "`$(realpath -m "`$directory")" = "`$directory" || { echo 'client incoming path escaped root' >&2; exit 40; }
test ! -L "`$directory" || { echo 'client incoming directory must not be symlink' >&2; exit 40; }
chown root:root "`$directory"
chmod 0750 "`$directory"
printf 'directory=%s\nmode=%s\nowner=%s\n' "`$directory" "`$(stat -c %a "`$directory")" "`$(stat -c %U:%G "`$directory")"
"@
    $result=Invoke-DDRECSsh -Context $Context -Command $command -NoRetry
    if ($result.Output -notmatch '(?m)^mode=750$' -or $result.Output -notmatch '(?m)^owner=root:root$') {
        throw '客户端 incoming 目录权限或所有者验证失败。'
    }
    return $paths
}

function Get-DDRECRemoteIncomingStatus {
    param([Parameter(Mandatory)]$Context,[Parameter(Mandatory)]$Metadata)
    $paths=Get-DDRECClientIncomingPaths -Context $Context -Metadata $Metadata
    $canonicalQ=ConvertTo-DDRECShellSingleQuote $paths.Path
    $legacyQ=ConvertTo-DDRECShellSingleQuote $paths.LegacyPath
    $command=@"
set -Eeuo pipefail
inspect_file() {
  prefix="`$1"
  path="`$2"
  if test ! -e "`$path"; then printf '%s.exists=false\n%s.regular=false\n' "`$prefix" "`$prefix"; return; fi
  printf '%s.exists=true\n' "`$prefix"
  if test -f "`$path" && test ! -L "`$path"; then
    printf '%s.regular=true\n' "`$prefix"
  else
    printf '%s.regular=false\n' "`$prefix"
    return
  fi
  printf '%s.actualName=%s\n' "`$prefix" "`$(basename -- "`$path")"
  printf '%s.size=%s\n' "`$prefix" "`$(stat -c %s -- "`$path")"
  printf '%s.sha256=%s\n' "`$prefix" "`$(sha256sum -- "`$path" | awk '{print `$1}')"
}
inspect_file canonical $canonicalQ
inspect_file legacy $legacyQ
"@
    $raw=(Invoke-DDRECSsh -Context $Context -Command $command -NoRetry).Output
    $values=@{}
    foreach($line in $raw -split "`r?`n"){if($line -match '^([^=]+)=(.*)$'){$values[$matches[1]]=$matches[2]}}
    $canonical=[pscustomobject]@{
        Exists=$values['canonical.exists'] -eq 'true'; Regular=$values['canonical.regular'] -eq 'true'
        FileName=[string]$values['canonical.actualName']; ExpectedFileName=$paths.FileName
        Size=$(if($values.ContainsKey('canonical.size')){[int64]$values['canonical.size']}else{[int64]0})
        SHA256=([string]$values['canonical.sha256']).ToUpperInvariant(); Path=$paths.Path
    }
    $legacy=[pscustomobject]@{
        Exists=$values['legacy.exists'] -eq 'true'; Regular=$values['legacy.regular'] -eq 'true'
        FileName=[string]$values['legacy.actualName']; ExpectedFileName=$paths.LegacyFileName
        Size=$(if($values.ContainsKey('legacy.size')){[int64]$values['legacy.size']}else{[int64]0})
        SHA256=([string]$values['legacy.sha256']).ToUpperInvariant(); Path=$paths.LegacyPath
    }
    return Resolve-DDRECIncomingCandidateStatus -CanonicalStatus $canonical -LegacyStatus $legacy -Metadata $Metadata
}

function Test-DDRECIncomingPackageStatus {
    param([Parameter(Mandatory)]$Status,[Parameter(Mandatory)]$Metadata)
    $expectedName=if($null -ne $Status.PSObject.Properties['ExpectedFileName']){[string]$Status.ExpectedFileName}else{[string]$Metadata.FileName}
    $reason=if(-not $Status.Exists){'文件不存在'}elseif(-not $Status.Regular){'目标不是普通文件或是符号链接'}elseif($Status.FileName -cne $expectedName){'文件名不一致'}elseif([int64]$Status.Size -ne [int64]$Metadata.FileSize){'文件大小不一致'}elseif(([string]$Status.SHA256).ToUpperInvariant() -cne ([string]$Metadata.SHA256).ToUpperInvariant()){'SHA256 不一致'}else{$null}
    return [pscustomobject]@{
        Valid=[string]::IsNullOrEmpty($reason); Reason=$reason; Exists=[bool]$Status.Exists; Regular=[bool]$Status.Regular
        FileName=[string]$Status.FileName; ExpectedFileName=$expectedName
        Size=[int64]$Status.Size; ExpectedSize=[int64]$Metadata.FileSize
        SHA256=([string]$Status.SHA256).ToUpperInvariant(); ExpectedSHA256=([string]$Metadata.SHA256).ToUpperInvariant(); Path=$Status.Path
    }
}

function Resolve-DDRECIncomingCandidateStatus {
    param(
        [Parameter(Mandatory)]$CanonicalStatus,
        [Parameter(Mandatory)]$LegacyStatus,
        [Parameter(Mandatory)]$Metadata
    )
    $canonical=Test-DDRECIncomingPackageStatus -Status $CanonicalStatus -Metadata $Metadata
    $legacy=Test-DDRECIncomingPackageStatus -Status $LegacyStatus -Metadata $Metadata
    if($canonical.Exists -and $legacy.Exists){
        if(-not $canonical.Valid -or -not $legacy.Valid){
            return [pscustomobject]@{
                Valid=$false;Reason="规范 .exe 与历史 .part 冲突：exe=$($canonical.Reason ?? 'PASS')；part=$($legacy.Reason ?? 'PASS')"
                Exists=$true;Regular=($canonical.Regular -and $legacy.Regular);FileName="$($canonical.FileName), $($legacy.FileName)"
                ExpectedFileName=$Metadata.FileName;Size=$canonical.Size;ExpectedSize=[int64]$Metadata.FileSize
                SHA256=$canonical.SHA256;ExpectedSHA256=$Metadata.SHA256;Path=$canonical.Path
                SelectedFileName=$null;SelectedPath=$null;Canonical=$canonical;Legacy=$legacy
            }
        }
        $selected=$canonical
    }elseif($canonical.Exists){
        $selected=$canonical
    }elseif($legacy.Exists){
        $selected=$legacy
    }else{
        $selected=$canonical
    }
    return [pscustomobject]@{
        Valid=$selected.Valid;Reason=$selected.Reason;Exists=$selected.Exists;Regular=$selected.Regular
        FileName=$selected.FileName;ExpectedFileName=$selected.ExpectedFileName;Size=$selected.Size
        ExpectedSize=$selected.ExpectedSize;SHA256=$selected.SHA256;ExpectedSHA256=$selected.ExpectedSHA256
        Path=$selected.Path;SelectedFileName=$(if($selected.Valid){$selected.FileName}else{$null})
        SelectedPath=$(if($selected.Valid){$selected.Path}else{$null});Canonical=$canonical;Legacy=$legacy
    }
}

function Show-DDRECManualUploadPrompt {
    param([Parameter(Mandatory)]$Context,[Parameter(Mandatory)]$Metadata,[Parameter(Mandatory)]$Paths,[Parameter(Mandatory)][string]$Lane)
    $title=if($Lane -eq 'standard'){'Standard'}else{'License-Production'}
    Write-Host ''
    Write-Host ('='*58) -ForegroundColor Cyan
    Write-Host "        请手动上传 $title 安装包" -ForegroundColor Cyan
    Write-Host ('='*58) -ForegroundColor Cyan
    Write-Host "`n本地文件：`n$($Metadata.Path)"
    Write-Host "`n服务器：`n$($Context.Config.ServerAddress)"
    Write-Host "`n远端目录：`n$($Paths.Directory)/"
    Write-Host "`n远端文件名：`n$($Paths.FileName)"
    Write-Host "`n大小：`n$($Metadata.FileSize) bytes"
    Write-Host "`nSHA256：`n$($Metadata.SHA256)"
    Write-Host "`n请使用 WinSCP / SFTP 直接上传原 EXE 文件；无需修改扩展名。"
    Write-Host '不要上传到最终下载目录。'
    Write-Host "`n上传完成后：`n[Enter] 验证并继续`n[R] 重新检查`n[Q] 保存进度并退出"
}

function Get-DDRECAutoUploadFailureAction {
    param([AllowEmptyString()][string]$InputText)
    switch(($InputText ?? '').Trim()){
        '1'{return 'Retry'}
        '2'{return 'Manual'}
        '3'{return 'Save'}
        default{return 'Invalid'}
    }
}

function Invoke-DDRECAutomaticClientUpload {
    param(
        [Parameter(Mandatory)]$Context,[Parameter(Mandatory)]$Metadata,
        [scriptblock]$DirectoryInitializer,[scriptblock]$TransferInvoker,[scriptblock]$StatusReader
    )
    $paths=if($DirectoryInitializer){& $DirectoryInitializer $Context $Metadata}else{Initialize-DDRECClientIncomingDirectory -Context $Context -Metadata $Metadata}
    $server=[string]$Context.Config.ServerHost
    $destination="${server}:$($paths.AutoPath)"
    Write-DDRECLog -Context $Context -Message "自动上传客户端安装包：$($Metadata.FileName) -> $($paths.AutoPath)"
    try{
        $copy=if($TransferInvoker){& $TransferInvoker ([string]$Metadata.Path) $destination}else{Invoke-DDRECNative scp @('-o','BatchMode=yes',[string]$Metadata.Path,$destination) -AllowFailure -NoLogOutput -Context $Context}
    }catch{
        return [pscustomobject]@{Action='Failed';Reason="无法启动 SCP/SFTP 传输：$($_.Exception.Message)";Status=$null;Paths=$paths}
    }
    if($copy.ExitCode -ne 0){
        return [pscustomobject]@{Action='Failed';Reason="SCP/SFTP 传输失败（ExitCode=$($copy.ExitCode)）";Status=$null;Paths=$paths}
    }
    $status=if($StatusReader){& $StatusReader $Context $Metadata}else{Get-DDRECRemoteIncomingStatus -Context $Context -Metadata $Metadata}
    if(-not $status.Valid){
        return [pscustomobject]@{Action='Failed';Reason=$status.Reason;Status=$status;Paths=$paths}
    }
    return [pscustomobject]@{Action='Verified';Reason=$null;Status=$status;Paths=$paths}
}

function Get-DDRECManualUploadAction {
    param([AllowEmptyString()][string]$InputText)
    $value=if($null -eq $InputText){''}else{$InputText.Trim()}
    if($value -match '^(?i)q$'){return 'Quit'}
    if([string]::IsNullOrWhiteSpace($value) -or $value -match '^(?i)r$'){return 'Check'}
    return 'Invalid'
}

function Wait-DDRECManualClientUpload {
    param(
        [Parameter(Mandatory)]$Context,[Parameter(Mandatory)]$Metadata,[Parameter(Mandatory)][string]$Lane,
        [switch]$NonInteractive,[scriptblock]$InputReader
    )
    $paths=Initialize-DDRECClientIncomingDirectory -Context $Context -Metadata $Metadata
    Show-DDRECManualUploadPrompt -Context $Context -Metadata $Metadata -Paths $paths -Lane $Lane
    if($NonInteractive){return [pscustomobject]@{Action='Waiting';Status=$null;Paths=$paths}}
    Write-Host ''
    Sync-DDRECConsoleOutput
    while($true){
        $answer=if($InputReader){[string](& $InputReader)}else{[string](Read-Host '选择')}
        $action=Get-DDRECManualUploadAction -InputText $answer
        if($action -eq 'Quit'){return [pscustomobject]@{Action='Quit';Status=$null;Paths=$paths}}
        if($action -eq 'Invalid'){
            Write-Host '请输入 R 重新检查、Q 保存退出，或直接按 Enter 验证。' -ForegroundColor Yellow
            continue
        }
        $status=Get-DDRECRemoteIncomingStatus -Context $Context -Metadata $Metadata
        if($status.Valid){
            Write-Host "上传验证 PASS：$($status.ExpectedFileName) / $($status.ExpectedSize) bytes / $($status.ExpectedSHA256)" -ForegroundColor Green
            return [pscustomobject]@{Action='Verified';Status=$status;Paths=$paths}
        }
        Write-Host "上传验证未通过：$($status.Reason)" -ForegroundColor Yellow
        Write-Host "实际：Exists=$($status.Exists) Regular=$($status.Regular) FileName=$($status.FileName) Size=$($status.Size) SHA256=$($status.SHA256)"
        Write-Host "期望：FileName=$($status.ExpectedFileName) Size=$($status.ExpectedSize) SHA256=$($status.ExpectedSHA256)"
        Write-Host '[R] 重新检查 / [Q] 保存进度并退出'
    }
}

function Install-DDRECVerifiedClientPackage {
    param([Parameter(Mandatory)]$Context,[Parameter(Mandatory)]$Metadata,[Parameter(Mandatory)]$Target)
    Assert-DDRECPackageMetadata -Metadata $Metadata | Out-Null
    $executor="$(([string]$Context.Config.RemoteRoot).TrimEnd('/'))/scripts/install-client-package.sh"
    $args=@('--session',$Context.SessionId,'--file-name',$Metadata.FileName,'--final',$Target.RemotePath,'--size',[string]$Metadata.FileSize,'--sha256',$Metadata.SHA256)
    $quoted=$args|ForEach-Object{ConvertTo-DDRECShellSingleQuote ([string]$_)}
    $result=Invoke-DDRECSsh -Context $Context -Command "$(ConvertTo-DDRECShellSingleQuote $executor) $($quoted -join ' ')" -NoRetry
    if($result.Output -notmatch '(?im)^result=(installed|reused)$' -or $result.Output -notmatch "(?im)^sha256=$([regex]::Escape($Metadata.SHA256))$"){
        throw '服务器客户端原子安装结果或最终 SHA256 复核失败。'
    }
    $Context.ProductionModified=$true
    $Context.ClientUploaded=$true
    return $result
}

function Test-DDRECDownloadUrl {
    param([Parameter(Mandatory)][string]$Url,[Parameter(Mandatory)][int64]$ExpectedLength,[int]$TimeoutSeconds=20)
    $head = Invoke-WebRequest -Uri $Url -Method Head -TimeoutSec $TimeoutSeconds -SkipHttpErrorCheck
    $range = Invoke-WebRequest -Uri $Url -Headers @{Range='bytes=0-1023'} -TimeoutSec $TimeoutSeconds -SkipHttpErrorCheck
    $length = [int64]($head.Headers.'Content-Length' | Select-Object -First 1)
    $accept = [string]($head.Headers.'Accept-Ranges' | Select-Object -First 1)
    $probe=[pscustomobject]@{StatusCode=[int]$head.StatusCode;RangeStatusCode=[int]$range.StatusCode;ContentLength=$length;AcceptRanges=($accept -match 'bytes');ETag=$head.Headers.ETag;LastModified=$head.Headers.'Last-Modified'}
    Assert-DDRECDownloadProbe -Probe $probe -ExpectedLength $ExpectedLength | Out-Null
    return $probe
}

function ConvertFrom-DDRECSecureInput {
    param([Parameter(Mandatory)][Security.SecureString]$SecureValue)
    $pointer=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureValue)
    try{return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)}finally{[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)}
}

function Get-DDRECHttpErrorDetail {
    param([AllowEmptyString()][string]$ResponseBody)
    if([string]::IsNullOrWhiteSpace($ResponseBody)){return 'Validation: response body unavailable'}
    try{$parsed=$ResponseBody|ConvertFrom-Json}catch{return "ResponseBody: $(Protect-DDRECLogText $ResponseBody)"}
    $lines=[Collections.Generic.List[string]]::new()
    $detailProperty=$parsed.PSObject.Properties['detail']
    $errorProperty=$parsed.PSObject.Properties['error']
    if($detailProperty -and $detailProperty.Value -is [Collections.IEnumerable] -and $detailProperty.Value -isnot [string]){
        foreach($item in @($detailProperty.Value)){
            $field=if($item.loc){@($item.loc|ForEach-Object{[string]$_}) -join '.'}else{'unknown'}
            $message=if($item.msg){[string]$item.msg}else{[string]$item}
            $lines.Add("field=$field message=$message")
        }
    } elseif($errorProperty){
        $lines.Add("code=$($errorProperty.Value.code) message=$($errorProperty.Value.message)")
    } else {$lines.Add((Protect-DDRECLogText $ResponseBody))}
    return 'Validation: ' + ($lines -join '; ')
}

function New-DDRECApiFailureMessage {
    param(
        [Parameter(Mandatory)][string]$Operation,[Parameter(Mandatory)][string]$Method,
        [Parameter(Mandatory)][string]$Endpoint,[int]$Status,[string[]]$RequestFields=@(),
        [AllowEmptyString()][string]$ResponseBody
    )
    $detail=Get-DDRECHttpErrorDetail -ResponseBody $ResponseBody
    return "$Operation 请求失败`nMethod: $Method`nEndpoint: $Endpoint`nHTTP: $Status`nRequestFields: $($RequestFields -join ',')`n$detail"
}

function Invoke-DDRECJsonApiRequest {
    param(
        [Parameter(Mandatory)]$Context,[Parameter(Mandatory)][string]$Operation,
        [ValidateSet('GET','POST','PATCH','PUT','DELETE')][string]$Method,[Parameter(Mandatory)][string]$Endpoint,
        [Microsoft.PowerShell.Commands.WebRequestSession]$WebSession,[hashtable]$Headers,[System.Collections.IDictionary]$Body,
        [scriptblock]$RequestInvoker
    )
    $fields=if($null -ne $Body){@($Body.Keys|ForEach-Object{[string]$_})}else{@()}
    $parameters=@{Uri=$Endpoint;Method=$Method;ContentType='application/json'}
    if($WebSession){$parameters.WebSession=$WebSession}
    if($Headers){$parameters.Headers=$Headers}
    if($null -ne $Body){$parameters.Body=$Body|ConvertTo-Json -Depth 8 -Compress}
    try{
        $result=if($RequestInvoker){& $RequestInvoker $parameters}else{Invoke-RestMethod @parameters}
        Write-DDRECLog -Context $Context -Message "$Operation PASS；Method=$Method Endpoint=$Endpoint RequestFields=$($fields -join ',')"
        return $result
    }catch{
        $status=0
        try{$status=[int]$_.Exception.Response.StatusCode}catch{}
        $responseBody=[string]$_.ErrorDetails.Message
        if([string]::IsNullOrWhiteSpace($responseBody)){
            try{$responseBody=$_.Exception.Response.Content.ReadAsStringAsync().GetAwaiter().GetResult()}catch{}
        }
        throw (New-DDRECApiFailureMessage -Operation $Operation -Method $Method -Endpoint $Endpoint -Status $status -RequestFields $fields -ResponseBody $responseBody)
    }
}

function Start-DDRECAdminLogin {
    param(
        [Parameter(Mandatory)]$Context,[string]$Username,[Security.SecureString]$Password,
        [scriptblock]$RequestInvoker
    )
    if([string]::IsNullOrWhiteSpace($Username)){$Username=Read-Host 'OWNER Username'}
    $ownsPassword=$false
    if($null -eq $Password){$Password=Read-Host 'Password' -AsSecureString;$ownsPassword=$true}
    $plainPassword=ConvertFrom-DDRECSecureInput -SecureValue $Password
    $session=[Microsoft.PowerShell.Commands.WebRequestSession]::new()
    try{
        $login=Invoke-DDRECJsonApiRequest -Context $Context -Operation 'OWNER 登录' -Method POST -Endpoint "$($Context.Config.ApiBaseUrl)/admin/auth/login" -WebSession $session -Body ([ordered]@{username=$Username;password=$plainPassword}) -RequestInvoker $RequestInvoker
    }finally{$plainPassword=$null;if($ownsPassword){$Password.Dispose()}}
    if([string]::IsNullOrWhiteSpace([string]$login.challenge)){throw 'OWNER 登录响应缺少 TOTP challenge。'}
    return [pscustomobject]@{Session=$session;Challenge=[string]$login.challenge;RequestInvoker=$RequestInvoker}
}

function Complete-DDRECAdminTotp {
    param([Parameter(Mandatory)]$Context,[Parameter(Mandatory)]$Login,[Security.SecureString]$Totp)
    $ownsTotp=$false
    if($null -eq $Totp){$Totp=Read-Host 'TOTP' -AsSecureString;$ownsTotp=$true}
    $plainTotp=ConvertFrom-DDRECSecureInput -SecureValue $Totp
    try{
        if($plainTotp -notmatch '^\d{6}$'){throw 'TOTP 格式无效：必须是6位数字。'}
        Invoke-DDRECJsonApiRequest -Context $Context -Operation 'OWNER TOTP 验证' -Method POST -Endpoint "$($Context.Config.ApiBaseUrl)/admin/auth/totp/verify" -WebSession $Login.Session -Body ([ordered]@{challenge=$Login.Challenge;code=$plainTotp}) -RequestInvoker $Login.RequestInvoker | Out-Null
    }finally{$plainTotp=$null;if($ownsTotp){$Totp.Dispose()}}
    $csrf=($Login.Session.Cookies.GetCookies([uri]$Context.Config.ApiBaseUrl)|Where-Object Name -eq 'pms_admin_csrf'|Select-Object -First 1).Value
    if(-not $csrf -and $Login.PSObject.Properties['CsrfToken']){$csrf=[string]$Login.CsrfToken}
    if(-not $csrf){throw 'OWNER TOTP 验证成功但未获得 CSRF 会话。'}
    return [pscustomobject]@{Session=$Login.Session;CsrfToken=$csrf;RequestInvoker=$Login.RequestInvoker}
}

function Connect-DDRECAdminApi {
    param([Parameter(Mandatory)]$Context)
    return Complete-DDRECAdminTotp -Context $Context -Login (Start-DDRECAdminLogin -Context $Context)
}

function Get-DDRECAdminRequestHeaders {
    param([Parameter(Mandatory)]$Auth)
    $csrf=if($Auth.PSObject.Properties['CsrfToken']){[string]$Auth.CsrfToken}elseif($Auth.PSObject.Properties['Headers']){[string]$Auth.Headers['X-CSRF-Token']}else{''}
    if([string]::IsNullOrWhiteSpace($csrf)){throw 'Admin API Auth 缺少 CSRF Token。'}
    return @{'X-CSRF-Token'=$csrf;'X-Request-ID'=[guid]::NewGuid().ToString()}
}

function New-DDRECClientDraftPayload {
    param([Parameter(Mandatory)]$Metadata,[Parameter(Mandatory)]$Target,[Parameter(Mandatory)]$Signed)
    $environment=if($Metadata.Edition -eq 'standard'){'production'}else{$Metadata.Environment}
    $payload=[ordered]@{
        product=$script:CurrentProduct;version=$Metadata.Version;buildNumber=[int]$Metadata.BuildNumber;gitCommit=$Metadata.GitCommit
        edition=$Metadata.Edition;environment=$environment;architecture='x64';channel='stable';title="iVRec V$($Metadata.Version)"
        releaseNotes="iVRec V$($Metadata.Version) Build $($Metadata.BuildNumber) formal release."
        fileName=$Metadata.FileName;downloadPath=$Target.RelativePath;fileSize=[int64]$Metadata.FileSize;sha256=$Metadata.SHA256
        signature=[string]$Signed.Signature;mandatory=$false;publishedAt=$Signed.Manifest.publishedAt
    }
    Assert-DDRECClientDraftPayload -Payload $payload | Out-Null
    return $payload
}

function Assert-DDRECClientDraftPayload {
    param([Parameter(Mandatory)][System.Collections.IDictionary]$Payload)
    $required=@('product','version','buildNumber','gitCommit','edition','environment','architecture','channel','title','releaseNotes','fileName','downloadPath','fileSize','sha256','signature','mandatory','publishedAt')
    $actual=@($Payload.Keys|ForEach-Object{[string]$_})
    foreach($field in $required){if($field -notin $actual -or $null -eq $Payload[$field] -or ($Payload[$field] -is [string] -and [string]::IsNullOrWhiteSpace($Payload[$field]))){throw "Draft Payload 无效：缺少 $field"}}
    foreach($field in $actual){if($field -notin $required){throw "Draft Payload 无效：API Schema 不接受字段 $field"}}
    if($Payload.product -cne $script:CurrentProduct -or $Payload.version -notmatch '^\d+\.\d+\.\d+$' -or [int]$Payload.buildNumber -lt 1){throw 'Draft Payload 无效：Product/Version/BuildNumber 不符合 Schema。'}
    if($Payload.gitCommit -notmatch '^[0-9a-fA-F]{7,40}$' -or $Payload.sha256 -notmatch '^[0-9a-fA-F]{64}$'){throw 'Draft Payload 无效：GitCommit/SHA256 不符合 Schema。'}
    if($Payload.edition -notin @('standard','license') -or $Payload.environment -cne 'production' -or $Payload.channel -cne 'stable' -or $Payload.architecture -cne 'x64'){throw 'Draft Payload 无效：Edition/Environment/Channel/Architecture 不符合正式规则。'}
    if(([string]$Payload.signature).Length -lt 80 -or ([string]$Payload.signature).Length -gt 200){throw 'Draft Payload 无效：Signature 长度不符合 API Schema。'}
    [DateTimeOffset]$published=[DateTimeOffset]::MinValue
    if(-not [DateTimeOffset]::TryParse([string]$Payload.publishedAt,[ref]$published)){throw 'Draft Payload 无效：publishedAt 必须是带时区时间。'}
    if(-not ([string]$Payload.downloadPath).StartsWith('/releases/') -or -not ([string]$Payload.downloadPath).EndsWith('/'+[string]$Payload.fileName)){throw 'Draft Payload 无效：downloadPath 与 fileName 不一致。'}
    return $true
}

function New-DDRECClientDraft {
    param([Parameter(Mandatory)]$Context,[Parameter(Mandatory)]$Auth,[Parameter(Mandatory)]$Metadata,[Parameter(Mandatory)]$Target,[Parameter(Mandatory)]$Signed)
    Assert-DDRECPackageMetadata -Metadata $Metadata | Out-Null
    $headers=Get-DDRECAdminRequestHeaders -Auth $Auth
    $requestInvoker=if($Auth.PSObject.Properties['RequestInvoker']){$Auth.RequestInvoker}else{$null}
    $list=Invoke-DDRECJsonApiRequest -Context $Context -Operation 'Client Release Draft 查询' -Method GET -Endpoint "$($Context.Config.ApiBaseUrl)/admin/client-releases?page=1&pageSize=200" -WebSession $Auth.Session -Headers $headers -RequestInvoker $requestInvoker
    $environment=if($Metadata.Edition -eq 'standard'){'production'}else{$Metadata.Environment}
    $existing=@($list.items|Where-Object{
        $_.product -eq $script:CurrentProduct -and $_.version -eq $Metadata.Version -and [int]$_.buildNumber -eq $Metadata.BuildNumber -and
        $_.edition -eq $Metadata.Edition -and $_.environment -eq $environment -and $_.channel -eq 'stable'
    })|Select-Object -First 1
    if($existing){
        Assert-DDRECExistingDraftCompatibility -Existing $existing -Metadata $Metadata -Target $Target | Out-Null
        if($existing.status -eq 'draft'){$Context.Drafts.Add($existing)}else{$Context.Published.Add($existing)}
        return $existing
    }
    $body=New-DDRECClientDraftPayload -Metadata $Metadata -Target $Target -Signed $Signed
    $operation=if($Metadata.Edition -eq 'standard'){'Standard Draft 创建'}else{'License Draft 创建'}
    $result=Invoke-DDRECJsonApiRequest -Context $Context -Operation $operation -Method POST -Endpoint "$($Context.Config.ApiBaseUrl)/admin/client-releases" -WebSession $Auth.Session -Headers (Get-DDRECAdminRequestHeaders -Auth $Auth) -Body $body -RequestInvoker $requestInvoker
    $Context.Drafts.Add($result.release)
    $Context.DraftCreated=$true
    return $result.release
}

function Publish-DDRECClientDraft {
    param([Parameter(Mandatory)]$Context,[Parameter(Mandatory)]$Auth,[Parameter(Mandatory)]$Draft)
    $requestInvoker=if($Auth.PSObject.Properties['RequestInvoker']){$Auth.RequestInvoker}else{$null}
    $result=Invoke-DDRECJsonApiRequest -Context $Context -Operation 'Client Release Published' -Method POST -Endpoint "$($Context.Config.ApiBaseUrl)/admin/client-releases/$($Draft.id)/publish" -WebSession $Auth.Session -Headers (Get-DDRECAdminRequestHeaders -Auth $Auth) -RequestInvoker $requestInvoker
    $Context.Published.Add($result.release)
    $Context.PublishedCreated=$true
    return $result.release
}

function Invoke-DDRECCloudBuild {
    param(
        [Parameter(Mandatory)]$Context,
        [Parameter(Mandatory)][string]$ExpectedCommit,
        [Parameter(Mandatory)][string]$ExpectedVersion,
        [switch]$Clean
    )
    $script=Join-Path $Context.CloudRoot 'scripts\build_cloud_release.ps1'
    $arguments=@('-NoProfile','-ExecutionPolicy','Bypass','-File',$script,'-Environment','production','-Service','all')
    if ($Clean) { $arguments += '-Clean' }
    Invoke-DDRECNative pwsh $arguments -WorkingDirectory $Context.CloudRoot -Context $Context | Out-Null
    return Get-DDRECCloudPackageMetadata -CloudRoot $Context.CloudRoot -ExpectedCommit $ExpectedCommit -ExpectedVersion $ExpectedVersion -ExpectedBranch $Context.Config.RequiredCloudBranch
}

function Update-DDRECDeploymentState {
    param([Parameter(Mandatory)]$Context,[AllowEmptyString()][string]$Output)
    $stateLine = @($Output -split "`r?`n" | Where-Object { $_ -match 'DDREC_STATE\s+' } | Select-Object -Last 1)
    if ($stateLine.Count -gt 0) {
        foreach ($name in @('Uploaded','BackupCreated','ReleaseInstalled','ContainerRecreated','DeploymentIdentityVerified','DeploymentSucceeded','CurrentSwitched','DatabaseModified','MigrationExecuted','AdminReplaced','RollbackAttempted','RollbackHealthy')) {
            if ($stateLine[0] -match "(?:^|\s)$name=(true|false)(?:\s|$)") {
                $Context.$name = $matches[1] -eq 'true'
            }
        }
    }
    $Context.PreparedProductionArtifacts = $Context.Uploaded -or $Context.BackupCreated -or $Context.ReleaseInstalled
    $Context.ProductionApplicationModified = $Context.ContainerRecreated -or $Context.CurrentSwitched -or $Context.AdminReplaced
    $Context.ProductionModified = $Context.PreparedProductionArtifacts -or $Context.ProductionApplicationModified -or $Context.DatabaseModified -or $Context.ClientUploaded -or $Context.DraftCreated -or $Context.PublishedCreated
    return $Context
}

function Invoke-DDRECCloudDeploy {
    param([Parameter(Mandatory)]$Context,[Parameter(Mandatory)]$Package,[Parameter(Mandatory)][string]$CloudCommit,[bool]$ApproveMigration=$false)
    Assert-DDRECCloudPackageMetadata -Metadata $Package | Out-Null
    $incoming="$($Context.Config.RemoteRoot)/incoming/$($Context.SessionId)-$($Package.FileName)"
    Invoke-DDRECSsh -Context $Context -Command "install -d -m 750 $(ConvertTo-DDRECShellSingleQuote "$($Context.Config.RemoteRoot)/incoming")" | Out-Null
    $scp=Invoke-DDRECNative scp @('-o','BatchMode=yes',$Package.Path,"$($Context.Config.ServerHost):$incoming") -AllowFailure -Context $Context
    if($scp.ExitCode -ne 0){throw 'Cloud 发布包上传失败。'}
    $Context.Uploaded=$true
    $Context.PreparedProductionArtifacts=$true
    $Context.ProductionModified=$true
    $args=@('--session', $Context.SessionId,'--archive',$incoming,'--sha256',$Package.SHA256,'--commit',$CloudCommit)
    if($ApproveMigration){$args+='--approve-migration'}
    $quoted=$args|ForEach-Object{ConvertTo-DDRECShellSingleQuote ([string]$_)}
    $command="$(ConvertTo-DDRECShellSingleQuote ([string]$Context.Config.RemoteExecutor)) $($quoted -join ' ')"
    try {
        $result=Invoke-DDRECSsh -Context $Context -Command $command -NoRetry
        Update-DDRECDeploymentState -Context $Context -Output $result.Output | Out-Null
        return $result
    }
    catch {
        $remoteOutput = [string]$_.Exception.Data['RemoteOutput']
        Update-DDRECDeploymentState -Context $Context -Output $remoteOutput | Out-Null
        throw
    }
}

function Get-DDRECFailureReport {
    param([Parameter(Mandatory)]$Context,[Parameter(Mandatory)][string]$Stage,[Parameter(Mandatory)]$ErrorRecord)
    return [pscustomobject]@{
        FailedStage=$Stage; FailedCommand=$ErrorRecord.Exception.Message; CompletedStages=@($Context.CompletedStages)
        ProductionModified=$Context.ProductionModified
        PreparedProductionArtifacts=$Context.PreparedProductionArtifacts
        ProductionApplicationModified=$Context.ProductionApplicationModified
        Uploaded=$Context.Uploaded; BackupCreated=$Context.BackupCreated; ReleaseInstalled=$Context.ReleaseInstalled
        ContainerRecreated=$Context.ContainerRecreated; DeploymentIdentityVerified=$Context.DeploymentIdentityVerified; DeploymentSucceeded=$Context.DeploymentSucceeded; CurrentSwitched=$Context.CurrentSwitched
        DatabaseModified=$Context.DatabaseModified; MigrationExecuted=$Context.MigrationExecuted; AdminReplaced=$Context.AdminReplaced
        ClientUploaded=$Context.ClientUploaded; DraftCreated=$Context.DraftCreated; PublishedCreated=$Context.PublishedCreated
        RollbackAttempted=$Context.RollbackAttempted; RollbackHealthy=$Context.RollbackHealthy
        Drafts=@($Context.Drafts); Published=@($Context.Published); LogPath=$Context.LogPath
    }
}

function Get-DDRECFailureExitCode {
    param([Parameter(Mandatory)][string]$Stage)
    if ($Stage -match '安装包|客户端') { return $script:ExitCodes.ClientValidation }
    if ($Stage -match 'Migration') { return $script:ExitCodes.Migration }
    if ($Stage -match 'Health') { return $script:ExitCodes.Health }
    if ($Stage -match 'Draft|Published|OWNER') { return $script:ExitCodes.PublishApi }
    if ($Stage -match '上传') { return $script:ExitCodes.Upload }
    return $script:ExitCodes.Preflight
}

Export-ModuleMember -Function *-DDREC*
