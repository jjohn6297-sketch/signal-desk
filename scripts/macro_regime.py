"""Indicator states and the macro regime, from config/macro.yaml and data/macro/.

Used by build_dashboard.py. The rules are in config/macro.yaml; this module only applies them.
"""
from __future__ import annotations

import bisect
import csv
import datetime as dt
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "macro"


def config() -> dict:
    return yaml.safe_load((ROOT / "config" / "macro.yaml").read_text())


def load(ind: dict, data_dir: Path = DATA) -> list[tuple[str, float]]:
    """Observations for one indicator, oldest first."""
    if ind["source"] == "fred":
        path = data_dir / f"{ind['series']}.csv"
        if not path.exists():
            return []
        with path.open(encoding="utf-8") as f:
            return sorted((r["date"], float(r["value"])) for r in csv.DictReader(f) if r["value"] not in ("", "."))
    path = data_dir / "manual.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        rows = [(r["date"], float(r["value"])) for r in csv.DictReader(f)
                if r["series"] == ind["series"] and r["value"] not in ("", ".")]
    return sorted(dict(rows).items())


def state(value: float | None, ind: dict) -> str | None:
    if value is None:
        return None
    worse = (lambda v, t: v >= t) if ind["direction"] == "above" else (lambda v, t: v <= t)
    if worse(value, ind["stress"]):
        return "stress"
    if worse(value, ind["watch"]):
        return "watch"
    return "normal"


def as_of(obs: list[tuple[str, float]], date: str, max_age_days: int = 120) -> float | None:
    """Last value on or before `date`, if it is not older than `max_age_days`."""
    dates = [d for d, _ in obs]
    i = bisect.bisect_right(dates, date) - 1
    if i < 0:
        return None
    if (dt.date.fromisoformat(date) - dt.date.fromisoformat(dates[i])).days > max_age_days:
        return None
    return obs[i][1]


def regime(states: dict[str, str | None], hy_now: float | None, hy_3m_ago: float | None,
           risk_off_in_last_6m: bool) -> tuple[str, int, int]:
    """Apply the rules in config/macro.yaml to the regime indicators' states."""
    stress = sum(1 for s in states.values() if s == "stress")
    watch = sum(1 for s in states.values() if s == "watch")
    if stress >= 2:
        return "Risk-off", stress, watch
    if risk_off_in_last_6m and stress <= 1 and hy_now is not None and hy_3m_ago is not None and hy_now < hy_3m_ago:
        return "Recovery", stress, watch
    if stress == 1 or watch >= 3:
        return "Late cycle", stress, watch
    return "Risk-on", stress, watch


def history(cfg: dict, series: dict[str, list[tuple[str, float]]], start: str, end: str) -> list[dict]:
    """Regime each Friday from `start` to `end`, using values known on that day."""
    inds = [i for i in cfg["indicators"] if i["in_regime"]]
    hy = series.get("hy_spread", [])
    d = dt.date.fromisoformat(start)
    d += dt.timedelta(days=(4 - d.weekday()) % 7)
    out: list[dict] = []
    while d.isoformat() <= end:
        day = d.isoformat()
        states = {i["id"]: state(as_of(series.get(i["id"], []), day), i) for i in inds}
        known = sum(1 for s in states.values() if s is not None)
        six_months = (d - dt.timedelta(days=183)).isoformat()
        recent_off = any(r["regime"] == "Risk-off" for r in out if r["date"] >= six_months)
        three_m = (d - dt.timedelta(days=91)).isoformat()
        label, s, w = regime(states, as_of(hy, day), as_of(hy, three_m), recent_off)
        out.append({"date": day, "regime": label if known >= 4 else None, "stress": s, "watch": w, "known": known})
        d += dt.timedelta(days=7)
    return out
