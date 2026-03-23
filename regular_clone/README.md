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
```

## Vincoli hard runtime
- Energia ciclo: `--energy-cap-kwh-m2` (kWh/m2 per ciclo).
- Resa annua farm-level: `--yield-cap-annual-kg` (kg/anno), convertita con `--farm-active-area-m2`.

Esempio:
```powershell
.\.venv\Scripts\python.exe controller_literature_realtime.py `
  --mode max_yield_energy `
  --energy-cap-kwh-m2 640 `
  --yield-cap-annual-kg 80 `
  --farm-active-area-m2 120 `
  --source mock_stream --max-samples 5
```

## Runtime locale
Path default locali al progetto:
- DB: `runtime/db/cea_timeseries.db`
- JSONL output: `runtime/jsonl/control_output_literature_realtime.jsonl`
- Profili runtime: `runtime/profiles/`
- Logs: `runtime/logs/`
