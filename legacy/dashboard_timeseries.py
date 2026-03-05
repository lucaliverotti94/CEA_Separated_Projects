from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Dict, List
import argparse
import json

from core.storage import fetch_alert_events, fetch_calibrations, fetch_control_ticks, fetch_optimizer_runs, init_storage


def _extract_series(rows: List[Dict], section: str, field: str) -> List[float | None]:
    out: List[float | None] = []
    for r in rows:
        block = r.get(section, {})
        val = block.get(field) if isinstance(block, dict) else None
        try:
            out.append(float(val) if val is not None else None)
        except Exception:
            out.append(None)
    return out


def _build_payload(db_path: str, ticks_limit: int, runs_limit: int, cals_limit: int) -> Dict:
    ticks = fetch_control_ticks(db_path=db_path, limit=ticks_limit)
    runs = fetch_optimizer_runs(db_path=db_path, limit=runs_limit)
    cals = fetch_calibrations(db_path=db_path, limit=cals_limit)
    alerts = fetch_alert_events(db_path=db_path, limit=max(400, int(ticks_limit)))

    action_counts: Counter[str] = Counter()
    for t in ticks:
        for a in t.get("actions", []):
            action_counts[str(a)] += 1

    timestamps = [t.get("ts") for t in ticks]
    payload = {
        "timestamps": timestamps,
        "sensor_t_air": _extract_series(ticks, "sensor", "t_air_c"),
        "rec_t_air": _extract_series(ticks, "recommended_setpoint", "t_air_c"),
        "sensor_rh": _extract_series(ticks, "sensor", "rh_pct"),
        "rec_rh": _extract_series(ticks, "recommended_setpoint", "rh_pct"),
        "sensor_ppfd": _extract_series(ticks, "sensor", "ppfd"),
        "rec_ppfd": _extract_series(ticks, "recommended_setpoint", "ppfd"),
        "sensor_ec": _extract_series(ticks, "sensor", "ec_ms_cm"),
        "rec_ec": _extract_series(ticks, "recommended_setpoint", "ec_ms_cm"),
        "sensor_ph": _extract_series(ticks, "sensor", "ph"),
        "rec_ph": _extract_series(ticks, "recommended_setpoint", "ph"),
        "optimizer_runs": runs,
        "calibrations": cals,
        "alerts": alerts,
        "action_counts": dict(action_counts.most_common(20)),
        "alert_counts": dict(Counter(str(a.get("code", "")) for a in alerts).most_common(20)),
        "alert_severity_counts": dict(Counter(str(a.get("severity", "")) for a in alerts).most_common(20)),
        "n_ticks": len(ticks),
        "n_runs": len(runs),
        "n_calibrations": len(cals),
        "n_alerts": len(alerts),
    }
    return payload


