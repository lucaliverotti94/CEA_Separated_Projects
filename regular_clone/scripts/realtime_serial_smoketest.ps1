param(
    [Parameter(Mandatory = $true)]
    [string]$SerialPort,

    [int]$SerialBaud = 115200,

    [ValidateSet("max_yield", "max_quality", "max_yield_energy", "max_quality_energy")]
    [string]$Mode = "max_yield",

    [double]$WatchdogTimeoutS = 5.0,
    [int]$MaxSamples = 20,
    [Alias("YieldCapAnnualKg")]
    [double]$YieldTargetAnnualKg = 80.0,
    [double]$FarmActiveAreaM2 = 1.0,

    [string]$ProfileJson = "",
    [switch]$UseMpcSupervisor,
    [int]$MpcHorizon = 6,
    [int]$MpcCandidates = 96,

    [string]$OutJsonl = "control_output_literature_realtime.jsonl",
    [string]$StoreDb = "cea_timeseries.db"
)

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
$controllerPy = Join-Path $repoRoot "controller_literature_realtime.py"

if (-not (Test-Path $pythonExe)) {
    throw "Python venv non trovato: $pythonExe"
}
if (-not (Test-Path $controllerPy)) {
    throw "Entrypoint controller non trovato: $controllerPy"
}

$args = @(
    $controllerPy,
    "--mode", $Mode,
    "--source", "serial_json",
    "--serial-port", $SerialPort,
    "--serial-baud", "$SerialBaud",
    "--watchdog-timeout-s", "$WatchdogTimeoutS",
    "--yield-target-annual-kg", "$YieldTargetAnnualKg",
    "--farm-active-area-m2", "$FarmActiveAreaM2",
    "--max-samples", "$MaxSamples",
    "--out-jsonl", $OutJsonl,
    "--store-db", $StoreDb
)

if ($ProfileJson) {
    $profilePath = (Resolve-Path $ProfileJson).Path
    $args += @("--profile-json", $profilePath)
}

if ($UseMpcSupervisor) {
    $args += @(
        "--use-mpc-supervisor",
        "--mpc-horizon", "$MpcHorizon",
        "--mpc-candidates", "$MpcCandidates"
    )
}

Write-Host "Running serial realtime smoke test on $SerialPort @ $SerialBaud baud..."
& $pythonExe @args
