param([Parameter(ValueFromRemainingArguments=$true)][string[]]$CommandArgs)
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv-astra\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Create .venv-astra and install the astra extra. See finance_lab/astra/README.md.'
}
Push-Location $PSScriptRoot
try {
    if (-not $CommandArgs) {
        & $python -m cli.main ftmo
    } else {
        & $python -m finance_lab.astra @CommandArgs
    }
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
