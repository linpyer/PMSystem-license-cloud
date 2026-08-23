$modulePath=Join-Path $PSScriptRoot '..\..\scripts\release\DDREC.Release.psm1'
Import-Module $modulePath -Force

function Test-ActionThrows([scriptblock]$Action){try{& $Action|Out-Null;return $false}catch{return $true}}

function New-TestMetadata([string]$edition='standard'){
    $name=if($edition -eq 'standard'){'DDREC-1.3.0-standard-Setup.exe'}else{'DDREC-1.3.0-license-Setup.exe'}
    $environment=if($edition -eq 'standard'){'none'}else{'production'}
    return [pscustomobject]@{
        PSTypeName='DDREC.PackageMetadata';Path="C:\artifacts\$name";FileName=$name;FileSize=[int64]100
        SHA256=('A'*64);Version='1.3.0';BuildNumber=86;GitCommit=('b'*40);Edition=$edition
        Environment=$environment;UpdaterVersion='1.2.0';ManifestPath='m';ChecksumsPath='s';PEProductVersion='1.3.0'
    }
}

function New-TestContext {
    $workspace=Join-Path $TestDrive 'workspace'
    New-Item -ItemType Directory -Path (Join-Path $workspace 'cloud-license') -Force|Out-Null
    $config=[pscustomobject]@{RemoteRoot='/opt/pmsystem-license';DownloadRoot='/var/www/ddrec-downloads';DownloadBaseUrl='https://download.aixcc.top';ServerAddress='47.98.206.68'}
    return New-DDRECReleaseContext -WorkspaceRoot $workspace -Config $config -SessionId '20260823-165958'
}

