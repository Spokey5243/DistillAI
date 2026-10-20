param(
    [ValidateSet('Check', 'Serve', 'Stop', 'Mcp', 'Web')]
    [string] $Action = 'Check',
    [string] $HermesSource,
    [string] $HermesPython,
    [string] $DataHome
)

$ErrorActionPreference = 'Stop'
$productSource = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../src'))
$controllerPython = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../.venv/Scripts/python.exe'))
if (-not (Test-Path -LiteralPath $controllerPython -PathType Leaf)) {
    throw 'Prepare the product environment first: uv sync --locked'
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
