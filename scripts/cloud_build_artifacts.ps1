Set-StrictMode -Version 2.0

function Get-CloudBuildTarget {
    param(
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [Parameter(Mandatory = $true)][ValidateSet('production')][string]$Environment,
        [Parameter(Mandatory = $true)][ValidateSet('api', 'admin', 'all')][string]$Service,
        [Parameter(Mandatory = $true)][ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version
    )

    $root = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\', '/')
    $artifactBase = [System.IO.Path]::GetFullPath((Join-Path $root 'artifacts\cloud')).TrimEnd('\', '/')
    $outputRoot = [System.IO.Path]::GetFullPath((Join-Path $artifactBase "$Environment\$Service")).TrimEnd('\', '/')
    $scratchRoot = [System.IO.Path]::GetFullPath((Join-Path $artifactBase ".build-$Environment-$Service")).TrimEnd('\', '/')
    $releaseName = "iVRec-License-Cloud-$Version-$Environment-$Service"

    return [pscustomobject]@{
        PSTypeName = 'DDREC.CloudBuildTarget'
        ProjectRoot = $root
        ArtifactBase = $artifactBase
        Environment = $Environment
        Service = $Service
        Version = $Version
        OutputRoot = $outputRoot
        ScratchRoot = $scratchRoot
        ReleaseName = $releaseName
        ArchivePath = Join-Path $outputRoot "$releaseName.tar.gz"
        ManifestPath = Join-Path $outputRoot 'RELEASE-MANIFEST.txt'
        ChecksumsPath = Join-Path $outputRoot 'SHA256SUMS.txt'
    }
}

function Assert-CloudBuildTargetPath {
    param([Parameter(Mandatory = $true)]$Target)

    $expected = Get-CloudBuildTarget `
        -ProjectRoot ([string]$Target.ProjectRoot) `
        -Environment ([string]$Target.Environment) `
        -Service ([string]$Target.Service) `
        -Version ([string]$Target.Version)

    foreach ($property in @(
        'ProjectRoot', 'ArtifactBase', 'OutputRoot', 'ScratchRoot',
        'ArchivePath', 'ManifestPath', 'ChecksumsPath'
    )) {
        $actualPath = [System.IO.Path]::GetFullPath([string]$Target.$property).TrimEnd('\', '/')
        $expectedPath = [System.IO.Path]::GetFullPath([string]$expected.$property).TrimEnd('\', '/')
        if (-not $actualPath.Equals($expectedPath, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "拒绝清理未精确匹配当前 environment + service 的路径：$actualPath"
        }
    }

    $artifactPrefix = $expected.ArtifactBase + [System.IO.Path]::DirectorySeparatorChar
    foreach ($candidate in @($expected.OutputRoot, $expected.ScratchRoot)) {
        if (-not $candidate.StartsWith($artifactPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "拒绝清理云端构建产物目录以外的路径：$candidate"
        }
    }

    $protectedPaths = @(
        $expected.ProjectRoot,
        $expected.ArtifactBase,
        (Join-Path $expected.ArtifactBase $expected.Environment)
    )
    foreach ($candidate in @($expected.OutputRoot, $expected.ScratchRoot)) {
        foreach ($protected in $protectedPaths) {
            $protectedPath = [System.IO.Path]::GetFullPath($protected).TrimEnd('\', '/')
            if ($candidate.Equals($protectedPath, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "拒绝清理受保护目录：$candidate"
            }
        }
    }
}

function Get-ExistingCloudBuildArtifacts {
    param([Parameter(Mandatory = $true)]$Target)

    Assert-CloudBuildTargetPath -Target $Target
    $entries = @()
    $files = @()
    foreach ($path in @($Target.OutputRoot, $Target.ScratchRoot)) {
        if (-not (Test-Path -LiteralPath $path)) { continue }
        $entries += @(Get-Item -LiteralPath $path -Force)
        if (Test-Path -LiteralPath $path -PathType Container) {
            $children = @(Get-ChildItem -LiteralPath $path -Force -Recurse)
            $entries += $children
            $files += @($children | Where-Object { -not $_.PSIsContainer })
        }
        else {
            $files += @(Get-Item -LiteralPath $path -Force)
        }
    }

    return [pscustomobject]@{
        PSTypeName = 'DDREC.ExistingCloudBuildArtifacts'
        Target = $Target
        HasExistingOutput = ($entries.Count -gt 0)
        Entries = @($entries)
        Files = @($files)
    }
}

function Confirm-CleanExistingCloudBuild {
    param(
        [Parameter(Mandatory = $true)]$ExistingBuild,
        [scriptblock]$InputReader,
        [scriptblock]$OutputWriter
    )

    if (-not $ExistingBuild.HasExistingOutput) { return $true }
    if ($null -eq $InputReader) {
        $InputReader = { param($Prompt) Read-Host $Prompt }
    }
    if ($null -eq $OutputWriter) {
        $OutputWriter = {
            param($Message, $Color)
            if ([string]::IsNullOrWhiteSpace([string]$Color)) { Write-Host $Message }
            else { Write-Host $Message -ForegroundColor $Color }
        }
    }

    $target = $ExistingBuild.Target
    & $OutputWriter '' ''
    & $OutputWriter '========================================' 'Yellow'
    & $OutputWriter '检测到已有云端构建产物' 'Yellow'
    & $OutputWriter '========================================' 'Yellow'
    & $OutputWriter '' ''
    & $OutputWriter "环境：$($target.Environment)" 'Cyan'
    & $OutputWriter "服务：$($target.Service)" 'Cyan'
    & $OutputWriter '' ''
    & $OutputWriter '已有文件：' ''
    & $OutputWriter $target.OutputRoot ''

    if ($ExistingBuild.Files.Count -eq 0) {
        & $OutputWriter '[X] 检测到旧产物目录或临时 staging。' 'Yellow'
    }
    else {
        foreach ($file in $ExistingBuild.Files) {
            & $OutputWriter $file.FullName 'Yellow'
            & $OutputWriter "大小：$($file.Length) bytes" ''
            & $OutputWriter "修改时间：$($file.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'))" ''
            & $OutputWriter '' ''
        }
    }

    & $OutputWriter '是否清除本次已有构建产物并重新完整打包？' ''
    & $OutputWriter '' ''
    & $OutputWriter '[Y] 清除并重新打包' ''
    & $OutputWriter '[N] 取消（默认）' ''

    while ($true) {
        $answer = [string](& $InputReader '是否继续？[Y/N]')
        if ([string]::IsNullOrWhiteSpace($answer)) { return $false }
        switch ($answer.Trim().ToUpperInvariant()) {
            'Y' { return $true }
            'N' { return $false }
            default { & $OutputWriter '输入无效，请输入 Y 或 N；直接按 Enter 将取消。' 'Yellow' }
        }
    }
}

function Get-CloudBuildDecision {
    param(
        [Parameter(Mandatory = $true)]$Target,
        [scriptblock]$InputReader,
        [scriptblock]$OutputWriter
    )

    $existingBuild = Get-ExistingCloudBuildArtifacts -Target $Target
    $confirmed = Confirm-CleanExistingCloudBuild `
        -ExistingBuild $existingBuild `
        -InputReader $InputReader `
        -OutputWriter $OutputWriter

    return [pscustomobject]@{
        PSTypeName = 'DDREC.CloudBuildDecision'
        Target = $Target
        ExistingBuild = $existingBuild
        ShouldBuild = [bool]$confirmed
        UseClean = ([bool]$confirmed -and $existingBuild.HasExistingOutput)
    }
}

function Remove-CloudBuildArtifactsSafely {
    param(
        [Parameter(Mandatory = $true)]$Target,
        [scriptblock]$RemovePathAction
    )

    Assert-CloudBuildTargetPath -Target $Target
    if ($null -eq $RemovePathAction) {
        $RemovePathAction = {
            param($Path)
            Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
        }
    }

    $paths = @($Target.OutputRoot, $Target.ScratchRoot)
    foreach ($path in $paths) {
        if (-not (Test-Path -LiteralPath $path)) { continue }
        try {
            & $RemovePathAction $path
        }
        catch {
            $remainingFiles = @()
            if (Test-Path -LiteralPath $path -PathType Container) {
                $remainingFiles = @(Get-ChildItem -LiteralPath $path -Force -Recurse -ErrorAction SilentlyContinue |
                    Where-Object { -not $_.PSIsContainer } | Select-Object -ExpandProperty FullName)
            }
            $blocked = if ($remainingFiles.Count -gt 0) { $remainingFiles[0] } else { $path }
            throw "无法清除旧构建产物：`n`n$blocked`n`n$($_.Exception.Message)`n`n本次打包已停止。"
        }
        if (Test-Path -LiteralPath $path) {
            throw "无法清除旧构建产物：`n`n$path`n`n清理后目标仍然存在。`n`n本次打包已停止。"
        }
    }

    $remaining = Get-ExistingCloudBuildArtifacts -Target $Target
    if ($remaining.HasExistingOutput) {
        $blocked = if ($remaining.Files.Count -gt 0) { $remaining.Files[0].FullName } else { $Target.OutputRoot }
        throw "清理验证失败，目标仍然存在：`n`n$blocked`n`n本次打包已停止。"
    }
}
