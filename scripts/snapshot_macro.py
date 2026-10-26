"""Daily snapshot of the macro indicators in config/macro.yaml that come from FRED.

Writes data/macro/<SERIES>.csv (date, value) from 2000 onwards, replacing the file each run,
because FRED revises recent values. Manual indicators live in data/macro/manual.csv and are
written by the Claude daily run, not by this script.

Run on GitHub Actions; this workspace cannot reach FRED.
"""
from __future__ import annotations

import csv
import io
import sys
import time
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "macro"
HEADERS = {"User-Agent": "signal-desk research bot (personal, non-commercial)"}
START = "2000-01-01"


def fetch_fred(series: str) -> list[tuple[str, float]]:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    rows = csv.reader(io.StringIO(r.text))
    next(rows)  # header: observation_date (or DATE), then the series id
    out = []
    for row in rows:
        if len(row) < 2 or row[1] in ("", "."):
            continue
        if row[0] >= START:
            out.append((row[0], float(row[1])))
    return out


def main() -> int:
    cfg = yaml.safe_load((ROOT / "config" / "macro.yaml").read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    manual = OUT / "manual.csv"
    if not manual.exists():
        manual.write_text("date,series,value,source\n", encoding="utf-8")
    ok = failed = 0
    for ind in cfg["indicators"]:
        if ind["source"] != "fred":
            continue
        try:
            rows = fetch_fred(ind["series"])
        except Exception as exc:  # one broken series must not stop the others
            print(f"{ind['series']}: failed ({exc})")
            failed += 1
            continue
        with (OUT / f"{ind['series']}.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["date", "value"])
            w.writerows(rows)
        print(f"{ind['series']}: {len(rows)} observations, latest {rows[-1] if rows else None}")
        ok += 1
        time.sleep(1)
    print(f"{ok} series fetched, {failed} failed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
