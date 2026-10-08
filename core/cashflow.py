"""
Cash-flow source: Finance's "Daily report on cash flow" Google Sheet.

That workbook has ONE TAB PER DAY (named like "03.10", sometimes "25.08 to 28.08")
laid out as a printed report, not a table. Columns shift between tabs, so this
module finds every figure by its LABEL ("1. Cash Position", "Cash Inflow", ...)
instead of by cell address.

Output (load_cashflow):
    daily      — one row per report day: opening / closing balances per account,
                 expected vs actual inflow & outflow, next-7-day obligations,
                 next-14-day expected receivables, reconciliation gap
    collectors — next-14-day expected receivables per collector per day

No Streamlit dependency (the scheduled brief job can use it too).
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date

import numpy as np
import pandas as pd

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}

TAB_RE = re.compile(r"(\d{1,2})\.(\d{1,2})")
TITLE_RE = re.compile(r"Daily Cash Flow Report\s*[–-]\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", re.I)


def is_day_tab(title: str) -> bool:
    """Daily report tabs are named dd.mm (or 'dd.mm to dd.mm'); skip Summary / Report tabs."""
    return bool(TAB_RE.search(title)) and not re.search(r"summary|report", title, re.I)


# ---------------------------------------------------------------------------
# Small grid helpers
# ---------------------------------------------------------------------------

def _num(v) -> float:
    """'  1,215,517.19 ' -> 1215517.19 ;  '  -   ' / '' -> 0 ;  '(500)' -> -500 ; text -> nan."""
    s = str(v).strip()
    if s in ("", "-", "–"):
        return 0.0
    neg = s.startswith("(") and s.endswith(")")
    s = re.sub(r"[₹,\s()]", "", s)
    try:
        x = float(s)
    except ValueError:
        return np.nan
    return -x if neg else x


def _norm(v) -> str:
    return re.sub(r"\s+", " ", str(v)).strip().lower()


def _cell(rows, r, c) -> str:
    return rows[r][c] if 0 <= r < len(rows) and 0 <= c < len(rows[r]) else ""


def _find(rows, pattern, start=0, col=None):
    """First (row, col) whose cell matches regex `pattern` (case-insensitive)."""
    rx = re.compile(pattern, re.I)
    for r in range(start, len(rows)):
        cols = [col] if col is not None else range(len(rows[r]))
        for c in cols:
            if rx.search(_norm(_cell(rows, r, c))):
                return r, c
    return None


def _value_right(rows, r, c, span=3) -> float:
    """Numeric value just to the right of a label (skips blank cells)."""
    for k in range(1, span + 1):
        raw = str(_cell(rows, r, c + k)).strip()
        if raw == "":
            continue
        x = _num(raw)
        if not np.isnan(x):
            return x
    return np.nan


def _block(rows, header_pat, labels: dict, depth=10) -> dict:
    """
    Read a vertical 'label | amount' block under a section header.
    labels = {"cash": r"^cash$", ...}; looks only in the header's column.
    """
    hit = _find(rows, header_pat)
    out = {k: np.nan for k in labels}
    if not hit:
        return out
    r0, c0 = hit
    for r in range(r0 + 1, min(r0 + 1 + depth, len(rows))):
        lab = _norm(_cell(rows, r, c0))
        for k, pat in labels.items():
            if np.isnan(out[k]) and re.search(pat, lab):
                out[k] = _value_right(rows, r, c0)
    return out


ACCOUNTS = {"cash": r"^cash$", "federal": r"^federal", "sbi": r"^sbi", "total": r"^total$"}


# ---------------------------------------------------------------------------
# One tab -> one record
# ---------------------------------------------------------------------------

def _tab_date(title: str, rows, fallback_year: int) -> pd.Timestamp | None:
    """Date from the TAB NAME (titles inside are sometimes copied and stale); year from the title row."""
    found = TAB_RE.findall(title)
    if not found:
        return None
    d, m = map(int, found[-1])                     # '25.08 to 28.08' -> 28.08 (last day of the block)
    year = fallback_year
    hit = _find(rows[:4], r"daily cash flow report")
    if hit:
        t = TITLE_RE.search(str(_cell(rows, *hit)))
        if t:
            year = int(t.group(3))
    try:
        return pd.Timestamp(date(year, m, d))
    except ValueError:
        return None


def parse_day(title: str, rows: list[list[str]], fallback_year: int | None = None) -> dict | None:
    fallback_year = fallback_year or date.today().year
    dt = _tab_date(title, rows, fallback_year)
    if dt is None:
        return None
    rec = {"date": dt, "tab": title}

    op = _block(rows, r"^1\.\s*cash position", ACCOUNTS, depth=6)
    cl = _block(rows, r"^5\.\s*closing balance", ACCOUNTS, depth=8)
    for k in ACCOUNTS:
        rec[f"open_{k}"] = op[k]
        rec[f"close_{k}"] = cl[k]

    # Expected vs actual movements ("Today's cash movements" table)
    rec.update(inflow_exp=np.nan, inflow_act=np.nan, outflow_exp=np.nan, outflow_act=np.nan)
    hit = _find(rows, r"^today'?s cash movements")
    if hit:
        r0, c0 = hit
        hdr = _find(rows, r"^expected$", start=r0 + 1)
        if hdr and hdr[0] <= r0 + 3:
            hr = hdr[0]
            ce = hdr[1]
            ca = next((c for c in range(ce + 1, ce + 4) if _norm(_cell(rows, hr, c)) == "actual"), ce + 1)
            for r in range(hr + 1, min(hr + 5, len(rows))):
                lab = _norm(_cell(rows, r, c0))
                if lab == "cash inflow":
                    rec["inflow_exp"], rec["inflow_act"] = _num(_cell(rows, r, ce)), _num(_cell(rows, r, ca))
                elif lab == "cash outflow":
                    rec["outflow_exp"], rec["outflow_act"] = _num(_cell(rows, r, ce)), _num(_cell(rows, r, ca))
    # Early tabs (before 06.03) only have the plan in section 2
    if np.isnan(rec["inflow_exp"]):
        mv = _block(rows, r"^2\.\s*(expected )?cash movement",
                    {"in": r"^add: receivables", "out": r"^less: payments"}, depth=6)
        rec["inflow_exp"], rec["outflow_exp"] = mv["in"], mv["out"]

    # Next 7 days obligations: the 'Total' line of section 3
    ob = _block(rows, r"^3\.\s*upcoming cash obligations", {"total": r"^total$", "regular": r"^regular payments",
                                                              "purchase": r"^aneesh"}, depth=8)
    rec["oblig_7d"], rec["oblig_regular"], rec["oblig_purchase"] = ob["total"], ob["regular"], ob["purchase"]

    # Next 14 days expected receivables, per collector
    coll = {}
    hit = _find(rows, r"^4\.\s*expected receivables")
    if hit:
        r0, c0 = hit
        for r in range(r0 + 1, min(r0 + 12, len(rows))):
            lab = str(_cell(rows, r, c0)).strip()
            if not lab:
                continue
            if _norm(lab) == "total":
                rec["recv_14d"] = _value_right(rows, r, c0)
                break
            v = _value_right(rows, r, c0)
            coll[lab.title()] = 0.0 if np.isnan(v) else v
    rec.setdefault("recv_14d", sum(coll.values()) if coll else np.nan)
    rec["_collectors"] = coll
    return rec


# ---------------------------------------------------------------------------
# Whole workbook -> DataFrames
# ---------------------------------------------------------------------------

EXCL_TAB = "Exclusions"


def parse_exclusions(rows: list[list[str]]) -> pd.DataFrame:
    """'Exclusions' tab: Date | In / Out | Amount | Category | Party | Reason | Added by | Approved."""
    cols = ["date", "direction", "amount", "category", "party", "reason", "added_by", "approved"]
    hdr = next((i for i, r in enumerate(rows[:10]) if r and _norm(r[0]) == "date"), None)
    if hdr is None:
        return pd.DataFrame(columns=cols)
    body = [list(r) + [""] * (8 - len(r)) for r in rows[hdr + 1:]]
    e = pd.DataFrame([r[:8] for r in body], columns=cols)
    e["date"] = pd.to_datetime(e["date"].astype(str).str.strip(), dayfirst=True, format="mixed", errors="coerce")
    e["amount"] = e["amount"].map(_num)
    e["direction"] = e["direction"].astype(str).str.strip().str.title()
    e["approved"] = e["approved"].astype(str).str.strip().str.upper().isin(["TRUE", "YES", "Y", "1", "✓"])
    e = e.dropna(subset=["date"])
    e = e[(e["amount"] > 0) & e["direction"].isin(["Inflow", "Outflow"])]
    return e.reset_index(drop=True)


def build_frames(tabs: dict[str, list[list[str]]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    d, c = _build_days(tabs)
    excl = parse_exclusions(tabs.get(EXCL_TAB, []))
    if not d.empty:
        d = apply_exclusions(d, excl)
    d.attrs["exclusions"] = excl
    return d, c


def apply_exclusions(d: pd.DataFrame, excl: pd.DataFrame) -> pd.DataFrame:
    """Operating figures = actual minus APPROVED non-operating items (pending ones shown separately)."""
    d = d.copy()
    for key, ok in (("excl", True), ("pending", False)):
        for side, direction in (("in", "Inflow"), ("out", "Outflow")):
            e = excl[(excl["approved"] == ok) & (excl["direction"] == direction)] if not excl.empty else excl
            amt = e.groupby("date")["amount"].sum() if not e.empty else pd.Series(dtype=float)
            d[f"{key}_{side}"] = d["date"].map(amt).fillna(0.0)
    d["inflow_op"] = d["inflow_act"] - d["excl_in"]
    d["outflow_op"] = d["outflow_act"] - d["excl_out"]
    d["net_op"] = d["inflow_op"] - d["outflow_op"]
    return d


def _build_days(tabs: dict[str, list[list[str]]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    recs = []
    for title, rows in tabs.items():
        if not is_day_tab(title):
            continue
        rec = parse_day(title, rows)
        if rec:
            recs.append(rec)
    if not recs:
        return pd.DataFrame(), pd.DataFrame()

    coll_rows = [{"date": r["date"], "collector": k, "expected_14d": v}
                 for r in recs for k, v in r.pop("_collectors").items()]
    d = pd.DataFrame(recs).sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)

    # Fill totals that were left blank
    for side in ("open", "close"):
        parts = d[[f"{side}_cash", f"{side}_federal", f"{side}_sbi"]]
        d[f"{side}_total"] = d[f"{side}_total"].where(d[f"{side}_total"].notna() & (d[f"{side}_total"] != 0),
                                                      parts.sum(axis=1, min_count=1))
    d["net_exp"] = d["inflow_exp"].fillna(0) - d["outflow_exp"].fillna(0)
    d["net_act"] = d["inflow_act"] - d["outflow_act"]
    d["has_actual"] = d["inflow_act"].notna() & ((d["inflow_act"] != 0) | (d["outflow_act"].fillna(0) != 0))
    d["balance_change"] = d["close_total"] - d["open_total"]
    # Opening + actual in - actual out should equal closing; the gap = unrecorded movement
    d["recon_gap"] = np.where(d["has_actual"], d["close_total"] - (d["open_total"] + d["net_act"]), np.nan)
    # Did today's opening match yesterday's closing?
    d["carry_gap"] = d["open_total"] - d["close_total"].shift(1)
    d["week"] = d["date"].dt.to_period("W-SAT").dt.start_time      # Sun–Sat weeks (Sunlit works Mon–Sat)
    d["month"] = d["date"].dt.to_period("M").dt.to_timestamp()

    c = pd.DataFrame(coll_rows)
    if not c.empty:
        c = c.sort_values("date").drop_duplicates(["date", "collector"], keep="last").reset_index(drop=True)
    return d, c


def weekly(d: pd.DataFrame) -> pd.DataFrame:
    """Week-wise inflow / outflow / net (actuals) for the Finance KPIs."""
    if d.empty:
        return d
    inc, out = ("inflow_op", "outflow_op") if "inflow_op" in d else ("inflow_act", "outflow_act")
    w = d.groupby("week").agg(days=("date", "count"),
                              inflow=(inc, "sum"), outflow=(out, "sum"),
                              inflow_exp=("inflow_exp", "sum"), outflow_exp=("outflow_exp", "sum"),
                              closing=("close_total", "last")).reset_index()
    w["net"] = w["inflow"] - w["outflow"]
    w["inflow_accuracy"] = np.where(w["inflow_exp"] > 0, w["inflow"] / w["inflow_exp"] * 100, np.nan)
    return w


def collector_accuracy(d: pd.DataFrame) -> pd.DataFrame:
    """Expected vs actual inflow totals per month (forecast discipline)."""
    if d.empty:
        return d
    m = d[d["has_actual"]].groupby("month").agg(expected=("inflow_exp", "sum"), actual=("inflow_act", "sum"),
                                                pay_exp=("outflow_exp", "sum"), pay_act=("outflow_act", "sum")).reset_index()
    m["inflow_var_pct"] = (m["actual"] - m["expected"]) / m["expected"].replace(0, np.nan) * 100
    m["outflow_var_pct"] = (m["pay_act"] - m["pay_exp"]) / m["pay_exp"].replace(0, np.nan) * 100
    return m


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------

def parse_dump(text: str) -> dict[str, list[list[str]]]:
    """Offline mode: a text export with '## Sheet name: <tab>' before each tab's CSV."""
    parts = re.split(r"^## Sheet name: (.*)$", text, flags=re.M)
    return {parts[i].strip(): list(csv.reader(io.StringIO(parts[i + 1].strip("\n"))))
            for i in range(1, len(parts), 2)}


