"""
Centralised BI data layer.

Reads every source sheet as a raw grid (list of rows), finds the real header
row, and converts it into a clean, typed pandas DataFrame with standard
column names. The same code path is used for:
  * live Google Sheets (service account via gspread)
  * local CSV snapshots (for offline testing: set SUNLIT_BI_LOCAL_DIR)

This module has no Streamlit dependency so the scheduled brief job can use it.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from core.cashflow import build_frames, parse_dump, read_workbook
from core.config import CASHFLOW, SHEETS

# ---------------------------------------------------------------------------
# Raw readers
# ---------------------------------------------------------------------------

def _service_account_info(secrets=None) -> dict | None:
    """Service-account JSON from Streamlit secrets or the environment."""
    if secrets is not None:
        try:
            if "gcp_service_account" in secrets:
                return dict(secrets["gcp_service_account"])
        except Exception:
            pass
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if raw:
        return json.loads(raw)
    return None


class SheetReader:
    """Returns raw rows for a (sheet_id, tab). Caches opened spreadsheets."""

    def __init__(self, secrets=None):
        self.local_dir = os.environ.get("SUNLIT_BI_LOCAL_DIR")
        self._gc = None
        self._books = {}
        info = None if self.local_dir else _service_account_info(secrets)
        if not self.local_dir and not info:
            # No Google login yet -> fall back to the bundled test data (demo mode)
            demo = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "test_data")
            if os.path.isdir(demo):
                self.local_dir = demo
        self.test_mode = bool(self.local_dir)
        if not self.local_dir:
            if not info:
                raise RuntimeError(
                    "No Google credentials found. Add [gcp_service_account] to "
                    ".streamlit/secrets.toml (see SETUP_GUIDE.md) or set "
                    "SUNLIT_BI_LOCAL_DIR for offline testing."
                )
            import gspread
            self._gc = gspread.service_account_from_dict(info)

    def rows(self, key: str) -> list[list[str]]:
        cfg = SHEETS[key]
        if self.local_dir:
            path = os.path.join(self.local_dir, f"{key}.csv")
            if not os.path.exists(path):
                raise FileNotFoundError(f"{path} not found")
            return pd.read_csv(path, header=None, dtype=str, keep_default_na=False).values.tolist()
        sid = cfg["sheet_id"]
        if sid not in self._books:
            self._books[sid] = self._gc.open_by_key(sid)
        ws = self._books[sid].worksheet(cfg["tab"])
        return ws.get_all_values()

    def cashflow_tabs(self) -> dict[str, list[list[str]]]:
        """All daily tabs of the Finance cash-flow workbook ({tab name: rows})."""
        if self.local_dir:
            path = os.path.join(self.local_dir, "cashflow.txt")    # '## Sheet name: <tab>' export
            if not os.path.exists(path):
                raise FileNotFoundError(f"{path} not found")
            with open(path, encoding="utf-8") as f:
                return parse_dump(f.read())
        sid = CASHFLOW["sheet_id"]
        if sid not in self._books:
            self._books[sid] = self._gc.open_by_key(sid)
        return read_workbook(self._books[sid], CASHFLOW.get("max_tabs", 200))


# ---------------------------------------------------------------------------
# Cleaning helpers
# ---------------------------------------------------------------------------

def grid_to_df(rows: list[list[str]], header_hint: str, scan: int = 12) -> pd.DataFrame:
    """Locate the header row (first row containing header_hint) and build a DataFrame."""
    hint = header_hint.strip().lower()
    hdr_idx = None
    for i, r in enumerate(rows[:scan]):
        if any(str(c).strip().lower() == hint for c in r):
            hdr_idx = i
            break
    if hdr_idx is None:
        raise ValueError(f"Header row with '{header_hint}' not found in first {scan} rows")
    header = [str(c).strip() for c in rows[hdr_idx]]
    # de-duplicate / fill blank header names
    seen, cols = {}, []
    for j, h in enumerate(header):
        h = h or f"_col{j}"
        if h in seen:
            seen[h] += 1
            h = f"{h}_{seen[h]}"
        else:
            seen[h] = 0
        cols.append(h)
    body = [r + [""] * (len(cols) - len(r)) for r in rows[hdr_idx + 1:]]
    body = [r[: len(cols)] for r in body]
    df = pd.DataFrame(body, columns=cols)
    # drop repeated header rows and fully blank rows
    first = cols[0]
    df = df[df[first].astype(str).str.strip().str.lower() != header[0].lower() if header[0] else True]
    df = df[~(df.astype(str).apply(lambda s: s.str.strip()).eq("").all(axis=1))]
    return df.reset_index(drop=True)


_NUM_RE = re.compile(r"[₹,\s%]")


def to_num(s: pd.Series) -> pd.Series:
    s = s.astype(str).str.strip()
    neg = s.str.match(r"^\(.*\)$")
    s = s.str.replace(r"[()]", "", regex=True).str.replace(_NUM_RE, "", regex=True)
    s = s.replace({"": np.nan, "-": np.nan, "#N/A": np.nan, "#VALUE!": np.nan, "#REF!": np.nan})
    out = pd.to_numeric(s, errors="coerce")
    return out.where(~neg, -out)


def to_date(s: pd.Series) -> pd.Series:
    s = s.astype(str).str.strip().replace({"": None})
    return pd.to_datetime(s, dayfirst=True, format="mixed", errors="coerce")


def pick(df: pd.DataFrame, *names: str, required: bool = True) -> str | None:
    """Find a column by any of several names (case/space-insensitive)."""
    norm = {re.sub(r"[^a-z0-9]", "", c.lower()): c for c in df.columns}
    for n in names:
        k = re.sub(r"[^a-z0-9]", "", n.lower())
        if k in norm:
            return norm[k]
    if required:
        raise KeyError(f"None of {names} found. Columns: {list(df.columns)[:25]}")
    return None


def clean_party(s: pd.Series) -> pd.Series:
    return s.astype(str).str.split("|").str[0].str.strip()


def code_str(s: pd.Series) -> pd.Series:
    """Normalise item / dealer codes: '80001.0' -> '80001', keep '10099.1'."""
    s = s.astype(str).str.strip()
    return s.str.replace(r"\.0$", "", regex=True)


def category_from_name(name: pd.Series) -> pd.Series:
    return name.astype(str).str.strip().str.split(r"[\s\-]").str[0].str.title()


# ---------------------------------------------------------------------------
# Typed loaders — one per source
# ---------------------------------------------------------------------------

def load_sales(rows) -> pd.DataFrame:
    d = grid_to_df(rows, SHEETS["sales"]["header_hint"])
    out = pd.DataFrame({
        "voucher": d[pick(d, "Voucher Number")].str.strip(),
        "date": to_date(d[pick(d, "Sale Date", "Date")]),
        "vtype": d[pick(d, "Voucher Type")].str.strip(),
        "cust_code": code_str(d[pick(d, "Cust Code", "Dealer Code")]),
        "party": clean_party(d[pick(d, "Party Name")]),
        "item_code": code_str(d[pick(d, "Item Code")]),
        "category": d[pick(d, "Item Cat", "Category")].str.strip(),
        "item": d[pick(d, "Item Name")].str.split("//").str[0].str.strip(),
        "qty": to_num(d[pick(d, "Billed Quantity", "Qty")]),
        "rate": to_num(d[pick(d, "Rate")]),
        "cost_rate": to_num(d[pick(d, "Purchase Rate")]),
        "discount_pct": to_num(d[pick(d, "Discount")]).fillna(0),
        "discount_amt": to_num(d[pick(d, "Discount Amount")]).fillna(0),
        "margin": to_num(d[pick(d, "Margin")]),
        "amount": to_num(d[pick(d, "Amount")]),
    })
    out = out.dropna(subset=["date", "amount"])
    out["category"] = out["category"].replace("", "Others")
    out["month"] = out["date"].dt.to_period("M").dt.to_timestamp()
    out["margin_pct"] = np.where(out["amount"] > 0, out["margin"] / out["amount"] * 100, np.nan)
    return out.reset_index(drop=True)


def load_customers(rows) -> pd.DataFrame:
    d = grid_to_df(rows, SHEETS["customers"]["header_hint"])
    return pd.DataFrame({
        "dealer_code": code_str(d[pick(d, "Dealer Code")]),
        "dealer": d[pick(d, "Dealer Name")].str.strip(),
        "executive": d[pick(d, "Executive")].str.strip().replace("", "Unassigned"),
        "avg_gap": to_num(d[pick(d, "Avg Gap (days)", required=False)]) if pick(d, "Avg Gap (days)", required=False) else np.nan,
        "last12m": to_num(d[pick(d, "Last 12M Billing", required=False)]) if pick(d, "Last 12M Billing", required=False) else np.nan,
        "status": d[pick(d, "Status")].str.strip() if pick(d, "Status", required=False) else "",
    }).drop_duplicates("dealer_code")


def load_exec_targets(rows) -> pd.DataFrame:
    d = grid_to_df(rows, SHEETS["exec_targets"]["header_hint"])
    tcol = pick(d, "Current Month Target", required=False)
    return pd.DataFrame({
        "executive": d[pick(d, "Executive")].str.strip(),
        "target": to_num(d[tcol]) if tcol else np.nan,
    })


def load_rm_stock(rows) -> pd.DataFrame:
    d = grid_to_df(rows, SHEETS["rm_stock"]["header_hint"])
    out = pd.DataFrame({
        "item_code": code_str(d[pick(d, "Item Code")]),
        "item": d[pick(d, "Item Name")].str.strip(),
        "unit": d[pick(d, "Unit")].str.strip().replace("#N/A", ""),
        "tally_qty": to_num(d[pick(d, "Tally Stock Qty")]),
        "rate": to_num(d[pick(d, "Rate")]).fillna(0),
        "phy_qty": to_num(d[pick(d, "Physical Stock Qty")]),
        "phy_date": to_date(d[pick(d, "Phy.St.Date")]),
        "need_30d": to_num(d[pick(d, "Net RM Requirement (30D)")]),
        "daily_req": to_num(d[pick(d, "Daily RM Requirement")]),
        "coverage_days": to_num(d[pick(d, "Stock Coverage (Days)")]),
        "lead_time": to_num(d[pick(d, "Lead Time (Days)")]),
        "excess_shortage": to_num(d[pick(d, "Excess / Shortage")]),
        "status": d[pick(d, "Status")].str.replace(r"[^\w\s/]", "", regex=True).str.strip().str.upper(),
        "priority": to_num(d[pick(d, "Priority")]),
        "order_due": to_date(d[pick(d, "Order Due Date")]),
        "delay_days": to_num(d[pick(d, "Delay Days")]).fillna(0),
    })
    out = out[out["item_code"].str.len() > 0]
    out["stock_qty"] = out["phy_qty"].fillna(out["tally_qty"]).fillna(0).clip(lower=0)
    out["stock_value"] = out["stock_qty"] * out["rate"]
    out["shortage_value"] = (-out["excess_shortage"].clip(upper=0)) * out["rate"]
    out["consumption_30d_value"] = out["daily_req"].fillna(0) * 30 * out["rate"]
    return out.reset_index(drop=True)


SALE_COLS = ["s14", "s30", "s60", "s90", "s180", "s365"]


def load_fg_stock(rows) -> pd.DataFrame:
    """Physical FG stock + rate from the FG app's FG_Stock tab."""
    d = grid_to_df(rows, SHEETS["fg_stock"]["header_hint"])
    tally = pick(d, "Tally Qty", required=False)
    out = pd.DataFrame({
        "item_code": code_str(d[pick(d, "Item Code")]),
        "item": d[pick(d, "Item Name")].str.strip(),
        "stock": to_num(d[pick(d, "Physical Stock")]).fillna(0),
        "tally_qty": to_num(d[tally]).fillna(0) if tally else np.nan,
        "rate": to_num(d[pick(d, "Rate")]).fillna(0),
    })
    out = out[out["item_code"].str.len() > 0].drop_duplicates("item_code")
    return out.reset_index(drop=True)


