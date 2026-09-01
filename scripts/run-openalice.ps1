$ErrorActionPreference = "Stop"
$projectDirectory = "C:\Programming\2026\OpenAlice"
$environmentFile = Join-Path $projectDirectory ".env"
$logDirectory = Join-Path $projectDirectory "logs"
$logFile = Join-Path $logDirectory "openalice.log"

Set-Location -LiteralPath $projectDirectory
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

if (-not (Test-Path -LiteralPath $environmentFile)) {
    throw "Missing environment file: $environmentFile"
}

foreach ($line in Get-Content -LiteralPath $environmentFile) {
    $trimmed = $line.Trim()
    if (-not $trimmed -or $trimmed.StartsWith("#")) {
        continue
    }
    $separator = $trimmed.IndexOf("=")
    if ($separator -lt 1) {
        continue
    }
    $name = $trimmed.Substring(0, $separator).Trim()
    $value = $trimmed.Substring($separator + 1).Trim().Trim('"').Trim("'")
    [Environment]::SetEnvironmentVariable($name, $value, "Process")
}

"$(Get-Date -Format o) Starting OpenAlice" | Add-Content -LiteralPath $logFile
$pythonExecutable = Join-Path $projectDirectory ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw "Missing virtual environment: $pythonExecutable"
}
& $pythonExecutable -m uvicorn openalice.app:create_app --factory --host 127.0.0.1 --port 8000 *>> $logFile
