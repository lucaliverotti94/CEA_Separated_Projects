# Next Steps Operativi (Calibrazione -> Produzione)

Questo piano traduce in azioni concrete sia il lavoro in campo sia il lavoro software, con dipendenze esplicite.
Baseline attuale: codice pronto per pre-calibrazione con `yield_cap_annual_kg` parametrico (default `80`).

## Fase A - Preparazione banco pilota (1-2 m2)

1. `A1 - Setup impiantistico pilota (reale)`
- Configurare una linea pilota con propagazione `DWC` e produzione `NFT` (stessa logica del runtime).
- Definire cultivar/famiglia per test (`indica_dominant` o `sativa_dominant`) e mantenere densita coerente:
  - indica: `4.0` piante/m2
  - sativa: `2.0` piante/m2

2. `A2 - Sensoristica e attuatori (reale)`
- Installare e validare sensori: `t_air_c`, `rh_pct`, `co2_ppm`, `ppfd`, `t_solution_c`, `do_mg_l`, `ec_ms_cm`, `ph`.
- Verificare latenza, frequenza campionamento e continuita stream.

3. `A3 - Infrastruttura runtime (codice)`
- Eseguire setup ambiente:
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements_realtime_optional.txt
```
- Verificare test:
```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```

Dipendenze: `A1` e `A2` sono prerequisiti per acquisire dati validi in `B1`.

## Fase B - Raccolta dataset calibrazione

4. `B1 - Esecuzione cicli osservati (reale)`
- Condurre cicli reali completi su banco pilota.
- Per ogni ciclo registrare:
  - output finali osservati: `dry_yield_g_m2`, `quality_index`, `penalty`, `disease_pressure`, `hlvd_pressure`, `energy_kwh_m2`
  - contesto: famiglia/cultivar, densita reale, ricircolo, qualita acqua, quality score sensori, note operative.

5. `B2 - Compilazione dataset (codice + dato)`
- Usare `calibration_dataset_template.json` come struttura base.
- Regola hard: coerenza famiglia/profilo/densita (enforced dal loader calibrazione).
- Se si usano profili esterni, devono essere della stessa famiglia del ciclo osservato.

Dipendenze: `B2` dipende da `B1`.

## Fase C - Calibrazione twin

6. `C1 - Fit calibrazione (codice)`
```powershell
.\.venv\Scripts\python.exe .\calibrate_twin.py ^
  --dataset-json .\calibration_dataset_template.json ^
  --out-json .\runtime\profiles\twin_calibration.json ^
  --store-db .\runtime\db\cea_timeseries.db
```

7. `C2 - Gate di accettazione calibrazione (analisi)`
- Verificare su output:
  - `fit.train_loss` basso e stabile.
  - `fit.val_loss` (se presente) accettabile e non divergente.
  - metriche per famiglia coerenti con osservazioni reali.
- Se non accettabile: tornare a `B1/B2` con piu cicli o migliore qualita dati.

Dipendenze: `C1` dipende da `B2`. `C2` dipende da `C1`.

## Fase D - Ottimizzazione profili pre-produzione

8. `D1 - Ottimizzazione offline energy-constrained (codice)`
- Eseguire optimizer in modalita `max_yield_energy` e/o `max_quality_energy` con cap energia coerente col budget.
- Mantenere `yield_cap_annual_kg` parametrico (default `80`, modificabile a target reale).

9. `D2 - Verifica vincoli hard (codice)`
- Controllare nel profilo finale:
  - energia ciclo <= `energy_cap_kwh_m2`
  - resa annua proiettata <= `yield_cap_annual_kg`
  - durate/densita family-hard coerenti.

Dipendenze: `D1` dipende da `C2`. `D2` dipende da `D1`.

## Fase E - Analisi economica pre-go-live

10. `E1 - Run analisi economica allineata (codice)`
```powershell
.\.venv\Scripts\python.exe .\scripts\run_economic_analysis.py ^
  --target-annual-kg 80 ^
  --price-eur-g 4.0 ^
  --mix-indica 0.5 ^
  --mix-sativa 0.5 ^
  --target-yield-kg-m2-cycle 0.35 ^
  --energy-cap-kwh-m2-cycle 700
```

11. `E2 - KPI economici da validare (business)`
- `annual_revenue_eur`
- `opex_total_annual`
- `ebitda_annual_eur`
- `roi_annual_pct`
- `simple_payback_years`
- `break_even_yield_kg_year`

Dipendenze: `E1` dipende da `D2`. `E2` dipende da `E1`.

## Fase F - Produzione giornaliera

12. `F1 - Avvio controller realtime (codice + impianto)`
- Avviare in `max_yield_energy` o `max_quality_energy`.
- Alimentare stream sensori reali.
- Attivare persistenza DB e watchdog/fallback.

13. `F2 - Routine operativa giornaliera (reale + codice)`
- Acquisizione sensori -> quality gate -> correzioni controller -> attuatori.
- Revisione giornaliera eventi `fallback`, `source_error`, alert rolling-window.
- Verifica continua gap reale-vs-target e tuning attuatori.

14. `F3 - Riesame periodico (settimanale/mensile)`
- Aggiornare dataset cicli conclusi.
- Rieseguire `calibrate_twin.py` quando emerge drift.
- Riottimizzare profili se cambiano costi energia, target resa o mix genetico.

Dipendenze: `F1` dipende da `E2`. `F2` dipende da `F1`. `F3` e ciclico su `B2 -> C1 -> D1 -> E1`.

## Parametri chiave da mantenere sotto controllo

- `yield_cap_annual_kg`: default `80`, sempre parametrico.
- `energy_cap_kwh_m2` / `energy_cap_kwh_m2_cycle`: cap energetico per ciclo.
- Densita hard family:
  - indica `4.0` pl/m2
  - sativa `2.0` pl/m2
- Finestre hard pre-ciclo:
  - germinazione `10-14` gg
  - seed -> talea `27-35` gg

