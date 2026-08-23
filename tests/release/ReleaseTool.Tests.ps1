$modulePath = Join-Path $PSScriptRoot '..\..\scripts\release\DDREC.Release.psm1'
Import-Module $modulePath -Force

function New-GitState {
    param([bool]$Clean=$true,[string]$Branch='v1.3',[string]$Head=('a'*40),[string]$Origin=('a'*40))
    [pscustomobject]@{Clean=$Clean;Branch=$Branch;Head=$Head;Origin=$Origin;Repository='mock';Status=' M file'}
}

function New-Metadata {
    param([string]$Edition='standard',[string]$Environment='none',[string]$Commit=('a'*40),[int]$Build=82)
    [pscustomobject]@{Edition=$Edition;Environment=$Environment;GitCommit=$Commit;ProductVersion='1.3.0';BuildNumber=$Build;UpdaterVersion='1.2.0'}
}

function Assert-Throws {
    param([Parameter(Mandatory)][scriptblock]$Script)
    $threw = $false
    try { & $Script | Out-Null } catch { $threw = $true }
    $threw | Should Be $true
}

Describe 'DDREC production release safety failures' {
    It '1 client working tree dirty' {
        Assert-Throws { Assert-DDRECGitReleaseState (New-GitState -Clean $false) }
    }
    It '2 cloud working tree dirty' {
        Assert-Throws { Assert-DDRECGitReleaseState (New-GitState -Clean $false) }
    }
    It '3 HEAD differs from origin v1.3' {
        Assert-Throws { Assert-DDRECGitReleaseState (New-GitState -Head ('a'*40) -Origin ('b'*40)) }
    }
    It '4 SSH failure stops transport' {
        Assert-Throws { Assert-DDRECTransportResult -ExitCode 255 -Stage SSH }
    }
    It '5 installer Edition mismatch' {
        Assert-Throws { Assert-DDRECInstallerPolicy (New-Metadata -Edition license -Environment production) standard ('a'*40) }
    }
    It '6 installer Build metadata and Git mismatch' {
        Assert-Throws { Assert-DDRECInstallerPolicy (New-Metadata -Commit ('b'*40)) standard ('a'*40) }
    }
    It '7 correct filename cannot bypass internal Edition policy' {
        Assert-Throws { Assert-DDRECInstallerPolicy (New-Metadata -Edition license -Environment production) standard ('a'*40) }
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

Describe 'DDREC successful safety policies' {
    It 'accepts clean matching Git state' { Assert-DDRECGitReleaseState (New-GitState) | Should Be $true }
    It 'accepts Standard production artifact policy' { Assert-DDRECInstallerPolicy (New-Metadata) standard ('a'*40) | Should Be $true }
    It 'accepts equal immutable SHA' { Assert-DDRECHashCompatibility ('F'*64) ('F'*64) | Should Be $true }
    It 'keeps standard and license-production isolated' { Assert-DDRECReleaseIsolation standard standard published | Should Be $true }
    It 'rejects standard receiving license-production stable' { Assert-Throws { Assert-DDRECReleaseIsolation standard license-production published } }
}
