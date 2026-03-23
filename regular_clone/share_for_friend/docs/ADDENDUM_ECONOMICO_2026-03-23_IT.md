# Addendum Economico-Finanziario (allineato a baseline low-cost)

Data aggiornamento: 23/03/2026

## Stato documento
- Questo addendum sostituisce i valori storici basati su baseline industriale full.
- I numeri ufficiali correnti sono quelli prodotti da:
  - `economics/cea_economic_analysis.py`
  - `scripts/run_economic_analysis.py`
  - `docs/business/BUSINESS_MEMO_REGULAR_CLONE_IT.tex` (versione aggiornata)

## Configurazione ufficiale startup
- `infrastructure_profile = startup_low_capex`
- `energy_architecture = grid_only_retrofit`
- `monitoring_tier = core_efficiency_extended`
- `yield_target_annual_kg = 80` (vincolo in uguaglianza)
- `energy_cap_kwh_m2_cycle = 700`
- `quality_floor = 62`
- `yield_source = optimizer` (`optimizer_mode = max_yield_energy`)

## KPI scenario principale (80 kg/anno)
- CAPEX totale: `79,433.84 EUR`
- OPEX annuo: `61,052.00 EUR`
- Ricavi annui a `4.0 EUR/g`: `320,000.00 EUR`
- EBITDA annuo: `258,948.00 EUR`
- ROI annuo: `325.99%`
- Payback semplice: `0.31 anni`
- Break-even produzione: `15.26 kg/anno`
- Break-even prezzo: `0.763 EUR/g`

## KPI scenario crescita (104 kg/anno)
- CAPEX totale: `93,641.20 EUR`
- OPEX annuo: `67,413.90 EUR`
- Ricavi annui a `4.0 EUR/g`: `416,000.00 EUR`
- EBITDA annuo: `348,586.10 EUR`
- ROI annuo: `372.26%`
- Payback semplice: `0.27 anni`

## Tracciabilita comando
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
  --economic-yield-basis-policy target `
  --json-only
```
