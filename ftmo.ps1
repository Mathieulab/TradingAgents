$ErrorActionPreference = 'Stop'
$ftmoPython = Join-Path $PSScriptRoot '.venv-ftmo\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $ftmoPython)) {
    throw 'Create .venv-ftmo and install finance_lab/ftmo/requirements.txt first. See finance_lab/ftmo/README.md.'
}
Push-Location -LiteralPath $PSScriptRoot
try {
    & $ftmoPython -m finance_lab.ftmo @args
    $ftmoExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $ftmoExitCode
