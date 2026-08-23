[CmdletBinding()]
param(
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$Version,

    [switch]$AllowDirty
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($AllowDirty) {
    throw 'Production cloud releases no longer allow dirty worktrees.'
}

$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$buildScript = Join-Path $projectRoot 'scripts\build_cloud_release.ps1'
if (-not (Test-Path -LiteralPath $buildScript -PathType Leaf)) {
    throw "Unified cloud build script not found: $buildScript"
}

$arguments = @{
    Environment = 'production'
    Service = 'all'
}
if ($PSBoundParameters.ContainsKey('Version')) {
    $arguments.Version = $Version
}

& $buildScript @arguments
