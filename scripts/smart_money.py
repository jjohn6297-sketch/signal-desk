"""Quarter-on-quarter moves by the tracked funds, from data/funds/ (see snapshot_sec.py).

Used by build_dashboard.py. Only common shares count as moves; listed options are reported
separately because a 13F gives their underlying value, not their cost or direction.
"""
from __future__ import annotations

import csv
import datetime as dt
import re
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "funds"

SUFFIXES = {"INC", "CORP", "CORPORATION", "CO", "COM", "LTD", "LIMITED", "PLC", "HLDGS", "HOLDINGS", "HLDG",
            "GROUP", "GRP", "NV", "N", "V", "SA", "AG", "LP", "LLC", "CL", "CLASS", "A", "B", "C", "ORD", "SHS",
            "NEW", "DEL", "THE", "ADR", "SPONSORED", "SPON", "ADS", "GDR", "TECHNOLOGIES"}
ALIASES = {"TSMC": "TAIWAN SEMICONDUCTOR", "AMD": "ADVANCED MICRO DEVICES", "NVIDIA": "NVIDIA",
           "GE VERNOVA": "GE VERNOVA", "OXFORD NANOPORE": "OXFORD NANOPORE"}


def norm(name: str) -> str:
    words = re.sub(r"[^A-Z0-9 ]", " ", (name or "").upper()).split()
    while words and words[-1] in SUFFIXES:
        words.pop()
    out = " ".join(words)
    return ALIASES.get(out, out)


def matches(issuer_norm: str, company_norm: str) -> bool:
    return bool(company_norm) and (issuer_norm == company_norm or issuer_norm.startswith(company_norm + " "))


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def holdings(fund: str, period: str, data: Path = DATA) -> dict[str, dict]:
    """Common-share holdings by normalised issuer: {issuer_norm: {issuer, value, shares}}."""
    out: dict[str, dict] = {}
    for r in read_csv(data / "holdings" / fund / f"{period}.csv"):
        if r.get("put_call"):
            continue
        k = norm(r["issuer"])
        h = out.setdefault(k, {"issuer": r["issuer"], "value": 0, "shares": 0})
        h["value"] += int(float(r["value_usd"] or 0))
        h["shares"] += int(float(r["shares"] or 0))
    return out


def action(prev: dict | None, cur: dict | None, min_change: float) -> str:
    if not prev and cur:
        return "new"
    if prev and not cur:
        return "exited"
    if not prev or not prev["shares"]:
        return "held"
    ch = cur["shares"] / prev["shares"] - 1
    if ch >= min_change:
        return "added"
    if ch <= -min_change:
        return "trimmed"
    return "held"


def fund_moves(fund: str, periods: list[str], min_change: float, data: Path = DATA) -> list[dict]:
    """Every issuer's move between a fund's last two periods."""
    if len(periods) < 2:
        return []
    cur_p, prev_p = periods[-1], periods[-2]
    cur, prev = holdings(fund, cur_p, data), holdings(fund, prev_p, data)
    total = sum(h["value"] for h in cur.values()) or 1
    out = []
    for k in set(cur) | set(prev):
        c, p = cur.get(k), prev.get(k)
        a = action(p, c, min_change)
        out.append({"fund": fund, "period": cur_p, "previous_period": prev_p, "issuer_norm": k,
                    "issuer": (c or p)["issuer"], "action": a,
                    "value_now": c["value"] if c else 0, "value_before": p["value"] if p else 0,
                    "shares_change": ((c["shares"] if c else 0) / p["shares"] - 1) if p and p["shares"] else None,
                    "weight_now": round((c["value"] if c else 0) / total, 5)})
    return out


def _holiday(d: dt.date) -> bool:
    """US federal holidays that can fall near a 13F deadline (mid Feb, May, Aug, Nov)."""
    presidents_day = d.month == 2 and d.weekday() == 0 and 15 <= d.day <= 21
    vet = dt.date(d.year, 11, 11)
    veterans_observed = vet + dt.timedelta(days={5: -1, 6: 1}.get(vet.weekday(), 0))
    return presidents_day or d == veterans_observed


def deadline(today: dt.date) -> tuple[str, str]:
    """The next 13F deadline (45 days after quarter end, moved to Monday if on a weekend) and its quarter."""
    for year in (today.year - 1, today.year, today.year + 1):
        for q_end in (dt.date(year, 3, 31), dt.date(year, 6, 30), dt.date(year, 9, 30), dt.date(year, 12, 31)):
            d = q_end + dt.timedelta(days=45)
            while d.weekday() >= 5 or _holiday(d):
                d += dt.timedelta(days=1)
            if d >= today:
                return d.isoformat(), q_end.isoformat()
    raise AssertionError