def load_fg_sales(rows) -> pd.DataFrame:
    """Tally sales history per FG item from the Sale_in-Days tab (header is on row 2)."""
    d = grid_to_df(rows, SHEETS["fg_sales"]["header_hint"])
    out = pd.DataFrame({
        "item_code": code_str(d[pick(d, "Code", "Item Code")]),
        "sales_rate": to_num(d[pick(d, "Rate")]) if pick(d, "Rate", required=False) else np.nan,
        "s14": to_num(d[pick(d, "14D")]),
        "s30": to_num(d[pick(d, "30D")]),
        "s60": to_num(d[pick(d, "60D")]),
        "s90": to_num(d[pick(d, "90D")]),
        "s180": to_num(d[pick(d, "180D")]),
        "s365": to_num(d[pick(d, "365D")]),
    })
    out = out[out["item_code"].str.fullmatch(r"[\w.\-/]+")]
    out[SALE_COLS] = out[SALE_COLS].fillna(0)
    # one row per item (keep the highest figures if an item appears twice)
    out = out.groupby("item_code", as_index=False).max()
    return out.reset_index(drop=True)


def _fg_status(days: pd.Series, stock: pd.Series) -> pd.Series:
    """FRESH < 15 days of stock, MEDIUM 15-90, AGING 90-180, DEAD > 180, OUT_OF_STOCK if none."""
    st = np.select(
        [stock <= 0, days < 15, days < 90, days <= 180],
        ["OUT_OF_STOCK", "FRESH", "MEDIUM", "AGING"],
        default="DEAD",
    )
    return pd.Series(st, index=days.index)


