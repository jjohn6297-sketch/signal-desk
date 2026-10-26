"""Daily snapshot of public career boards (Greenhouse, Lever, Ashby).

Keeps a small, append-only history instead of full daily copies:
  data/jobs/current/<board>.csv   every open role today
  data/jobs/events/YYYY-MM.csv     one row per role opened or closed
  data/jobs/daily_counts.csv       open roles per board, role group, seniority and region, per day,
                                   with how many of them are AI-related
  data/jobs/board_status.csv       whether each board answered on the last run

Run: python scripts/snapshot_jobs.py [--date YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import sys
import time
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "career_boards.yaml"
OUT = ROOT / "data" / "jobs"
FIELDS = ["job_id", "title", "department", "location", "updated_at", "url", "role_group", "seniority", "region", "ai_related"]
COUNT_FIELDS = ["date", "board", "role_group", "seniority", "region", "open_roles", "ai_roles"]
HEADERS = {"User-Agent": "signal-desk research bot (personal, non-commercial)"}

# Order matters: the first matching group wins. Product comes first so that
# "Product Manager, Customer Support" counts as product, not support.
_NOT_PM = r"(?! ?(marketing|design|analy|engineer|support|counsel|specialist))"
ROLE_GROUPS = [
    ("product_management", r"product manag|product owner|\bproduct lead\b|\bhead of product" + _NOT_PM
     + r"|director,? (of )?product" + _NOT_PM + r"|\b(vp|vice president),? (of )?product" + _NOT_PM
     + r"|chief product officer|\bcpo\b|product operations|\bproduct ops\b|\bapm\b"),
    ("customer_support", r"customer (support|service|success|care)|support (agent|specialist|representative)|call cent|contact cent|help ?desk"),
    ("data_ai", r"machine learning|\bml\b|\bai\b|data scien|data engineer|research scientist|\bllm\b"),
    ("software_engineering", r"software|engineer|developer|\bsre\b|devops|front.?end|back.?end|full.?stack"),
    ("legal", r"legal|counsel|paralegal|attorney|lawyer|contracts? manager|compliance"),
    ("accounting_finance", r"account(ant|ing)|audit|tax\b|controller|bookkeep|financial analyst|\bfp&a\b|payroll"),
    ("sales", r"sales|account executive|business development|\bsdr\b|\bbdr\b"),
    ("marketing_content", r"marketing|content|copywrit|brand|communications|translator|localis|localiz"),
    ("people_admin", r"recruit|talent|\bhr\b|people partner|administrative|assistant|receptionist"),
]
SENIORITY = [
    ("intern", r"\bintern\b|internship|apprentice|graduate|new grad"),
    ("leadership", r"head of|director|\bvp\b|vice president|\bchief\b|\bcpo\b"),
    ("junior", r"\bjunior\b|\bjr\.?\b|associate|entry.level|\bi\b$|\b1\b$"),
    ("senior", r"\bsenior\b|\bsr\.?\b|staff|principal|lead|manager"),
]
# Product managers have "manager" in every title, so they get their own ladder.
PM_LEVELS = [
    ("intern", r"\bintern\b|internship"),
    ("leadership", r"head of|director|\bvp\b|vice president|\bchief\b|\bcpo\b"),
    ("junior", r"associate product|\bapm\b|\bjunior\b|\bjr\.?\b|graduate|rotational|entry.level"),
    ("senior", r"\bsenior\b|\bsr\.?\b|staff|principal|group product|\blead\b"),
]
REGIONS = [
    ("dublin", r"dublin"),
    ("ireland_other", r"ireland|cork|galway|limerick|\bie\b"),
    ("uk", r"london|united kingdom|\buk\b|england|scotland|manchester|edinburgh|belfast"),
    ("us", r"united states|\busa?\b|new york|san francisco|seattle|austin|boston|chicago|denver|atlanta"
           r"|los angeles|bay area|washington|, (ca|ny|wa|tx|ma|il|co|ga|nc|va|fl|or|ut)\b"),
    ("remote", r"remote|anywhere"),
]
AI_RELATED = r"\bai\b|\ba\.i\.|machine learning|\bml\b|\bllms?\b|genai|generative|agentic|ai agent|artificial intelligence"


def region(location: str) -> str:
    text = (location or "").lower()
    return next((r for r, pat in REGIONS if re.search(pat, text)), "other")


def ai_related(title: str, department: str = "") -> bool:
    return bool(re.search(AI_RELATED, f"{title} {department}".lower()))


def classify(title: str, department: str = "") -> tuple[str, str]:
    text = f"{title} {department}".lower()
    group = next((g for g, pat in ROLE_GROUPS if re.search(pat, text)), "other")
    t = title.lower()
    ladder = PM_LEVELS if group == "product_management" else SENIORITY
    level = next((s for s, pat in ladder if re.search(pat, t)), "mid_or_unknown")
    return group, level


def fetch(ats: str, slug: str) -> list[dict]:
    if ats == "greenhouse":
        url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
        data = requests.get(url, headers=HEADERS, timeout=30).json()
        jobs = data["jobs"]
        return [{
            "job_id": str(j["id"]), "title": j.get("title", ""),
            "department": ", ".join(d.get("name", "") for d in j.get("departments", []) or []),
            "location": (j.get("location") or {}).get("name", ""),
            "updated_at": j.get("updated_at", ""), "url": j.get("absolute_url", ""),
        } for j in jobs]
    if ats == "lever":
        url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
        jobs = requests.get(url, headers=HEADERS, timeout=30).json()
        return [{
            "job_id": j["id"], "title": j.get("text", ""),
            "department": (j.get("categories") or {}).get("team", ""),
            "location": (j.get("categories") or {}).get("location", ""),
            "updated_at": str(j.get("createdAt", "")), "url": j.get("hostedUrl", ""),
        } for j in jobs]
    if ats == "ashby":
        url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
        jobs = requests.get(url, headers=HEADERS, timeout=30).json()["jobs"]
        return [{
            "job_id": j["id"], "title": j.get("title", ""), "department": j.get("department", ""),
            "location": j.get("location", ""), "updated_at": j.get("publishedAt", ""), "url": j.get("jobUrl", ""),
        } for j in jobs]
    raise ValueError(f"unknown ATS: {ats}")


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def append_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)


def diff(board: str, today: str, before: list[dict], now: list[dict]) -> list[dict]:
    """Opened and closed events between two snapshots of one board."""
    old = {r["job_id"]: r for r in before}
    cur = {r["job_id"]: r for r in now}
    events = [{"date": today, "board": board, "event": "opened", **cur[k]} for k in cur.keys() - old.keys()]
    events += [{"date": today, "board": board, "event": "closed", **old[k]} for k in old.keys() - cur.keys()]
    return sorted(events, key=lambda e: (e["event"], e["job_id"]))


def counts(board: str, today: str, rows: list[dict]) -> list[dict]:
    tally: dict[tuple[str, str, str], list[int]] = {}
    for r in rows:
        key = (r["role_group"], r["seniority"], r.get("region", "other"))
        t = tally.setdefault(key, [0, 0])
        t[0] += 1
        t[1] += 1 if str(r.get("ai_related")) in ("True", "true", "1") else 0
    return [{"date": today, "board": board, "role_group": g, "seniority": s, "region": rg, "open_roles": n, "ai_roles": a}
            for (g, s, rg), (n, a) in sorted(tally.items())]


def run(today: str) -> int:
    boards = yaml.safe_load(CONFIG.read_text())["boards"]
    status, all_events, all_counts = [], [], []
    for b in boards:
        name = b["board"]
        try:
            jobs = fetch(b["ats"], b["slug"])
        except Exception as exc:  # one broken board must not stop the run
            status.append({"date": today, "board": name, "ats": b["ats"], "slug": b["slug"], "ok": "no", "open_roles": "", "error": str(exc)[:200]})
            continue
        for j in jobs:
            j["role_group"], j["seniority"] = classify(j["title"], j["department"])
            j["region"] = region(j["location"])
            j["ai_related"] = ai_related(j["title"], j["department"])
        cur_path = OUT / "current" / f"{name}.csv"
        before = read_csv(cur_path)
        if before:  # first run sets a baseline; it is not a burst of openings
            all_events += diff(name, today, before, jobs)
        write_csv(cur_path, jobs, FIELDS)
        all_counts += counts(name, today, jobs)
        status.append({"date": today, "board": name, "ats": b["ats"], "slug": b["slug"], "ok": "yes", "open_roles": len(jobs), "error": ""})
        time.sleep(1)  # be polite to the job-board APIs
    month = today[:7]
    append_csv(OUT / "events" / f"{month}.csv", all_events, ["date", "board", "event"] + FIELDS)
    append_csv(OUT / "daily_counts.csv", all_counts, COUNT_FIELDS)
    write_csv(OUT / "board_status.csv", status, ["date", "board", "ats", "slug", "ok", "open_roles", "error"])
    ok = sum(s["ok"] == "yes" for s in status)
    print(f"{today}: {ok}/{len(status)} boards fetched, {len(all_events)} open/close events")
    return 0 if ok else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=dt.date.today().isoformat())
    sys.exit(run(p.parse_args().date))
