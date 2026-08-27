$modulePath = Join-Path $PSScriptRoot '..\..\scripts\release\DDREC.Release.psm1'
Import-Module $modulePath -Force

function New-CloudPackageFixture {
    param(
        [Parameter(Mandatory)][string]$CloudRoot,
        [string]$Commit = ('a' * 40),
        [string]$Environment = 'production',
        [string]$Service = 'all',
        [string]$Version = '1.3.0',
        [switch]$MissingManifest,
        [switch]$TamperArchive
    )
    $root = Join-Path $CloudRoot 'artifacts\cloud\production\all'
    New-Item -ItemType Directory -Path $root -Force | Out-Null
    $name = "iVRec-License-Cloud-$Version-production-all.tar.gz"
    $archive = Join-Path $root $name
    [IO.File]::WriteAllText($archive, 'cloud-package-fixture', [Text.Encoding]::ASCII)
    $item = Get-Item -LiteralPath $archive
    $hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    if (-not $MissingManifest) {
        $manifest = @(
            'Project: iVRec License Cloud'
            "Release version: $Version"
            "Environment: $Environment"
            "Service: $Service"
            'Git branch: v1.3'
            "Git commit: $Commit"
            'Git worktree clean: True'
            'Build time UTC: 2026-08-23T00:00:00Z'
            "Archive: $name"
            "Archive size bytes: $($item.Length)"
            "Archive SHA-256: $hash"
        )
        [IO.File]::WriteAllLines((Join-Path $root 'RELEASE-MANIFEST.txt'), $manifest, [Text.UTF8Encoding]::new($false))
    }
    [IO.File]::WriteAllText((Join-Path $root 'SHA256SUMS.txt'), "$hash  $name`n", [Text.Encoding]::ASCII)
    if ($TamperArchive) { [IO.File]::AppendAllText($archive, '-tampered', [Text.Encoding]::ASCII) }
    return $archive
}

function New-CloudStateFixture {
    param([bool]$Existing=$true,[bool]$Valid=$true,[string]$Error='fixture invalid')
    [pscustomobject]@{
        HasExistingOutput=$Existing
        IsValid=$Valid
        Metadata=if($Valid){[pscustomobject]@{FileName='fixture.tar.gz'}}else{$null}
        ValidationError=if($Valid){$null}else{$Error}
    }
}

function Get-ExceptionMessage {
    param([Parameter(Mandatory)][scriptblock]$Script)
    try { & $Script | Out-Null; return '<no error>' } catch { return $_.Exception.Message }
}

