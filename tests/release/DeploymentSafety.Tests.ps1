$modulePath = Join-Path $PSScriptRoot '..\..\scripts\release\DDREC.Release.psm1'
Import-Module $modulePath -Force
$auditorPath = Join-Path $PSScriptRoot '..\..\deploy\production-release\audit-pending-migrations.py'

function New-MigrationFile {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$Revision,
        [AllowEmptyString()][string]$DownRevision,
        [string]$Upgrade = '    op.add_column("items", sa.Column("value", sa.String()))',
        [string]$Downgrade = '    op.drop_column("items", "value")'
    )
    New-Item -ItemType Directory -Path $Root -Force | Out-Null
    $down = if ([string]::IsNullOrWhiteSpace($DownRevision)) {'None'} else {"`"$DownRevision`""}
    $text = @"
revision = "$Revision"
down_revision = $down

def upgrade():
$Upgrade

def downgrade():
$Downgrade
"@
    [IO.File]::WriteAllText((Join-Path $Root "$Revision.py"), $text, [Text.UTF8Encoding]::new($false))
}

function New-MigrationCloudRoot {
    param([Parameter(Mandatory)][string]$Root)
    $versions = Join-Path $Root 'license-server\alembic\versions'
    New-MigrationFile -Root $versions -Revision 0001 -DownRevision '' -Upgrade '    op.create_table("items")' -Downgrade '    op.drop_table("items")'
    New-MigrationFile -Root $versions -Revision 0002 -DownRevision 0001 -Upgrade '    op.add_column("items", sa.Column("name", sa.String()))'
    return $versions
}

function Invoke-PendingAuditFixture {
    param([Parameter(Mandatory)][string]$Versions,[Parameter(Mandatory)][string]$Current,[Parameter(Mandatory)][string]$Head)
    $output = @(& python $auditorPath --versions $Versions --current $Current --head $Head 2>&1)
    return [pscustomobject]@{ExitCode=$LASTEXITCODE;Output=($output -join "`n")}
}

Describe 'pending-only migration safety' {
    BeforeEach {
        $script:cloudRoot = Join-Path ([IO.Path]::GetTempPath()) ('ddrec-migration-audit-' + [guid]::NewGuid().ToString('N'))
        $script:versions = New-MigrationCloudRoot -Root $script:cloudRoot
    }
    AfterEach {
        if (Test-Path -LiteralPath $script:cloudRoot) { Remove-Item -LiteralPath $script:cloudRoot -Recurse -Force }
    }

    It 'does not block pending zero when historical downgrade contains DROP' {
        $plan = Get-DDRECLocalMigrationPlan -CloudRoot $script:cloudRoot -CurrentRevision 0002
        @($plan.Pending).Count | Should Be 0
        $plan.Destructive | Should Be $false
        $audit = Invoke-PendingAuditFixture -Versions $script:versions -Current 0002 -Head 0002
        $audit.ExitCode | Should Be 0
        $audit.Output | Should Match 'pending=0'
    }

    It 'allows a safe pending migration' {
        New-MigrationFile -Root $script:versions -Revision 0003 -DownRevision 0002 -Upgrade '    op.add_column("items", sa.Column("safe", sa.String()))'
        $plan = Get-DDRECLocalMigrationPlan -CloudRoot $script:cloudRoot -CurrentRevision 0002
        @($plan.Pending).Count | Should Be 1
        $plan.Destructive | Should Be $false
        (Invoke-PendingAuditFixture -Versions $script:versions -Current 0002 -Head 0003).ExitCode | Should Be 0
    }

    It 'blocks DROP TABLE in a pending upgrade' {
        New-MigrationFile -Root $script:versions -Revision 0003 -DownRevision 0002 -Upgrade '    op.drop_table("items")'
        $plan = Get-DDRECLocalMigrationPlan -CloudRoot $script:cloudRoot -CurrentRevision 0002
        $plan.Destructive | Should Be $true
        $audit = Invoke-PendingAuditFixture -Versions $script:versions -Current 0002 -Head 0003
        $audit.ExitCode | Should Be 50
        $audit.Output | Should Match 'rule=DROP_TABLE'
    }

    It 'blocks DROP COLUMN in a pending upgrade' {
        New-MigrationFile -Root $script:versions -Revision 0003 -DownRevision 0002 -Upgrade '    op.drop_column("items", "name")'
        $audit = Invoke-PendingAuditFixture -Versions $script:versions -Current 0002 -Head 0003
        $audit.ExitCode | Should Be 50
        $audit.Output | Should Match 'rule=DROP_COLUMN'
    }

    It 'ignores historical DROP while auditing a newer safe pending revision' {
        New-MigrationFile -Root $script:versions -Revision 0003 -DownRevision 0002 -Upgrade '    op.create_table("new_items")' -Downgrade '    op.drop_table("new_items")'
        $audit = Invoke-PendingAuditFixture -Versions $script:versions -Current 0002 -Head 0003
        $audit.ExitCode | Should Be 0
        $audit.Output | Should Match 'pendingRevision=0003'
    }

    It 'server executor skips destructive audit when current equals head' {
        $deploy = Get-Content -LiteralPath (Join-Path $PSScriptRoot '..\..\deploy\production-release\deploy-release.sh') -Raw
        $equalBranch = $deploy.IndexOf('pendingMigration=0 current=${db_current} head=${db_head}; destructive audit skipped')
        $auditCall = $deploy.IndexOf('audit-pending-migrations.py')
        ($auditCall -ge 0 -and $equalBranch -gt $auditCall) | Should Be $true
        $deploy | Should Match 'if \[\[ "\$\{db_current\}" != "\$\{db_head\}" \]\]'
    }
}