def build(today: dt.date, data: Path = DATA, root: Path = ROOT) -> dict[str, list[dict]]:
    cfg = yaml.safe_load((root / "config" / "funds.yaml").read_text())
    funds = {f["fund"]: f for f in cfg["funds"]}
    filings = read_csv(data / "filings.csv")
    status = {s["fund"]: s for s in read_csv(data / "fund_status.csv")}
    by_fund = defaultdict(list)
    for f in filings:
        by_fund[f["fund"]].append(f)
    watch = [(norm(r["company"]), r) for r in read_csv(root / "watchlist" / "companies.csv")]
    held = {norm(r["instrument"]) for r in read_csv(root / "journal" / "positions.csv") if r.get("status") == "open"}

    def watch_of(k: str) -> dict | None:
        return next((r for n, r in watch if matches(k, n)), None)

    def is_held(k: str) -> bool:
        return any(matches(k, h) for h in held)

    moves = []
    fund_rows = []
    for name, f in funds.items():
        fl = sorted(by_fund.get(name, []), key=lambda x: x["period"])
        periods = [x["period"] for x in fl]
        m = fund_moves(name, periods, cfg["min_change"], data)
        moves += m
        latest = fl[-1] if fl else {}
        top = sorted(holdings(name, latest["period"], data).values(), key=lambda h: -h["value"])[:5] if latest else []
        st = status.get(name, {})
        fund_rows.append({
            "fund": name, "name": f["name"], "manager": f.get("manager"), "style": f.get("style"), "cik": f["cik"],
            "edgar_name": st.get("edgar_name") or None, "ok": (st.get("ok") == "yes") if st else None,
            "latest_period": latest.get("period"), "filed": latest.get("filed"),
            "positions": int(latest["positions"]) if latest.get("positions") else None,
            "total_value_usd": int(latest["total_value_usd"]) if latest.get("total_value_usd") else None,
            "top_holdings": ", ".join(h["issuer"].title() for h in top) or None,
            "moves": sum(1 for x in m if x["action"] != "held"),
        })

    agg: dict[str, dict] = {}
    for x in moves:
        if x["action"] == "held":
            continue
        a = agg.setdefault(x["issuer_norm"], {"issuer": x["issuer"], "adding": [], "cutting": [], "periods": set(),
                                              "value_change": 0})
        a["periods"].add(x["period"])
        a["value_change"] += x["value_now"] - x["value_before"]
        label = funds[x["fund"]]["name"] + (" (new)" if x["action"] == "new" else " (exit)" if x["action"] == "exited" else "")
        (a["adding"] if x["action"] in ("new", "added") else a["cutting"]).append(label)
    issuer_rows = []
    for k, a in agg.items():
        w = watch_of(k)
        n_add, n_cut = len(a["adding"]), len(a["cutting"])
        if n_add + n_cut < 2 and not w and not is_held(k):
            continue
        issuer_rows.append({
            "key": k, "issuer": a["issuer"].title(), "funds_adding": n_add, "funds_cutting": n_cut, "net": n_add - n_cut,
            "adding": "; ".join(sorted(a["adding"])) or None, "cutting": "; ".join(sorted(a["cutting"])) or None,
            "value_change_usd": a["value_change"], "period": max(a["periods"]),
            "watchlist": w["company"] if w else None, "ticker": w["ticker"] if w else None,
            "theme": w["theme"] if w else None, "held": is_held(k),
            "consensus": "buying" if n_add >= 3 and n_add > n_cut else "selling" if n_cut >= 3 and n_cut > n_add else None,
        })
    issuer_rows.sort(key=lambda r: (-(r["funds_adding"] + r["funds_cutting"]), -abs(r["net"]), r["issuer"]))

    per_fund = []
    for name in funds:
        mine = sorted((x for x in moves if x["fund"] == name and x["action"] != "held"),
                      key=lambda x: -abs(x["value_now"] - x["value_before"]))[:6]
        for x in mine:
            w = watch_of(x["issuer_norm"])
            per_fund.append({"key": f"{name}|{x['issuer_norm']}", "fund": funds[name]["name"], "issuer": x["issuer"].title(),
                             "action": x["action"], "value_now_usd": x["value_now"],
                             "value_change_usd": x["value_now"] - x["value_before"],
                             "shares_change": round(x["shares_change"], 4) if x["shares_change"] is not None else None,
                             "weight_now": x["weight_now"], "period": x["period"],
                             "watchlist": w["company"] if w else None, "held": is_held(x["issuer_norm"])})

    since = (today - dt.timedelta(days=60)).isoformat()
    trades = [t for t in read_csv(data / "insider_trades.csv") if t["filed"] >= since]
    insiders = [{"key": f"{t['accession']}|{i}", "transaction_date": t["transaction_date"], "filed": t["filed"],
                 "company": t["company"], "ticker": t["ticker"], "insider": t["insider"].title(), "role": t["role"],
                 "shares": int(float(t["shares"] or 0)), "price": float(t["price"] or 0),
                 "value_usd": int(float(t["value_usd"] or 0)), "source_url": t["source_url"]}
                for i, t in enumerate(trades)]
    insiders.sort(key=lambda t: t["transaction_date"], reverse=True)

    statements = [{"key": f"{s['date']}|{i}", **s} for i, s in enumerate(read_csv(data / "statements.csv"))]

    due, quarter = deadline(today)
    periods = [r["latest_period"] for r in fund_rows if r["latest_period"]]
    latest_period = max(periods) if periods else None
    month_ago = (today - dt.timedelta(days=30)).isoformat()
    summary = [{
        "as_of": today.isoformat(), "latest_period": latest_period,
        "funds_reported": sum(1 for p in periods if p == latest_period), "funds_tracked": len(funds),
        "consensus_buys": sum(1 for r in issuer_rows if r["consensus"] == "buying"),
        "consensus_sells": sum(1 for r in issuer_rows if r["consensus"] == "selling"),
        "insider_buys_30d": sum(1 for t in insiders if t["filed"] >= month_ago),
        "conflicts": sum(1 for s in statements if (s.get("conflict") or "").strip()),
        "next_deadline": due, "next_quarter": quarter,
    }]
    return {"sm_summary": summary, "sm_moves": issuer_rows, "sm_fund_moves": per_fund, "sm_funds": fund_rows,
            "sm_insiders": insiders, "sm_statements": statements}
