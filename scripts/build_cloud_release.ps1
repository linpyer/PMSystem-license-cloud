[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('production')]
    [string]$Environment,

    [Parameter(Mandatory = $true)]
    [ValidateSet('api', 'admin', 'all')]
    [string]$Service,

    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$Version,

    [switch]$Clean,
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$artifactScript = Join-Path $PSScriptRoot 'cloud_build_artifacts.ps1'
if (-not (Test-Path -LiteralPath $artifactScript -PathType Leaf)) {
    throw "缺少云端构建产物安全脚本：$artifactScript"
}
. $artifactScript

$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptRoot '..'))
$configPath = Join-Path $scriptRoot 'cloud_release_config.psd1'

function Write-Utf8File {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string[]]$Lines,
        [switch]$UnixNewlines
    )
    $newline = if ($UnixNewlines) { "`n" } else { "`r`n" }
    [System.IO.File]::WriteAllText($Path, (($Lines -join $newline) + $newline), $script:utf8NoBom)
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [string]$FailureMessage = '命令执行失败'
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMessage（退出代码 $LASTEXITCODE）：$FilePath $($Arguments -join ' ')"
    }
}

function Get-RelativeUnixPath {
    param([Parameter(Mandatory = $true)][string]$Base, [Parameter(Mandatory = $true)][string]$Path)
    $baseFull = [System.IO.Path]::GetFullPath($Base).TrimEnd('\') + '\'
    $pathFull = [System.IO.Path]::GetFullPath($Path)
    $relative = ([Uri]$baseFull).MakeRelativeUri([Uri]$pathFull).ToString()
    return [Uri]::UnescapeDataString($relative).Replace('\', '/')
}

function Assert-ChildPath {
    param([Parameter(Mandatory = $true)][string]$Parent, [Parameter(Mandatory = $true)][string]$Child)
    $parentFull = [System.IO.Path]::GetFullPath($Parent).TrimEnd('\') + '\'
    $childFull = [System.IO.Path]::GetFullPath($Child)
    if (-not $childFull.StartsWith($parentFull, [StringComparison]::OrdinalIgnoreCase)) {
        throw "拒绝操作不安全的路径：$childFull"
    }
}

function Copy-FilteredTree {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination,
        [string[]]$ExcludedDirectories = @('__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', '.venv', 'venv', 'node_modules', 'dist', '.git', '.secrets'),
        [string[]]$ExcludedFiles = @('.env'),
        [string[]]$ExcludedExtensions = @('.pyc', '.pyo', '.db', '.sqlite', '.sqlite3', '.log')
    )
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    $sourceFull = [System.IO.Path]::GetFullPath($Source)
    foreach ($file in Get-ChildItem -LiteralPath $sourceFull -Recurse -Force -File) {
        $relative = Get-RelativeUnixPath $sourceFull $file.FullName
        $segments = $relative -split '/'
        if (@($segments | Where-Object { $ExcludedDirectories -contains $_ }).Count -gt 0) { continue }
        if ($ExcludedFiles -contains $file.Name) { continue }
        if ($ExcludedExtensions -contains $file.Extension.ToLowerInvariant()) { continue }
        $target = Join-Path $Destination ($relative.Replace('/', '\'))
        $targetParent = Split-Path -Parent $target
        New-Item -ItemType Directory -Path $targetParent -Force | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $target -Force
    }
}

function Get-CommandPath {
    param([Parameter(Mandatory = $true)][string]$Name)
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $command) { throw "缺少构建工具：$Name" }
    return $command.Source
}

function Initialize-PythonBuildEnvironment {
    param(
        [Parameter(Mandatory = $true)][string]$BasePython,
        [Parameter(Mandatory = $true)][string]$ArtifactRoot
    )
    $venvRoot = Join-Path $ArtifactRoot '.venv'
    $venvPython = Join-Path $venvRoot 'Scripts\python.exe'
    $stampPath = Join-Path $venvRoot '.dependency-stamp'
    $dependencyStamp = @(
        (Get-FileHash -LiteralPath (Join-Path $script:serverRoot 'pyproject.toml') -Algorithm SHA256).Hash,
        (Get-FileHash -LiteralPath (Join-Path $script:serverRoot 'constraints.txt') -Algorithm SHA256).Hash
    ) -join ':'
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        Write-Host "创建后端构建虚拟环境：$venvRoot"
        New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null
        Invoke-Checked $BasePython @('-m', 'venv', $venvRoot) '创建 Python 虚拟环境失败'
    }
    $installedStamp = if (Test-Path -LiteralPath $stampPath -PathType Leaf) {
        (Get-Content -LiteralPath $stampPath -Raw -Encoding UTF8).Trim()
    } else { '' }
    if ($installedStamp -ne $dependencyStamp) {
        Write-Host '安装后端锁定依赖...'
        Push-Location $script:serverRoot
        try {
            Invoke-Checked $venvPython @('-m', 'pip', 'install', '--disable-pip-version-check', '-e', '.[dev]', '--constraint', 'constraints.txt') '安装后端依赖失败'
        } finally {
            Pop-Location
        }
        [System.IO.File]::WriteAllText($stampPath, "$dependencyStamp`r`n", $script:utf8NoBom)
    }
    $script:pythonBuildPath = $venvPython
}

function Assert-VersionConsistency {
    param([Parameter(Mandatory = $true)][string]$ExpectedVersion)
    $pyproject = Get-Content -LiteralPath (Join-Path $script:serverRoot 'pyproject.toml') -Raw -Encoding UTF8
    $apiMatch = [regex]::Match($pyproject, '(?m)^version\s*=\s*"([^"]+)"')
    if (-not $apiMatch.Success) { throw '无法从 license-server/pyproject.toml 读取版本号。' }
    $adminPackageText = Get-Content -LiteralPath (Join-Path $script:adminRoot 'package.json') -Raw -Encoding UTF8
    $lockPackageText = Get-Content -LiteralPath (Join-Path $script:adminRoot 'package-lock.json') -Raw -Encoding UTF8
    $adminMatch = [regex]::Match($adminPackageText, '(?m)^\s*"version"\s*:\s*"([^"]+)"')
    $lockMatch = [regex]::Match($lockPackageText, '(?m)^\s*"version"\s*:\s*"([^"]+)"')
    if (-not $adminMatch.Success -or -not $lockMatch.Success) { throw '无法读取前端 package 版本号。' }
    $versions = @{
        'VERSION' = $ExpectedVersion
        'license-server/pyproject.toml' = $apiMatch.Groups[1].Value
        'license-admin/package.json' = $adminMatch.Groups[1].Value
        'license-admin/package-lock.json' = $lockMatch.Groups[1].Value
    }
    $mismatches = @($versions.GetEnumerator() | Where-Object { $_.Value -ne $ExpectedVersion })
    if ($mismatches) {
        throw "云端版本不一致：$($mismatches | ForEach-Object { "$($_.Key)=$($_.Value)" } | Sort-Object | Out-String)"
    }
}

function Assert-ProductionGitState {
    if ($script:branch -ne $script:config.ProductionBranch) {
        throw "生产构建只允许在分支 $($script:config.ProductionBranch) 执行，当前分支为 $script:branch。"
    }
    if (-not $script:isClean) {
        Write-Host '未提交文件：' -ForegroundColor Red
        $script:dirtyLines | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
        throw '生产构建要求 Git 工作区干净。'
    }
}

function Assert-ProductionEnvironment {
    param([Parameter(Mandatory = $true)][hashtable]$EnvironmentConfig)
    if ($EnvironmentConfig.ApiBaseUrl -ne 'https://license.aixcc.top/api/v1') {
        throw '生产 API 地址必须精确为 https://license.aixcc.top/api/v1。'
    }
    if (-not $EnvironmentConfig.ApiBaseUrl.StartsWith('https://', [StringComparison]::OrdinalIgnoreCase)) {
        throw '生产 API 地址必须使用 HTTPS。'
    }
    if ($EnvironmentConfig.AdminEnvironment -ne 'production' -or $EnvironmentConfig.AdminLabel -ne '生产环境') {
        throw '生产后台环境标识配置错误。'
    }
    foreach ($value in @($EnvironmentConfig.ApiBaseUrl, $EnvironmentConfig.PublicBaseUrl, $EnvironmentConfig.AdminBaseUrl)) {
        if ($value -match '(?i)localhost|127\.0\.0\.1|47\.98\.206\.68|^http://') {
            throw "生产对外地址包含禁止值：$value"
        }
    }
}

function Test-PlaceholderValue {
    param([string]$Value)
    $normalized = $Value.Trim().Trim('"', "'")
    return [string]::IsNullOrWhiteSpace($normalized) -or
        $normalized -match '^(?i)(REPLACE_|replace-|CHANGE_|example|dummy|test-|ci-|development-|ddrec_license_dev_only|\$\{|<)'
}

function Assert-NoSensitiveMaterial {
    param([Parameter(Mandatory = $true)][string[]]$Files, [Parameter(Mandatory = $true)][string]$Scope)
    $findings = [System.Collections.Generic.List[object]]::new()
    $secretNames = 'POSTGRES_PASSWORD|DATABASE_PASSWORD|ADMIN_PASSWORD|TOTP_SECRET|JWT_SECRET|FERNET_KEY|PRIVATE_KEY|LICENSE_ADMIN_SESSION_SECRET|LICENSE_ADMIN_TOTP_ENCRYPTION_KEY|LICENSE_CODE_PEPPER|LICENSE_DEVICE_CREDENTIAL_PEPPER'
    foreach ($file in $Files | Sort-Object -Unique) {
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { continue }
        $extension = [System.IO.Path]::GetExtension($file).ToLowerInvariant()
        if ($extension -in @('.exe', '.dll', '.png', '.jpg', '.jpeg', '.ico', '.woff', '.woff2', '.tar', '.gz', '.zip')) { continue }
        try { $text = Get-Content -LiteralPath $file -Raw -Encoding UTF8 } catch { continue }
        if ($text -match '(?s)-----BEGIN (?:RSA |EC |OPENSSH |ED25519 )?PRIVATE KEY-----\s+[A-Za-z0-9+/=\r\n]{64,}\s+-----END (?:RSA |EC |OPENSSH |ED25519 )?PRIVATE KEY-----') {
            $findings.Add([pscustomobject]@{ Type = 'PRIVATE_KEY_MATERIAL'; File = $file })
        }
        if ($file -notmatch '(?i)package-lock\.json$' -and $text -match '(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}(?![A-Za-z0-9])') {
            $findings.Add([pscustomobject]@{ Type = 'AWS_ACCESS_KEY'; File = $file })
        }
        $isTestFixture = $file -match '(?i)[\\/]tests?[\\/]'
        foreach ($line in ($text -split "`r?`n")) {
            $match = [regex]::Match($line, "^\s*(?:export\s+)?($secretNames)\s*[:=]\s*(.+?)\s*$")
            if (-not $isTestFixture -and $match.Success -and -not (Test-PlaceholderValue $match.Groups[2].Value)) {
                $findings.Add([pscustomobject]@{ Type = $match.Groups[1].Value.ToUpperInvariant(); File = $file })
            }
            $urlMatch = [regex]::Match($line, '^\s*(?:LICENSE_)?DATABASE_URL\s*[:=]\s*(.+?)\s*$')
            if (-not $isTestFixture -and $urlMatch.Success -and $urlMatch.Groups[1].Value -match '://[^:/\s]+:([^@\s]+)@') {
                $password = $Matches[1]
                if (-not (Test-PlaceholderValue $password)) {
                    $findings.Add([pscustomobject]@{ Type = 'DATABASE_URL_PASSWORD'; File = $file })
                }
            }
        }
    }
    if ($findings.Count -gt 0) {
        Write-Host "在 $Scope 中发现敏感信息：" -ForegroundColor Red
        $findings | Sort-Object Type, File -Unique | ForEach-Object {
            Write-Host "  类型=$($_.Type) 文件=$($_.File)" -ForegroundColor Red
        }
        throw "$Scope 敏感信息检查失败。"
    }
}

function Invoke-ApiChecks {
    Write-Host '执行后端检查...'
    Push-Location $script:serverRoot
    try {
        Invoke-Checked $script:python @('-m', 'compileall', '-q', 'app', 'alembic') 'Python 编译检查失败'
        Invoke-Checked $script:python @('-m', 'pip', 'check') 'Python 依赖检查失败'
        if (-not $SkipTests) {
            Invoke-Checked $script:python @('-m', 'pytest', '-q', '-m', 'not integration') '后端单元测试失败'
        }
        Invoke-Checked $script:alembic @('-c', 'alembic.ini', 'heads') 'Alembic 迁移检查失败'
    } finally {
        Pop-Location
    }
}

function Invoke-AdminBuild {
    param([Parameter(Mandatory = $true)][hashtable]$EnvironmentConfig)
    Write-Host '执行管理后台依赖、测试和构建...'
    Push-Location $script:adminRoot
    try {
        Invoke-Checked $script:npm @('ci', '--ignore-scripts') 'npm ci 失败'
        if (-not $SkipTests) {
            Invoke-Checked $script:npm @('run', 'type-check') '前端类型检查失败'
            Invoke-Checked $script:npm @('test') '前端单元测试失败'
        }
        $savedEnvironment = @{}
        foreach ($name in @('NODE_ENV', 'VITE_API_BASE_URL', 'VITE_APP_ENVIRONMENT', 'VITE_APP_ENV_LABEL', 'VITE_APP_TITLE', 'VITE_APP_VERSION', 'VITE_BASE_PATH')) {
            $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
        }
        try {
            $env:NODE_ENV = 'production'
            $env:VITE_API_BASE_URL = $EnvironmentConfig.ApiBaseUrl
            $env:VITE_APP_ENVIRONMENT = $EnvironmentConfig.AdminEnvironment
            $env:VITE_APP_ENV_LABEL = $EnvironmentConfig.AdminLabel
            $env:VITE_APP_TITLE = $EnvironmentConfig.AdminTitle
            $env:VITE_APP_VERSION = $script:releaseVersion
            $env:VITE_BASE_PATH = $EnvironmentConfig.AdminBasePath
            $buildCommand = if ($Environment -eq 'production') { 'build:production' } else { 'build:app' }
            Invoke-Checked $script:npm @('run', $buildCommand) '前端构建失败'
        } finally {
            foreach ($name in $savedEnvironment.Keys) {
                [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process')
            }
        }
    } finally {
        Pop-Location
    }

    $distRoot = Join-Path $script:adminRoot 'dist'
    $indexPath = Join-Path $distRoot 'index.html'
    if (-not (Test-Path -LiteralPath $indexPath -PathType Leaf)) { throw '前端未生成 dist/index.html。' }
    $index = Get-Content -LiteralPath $indexPath -Raw -Encoding UTF8
    if ($index -notmatch '/admin/') { throw '前端 index.html 未使用 /admin/ 子路径。' }
    $hashedAssets = @(Get-ChildItem -LiteralPath (Join-Path $distRoot 'assets') -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '-[A-Za-z0-9_-]{8,}\.(?:js|css)$' })
    if ($hashedAssets.Count -eq 0) { throw '前端构建产物未发现带 hash 的 JS/CSS 资源。' }

    $runtimeTextFiles = @(Get-ChildItem -LiteralPath $distRoot -Recurse -File | Where-Object { $_.Extension -in @('.html', '.js', '.css', '.json', '.txt') })
    $runtimeText = ($runtimeTextFiles | ForEach-Object { Get-Content -LiteralPath $_.FullName -Raw -Encoding UTF8 }) -join "`n"
    if (-not $runtimeText.Contains($EnvironmentConfig.ApiBaseUrl)) { throw "前端产物缺少 API 地址 $($EnvironmentConfig.ApiBaseUrl)。" }
    if (-not $runtimeText.Contains($EnvironmentConfig.AdminLabel)) { throw "前端产物缺少环境标签 $($EnvironmentConfig.AdminLabel)。" }
    if ($Environment -eq 'production') {
        foreach ($forbidden in @('开发环境', 'localhost', '127.0.0.1', '47.98.206.68')) {
            if ($runtimeText -match [regex]::Escape($forbidden)) { throw "生产前端产物包含禁止内容：$forbidden" }
        }
    }
    $script:builtAdminDist = $distRoot
}

function Assert-ProductionComposeTemplate {
    Write-Host '静态验证生产 Compose 配置...'
    $deployRoot = Join-Path $projectRoot 'deploy\production-nginx'
    $composePath = Join-Path $deployRoot 'compose.yml'
    $composeText = Get-Content -LiteralPath $composePath -Raw -Encoding UTF8
    foreach ($required in @(
        'services:', 'postgres:', 'license-api:', 'postgres:17.5-alpine',
        'ddrec-license-api:${DDREC_API_IMAGE_TAG:', 'pull_policy: never'
    )) {
        if (-not $composeText.Contains($required)) { throw "生产 Compose 缺少必要配置：$required" }
    }
    if ($composeText -match '(?im)^\s*build\s*:') { throw '生产 Compose 不得隐式 build；API 镜像由服务器执行器显式构建。' }
}

function Add-ApiUpgradeWheel {
    param([Parameter(Mandatory = $true)][string]$Destination)
    Write-Host '生成服务器侧 API 镜像构建 wheel...'
    Invoke-Checked $script:pythonBuildPath @(
        '-m', 'pip', 'wheel', '--disable-pip-version-check', '--no-deps',
        '--wheel-dir', $Destination, $script:serverRoot
    ) '生成 API wheel 失败'
    $wheels = @(Get-ChildItem -LiteralPath $Destination -File -Filter 'ddrec_license_server-*.whl')
    if ($wheels.Count -ne 1) { throw "API 发布目录必须且只能包含一个 wheel，实际：$($wheels.Count)" }
}

function Copy-ApiRelease {
    param([Parameter(Mandatory = $true)][string]$Destination)
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    foreach ($name in @('Dockerfile', 'Dockerfile.offline-upgrade', '.dockerignore', 'pyproject.toml', 'constraints.txt', 'README.md', 'alembic.ini')) {
        Copy-Item -LiteralPath (Join-Path $script:serverRoot $name) -Destination (Join-Path $Destination $name)
    }
    Copy-FilteredTree (Join-Path $script:serverRoot 'app') (Join-Path $Destination 'app')
    Copy-FilteredTree (Join-Path $script:serverRoot 'alembic') (Join-Path $Destination 'alembic')
}

function Copy-DeploymentFiles {
    param([Parameter(Mandatory = $true)][string]$Destination)
    $deployRoot = Join-Path $projectRoot 'deploy\production-nginx'
    foreach ($name in @('compose.yml', 'env.production.example', 'README.md', 'SERVER-PREPARATION.md', 'DISASTER_RECOVERY.md')) {
        Copy-Item -LiteralPath (Join-Path $deployRoot $name) -Destination (Join-Path $Destination $name)
    }
    Copy-FilteredTree (Join-Path $deployRoot 'scripts') (Join-Path $Destination 'scripts') -ExcludedDirectories @() -ExcludedFiles @() -ExcludedExtensions @()
    Copy-FilteredTree (Join-Path $deployRoot 'nginx') (Join-Path $Destination 'nginx') -ExcludedDirectories @() -ExcludedFiles @() -ExcludedExtensions @()
    Copy-FilteredTree (Join-Path $deployRoot 'config') (Join-Path $Destination 'config') -ExcludedDirectories @() -ExcludedFiles @() -ExcludedExtensions @()
    $envPath = Join-Path $Destination 'env.production.example'
    $envText = Get-Content -LiteralPath $envPath -Raw -Encoding UTF8
    $imageTag = "$script:releaseVersion-$($script:commit.Substring(0, 7))-production"
    $envText = [regex]::Replace($envText, '(?m)^DDREC_API_IMAGE_TAG=.*$', "DDREC_API_IMAGE_TAG=$imageTag")
    $envText = [regex]::Replace($envText, '(?m)^LICENSE_SERVICE_VERSION=.*$', "LICENSE_SERVICE_VERSION=$script:releaseVersion")
    $envText = [regex]::Replace($envText, '(?m)^LICENSE_BUILD_COMMIT=.*$', "LICENSE_BUILD_COMMIT=$script:commit")
    [System.IO.File]::WriteAllText($envPath, $envText, $script:utf8NoBom)
}

function Copy-ProductionComponentFiles {
    param([Parameter(Mandatory = $true)][string]$Destination)
    $deployRoot = Join-Path $projectRoot 'deploy\production-nginx'
    if ($Service -eq 'api') {
        foreach ($name in @('compose.yml', 'env.production.example', 'README.md')) {
            Copy-Item -LiteralPath (Join-Path $deployRoot $name) -Destination (Join-Path $Destination $name)
        }
        New-Item -ItemType Directory -Path (Join-Path $Destination 'scripts') -Force | Out-Null
        foreach ($name in @('common.sh', 'migrate.sh', 'verify.sh')) {
            Copy-Item -LiteralPath (Join-Path $deployRoot "scripts\$name") -Destination (Join-Path $Destination "scripts\$name")
        }
        Copy-FilteredTree (Join-Path $deployRoot 'config') (Join-Path $Destination 'config') -ExcludedDirectories @() -ExcludedFiles @() -ExcludedExtensions @()
        $envPath = Join-Path $Destination 'env.production.example'
        $envText = Get-Content -LiteralPath $envPath -Raw -Encoding UTF8
        $imageTag = "$script:releaseVersion-$($script:commit.Substring(0, 7))-production"
        $envText = [regex]::Replace($envText, '(?m)^DDREC_API_IMAGE_TAG=.*$', "DDREC_API_IMAGE_TAG=$imageTag")
        $envText = [regex]::Replace($envText, '(?m)^LICENSE_SERVICE_VERSION=.*$', "LICENSE_SERVICE_VERSION=$script:releaseVersion")
        $envText = [regex]::Replace($envText, '(?m)^LICENSE_BUILD_COMMIT=.*$', "LICENSE_BUILD_COMMIT=$script:commit")
        [System.IO.File]::WriteAllText($envPath, $envText, $script:utf8NoBom)
    } elseif ($Service -eq 'admin') {
        Copy-FilteredTree (Join-Path $deployRoot 'nginx') (Join-Path $Destination 'nginx') -ExcludedDirectories @() -ExcludedFiles @() -ExcludedExtensions @()
        Write-Utf8File (Join-Path $Destination 'ADMIN-DEPLOY.txt') @(
            '将 admin 目录部署到 /var/www/ddrec-license/admin。',
            '部署前备份现有静态目录，部署后执行 nginx -t 并检查 /admin/。',
            '本组件包不会修改 API、PostgreSQL、数据库迁移或 current 软链接。'
        )
    } else {
        Copy-DeploymentFiles $Destination
    }
}

function Get-DatabaseMigrationHead {
    $versionsRoot = Join-Path $script:serverRoot 'alembic\versions'
    $files = @(Get-ChildItem -LiteralPath $versionsRoot -File -Filter '*.py' | Sort-Object Name)
    if ($files.Count -eq 0) { throw '未找到 Alembic 迁移文件。' }
    return $files[-1].BaseName
}

try {
    if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) { throw "缺少构建配置：$configPath" }
    $config = Import-PowerShellDataFile -LiteralPath $configPath
    $environmentConfig = $config.Environments[$Environment]
    if ($null -eq $environmentConfig) { throw "未配置环境：$Environment" }

    $git = Get-CommandPath 'git.exe'
    $basePython = Get-CommandPath 'python.exe'
    $npm = Get-CommandPath 'npm.cmd'
    $tar = Get-CommandPath 'tar.exe'

    $gitRoot = (& $git -C $projectRoot rev-parse --show-toplevel).Trim()
    if ($LASTEXITCODE -ne 0 -or [System.IO.Path]::GetFullPath($gitRoot) -ne $projectRoot) { throw "Git 根目录异常：$gitRoot" }
    $branch = (& $git -C $projectRoot branch --show-current).Trim()
    $commit = (& $git -C $projectRoot rev-parse HEAD).Trim()
    $dirtyLines = @(& $git -C $projectRoot status --porcelain --untracked-files=all)
    $isClean = $dirtyLines.Count -eq 0

    $serverRoot = Join-Path $projectRoot 'license-server'
    $adminRoot = Join-Path $projectRoot 'license-admin'
    foreach ($requiredPath in @(
        (Join-Path $serverRoot 'Dockerfile'),
        (Join-Path $serverRoot 'pyproject.toml'),
        (Join-Path $serverRoot 'alembic.ini'),
        (Join-Path $adminRoot 'package.json'),
        (Join-Path $adminRoot 'package-lock.json'),
        (Join-Path $projectRoot 'deploy\production-nginx\compose.yml')
    )) {
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) { throw "缺少云端构建文件：$requiredPath" }
    }

    $canonicalVersion = (Get-Content -LiteralPath (Join-Path $projectRoot $config.VersionFile) -Raw -Encoding UTF8).Trim()
    if ($canonicalVersion -notmatch '^\d+\.\d+\.\d+$') { throw "VERSION 格式非法：$canonicalVersion" }
    if ($PSBoundParameters.ContainsKey('Version') -and $Version -ne $canonicalVersion) {
        throw "-Version $Version 与统一版本文件 $canonicalVersion 不一致。"
    }
    $releaseVersion = $canonicalVersion
    Assert-VersionConsistency $releaseVersion

    if ($SkipTests -and $Environment -eq 'production') { throw '生产构建禁止使用 -SkipTests。' }
    if ($Environment -eq 'production') {
        Assert-ProductionGitState
        Assert-ProductionEnvironment $environmentConfig
        $trackedScopes = @(
            'deploy',
            'scripts/build_cloud_menu.ps1',
            'scripts/build_cloud_release.ps1',
            'scripts/cloud_build_artifacts.ps1',
            'scripts/cloud_release_config.psd1'
        )
        if ($Service -in @('api', 'all')) { $trackedScopes += 'license-server' }
        if ($Service -in @('admin', 'all')) { $trackedScopes += 'license-admin' }
        $trackedRelative = @(& $git -C $projectRoot ls-files -- @trackedScopes)
        $trackedFiles = @($trackedRelative | ForEach-Object { Join-Path $projectRoot $_ })
        Assert-NoSensitiveMaterial $trackedFiles 'Git 跟踪的云端发布输入'
    } elseif (-not $isClean) {
        Write-Warning "本地构建使用未提交工作区（$($dirtyLines.Count) 项变更）。"
    }

    $buildTarget = Get-CloudBuildTarget `
        -ProjectRoot $projectRoot `
        -Environment $Environment `
        -Service $Service `
        -Version $releaseVersion
    $existingBuild = Get-ExistingCloudBuildArtifacts -Target $buildTarget
    if ($existingBuild.HasExistingOutput -and -not $Clean) {
        throw "产物已存在；请确认后使用 -Clean 重建：$($buildTarget.OutputRoot)"
    }
    if ($Clean) {
        Remove-CloudBuildArtifactsSafely -Target $buildTarget
        Write-Host '旧构建产物已安全清除，将从当前源码重新完整构建。' -ForegroundColor Green
    }

    $artifactRoot = $buildTarget.ArtifactBase
    $script:pythonBuildPath = $null
    Initialize-PythonBuildEnvironment $basePython $artifactRoot
    $python = $script:pythonBuildPath
    $alembic = Join-Path (Split-Path -Parent $python) 'alembic.exe'
    if (-not (Test-Path -LiteralPath $alembic -PathType Leaf)) { throw "虚拟环境缺少 Alembic：$alembic" }

    Write-Host '========================================'
    Write-Host ' iVRec 云端授权系统构建'
    Write-Host '========================================'
    Write-Host "项目路径：$projectRoot"
    Write-Host "Git 分支：$branch"
    Write-Host "Git 提交：$commit"
    Write-Host "版本：$releaseVersion"
    Write-Host "环境：$Environment"
    Write-Host "服务：$Service"
    Write-Host "API：$($environmentConfig.ApiBaseUrl)"

    $outputRoot = $buildTarget.OutputRoot
    $scratchRoot = $buildTarget.ScratchRoot
    $releaseName = $buildTarget.ReleaseName
    $payloadRoot = Join-Path $scratchRoot $releaseName
    $archivePath = $buildTarget.ArchivePath
    $manifestPath = $buildTarget.ManifestPath
    $checksumsPath = $buildTarget.ChecksumsPath

    New-Item -ItemType Directory -Path $payloadRoot, $outputRoot -Force | Out-Null

    Assert-ProductionComposeTemplate
    if ($Service -in @('api', 'all')) { Invoke-ApiChecks }
    $adminDist = $null
    if ($Service -in @('admin', 'all')) {
        $script:builtAdminDist = $null
        Invoke-AdminBuild $environmentConfig
        $adminDist = $script:builtAdminDist
    }

    if ($Service -eq 'api') {
        $apiRoot = Join-Path $payloadRoot 'api'
        Copy-ApiRelease $apiRoot
        Add-ApiUpgradeWheel $apiRoot
    } elseif ($Service -eq 'admin') {
        Copy-FilteredTree $adminDist (Join-Path $payloadRoot 'admin') -ExcludedDirectories @() -ExcludedFiles @() -ExcludedExtensions @()
    } else {
        $apiRoot = Join-Path $payloadRoot 'api-source'
        Copy-ApiRelease $apiRoot
        Add-ApiUpgradeWheel $apiRoot
        Copy-FilteredTree $adminDist (Join-Path $payloadRoot 'admin') -ExcludedDirectories @() -ExcludedFiles @() -ExcludedExtensions @()
    }

    Copy-ProductionComponentFiles $payloadRoot

    $imageName = if ($Service -in @('api', 'all')) { 'SERVER_BUILD' } else { 'NOT_APPLICABLE' }
    $imageDigest = if ($Service -in @('api', 'all')) { 'SERVER_BUILD' } else { 'NOT_APPLICABLE' }

    Write-Utf8File (Join-Path $payloadRoot 'RELEASE-VERSION.txt') @($releaseVersion)
    Write-Utf8File (Join-Path $payloadRoot 'RELEASE-GIT-COMMIT.txt') @($commit)
    $migrationHead = Get-DatabaseMigrationHead
    $internalManifest = @(
        "Project: $($config.ProjectName)",
        "Release version: $releaseVersion",
        "Environment: $Environment",
        "Service: $Service",
        "Git branch: $branch",
        "Git commit: $commit",
        "Git worktree clean: $isClean",
        "Build time UTC: $([DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ'))",
        "API base URL: $($environmentConfig.ApiBaseUrl)",
        "Admin environment label: $($environmentConfig.AdminLabel)",
        "Docker image: $imageName",
        "Docker image digest: $imageDigest",
        "Database migration head: $migrationHead",
        "Archive: $releaseName.tar.gz",
        'Archive SHA-256: see the adjacent SHA256SUMS.txt file'
    )
    Write-Utf8File (Join-Path $payloadRoot 'RELEASE-MANIFEST.txt') $internalManifest

    $payloadFiles = @(Get-ChildItem -LiteralPath $payloadRoot -Recurse -File)
    Assert-NoSensitiveMaterial ($payloadFiles | Select-Object -ExpandProperty FullName) '最终发布目录'
    $allowedUpdatePublicKey = [System.IO.Path]::GetFullPath((Join-Path $payloadRoot 'config\update_ed25519_public.pem'))
    $blocked = @($payloadFiles | Where-Object {
        $extension = $_.Extension.ToLowerInvariant()
        $isBlockedExtension = $extension -in @('.db', '.sqlite', '.sqlite3', '.dump', '.backup', '.key') -or
            ($extension -eq '.pem' -and -not $_.FullName.Equals($allowedUpdatePublicKey, [StringComparison]::OrdinalIgnoreCase))
        $_.Name -in @('.env', '.env.production') -or
        $_.FullName -match '(?i)[\\/](?:node_modules|\.venv|venv|__pycache__|\.git|\.secrets)[\\/]' -or
        $isBlockedExtension
    })
    if ($blocked.Count -gt 0) {
        $blocked | ForEach-Object { Write-Host "禁止打包：$($_.FullName)" -ForegroundColor Red }
        throw '最终发布目录包含禁止文件。'
    }

    $payloadChecksumsPath = Join-Path $payloadRoot 'SHA256SUMS.txt'
    $payloadChecksumLines = Get-ChildItem -LiteralPath $payloadRoot -Recurse -File | Where-Object {
        $_.FullName -ne $payloadChecksumsPath
    } | Sort-Object FullName | ForEach-Object {
        $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        "$hash  $(Get-RelativeUnixPath $payloadRoot $_.FullName)"
    }
    Write-Utf8File $payloadChecksumsPath $payloadChecksumLines -UnixNewlines

    Push-Location $scratchRoot
    try { Invoke-Checked $tar @('-czf', $archivePath, $releaseName) '创建发布压缩包失败' } finally { Pop-Location }
    $archiveItem = Get-Item -LiteralPath $archivePath
    $archiveHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $manifest = $internalManifest[0..($internalManifest.Count - 3)] + @(
        "Archive: $($archiveItem.Name)",
        "Archive size bytes: $($archiveItem.Length)",
        "Archive SHA-256: $archiveHash"
    )
    Write-Utf8File $manifestPath $manifest
    Write-Utf8File $checksumsPath @("$archiveHash  $($archiveItem.Name)") -UnixNewlines

    Remove-Item -LiteralPath $scratchRoot -Recurse -Force
    Write-Host ''
    Write-Host '构建成功' -ForegroundColor Green
    Write-Host "环境：$Environment"
    Write-Host "服务：$Service"
    Write-Host "版本：$releaseVersion"
    Write-Host "产物：$archivePath"
    Write-Host "大小：$($archiveItem.Length) bytes"
    Write-Host "SHA-256：$archiveHash"
    Write-Host "清单：$manifestPath"
} catch {
    if (Get-Variable -Name scratchRoot -ErrorAction SilentlyContinue) {
        if ((Test-Path -LiteralPath $scratchRoot) -and (Get-Variable -Name artifactRoot -ErrorAction SilentlyContinue)) {
            Assert-ChildPath $artifactRoot $scratchRoot
            Remove-Item -LiteralPath $scratchRoot -Recurse -Force
        }
    }
    Write-Host ''
    Write-Host '构建失败' -ForegroundColor Red
    Write-Host "环境：$Environment"
    Write-Host "服务：$Service"
    Write-Host "错误：$($_.Exception.Message)" -ForegroundColor Red
    throw
}
