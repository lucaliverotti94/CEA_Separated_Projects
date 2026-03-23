param(
    [ValidateSet("controller", "core")]
    [string]$Entrypoint = "controller",

    [ValidateSet("max_yield", "max_quality", "max_yield_energy", "max_quality_energy")]
    [string]$Mode = "max_yield",

    [int]$Port = 8091,
    [int]$DurationSamples = 80,
    [int]$DurationSec = 90,
    [double]$TickSeconds = 0.5,
    [double]$WatchdogTimeoutS = 2.0,
    [double]$YieldCapAnnualKg = 80.0,
    [double]$FarmActiveAreaM2 = 1.0,
    [string]$OutJsonl = "control_output_fault_hil.jsonl",
    [string]$StoreDb = "cea_timeseries.db",
    [string]$DbPath = ""
)

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
$serverPy = Join-Path $repoRoot "scripts\faulty_sensor_http_server.py"
$controllerPy = if ($Entrypoint -eq "core") {
    Join-Path $repoRoot "core\realtime_io.py"
} else {
    Join-Path $repoRoot "controller_literature_realtime.py"
}
$prebuiltProfile = Join-Path $repoRoot "literature_best_profile_runtime.json"

if (!(Test-Path $pythonExe)) { $pythonExe = "python" }
if (!(Test-Path $serverPy)) { throw "Server fault injection non trovato: $serverPy" }
if (!(Test-Path $controllerPy)) { throw "Entrypoint non trovato: $controllerPy" }
if ($DbPath -and $DbPath.Trim().Length -gt 0) { $StoreDb = $DbPath }
if ($DurationSec -gt 0 -and $TickSeconds -gt 0) {
    $maxByTime = [Math]::Max(1, [int][Math]::Ceiling($DurationSec / $TickSeconds))
    if ($DurationSamples -gt $maxByTime) { $DurationSamples = $maxByTime }
}

$endpoint = "http://127.0.0.1:$Port/sensors/latest"
$logDir = Join-Path $repoRoot "logs"
if (!(Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$serverStdout = Join-Path $logDir "fault_injector_stdout.log"
$serverStderr = Join-Path $logDir "fault_injector_stderr.log"
if (Test-Path $OutJsonl) { Remove-Item $OutJsonl -Force }

Write-Host "Starting fault injector at $endpoint"
$serverArgs = @(
    ('"{0}"' -f $serverPy),
    "--host", "127.0.0.1",
    "--port", "$Port",
    "--drop-rate", "0.10",
    "--malformed-rate", "0.08",
    "--missing-field-rate", "0.08",
    "--slow-rate", "0.06",
    "--slow-seconds", "3.0"
)
$serverProc = Start-Process -FilePath $pythonExe -ArgumentList $serverArgs -PassThru -WindowStyle Hidden -RedirectStandardOutput $serverStdout -RedirectStandardError $serverStderr

Start-Sleep -Seconds 1
$serverProc.Refresh()
if ($serverProc.HasExited) {
    $stderr = if (Test-Path $serverStderr) { (Get-Content $serverStderr -Raw) } else { "" }
    throw "Fault injector terminato prematuramente. stderr: $stderr"
}

try {
    Write-Host "Running realtime loop with fault injection..."
    $controllerArgs = @(
        $controllerPy,
        "--mode", $Mode,
        "--source", "http_poll",
        "--http-url", $endpoint,
        "--poll-seconds", "$TickSeconds",
        "--watchdog-timeout-s", "$WatchdogTimeoutS",
        "--yield-cap-annual-kg", "$YieldCapAnnualKg",
        "--farm-active-area-m2", "$FarmActiveAreaM2",
        "--max-samples", "$DurationSamples",
        "--out-jsonl", $OutJsonl,
        "--store-db", $StoreDb
    )
    if ($Entrypoint -eq "controller" -and (Test-Path $prebuiltProfile)) {
        $controllerArgs += @("--profile-json", $prebuiltProfile)
    }
    & $pythonExe @controllerArgs
}
finally {
    if ($serverProc -and !$serverProc.HasExited) {
        Stop-Process -Id $serverProc.Id -Force
    }
}

if (Test-Path $OutJsonl) {
    $rows = Get-Content $OutJsonl | Where-Object { $_.Trim().Length -gt 0 } | ForEach-Object { $_ | ConvertFrom-Json }
    $fallback = @($rows | Where-Object { $_.actions -contains "safe_fallback_recipe" }).Count
    $timeout = @($rows | Where-Object { $_.actions -contains "safe_fallback_watchdog_timeout" }).Count
    $payloadErr = @($rows | Where-Object { $_.actions -contains "safe_fallback_sensor_payload_error" -or $_.actions -contains "safe_fallback_source_error" }).Count
    $qualityErr = @($rows | Where-Object { $_.actions -contains "safe_fallback_sensor_quality_fault" }).Count
    Write-Host "HIL summary:"
    Write-Host "  total_ticks: $($rows.Count)"
    Write-Host "  fallback_ticks: $fallback"
    Write-Host "  timeout_fallback_ticks: $timeout"
    Write-Host "  payload/source_fallback_ticks: $payloadErr"
    Write-Host "  sensor_quality_fallback_ticks: $qualityErr"
}
