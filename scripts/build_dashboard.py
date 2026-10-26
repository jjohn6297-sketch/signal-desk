"""Build the data files for the private Signal Desk dashboard.

Reads the repository (forecasts, theses, scores, insights, labour data) and writes one
JSON file of row objects per dashboard source into dashboard/. The scheduled Claude run
uploads each file to the dashboard and updates its source (docs/AUTOMATION.md, step 10).

  dashboard/insights.json        latest insight bullets, newest file first
  dashboard/forecasts.json       every forecast, one row each
  dashboard/theses.json          every thesis with its forecast counts and conviction
  dashboard/scores.json          one row: headline scores and recalibration status
  dashboard/calibration.json     stated probability band vs share that happened
  dashboard/score_groups.json    Brier score by kind and by thesis
  dashboard/labour_summary.json  Indeed Hiring Lab: latest index and 3/12-month change
  dashboard/labour_trend.json    Indeed Hiring Lab: month-end index by country and series
  dashboard/ai_share.json        Indeed Hiring Lab: month-end AI share of postings
  dashboard/career_boards.json   latest open roles by role group and seniority
  dashboard/board_status.json    whether each career board answered on the last run
  dashboard/product_summary.json one row: product-manager roles open on the latest snapshot
  dashboard/product_levels.json  product-manager roles by level, all regions and Ireland
  dashboard/product_trend.json   product-manager roles per snapshot day
  dashboard/product_by_company.json  product-manager roles per tracked company
  dashboard/product_roles_ireland.json  every open product-manager role in Ireland
  dashboard/macro_regime.json    one row: current regime, counts and position-size limits
  dashboard/macro_indicators.json  every macro indicator with latest value, state and thresholds
  dashboard/macro_history.json   weekly (Friday) value of each indicator since 2023
  dashboard/regime_history.json  weekly regime since 2023

A source with no rows yet is written as one row {"_empty": true}, because the dashboard
cannot load an empty file; the page shows its empty message for that row.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from score_forecasts import BINS, MIN_N, brier  # noqa: E402

OUT = ROOT / "dashboard"
TODAY = dt.date.today()


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def num(x):
    try:
        return round(float(x), 4)
    except (TypeError, ValueError):
        return None


def write(name: str, rows: list[dict]) -> None:
    if not rows:
        rows = [{"_empty": True}]
    (OUT / f"{name}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    print(f"{name}: {len(rows)} rows")


def insights() -> list[dict]:
    files = sorted((ROOT / "insights").glob("*.md"), reverse=True)[:5]
    files += sorted((ROOT / "insights" / "weekly").glob("*.md"), reverse=True)[:2]
    rows = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        title = next((l.lstrip("# ").strip() for l in text.splitlines() if l.startswith("#")), f.stem)
        bullets = [l[2:].strip() for l in text.splitlines() if l.startswith("- ")]
        kind = "weekly" if f.parent.name == "weekly" else "daily"
        for i, b in enumerate(bullets, 1):
            rows.append({"key": f"{f.stem}-{i}", "date": f.stem, "kind": kind, "title": title, "rank": i, "text": b})
    return rows


def forecasts(thesis_titles: dict[str, str]) -> list[dict]:
    doc = yaml.safe_load((ROOT / "forecasts" / "forecasts.yaml").read_text())
    rows = []
    for f in doc["forecasts"]:
        p = float(f["probability"])
        out = f.get("outcome")
        ov = f.get("override") or {}
        rows.append({
            "id": f["id"],
            "kind": f.get("kind", "thesis"),
            "thesis": f.get("thesis"),
            "thesis_title": thesis_titles.get(f.get("thesis"), "Other"),
            "statement": f["statement"],
            "probability": p,
            "probability_raw": num(f.get("probability_raw", p)),
            "override": num(ov.get("probability")),
            "reasoning": f.get("reasoning"),
            "expected": f.get("expected"),
            "if_yes": (f.get("implications") or {}).get("if_yes"),
            "if_no": (f.get("implications") or {}).get("if_no"),
            "made_at": str(f.get("made_at")),
            "event_date": str(f["event_date"]) if f.get("event_date") else None,
            "resolves_by": str(f.get("resolves_by")),
            "method": (f.get("resolution") or {}).get("method"),
            "status": f.get("status"),
            "outcome": out,
            "brier": round((p - out) ** 2, 4) if out in (0, 1) else None,
            "evidence": f.get("evidence"),
        })
    return rows


def theses(fc: list[dict]) -> tuple[list[dict], dict[str, str]]:
    rows, titles = [], {}
    for path in sorted((ROOT / "theses").glob("*.yaml")):
        if path.stem == "TEMPLATE":
            continue
        t = yaml.safe_load(path.read_text())
        titles[t["id"]] = t["title"]
        hist = t.get("conviction_history") or []
        prev = hist[-2].get("value") if len(hist) >= 2 and isinstance(hist[-2], dict) else None
        rows.append({
            "id": t["id"],
            "title": t["title"],
            "type": t.get("type"),
            "theme": t.get("theme"),
            "status": t.get("status"),
            "opened": str(t.get("opened")),
            "horizon": t.get("horizon"),
            "conviction": t.get("system_conviction"),
            "conviction_prev": prev,
            "conviction_reason": t.get("conviction_reason"),
            "owner_conviction": t.get("owner_conviction"),
            "evidence_for": len(t.get("evidence_for") or []),
            "evidence_against": len(t.get("evidence_against") or []),
            "kill_criteria": " · ".join(t.get("kill_criteria") or []),
            "kill_hit": " · ".join(t.get("kill_criteria_hit") or []),
            "variant_view": t.get("variant_view"),
        })
    for r in rows:
        mine = [f for f in fc if f["thesis"] == r["id"]]
        open_ = [f for f in mine if f["status"] == "open"]
        r["open_forecasts"] = len(open_)
        r["resolved_forecasts"] = sum(1 for f in mine if f["status"] == "resolved")
        r["next_resolves"] = min((f["event_date"] or f["resolves_by"] for f in open_), default=None)
    return rows, titles


def scores(fc: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    res = [f for f in fc if f["status"] == "resolved" and f["outcome"] in (0, 1)]
    pairs = [(f["probability"], f["outcome"]) for f in res]
    ov = [f for f in res if f["override"] is not None]
    rec = json.loads((ROOT / "scores" / "recalibration.json").read_text())
    summary = [{
        "as_of": TODAY.isoformat(),
        "total": len(fc),
        "open": sum(1 for f in fc if f["status"] == "open"),
        "resolved": len(res),
        "void": sum(1 for f in fc if f["status"] == "void"),
        "hits": sum(1 for f in res if (f["probability"] >= 0.5) == (f["outcome"] == 1)),
        "brier_system": round(brier(pairs), 4) if pairs else None,
        "n_override": len(ov),
        "brier_override": round(brier([(f["override"], f["outcome"]) for f in ov]), 4) if ov else None,
        "brier_system_same": round(brier([(f["probability"], f["outcome"]) for f in ov]), 4) if ov else None,
        "recal_active": bool(rec.get("active")),
        "recal_k": rec.get("k"),
        "recal_b": rec.get("b"),
        "recal_n": rec.get("n", len(res)),
        "recal_min_n": rec.get("min_n", MIN_N),
    }]
    calib = []
    for lo, hi in BINS:
        b = [(p, o) for p, o in pairs if lo <= p < hi]
        calib.append({
            "band": f"{round(lo * 100)}–{round(min(hi, 1) * 100)}%",
            "lo": lo, "hi": min(hi, 1.0), "n": len(b),
            "mean_stated": round(sum(p for p, _ in b) / len(b), 4) if b else None,
            "share_happened": round(sum(o for _, o in b) / len(b), 4) if b else None,
        })
    groups = defaultdict(list)
    for f in res:
        groups[("Kind", f["kind"])].append((f["probability"], f["outcome"]))
        groups[("Thesis", f["thesis_title"])].append((f["probability"], f["outcome"]))
    grp = [{"key": f"{a}: {g}", "group_type": a, "group": g, "n": len(v), "brier": round(brier(v), 4)}
           for (a, g), v in sorted(groups.items())]
    return summary, calib, grp


def month_end(rows: list[dict], keys: tuple[str, ...], value: str) -> list[dict]:
    """Keep the last observation of each month for each key, plus the latest date."""
    last: dict[tuple, dict] = {}
    for r in rows:
        k = tuple(r[x] for x in keys) + (r["date"][:7],)
        if k not in last or r["date"] > last[k]["date"]:
            last[k] = r
    out = []
    for k, r in sorted(last.items(), key=lambda kv: (kv[1]["date"],) + kv[0][:-1]):
        row = {x: r[x] for x in keys}
        row.update({"date": r["date"], value: num(r[value])})
        out.append(row)
    return out


def labour() -> tuple[list[dict], list[dict], list[dict]]:
    hl = ROOT / "data" / "hiringlab"
    summary = [{
        "key": f"{r['country']}|{r['series']}",
        "country": r["country"], "series": r["series"], "latest_date": r["latest_date"],
        "index_vs_feb_2020": num(r["index_vs_feb_2020"]),
        "change_3m_pct": num(r["change_3m_pct"]), "change_12m_pct": num(r["change_12m_pct"]),
    } for r in read_csv(hl / "summary.csv")]
    sectors = [dict(r, series=r["sector"]) for r in read_csv(hl / "sectors.csv")]
    totals = [dict(r, series="All postings") for r in read_csv(hl / "totals.csv")]
    trend = month_end(sectors + totals, ("country", "series"), "index")
    ai = [r for r in month_end(read_csv(hl / "ai_share.csv"), ("country",), "ai_share") if r["ai_share"] is not None]
    return summary, trend, ai


def career_boards() -> tuple[list[dict], list[dict]]:
    jobs = ROOT / "data" / "jobs"
    counts = read_csv(jobs / "daily_counts.csv")
    if counts:
        latest = max(r["date"] for r in counts)
        agg = defaultdict(int)
        for r in counts:
            if r["date"] == latest:
                agg[(r["role_group"], r["seniority"])] += int(r["open_roles"] or 0)  # all regions
        counts = [{"key": f"{g}|{s}", "date": latest, "role_group": g, "seniority": s, "open_roles": n}
                  for (g, s), n in sorted(agg.items())]
    status = [{"board": r["board"], "date": r["date"], "ok": r["ok"] in ("yes", "True", "true", "1"),
               "open_roles": int(r["open_roles"]) if (r.get("open_roles") or "").isdigit() else None,
               "error": r.get("error") or None} for r in read_csv(jobs / "board_status.csv")]
    return counts, status


PM = "product_management"
LEVELS = ["leadership", "senior", "mid_or_unknown", "junior", "intern"]
IRELAND = ("dublin", "ireland_other")


def product() -> tuple[list[dict], ...]:
    jobs = ROOT / "data" / "jobs"
    boards = {b["board"]: b for b in yaml.safe_load((ROOT / "config" / "career_boards.yaml").read_text())["boards"]}
    counts = read_csv(jobs / "daily_counts.csv")
    if not counts or "region" not in counts[0]:
        return [], [], [], [], []
    for r in counts:
        r["open_roles"] = int(r["open_roles"] or 0)
        r["ai_roles"] = int(r.get("ai_roles") or 0)
    latest = max(r["date"] for r in counts)
    now = [r for r in counts if r["date"] == latest]
    pm = [r for r in now if r["role_group"] == PM]
    tot = lambda rows, f="open_roles": sum(r[f] for r in rows)
    share = lambda a, b: round(a / b, 4) if b else None
    ok_boards = sorted({r["board"] for r in now})
    summary = [{
        "date": latest, "boards": len(ok_boards),
        "all_open": tot(now), "pm_open": tot(pm), "pm_share": share(tot(pm), tot(now)),
        "pm_ai": tot(pm, "ai_roles"), "pm_ai_share": share(tot(pm, "ai_roles"), tot(pm)),
        "pm_ireland": tot([r for r in pm if r["region"] in IRELAND]),
        "pm_dublin": tot([r for r in pm if r["region"] == "dublin"]),
    }]
    levels = [{"level": lv, "order": i, "open_roles": tot([r for r in pm if r["seniority"] == lv]),
               "ireland": tot([r for r in pm if r["seniority"] == lv and r["region"] in IRELAND])}
              for i, lv in enumerate(LEVELS)]
    trend = []
    for d in sorted({r["date"] for r in counts}):
        day = [r for r in counts if r["date"] == d]
        dpm = [r for r in day if r["role_group"] == PM]
        trend.append({"date": d, "boards": len({r["board"] for r in day}), "all_open": tot(day), "pm_open": tot(dpm),
                      "pm_share": share(tot(dpm), tot(day)), "pm_ai_share": share(tot(dpm, "ai_roles"), tot(dpm)),
                      "pm_ireland": tot([r for r in dpm if r["region"] in IRELAND])})
    by_co = []
    for b in ok_boards:
        rows = [r for r in now if r["board"] == b]
        bp = [r for r in rows if r["role_group"] == PM]
        meta = boards.get(b, {})
        by_co.append({"board": b, "company": meta.get("company", b), "ticker": meta.get("ticker"),
                      "all_open": tot(rows), "pm_open": tot(bp), "pm_share": share(tot(bp), tot(rows)),
                      "pm_senior_plus": tot([r for r in bp if r["seniority"] in ("senior", "leadership")]),
                      "pm_junior": tot([r for r in bp if r["seniority"] in ("junior", "intern")]),
                      "pm_ai": tot(bp, "ai_roles"), "pm_ireland": tot([r for r in bp if r["region"] in IRELAND])})
    roles = []
    for b in ok_boards:
        for j in read_csv(jobs / "current" / f"{b}.csv"):
            if j.get("role_group") == PM and j.get("region") in IRELAND:
                roles.append({"key": f"{b}|{j['job_id']}", "company": boards.get(b, {}).get("company", b),
                              "title": j["title"], "level": j["seniority"], "location": j["location"],
                              "ai_related": j.get("ai_related") in ("True", "true", "1"),
                              "updated": (j.get("updated_at") or "")[:10] or None, "url": j.get("url")})
    roles.sort(key=lambda r: (r["company"], r["title"]))
    return summary, levels, trend, by_co, roles


SERIES_TO_INDICATOR = {"UST10Y": "ust10y", "BRENT": "brent", "T5YIFR": "inflation_5y5y"}


def macro() -> tuple[list[dict], ...]:
    import macro_regime as mr
    cfg = mr.config()
    inds = cfg["indicators"]
    series = {i["id"]: mr.load(i) for i in inds}
    manual_src = {}
    for r in read_csv(ROOT / "data" / "macro" / "manual.csv"):
        manual_src[r["series"]] = r.get("source")
    fc = yaml.safe_load((ROOT / "forecasts" / "forecasts.yaml").read_text())["forecasts"]
    linked = defaultdict(list)
    for f in fc:
        rule = ((f.get("resolution") or {}).get("rule") or {})
        ind = SERIES_TO_INDICATOR.get(rule.get("series"))
        if ind and f.get("status") == "open":
            linked[ind].append(f["id"])
    today = TODAY.isoformat()
    rows = []
    for i in inds:
        obs = series[i["id"]]
        latest = obs[-1] if obs else (None, None)
        ago = lambda days: mr.as_of(obs, (TODAY - dt.timedelta(days=days)).isoformat(), 400) if obs else None
        v1, v3 = ago(30), ago(91)
        rows.append({
            "id": i["id"], "name": i["name"], "unit": i["unit"], "in_regime": i["in_regime"],
            "direction": i["direction"], "watch": i["watch"], "stress": i["stress"],
            "latest_date": latest[0], "value": latest[1], "state": mr.state(latest[1], i),
            "change_1m": round(latest[1] - v1, 4) if latest[1] is not None and v1 is not None else None,
            "change_3m": round(latest[1] - v3, 4) if latest[1] is not None and v3 is not None else None,
            "why": i.get("why"), "how": i.get("how"), "linked_forecasts": ", ".join(linked.get(i["id"], [])) or None,
            "source_url": (f"https://fred.stlouisfed.org/series/{i['series']}" if i["source"] == "fred"
                           else manual_src.get(i["series"])),
            "source": "FRED" if i["source"] == "fred" else "Updated by the daily run",
        })
    start = "2023-01-06"
    hist = []
    for i in inds:
        obs = series[i["id"]]
        if not obs:
            continue
        d = dt.date.fromisoformat(start)
        while d <= TODAY:
            v = mr.as_of(obs, d.isoformat(), 400)
            if v is not None:
                hist.append({"key": f"{i['id']}|{d.isoformat()}", "id": i["id"], "date": d.isoformat(), "value": v})
            d += dt.timedelta(days=7)
        hist.append({"key": f"{i['id']}|{obs[-1][0]}|last", "id": i["id"], "date": obs[-1][0], "value": obs[-1][1]})
    reg_hist = mr.history(cfg, series, start, today)
    known_hist = [r for r in reg_hist if r["regime"]]
    states = {r["id"]: r["state"] for r in rows if r["in_regime"]}
    known = sum(1 for v in states.values() if v is not None)
    hy = series.get("hy_spread", [])
    six = (TODAY - dt.timedelta(days=183)).isoformat()
    recent_off = any(r["regime"] == "Risk-off" for r in known_hist if r["date"] >= six)
    label, s_n, w_n = mr.regime(states, hy[-1][1] if hy else None,
                                mr.as_of(hy, (TODAY - dt.timedelta(days=91)).isoformat()) if hy else None, recent_off)
    label = label if known >= 4 else None
    since = None
    for r in reversed(known_hist):
        if r["regime"] != label:
            break
        since = r["date"]
    bands = cfg["regime"]["bands"]
    regime_row = [{
        "as_of": today, "regime": label, "since": since, "stress": s_n, "watch": w_n, "known": known,
        "total": len(states), "size_limit": cfg["regime"]["size_limits"].get(label) if label else None,
        "bands": f"Starter {bands['starter']}%, standard {bands['standard']}%, maximum {bands['maximum']}% (proposed)",
    }]
    return regime_row, rows, hist, [r for r in reg_hist if r["regime"]]


def main() -> None:
    OUT.mkdir(exist_ok=True)
    titles = {yaml.safe_load(p.read_text())["id"]: yaml.safe_load(p.read_text())["title"]
              for p in (ROOT / "theses").glob("*.yaml") if p.stem != "TEMPLATE"}
    fc = forecasts(titles)
    th, _ = theses(fc)
    s, c, g = scores(fc)
    ls, lt, ai = labour()
    cb, bs = career_boards()
    write("insights", insights())
    write("forecasts", fc)
    write("theses", th)
    write("scores", s)
    write("calibration", c)
    write("score_groups", g)
    write("labour_summary", ls)
    write("labour_trend", lt)
    write("ai_share", ai)
    write("career_boards", cb)
    write("board_status", bs)
    ps, pl, pt, pc, pr = product()
    write("product_summary", ps)
    write("product_levels", pl)
    write("product_trend", pt)
    write("product_by_company", pc)
    write("product_roles_ireland", pr)
    mreg, mind, mhist, rhist = macro()
    write("macro_regime", mreg)
    write("macro_indicators", mind)
    write("macro_history", mhist)
    write("regime_history", rhist)


if __name__ == "__main__":
    main()
