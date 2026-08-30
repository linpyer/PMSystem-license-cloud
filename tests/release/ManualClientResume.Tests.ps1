$modulePath=Join-Path $PSScriptRoot '..\..\scripts\release\DDREC.Release.psm1'
Import-Module $modulePath -Force

function Test-ActionThrows([scriptblock]$Action){try{& $Action|Out-Null;return $false}catch{return $true}}

function New-TestMetadata([string]$edition='standard'){
    $name=if($edition -eq 'standard'){'iVRec-1.4.0-standard-Setup.exe'}else{'iVRec-1.4.0-license-Setup.exe'}
    $environment=if($edition -eq 'standard'){'none'}else{'production'}
    return [pscustomobject]@{
        PSTypeName='DDREC.PackageMetadata';Path="C:\artifacts\$name";FileName=$name;FileSize=[int64]100
        SHA256=('A'*64);Product='iVRec';DisplayName='iVRec';MainExe='iVRec.exe';UpdaterExe='iVRec-Updater.exe'
        Version='1.4.0';BuildNumber=86;GitCommit=('b'*40);Edition=$edition
        Environment=$environment;UpdaterVersion='1.2.0';ManifestPath='m';ChecksumsPath='s';PEProductVersion='1.4.0'
    }
}

function New-TestContext {
    $workspace=Join-Path $TestDrive 'workspace'
    New-Item -ItemType Directory -Path (Join-Path $workspace 'cloud-license') -Force|Out-Null
    $config=[pscustomobject]@{RemoteRoot='/opt/pmsystem-license';DownloadRoot='/var/www/ddrec-downloads';DownloadBaseUrl='https://download.aixcc.top';ApiBaseUrl='https://license.aixcc.top/api/v1';ServerAddress='47.98.206.68'}
    return New-DDRECReleaseContext -WorkspaceRoot $workspace -Config $config -SessionId '20260823-165958'
}

function New-IncomingStatus([string]$name,[bool]$exists=$true,[bool]$regular=$true,[int64]$size=100,[string]$sha=('A'*64)){
    return [pscustomobject]@{Exists=$exists;Regular=$regular;FileName=$(if($exists){$name}else{''});ExpectedFileName=$name;Size=$(if($exists){$size}else{0});SHA256=$(if($exists){$sha}else{''});Path="/incoming/$name"}
}