def combine_fg(stock: pd.DataFrame, sales: pd.DataFrame) -> pd.DataFrame:
    """Physical stock (FG_Stock) + Tally sales history (Sale_in-Days), joined on item code."""
    if stock.empty:
        return stock
    out = stock.copy()
    if not sales.empty:
        out = out.merge(sales, on="item_code", how="left")
        out["rate"] = out["rate"].where(out["rate"] > 0, out["sales_rate"]).fillna(0)
        out = out.drop(columns="sales_rate")
    for c in SALE_COLS:
        out[c] = out[c].fillna(0) if c in out.columns else 0.0
    out["category"] = category_from_name(out["item"])
    qty = out["stock"].clip(lower=0)
    out["stock_value"] = qty * out["rate"]
    # daily sales rate: last 30 days; if nothing sold in 30 days, fall back to 90 / 180 / 365 days
    daily = (out["s30"] / 30).where(out["s30"] > 0, out["s90"] / 90)
    daily = daily.where(daily > 0, out["s180"] / 180)
    daily = daily.where(daily > 0, out["s365"] / 365)
    out["days_of_stock"] = np.where(daily > 0, qty / daily.replace(0, np.nan), np.inf)
    out.loc[out["stock"] <= 0, "days_of_stock"] = 0
    out["status"] = _fg_status(pd.Series(out["days_of_stock"], index=out.index), out["stock"])
    return out.reset_index(drop=True)


