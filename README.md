# CEA Separated Projects

Questa cartella contiene due progetti indipendenti:

- `legacy/`: snapshot metodo legacy (HEAD del repository sorgente).
- `regular_clone/`: snapshot metodo regular clone (working tree corrente + file sessione necessari).

## Setup rapido

### Legacy
```powershell
cd legacy
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements_realtime_optional.txt
```

### Regular Clone
```powershell
cd regular_clone
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements_realtime_optional.txt
```