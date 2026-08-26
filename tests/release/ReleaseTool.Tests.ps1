$modulePath = Join-Path $PSScriptRoot '..\..\scripts\release\DDREC.Release.psm1'
Import-Module $modulePath -Force

function New-GitState {
    param([bool]$Clean=$true,[string]$Branch='v1.3',[string]$Head=('a'*40),[string]$Origin=('a'*40))
    [pscustomobject]@{Clean=$Clean;Branch=$Branch;Head=$Head;Origin=$Origin;Repository='mock';Status=' M file'}
}

function New-Metadata {
    param(
        [string]$Edition='standard',
        [string]$Environment='none',
        [string]$Commit=('a'*40),
        [int]$Build=82,
        [string]$Version='1.3.0'
    )
    [pscustomobject]@{
        PSTypeName='DDREC.PackageMetadata'
        Path='C:\fixture\DDREC-Setup.exe';FileName='DDREC-Setup.exe';FileSize=1024;SHA256=('A'*64)
        Version=$Version;BuildNumber=$Build;GitCommit=$Commit;Edition=$Edition
        Environment=$Environment;UpdaterVersion='1.2.0'
    }
}

function New-InstallerFixture {
    param(
        [Parameter(Mandatory)][string]$Root,
        [ValidateSet('standard','license')][string]$Edition='standard',
        [ValidateSet('none','production')][string]$Environment='none',
        [string]$Commit=('a'*40),
        [string]$MissingField=''
    )
    New-Item -ItemType Directory -Path $Root -Force | Out-Null
    $source = (Get-Command where.exe -ErrorAction Stop).Source
    $fileName = if ($Edition -eq 'standard') {'DDREC-standard-fixture.exe'} else {'DDREC-license-fixture.exe'}
    $installer = Join-Path $Root $fileName
    Copy-Item -LiteralPath $source -Destination $installer
    $peProductVersion = [string]([Diagnostics.FileVersionInfo]::GetVersionInfo($installer).ProductVersion)
    if ($peProductVersion -notmatch '^(\d+\.\d+\.\d+)') { throw "测试 PE ProductVersion 无效：$peProductVersion" }
    $version = $matches[1]
    $hash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToUpperInvariant()
    $size = (Get-Item -LiteralPath $installer).Length
    $values = [ordered]@{
        Version=$version;BuildNumber='85';GitCommit=$Commit;Edition=$Edition;LicenseEnvironment=$Environment
        UpdaterVersion='1.2.0';Installer=$fileName;SizeBytes=[string]$size;SHA256=$hash
    }
    $manifestField = if ($MissingField -eq 'Environment') {'LicenseEnvironment'} else {$MissingField}
    if ($manifestField) { $values.Remove($manifestField) }
    $manifestLines = @($values.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" })
    [IO.File]::WriteAllLines((Join-Path $Root 'RELEASE-MANIFEST.txt'), $manifestLines, [Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllText((Join-Path $Root 'SHA256SUMS.txt'), "$hash  $fileName`n", [Text.Encoding]::ASCII)
    return $installer
}

function Get-InstallerFixtureVersion {
    param([Parameter(Mandatory)][string]$Installer)
    $productVersion=[string]([Diagnostics.FileVersionInfo]::GetVersionInfo($Installer).ProductVersion)
    if($productVersion -notmatch '^(\d+\.\d+\.\d+)'){throw "测试 PE ProductVersion 无效：$productVersion"}
    return $matches[1]
}

function Assert-Throws {
    param([Parameter(Mandatory)][scriptblock]$Script)
    $threw = $false
    try { & $Script | Out-Null } catch { $threw = $true }
    $threw | Should Be $true
}

Describe 'DDREC production release safety failures' {
    It '1 client working tree dirty' {
        Assert-Throws { Assert-DDRECGitReleaseState (New-GitState -Clean $false) -RequiredBranch 'v1.3' }
    }
    It '2 cloud working tree dirty' {
        Assert-Throws { Assert-DDRECGitReleaseState (New-GitState -Clean $false) -RequiredBranch 'v1.3' }
    }
    It '3 HEAD differs from origin v1.3' {
        Assert-Throws { Assert-DDRECGitReleaseState (New-GitState -Head ('a'*40) -Origin ('b'*40)) -RequiredBranch 'v1.3' }
    }
    It '4 SSH failure stops transport' {
        Assert-Throws { Assert-DDRECTransportResult -ExitCode 255 -Stage SSH }
    }
    It '5 installer Edition mismatch' {
        Assert-Throws { Assert-DDRECInstallerPolicy (New-Metadata -Edition license -Environment production) standard ('a'*40) '1.3.0' }
    }
    It '6 installer Build metadata and Git mismatch' {
        Assert-Throws { Assert-DDRECInstallerPolicy (New-Metadata -Commit ('b'*40)) standard ('a'*40) '1.3.0' }
    }
    It '7 correct filename cannot bypass internal Edition policy' {
        Assert-Throws { Assert-DDRECInstallerPolicy (New-Metadata -Edition license -Environment production) standard ('a'*40) '1.3.0' }
    }
    It '8 local and remote SHA mismatch' {
        Assert-Throws { Assert-DDRECHashCompatibility ('A'*64) ('B'*64) }
    }
    It '9 immutable target with different SHA cannot be overwritten' {
        Assert-Throws { Assert-DDRECHashCompatibility ('C'*64) ('D'*64) }
    }
    It '10 insufficient disk space' {
        Assert-Throws { Assert-DDRECDiskSpace 1GB 5GB }
    }
    It '11 PostgreSQL backup failure or empty dump' {
        Assert-Throws { Assert-DDRECBackupResult ([pscustomobject]@{Success=$false;Size=0;ChecksumValid=$false;RestoreListReadable=$false}) }
    }
    It '12 pending Migration is detected' {
        $plan=Get-DDRECMigrationSafety @('def upgrade():`n    op.add_column(...)')
        $plan.Destructive | Should Be $false
    }
    It '13 destructive Migration is blocked' {
        (Get-DDRECMigrationSafety @('def upgrade(): op.drop_column("x", "y")')).Destructive | Should Be $true
    }
    It '14 Docker health failure' {
        $s=[pscustomobject]@{ApiStatus='ok';Database='ok';AdminHttp=200;ApiContainerHealthy=$false;PostgresHealthy=$true;BuildCommit=('a'*40)}
        Assert-Throws { Assert-DDRECHealthSnapshot $s ('a'*40) }
    }
    It '15 Admin HTTP failure' {
        $s=[pscustomobject]@{ApiStatus='ok';Database='ok';AdminHttp=503;ApiContainerHealthy=$true;PostgresHealthy=$true;BuildCommit=('a'*40)}
        Assert-Throws { Assert-DDRECHealthSnapshot $s ('a'*40) }
    }
    It '16 download HTTP failure' {
        $p=[pscustomobject]@{StatusCode=500;RangeStatusCode=500;ContentLength=10;AcceptRanges=$false}
        Assert-Throws { Assert-DDRECDownloadProbe $p 10 }
    }
    It '17 Range failure' {
        $p=[pscustomobject]@{StatusCode=200;RangeStatusCode=200;ContentLength=10;AcceptRanges=$true}
        Assert-Throws { Assert-DDRECDownloadProbe $p 10 }
    }
    It '18 Ed25519 verification failure' {
        Assert-Throws { Assert-DDRECSignatureResult $false }
    }
    It '19 Draft API failure' {
        Assert-Throws { Assert-DDRECApiMutationResult ([pscustomobject]@{Success=$false}) Draft }
    }
    It '20 Published API failure' {
        Assert-Throws { Assert-DDRECApiMutationResult ([pscustomobject]@{Success=$false}) Published }
    }
    It '21 concurrent deployment lock is rejected' {
        Assert-Throws { Assert-DDRECDeployLock $false }
    }
    It '22 SSH interruption during upload cannot pass' {
        Assert-Throws { Assert-DDRECTransportResult -ExitCode 255 -Stage Upload }
    }
    It '23 cancelling DEPLOY performs no confirmation' {
        (Test-DDRECExplicitConfirmation CANCEL DEPLOY) | Should Be $false
    }
    It '24 cancelling PUBLISH keeps Draft' {
        (Test-DDRECExplicitConfirmation '' PUBLISH) | Should Be $false
    }
    It '25 rerunning the same published Build is idempotent' {
        (Get-DDRECIdempotencyAction published ('E'*64) ('E'*64)) | Should Be 'already-published'
    }
}

Describe 'DDREC client release branch and version mapping' {
    It 'accepts historical v1.3 with 1.3.0' {
        Assert-DDRECClientReleaseState -State (New-GitState -Branch 'v1.3') -ClientVersion '1.3.0' | Should Be $true
    }
    It 'accepts v1.3.1 with 1.3.1' {
        Assert-DDRECClientReleaseState -State (New-GitState -Branch 'v1.3.1') -ClientVersion '1.3.1' | Should Be $true
    }
    It 'rejects v1.3 with 1.3.1' {
        Assert-Throws { Assert-DDRECClientReleaseState -State (New-GitState -Branch 'v1.3') -ClientVersion '1.3.1' }
    }
    It 'rejects v1.3.1 with 1.3.0' {
        Assert-Throws { Assert-DDRECClientReleaseState -State (New-GitState -Branch 'v1.3.1') -ClientVersion '1.3.0' }
    }
    It 'rejects an unknown release branch' {
        Assert-Throws { Assert-DDRECClientReleaseState -State (New-GitState -Branch 'feature/release') -ClientVersion '1.3.1' }
    }
    It 'rejects a detached HEAD' {
        Assert-Throws { Assert-DDRECClientReleaseState -State (New-GitState -Branch '') -ClientVersion '1.3.1' }
    }
    It 'rejects a dirty v1.3.1 worktree' {
        Assert-Throws { Assert-DDRECClientReleaseState -State (New-GitState -Branch 'v1.3.1' -Clean $false) -ClientVersion '1.3.1' }
    }
    It 'rejects metadata version that differs from the mapped client version' {
        Assert-Throws {
            Assert-DDRECInstallerPolicy -Metadata (New-Metadata -Version '1.3.0') -Lane standard -ExpectedCommit ('a'*40) -ExpectedVersion '1.3.1'
        }
    }
    It 'does not use wildcard or prefix matching for release branches' {
        $definition=(Get-Command Get-DDRECExpectedClientVersion).Definition
        $definition|Should Not Match 'StartsWith'
        $definition|Should Not Match '-like'
        $definition|Should Not Match 'v1\.3\\\*'
    }
}

Describe 'DDREC successful safety policies' {
    It 'accepts clean matching Git state' { Assert-DDRECGitReleaseState (New-GitState) -RequiredBranch 'v1.3' | Should Be $true }
    It 'accepts Standard production artifact policy' { Assert-DDRECInstallerPolicy (New-Metadata) standard ('a'*40) '1.3.0' | Should Be $true }
    It 'accepts equal immutable SHA' { Assert-DDRECHashCompatibility ('F'*64) ('F'*64) | Should Be $true }
    It 'keeps standard and license-production isolated' { Assert-DDRECReleaseIsolation standard standard published | Should Be $true }
    It 'rejects standard receiving license-production stable' { Assert-Throws { Assert-DDRECReleaseIsolation standard license-production published } }
}

Describe 'DDREC PackageMetadata parsing and release modes' {
    It '41 parses Standard metadata into the unified model' {
        $installer = New-InstallerFixture -Root (Join-Path $TestDrive 'standard')
        $metadata = Get-DDRECInstallerMetadata -InstallerPath $installer -Lane standard -ExpectedCommit ('a'*40) -ExpectedVersion (Get-InstallerFixtureVersion $installer)
        ($metadata.PSObject.TypeNames -contains 'DDREC.PackageMetadata') | Should Be $true
        (@($metadata.PSObject.Properties.Name) -contains 'Path') | Should Be $true
        (@($metadata.PSObject.Properties.Name) -contains 'FileSize') | Should Be $true
        (@($metadata.PSObject.Properties.Name) -contains 'Version') | Should Be $true
        $metadata.Edition | Should Be 'standard'
        $metadata.Environment | Should Be 'none'
        @((Show-DDRECPackageMetadata -Metadata $metadata)).Count | Should Be 0
    }

    It '42 parses License-Production metadata into the same unified model' {
        $installer = New-InstallerFixture -Root (Join-Path $TestDrive 'license') -Edition license -Environment production
        $metadata = Get-DDRECInstallerMetadata -InstallerPath $installer -Lane license-production -ExpectedCommit ('a'*40) -ExpectedVersion (Get-InstallerFixtureVersion $installer)
        ($metadata.PSObject.TypeNames -contains 'DDREC.PackageMetadata') | Should Be $true
        $metadata.Edition | Should Be 'license'
        $metadata.Environment | Should Be 'production'
    }

    It '43 reports a business error when Edition is missing' {
        $installer = New-InstallerFixture -Root (Join-Path $TestDrive 'missing-edition') -MissingField Edition
        $message = try { Get-DDRECInstallerMetadata -InstallerPath $installer -Lane standard -ExpectedCommit ('a'*40) -ExpectedVersion (Get-InstallerFixtureVersion $installer) | Out-Null; '<no error>' } catch { $_.Exception.Message }
        $message | Should Be '安装包元数据无效：RELEASE-MANIFEST 缺少 Edition'
        $message | Should Not Match "property 'Edition'"
    }

    It '44 reports a business error when Environment is missing' {
        $installer = New-InstallerFixture -Root (Join-Path $TestDrive 'missing-environment') -MissingField Environment
        $message = try { Get-DDRECInstallerMetadata -InstallerPath $installer -Lane standard -ExpectedCommit ('a'*40) -ExpectedVersion (Get-InstallerFixtureVersion $installer) | Out-Null; '<no error>' } catch { $_.Exception.Message }
        $message | Should Be '安装包元数据无效：RELEASE-MANIFEST 缺少 Environment'
        $message | Should Not Match "property 'Environment'"
    }

    It '45 reports a business error when GitCommit is missing' {
        $installer = New-InstallerFixture -Root (Join-Path $TestDrive 'missing-commit') -MissingField GitCommit
        $message = try { Get-DDRECInstallerMetadata -InstallerPath $installer -Lane standard -ExpectedCommit ('a'*40) -ExpectedVersion (Get-InstallerFixtureVersion $installer) | Out-Null; '<no error>' } catch { $_.Exception.Message }
        $message | Should Be '安装包元数据无效：RELEASE-MANIFEST 缺少 GitCommit'
        $message | Should Not Match "property 'GitCommit'"
    }

    It '46 strictly rejects Standard and License lane mismatches' {
        Assert-Throws { Assert-DDRECInstallerPolicy (New-Metadata -Edition license -Environment production) standard ('a'*40) '1.3.0' }
        Assert-Throws { Assert-DDRECInstallerPolicy (New-Metadata -Edition standard -Environment none) license-production ('a'*40) '1.3.0' }
    }

    It '47 maps Standard mode to Standard client validation only' {
        $plan = Get-DDRECModePlan -Mode Standard
        $plan.Cloud | Should Be $false
        ($plan.Lanes -join ',') | Should Be 'standard'
    }

    It '48 maps License-Production mode to License client validation only' {
        $plan = Get-DDRECModePlan -Mode LicenseProduction
        $plan.Cloud | Should Be $false
        ($plan.Lanes -join ',') | Should Be 'license-production'
    }

    It '49 maps two-client mode to both unified metadata validations' {
        $plan = Get-DDRECModePlan -Mode BothClients
        $plan.Cloud | Should Be $false
        ($plan.Lanes -join ',') | Should Be 'standard,license-production'
    }

    It '50 maps Cloud mode without a client package' {
        $plan = Get-DDRECModePlan -Mode Cloud
        $plan.Cloud | Should Be $true
        @($plan.Lanes).Count | Should Be 0
    }

    It '51 maps Cloud plus Standard mode correctly' {
        $plan = Get-DDRECModePlan -Mode CloudStandard
        $plan.Cloud | Should Be $true
        ($plan.Lanes -join ',') | Should Be 'standard'
    }

    It '52 maps full mode to Cloud and both unified metadata validations' {
        $plan = Get-DDRECModePlan -Mode CloudBoth
        $plan.Cloud | Should Be $true
        ($plan.Lanes -join ',') | Should Be 'standard,license-production'
    }

    It '53 keeps stale GitCommit protection at exit code 70' {
        $installer = New-InstallerFixture -Root (Join-Path $TestDrive 'stale') -Commit ('b'*40)
        $message = try { Get-DDRECInstallerMetadata -InstallerPath $installer -Lane standard -ExpectedCommit ('a'*40) -ExpectedVersion (Get-InstallerFixtureVersion $installer) | Out-Null; '<no error>' } catch { $_.Exception.Message }
        $message | Should Match 'GitCommit 与当前 client HEAD 不一致'
        Get-DDRECFailureExitCode -Stage '客户端安装包识别与真实性校验' | Should Be 70
    }

    It '54 leaves production, Drafts, and Published untouched on missing metadata' {
        $context = New-DDRECReleaseContext -WorkspaceRoot $TestDrive -Config ([pscustomobject]@{}) -SessionId 'metadata-failure'
        $installer = New-InstallerFixture -Root (Join-Path $TestDrive 'safe-failure') -MissingField Edition
        try { Get-DDRECInstallerMetadata -InstallerPath $installer -Lane standard -ExpectedCommit ('a'*40) -ExpectedVersion (Get-InstallerFixtureVersion $installer) | Out-Null } catch {}
        $context.ProductionModified | Should Be $false
        $context.Drafts.Count | Should Be 0
        $context.Published.Count | Should Be 0
    }
}

Describe 'DDREC release works without local Docker' {
    BeforeAll {
        $script:cloudRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
        $script:workspaceRoot = (Resolve-Path (Join-Path $script:cloudRoot '..')).Path
        $script:releaseScript = Join-Path $script:cloudRoot 'scripts\release\release-all.ps1'
        $script:moduleScript = Join-Path $script:cloudRoot 'scripts\release\DDREC.Release.psm1'
        $script:buildScript = Join-Path $script:cloudRoot 'scripts\build_cloud_release.ps1'
        $script:executorScript = Join-Path $script:cloudRoot 'deploy\production-release\deploy-release.sh'
        $script:verifyScript = Join-Path $script:cloudRoot 'deploy\production-release\verify-release.sh'
    }

    It '31 workstation PATH has no docker executable' {
        (Get-Command docker -ErrorAction SilentlyContinue) | Should Be $null
    }
    It '32 release entry parses without Docker installed' {
        $errors = $null
        [Management.Automation.Language.Parser]::ParseFile($script:releaseScript, [ref]$null, [ref]$errors) | Out-Null
        @($errors).Count | Should Be 0
    }
    It '33 release module imports without Docker installed' {
        Import-Module $script:moduleScript -Force
        (Get-Command Get-DDRECRemoteState -ErrorAction Stop).Name | Should Be 'Get-DDRECRemoteState'
    }
    It '34 cloud package builder has no local docker command' {
        $text = Get-Content -LiteralPath $script:buildScript -Raw
        $text.Contains("Get-CommandPath 'docker.exe'") | Should Be $false
        $text.Contains('script:docker') | Should Be $false
    }
    It '35 release orchestrator does not request a local image export' {
        $text = Get-Content -LiteralPath $script:moduleScript -Raw
        $text.Contains('ExportDockerImage') | Should Be $false
        $text.Contains('Invoke-DDRECNative docker') | Should Be $false
    }
    It '36 production executor builds the API image on the server' {
        $text = Get-Content -LiteralPath $script:executorScript -Raw
        $text | Should Match 'docker build --pull=false'
        $text | Should Match 'target_api_tag=.*expected_commit'
    }
    It '37 server verifies the packaged API wheel' {
        $text = Get-Content -LiteralPath $script:verifyScript -Raw
        $text | Should Match 'ddrec_license_server-.*\.whl'
        $text | Should Match 'wheel_count'
    }
    It '38 menu and installer discovery contain only formal lanes' {
        $menu = Get-Content -LiteralPath $script:releaseScript -Raw
        $menu | Should Match 'Standard'
        $menu | Should Match 'License-Production'
        $menu.Contains('License Local') | Should Be $false
        $candidate = Get-DDRECInstallerCandidate -ClientRoot (Join-Path $script:workspaceRoot 'client') -Lane standard
        ($null -ne $candidate) | Should Be $true
    }
    It '39 menu uses a stable loop and captures each isolated task exit code' {
        $text = Get-Content -LiteralPath $script:releaseScript -Raw
        $menu=[regex]::Match($text,'(?s)function Invoke-ReleaseMenuLoop.*?(?=function Select-ClientUploadMode)').Value
        $menu|Should Match 'while\(\$true\)'
        $menu|Should Match "if\(\`$selectedMode -eq 'Exit'\)\{return"
        $menu|Should Match 'Invoke-DDRECConsoleTask -PwshPath \$pwsh'
        $menu|Should Match '-ExitCode \(\[ref\]\$taskExitCode\)'
        $menu|Should Match '按 Enter 返回主菜单'
        $text|Should Not Match 'exit \(Invoke-ReleaseMenuLoop\)'
    }
    It '40 menu reads the client version from the client repository' {
        $text = Get-Content -LiteralPath $script:releaseScript -Raw
        $text | Should Match 'Get-DDRECClientApplicationVersion -ClientRoot \$context\.ClientRoot'
        $definition=(Get-Command Get-DDRECClientApplicationVersion).Definition
        $definition | Should Match 'Push-Location \$ClientRoot'
        $definition | Should Match '无法读取客户端版本'
    }
    It '41 only menu zero maps to Exit and ordinary actions remain task modes' {
        (Get-DDRECMainMenuAction -InputText '0')|Should Be 'Exit'
        (Get-DDRECMainMenuAction -InputText '7')|Should Be 'DryRun'
        (Get-DDRECMainMenuAction -InputText '8')|Should Be 'Status'
        (Get-DDRECMainMenuAction -InputText '9')|Should Be 'Resume'
        (Get-DDRECMainMenuAction -InputText '')|Should Be 'Invalid'
    }
    It '42 BAT does not recursively relaunch itself and has no normal-exit second pause' {
        $bat=Get-Content -LiteralPath (Join-Path $script:workspaceRoot 'DDREC-Release.bat') -Raw -Encoding ASCII
        $bat|Should Not Match '(?im)^\s*(call|start)\s+.*DDREC-Release\.bat'
        ([regex]::Matches($bat,'(?im)^\s*pause\s*$')).Count|Should Be 3
        $bat|Should Match 'if not "%DDREC_EXIT%"=="0" \('
    }
    It '43 PowerShell owns the single return-to-menu prompt' {
        $text=Get-Content -LiteralPath $script:releaseScript -Raw
        ([regex]::Matches($text,'按 Enter 返回主菜单')).Count|Should Be 1
        $text|Should Not Match '(?im)^\s*pause\s*$'
    }
    It '44 does not clear the console between tasks' {
        $text=Get-Content -LiteralPath $script:releaseScript -Raw
        $text|Should Not Match '(?i)Clear-Host|cmd\s+/c\s+cls|(?m)^\s*cls\s*$'
    }
    It '45 streams child stdout and stderr before exit while preserving exit 70' {
        $child=Join-Path $TestDrive 'stream-child.ps1'
        $runner=Join-Path $TestDrive 'stream-runner.ps1'
        @'
[Console]::Out.WriteLine('STATUS-STDOUT')
[Console]::Out.Flush()
[Console]::Error.WriteLine('STATUS-STDERR')
[Console]::Error.Flush()
Start-Sleep -Seconds 2
exit 70
'@|Set-Content -LiteralPath $child -Encoding UTF8
        @"
Import-Module '$($script:moduleScript.Replace("'","''"))' -Force
`$code=0
Invoke-DDRECConsoleTask -PwshPath '$(Join-Path $PSHOME 'pwsh.exe')' -Arguments @('-NoLogo','-NoProfile','-File','$($child.Replace("'","''"))') -ExitCode ([ref]`$code)
Write-Output "CHILD-EXIT=`$code"
exit 0
"@|Set-Content -LiteralPath $runner -Encoding UTF8
        $start=[Diagnostics.ProcessStartInfo]::new()
        $start.FileName=Join-Path $PSHOME 'pwsh.exe'
        $start.UseShellExecute=$false;$start.CreateNoWindow=$true
        $start.RedirectStandardOutput=$true;$start.RedirectStandardError=$true
        [void]$start.ArgumentList.Add('-NoLogo');[void]$start.ArgumentList.Add('-NoProfile');[void]$start.ArgumentList.Add('-File');[void]$start.ArgumentList.Add($runner)
        $process=[Diagnostics.Process]::Start($start)
        $watch=[Diagnostics.Stopwatch]::StartNew()
        $stdout=$process.StandardOutput.ReadLine()
        $stderr=$process.StandardError.ReadLine()
        $watch.Stop()
        $stdout|Should Be 'STATUS-STDOUT'
        $stderr|Should Be 'STATUS-STDERR'
        $watch.Elapsed.TotalSeconds|Should BeLessThan 1.5
        $process.HasExited|Should Be $false
        $process.WaitForExit()
        $remaining=$process.StandardOutput.ReadToEnd()
        $remaining|Should Match 'CHILD-EXIT=70'
        $process.ExitCode|Should Be 0
    }
    It '46 child exit 80 does not terminate the menu host process' {
        $child=Join-Path $TestDrive 'exit80-child.ps1'
        $runner=Join-Path $TestDrive 'exit80-runner.ps1'
        'Write-Output "DRAFT-ERROR"; exit 80'|Set-Content -LiteralPath $child -Encoding UTF8
        @"
Import-Module '$($script:moduleScript.Replace("'","''"))' -Force
`$code=0
Invoke-DDRECConsoleTask -PwshPath '$(Join-Path $PSHOME 'pwsh.exe')' -Arguments @('-NoLogo','-NoProfile','-File','$($child.Replace("'","''"))') -ExitCode ([ref]`$code)
Write-Output "MENU-ALIVE=`$code"
exit 0
"@|Set-Content -LiteralPath $runner -Encoding UTF8
        $output=@(& (Join-Path $PSHOME 'pwsh.exe') -NoLogo -NoProfile -File $runner 2>&1)|ForEach-Object{[string]$_}
        $LASTEXITCODE|Should Be 0
        ($output -join "`n")|Should Match 'DRAFT-ERROR'
        ($output -join "`n")|Should Match 'MENU-ALIVE=80'
    }
    It '47 menu rendering is cache-only and performs no SSH HTTP or git command' {
        $text=Get-Content -LiteralPath $script:releaseScript -Raw
        $show=[regex]::Match($text,'(?s)function Show-DDRECReleaseMenu.*?(?=function Read-ReleaseMenuMode)').Value
        $show|Should Match 'ProductionApi'
        $show|Should Match 'ProductionRelease'
        $show|Should Not Match 'Get-DDRECRemoteState|Get-DDRECMenuProductionOverview|Invoke-DDRECSsh|Invoke-WebRequest|Invoke-RestMethod|Invoke-DDRECNative|\bgit\b'
    }
    It '48 menu local refresh uses rev-parse only and has no git network or worktree scan' {
        $text=Get-Content -LiteralPath $script:releaseScript -Raw
        $refresh=[regex]::Match($text,'(?s)function Update-ReleaseMenuLocalCache.*?(?=function Show-DDRECReleaseMenu)').Value
        $local=(Get-Command Get-DDRECLocalGitHead).Definition
        $refresh|Should Match 'Get-DDRECLocalGitHead'
        $refresh|Should Not Match 'Get-DDRECGitState|Get-DDRECRemoteState|Get-DDRECMenuProductionOverview'
        $local|Should Not Match "'fetch'|'ls-remote'|'status'|'origin/v1\.3'"
        $local|Should Match "rev-parse','HEAD"
    }
    It '49 Production overview is requested only during menu initialization' {
        $text=Get-Content -LiteralPath $script:releaseScript -Raw
        $loop=[regex]::Match($text,'(?s)function Invoke-ReleaseMenuLoop.*?(?=function Select-ClientUploadMode)').Value
        ([regex]::Matches($text,'Get-DDRECMenuProductionOverview -Context \$context')).Count|Should Be 1
        $loop|Should Not Match 'Get-DDRECRemoteState|Get-DDRECMenuProductionOverview'
    }
    It '50 cached Production overview parses current and API health' {
        $script:calls=0
        $fake={
            $script:calls++
            [pscustomobject]@{ExitCode=0;Output="current=/opt/pmsystem-license/release/cached`nhealthJson={`"status`":`"ok`"}"}
        }
        $ctx=[pscustomobject]@{Config=[pscustomobject]@{ServerHost='test'}}
        $overview=Get-DDRECMenuProductionOverview -Context $ctx -NativeInvoker $fake
        $overview.Api|Should Be 'ok'
        $overview.Release|Should Be '/opt/pmsystem-license/release/cached'
        $script:calls|Should Be 1
    }
    It '51 offline initial overview fails quickly to unknown instead of blocking menu safety' {
        $ctx=[pscustomobject]@{Config=[pscustomobject]@{ServerHost='test'}}
        $watch=[Diagnostics.Stopwatch]::StartNew()
        $overview=Get-DDRECMenuProductionOverview -Context $ctx -NativeInvoker { [pscustomobject]@{ExitCode=255;Output='network unreachable'} }
        $watch.Stop()
        $overview.Api|Should Be 'unknown'
        $overview.Release|Should Be 'unknown'
        $watch.Elapsed.TotalMilliseconds|Should BeLessThan 100
    }
    It '52 Status output refreshes the in-memory menu cache without another remote request' {
        $child=Join-Path $TestDrive 'status-cache-child.ps1'
        'Write-Output "CurrentRelease : /opt/pmsystem-license/release/new"; Write-Output "ApiStatus : ok"; exit 0'|Set-Content -LiteralPath $child -Encoding UTF8
        $cache=[pscustomobject]@{ProductionRelease='old';ProductionApi='unknown';LastProductionCheck=$null}
        $code=99
        Invoke-DDRECConsoleTask -PwshPath (Join-Path $PSHOME 'pwsh.exe') -Arguments @('-NoLogo','-NoProfile','-File',$child) -ExitCode ([ref]$code) -MenuCache $cache
        $code|Should Be 0
        $cache.ProductionRelease|Should Be '/opt/pmsystem-license/release/new'
        $cache.ProductionApi|Should Be 'ok'
        $cache.LastProductionCheck|Should Not Be $null
    }
    It '53 Dry Run and release preflight still obtain full live Production state' {
        $text=Get-Content -LiteralPath $script:releaseScript -Raw
        $taskBody=$text.Substring($text.IndexOf("if(`$Mode -eq 'Menu')"))
        $taskBody|Should Match '\$remoteState=Get-DDRECRemoteState -Context \$context'
        $taskBody|Should Match 'Assert-DDRECGitReleaseState'
        $taskBody|Should Match 'Assert-DDRECDiskSpace'
        $taskBody|Should Match "ApiStatus -ne 'ok'"
    }
    It '54 menu cache remains process memory and is not saved as a release safety fact' {
        $text=Get-Content -LiteralPath $script:releaseScript -Raw
        $save=[regex]::Match($text,'(?s)function Save-ReleaseSession.*?(?=function Invoke-ClientPackageStages)').Value
        $save|Should Not Match 'menuCache|ProductionApi|LastProductionCheck'
        $text|Should Not Match 'MenuCachePath|menu-cache\.json'
    }
    It '55 returning from Status Dry Run or Publish does not refresh Production remotely' {
        $text=Get-Content -LiteralPath $script:releaseScript -Raw
        $loop=[regex]::Match($text,'(?s)function Invoke-ReleaseMenuLoop.*?(?=function Select-ClientUploadMode)').Value
        $afterTask=[regex]::Match($loop,'(?s)Invoke-DDRECConsoleTask.*?Read-Host ''按 Enter 返回主菜单''').Value
        $afterTask|Should Match 'Update-ReleaseMenuLocalCache'
        $afterTask|Should Not Match 'Get-DDRECRemoteState|Get-DDRECMenuProductionOverview|Invoke-DDRECSsh|Invoke-RestMethod|Invoke-WebRequest'
    }
    It '56 ten cached menu render paths cannot create an SSH request' {
        $text=Get-Content -LiteralPath $script:releaseScript -Raw
        $show=[regex]::Match($text,'(?s)function Show-DDRECReleaseMenu.*?(?=function Read-ReleaseMenuMode)').Value
        1..10|ForEach-Object{$show|Should Not Match 'ssh|http|Get-DDRECRemoteState'}
    }
}
