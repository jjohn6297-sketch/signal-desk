"""Resolve forecasts that can be checked against public data, without a human or a model.

Reads forecasts/forecasts.yaml. For every open forecast with `resolution.method: auto`,
fetches the named series and applies the rule. Judged forecasts (method: judged) are left
for the scheduled Claude run described in docs/AUTOMATION.md.

Rules (resolution.rule.kind):
  never_close_above  outcome 1 if no observation in [start, end] is above `threshold`;
                     resolves 0 as soon as one is, 1 once `end` has passed.
  touch_below        outcome 1 as soon as an observation in [start, end] is below `threshold`;
                     0 once `end` has passed without one.
  value_on_date      compares the last observation on or before `date` with `threshold`
                     using `op` (<=, <, >=, >); resolves once data for that date exists.
  release_value      compares the value for observation `period` (e.g. 2026-12-01) with
                     `threshold` using `op`; resolves once that period is published.

Series: UST10Y (US Treasury 10-year par yield), BRENT (FRED DCOILBRENTEU spot),
UNRATE, T5YIFR (FRED), INDEED_US:<sector> and INDEED_US_TOTAL (data/hiringlab).
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import sys
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "forecasts" / "forecasts.yaml"
HEADERS = {"User-Agent": "signal-desk research bot (personal, non-commercial)"}
TODAY = dt.date.today()


def _fred(series_id: str) -> dict[str, float]:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    rows = csv.reader(io.StringIO(requests.get(url, headers=HEADERS, timeout=60).text))
    next(rows)  # header: DATE or observation_date, then the series id
    out = {}
    for date, value in rows:
        if value not in ("", "."):
            out[date] = float(value)
    return out


def _treasury_10y() -> dict[str, float]:
    out = {}
    for year in range(2026, TODAY.year + 1):
        url = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
               f"daily-treasury-rates.csv/{year}/all?type=daily_treasury_yield_curve"
               f"&field_tdr_date_value={year}&page&_format=csv")
        text = requests.get(url, headers=HEADERS, timeout=60).text
        for row in csv.DictReader(io.StringIO(text)):
            if row.get("10 Yr"):
                m, d, y = row["Date"].split("/")
                out[f"{y}-{m}-{d}"] = float(row["10 Yr"])
    return out


def _indeed(sector: str | None) -> dict[str, float]:
    path = ROOT / "data" / "hiringlab" / ("totals.csv" if sector is None else "sectors.csv")
    out = {}
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["country"] == "US" and (sector is None or r["sector"] == sector):
                out[r["date"]] = float(r["index"])
    return out


_cache: dict[str, dict[str, float]] = {}


def series(name: str) -> dict[str, float]:
    if name not in _cache:
        if name == "UST10Y":
            _cache[name] = _treasury_10y()
        elif name == "BRENT":
            _cache[name] = _fred("DCOILBRENTEU")
        elif name in ("UNRATE", "T5YIFR"):
            _cache[name] = _fred(name)
        elif name == "INDEED_US_TOTAL":
            _cache[name] = _indeed(None)
        elif name.startswith("INDEED_US:"):
            _cache[name] = _indeed(name.split(":", 1)[1])
        else:
            raise ValueError(f"unknown series {name}")
    return _cache[name]


OPS = {"<=": lambda a, b: a <= b, "<": lambda a, b: a < b, ">=": lambda a, b: a >= b, ">": lambda a, b: a > b}


def evaluate(rule: dict, data: dict[str, float], today: dt.date) -> tuple[int | None, str]:
    """Return (outcome or None if not yet resolvable, evidence text)."""
    kind = rule["kind"]
    if kind in ("never_close_above", "touch_below"):
        start, end = str(rule["start"]), str(rule["end"])
        window = {d: v for d, v in data.items() if start <= d <= end}
        thr = float(rule["threshold"])
        if kind == "never_close_above":
            hits = sorted(d for d, v in window.items() if v > thr)
            if hits:
                return 0, f"{hits[0]}: {window[hits[0]]} > {thr}"
            if today.isoformat() > end and window:
                return 1, f"max {max(window.values())} <= {thr} over {start}..{end}"
        else:
            hits = sorted(d for d, v in window.items() if v < thr)
            if hits:
                return 1, f"{hits[0]}: {window[hits[0]]} < {thr}"
            if today.isoformat() > end and window:
                return 0, f"min {min(window.values())} >= {thr} over {start}..{end}"
        return None, ""
    if kind == "value_on_date":
        date = str(rule["date"])
        if today.isoformat() <= date:
            return None, ""
        prior = [d for d in data if d <= date]
        if not prior:
            return None, ""
        d = max(prior)
        v = data[d]
        return int(OPS[rule["op"]](v, float(rule["threshold"]))), f"{d}: {v} {rule['op']} {rule['threshold']}"
    if kind == "release_value":
        period = str(rule["period"])
        if period not in data:
            return None, ""
        v = data[period]
        return int(OPS[rule["op"]](v, float(rule["threshold"]))), f"{period}: {v} {rule['op']} {rule['threshold']}"
    raise ValueError(f"unknown rule kind {kind}")


def main() -> int:
    doc = yaml.safe_load(REGISTRY.read_text())
    changed = 0
    for f in doc["forecasts"]:
        res = f.get("resolution") or {}
        if f.get("status") != "open" or res.get("method") != "auto":
            continue
        rule = res["rule"]
        try:
            outcome, evidence = evaluate(rule, series(rule["series"]), TODAY)
        except Exception as exc:  # a broken feed must not stop the others
            print(f"{f['id']}: could not evaluate ({exc})")
            continue
        if outcome is not None:
            f.update({"status": "resolved", "outcome": outcome, "resolved_at": TODAY.isoformat(),
                      "evidence": f"auto: {rule['series']} {evidence}"})
            changed += 1
            print(f"{f['id']}: resolved {outcome} ({evidence})")
    if changed:
        REGISTRY.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=110))
    print(f"{changed} forecast(s) resolved automatically")
    return 0


if __name__ == "__main__":
    sys.exit(main())
