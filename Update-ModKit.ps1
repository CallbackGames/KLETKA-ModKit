# Copyright Callback LLP. All Rights Reserved.
[CmdletBinding()]
param(
    [string]$Directory = (Join-Path $PSScriptRoot 'KLETKA_ModKit'),
    [ValidateSet('BlueprintBinary', 'NativeSdk')][string]$Kind = 'BlueprintBinary',
    [string]$Channel = 'public',
    [string]$Tag,
    [string]$EngineRoot,
    [string]$PythonPath,
    [switch]$Rollback,
    [switch]$Recover
)
$ErrorActionPreference = 'Stop'
if (-not $PythonPath -and -not $EngineRoot) {
    $key = Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\EpicGames\Unreal Engine\5.8' -ErrorAction SilentlyContinue
    if ($key) { $EngineRoot = $key.InstalledDirectory }
}
if (-not $PythonPath -and $EngineRoot) {
    $PythonPath = Join-Path $EngineRoot 'Engine\Binaries\ThirdParty\Python3\Win64\python.exe'
}
if (-not $PythonPath) {
    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($command -and $command.Source -notlike '*WindowsApps*') { $PythonPath = $command.Source }
}
if (-not $PythonPath -or -not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw 'Pass -EngineRoot pointing to your UE 5.8 folder, or -PythonPath pointing to Python 3.11+.'
}
& $PythonPath -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ required"'
if ($LASTEXITCODE -ne 0) { throw 'Unsupported Python runtime.' }
$arguments = @('-X', 'utf8', (Join-Path $PSScriptRoot 'modkit_update.py'),
    '--directory', $Directory, '--kind', $Kind, '--channel', $Channel)
if ($Tag) { $arguments += @('--tag', $Tag) }
if ($Rollback) { $arguments += '--rollback' }
if ($Recover) { $arguments += '--recover' }
& $PythonPath @arguments
if ($LASTEXITCODE -ne 0) { throw 'ModKit update stopped. Read the conflict/error above; do not delete your mods.' }
