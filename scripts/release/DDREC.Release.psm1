Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:ExitCodes = [ordered]@{
    Success = 0; Preflight = 10; Upload = 20; Backup = 30; Deployment = 40
    Migration = 50; Health = 60; ClientValidation = 70; PublishApi = 80
    Cancelled = 90
}

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
    foreach ($name in @('ServerHost','ApiBaseUrl','AdminUrl','DownloadBaseUrl','RemoteRoot','DownloadRoot','RemoteExecutor')) {
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
        Config = $Config
        CompletedStages = [Collections.Generic.List[string]]::new()
        ProductionModified = $false
        MigrationExecuted = $false
        RollbackAttempted = $false
        RollbackHealthy = $false
        Drafts = [Collections.Generic.List[object]]::new()
        Published = [Collections.Generic.List[object]]::new()
    }
    return $context
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

function Get-DDRECGitState {
    param([Parameter(Mandatory)][string]$Repository)
    $branch = (Invoke-DDRECNative git @('branch','--show-current') $Repository).Output.Trim()
    $head = (Invoke-DDRECNative git @('rev-parse','HEAD') $Repository).Output.Trim()
    $remote = (Invoke-DDRECNative git @('rev-parse','origin/v1.3') $Repository).Output.Trim()
    $status = (Invoke-DDRECNative git @('status','--porcelain=v1','--untracked-files=all') $Repository).Output
    return [pscustomobject]@{
        Repository=$Repository; Branch=$branch; Head=$head; Origin=$remote
        Clean=[string]::IsNullOrWhiteSpace($status); Status=$status
    }
}

function Assert-DDRECGitReleaseState {
    param([Parameter(Mandatory)]$State,[string]$RequiredBranch='v1.3')
    if ($State.Branch -cne $RequiredBranch) { throw "Git 分支错误：需要 $RequiredBranch，实际 $($State.Branch)" }
    if (-not $State.Clean) { throw "Git 工作区不干净：$($State.Repository)`n$($State.Status)" }
    if ($State.Head -cne $State.Origin) { throw "Git HEAD 与 origin/$RequiredBranch 不一致：$($State.Head) != $($State.Origin)" }
    return $true
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
    foreach ($field in @('Path','FileName','FileSize','SHA256','Version','BuildNumber','GitCommit','Edition','Environment','UpdaterVersion')) {
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
        [Parameter(Mandatory)][string]$ExpectedCommit
    )
    Assert-DDRECPackageMetadata -Metadata $Metadata | Out-Null
    $expectedEdition = if ($Lane -eq 'standard') {'standard'} else {'license'}
    $expectedEnvironment = if ($Lane -eq 'standard') {'none'} else {'production'}
    if ($Metadata.Edition -cne $expectedEdition) { throw "安装包 Edition 错误：$($Metadata.Edition)" }
    if ($Metadata.Environment -cne $expectedEnvironment) { throw "安装包 Environment 错误：$($Metadata.Environment)" }
    if ($Metadata.GitCommit -cne $ExpectedCommit) { throw "安装包 GitCommit 与当前 client HEAD 不一致：$($Metadata.GitCommit) != $ExpectedCommit" }
    if ($Metadata.Version -notmatch '^\d+\.\d+\.\d+$') { throw 'Version 必须为三段式版本号。' }
    if ([int64]$Metadata.BuildNumber -lt 1) { throw 'BuildNumber 必须大于 0。' }
    if ($Metadata.UpdaterVersion -notmatch '^\d+\.\d+\.\d+$') { throw 'UpdaterVersion 无效或缺失。' }
    return $true
}

function Show-DDRECPackageMetadata {
    param([Parameter(Mandatory)]$Metadata)
    Assert-DDRECPackageMetadata -Metadata $Metadata | Out-Null
    $Metadata |
        Select-Object FileName,Version,BuildNumber,GitCommit,Edition,Environment,UpdaterVersion,FileSize,SHA256 |
        Format-List | Out-Host
}

