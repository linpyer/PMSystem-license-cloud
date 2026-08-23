$helperPath = Join-Path $PSScriptRoot '..\..\scripts\cloud_build_artifacts.ps1'
. $helperPath

function Assert-CloudTestThrows {
    param([Parameter(Mandatory = $true)][scriptblock]$Script)

    $threw = $false
    try { & $Script | Out-Null } catch { $threw = $true }
    $threw | Should Be $true
}

function New-CloudTestOutput {
    param(
        [Parameter(Mandatory = $true)]$Target,
        [string]$Generation = 'old'
    )

    New-Item -ItemType Directory -Path $Target.OutputRoot -Force | Out-Null
    [System.IO.File]::WriteAllText($Target.ArchivePath, "archive-$Generation")
    [System.IO.File]::WriteAllText($Target.ManifestPath, "Generation=$Generation")
    [System.IO.File]::WriteAllText($Target.ChecksumsPath, "sha-$Generation  $([System.IO.Path]::GetFileName($Target.ArchivePath))")
    [System.IO.File]::WriteAllText((Join-Path $Target.OutputRoot 'BUILD-METADATA.json'), "{`"generation`":`"$Generation`"}")
}

Describe 'Cloud one-click build artifact interaction' {
    BeforeEach {
        $script:testRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('ddrec-cloud-build-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $script:testRoot -Force | Out-Null
        $script:silentWriter = { param($Message, $Color) }
    }

    AfterEach {
        if (Test-Path -LiteralPath $script:testRoot) {
            Remove-Item -LiteralPath $script:testRoot -Recurse -Force
        }
    }

    foreach ($service in @('api', 'admin', 'all')) {
        It "$service without old output builds directly without Clean" {
            $target = Get-CloudBuildTarget -ProjectRoot $script:testRoot -Environment production -Service $service -Version 1.3.0
            $decision = Get-CloudBuildDecision -Target $target -InputReader { throw '不应询问' } -OutputWriter $script:silentWriter
            $decision.ShouldBuild | Should Be $true
            $decision.UseClean | Should Be $false
        }

        It "$service with old output uses Clean and can rebuild after Y" {
            $target = Get-CloudBuildTarget -ProjectRoot $script:testRoot -Environment production -Service $service -Version 1.3.0
            New-CloudTestOutput -Target $target -Generation old
            $decision = Get-CloudBuildDecision -Target $target -InputReader { 'Y' } -OutputWriter $script:silentWriter
            $decision.ShouldBuild | Should Be $true
            $decision.UseClean | Should Be $true

            Remove-CloudBuildArtifactsSafely -Target $target
            (Get-ExistingCloudBuildArtifacts -Target $target).HasExistingOutput | Should Be $false
            New-CloudTestOutput -Target $target -Generation new
            (Get-Content -LiteralPath $target.ManifestPath -Raw) | Should Be 'Generation=new'
            (Get-Content -LiteralPath $target.ChecksumsPath -Raw).StartsWith('sha-new') | Should Be $true
        }

        It "$service with old output cancels and preserves files after N" {
            $target = Get-CloudBuildTarget -ProjectRoot $script:testRoot -Environment production -Service $service -Version 1.3.0
            New-CloudTestOutput -Target $target
            $decision = Get-CloudBuildDecision -Target $target -InputReader { 'N' } -OutputWriter $script:silentWriter
            $decision.ShouldBuild | Should Be $false
            $decision.UseClean | Should Be $false
            (Test-Path -LiteralPath $target.ArchivePath -PathType Leaf) | Should Be $true
        }
    }

    It 'Enter defaults to cancellation' {
        $target = Get-CloudBuildTarget -ProjectRoot $script:testRoot -Environment production -Service all -Version 1.3.0
        New-CloudTestOutput -Target $target
        $decision = Get-CloudBuildDecision -Target $target -InputReader { '' } -OutputWriter $script:silentWriter
        $decision.ShouldBuild | Should Be $false
        (Test-Path -LiteralPath $target.ArchivePath) | Should Be $true
    }

    It 'invalid answers are rejected until Y or N is entered' {
        $target = Get-CloudBuildTarget -ProjectRoot $script:testRoot -Environment production -Service api -Version 1.3.0
        New-CloudTestOutput -Target $target
        $script:answers = @('maybe', 'Y')
        $script:index = 0
        $script:messages = @()
        $reader = { $answer = $script:answers[$script:index]; $script:index++; return $answer }
        $writer = { param($Message, $Color) $script:messages += [string]$Message }
        $decision = Get-CloudBuildDecision -Target $target -InputReader $reader -OutputWriter $writer
        $decision.UseClean | Should Be $true
        $script:index | Should Be 2
        (($script:messages -join "`n") -match '输入无效') | Should Be $true
    }

    It 'a Clean failure stops before rebuild and reports the failed target' {
        $target = Get-CloudBuildTarget -ProjectRoot $script:testRoot -Environment production -Service admin -Version 1.3.0
        New-CloudTestOutput -Target $target
        $buildStarted = $false
        $message = ''
        try {
            Remove-CloudBuildArtifactsSafely -Target $target -RemovePathAction { param($Path) throw 'fixture access denied' }
            $buildStarted = $true
        }
        catch { $message = $_.Exception.Message }
        $buildStarted | Should Be $false
        ($message -match [regex]::Escape($target.OutputRoot)) | Should Be $true
        ($message -match '本次打包已停止') | Should Be $true
        (Test-Path -LiteralPath $target.ArchivePath) | Should Be $true
    }

    It 'cleaning API does not remove Admin All or history archives' {
        $api = Get-CloudBuildTarget -ProjectRoot $script:testRoot -Environment production -Service api -Version 1.3.0
        $admin = Get-CloudBuildTarget -ProjectRoot $script:testRoot -Environment production -Service admin -Version 1.3.0
        $all = Get-CloudBuildTarget -ProjectRoot $script:testRoot -Environment production -Service all -Version 1.3.0
        New-CloudTestOutput $api
        New-CloudTestOutput $admin
        New-CloudTestOutput $all
        $history = Join-Path $api.ArtifactBase 'production-release\archive\kept.tar.gz'
        New-Item -ItemType Directory -Path (Split-Path -Parent $history) -Force | Out-Null
        [System.IO.File]::WriteAllText($history, 'history')

        Remove-CloudBuildArtifactsSafely -Target $api
        (Test-Path -LiteralPath $api.OutputRoot) | Should Be $false
        (Test-Path -LiteralPath $admin.ArchivePath) | Should Be $true
        (Test-Path -LiteralPath $all.ArchivePath) | Should Be $true
        (Test-Path -LiteralPath $history) | Should Be $true
    }

    It 'cleaning All removes its tar SHA manifest metadata and staging only' {
        $target = Get-CloudBuildTarget -ProjectRoot $script:testRoot -Environment production -Service all -Version 1.3.0
        New-CloudTestOutput $target
        New-Item -ItemType Directory -Path $target.ScratchRoot -Force | Out-Null
        [System.IO.File]::WriteAllText((Join-Path $target.ScratchRoot 'staging.tmp'), 'old')
        Remove-CloudBuildArtifactsSafely -Target $target
        (Test-Path -LiteralPath $target.OutputRoot) | Should Be $false
        (Test-Path -LiteralPath $target.ScratchRoot) | Should Be $false
    }

    It 'rejects a tampered path outside the exact service target' {
        $target = Get-CloudBuildTarget -ProjectRoot $script:testRoot -Environment production -Service api -Version 1.3.0
        $target.OutputRoot = $target.ArtifactBase
        Assert-CloudTestThrows { Remove-CloudBuildArtifactsSafely -Target $target }
    }
}

Describe 'Cloud builder integration invariants' {
    It 'keeps bottom-level Clean and invokes it before creating new output' {
        $build = Get-Content -LiteralPath (Join-Path $PSScriptRoot '..\..\scripts\build_cloud_release.ps1') -Raw -Encoding UTF8
        ($build -match '\[switch\]\$Clean') | Should Be $true
        $cleanIndex = $build.IndexOf('Remove-CloudBuildArtifactsSafely -Target $buildTarget')
        $createIndex = $build.IndexOf('New-Item -ItemType Directory -Path $payloadRoot, $outputRoot')
        ($cleanIndex -ge 0) | Should Be $true
        ($createIndex -gt $cleanIndex) | Should Be $true
    }

    It 'cancels normally without printing build success' {
        $menu = Get-Content -LiteralPath (Join-Path $PSScriptRoot '..\..\scripts\build_cloud_menu.ps1') -Raw -Encoding UTF8
        $cancelIndex = $menu.IndexOf("if (-not `$decision.ShouldBuild)")
        $normalExitIndex = $menu.IndexOf('exit 0', $cancelIndex)
        $successIndex = $menu.IndexOf("Write-Host '构建成功'", $cancelIndex)
        ($cancelIndex -ge 0) | Should Be $true
        ($normalExitIndex -gt $cancelIndex) | Should Be $true
        ($successIndex -gt $normalExitIndex) | Should Be $true
    }

    It 'does not require local Docker and keeps production-only licensing' {
        $build = Get-Content -LiteralPath (Join-Path $PSScriptRoot '..\..\scripts\build_cloud_release.ps1') -Raw -Encoding UTF8
        $menu = Get-Content -LiteralPath (Join-Path $PSScriptRoot '..\..\scripts\build_cloud_menu.ps1') -Raw -Encoding UTF8
        ($build -match "Get-CommandPath 'docker(?:\.exe)?'") | Should Be $false
        ($build -match "\[ValidateSet\('production'\)\]") | Should Be $true
        ($menu -match 'license-local|本地环境') | Should Be $false
    }
}
