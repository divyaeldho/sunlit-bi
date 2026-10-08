"""
KPIs, trend analysis, anomaly detection and the alert engine.

Alert flow (Module 56 — Digital Early-Warning System):
    Data -> Trend -> Risk -> Alert -> Owner -> Action
Every alert row carries: category, severity, what happened, ₹ impact,
owner (department + person) and the recommended action.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.config import OWNERS, THRESHOLDS as T

SEV_ORDER = {"Critical": 0, "High": 1, "Medium": 2}


def inr(x: float) -> str:
    """₹ in Indian style: ₹12.3 L / ₹1.2 Cr / ₹8,450."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "–"
    a = abs(x)
    sign = "-" if x < 0 else ""
    if a >= 1e7:
        return f"{sign}₹{a/1e7:.2f} Cr"
    if a >= 1e5:
        return f"{sign}₹{a/1e5:.2f} L"
    return f"{sign}₹{a:,.0f}"


def pct(a, b):
    return (a - b) / b * 100 if b else np.nan


# ---------------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------------

def window(df: pd.DataFrame, end: pd.Timestamp, days: int, offset: int = 0, col="date"):
    hi = end - pd.Timedelta(days=offset)
    lo = hi - pd.Timedelta(days=days)
    return df[(df[col] > lo) & (df[col] <= hi)]


def sales_kpis(sales: pd.DataFrame, as_of: pd.Timestamp) -> dict:
    if sales.empty:
        return {}
    m_start = as_of.replace(day=1)
    mtd = sales[(sales["date"] >= m_start) & (sales["date"] <= as_of)]
    prev_start = (m_start - pd.offsets.MonthBegin(1))
    prev_same = sales[(sales["date"] >= prev_start) & (sales["date"] <= prev_start + (as_of - m_start))]
    l30, p30 = window(sales, as_of, 30), window(sales, as_of, 30, 30)
    days_in_month = pd.Period(as_of, "M").days_in_month
    return {
        "mtd_sales": mtd["amount"].sum(),
        "mtd_prev_same": prev_same["amount"].sum(),
        "mtd_growth": pct(mtd["amount"].sum(), prev_same["amount"].sum()),
        "mtd_margin_pct": mtd["margin"].sum() / mtd["amount"].sum() * 100 if mtd["amount"].sum() else np.nan,
        "mtd_projection": mtd["amount"].sum() / as_of.day * days_in_month,
        "mtd_dealers": mtd["cust_code"].nunique(),
        "mtd_invoices": mtd["voucher"].nunique(),
        "l30_sales": l30["amount"].sum(),
        "p30_sales": p30["amount"].sum(),
        "l30_growth": pct(l30["amount"].sum(), p30["amount"].sum()),
        "fy_sales": sales[sales["date"] >= fy_start(as_of)]["amount"].sum(),
    }


def fy_start(d: pd.Timestamp) -> pd.Timestamp:
    return pd.Timestamp(d.year if d.month >= 4 else d.year - 1, 4, 1)


