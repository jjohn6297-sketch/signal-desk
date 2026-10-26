"""Daily SEC EDGAR snapshot: tracked funds' 13F holdings and insider buying at watch-list companies.

Writes:
  data/funds/holdings/<fund>/<period>.csv   one row per issuer, class, CUSIP and put/call
  data/funds/filings.csv                    every 13F used: fund, period, filed, accession, totals
  data/funds/fund_status.csv                EDGAR's name for each CIK and whether the fetch worked
  data/funds/insider_trades.csv             Form 4 open-market purchases (code P), append-only
  data/funds/form4_seen.txt                 Form 4 accession numbers already read

Run on GitHub Actions; this workspace cannot reach sec.gov. The SEC asks for at most
10 requests a second and a contact in the User-Agent (config/funds.yaml).
"""
from __future__ import annotations

import csv
import datetime as dt
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "funds"
CFG = yaml.safe_load((ROOT / "config" / "funds.yaml").read_text())
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": CFG["contact"], "Accept-Encoding": "gzip, deflate"})
HOLDING_FIELDS = ["issuer", "title_of_class", "cusip", "put_call", "value_usd", "shares", "share_type"]
TRADE_FIELDS = ["transaction_date", "filed", "company", "ticker", "insider", "role", "code", "shares", "price",
                "value_usd", "accession", "source_url"]


def get(url: str) -> requests.Response:
    time.sleep(0.15)
    r = SESSION.get(url, timeout=60)
    r.raise_for_status()
    return r


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def find(el: ET.Element, *path: str) -> str:
    """Text at a path of local tag names, ignoring namespaces; '' if absent."""
    cur = [el]
    for name in path:
        cur = [c for e in cur for c in e if local(c.tag) == name]
        if not cur:
            return ""
    return (cur[0].text or "").strip()


def submissions(cik: int) -> dict:
    return get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json").json()


def recent(sub: dict) -> list[dict]:
    r = sub["filings"]["recent"]
    keys = ["form", "accessionNumber", "filingDate", "reportDate", "primaryDocument"]
    return [dict(zip(keys, vals)) for vals in zip(*(r[k] for k in keys))]


def parse_info_table(xml: bytes) -> list[dict]:
    root = ET.fromstring(xml)
    rows: dict[tuple, dict] = {}
    for it in root.iter():
        if local(it.tag) != "infoTable":
            continue
        key = (find(it, "nameOfIssuer"), find(it, "titleOfClass"), find(it, "cusip"), find(it, "putCall"))
        row = rows.setdefault(key, {"issuer": key[0], "title_of_class": key[1], "cusip": key[2], "put_call": key[3],
                                    "value_usd": 0, "shares": 0, "share_type": find(it, "shrsOrPrnAmt", "sshPrnamtType")})
        row["value_usd"] += int(float(find(it, "value") or 0))
        row["shares"] += int(float(find(it, "shrsOrPrnAmt", "sshPrnamt") or 0))
    return sorted(rows.values(), key=lambda r: -r["value_usd"])


def info_table(cik: int, accession: str) -> list[dict]:
    folder = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}"
    items = get(f"{folder}/index.json").json()["directory"]["item"]
    for it in items:
        name = it["name"]
        if name.lower().endswith(".xml") and name.lower() != "primary_doc.xml":
            rows = parse_info_table(get(f"{folder}/{name}").content)
            if rows:
                return rows
    raise ValueError("no information table in filing")


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def thirteen_f() -> None:
    status, filings = [], read_csv(OUT / "filings.csv")
    have = {(f["fund"], f["period"]) for f in filings}
    for fund in CFG["funds"]:
        name, cik = fund["fund"], int(fund["cik"])
        try:
            sub = submissions(cik)
            by_period: dict[str, dict] = {}
            for f in recent(sub):
                if f["form"] == "13F-HR" and f["reportDate"]:
                    by_period.setdefault(f["reportDate"], f)  # newest first: keep the latest original filing
            periods = sorted(by_period, reverse=True)[: CFG["quarters_kept"]]
            for p in periods:
                if (name, p) in have:
                    continue
                f = by_period[p]
                rows = info_table(cik, f["accessionNumber"])
                write_csv(OUT / "holdings" / name / f"{p}.csv", rows, HOLDING_FIELDS)
                filings.append({"fund": name, "cik": cik, "period": p, "filed": f["filingDate"],
                                "accession": f["accessionNumber"], "positions": len(rows),
                                "total_value_usd": sum(r["value_usd"] for r in rows)})
                print(f"{name} {p}: {len(rows)} positions")
            for old in (OUT / "holdings" / name).glob("*.csv") if (OUT / "holdings" / name).exists() else []:
                if old.stem not in periods:
                    old.unlink()
            filings = [f for f in filings if f["fund"] != name or f["period"] in periods]
            status.append({"fund": name, "cik": cik, "edgar_name": sub.get("name"), "ok": "yes",
                           "latest_period": periods[0] if periods else "", "error": ""})
        except Exception as exc:  # one fund must not stop the others
            status.append({"fund": name, "cik": cik, "edgar_name": "", "ok": "no", "latest_period": "", "error": str(exc)[:200]})
            print(f"{name}: failed ({exc})")
    write_csv(OUT / "filings.csv", sorted(filings, key=lambda f: (f["fund"], f["period"])),
              ["fund", "cik", "period", "filed", "accession", "positions", "total_value_usd"])
    write_csv(OUT / "fund_status.csv", status, ["fund", "cik", "edgar_name", "ok", "latest_period", "error"])


