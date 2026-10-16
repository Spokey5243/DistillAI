param(
    [ValidateSet('Check', 'Serve', 'Stop', 'Mcp', 'Web')]
    [string] $Action = 'Check',
    [string] $HermesSource,
    [string] $HermesPython,
    [string] $DataHome
)

$ErrorActionPreference = 'Stop'
$productSource = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../src'))
$controllerPython = if ($HermesPython) { $HermesPython } else { (Get-Command python -ErrorAction Stop).Source }
if ($Action -in @('Mcp', 'Web') -and -not $HermesPython) {
    $configRoot = if ($DataHome) { $DataHome } elseif ($env:DISTILLAI_HOME) { $env:DISTILLAI_HOME } else { Join-Path $env:USERPROFILE '.distillAI' }
    $launchPath = Join-Path $configRoot 'config/launch.json'
    if (Test-Path -LiteralPath $launchPath) {
        $controllerPython = (Get-Content -LiteralPath $launchPath -Raw | ConvertFrom-Json).hermes_python
    }
}
$mode = @{ Check = 'check'; Serve = 'start'; Stop = 'stop'; Mcp = 'mcp'; Web = 'web' }[$Action]
$pythonCode = 'import sys;sys.path.insert(0,sys.argv.pop(1));from distillai.__main__ import main;main()'
$arguments = @('-I', '-B', '-c', $pythonCode, $productSource, $mode)
if ($HermesSource) { $arguments += @('--hermes-source', $HermesSource) }
if ($HermesPython) { $arguments += @('--hermes-python', $HermesPython) }
if ($DataHome) { $arguments += @('--home', $DataHome) }
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
& $controllerPython @arguments
exit $LASTEXITCODE
