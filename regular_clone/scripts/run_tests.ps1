$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $pythonExe)) {
    throw "Python venv non trovato: $pythonExe"
}

Push-Location $repoRoot
try {
    & $pythonExe -m unittest discover -s tests -p "test_*.py" -v
}
finally {
    Pop-Location
}