def us_watchlist() -> list[dict]:
    rows = read_csv(ROOT / "watchlist" / "companies.csv")
    return [r for r in rows if r["exchange"].split(" ")[0].rstrip(";") in ("Nasdaq", "NYSE")]


def parse_form4(xml: bytes) -> list[dict]:
    root = ET.fromstring(xml)
    owner = next((e for e in root.iter() if local(e.tag) == "reportingOwner"), None)
    insider = find(owner, "reportingOwnerId", "rptOwnerName") if owner is not None else ""
    rel = next((e for e in root.iter() if local(e.tag) == "reportingOwnerRelationship"), None)
    roles = []
    if rel is not None:
        if find(rel, "isDirector") in ("1", "true"):
            roles.append("Director")
        if find(rel, "isOfficer") in ("1", "true"):
            roles.append(find(rel, "officerTitle") or "Officer")
        if find(rel, "isTenPercentOwner") in ("1", "true"):
            roles.append("10% owner")
    out = []
    for t in root.iter():
        if local(t.tag) != "nonDerivativeTransaction":
            continue
        code = find(t, "transactionCoding", "transactionCode")
        if code != "P" or find(t, "transactionAmounts", "transactionAcquiredDisposedCode", "value") != "A":
            continue
        shares = float(find(t, "transactionAmounts", "transactionShares", "value") or 0)
        price = float(find(t, "transactionAmounts", "transactionPricePerShare", "value") or 0)
        out.append({"transaction_date": find(t, "transactionDate", "value"), "insider": insider,
                    "role": ", ".join(roles), "code": code, "shares": int(shares), "price": round(price, 4),
                    "value_usd": int(shares * price)})
    return out


def form4() -> None:
    seen_path = OUT / "form4_seen.txt"
    seen = set(seen_path.read_text().split()) if seen_path.exists() else set()
    trades = read_csv(OUT / "insider_trades.csv")
    tickers = {v["ticker"].upper(): int(v["cik_str"]) for v in get("https://www.sec.gov/files/company_tickers.json").json().values()}
    since = (dt.date.today() - dt.timedelta(days=CFG["insider_lookback_days"])).isoformat()
    for c in us_watchlist():
        cik = tickers.get(c["ticker"].upper())
        if not cik:
            print(f"{c['ticker']}: no CIK")
            continue
        try:
            for f in recent(submissions(cik)):
                if f["form"] != "4" or f["filingDate"] < since or f["accessionNumber"] in seen:
                    continue
                doc = f["primaryDocument"].split("/")[-1]
                url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{f['accessionNumber'].replace('-', '')}/{doc}"
                try:
                    for t in parse_form4(get(url).content):
                        t.update({"filed": f["filingDate"], "company": c["company"], "ticker": c["ticker"],
                                  "accession": f["accessionNumber"], "source_url": url})
                        trades.append(t)
                        print(f"{c['ticker']}: purchase by {t['insider']} on {t['transaction_date']}")
                    seen.add(f["accessionNumber"])
                except Exception as exc:
                    print(f"{c['ticker']} {f['accessionNumber']}: could not read ({exc})")
        except Exception as exc:
            print(f"{c['ticker']}: failed ({exc})")
    write_csv(OUT / "insider_trades.csv", sorted(trades, key=lambda t: (t["filed"], t["accession"])), TRADE_FIELDS)
    seen_path.write_text("\n".join(sorted(seen)) + "\n")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    thirteen_f()
    form4()
    return 0


if __name__ == "__main__":
    sys.exit(main())