def _guess_date(title: str) -> pd.Timestamp:
    """Tab name -> date; a dd.mm later than ~next week is taken as last year."""
    d, m = map(int, TAB_RE.findall(title)[-1])
    today = pd.Timestamp.today().normalize()
    try:
        t = pd.Timestamp(date(today.year, m, d))
    except ValueError:
        return pd.Timestamp.min
    return t if t <= today + pd.Timedelta(days=7) else t - pd.DateOffset(years=1)


def read_workbook(book, max_tabs: int = 150) -> dict[str, list[list[str]]]:
    """Live mode: read the latest `max_tabs` daily tabs of a gspread Spreadsheet in ONE API call."""
    sheets = [ws.title for ws in book.worksheets()]
    titles = [t for t in sheets if is_day_tab(t)]
    titles = sorted(titles, key=_guess_date)            # tabs are not always in date order
    titles = titles[-max_tabs:] if max_tabs else titles
    if not titles:
        return {}
    if EXCL_TAB in sheets:
        titles = titles + [EXCL_TAB]
    ranges = [f"'{t}'!A1:Z300" for t in titles]
    res = book.values_batch_get(ranges)
    out = {}
    for t, vr in zip(titles, res.get("valueRanges", [])):
        out[t] = vr.get("values", [])
    return out