def load_outstanding(rows) -> pd.DataFrame:
    d = grid_to_df(rows, SHEETS["outstanding"]["header_hint"])
    out = pd.DataFrame({
        "dealer_code": code_str(d[pick(d, "Dealer Code")]),
        "dealer": clean_party(d[pick(d, "Party Name")]),
        "amount": to_num(d[pick(d, "Amount")]).fillna(0),
        "upto60": to_num(d[pick(d, "Upto 60 days")]).fillna(0),
        "above60": to_num(d[pick(d, "Above 60 days")]).fillna(0),
        "remarks": d[pick(d, "Remarks")].str.strip() if pick(d, "Remarks", required=False) else "",
    })
    out = out[out["dealer_code"].str.fullmatch(r"\d+")]
    return out.reset_index(drop=True)


def load_collections(rows) -> pd.DataFrame:
    d = grid_to_df(rows, SHEETS["collections"]["header_hint"])
    out = pd.DataFrame({
        "date": to_date(d[pick(d, "Date")]),
        "dealer_code": code_str(d[pick(d, "Dealer Code")]),
        "dealer": clean_party(d[pick(d, "Dealer Name")]),
        "vtype": d[pick(d, "Vch Type")].str.strip(),
        "amount": to_num(d[pick(d, "Deposit")]).fillna(0),
        "source": d[pick(d, "Source")].str.strip() if pick(d, "Source", required=False) else "",
    })
    out = out.dropna(subset=["date"])
    out = out[(out["amount"] > 0) & out["vtype"].str.contains("Receipt", case=False)]
    return out.reset_index(drop=True)


def load_purchases(rows) -> pd.DataFrame:
    """Tally Purchase Register (item-wise). Column names are matched flexibly."""
    d = grid_to_df(rows, SHEETS["purchases"]["header_hint"])
    sup = pick(d, "Supplier", "Party Name", "Particulars", "Supplier Name", "Party")
    item = pick(d, "Item Name", "Item", "Stock Item", "Item Description")
    qty = pick(d, "Qty", "Quantity", "Billed Quantity", "Actual Quantity")
    rate = pick(d, "Rate", required=False)
    amt = pick(d, "Amount", "Value", "Gross Total", required=False)
    code = pick(d, "Item Code", required=False)
    out = pd.DataFrame({
        "date": to_date(d[pick(d, "Date")]),
        "supplier": clean_party(d[sup]),
        "item": d[item].astype(str).str.split("//").str[0].str.strip(),
        "item_code": code_str(d[code]) if code else d[item].astype(str).str.extract(r"//(\S+)$")[0].fillna(""),
        "qty": to_num(d[qty]),
        "rate": to_num(d[rate]) if rate else np.nan,
        "amount": to_num(d[amt]) if amt else np.nan,
    })
    out["rate"] = out["rate"].fillna(out["amount"] / out["qty"].replace(0, np.nan))
    out["amount"] = out["amount"].fillna(out["rate"] * out["qty"])
    out = out.dropna(subset=["date", "amount"])
    out = out[out["supplier"].str.len() > 0]
    out["month"] = out["date"].dt.to_period("M").dt.to_timestamp()
    return out.reset_index(drop=True)