def _render_html(data: Dict) -> str:
    blob = json.dumps(data, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>CEA Dashboard</title>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <style>
    body {{
      font-family: "Segoe UI", Tahoma, sans-serif;
      margin: 0;
      background: linear-gradient(135deg, #f4f8f5 0%, #e8f1e9 100%);
      color: #1f2a1f;
    }}
    .wrap {{
      max-width: 1280px;
      margin: 20px auto;
      padding: 0 16px 24px 16px;
    }}
    h1 {{
      font-size: 1.6rem;
      margin-bottom: 6px;
    }}
    .meta {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px;
      margin: 14px 0 20px 0;
    }}
    .card {{
      background: white;
      border: 1px solid #d8e4da;
      border-radius: 10px;
      padding: 10px 12px;
      box-shadow: 0 2px 7px rgba(0,0,0,0.05);
    }}
    .grid {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 12px;
    }}
    .chart {{
      background: white;
      border: 1px solid #d8e4da;
      border-radius: 10px;
      padding: 6px;
      min-height: 320px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: white;
      border: 1px solid #d8e4da;
      border-radius: 10px;
      overflow: hidden;
      font-size: 0.9rem;
    }}
    th, td {{
      border-bottom: 1px solid #edf3ee;
      padding: 8px;
      text-align: left;
    }}
    th {{
      background: #f2f8f3;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>CEA Realtime Dashboard</h1>
    <div>Dati da storage SQLite: sensori, setpoint, ottimizzazioni e calibrazioni twin.</div>
    <div class="meta">
      <div class="card"><b>Control ticks</b><br /><span id="m_ticks"></span></div>
      <div class="card"><b>Optimizer runs</b><br /><span id="m_runs"></span></div>
      <div class="card"><b>Twin calibrations</b><br /><span id="m_cals"></span></div>
      <div class="card"><b>Alerts</b><br /><span id="m_alerts"></span></div>
    </div>

    <div class="grid">
      <div id="chart_temp" class="chart"></div>
      <div id="chart_ppfd" class="chart"></div>
      <div id="chart_ec_ph" class="chart"></div>
      <div id="chart_actions" class="chart"></div>
      <div id="chart_alerts" class="chart"></div>
      <div id="chart_runs" class="chart"></div>
    </div>

    <h3>Ultime calibrazioni twin</h3>
    <table id="tbl_cal"></table>
  </div>

  <script>
    const DATA = {blob};
    document.getElementById("m_ticks").textContent = DATA.n_ticks;
    document.getElementById("m_runs").textContent = DATA.n_runs;
    document.getElementById("m_cals").textContent = DATA.n_calibrations;
    document.getElementById("m_alerts").textContent = DATA.n_alerts;

    const x = DATA.timestamps;
    Plotly.newPlot("chart_temp", [
      {{x, y: DATA.sensor_t_air, name: "Sensor T aria", mode: "lines"}},
      {{x, y: DATA.rec_t_air, name: "Setpoint T aria", mode: "lines"}},
      {{x, y: DATA.sensor_rh, name: "Sensor RH", mode: "lines", yaxis: "y2"}},
      {{x, y: DATA.rec_rh, name: "Setpoint RH", mode: "lines", yaxis: "y2"}}
    ], {{
      title: "Clima aria: misura vs setpoint",
      yaxis: {{title: "T aria (degC)"}},
      yaxis2: {{title: "RH (%)", overlaying: "y", side: "right"}},
      legend: {{orientation: "h"}}
    }}, {{responsive: true}});

    Plotly.newPlot("chart_ppfd", [
      {{x, y: DATA.sensor_ppfd, name: "Sensor PPFD", mode: "lines"}},
      {{x, y: DATA.rec_ppfd, name: "Setpoint PPFD", mode: "lines"}}
    ], {{
      title: "Luce: PPFD misura vs setpoint",
      yaxis: {{title: "PPFD (umol m-2 s-1)"}},
      legend: {{orientation: "h"}}
    }}, {{responsive: true}});

    Plotly.newPlot("chart_ec_ph", [
      {{x, y: DATA.sensor_ec, name: "Sensor EC", mode: "lines"}},
      {{x, y: DATA.rec_ec, name: "Setpoint EC", mode: "lines"}},
      {{x, y: DATA.sensor_ph, name: "Sensor pH", mode: "lines", yaxis: "y2"}},
      {{x, y: DATA.rec_ph, name: "Setpoint pH", mode: "lines", yaxis: "y2"}}
    ], {{
      title: "Nutrizione: EC/pH misura vs setpoint",
      yaxis: {{title: "EC (mS/cm)"}},
      yaxis2: {{title: "pH", overlaying: "y", side: "right"}},
      legend: {{orientation: "h"}}
    }}, {{responsive: true}});

    const actionLabels = Object.keys(DATA.action_counts);
    const actionVals = actionLabels.map(k => DATA.action_counts[k]);
    Plotly.newPlot("chart_actions", [
      {{x: actionLabels, y: actionVals, type: "bar"}}
    ], {{
      title: "Top adaptive actions",
      xaxis: {{title: "Azione"}},
      yaxis: {{title: "Conteggio"}}
    }}, {{responsive: true}});

    const alertLabels = Object.keys(DATA.alert_counts || {{}});
    const alertVals = alertLabels.map(k => DATA.alert_counts[k]);
    Plotly.newPlot("chart_alerts", [
      {{x: alertLabels, y: alertVals, type: "bar"}}
    ], {{
      title: "Operational alerts by code",
      xaxis: {{title: "Alert code"}},
      yaxis: {{title: "Count"}}
    }}, {{responsive: true}});

    const runs = DATA.optimizer_runs || [];
    Plotly.newPlot("chart_runs", [
      {{
        x: runs.filter(r => r.mode === "max_yield").map(r => r.dry_yield_g_m2),
        y: runs.filter(r => r.mode === "max_yield").map(r => r.quality_index),
        mode: "markers",
        type: "scatter",
        name: "max_yield",
      }},
      {{
        x: runs.filter(r => r.mode === "max_quality").map(r => r.dry_yield_g_m2),
        y: runs.filter(r => r.mode === "max_quality").map(r => r.quality_index),
        mode: "markers",
        type: "scatter",
        name: "max_quality",
      }}
    ], {{
      title: "Optimizer runs: resa vs qualita",
      xaxis: {{title: "Dry yield (g/m2)"}},
      yaxis: {{title: "Quality index"}}
    }}, {{responsive: true}});

    const cal = DATA.calibrations || [];
    const headers = ["ts", "name", "train_loss", "val_loss", "params"];
    const tbl = document.getElementById("tbl_cal");
    const hRow = document.createElement("tr");
    headers.forEach(h => {{
      const th = document.createElement("th");
      th.textContent = h;
      hRow.appendChild(th);
    }});
    tbl.appendChild(hRow);
    cal.slice(-15).reverse().forEach(c => {{
      const tr = document.createElement("tr");
      const cols = [
        c.ts || "",
        c.name || "",
        (c.train_loss ?? "").toString(),
        (c.val_loss ?? "").toString(),
        JSON.stringify(c.params || {{}})
      ];
      cols.forEach(v => {{
        const td = document.createElement("td");
        td.textContent = v;
        tr.appendChild(td);
      }});
      tbl.appendChild(tr);
    }});
  </script>
</body>
</html>
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate HTML dashboard from CEA SQLite telemetry.")
    parser.add_argument("--db-path", default="runtime/db/cea_timeseries.db")
    parser.add_argument("--out-html", default="runtime/logs/dashboard_timeseries.html")
    parser.add_argument("--ticks-limit", type=int, default=4000)
    parser.add_argument("--runs-limit", type=int, default=300)
    parser.add_argument("--cal-limit", type=int, default=80)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    init_storage(args.db_path)
    data = _build_payload(
        db_path=args.db_path,
        ticks_limit=args.ticks_limit,
        runs_limit=args.runs_limit,
        cals_limit=args.cal_limit,
    )
    html = _render_html(data)
    out = Path(args.out_html)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(str(out.resolve()))


if __name__ == "__main__":
    main()