# ---------------------------------------------------------------------------
# Company monthly target — Net Operating Cash Flow
# ---------------------------------------------------------------------------

def working_days(start: pd.Timestamp, end: pd.Timestamp) -> int:
    """Mon–Sat days from start to end inclusive (Sunlit works Mon–Sat)."""
    if end < start:
        return 0
    days = pd.date_range(start, end, freq="D")
    return int((days.dayofweek < 6).sum())


def month_tracker(d: pd.DataFrame, cfg: dict) -> dict | None:
    """Progress of the month in cfg['month'] ('YYYY-MM') towards cfg['target']."""
    m0 = pd.Timestamp(cfg["month"] + "-01")
    m1 = m0 + pd.offsets.MonthEnd(0)
    mm = d[(d["date"] >= m0) & (d["date"] <= m1) & d["has_actual"]].copy()
    if mm.empty:
        return None
    last = mm["date"].max()
    mm["cum_net"] = mm["net_op"].cumsum()
    mtd = float(mm["net_op"].sum())
    done = working_days(m0, last)
    left = working_days(last + pd.Timedelta(days=1), m1)
    total = done + left
    run_rate = mtd / done * total if done else np.nan
    need = cfg["target"] - mtd
    # what the same month-end window paid out last month (salary, statutory, OD interest ...)
    p0 = m0 - pd.DateOffset(months=1)
    prev = d[(d["date"] >= p0 + pd.Timedelta(days=24)) & (d["date"] < m0)]
    return {
        "month": m0, "month_end": m1, "last_day": last, "days": mm,
        "mtd": mtd, "inflow": float(mm["inflow_op"].sum()), "outflow": float(mm["outflow_op"].sum()),
        "excluded_in": float(mm["excl_in"].sum()), "excluded_out": float(mm["excl_out"].sum()),
        "pending_in": float(mm["pending_in"].sum()), "pending_out": float(mm["pending_out"].sum()),
        "pct": mtd / cfg["target"] * 100,
        "done_days": done, "left_days": left, "need": need,
        "need_per_day": need / left if left else np.nan,
        "run_rate": run_rate,
        "prev_month_end_out": float(prev["outflow_act"].sum()) if not prev.empty else np.nan,
        "prev_month_end_net": float((prev["inflow_act"] - prev["outflow_act"]).sum()) if not prev.empty else np.nan,
    }
