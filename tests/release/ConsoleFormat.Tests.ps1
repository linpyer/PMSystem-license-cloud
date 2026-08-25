$ErrorActionPreference='Stop'
$cloudRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$modulePath=Join-Path $cloudRoot 'scripts\release\DDREC.Release.psm1'
$releasePath=Join-Path $cloudRoot 'scripts\release\release-all.ps1'
Import-Module $modulePath -Force

function New-ConsoleMetadata {
    param([string]$Edition='standard',[string]$Environment='none')
    $name=if($Edition -eq 'standard'){'DDREC-1.3.0-standard-Setup.exe'}else{'DDREC-1.3.0-license-Setup.exe'}
    $metadata=[pscustomobject]@{
        Path="C:\artifacts\$name";FileName=$name;FileSize=157521087;SHA256=('A'*64)
        Version='1.3.0';BuildNumber=102;GitCommit='79b17402aea1f2f97f9188c0aaad8d2c4f318208'
        Edition=$Edition;Environment=$Environment;UpdaterVersion='1.2.0'
    }
    $metadata.PSObject.TypeNames.Insert(0,'DDREC.PackageMetadata')
    return $metadata
}

function Get-RenderedPackageLines {
    param($Metadata)
    $lines=[Collections.Generic.List[string]]::new()
    Show-DDRECPackageMetadata -Metadata $Metadata -OutputWriter {param($line)[void]$lines.Add([string]$line)}
    return @($lines)
}

