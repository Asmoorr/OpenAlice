Set-StrictMode -Version Latest

function Assert-SafeTestWorkspacePath {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string] $RepositoryRoot,

        [Parameter(Mandatory)]
        [string] $CandidatePath
    )

    $resolvedRoot = [System.IO.Path]::GetFullPath($RepositoryRoot)
    $resolvedCandidate = [System.IO.Path]::GetFullPath($CandidatePath)
    $expectedCandidate = [System.IO.Path]::GetFullPath(
        [System.IO.Path]::Combine($resolvedRoot, '.test-tmp')
    )

    if (-not [string]::Equals(
            $resolvedCandidate,
            $expectedCandidate,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
        throw "Refusing to clean a path outside the repository test workspace: $resolvedCandidate"
    }

    if (Test-Path -LiteralPath $resolvedCandidate) {
        $item = Get-Item -LiteralPath $resolvedCandidate -Force
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Refusing to clean a reparse-point test workspace: $resolvedCandidate"
        }
    }

    return $resolvedCandidate
}

function Remove-TestWorkspace {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string] $RepositoryRoot,

        [Parameter(Mandatory)]
        [string] $CandidatePath
    )

    $safePath = Assert-SafeTestWorkspacePath `
        -RepositoryRoot $RepositoryRoot `
        -CandidatePath $CandidatePath
    if (Test-Path -LiteralPath $safePath) {
        Remove-Item -LiteralPath $safePath -Recurse -Force
    }
}

Export-ModuleMember -Function Assert-SafeTestWorkspacePath, Remove-TestWorkspace
