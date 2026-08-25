$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$scriptPath = Join-Path $repoRoot 'scripts\test_all.ps1'

Describe 'DDREC unified test harness' {
    It 'exists in the Cloud scripts directory' {
        (Test-Path -LiteralPath $scriptPath -PathType Leaf) | Should Be $true
    }

    It 'declares every required test domain in a stable order' {
        $plan = @(& $scriptPath -PlanOnly)
        ($plan.Name -join '|') | Should Be 'Client|Cloud Python|License Server|Pester|Admin Vitest|Admin TypeCheck|Admin E2E'
    }

    It 'runs Client and Cloud Python from different working directories' {
        $plan = @(& $scriptPath -PlanOnly)
        $plan[0].WorkingDirectory | Should Not Be $plan[1].WorkingDirectory
    }

    It 'runs license-server pytest from the license-server directory' {
        $plan = @(& $scriptPath -PlanOnly)
        $license = $plan | Where-Object Name -eq 'License Server'
        (Split-Path -Leaf $license.WorkingDirectory) | Should Be 'license-server'
    }

    It 'does not combine Cloud root and license-server pytest paths' {
        $plan = @(& $scriptPath -PlanOnly)
        $cloud = $plan | Where-Object Name -eq 'Cloud Python'
        $server = $plan | Where-Object Name -eq 'License Server'
        ($cloud.Arguments -match 'license-server') | Should Be $false
        ($server.Arguments -match 'license-server/tests') | Should Be $false
    }

    It 'runs every Cloud Pester suite including build guards' {
        $plan = @(& $scriptPath -PlanOnly)
        $pester = $plan | Where-Object Name -eq 'Pester'
        $pester.Arguments | Should Be 'tests'
    }

    It 'contains an explicit stale PMSystem editable-path guard' {
        (Get-Content -LiteralPath $scriptPath -Raw) | Should Match 'PMSystem'
    }
}
