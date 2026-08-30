function Invoke-MockReleaseFlow {
    param([Parameter(Mandatory)][string]$Root,[string]$FailAt='',[bool]$DeployConfirmed=$true,[bool]$PublishConfirmed=$true)
    $stages=[Collections.Generic.List[string]]::new()
    $state=[ordered]@{Draft=$false;Published=$false;ProductionModified=$false;Stages=$stages}
    $incoming=Join-Path $Root 'incoming';$release=Join-Path $Root 'release';$download=Join-Path $Root 'downloads'
    New-Item -ItemType Directory -Path $incoming,$release,$download -Force|Out-Null
    $installer=Join-Path $Root 'iVRec-1.4.0-standard-Setup.exe'
    [IO.File]::WriteAllBytes($installer,[Text.Encoding]::UTF8.GetBytes('fake-ivrec-installer-build-121'))
    $hash=(Get-FileHash $installer -Algorithm SHA256).Hash
    $stages.Add('preflight');if($FailAt -eq 'preflight'){throw 'mock preflight failed'}
    if(-not $DeployConfirmed){return [pscustomobject]$state}
    $cloudStage=Join-Path $release '.staging-session';New-Item -ItemType Directory $cloudStage|Out-Null
    [IO.File]::WriteAllText((Join-Path $cloudStage 'commit.txt'),'a'*40)
    $cloudFinal=Join-Path $release '1.4.0-aaaaaaa';Move-Item $cloudStage $cloudFinal
    $state.ProductionModified=$true;$stages.Add('deploy');if($FailAt -eq 'deploy'){throw 'mock deploy failed'}
    $stages.Add('health');if($FailAt -eq 'health'){throw 'mock health failed'}
    $part=Join-Path $incoming 'client.part';Copy-Item $installer $part
    if($FailAt -eq 'upload'){throw 'mock upload disconnected'}
    if((Get-FileHash $part -Algorithm SHA256).Hash -ne $hash){throw 'mock SHA mismatch'}
    $targetDir=Join-Path $download 'stable\standard\1.4.0\121';New-Item -ItemType Directory $targetDir -Force|Out-Null
    $staged=Join-Path $targetDir '.installer.part';Move-Item $part $staged
    $final=Join-Path $targetDir 'iVRec-1.4.0-standard-Setup.exe';Move-Item $staged $final
    $stages.Add('upload');$stages.Add('download');$stages.Add('signature')
    if($FailAt -eq 'signature'){throw 'mock signature invalid'}
    $draftPath=Join-Path $Root 'client-release-draft.json'
    @{status='draft';product='iVRec';sha256=$hash;buildNumber=121}|ConvertTo-Json|Set-Content $draftPath -Encoding utf8NoBOM
    $state.Draft=$true;$stages.Add('draft');if($FailAt -eq 'draft'){throw 'mock Draft API failed'}
    if($PublishConfirmed){$state.Published=$true;$stages.Add('published')}
    return [pscustomobject]$state
}

Describe 'iVRec mocked complete release flow' {
    BeforeEach { $script:mockRoot=Join-Path ([IO.Path]::GetTempPath()) ('ddrec-release-'+[guid]::NewGuid().ToString('N')) }
    AfterEach { if(Test-Path $script:mockRoot){Remove-Item -LiteralPath $script:mockRoot -Recurse -Force} }

    It 'runs preflight through Published with Published last' {
        $result=Invoke-MockReleaseFlow -Root $script:mockRoot
        $result.Published|Should Be $true
        $result.Stages[-1]|Should Be 'published'
        (Test-Path (Join-Path $script:mockRoot 'downloads\stable\standard\1.4.0\121\iVRec-1.4.0-standard-Setup.exe'))|Should Be $true
    }
    It 'an upload disconnect leaves no final file and no Draft or Published' {
        $threw=$false
        try{Invoke-MockReleaseFlow -Root $script:mockRoot -FailAt upload|Out-Null}catch{$threw=$true}
        $threw|Should Be $true
        (Test-Path (Join-Path $script:mockRoot 'downloads\stable\standard\1.4.0\121\iVRec-1.4.0-standard-Setup.exe'))|Should Be $false
        (Test-Path (Join-Path $script:mockRoot 'client-release-draft.json'))|Should Be $false
    }
    It 'can keep a verified release as Draft without Published' {
        $result=Invoke-MockReleaseFlow -Root $script:mockRoot -PublishConfirmed $false
        $result.Draft|Should Be $true
        $result.Published|Should Be $false
        $result.Stages[-1]|Should Be 'draft'
    }
    It 'cancelling DEPLOY causes no production modification' {
        $result=Invoke-MockReleaseFlow -Root $script:mockRoot -DeployConfirmed $false
        $result.ProductionModified|Should Be $false
        $result.Draft|Should Be $false
        $result.Published|Should Be $false
    }
}
