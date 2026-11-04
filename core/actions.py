"""
Phase 2 — Early-Warning & Action Loop.

The Sunlit Alert Tracker (Google Sheet + Apps Script) raises the alerts every
morning and owners record actions in its web form. This module turns its
Alert_Log into the management view:

    Data -> Trend -> Risk -> Alert -> OWNER -> ACTION -> did it happen within 7 days?

The weekly scoring follows the tracker's own rules (scoreWeek_ in Code.gs):
weeks run Monday-Saturday, "Closed (out of scope)" alerts are excluded, and an
alert counts as acted on time when its first action came within ACT_WITHIN_DAYS.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.config import ACT_WITHIN_DAYS

OUT_OF_SCOPE = "Closed (out of scope)"
TYPE_ORDER = ["Receivable", "Slow Moving", "Low RM Cover"]

# Outcome of one alert, as of today
ON_TIME, LATE, PENDING, MISSED, AUTO = "Acted ≤ 7 days", "Acted late", "Waiting (within 7 days)", "No action > 7 days", "Resolved without action"
OUTCOMES = [ON_TIME, LATE, PENDING, MISSED, AUTO]


def today() -> pd.Timestamp:
    return pd.Timestamp.today().normalize()


def week_start(d: pd.Series) -> pd.Series:
    """Monday of the week (Sunday belongs to the week before, like the tracker)."""
    return (d - pd.to_timedelta(d.dt.dayofweek, unit="D")).dt.normalize()


def prepare(log: pd.DataFrame, as_of: pd.Timestamp | None = None, within: int = ACT_WITHIN_DAYS) -> pd.DataFrame:
    """Alert_Log + age, outcome and week. Out-of-scope alerts are dropped."""
    if log is None or log.empty:
        return pd.DataFrame()
    as_of = as_of or today()
    a = log[log["status"] != OUT_OF_SCOPE].copy()
    a["closed_flag"] = a["status"].str.startswith("Closed")
    a["acted"] = a["days_to_act"].notna()
    end = a["closed"].where(a["closed_flag"] & ~a["acted"], as_of).fillna(as_of)
    a["age"] = (end - a["raised"]).dt.days.clip(lower=0)
    a["outcome"] = np.select(
        [a["acted"] & (a["days_to_act"] <= within),
         a["acted"],
         a["closed_flag"],
         (as_of - a["raised"]).dt.days <= within],
        [ON_TIME, LATE, AUTO, PENDING],
        default=MISSED,
    )
    a["week"] = week_start(a["raised"])
    a["open_no_action"] = ~a["acted"] & ~a["closed_flag"]
    a["overdue"] = a["open_no_action"] & ((as_of - a["raised"]).dt.days > within)
    a["change_pct"] = np.where(a["amount"] > 0, (a["latest"] - a["amount"]) / a["amount"] * 100, np.nan)
    return a


def weekly(a: pd.DataFrame, by_type: bool = False, as_of: pd.Timestamp | None = None,
           within: int = ACT_WITHIN_DAYS) -> pd.DataFrame:
    """One row per week (Mon-Sat): raised, outcome counts, % acted within 7 days, final or in progress."""
    if a.empty:
        return pd.DataFrame()
    as_of = as_of or today()
    keys = ["week", "type"] if by_type else ["week"]
    g = a.groupby(keys + ["outcome"]).size().unstack("outcome", fill_value=0)
    for o in OUTCOMES:
        if o not in g:
            g[o] = 0
    g = g[OUTCOMES].reset_index()
    g["raised"] = g[OUTCOMES].sum(axis=1)
    g["pct_on_time"] = np.where(g["raised"] > 0, g[ON_TIME] / g["raised"] * 100, np.nan)
    # a week is final once its Saturday alert has had its full 7 days
    g["week_end"] = g["week"] + pd.Timedelta(days=5)
    g["final"] = as_of > g["week_end"] + pd.Timedelta(days=within)
    return g.sort_values(keys).reset_index(drop=True)


def owner_view(a: pd.DataFrame, weeks: int = 4, as_of: pd.Timestamp | None = None) -> pd.DataFrame:
    """Per owner: open now, overdue without action, and acted-on-time % over the last N weeks."""
    if a.empty:
        return pd.DataFrame()
    as_of = as_of or today()
    since = as_of - pd.Timedelta(days=7 * weeks)
    live = a[~a["closed_flag"]]
    recent = a[a["raised"] >= since]
    out = pd.DataFrame({
        "open_alerts": live.groupby("owner").size(),
        "waiting_action": live[live["open_no_action"]].groupby("owner").size(),
        "overdue_no_action": live[live["overdue"]].groupby("owner").size(),
        "value_open": live.groupby("owner")["latest"].sum(),
        "raised_recent": recent.groupby("owner").size(),
        "on_time_recent": recent[recent["outcome"] == ON_TIME].groupby("owner").size(),
        "decided_recent": recent[recent["outcome"] != PENDING].groupby("owner").size(),
    }).fillna(0)
    out["pct_on_time"] = np.where(out["decided_recent"] > 0, out["on_time_recent"] / out["decided_recent"] * 100, np.nan)
    types = a.groupby("owner")["type"].agg(lambda s: ", ".join(t for t in TYPE_ORDER if t in set(s)))
    out = out.join(types.rename("alert_types"))
    int_cols = ["open_alerts", "waiting_action", "overdue_no_action", "raised_recent", "on_time_recent", "decided_recent"]
    out[int_cols] = out[int_cols].astype(int)
    return out.reset_index().rename(columns={"index": "owner"}).sort_values(
        ["overdue_no_action", "open_alerts"], ascending=False).reset_index(drop=True)


def kpis(a: pd.DataFrame, as_of: pd.Timestamp | None = None) -> dict:
    if a.empty:
        return {}
    as_of = as_of or today()
    live = a[~a["closed_flag"]]
    wk = weekly(a, as_of=as_of)
    fin = wk[wk["final"]]
    last = fin.iloc[-1] if not fin.empty else None
    prev = fin.iloc[-2] if len(fin) > 1 else None
    promise_due = live[(live["status"] == "Actioned") & live["promise"].notna() & (live["promise"] <= as_of)]
    return {
        "open": len(live),
        "open_value": live["latest"].sum(),
        "waiting": int(live["open_no_action"].sum()),
        "overdue": int(live["overdue"].sum()),
        "promise_due": len(promise_due),
        "last_week": last["week"] if last is not None else None,
        "last_pct": last["pct_on_time"] if last is not None else np.nan,
        "prev_pct": prev["pct_on_time"] if prev is not None else np.nan,
        "raised_7d": int((a["raised"] > as_of - pd.Timedelta(days=7)).sum()),
        "rising": int(live["trend"].str.startswith("▲").sum()),
    }