function Get-DDRECInstallerMetadata {
    param(
        [Parameter(Mandatory)][string]$InstallerPath,
        [ValidateSet('standard','license-production')][string]$Lane,
        [Parameter(Mandatory)][string]$ExpectedCommit
    )
    $file = Get-Item -LiteralPath $InstallerPath -ErrorAction Stop
    $manifestPath = Join-Path $file.DirectoryName 'RELEASE-MANIFEST.txt'
    $checksumsPath = Join-Path $file.DirectoryName 'SHA256SUMS.txt'
    $m = Read-DDRECKeyValueFile $manifestPath
    $manifestFields = [ordered]@{
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
        Version=[string]$m['Version']; BuildNumber=$buildNumber; GitCommit=([string]$m['GitCommit']).ToLowerInvariant()
        Edition=([string]$m['Edition']).ToLowerInvariant(); Environment=([string]$m['LicenseEnvironment']).ToLowerInvariant()
        UpdaterVersion=[string]$m['UpdaterVersion']
        ManifestPath=$manifestPath; ChecksumsPath=$checksumsPath; PEProductVersion=$peProductVersion
    }
    Assert-DDRECInstallerPolicy -Metadata $metadata -Lane $Lane -ExpectedCommit $ExpectedCommit | Out-Null
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
        foreach ($pattern in @('op\.drop_table\s*\(','op\.drop_column\s*\(','DROP\s+TABLE','DROP\s+COLUMN','TRUNCATE\s+','DELETE\s+FROM')) {
            if ($text -match $pattern) { $destructive.Add($pattern) }
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
    if ($Probe.StatusCode -notin @(200,206) -or $Probe.RangeStatusCode -ne 206) { throw '客户端下载或 HTTP Range 验证失败。' }
    if ([int64]$Probe.ContentLength -ne $ExpectedLength) { throw '客户端下载 Content-Length 不一致。' }
    if (-not $Probe.AcceptRanges) { throw '客户端下载缺少 Accept-Ranges: bytes。' }
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

function Invoke-DDRECSsh {
    param(
        [Parameter(Mandatory)]$Context,
        [Parameter(Mandatory)][string]$Command,
        [switch]$AllowFailure,
        [switch]$NoRetry
    )
    $attempts = if ($NoRetry) {1} else {[int]$Context.Config.SshAttempts}
    for ($attempt=1; $attempt -le $attempts; $attempt++) {
        $result = Invoke-DDRECNative ssh @('-o','BatchMode=yes','-o','ConnectTimeout=10',[string]$Context.Config.ServerHost,$Command) -AllowFailure -Context $Context
        if ($result.ExitCode -eq 0) { return $result }
        if ($attempt -lt $attempts) {
            Write-DDRECLog -Context $Context -Level WARN -Message "SSH 第 $attempt 次失败，$($Context.Config.SshRetrySeconds) 秒后重试。"
            Start-Sleep -Seconds ([int]$Context.Config.SshRetrySeconds)
        }
    }
    if ($AllowFailure) { return $result }
    throw "SSH 连续 $attempts 次失败。"
}

function ConvertTo-DDRECShellSingleQuote {
    param([Parameter(Mandatory)][string]$Value)
    $replacement = "'" + '"' + "'" + '"' + "'"
    return "'" + $Value.Replace("'", $replacement) + "'"
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
    $query = "product=DDREC&edition=$edition&environment=production&arch=x64&channel=stable&version=0.0.0&buildNumber=1"
    try { return Invoke-RestMethod -Uri "$($Config.ApiBaseUrl)/client-updates/latest?$query" -TimeoutSec ([int]$Config.HttpTimeoutSeconds) }
    catch { return [pscustomobject]@{ updateAvailable=$false; error=$_.Exception.Message } }
}

function Test-DDRECRemoteClientTarget {
    param([Parameter(Mandatory)]$Context,[Parameter(Mandatory)]$Target,[Parameter(Mandatory)]$Metadata)
    $path = ConvertTo-DDRECShellSingleQuote $Target.RemotePath
    $command = "if test -f $path; then sha256sum $path | awk '{print `$1}'; fi"
    $existing = (Invoke-DDRECSsh -Context $Context -Command $command).Output.Trim()
    Assert-DDRECHashCompatibility -ExistingHash $existing -ExpectedHash $Metadata.SHA256 | Out-Null
    return [pscustomobject]@{ Exists=[bool]$existing; SHA256=$existing }
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
        product='DDREC'; version=$Metadata.Version; buildNumber=$Metadata.BuildNumber
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

function Invoke-DDRECClientUpload {
    param([Parameter(Mandatory)]$Context,[Parameter(Mandatory)]$Metadata,[Parameter(Mandatory)]$Target)
    Assert-DDRECPackageMetadata -Metadata $Metadata | Out-Null
    $incoming = "$($Context.Config.RemoteRoot)/incoming/client/$($Context.SessionId)/$($Metadata.FileName).part"
    $incomingDir = Split-Path $incoming -Parent
    $mkdir = "install -d -m 750 $(ConvertTo-DDRECShellSingleQuote $incomingDir)"
    Invoke-DDRECSsh -Context $Context -Command $mkdir | Out-Null
    $scp = Invoke-DDRECNative scp @('-o','BatchMode=yes',$Metadata.Path,"$($Context.Config.ServerHost):$incoming") -AllowFailure -Context $Context
    if ($scp.ExitCode -ne 0) { throw 'SCP 上传客户端安装包失败；不会创建 Draft 或 Published。' }
    $incomingQ=ConvertTo-DDRECShellSingleQuote $incoming; $finalQ=ConvertTo-DDRECShellSingleQuote $Target.RemotePath
    $dirQ=ConvertTo-DDRECShellSingleQuote (Split-Path $Target.RemotePath -Parent); $hashQ=ConvertTo-DDRECShellSingleQuote $Metadata.SHA256
    $lockQ=ConvertTo-DDRECShellSingleQuote "$($Context.Config.RemoteRoot)/.deploy.lock"
    $command=@"
set -Eeuo pipefail
exec 9>$lockQ
flock -n 9 || { echo 'deployment lock busy' >&2; exit 21; }
test "`$(stat -c%s $incomingQ)" -eq $($Metadata.FileSize)
echo "$($Metadata.SHA256)  $incoming" | sha256sum -c -
install -d -m 755 $dirQ
if test -e $finalQ; then
  test "`$(sha256sum $finalQ | awk '{print `$1}')" = "`$(printf '%s' $hashQ | tr A-F a-f)" || exit 22
  rm -f $incomingQ
else
  staged="$(Split-Path $Target.RemotePath -Parent)/.$($Metadata.FileName).$($Context.SessionId).part"
  install -m 0644 $incomingQ "`$staged"
  echo "$($Metadata.SHA256)  `$staged" | sha256sum -c -
  ln "`$staged" $finalQ
  rm -f "`$staged" $incomingQ
fi
sha256sum $finalQ
"@
    $result=Invoke-DDRECSsh -Context $Context -Command $command -NoRetry
    if ($result.Output -notmatch $Metadata.SHA256.ToLowerInvariant()) { throw '服务器最终客户端 SHA256 复核失败。' }
    $Context.ProductionModified=$true
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

function Connect-DDRECAdminApi {
    param([Parameter(Mandatory)]$Context)
    $username=Read-Host 'OWNER Username'
    $secure=Read-Host 'Password' -AsSecureString
    $ptr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { $password=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
    $session=[Microsoft.PowerShell.Commands.WebRequestSession]::new()
    try {
        $login=Invoke-RestMethod -Uri "$($Context.Config.ApiBaseUrl)/admin/auth/login" -Method Post -WebSession $session -ContentType 'application/json' -Body (@{username=$username;password=$password}|ConvertTo-Json -Compress)
    } finally { $password=$null; $secure.Dispose() }
    $totp=Read-Host 'TOTP'
    try {
        Invoke-RestMethod -Uri "$($Context.Config.ApiBaseUrl)/admin/auth/totp/verify" -Method Post -WebSession $session -ContentType 'application/json' -Body (@{challenge=$login.challenge;code=$totp}|ConvertTo-Json -Compress) | Out-Null
    } finally { $totp=$null }
    $csrf=($session.Cookies.GetCookies([uri]$Context.Config.ApiBaseUrl) | Where-Object Name -eq 'pms_admin_csrf' | Select-Object -First 1).Value
    if (-not $csrf) { throw 'OWNER 登录成功但未获得 CSRF 会话。' }
    return [pscustomobject]@{Session=$session;Headers=@{'X-CSRF-Token'=$csrf; 'X-Request-ID'=[guid]::NewGuid().ToString()}}
}

function New-DDRECClientDraft {
    param([Parameter(Mandatory)]$Context,[Parameter(Mandatory)]$Auth,[Parameter(Mandatory)]$Metadata,[Parameter(Mandatory)]$Target,[Parameter(Mandatory)]$Signed)
    Assert-DDRECPackageMetadata -Metadata $Metadata | Out-Null
    $list=Invoke-RestMethod -Uri "$($Context.Config.ApiBaseUrl)/admin/client-releases?page=1&pageSize=200" -Method Get -WebSession $Auth.Session -Headers $Auth.Headers
    $environment=if($Metadata.Edition -eq 'standard'){'production'}else{$Metadata.Environment}
    $existing=@($list.items|Where-Object{
        $_.product -eq 'DDREC' -and $_.version -eq $Metadata.Version -and [int]$_.buildNumber -eq $Metadata.BuildNumber -and
        $_.edition -eq $Metadata.Edition -and $_.environment -eq $environment -and $_.channel -eq 'stable'
    })|Select-Object -First 1
    if($existing){
        if(([string]$existing.sha256).ToUpperInvariant() -cne $Metadata.SHA256){throw '已存在 client release 的 SHA256 与本地安装包不同。'}
        if($existing.status -eq 'withdrawn'){throw '相同 Build 已 withdrawn；禁止覆盖或创建重复记录。'}
        if($existing.status -eq 'draft'){$Context.Drafts.Add($existing)}else{$Context.Published.Add($existing)}
        return $existing
    }
    $body=[ordered]@{
        product='DDREC';version=$Metadata.Version;buildNumber=$Metadata.BuildNumber;gitCommit=$Metadata.GitCommit
        edition=$Metadata.Edition;environment=$environment
        architecture='x64';channel='stable';title="DD Rec V$($Metadata.Version)";releaseNotes=''
        fileName=$Metadata.FileName;downloadPath=$Target.RelativePath;fileSize=$Metadata.FileSize;sha256=$Metadata.SHA256
        signature=$Signed.Signature;mandatory=$false;publishedAt=$Signed.Manifest.publishedAt
    }
    $result=Invoke-RestMethod -Uri "$($Context.Config.ApiBaseUrl)/admin/client-releases" -Method Post -WebSession $Auth.Session -Headers $Auth.Headers -ContentType 'application/json' -Body ($body|ConvertTo-Json -Depth 5 -Compress)
    $Context.Drafts.Add($result.release)
    return $result.release
}

function Publish-DDRECClientDraft {
    param([Parameter(Mandatory)]$Context,[Parameter(Mandatory)]$Auth,[Parameter(Mandatory)]$Draft)
    $result=Invoke-RestMethod -Uri "$($Context.Config.ApiBaseUrl)/admin/client-releases/$($Draft.id)/publish" -Method Post -WebSession $Auth.Session -Headers $Auth.Headers -ContentType 'application/json'
    $Context.Published.Add($result.release)
    return $result.release
}

function Invoke-DDRECCloudBuild {
    param([Parameter(Mandatory)]$Context)
    $script=Join-Path $Context.CloudRoot 'scripts\build_cloud_release.ps1'
    Invoke-DDRECNative pwsh @('-NoProfile','-ExecutionPolicy','Bypass','-File',$script,'-Environment','production','-Service','all') -WorkingDirectory $Context.CloudRoot -Context $Context | Out-Null
    $root=Join-Path $Context.CloudRoot 'artifacts\cloud\production\all'
    $archive=Get-ChildItem -LiteralPath $root -Filter '*.tar.gz' -File | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
    if (-not $archive) { throw 'Cloud 生产发布包未生成。' }
    $hash=(Get-FileHash $archive.FullName -Algorithm SHA256).Hash.ToUpperInvariant()
    return [pscustomobject]@{Path=$archive.FullName;Name=$archive.Name;SHA256=$hash;Size=$archive.Length}
}

function Invoke-DDRECCloudDeploy {
    param([Parameter(Mandatory)]$Context,[Parameter(Mandatory)]$Package,[Parameter(Mandatory)][string]$CloudCommit,[bool]$ApproveMigration=$false)
    $incoming="$($Context.Config.RemoteRoot)/incoming/$($Context.SessionId)-$($Package.Name)"
    Invoke-DDRECSsh -Context $Context -Command "install -d -m 750 $(ConvertTo-DDRECShellSingleQuote "$($Context.Config.RemoteRoot)/incoming")" | Out-Null
    $scp=Invoke-DDRECNative scp @('-o','BatchMode=yes',$Package.Path,"$($Context.Config.ServerHost):$incoming") -AllowFailure -Context $Context
    if($scp.ExitCode -ne 0){throw 'Cloud 发布包上传失败。'}
    $args=@('--session', $Context.SessionId,'--archive',$incoming,'--sha256',$Package.SHA256,'--commit',$CloudCommit)
    if($ApproveMigration){$args+='--approve-migration'}
    $quoted=$args|ForEach-Object{ConvertTo-DDRECShellSingleQuote ([string]$_)}
    $command="$(ConvertTo-DDRECShellSingleQuote ([string]$Context.Config.RemoteExecutor)) $($quoted -join ' ')"
    try { $result=Invoke-DDRECSsh -Context $Context -Command $command -NoRetry; $Context.ProductionModified=$true; return $result }
    catch { $Context.ProductionModified=$true; throw }
}

function Get-DDRECFailureReport {
    param([Parameter(Mandatory)]$Context,[Parameter(Mandatory)][string]$Stage,[Parameter(Mandatory)]$ErrorRecord)
    return [pscustomobject]@{
        FailedStage=$Stage; FailedCommand=$ErrorRecord.Exception.Message; CompletedStages=@($Context.CompletedStages)
        ProductionModified=$Context.ProductionModified; MigrationExecuted=$Context.MigrationExecuted
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