Describe 'SSH transport and remote command classification' {
    BeforeEach {
        $config=[pscustomobject]@{SshAttempts=3;SshRetrySeconds=0;ServerHost='fixture'}
        $script:context=New-DDRECReleaseContext -WorkspaceRoot $TestDrive -Config $config -SessionId ssh-fixture
    }

    It 'retries a real SSH transport failure' {
        $script:calls=0
        $message=''
        try {
            Invoke-DDRECSsh -Context $script:context -Command status -NativeInvoker { param($Attempt) $script:calls++; [pscustomobject]@{ExitCode=255;Output='connection refused'} } | Out-Null
        } catch { $message=$_.Exception.Message }
        $script:calls | Should Be 3
        $message | Should Match 'SSH transport failure'
    }

    It 'reports a remote command failure once without retrying' {
        $script:calls=0
        $message=''
        try {
            Invoke-DDRECSsh -Context $script:context -Command deploy -NativeInvoker { param($Attempt) $script:calls++; [pscustomobject]@{ExitCode=50;Output='ERROR: destructive migration pattern found'} } | Out-Null
        } catch { $message=$_.Exception.Message }
        $script:calls | Should Be 1
        $message | Should Match '远端发布执行器失败'
        $message | Should Match 'RemoteExitCode=50'
        $message | Should Match 'destructive migration pattern found'
        $message | Should Not Match 'SSH 连续'
    }
}

Describe 'detailed production modification state' {
    It 'records upload-only preparation without claiming app or database changes' {
        $context=New-DDRECReleaseContext -WorkspaceRoot $TestDrive -Config ([pscustomobject]@{}) -SessionId state-fixture
        $output='DDREC_STATE Uploaded=true BackupCreated=false ReleaseInstalled=false ContainerRecreated=false CurrentSwitched=false DatabaseModified=false MigrationExecuted=false AdminReplaced=false RollbackAttempted=false RollbackHealthy=false'
        Update-DDRECDeploymentState -Context $context -Output $output | Out-Null
        $context.ProductionModified | Should Be $true
        $context.PreparedProductionArtifacts | Should Be $true
        $context.ProductionApplicationModified | Should Be $false
        $context.DatabaseModified | Should Be $false
        $context.MigrationExecuted | Should Be $false
        $context.CurrentSwitched | Should Be $false
    }

    It 'includes detailed compatible fields in failure reports' {
        $context=New-DDRECReleaseContext -WorkspaceRoot $TestDrive -Config ([pscustomobject]@{}) -SessionId report-fixture
        Update-DDRECDeploymentState -Context $context -Output 'DDREC_STATE Uploaded=true BackupCreated=true ReleaseInstalled=true ContainerRecreated=false CurrentSwitched=false DatabaseModified=false MigrationExecuted=false AdminReplaced=false RollbackAttempted=false RollbackHealthy=false' | Out-Null
        $report=Get-DDRECFailureReport -Context $context -Stage deploy -ErrorRecord ([Management.Automation.ErrorRecord]::new([Exception]::new('fixture'),'fixture',[Management.Automation.ErrorCategory]::InvalidOperation,$null))
        $report.ProductionModified | Should Be $true
        $report.Uploaded | Should Be $true
        $report.BackupCreated | Should Be $true
        $report.ReleaseInstalled | Should Be $true
        $report.ContainerRecreated | Should Be $false
        $report.CurrentSwitched | Should Be $false
        $report.DatabaseModified | Should Be $false
    }

    It 'does not treat container recreation as verified deployment identity' {
        $context=New-DDRECReleaseContext -WorkspaceRoot $TestDrive -Config ([pscustomobject]@{}) -SessionId identity-fixture
        Update-DDRECDeploymentState -Context $context -Output 'DDREC_STATE Uploaded=true BackupCreated=true ReleaseInstalled=true ContainerRecreated=true DeploymentIdentityVerified=false DeploymentSucceeded=false CurrentSwitched=true DatabaseModified=false MigrationExecuted=false AdminReplaced=true RollbackAttempted=false RollbackHealthy=false' | Out-Null
        $context.ContainerRecreated | Should Be $true
        $context.DeploymentIdentityVerified | Should Be $false
        $context.DeploymentSucceeded | Should Be $false
        $report=Get-DDRECFailureReport -Context $context -Stage deploy -ErrorRecord ([Management.Automation.ErrorRecord]::new([Exception]::new('identity mismatch'),'fixture',[Management.Automation.ErrorCategory]::InvalidOperation,$null))
        $report.DeploymentIdentityVerified | Should Be $false
        $report.DeploymentSucceeded | Should Be $false
    }
}
