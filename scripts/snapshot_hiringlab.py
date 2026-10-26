"""Daily copy of the Indeed Hiring Lab series the labour tracker uses.

Hiring Lab publishes full history in its own GitHub repositories, so this script keeps only
the countries and sectors we track, appends new dates, and writes a summary table.

Outputs:
  data/hiringlab/sectors.csv   date, country, sector, index (total postings, 1 Feb 2020 = 100)
  data/hiringlab/totals.csv    date, country, index (all postings, seasonally adjusted)
  data/hiringlab/ai_share.csv  date, country, ai_share, genai_share
  data/hiringlab/summary.csv   latest level and change over 3 and 12 months per series

Data: Indeed Hiring Lab, CC BY 4.0. Cite "Indeed Hiring Lab" when publishing.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "hiringlab"
BASE = "https://raw.githubusercontent.com/hiring-lab"
COUNTRIES = ["US", "GB", "DE", "FR", "IE"]  # Hiring Lab publishes no sector data for Ireland
SECTORS = [
    "Software Development", "Customer Service", "Legal", "Accounting", "Banking & Finance",
    "Insurance", "Marketing", "Media & Communications", "Data & Analytics", "Project Management",
    "Administrative Assistance", "Human Resources", "IT Infrastructure, Operations & Support",
]


def get_csv(url: str) -> list[dict]:
    r = requests.get(url, timeout=120)
    if r.status_code == 404:
        return []
    r.raise_for_status()
    return list(csv.DictReader(io.StringIO(r.text)))


def last_date(path: Path) -> str:
    if not path.exists():
        return ""
    with path.open(encoding="utf-8") as f:
        dates = [row["date"] for row in csv.DictReader(f)]
    return max(dates) if dates else ""


def append(path: Path, rows: list[dict], fields: list[str]) -> int:
    since = last_date(path)
    rows = sorted((r for r in rows if r["date"] > since), key=lambda r: tuple(r[k] for k in fields))
    if not rows:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new:
            w.writeheader()
        w.writerows(rows)
    return len(rows)


def change(series: dict[str, float], latest: str, months: int) -> str:
    d = dt.date.fromisoformat(latest)
    m = d.month - months
    y = d.year + (m - 1) // 12
    then = d.replace(year=y, month=(m - 1) % 12 + 1, day=min(d.day, 28)).isoformat()
    earlier = [k for k in series if k <= then]
    if not earlier:
        return ""
    base = series[max(earlier)]
    return f"{100 * (series[latest] / base - 1):.1f}" if base else ""


def main() -> None:
    sectors, totals, ai = [], [], []
    for c in COUNTRIES:
        for r in get_csv(f"{BASE}/job_postings_tracker/master/{c}/job_postings_by_sector_{c}.csv"):
            if r["variable"] == "total postings" and r["display_name"] in SECTORS:
                sectors.append({"date": r["date"], "country": c, "sector": r["display_name"], "index": r["indeed_job_postings_index"]})
        for r in get_csv(f"{BASE}/job_postings_tracker/master/{c}/aggregate_job_postings_{c}.csv"):
            if r["variable"] == "total postings":
                totals.append({"date": r["date"], "country": c, "index": r["indeed_job_postings_index_SA"]})
    share = {}
    for name, col in (("AI_posting.csv", "ai_share"), ("GenAI_posting.csv", "genai_share")):
        for r in get_csv(f"{BASE}/ai-tracker/main/{name}") or get_csv(f"{BASE}/ai-tracker/master/{name}"):
            if r.get("jobcountry") in COUNTRIES:
                value = next((v for k, v in r.items() if "share" in k.lower()), "")
                share.setdefault((r["date"], r["jobcountry"]), {})[col] = value
    ai = [{"date": d, "country": c, "ai_share": v.get("ai_share", ""), "genai_share": v.get("genai_share", "")} for (d, c), v in share.items()]

    n1 = append(OUT / "sectors.csv", sectors, ["date", "country", "sector", "index"])
    n2 = append(OUT / "totals.csv", totals, ["date", "country", "index"])
    n3 = append(OUT / "ai_share.csv", ai, ["date", "country", "ai_share", "genai_share"])

    summary = []
    series: dict[tuple[str, str], dict[str, float]] = {}
    for r in sectors:
        series.setdefault((r["country"], r["sector"]), {})[r["date"]] = float(r["index"])
    for r in totals:
        series.setdefault((r["country"], "All postings"), {})[r["date"]] = float(r["index"])
    for (c, s), points in sorted(series.items()):
        latest = max(points)
        summary.append({"country": c, "series": s, "latest_date": latest, "index_vs_feb_2020": points[latest],
                        "change_3m_pct": change(points, latest, 3), "change_12m_pct": change(points, latest, 12)})
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "summary.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0].keys()))
        w.writeheader()
        w.writerows(summary)
    print(f"Hiring Lab: +{n1} sector rows, +{n2} total rows, +{n3} AI-share rows; {len(summary)} series summarised")


if __name__ == "__main__":
    main()