Describe 'DDREC CloudPackageMetadata authenticity' {
    BeforeEach {
        $script:cloudRoot = Join-Path ([IO.Path]::GetTempPath()) ('ddrec-cloud-package-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $script:cloudRoot -Force | Out-Null
    }
    AfterEach {
        if (Test-Path -LiteralPath $script:cloudRoot) { Remove-Item -LiteralPath $script:cloudRoot -Recurse -Force }
    }

    It 'parses a valid production all package into the unified model' {
        New-CloudPackageFixture -CloudRoot $script:cloudRoot | Out-Null
        $metadata = Get-DDRECCloudPackageMetadata -CloudRoot $script:cloudRoot -ExpectedCommit ('a'*40) -ExpectedVersion 1.3.0 -ExpectedBranch v1.3
        ($metadata.PSObject.TypeNames -contains 'DDREC.CloudPackageMetadata') | Should Be $true
        ($metadata.PSObject.Properties.Name -join ',') | Should Match 'Path.*FileName.*FileSize.*SHA256.*Version.*GitCommit.*Environment.*Service.*ManifestPath.*ChecksumsPath.*BuildTime'
        $metadata.Environment | Should Be 'production'
        $metadata.Service | Should Be 'all'
        $metadata.SHA256.Length | Should Be 64
    }

    It 'rejects a stale GitCommit with an explicit old package error' {
        New-CloudPackageFixture -CloudRoot $script:cloudRoot -Commit ('b'*40) | Out-Null
        $message = Get-ExceptionMessage { Get-DDRECCloudPackageMetadata -CloudRoot $script:cloudRoot -ExpectedCommit ('a'*40) -ExpectedVersion 1.3.0 -ExpectedBranch v1.3 }
        $message | Should Match '当前 Cloud 构建产物已过期'
        $message | Should Match 'Package GitCommit'
        $message | Should Match 'Current Git HEAD'
    }

    It 'rejects a tampered archive SHA and size' {
        New-CloudPackageFixture -CloudRoot $script:cloudRoot -TamperArchive | Out-Null
        (Get-ExceptionMessage { Get-DDRECCloudPackageMetadata -CloudRoot $script:cloudRoot -ExpectedCommit ('a'*40) -ExpectedVersion 1.3.0 -ExpectedBranch v1.3 }) | Should Match '实际大小|实际 SHA256'
    }

    It 'rejects a missing Manifest' {
        New-CloudPackageFixture -CloudRoot $script:cloudRoot -MissingManifest | Out-Null
        (Get-ExceptionMessage { Get-DDRECCloudPackageMetadata -CloudRoot $script:cloudRoot -ExpectedCommit ('a'*40) -ExpectedVersion 1.3.0 -ExpectedBranch v1.3 }) | Should Match 'Manifest 不存在'
    }

    It 'rejects a non-production Environment' {
        New-CloudPackageFixture -CloudRoot $script:cloudRoot -Environment staging | Out-Null
        (Get-ExceptionMessage { Get-DDRECCloudPackageMetadata -CloudRoot $script:cloudRoot -ExpectedCommit ('a'*40) -ExpectedVersion 1.3.0 -ExpectedBranch v1.3 }) | Should Match 'Environment 错误'
    }

    It 'rejects a Service other than all' {
        New-CloudPackageFixture -CloudRoot $script:cloudRoot -Service api | Out-Null
        (Get-ExceptionMessage { Get-DDRECCloudPackageMetadata -CloudRoot $script:cloudRoot -ExpectedCommit ('a'*40) -ExpectedVersion 1.3.0 -ExpectedBranch v1.3 }) | Should Match 'Service 错误'
    }

    It 'reports no package when formal output and staging are absent' {
        $state = Get-DDRECCloudPackageState -CloudRoot $script:cloudRoot -ExpectedCommit ('a'*40) -ExpectedVersion 1.3.0 -ExpectedBranch v1.3
        $state.HasExistingOutput | Should Be $false
        (Get-DDRECCloudPackageDecision -State $state).Action | Should Be 'Build'
    }
}

Describe 'DDREC Cloud package release decisions' {
    BeforeEach { $script:silent = { param($Message,$Color) } }

    It 'uses a valid existing package after Y without rebuilding' {
        (Get-DDRECCloudPackageDecision -State (New-CloudStateFixture) -InputReader {'Y'} -OutputWriter $script:silent).Action | Should Be 'Use'
    }

    It 'selects the existing safe Clean rebuild only after R' {
        (Get-DDRECCloudPackageDecision -State (New-CloudStateFixture) -InputReader {'R'} -OutputWriter $script:silent).Action | Should Be 'Rebuild'
    }

    It 'cancels after N' {
        (Get-DDRECCloudPackageDecision -State (New-CloudStateFixture) -InputReader {'N'} -OutputWriter $script:silent).Action | Should Be 'Cancel'
    }

    It 'defaults Enter to cancellation' {
        (Get-DDRECCloudPackageDecision -State (New-CloudStateFixture) -InputReader {''} -OutputWriter $script:silent).Action | Should Be 'Cancel'
    }

    It 'does not offer Y for an invalid package' {
        $script:answers=@('Y','N');$script:index=0;$script:messages=@()
        $reader={ $answer=$script:answers[$script:index];$script:index++;$answer }
        $writer={ param($Message,$Color) $script:messages += [string]$Message }
        $decision=Get-DDRECCloudPackageDecision -State (New-CloudStateFixture -Valid $false) -InputReader $reader -OutputWriter $writer
        $decision.Action | Should Be 'Cancel'
        $script:index | Should Be 2
        ($script:messages -join "`n") | Should Match '允许的选择：R/N'
    }

    It 'uses a valid package read-only during Dry Run without prompting' {
        $decision=Get-DDRECCloudPackageDecision -State (New-CloudStateFixture) -DryRun -InputReader {throw 'Dry Run 不应询问'} -OutputWriter $script:silent
        $decision.Action | Should Be 'Use'
    }

    It 'does not Clean or accept an invalid package during Dry Run' {
        (Get-ExceptionMessage { Get-DDRECCloudPackageDecision -State (New-CloudStateFixture -Valid $false -Error 'SHA invalid') -DryRun -OutputWriter $script:silent }) | Should Be 'SHA invalid'
    }

    It 'keeps ProductionModified false while only selecting a package' {
        $context=New-DDRECReleaseContext -WorkspaceRoot $TestDrive -Config ([pscustomobject]@{}) -SessionId cloud-selection
        (Get-DDRECCloudPackageDecision -State (New-CloudStateFixture) -DryRun -OutputWriter $script:silent).Action | Should Be 'Use'
        $context.ProductionModified | Should Be $false
    }
}

Describe 'DDREC Cloud package orchestration invariants' {
    BeforeAll {
        $script:releaseScript=Join-Path $PSScriptRoot '..\..\scripts\release\release-all.ps1'
        $script:moduleScript=Join-Path $PSScriptRoot '..\..\scripts\release\DDREC.Release.psm1'
        $script:builderScript=Join-Path $PSScriptRoot '..\..\scripts\build_cloud_release.ps1'
    }

    It 'routes Cloud CloudStandard and CloudBoth through one common package flow' {
        foreach($mode in @('Cloud','CloudStandard','CloudBoth')){ (Get-DDRECModePlan -Mode $mode).Cloud | Should Be $true }
        $text=Get-Content -LiteralPath $script:releaseScript -Raw
        ([regex]::Matches($text,'Get-DDRECCloudPackageState')).Count | Should Be 1
    }

    It 'passes Clean only for the explicit Rebuild action' {
        (Get-Content -LiteralPath $script:releaseScript -Raw) | Should Match '-Clean:\(\$decision\.Action -eq ''Rebuild''\)'
    }

    It 'validates and displays Cloud metadata before the Dry Run result' {
        $text=Get-Content -LiteralPath $script:releaseScript -Raw
        $metadataIndex=$text.IndexOf('Get-DDRECCloudPackageState')
        $dryRunIndex=$text.IndexOf('if($dryRun){', $metadataIndex)
        ($metadataIndex -ge 0 -and $dryRunIndex -gt $metadataIndex) | Should Be $true
    }

    It 'keeps the bottom-level no-Clean overwrite refusal' {
        $text=Get-Content -LiteralPath $script:builderScript -Raw
        $text | Should Match 'HasExistingOutput -and -not \$Clean'
        $text | Should Match '产物已存在；请确认后使用 -Clean 重建'
    }

    It 'keeps local Docker out of package preparation' {
        $module=Get-Content -LiteralPath $script:moduleScript -Raw
        $builder=Get-Content -LiteralPath $script:builderScript -Raw
        $module | Should Not Match 'Invoke-DDRECNative docker'
        $builder | Should Not Match "Get-CommandPath 'docker"
    }
}