LOADERS = {
    "sales": load_sales,
    "customers": load_customers,
    "exec_targets": load_exec_targets,
    "rm_stock": load_rm_stock,
    "purchases": load_purchases,
    "fg_stock": load_fg_stock,
    "fg_sales": load_fg_sales,
    "outstanding": load_outstanding,
    "collections": load_collections,
}


# ---------------------------------------------------------------------------
# Bundle
# ---------------------------------------------------------------------------

@dataclass
class DataBundle:
    frames: dict = field(default_factory=dict)
    health: list = field(default_factory=list)   # one row per source
    loaded_at: datetime = field(default_factory=datetime.now)
    test_mode: bool = False

    def get(self, key) -> pd.DataFrame:
        return self.frames.get(key, pd.DataFrame())

    def has(self, key) -> bool:
        df = self.frames.get(key)
        return df is not None and not df.empty

    @property
    def as_of(self) -> pd.Timestamp:
        """Business 'today' = latest sales date (falls back to system date)."""
        s = self.get("sales")
        if not s.empty:
            return s["date"].max().normalize()
        return pd.Timestamp.today().normalize()


def load_all(secrets=None) -> DataBundle:
    bundle = DataBundle()
    reader = SheetReader(secrets)
    bundle.test_mode = reader.test_mode
    for key, fn in LOADERS.items():
        cfg = SHEETS[key]
        try:
            df = fn(reader.rows(key))
            bundle.frames[key] = df
            bundle.health.append({"source": key, "sheet_tab": cfg["tab"], "rows": len(df), "status": "OK", "detail": ""})
        except Exception as e:  # keep going — one broken sheet must not kill the dashboard
            bundle.frames[key] = pd.DataFrame()
            status = "Not set up (optional)" if cfg.get("optional") else "ERROR"
            bundle.health.append({"source": key, "sheet_tab": cfg["tab"], "rows": 0, "status": status, "detail": str(e)[:200]})
    # Cash flow: Finance's daily report workbook (one tab per day)
    try:
        cf, cc = build_frames(reader.cashflow_tabs())
        if cf.empty:
            raise ValueError("No daily tabs (dd.mm) could be read")
        bundle.frames["cash_exclusions"] = cf.attrs.pop("exclusions", pd.DataFrame())
        bundle.frames["cashflow"], bundle.frames["cash_collectors"] = cf, cc
        bundle.health.append({"source": "cashflow", "sheet_tab": "daily tabs (dd.mm)", "rows": len(cf), "status": "OK",
                              "detail": f"{cf['date'].min():%d-%b} to {cf['date'].max():%d-%b-%Y}"})
    except Exception as e:
        bundle.frames["cashflow"] = bundle.frames["cash_collectors"] = bundle.frames["cash_exclusions"] = pd.DataFrame()
        bundle.health.append({"source": "cashflow", "sheet_tab": "daily tabs (dd.mm)", "rows": 0,
                              "status": "Not set up (optional)" if reader.test_mode else "ERROR", "detail": str(e)[:200]})
    # FG: physical stock (FG_Stock) + Tally sales history (Sale_in-Days)
    if bundle.has("fg_stock"):
        bundle.frames["fg_stock"] = combine_fg(bundle.get("fg_stock"), bundle.get("fg_sales"))
    # attach executive to sales
    s, c = bundle.get("sales"), bundle.get("customers")
    if not s.empty:
        if not c.empty:
            s = s.merge(c[["dealer_code", "executive"]], left_on="cust_code", right_on="dealer_code", how="left").drop(columns="dealer_code")
        else:
            s["executive"] = np.nan
        s["executive"] = s["executive"].fillna("Unassigned")
        bundle.frames["sales"] = s
    o = bundle.get("outstanding")
    if not o.empty and not c.empty:
        o = o.merge(c[["dealer_code", "executive"]], on="dealer_code", how="left")
        o["executive"] = o["executive"].fillna("Unassigned")
        bundle.frames["outstanding"] = o
    return bundle
