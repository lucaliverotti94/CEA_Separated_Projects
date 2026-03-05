# Legacy Project

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

## Runtime locale
Path default locali al progetto:
- DB: `runtime/db/cea_timeseries.db`
- JSONL output: `runtime/jsonl/control_output_literature_realtime.jsonl`
- Profili runtime: `runtime/profiles/`
- Logs: `runtime/logs/`