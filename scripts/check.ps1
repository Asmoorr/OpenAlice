$ErrorActionPreference = 'Stop'
$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$python = Join-Path $repositoryRoot '.venv/Scripts/python.exe'
Push-Location $repositoryRoot
try {
    & $python -m ruff format --check openalice tests
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
    & $python -m ruff check openalice tests
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
    & $python -m mypy openalice
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
    & (Join-Path $PSScriptRoot 'test.ps1') -PytestArguments @('-q', '--cov=openalice', '--cov-branch', '--cov-report=term:skip-covered')
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