Describe 'DDREC release console formatting' {
    BeforeAll {
        $script:releaseText=Get-Content -LiteralPath $releasePath -Raw
        $script:moduleText=Get-Content -LiteralPath $modulePath -Raw
    }

    It 'renders Standard metadata completely in a fixed order before confirmation' {
        $lines=Get-RenderedPackageLines (New-ConsoleMetadata)
        $lines.Count|Should Be 9
        $lines[0]|Should Be 'FileName       : DDREC-1.3.0-standard-Setup.exe'
        $lines[1]|Should Be 'Version        : 1.3.0'
        $lines[2]|Should Be 'BuildNumber    : 102'
        $lines[3]|Should Be 'GitCommit      : 79b17402aea1f2f97f9188c0aaad8d2c4f318208'
        $lines[4]|Should Be 'Edition        : standard'
        $lines[5]|Should Be 'Environment    : none'
        $lines[8]|Should Be ('SHA256         : '+('A'*64))
    }

    It 'renders License-Production metadata completely in the same fixed order' {
        $lines=Get-RenderedPackageLines (New-ConsoleMetadata -Edition license -Environment production)
        $lines[0]|Should Be 'FileName       : DDREC-1.3.0-license-Setup.exe'
        $lines[2]|Should Be 'BuildNumber    : 102'
        $lines[3]|Should Be 'GitCommit      : 79b17402aea1f2f97f9188c0aaad8d2c4f318208'
        $lines[4]|Should Be 'Edition        : license'
        $lines[5]|Should Be 'Environment    : production'
        $lines[6]|Should Be 'UpdaterVersion : 1.2.0'
    }

    It 'does not return PackageMetadata to the deferred formatting pipeline' {
        $definition=(Get-Command Show-DDRECPackageMetadata).Definition
        $definition|Should Not Match 'Format-List|Format-Table|Write-Output'
        @((Show-DDRECPackageMetadata -Metadata (New-ConsoleMetadata))).Count|Should Be 0
    }

    It 'writes isolated child stdout synchronously instead of returning it for formatting' {
        $definition=(Get-Command Invoke-DDRECConsoleTask).Definition
        $definition|Should Match '\[Console\]::Out\.WriteLine\(\$line\)'
        $definition|Should Match '\[Console\]::Out\.Flush\(\)'
        $definition|Should Not Match 'Write-Output \$_'
    }

    It 'preserves metadata then blank line then prompt through the isolated console task' {
        $child=Join-Path $TestDrive 'metadata-order-child.ps1'
        $runner=Join-Path $TestDrive 'metadata-order-runner.ps1'
        @"
Import-Module '$($modulePath.Replace("'","''"))' -Force
`$metadata=[pscustomobject]@{Path='C:\fixture.exe';FileName='DDREC-1.3.0-license-Setup.exe';FileSize=157521087;SHA256=('A'*64);Version='1.3.0';BuildNumber=102;GitCommit='79b17402aea1f2f97f9188c0aaad8d2c4f318208';Edition='license';Environment='production';UpdaterVersion='1.2.0'}
`$metadata.PSObject.TypeNames.Insert(0,'DDREC.PackageMetadata')
Show-DDRECPackageMetadata -Metadata `$metadata
[Console]::Out.WriteLine('')
[Console]::Out.WriteLine('[Y] 使用 / [N] 手动选择其它安装包: Y')
exit 0
"@|Set-Content -LiteralPath $child -Encoding UTF8
        @"
Import-Module '$($modulePath.Replace("'","''"))' -Force
`$code=99
Invoke-DDRECConsoleTask -PwshPath '$(Join-Path $PSHOME 'pwsh.exe')' -Arguments @('-NoLogo','-NoProfile','-File','$($child.Replace("'","''"))') -ExitCode ([ref]`$code)
[Console]::Out.WriteLine("CHILD-EXIT=`$code")
"@|Set-Content -LiteralPath $runner -Encoding UTF8
        $text=(@(& (Join-Path $PSHOME 'pwsh.exe') -NoLogo -NoProfile -File $runner 2>&1)|ForEach-Object{[string]$_}) -join "`n"
        $sha=$text.IndexOf('SHA256         : '+('A'*64))
        $prompt=$text.IndexOf('[Y] 使用 / [N] 手动选择其它安装包: Y')
        $sha|Should BeGreaterThan -1
        $sha|Should BeLessThan $prompt
        $text.Substring($sha,$prompt-$sha)|Should Match "A{64}\r?\n\r?\n$"
        $text|Should Match 'CHILD-EXIT=0'
    }

    It 'places the package summary and blank line before the Y N prompt' {
        $select=[regex]::Match($script:releaseText,'(?s)function Select-Installer.*?(?=function Show-ProductionStatus)').Value
        $select.IndexOf('Show-DDRECPackageMetadata -Metadata $metadata')|Should BeLessThan $select.IndexOf("Read-Host '[Y] 使用 / [N] 手动选择其它安装包'")
        $between=$select.Substring($select.IndexOf('Show-DDRECPackageMetadata -Metadata $metadata'))
        $between.Substring(0,$between.IndexOf("Read-Host '[Y] 使用 / [N] 手动选择其它安装包'"))|Should Match "Write-Host ''"
    }

    It 'prints every upload mode option before Read-Host' {
        $menu=[regex]::Match($script:releaseText,'(?s)function Select-ClientUploadMode.*?(?=function Select-Installer)').Value
        $prompt=$menu.IndexOf("Read-Host '请选择 [1/2/0]'")
        $menu.IndexOf('[1] 自动上传')|Should BeLessThan $prompt
        $menu.IndexOf('[2] 手动上传')|Should BeLessThan $prompt
        $menu.IndexOf('[0] 取消')|Should BeLessThan $prompt
        $menu.IndexOf('Sync-DDRECConsoleOutput')|Should BeLessThan $prompt
    }

    It 'prints every multi-Draft publish option before Read-Host' {
        $publish=[regex]::Match($script:releaseText,'(?s)function Invoke-ClientDraftAndPublishStages.*?(?=function Get-ResumeTargets)').Value
        $prompt=$publish.IndexOf("Read-Host '请选择 [0-4]'")
        $publish.IndexOf("Write-Host '[1] Standard'")|Should BeLessThan $prompt
        $publish.IndexOf("Write-Host '[2] License-Production'")|Should BeLessThan $prompt
        $publish.IndexOf("Write-Host '[3] 两个'")|Should BeLessThan $prompt
        $publish.IndexOf("Write-Host '[4] 全部保持 Draft'")|Should BeLessThan $prompt
        $publish.IndexOf("Write-Host '[0] 退出'")|Should BeLessThan $prompt
    }

    It 'keeps DEPLOY and exact PUBLISH confirmations unchanged' {
        $script:releaseText|Should Match "Read-Host '请输入 DEPLOY 才允许生产写操作'\) -cne 'DEPLOY'"
        $script:releaseText|Should Match "Read-Host '请输入 PUBLISH 二次确认'\) -ceq 'PUBLISH'"
    }

    It 'keeps Draft as the default safe publish outcome' {
        $script:releaseText|Should Match '默认保持 Draft。只有先选择目标并再次输入 PUBLISH 才会发布。'
        $script:releaseText|Should Match "default\{@\(\)\}"
        $script:releaseText|Should Match '所有目标保持 Draft；没有 Published。'
    }

    It 'keeps all PackageMetadata authenticity fields and SHA validation' {
        $script:moduleText|Should Match "'Path','FileName','FileSize','SHA256','Version','BuildNumber','GitCommit','Edition','Environment','UpdaterVersion'"
        $script:moduleText|Should Match '安装包 SHA256 与构建元数据不一致'
        $script:moduleText|Should Match '安装包 GitCommit 与当前 client HEAD 不一致'
    }

    It 'keeps Dry Run read-only and production confirmations after its early return' {
        $script:releaseText|Should Match 'PASS：未上传、未备份、未部署、未 Migration、未修改数据库、未创建 Draft、未 Published、未 reload。'
        $dry=$script:releaseText.IndexOf("if(`$dryRun)")
        $deploy=$script:releaseText.IndexOf("Read-Host '请输入 DEPLOY 才允许生产写操作'")
        $dry|Should BeLessThan $deploy
    }

    It 'keeps Resume pinned to its session without Cloud redeploy' {
        $script:releaseText|Should Match 'Resume 仅从客户端上传/Draft 阶段继续；不会重新构建、上传或部署 Cloud。'
        $script:releaseText|Should Match 'ExpectedCommit \(\[string\]\$State\.ClientGitCommit\)'
    }

    It 'keeps child exit-code propagation and Enter return to the main menu' {
        $script:releaseText|Should Match '-ExitCode \(\[ref\]\$taskExitCode\)'
        $script:releaseText|Should Match "Read-Host '按 Enter 返回主菜单'"
        $script:moduleText|Should Match '\$ExitCode\.Value=\[int\]\$LASTEXITCODE'
    }

    It 'keeps the main menu summary and all choices before its prompt' {
        $menu=[regex]::Match($script:releaseText,'(?s)function Show-DDRECReleaseMenu.*?(?=function Read-ReleaseMenuMode)').Value
        $menu|Should Match 'Client:'
        $menu|Should Match 'Cloud:'
        $menu|Should Match 'Production:'
        $menu|Should Match '\[9\] 继续未完成发布 / Resume Release'
        $menu|Should Match '\[0\] 退出'
    }
}