Describe 'Manual client upload contract' {
    It 'constructs a strict POSIX incoming directory and never Windows backslashes' {
        $paths=Get-DDRECClientIncomingPaths -Context (New-TestContext) -Metadata (New-TestMetadata)
        $paths.Directory|Should Be '/opt/pmsystem-license/incoming/client/20260823-165958'
        $paths.Path.Contains('\')|Should Be $false
    }
    It 'rejects an unsafe session id' {
        $context=New-TestContext;$context.SessionId='../escape'
        (Test-ActionThrows {Get-DDRECClientIncomingPaths -Context $context -Metadata (New-TestMetadata)})|Should Be $true
    }
    It 'treats a missing Standard upload as invalid' {
        $status=[pscustomobject]@{Exists=$false;Regular=$false;FileName='';Size=0;SHA256='';Path='x'}
        (Test-DDRECIncomingPackageStatus -Status $status -Metadata (New-TestMetadata)).Reason|Should Be '文件不存在'
    }
    It 'blocks a partially uploaded Standard by exact size' {
        $status=[pscustomobject]@{Exists=$true;Regular=$true;FileName='DDREC-1.3.0-standard-Setup.exe.part';Size=50;SHA256=('A'*64);Path='x'}
        (Test-DDRECIncomingPackageStatus -Status $status -Metadata (New-TestMetadata)).Reason|Should Be '文件大小不一致'
    }
    It 'blocks a Standard upload with the wrong SHA' {
        $status=[pscustomobject]@{Exists=$true;Regular=$true;FileName='DDREC-1.3.0-standard-Setup.exe.part';Size=100;SHA256=('C'*64);Path='x'}
        (Test-DDRECIncomingPackageStatus -Status $status -Metadata (New-TestMetadata)).Reason|Should Be 'SHA256 不一致'
    }
    It 'accepts Standard only when file name size and SHA all match' {
        $status=[pscustomobject]@{Exists=$true;Regular=$true;FileName='DDREC-1.3.0-standard-Setup.exe.part';Size=100;SHA256=('a'*64);Path='x'}
        (Test-DDRECIncomingPackageStatus -Status $status -Metadata (New-TestMetadata)).Valid|Should Be $true
    }
    It 'accepts License-Production with its exact lane file name' {
        $status=[pscustomobject]@{Exists=$true;Regular=$true;FileName='DDREC-1.3.0-license-Setup.exe.part';Size=100;SHA256=('A'*64);Path='x'}
        (Test-DDRECIncomingPackageStatus -Status $status -Metadata (New-TestMetadata 'license')).Valid|Should Be $true
    }
    It 'Q maps to a safe quit action' {(Get-DDRECManualUploadAction -InputText 'Q')|Should Be 'Quit'}
    It 'Enter maps to verification rather than success' {(Get-DDRECManualUploadAction -InputText '')|Should Be 'Check'}
    It 'invalid input is rejected' {(Get-DDRECManualUploadAction -InputText 'Y')|Should Be 'Invalid'}
}

Describe 'Persistent Resume state' {
    It 'writes state atomically and leaves no temporary state files' {
        $context=New-TestContext
        $state=[pscustomobject]@{SchemaVersion=1;SessionId=$context.SessionId;UpdatedAt=$null;CloudDeployed=$true;Published=$false;CompletedStage='CloudDeployed'}
        $path=Write-DDRECReleaseSessionState -Context $context -State $state
        Test-Path -LiteralPath $path|Should Be $true
        @(Get-ChildItem (Split-Path $path -Parent) -Filter '*.tmp').Count|Should Be 0
    }
    It 'round trips a valid session state' {
        $context=New-TestContext
        $state=[pscustomobject]@{SchemaVersion=1;SessionId=$context.SessionId;UpdatedAt=$null;CloudDeployed=$true;Published=$false;CompletedStage='CloudDeployed'}
        Write-DDRECReleaseSessionState -Context $context -State $state|Out-Null
        (Read-DDRECReleaseSessionState -Context $context).SessionId|Should Be $context.SessionId
    }
    It 'accepts Resume only when current API health and DB revision match' {
        $state=[pscustomobject]@{CloudDeployed=$true;CurrentSwitched=$true;CloudRelease='/opt/pmsystem-license/release/1.3.0-8081c65';CloudGitCommit=('8'*40);DbRevision='0007_client_releases'}
        $remote=[pscustomobject]@{Current=$state.CloudRelease;BuildCommit=$state.CloudGitCommit;ApiStatus='ok';Database='ok';ApiContainer='healthy';PostgresContainer='healthy';AdminHttp=200;DbRevision=$state.DbRevision;CodeHead=$state.DbRevision}
        Assert-DDRECResumeProductionState -State $state -RemoteState $remote|Should Be $true
    }
    It 'blocks Resume when current does not match the session' {
        $state=[pscustomobject]@{CloudDeployed=$true;CurrentSwitched=$true;CloudRelease='expected';CloudGitCommit=('8'*40);DbRevision='0007_client_releases'}
        $remote=[pscustomobject]@{Current='other';BuildCommit=$state.CloudGitCommit;ApiStatus='ok';Database='ok';ApiContainer='healthy';PostgresContainer='healthy';AdminHttp=200;DbRevision=$state.DbRevision;CodeHead=$state.DbRevision}
        (Test-ActionThrows {Assert-DDRECResumeProductionState -State $state -RemoteState $remote})|Should Be $true
    }
    It 'blocks Resume when API is unhealthy' {
        $state=[pscustomobject]@{CloudDeployed=$true;CurrentSwitched=$true;CloudRelease='x';CloudGitCommit=('8'*40);DbRevision='0007_client_releases'}
        $remote=[pscustomobject]@{Current='x';BuildCommit=$state.CloudGitCommit;ApiStatus='down';Database='ok';ApiContainer='healthy';PostgresContainer='healthy';AdminHttp=200;DbRevision=$state.DbRevision;CodeHead=$state.DbRevision}
        (Test-ActionThrows {Assert-DDRECResumeProductionState -State $state -RemoteState $remote})|Should Be $true
    }
    It 'blocks Resume when database revision changes' {
        $state=[pscustomobject]@{CloudDeployed=$true;CurrentSwitched=$true;CloudRelease='x';CloudGitCommit=('8'*40);DbRevision='0007_client_releases'}
        $remote=[pscustomobject]@{Current='x';BuildCommit=$state.CloudGitCommit;ApiStatus='ok';Database='ok';ApiContainer='healthy';PostgresContainer='healthy';AdminHttp=200;DbRevision='other';CodeHead='other'}
        (Test-ActionThrows {Assert-DDRECResumeProductionState -State $state -RemoteState $remote})|Should Be $true
    }
    It 'revalidates local installer metadata against the session' {
        $metadata=New-TestMetadata
        $item=[pscustomobject]@{Path=$metadata.Path;FileName=$metadata.FileName;Version=$metadata.Version;BuildNumber=$metadata.BuildNumber;GitCommit=$metadata.GitCommit;Edition=$metadata.Edition;Environment=$metadata.Environment;FileSize=$metadata.FileSize;SHA256=$metadata.SHA256}
        Assert-DDRECSessionClientMetadata -SessionItem $item -Metadata $metadata|Should Be $true
    }
    It 'blocks a session/local installer SHA conflict' {
        $metadata=New-TestMetadata
        $item=[pscustomobject]@{Path=$metadata.Path;FileName=$metadata.FileName;Version=$metadata.Version;BuildNumber=$metadata.BuildNumber;GitCommit=$metadata.GitCommit;Edition=$metadata.Edition;Environment=$metadata.Environment;FileSize=$metadata.FileSize;SHA256=('F'*64)}
        (Test-ActionThrows {Assert-DDRECSessionClientMetadata -SessionItem $item -Metadata $metadata})|Should Be $true
    }
}

Describe 'Immutable final and Draft safety' {
    It 'requires an exact HTTP 200 and Range 206 response' {
        $probe=[pscustomobject]@{StatusCode=200;RangeStatusCode=206;ContentLength=100;AcceptRanges=$true}
        Assert-DDRECDownloadProbe -Probe $probe -ExpectedLength 100|Should Be $true
    }
    It 'does not accept a non-200 full response' {
        $probe=[pscustomobject]@{StatusCode=206;RangeStatusCode=206;ContentLength=100;AcceptRanges=$true}
        (Test-ActionThrows {Assert-DDRECDownloadProbe -Probe $probe -ExpectedLength 100})|Should Be $true
    }
    It 'reuses an existing Draft only when all immutable metadata match' {
        $metadata=New-TestMetadata;$target=[pscustomobject]@{RelativePath='/releases/stable/standard/1.3.0/86/DDREC-1.3.0-standard-Setup.exe'}
        $existing=[pscustomobject]@{product='DDREC';version='1.3.0';buildNumber=86;gitCommit=$metadata.GitCommit;edition='standard';environment='production';architecture='x64';channel='stable';fileName=$metadata.FileName;downloadPath=$target.RelativePath;fileSize=100;sha256=$metadata.SHA256;status='draft'}
        Assert-DDRECExistingDraftCompatibility -Existing $existing -Metadata $metadata -Target $target|Should Be $true
    }
    It 'blocks a Draft with conflicting metadata' {
        $metadata=New-TestMetadata;$target=[pscustomobject]@{RelativePath='/correct'}
        $existing=[pscustomobject]@{product='DDREC';version='1.3.0';buildNumber=86;gitCommit=$metadata.GitCommit;edition='standard';environment='production';architecture='x64';channel='stable';fileName=$metadata.FileName;downloadPath='/wrong';fileSize=100;sha256=$metadata.SHA256;status='draft'}
        (Test-ActionThrows {Assert-DDRECExistingDraftCompatibility -Existing $existing -Metadata $metadata -Target $target})|Should Be $true
    }
    It 'uses an atomic rename and never overwrites a different final package' {
        $text=Get-Content (Join-Path $PSScriptRoot '..\..\deploy\production-release\install-client-package.sh') -Raw
        $text|Should Match 'mv -T -- "\$staged" "\$final"'
        $text|Should Match "existing immutable client package"
    }
    It 'limits final installation to stable Standard or License paths' {
        $text=Get-Content (Join-Path $PSScriptRoot '..\..\deploy\production-release\install-client-package.sh') -Raw
        $text|Should Match 'releases/stable/standard'
        $text|Should Match 'releases/stable/license'
        $text|Should Not Match 'license-local'
    }
}

Describe 'Release orchestration regression guards' {
    $releaseText=Get-Content (Join-Path $PSScriptRoot '..\..\scripts\release\release-all.ps1') -Raw
    $moduleText=Get-Content $modulePath -Raw
    It 'does not SCP client packages from the client flow' {
        $moduleText|Should Not Match 'SCP 上传客户端安装包'
        $releaseText|Should Not Match 'Invoke-DDRECClientUpload'
    }
    It 'creates the protected incoming directory before displaying the upload prompt' {
        $moduleText.IndexOf('install -d -o root -g root -m 0750')|Should BeGreaterThan -1
        $moduleText.IndexOf('Initialize-DDRECClientIncomingDirectory -Context')|Should BeLessThan $moduleText.IndexOf('Show-DDRECManualUploadPrompt -Context')
    }
    It 'keeps Standard before License-Production in a two-client release' {
        (Get-DDRECModePlan -Mode CloudBoth).Lanes -join ','|Should Be 'standard,license-production'
    }
    It 'does not enter Draft creation until all client package stages complete' {
        $releaseText.IndexOf('Invoke-ClientPackageStages -Targets $targets')|Should BeLessThan $releaseText.IndexOf('Invoke-ClientDraftAndPublishStages -Targets $targets')
    }
    It 'checks HTTP and final SHA before signing and Draft' {
        $releaseText.IndexOf('Test-DDRECRemoteClientTarget -Context $context -Target $item.Target')|Should BeLessThan $releaseText.IndexOf('Invoke-DDRECManifestSigning -Context $context')
    }
    It 'adds an explicit Resume menu entry' {$releaseText|Should Match '\[9\] 继续未完成发布'}
    It 'states that Resume never redeploys Cloud' {
        $releaseText|Should Match '不会重新构建、上传或部署 Cloud'
        $resume=[regex]::Match($releaseText,'(?s)if\(\$Mode -eq ''Resume''\).*?(?=Write-DDRECLog -Context \$context -Message "发布 Session)').Value
        $resume|Should Not Match 'Invoke-DDRECCloudDeploy'
    }
    It 'keeps final PUBLISH as an exact explicit confirmation' {$releaseText|Should Match "-ceq 'PUBLISH'"}
    It 'never logs secrets through the session state schema' {
        $schema=[regex]::Match($moduleText,'(?s)function New-DDRECReleaseSessionState.*?(?=function Update-DDRECReleaseSessionFromContext)').Value
        $schema|Should Not Match '(?i)password|privatekey|totp|credential'
    }
    It 'does not invoke rollback for a client upload failure' {$releaseText|Should Not Match 'Rollback-DDREC|rollback-release'}
}