def dealer_activity(sales: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Per dealer: last order, typical gap, 12M billing, days silent."""
    if sales.empty:
        return pd.DataFrame()
    orders = sales.groupby(["cust_code", "party", "executive", sales["date"].dt.normalize()])["amount"].sum().reset_index()
    orders = orders.sort_values("date")
    g = orders.groupby(["cust_code", "party", "executive"])
    act = g.agg(last_order=("date", "max"), first_order=("date", "min"), orders=("date", "count")).reset_index()
    gaps = orders.groupby("cust_code")["date"].apply(lambda s: s.diff().dt.days.median()).rename("typical_gap")
    act = act.merge(gaps, on="cust_code", how="left")
    l12 = sales[sales["date"] > as_of - pd.Timedelta(days=365)].groupby("cust_code")["amount"].sum().rename("last12m")
    l90 = window(sales, as_of, 90).groupby("cust_code")["amount"].sum().rename("last90")
    p90 = window(sales, as_of, 90, 90).groupby("cust_code")["amount"].sum().rename("prev90")
    act = act.merge(l12, on="cust_code", how="left").merge(l90, on="cust_code", how="left").merge(p90, on="cust_code", how="left")
    act[["last12m", "last90", "prev90"]] = act[["last12m", "last90", "prev90"]].fillna(0)
    act["days_silent"] = (as_of - act["last_order"]).dt.days
    return act


def daily_series(sales: pd.DataFrame, as_of: pd.Timestamp, days: int = 120) -> pd.DataFrame:
    s = window(sales, as_of, days)
    d = s.groupby(s["date"].dt.normalize())["amount"].sum()
    idx = pd.date_range(as_of - pd.Timedelta(days=days - 1), as_of, freq="D")
    d = d.reindex(idx, fill_value=0).rename_axis("date").reset_index(name="amount")
    d = d[d["date"].dt.dayofweek != 6]            # Sunday off
    d["rolling"] = d["amount"].rolling(20, min_periods=8).mean()
    sd = d["amount"].rolling(20, min_periods=8).std()
    d["z"] = (d["amount"] - d["rolling"].shift(1)) / sd.shift(1)
    return d


def category_trend(sales: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    l30 = window(sales, as_of, 30).groupby("category")["amount"].sum().rename("last30")
    p30 = window(sales, as_of, 30, 30).groupby("category")["amount"].sum().rename("prev30")
    l90 = window(sales, as_of, 90).groupby("category")["amount"].sum().rename("last90")
    df = pd.concat([l30, p30, l90], axis=1).fillna(0).reset_index().rename(columns={"index": "category"})
    df["change_pct"] = np.where(df["prev30"] > 0, (df["last30"] - df["prev30"]) / df["prev30"] * 100, np.nan)
    return df.sort_values("last90", ascending=False)


def cost_rate_changes(sales: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Product cost-rate (Tally 'Purchase Rate') latest vs previous 90-day median."""
    s = sales.dropna(subset=["cost_rate"])
    s = s[s["cost_rate"] > 0]
    recent = window(s, as_of, 30)
    base = window(s, as_of, 90, 30)
    if recent.empty or base.empty:
        return pd.DataFrame()
    latest = recent.sort_values("date").groupby(["item_code", "item"])["cost_rate"].last().rename("latest_rate")
    prev = base.groupby(["item_code", "item"])["cost_rate"].median().rename("prev_rate")
    qty = recent.groupby(["item_code", "item"])["qty"].sum().rename("qty_30d")
    df = pd.concat([latest, prev, qty], axis=1).dropna(subset=["latest_rate", "prev_rate"]).reset_index()
    df["change_pct"] = (df["latest_rate"] - df["prev_rate"]) / df["prev_rate"] * 100
    df["impact_30d"] = (df["latest_rate"] - df["prev_rate"]) * df["qty_30d"]
    return df


def purchase_price_changes(pur: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Latest purchase rate per item vs average of earlier purchases (Purchase Register)."""
    if pur.empty:
        return pd.DataFrame()
    p = pur.dropna(subset=["rate"]).sort_values("date")
    rows = []
    for (code, item), g in p.groupby(["item_code", "item"]):
        if len(g) < 2:
            continue
        last = g.iloc[-1]
        prev = g.iloc[:-1]
        prev_avg = np.average(prev["rate"], weights=prev["qty"].clip(lower=1).fillna(1))
        rows.append({
            "item_code": code, "item": item, "supplier": last["supplier"], "last_date": last["date"],
            "latest_rate": last["rate"], "prev_rate": prev_avg,
            "best_rate": prev["rate"].min(), "best_supplier": prev.loc[prev["rate"].idxmin(), "supplier"],
            "change_pct": (last["rate"] - prev_avg) / prev_avg * 100 if prev_avg else np.nan,
            "impact": (last["rate"] - prev_avg) * (last["qty"] or 0),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Alert engine
# ---------------------------------------------------------------------------

def _owner(dept: str, override: str | None = None) -> str:
    return override or OWNERS.get(dept, {}).get("name", dept)


def _a(rows, category, severity, title, detail, value, dept, action, owner=None, ref=""):
    rows.append({
        "category": category, "severity": severity, "title": title, "detail": detail,
        "value": float(value) if value is not None and not pd.isna(value) else 0.0,
        "department": dept, "owner": _owner(dept, owner), "action": action, "ref": ref,
    })


def build_alerts(b) -> pd.DataFrame:
    rows: list[dict] = []
    as_of = b.as_of
    sales, rm, fg = b.get("sales"), b.get("rm_stock"), b.get("fg_stock")
    osd, pur, tgt = b.get("outstanding"), b.get("purchases"), b.get("exec_targets")

    # 1. RM stock-out risk --------------------------------------------------
    if not rm.empty:
        risk = rm[(rm["status"].str.contains("ORDER NOW")) & (rm["daily_req"].fillna(0) > 0)]
        risk = risk[risk["shortage_value"] >= T["rm_min_value_alert"]]
        for _, r in risk.sort_values(["coverage_days", "shortage_value"], ascending=[True, False]).iterrows():
            cov = r["coverage_days"] if pd.notna(r["coverage_days"]) else 0
            lt = r["lead_time"] if pd.notna(r["lead_time"]) else 0
            sev = "Critical" if cov < lt / 2 or cov <= 3 else "High" if cov < lt else "Medium"
            _a(rows, "Stock-out risk (RM)", sev, f"{r['item']} — {cov:.0f} days cover vs {lt:.0f} days lead time",
               f"Short by {abs(r['excess_shortage']):,.0f} {r['unit']}; order was due {int(r['delay_days'])} days ago",
               r["shortage_value"], "Purchase", f"Raise PO for {abs(r['excess_shortage']):,.0f} {r['unit']} today; confirm supplier delivery date",
               ref=r["item_code"])

    # 2. FG stock-out risk --------------------------------------------------
    if not fg.empty:
        fr = fg[(fg["s30"] > 0) & (fg["days_of_stock"] < T["fg_stockout_days"])]
        for _, r in fr.sort_values("s30", ascending=False).iterrows():
            need = max(r["s30"] - r["stock"], 0)
            sev = "Critical" if r["stock"] <= 0 else "High"
            _a(rows, "Stock-out risk (FG)", sev, f"{r['item']} — {r['days_of_stock']:.0f} days of stock left",
               f"Stock {r['stock']:,.0f} vs 30-day sales {r['s30']:,.0f}", need * r["rate"],
               "Production", f"Schedule production of ~{need:,.0f} nos this week", ref=r["item_code"])

    # 3. Sales decline — category & executive pace ---------------------------
    if not sales.empty:
        ct = category_trend(sales, as_of)
        dec = ct[(ct["prev30"] >= T["sales_decline_min_value"]) & (ct["change_pct"] <= -T["sales_decline_pct"])]
        for _, r in dec.iterrows():
            sev = "High" if r["change_pct"] <= -40 else "Medium"
            _a(rows, "Sales decline", sev, f"{r['category']} sales down {abs(r['change_pct']):.0f}% (last 30 days)",
               f"{inr(r['last30'])} vs {inr(r['prev30'])} in the previous 30 days", r["prev30"] - r["last30"],
               "Sales", f"Review {r['category']} with executives; push to dealers who bought it before", ref=r["category"])
        if not tgt.empty:
            m_start = as_of.replace(day=1)
            mtd = sales[sales["date"] >= m_start].groupby("executive")["amount"].sum()
            dim = pd.Period(as_of, "M").days_in_month
            for _, r in tgt.dropna(subset=["target"]).iterrows():
                if r["target"] <= 0:
                    continue
                proj = mtd.get(r["executive"], 0) / as_of.day * dim
                if proj < 0.9 * r["target"] and as_of.day >= 7:
                    gap = r["target"] - proj
                    _a(rows, "Sales decline", "High" if proj < 0.75 * r["target"] else "Medium",
                       f"{r['executive']} projected at {proj / r['target'] * 100:.0f}% of monthly target",
                       f"MTD {inr(mtd.get(r['executive'], 0))}; projected {inr(proj)} vs target {inr(r['target'])}",
                       gap, "Sales", f"Daily review with {r['executive']}; focus on 'due for follow-up' dealers",
                       owner=f"{_owner('Sales')} / {r['executive']}", ref=r["executive"])

    # 4. Key-dealer inactivity -------------------------------------------------
    if not sales.empty:
        act = dealer_activity(sales, as_of)
        key = act[(act["last12m"] >= T["dealer_key_min_12m"]) & act["typical_gap"].notna()]
        thr = np.maximum(key["typical_gap"] * T["dealer_silent_gap_mult"], 14)
        silent = key[key["days_silent"] > thr]
        for _, r in silent.sort_values("last12m", ascending=False).iterrows():
            sev = "High" if r["days_silent"] > 3 * max(r["typical_gap"], 7) else "Medium"
            _a(rows, "Dealer inactivity", sev, f"{r['party']} silent for {r['days_silent']} days",
               f"Usually orders every {r['typical_gap']:.0f} days; last-12M billing {inr(r['last12m'])}",
               r["last12m"] / 12, "Sales", "Call dealer this week; check for competitor / service / payment issue",
               owner=r["executive"], ref=r["cust_code"])

    # 5. Price variation --------------------------------------------------------
    if not pur.empty:
        pc = purchase_price_changes(pur, as_of)
        src = "purchase rate"
    elif not sales.empty:
        pc = cost_rate_changes(sales, as_of)
        src = "product cost rate (Tally)"
    else:
        pc = pd.DataFrame()
    if not pc.empty:
        pv = pc[pc["change_pct"].abs() >= T["price_variation_pct"]]
        for _, r in pv.sort_values("change_pct", ascending=False).iterrows():
            up = r["change_pct"] > 0
            sev = "High" if abs(r["change_pct"]) >= 15 else "Medium"
            extra = f"; best earlier rate ₹{r['best_rate']:.2f} ({r['best_supplier']})" if "best_rate" in r else ""
            _a(rows, "Price variation", sev,
               f"{r['item']} {src} {'up' if up else 'down'} {abs(r['change_pct']):.1f}%",
               f"₹{r['prev_rate']:.2f} → ₹{r['latest_rate']:.2f}{extra}",
               abs(r.get("impact", r.get("impact_30d", 0)) or 0), "Purchase",
               "Negotiate / compare suppliers; update selling price if cost rise is permanent" if up else "Confirm new rate is sustainable; pass benefit to margin",
               ref=r["item_code"])

    # 6. Overdue payments ---------------------------------------------------------
    if not osd.empty:
        od = osd[osd["above60"] >= T["overdue_min_value"]]
        for _, r in od.sort_values("above60", ascending=False).iterrows():
            sev = "Critical" if r["above60"] >= T["overdue_critical_value"] else "High"
            _a(rows, "Overdue payment", sev, f"{r['dealer']} — {inr(r['above60'])} overdue > 60 days",
               f"Total outstanding {inr(r['amount'])}" + (f"; note: {r['remarks']}" if r.get("remarks") else ""),
               r["above60"], "Finance", "Collection call + written reminder; hold further credit until cleared",
               owner=f"{_owner('Finance')} / {r.get('executive', '')}".rstrip(" /"), ref=r["dealer_code"])

    # 7. Slow-moving FG stock ---------------------------------------------------------
    if not fg.empty:
        slow = fg[(fg["stock"] > 0) & (fg["days_of_stock"] > T["fg_slow_days"]) & (fg["stock_value"] >= 5000)]
        for _, r in slow.sort_values("stock_value", ascending=False).head(25).iterrows():
            dos = "no sales in 30 days" if np.isinf(r["days_of_stock"]) else f"{r['days_of_stock']:.0f} days of stock"
            _a(rows, "Slow-moving stock", "High" if r["stock_value"] >= 50000 else "Medium",
               f"{r['item']} — {inr(r['stock_value'])} tied up ({dos})",
               f"{r['stock']:,.0f} nos in stock; 365-day sales {r['s365']:,.0f}", r["stock_value"],
               "Sales", "Offer to dealers who bought this range; consider scheme / project use", ref=r["item_code"])

    # 8. Margin / discount exceptions (last 30 days) ------------------------------------
    if not sales.empty:
        l30 = window(sales, as_of, 30)
        ex = l30[((l30["margin_pct"] < T["low_margin_pct"]) | (l30["discount_pct"] > T["high_discount_pct"])) & (l30["amount"] > 0)]
        if not ex.empty:
            by = ex.groupby(["item_code", "item"]).agg(lines=("amount", "size"), amount=("amount", "sum"),
                                                        margin=("margin", "sum"), disc=("discount_pct", "max"),
                                                        disc_amt=("discount_amt", "sum")).reset_index()
            by["margin_pct"] = by["margin"] / by["amount"] * 100
            for _, r in by.sort_values("amount", ascending=False).head(10).iterrows():
                _a(rows, "Margin / discount exception", "Medium",
                   f"{r['item']} sold at {r['margin_pct']:.1f}% margin",
                   f"{r['lines']} invoice lines, {inr(r['amount'])} in last 30 days; max discount {r['disc']:.0f}%",
                   r["disc_amt"] + r["amount"] * max(T["low_margin_pct"] - r["margin_pct"], 0) / 100, "Sales",
                   "Check discount approvals and cost rate; correct price list if needed", ref=r["item_code"])

    # 9. Sales anomaly (statistical) -------------------------------------------------------
    if not sales.empty:
        ds = daily_series(sales, as_of)
        recent = ds[ds["date"] > as_of - pd.Timedelta(days=14)].dropna(subset=["z"])
        for _, r in recent[recent["z"].abs() >= T["anomaly_z"]].iterrows():
            hi = r["z"] > 0
            _a(rows, "Sales anomaly", "Medium",
               f"Unusually {'high' if hi else 'low'} sales on {r['date']:%d-%b}",
               f"{inr(r['amount'])} vs normal ~{inr(r['rolling'])} (z = {r['z']:.1f})", abs(r["amount"] - r["rolling"]),
               "Sales" if not hi else "Management",
               "Verify large orders / billing timing" if hi else "Check for billing backlog or dispatch hold",
               ref=f"{r['date']:%Y-%m-%d}")

    # 10. Cash flow (Finance daily report) -------------------------------------------------
    cash_alerts(rows, b.get("cashflow"), as_of)

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["category", "severity", "title", "detail", "value", "department", "owner", "action", "ref"])
    df["_s"] = df["severity"].map(SEV_ORDER)
    df = df.sort_values(["_s", "value"], ascending=[True, False]).drop(columns="_s").reset_index(drop=True)
    return df


def diverse_top(alerts: pd.DataFrame, per_cat: int = 2, n: int = 10) -> pd.DataFrame:
    """Top alerts across categories (round-robin) so one category can't crowd out the rest."""
    if alerts.empty:
        return alerts
    ranked = alerts.assign(_rank=alerts.groupby("category").cumcount())
    ranked = ranked[ranked["_rank"] < per_cat]
    ranked["_s"] = ranked["severity"].map(SEV_ORDER)
    return ranked.sort_values(["_rank", "_s", "value"], ascending=[True, True, False]).head(n).drop(columns=["_rank", "_s"])


def alert_summary(alerts: pd.DataFrame) -> pd.DataFrame:
    if alerts.empty:
        return pd.DataFrame()
    s = alerts.pivot_table(index="category", columns="severity", values="title", aggfunc="count", fill_value=0)
    for c in ["Critical", "High", "Medium"]:
        if c not in s:
            s[c] = 0
    s = s[["Critical", "High", "Medium"]]
    s["Total"] = s.sum(axis=1)
    s["₹ at stake"] = alerts.groupby("category")["value"].sum()
    return s.sort_values(["Critical", "High", "Total"], ascending=False).reset_index()


# ---------------------------------------------------------------------------
# Cash-flow alerts  (owner: Finance)
# ---------------------------------------------------------------------------

def cash_alerts(rows, cf: pd.DataFrame, as_of: pd.Timestamp):
    if cf is None or cf.empty:
        return
    from core.cashflow import weekly
    last = cf.iloc[-1]
    day = f"{last['date']:%d-%b}"

    # a) report not updated
    stale = (as_of - last["date"]).days
    if stale > T["cash_report_stale_days"]:
        _a(rows, "Cash flow", "Medium", f"Cash flow report not updated for {stale} days",
           f"Last daily tab is {last['tab']} ({day}); sales data runs to {as_of:%d-%b}", 0, "Finance",
           "Update today's cash flow tab before 11 AM", ref=str(last["tab"]))

    # b) closing funds vs next-7-day obligations
    funds, ob = last["close_total"], last["oblig_7d"]
    if pd.notna(funds) and pd.notna(ob) and ob > 0 and funds < T["cash_cover_min"] * ob:
        sev = "Critical" if funds < ob else "High"
        _a(rows, "Cash flow", sev, f"Funds cover only {funds / ob:.1f}x of next-7-day payments",
           f"Closing funds {inr(funds)} vs obligations {inr(ob)} ({day})", max(ob * T["cash_cover_min"] - funds, 0),
           "Finance", "Prioritise collections from the 14-day list; reschedule non-critical payments", ref=day)

    # c) weekly net cash flow (last COMPLETE week, Sun-Sat)
    w = weekly(cf[cf["has_actual"]])
    rep = last["date"]
    cur_week = (rep - pd.Timedelta(days=(rep.dayofweek + 1) % 7)).normalize()
    done = w[w["week"] < cur_week]
    if not done.empty:
        r = done.iloc[-1]
        wk = f"week of {r['week']:%d-%b}"
        if r["net"] < 0:
            _a(rows, "Cash flow", "High", f"Net cash flow negative: {inr(r['net'])} ({wk})",
               f"In {inr(r['inflow'])} vs out {inr(r['outflow'])}; target is positive every week",
               -r["net"], "Finance", "Review the week's large payments; push the 14-day collection list",
               ref=f"{r['week']:%Y-%m-%d}")
        elif r["net"] < T["weekly_net_target"]:
            _a(rows, "Cash flow", "Medium", f"Weekly net cash flow {inr(r['net'])} below {inr(T['weekly_net_target'])} target",
               f"{wk}: in {inr(r['inflow'])}, out {inr(r['outflow'])}", T["weekly_net_target"] - r["net"],
               "Finance", "Raise collections or defer discretionary payments to reach ₹5 L/week",
               ref=f"{r['week']:%Y-%m-%d}")

    # d) closing funds falling vs ~30 days ago
    past = cf[cf["date"] <= last["date"] - pd.Timedelta(days=30)]
    if not past.empty and pd.notna(funds):
        then = past.iloc[-1]["close_total"]
        if then and (then - funds) / then * 100 >= T["cash_drop_pct"]:
            _a(rows, "Cash flow", "High", f"Available funds down {(then - funds) / then * 100:.0f}% in 30 days",
               f"{inr(then)} on {past.iloc[-1]['date']:%d-%b} -> {inr(funds)} on {day}", then - funds,
               "Finance", "Explain the drop to management; check OD utilisation and planned outflows",
               owner=f"{_owner('Finance')} / {_owner('Management')}", ref=day)

    # e) unplanned payments (last 30 days)
    l30 = cf[(cf["date"] > last["date"] - pd.Timedelta(days=30)) & cf["has_actual"]]
    if not l30.empty:
        plan, act = l30["outflow_exp"].sum(), l30["outflow_act"].sum()
        if plan > 0 and (act - plan) / plan * 100 > T["unplanned_payment_pct"]:
            _a(rows, "Cash flow", "Medium", f"Payments {(act - plan) / plan * 100:.0f}% above plan (last 30 days)",
               f"Planned {inr(plan)} vs paid {inr(act)} — payments are not being listed in advance", act - plan,
               "Finance", "Add every payment to the 7-day payment list before paying", ref="30d")

    # f) books don't tie: opening + in - out != closing
    l7 = cf[cf["date"] > last["date"] - pd.Timedelta(days=7)]
    bad = l7[l7["recon_gap"].abs() >= T["recon_gap_min"]]
    if not bad.empty:
        _a(rows, "Cash flow", "Medium", f"Cash report does not tie on {len(bad)} day(s) this week",
           "Opening + actual inflow - actual outflow ≠ closing on " + ", ".join(bad["tab"].astype(str)),
           bad["recon_gap"].abs().sum(), "Finance", "Find the missing receipt / payment lines and correct the tabs",
           ref=",".join(bad["tab"].astype(str)))
