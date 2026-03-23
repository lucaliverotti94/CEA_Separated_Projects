# Regular Clone Project

## Virtualenv
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements_realtime_optional.txt
```

## Comandi base
```powershell
.\.venv\Scripts\python.exe optimizer_literature_best.py --help
.\.venv\Scripts\python.exe controller_literature_realtime.py --help
.\.venv\Scripts\python.exe calibrate_twin.py --help
```

## Vincoli hard runtime
- Energia ciclo: `--energy-cap-kwh-m2` (kWh/m2 per ciclo).
- Resa annua farm-level: `--yield-target-annual-kg` (kg/anno, alias compatibile `--yield-cap-annual-kg`), con verifica di fattibilita rispetto a `--farm-active-area-m2`.

Esempio:
```powershell
.\.venv\Scripts\python.exe controller_literature_realtime.py `
  --mode max_yield_energy `
  --quality-floor 62 `
  --energy-cap-kwh-m2 640 `
  --yield-target-annual-kg 80 `
  --farm-active-area-m2 120 `
  --source mock_stream --max-samples 5
```

## Runtime locale
Path default locali al progetto:
- DB: `runtime/db/cea_timeseries.db`
- JSONL output: `runtime/jsonl/control_output_literature_realtime.jsonl`
- Profili runtime: `runtime/profiles/`
- Logs: `runtime/logs/`

## Documentazione
- Sorgente tecnico: `docs/technical/DOCUMENTAZIONE_TECNICA_REGULAR_CLONE_IT.tex`
- PDF tecnico: `docs/technical/DOCUMENTAZIONE_TECNICA_REGULAR_CLONE_IT.pdf`
- Sorgente business memo: `docs/business/BUSINESS_MEMO_REGULAR_CLONE_IT.tex`
- PDF business memo: `docs/business/BUSINESS_MEMO_REGULAR_CLONE_IT.pdf`
- Piano operativo: `docs/operations/NEXT_STEPS.md`

## Calibrazione twin (dataset template)
`calibration_dataset_template.json` e self-contained (profili inline) e include controlli hard
di coerenza famiglia/densita/sistema DWC-NFT durante il caricamento in `calibrate_twin.py`.

## Analisi economica (allineata al planner)
```powershell
.\.venv\Scripts\python.exe .\scripts\run_economic_analysis.py `
  --target-annual-kg 80 `
  --price-eur-g 4.0 `
  --mix-indica 0.5 `
  --mix-sativa 0.5 `
  --yield-source optimizer `
  --optimizer-mode max_yield_energy `
  --quality-floor 62 `
  --infrastructure-profile startup_low_capex `
  --energy-architecture grid_only_retrofit `
  --monitoring-tier core_efficiency_extended `
  --energy-cap-kwh-m2-cycle 700 `
  --economic-yield-basis-policy target
```

Il report include `selected_configuration`, `candidate_rankings` e `constraints_satisfied`.
