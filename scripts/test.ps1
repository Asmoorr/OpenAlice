param(
    [Parameter(ValueFromRemainingArguments)]
    [string[]] $PytestArguments
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repositoryRoot = [System.IO.Path]::GetFullPath(
    [System.IO.Path]::Combine($PSScriptRoot, '..')
)
$testWorkspace = [System.IO.Path]::Combine($repositoryRoot, '.test-tmp')
$python = [System.IO.Path]::Combine($repositoryRoot, '.venv', 'Scripts', 'python.exe')

Import-Module ([System.IO.Path]::Combine($PSScriptRoot, 'OpenAlice.Testing.psm1')) -Force

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python virtual environment was not found: $python"
}

Remove-TestWorkspace -RepositoryRoot $repositoryRoot -CandidatePath $testWorkspace
$exitCode = 1
try {
    Push-Location $repositoryRoot
    & $python -m pytest @PytestArguments
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
    Remove-TestWorkspace -RepositoryRoot $repositoryRoot -CandidatePath $testWorkspace
}

exit $exitCode