Describe 'Manual client upload contract' {
    It 'constructs a strict POSIX incoming directory and never Windows backslashes' {
        $paths=Get-DDRECClientIncomingPaths -Context (New-TestContext) -Metadata (New-TestMetadata)
        $paths.Directory|Should Be '/opt/pmsystem-license/incoming/client/20260823-165958'
        $paths.Path.Contains('\')|Should Be $false
        $paths.FileName|Should Be 'iVRec-1.4.0-standard-Setup.exe'
        $paths.LegacyFileName|Should Be 'iVRec-1.4.0-standard-Setup.exe.part'
        $paths.AutoPath|Should Be $paths.LegacyPath
    }
    It 'rejects an unsafe session id' {
        $context=New-TestContext;$context.SessionId='../escape'
        (Test-ActionThrows {Get-DDRECClientIncomingPaths -Context $context -Metadata (New-TestMetadata)})|Should Be $true
    }
    It 'treats a missing Standard upload as invalid' {
        $status=New-IncomingStatus 'iVRec-1.4.0-standard-Setup.exe' $false $false
        (Test-DDRECIncomingPackageStatus -Status $status -Metadata (New-TestMetadata)).Reason|Should Be '文件不存在'
    }
    It 'accepts a canonical exe manual upload' {
        $status=New-IncomingStatus 'iVRec-1.4.0-standard-Setup.exe'
        (Test-DDRECIncomingPackageStatus -Status $status -Metadata (New-TestMetadata)).Valid|Should Be $true
    }
    It 'blocks a partially uploaded Standard exe by exact size' {
        $status=New-IncomingStatus 'iVRec-1.4.0-standard-Setup.exe' $true $true 50
        (Test-DDRECIncomingPackageStatus -Status $status -Metadata (New-TestMetadata)).Reason|Should Be '文件大小不一致'
    }
    It 'blocks a Standard exe upload with the wrong SHA' {
        $status=New-IncomingStatus 'iVRec-1.4.0-standard-Setup.exe' $true $true 100 ('C'*64)
        (Test-DDRECIncomingPackageStatus -Status $status -Metadata (New-TestMetadata)).Reason|Should Be 'SHA256 不一致'
    }
    It 'accepts the historical Standard part name' {
        $status=New-IncomingStatus 'iVRec-1.4.0-standard-Setup.exe.part' $true $true 100 ('a'*64)
        (Test-DDRECIncomingPackageStatus -Status $status -Metadata (New-TestMetadata)).Valid|Should Be $true
    }
    It 'accepts License-Production with its exact lane file name' {
        $status=New-IncomingStatus 'iVRec-1.4.0-license-Setup.exe'
        (Test-DDRECIncomingPackageStatus -Status $status -Metadata (New-TestMetadata 'license')).Valid|Should Be $true
    }
    It 'prefers canonical exe when exe and part are identical' {
        $metadata=New-TestMetadata
        $resolved=Resolve-DDRECIncomingCandidateStatus -CanonicalStatus (New-IncomingStatus $metadata.FileName) -LegacyStatus (New-IncomingStatus "$($metadata.FileName).part") -Metadata $metadata
        $resolved.Valid|Should Be $true
        $resolved.SelectedFileName|Should Be $metadata.FileName
    }
    It 'blocks conflicting exe and part candidates' {
        $metadata=New-TestMetadata
        $resolved=Resolve-DDRECIncomingCandidateStatus -CanonicalStatus (New-IncomingStatus $metadata.FileName) -LegacyStatus (New-IncomingStatus "$($metadata.FileName).part" $true $true 100 ('C'*64)) -Metadata $metadata
        $resolved.Valid|Should Be $false
        $resolved.Reason|Should Match '冲突'
    }
    It 'Q maps to a safe quit action' {(Get-DDRECManualUploadAction -InputText 'Q')|Should Be 'Quit'}
    It 'Enter maps to verification rather than success' {(Get-DDRECManualUploadAction -InputText '')|Should Be 'Check'}
    It 'invalid input is rejected' {(Get-DDRECManualUploadAction -InputText 'Y')|Should Be 'Invalid'}
    It 'requires an explicit upload mode and gives Enter no default' {
        (Get-DDRECClientUploadModeAction -InputText '1')|Should Be 'auto'
        (Get-DDRECClientUploadModeAction -InputText '2')|Should Be 'manual'
        (Get-DDRECClientUploadModeAction -InputText '0')|Should Be 'cancel'
        (Get-DDRECClientUploadModeAction -InputText '')|Should Be 'invalid'
    }
}

Describe 'Automatic client upload contract' {
    BeforeEach {
        $script:destinations=[Collections.Generic.List[string]]::new()
        $script:initializer={param($context,$metadata)[pscustomobject]@{Directory='/opt/pmsystem-license/incoming/client/20260823-165958';AutoPath="/opt/pmsystem-license/incoming/client/20260823-165958/$($metadata.FileName).part"}}
        $script:transfer={param($local,$destination)$script:destinations.Add($destination);[pscustomobject]@{ExitCode=0;Output=''}}
        $script:status={param($context,$metadata)[pscustomobject]@{Valid=$true;SelectedFileName="$($metadata.FileName).part";ExpectedSize=$metadata.FileSize;ExpectedSHA256=$metadata.SHA256}}
    }
    It 'automatically uploads and verifies Standard through an internal part path' {
        $context=New-TestContext;$context.Config|Add-Member -NotePropertyName ServerHost -NotePropertyValue 'root@example'
        $result=Invoke-DDRECAutomaticClientUpload -Context $context -Metadata (New-TestMetadata) -DirectoryInitializer $script:initializer -TransferInvoker $script:transfer -StatusReader $script:status
        $result.Action|Should Be 'Verified'
        $script:destinations.Count|Should Be 1
        $script:destinations[0]|Should Match '/iVRec-1\.4\.0-standard-Setup\.exe\.part$'
    }
    It 'automatically uploads and verifies License-Production' {
        $context=New-TestContext;$context.Config|Add-Member -NotePropertyName ServerHost -NotePropertyValue 'root@example'
        (Invoke-DDRECAutomaticClientUpload -Context $context -Metadata (New-TestMetadata 'license') -DirectoryInitializer $script:initializer -TransferInvoker $script:transfer -StatusReader $script:status).Action|Should Be 'Verified'
        $script:destinations.Count|Should Be 1
        $script:destinations[0]|Should Match '/iVRec-1\.4\.0-license-Setup\.exe\.part$'
    }
    It 'maps auto upload failure choices without a dangerous default' {
        (Get-DDRECAutoUploadFailureAction '1')|Should Be 'Retry'
        (Get-DDRECAutoUploadFailureAction '2')|Should Be 'Manual'
        (Get-DDRECAutoUploadFailureAction '3')|Should Be 'Save'
        (Get-DDRECAutoUploadFailureAction '')|Should Be 'Invalid'
    }
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
    It 'persists and reads auto or manual upload mode' {
        $state=[pscustomobject]@{ClientUploadMode='auto'}
        (Get-DDRECSessionUploadMode -State $state)|Should Be 'auto'
        Set-DDRECSessionUploadMode -State $state -Mode manual|Out-Null
        (Get-DDRECSessionUploadMode -State $state)|Should Be 'manual'
    }
    It 'treats a historical schema-v1 session as manual' {
        (Get-DDRECSessionUploadMode -State ([pscustomobject]@{SchemaVersion=1}))|Should Be 'manual'
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
        $metadata=New-TestMetadata;$target=[pscustomobject]@{RelativePath='/releases/stable/standard/1.4.0/86/iVRec-1.4.0-standard-Setup.exe'}
        $existing=[pscustomobject]@{product='iVRec';version='1.4.0';buildNumber=86;gitCommit=$metadata.GitCommit;edition='standard';environment='production';architecture='x64';channel='stable';fileName=$metadata.FileName;downloadPath=$target.RelativePath;fileSize=100;sha256=$metadata.SHA256;status='draft'}
        Assert-DDRECExistingDraftCompatibility -Existing $existing -Metadata $metadata -Target $target|Should Be $true
    }
    It 'blocks a Draft with conflicting metadata' {
        $metadata=New-TestMetadata;$target=[pscustomobject]@{RelativePath='/correct'}
        $existing=[pscustomobject]@{product='iVRec';version='1.4.0';buildNumber=86;gitCommit=$metadata.GitCommit;edition='standard';environment='production';architecture='x64';channel='stable';fileName=$metadata.FileName;downloadPath='/wrong';fileSize=100;sha256=$metadata.SHA256;status='draft'}
        (Test-ActionThrows {Assert-DDRECExistingDraftCompatibility -Existing $existing -Metadata $metadata -Target $target})|Should Be $true
    }
    It 'uses an atomic rename and never overwrites a different final package' {
        $text=Get-Content (Join-Path $PSScriptRoot '..\..\deploy\production-release\install-client-package.sh') -Raw
        $text|Should Match 'mv -T -- "\$staged" "\$final"'
        $text|Should Match "existing immutable client package"
    }
    It 'server installer accepts canonical exe first and keeps legacy part compatibility' {
        $text=Get-Content (Join-Path $PSScriptRoot '..\..\deploy\production-release\install-client-package.sh') -Raw
        $text|Should Match 'canonical_incoming="\$incoming_dir/\$file_name"'
        $text|Should Match 'legacy_incoming="\$incoming_dir/\$file_name\.part"'
        $text.IndexOf('incoming=$canonical_incoming')|Should BeLessThan $text.IndexOf('incoming=$legacy_incoming')
        $text|Should Match 'canonical \.exe and legacy \.part conflict'
    }
    It 'incoming client staging remains outside the public download root' {
        $text=Get-Content (Join-Path $PSScriptRoot '..\..\deploy\production-release\install-client-package.sh') -Raw
        $text|Should Match 'incoming_dir="\$ROOT/incoming/client/\$session"'
        $text|Should Match 'DOWNLOAD_ROOT=/var/www/ddrec-downloads'
        $text|Should Not Match 'incoming_dir="\$DOWNLOAD_ROOT'
    }
    It 'limits final installation to stable Standard or License paths' {
        $text=Get-Content (Join-Path $PSScriptRoot '..\..\deploy\production-release\install-client-package.sh') -Raw
        $text|Should Match 'releases/stable/standard'
        $text|Should Match 'releases/stable/license'
        $text|Should Not Match 'license-local'
    }
    It 'accepts only strict current iVRec filenames for new writes' {
        $text=Get-Content (Join-Path $PSScriptRoot '..\..\deploy\production-release\install-client-package.sh') -Raw
        $match=[regex]::Match($text,'\[\[ \$file_name =~ (\^iVRec-[^\r\n]+?) \]\]')
        $match.Success|Should Be $true
        $pattern=$match.Groups[1].Value
        & bash -c '[[ "$1" =~ $2 ]]' _ 'iVRec-1.4.0-standard-Setup.exe' $pattern
        $LASTEXITCODE|Should Be 0
        & bash -c '[[ "$1" =~ $2 ]]' _ 'iVRec-1.4.0-license-Setup.exe' $pattern
        $LASTEXITCODE|Should Be 0
        foreach($invalid in @('iVRec-1.4-standard-Setup.exe','iVRec-1.4.0-standard.exe','DDREC-1.4.0-standard-Setup.exe','random.exe')){
            & bash -c '[[ "$1" =~ $2 ]]' _ $invalid $pattern
            $LASTEXITCODE|Should Not Be 0
        }
        $text|Should Match 'NEW WRITE PATH'
        $text|Should Not Match 'releases/stable/standard/\*/\*/DDREC-'
        $text|Should Not Match 'releases/stable/license/\*/\*/DDREC-'
    }
    It 'supports a zero-write production helper dry run before incoming paths are touched' {
        $text=Get-Content (Join-Path $PSScriptRoot '..\..\deploy\production-release\install-client-package.sh') -Raw
        $text|Should Match '--dry-run'
        $text.IndexOf('if [[ $dry_run == true ]]')|Should BeLessThan $text.IndexOf('incoming_dir="$ROOT/incoming/client/$session"')
    }
}

Describe 'Release orchestration regression guards' {
    $releaseText=Get-Content (Join-Path $PSScriptRoot '..\..\scripts\release\release-all.ps1') -Raw
    $moduleText=Get-Content $modulePath -Raw
    It 'supports explicit automatic upload while retaining manual upload' {
        $moduleText|Should Match 'Invoke-DDRECAutomaticClientUpload'
        $releaseText|Should Match 'Select-ClientUploadMode'
        $releaseText|Should Match 'Wait-DDRECManualClientUpload'
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
    It 'keeps historical Resume packages pinned to the Session commit after client HEAD advances' {
        $resumeTargets=[regex]::Match($releaseText,'(?s)function Get-ResumeTargets.*?(?=if\(\$Mode -eq ''Menu'')').Value
        $resumeTargets|Should Match '-ExpectedCommit \(\[string\]\$State.ClientGitCommit\)'
        $resume=[regex]::Match($releaseText,'(?s)if\(\$Mode -eq ''Resume''\).*?(?=Write-DDRECLog -Context \$context -Message "发布 Session)').Value
        $resume|Should Not Match 'client HEAD 与 Session 不一致'
    }
    It 'uses POSIX helpers rather than Split-Path for remote incoming paths' {
        $incoming=[regex]::Match($moduleText,'(?s)function Get-DDRECClientIncomingPaths.*?(?=function New-DDRECClientSessionItem)').Value
        $incoming|Should Match 'Join-DDRECPosixPath'
        $incoming|Should Not Match 'Split-Path'
    }
    It 'keeps automatic part files internal and manual prompts on the original exe name' {
        $moduleText|Should Match 'AutoFileName = "\$\(\$Metadata.FileName\)\.part"'
        $moduleText|Should Match '无需修改扩展名'
    }
    It 'allows auto failure to switch to manual without redeploying Cloud' {
        $releaseText|Should Match '\$activeMode=''manual'''
        $releaseText|Should Match '不会重新执行 Cloud 部署'
    }
    It 'keeps final PUBLISH as an exact explicit confirmation' {$releaseText|Should Match "-ceq 'PUBLISH'"}
    It 'never logs secrets through the session state schema' {
        $schema=[regex]::Match($moduleText,'(?s)function New-DDRECReleaseSessionState.*?(?=function Update-DDRECReleaseSessionFromContext)').Value
        $schema|Should Not Match '(?i)password|privatekey|totp|credential'
    }
    It 'does not invoke rollback for a client upload failure' {$releaseText|Should Not Match 'Rollback-DDREC|rollback-release'}
}

Describe 'OWNER authentication and Draft API contract' {
    It 'accepts a valid OWNER login request without exposing the password value' {
        $context=New-TestContext;$secret=ConvertTo-SecureString 'NeverLogThisPassword!' -AsPlainText -Force
        $login=Start-DDRECAdminLogin -Context $context -Username 'owner' -Password $secret -RequestInvoker {param($p)[pscustomobject]@{challenge=('c'*40)}}
        $login.Challenge.Length|Should Be 40
        (Get-Content $context.LogPath -Raw)|Should Not Match 'NeverLogThisPassword'
    }
    It 'formats a 422 OWNER field validation error with endpoint and detail' {
        $body='{"detail":[{"loc":["body","username"],"msg":"String should have at least 3 characters"}]}'
        $message=New-DDRECApiFailureMessage -Operation 'OWNER登录' -Method POST -Endpoint 'https://example/admin/auth/login' -Status 422 -RequestFields username,password -ResponseBody $body
        $message|Should Match 'HTTP: 422';$message|Should Match 'field=body.username';$message|Should Match 'at least 3'
    }
    It 'reports TOTP authentication failure as its own endpoint and stage' {
        $body='{"error":{"code":"ADMIN_INVALID_CREDENTIALS","message":"Invalid TOTP","retryable":false}}'
        $message=New-DDRECApiFailureMessage -Operation 'OWNER TOTP 验证' -Method POST -Endpoint 'https://example/admin/auth/totp/verify' -Status 401 -RequestFields challenge,code -ResponseBody $body
        $message|Should Match 'OWNER TOTP';$message|Should Match 'ADMIN_INVALID_CREDENTIALS'
    }
    It 'requires TOTP to be a six digit secret before any request' {
        $context=New-TestContext;$login=[pscustomobject]@{Session=[Microsoft.PowerShell.Commands.WebRequestSession]::new();Challenge=('c'*40);CsrfToken='csrf';RequestInvoker={throw 'must not call'}}
        $totp=ConvertTo-SecureString '12x456' -AsPlainText -Force
        (Test-ActionThrows {Complete-DDRECAdminTotp -Context $context -Login $login -Totp $totp})|Should Be $true
    }
    It 'uses non-echoing secure input for both Password and TOTP' {
        $text=Get-Content $modulePath -Raw
        $text|Should Match "Read-Host 'Password' -AsSecureString"
        $text|Should Match "Read-Host 'TOTP' -AsSecureString"
    }
    It 'never writes a password or TOTP value to logs or session JSON' {
        $text=Get-Content $modulePath -Raw
        $text|Should Not Match 'Write-DDRECLog[^\r\n]+plainPassword'
        $text|Should Not Match 'Write-DDRECLog[^\r\n]+plainTotp'
        $session=Get-Content (Join-Path $PSScriptRoot '..\..\scripts\release\DDREC.Release.psm1') -Raw
        [regex]::Match($session,'(?s)function New-DDRECReleaseSessionState.*?(?=function Update-DDRECReleaseSessionFromContext)').Value|Should Not Match '(?i)password|totp|token|cookie'
    }
    It 'builds a complete Standard Draft payload compatible with the production wire schema' {
        $metadata=New-TestMetadata;$target=[pscustomobject]@{RelativePath='/releases/stable/standard/1.4.0/86/iVRec-1.4.0-standard-Setup.exe'}
        $signed=[pscustomobject]@{Signature=('s'*86);Manifest=[pscustomobject]@{publishedAt='2026-08-23T10:41:13Z'}}
        $payload=New-DDRECClientDraftPayload -Metadata $metadata -Target $target -Signed $signed
        $payload.environment|Should Be 'production';$payload.releaseNotes.Length|Should BeGreaterThan 0
        Assert-DDRECClientDraftPayload -Payload $payload|Should Be $true
    }
    It 'builds a complete License-Production Draft payload' {
        $metadata=New-TestMetadata 'license';$target=[pscustomobject]@{RelativePath='/releases/stable/license/1.4.0/86/iVRec-1.4.0-license-Setup.exe'}
        $signed=[pscustomobject]@{Signature=('s'*86);Manifest=[pscustomobject]@{publishedAt='2026-08-23T10:41:13Z'}}
        $payload=New-DDRECClientDraftPayload -Metadata $metadata -Target $target -Signed $signed
        $payload.edition|Should Be 'license';$payload.environment|Should Be 'production'
    }
    It 'identifies a missing required Draft field before HTTP' {
        $payload=[ordered]@{product='iVRec'}
        $message='';try{Assert-DDRECClientDraftPayload -Payload $payload|Out-Null}catch{$message=$_.Exception.Message}
        $message|Should Match '缺少 version'
    }
    It 'does not send retired or unsupported Draft fields' {
        $metadata=New-TestMetadata;$target=[pscustomobject]@{RelativePath='/releases/stable/standard/1.4.0/86/iVRec-1.4.0-standard-Setup.exe'}
        $signed=[pscustomobject]@{Signature=('s'*86);Manifest=[pscustomobject]@{publishedAt='2026-08-23T10:41:13Z'}}
        $payload=New-DDRECClientDraftPayload -Metadata $metadata -Target $target -Signed $signed
        ('updaterVersion' -notin @($payload.Keys))|Should Be $true;('licenseLocal' -notin @($payload.Keys))|Should Be $true
    }
    It 'creates a Standard Draft with the complete validated payload' {
        $context=New-TestContext;$metadata=New-TestMetadata;$target=[pscustomobject]@{RelativePath='/releases/stable/standard/1.4.0/86/iVRec-1.4.0-standard-Setup.exe'}
        $signed=[pscustomobject]@{Signature=('s'*86);Manifest=[pscustomobject]@{publishedAt='2026-08-23T10:41:13Z'}}
        $release=[pscustomobject]@{id='standard-draft';status='draft';product='iVRec';version='1.4.0';buildNumber=86;gitCommit=$metadata.GitCommit;edition='standard';environment='production';architecture='x64';channel='stable';fileName=$metadata.FileName;downloadPath=$target.RelativePath;fileSize=100;sha256=$metadata.SHA256}
        $auth=[pscustomobject]@{Session=[Microsoft.PowerShell.Commands.WebRequestSession]::new();CsrfToken='csrf';RequestInvoker={param($p)if($p.Method -eq 'GET'){[pscustomobject]@{items=@()}}else{[pscustomobject]@{release=$release}}}}
        (New-DDRECClientDraft -Context $context -Auth $auth -Metadata $metadata -Target $target -Signed $signed).id|Should Be 'standard-draft'
    }
    It 'creates a License-Production Draft independently' {
        $context=New-TestContext;$metadata=New-TestMetadata 'license';$target=[pscustomobject]@{RelativePath='/releases/stable/license/1.4.0/86/iVRec-1.4.0-license-Setup.exe'}
        $signed=[pscustomobject]@{Signature=('s'*86);Manifest=[pscustomobject]@{publishedAt='2026-08-23T10:41:13Z'}}
        $release=[pscustomobject]@{id='license-draft';status='draft';product='iVRec';version='1.4.0';buildNumber=86;gitCommit=$metadata.GitCommit;edition='license';environment='production';architecture='x64';channel='stable';fileName=$metadata.FileName;downloadPath=$target.RelativePath;fileSize=100;sha256=$metadata.SHA256}
        $auth=[pscustomobject]@{Session=[Microsoft.PowerShell.Commands.WebRequestSession]::new();CsrfToken='csrf';RequestInvoker={param($p)if($p.Method -eq 'GET'){[pscustomobject]@{items=@()}}else{[pscustomobject]@{release=$release}}}}
        (New-DDRECClientDraft -Context $context -Auth $auth -Metadata $metadata -Target $target -Signed $signed).id|Should Be 'license-draft'
    }
    It 'reuses an existing matching Draft without issuing a POST' {
        $context=New-TestContext;$metadata=New-TestMetadata;$target=[pscustomobject]@{RelativePath='/releases/stable/standard/1.4.0/86/iVRec-1.4.0-standard-Setup.exe'}
        $signed=[pscustomobject]@{Signature=('s'*86);Manifest=[pscustomobject]@{publishedAt='2026-08-23T10:41:13Z'}}
        $existing=[pscustomobject]@{id='existing';status='draft';product='iVRec';version='1.4.0';buildNumber=86;gitCommit=$metadata.GitCommit;edition='standard';environment='production';architecture='x64';channel='stable';fileName=$metadata.FileName;downloadPath=$target.RelativePath;fileSize=100;sha256=$metadata.SHA256}
        $script:draftPostCalls=0
        $auth=[pscustomobject]@{Session=[Microsoft.PowerShell.Commands.WebRequestSession]::new();CsrfToken='csrf';RequestInvoker={param($p)if($p.Method -eq 'GET'){[pscustomobject]@{items=@($existing)}}else{$script:draftPostCalls++;throw 'unexpected POST'}}}
        (New-DDRECClientDraft -Context $context -Auth $auth -Metadata $metadata -Target $target -Signed $signed).id|Should Be 'existing'
        $script:draftPostCalls|Should Be 0
    }
}

Describe 'Resume historical state merge' {
    It 'preserves ClientUploaded true after a later Draft failure' {
        $context=New-TestContext
        $item=[pscustomobject]@{Uploaded=$true;Installed=$true;Verified=$true;DraftId=$null;Published=$false}
        $state=[pscustomobject]@{CurrentSwitched=$true;DatabaseModified=$false;MigrationExecuted=$false;AdminReplaced=$true;CloudDeployed=$true;DraftCreated=$false;Published=$false;Standard=$item;License=$item}
        Merge-DDRECReleaseSessionContext -Context $context -State $state|Out-Null
        $context.ClientUploaded|Should Be $true
    }
    It 'preserves CurrentSwitched and AdminReplaced historical truth' {
        $context=New-TestContext
        $state=[pscustomobject]@{CurrentSwitched=$true;DatabaseModified=$false;MigrationExecuted=$false;AdminReplaced=$true;CloudDeployed=$true;DraftCreated=$false;Published=$false;Standard=$null;License=$null}
        Merge-DDRECReleaseSessionContext -Context $context -State $state|Out-Null
        $context.CurrentSwitched|Should Be $true;$context.AdminReplaced|Should Be $true
    }
    It 'keeps Draft creation after both idempotent client verifications' {
        $text=Get-Content (Join-Path $PSScriptRoot '..\..\scripts\release\release-all.ps1') -Raw
        $text.IndexOf('Invoke-ClientPackageStages -Targets $targets')|Should BeLessThan $text.IndexOf('Invoke-ClientDraftAndPublishStages -Targets $targets')
    }
}
