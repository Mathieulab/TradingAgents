param([Parameter(ValueFromRemainingArguments=$true)][string[]]$CommandArgs)
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv-astra\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Create .venv-astra and install the astra extra. See finance_lab/astra/README.md.'
}
Push-Location $PSScriptRoot
try {
    & $python -m cli.main @CommandArgs
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
