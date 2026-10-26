import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.analytics import dealer_activity, inr, pct
from core.config import THRESHOLDS as T
from core.ui import SERIES, delta_str, download, get_data, hbar, money_axis, page_setup, show, sidebar

page_setup("Sales Intelligence", "📈", key="sales")
b, alerts = get_data()
sidebar(b)
st.title("📈 Sales Intelligence")

sales = b.get("sales")
if sales.empty:
    st.error("Sales data not available — check Data sources in the sidebar.")
    st.stop()

# ---- Filters (one row) ----------------------------------------------------
as_of = b.as_of
presets = {"Month to date": (as_of.replace(day=1), as_of), "Last 30 days": (as_of - pd.Timedelta(days=29), as_of),
           "Last 90 days": (as_of - pd.Timedelta(days=89), as_of),
           "FY to date": (pd.Timestamp(as_of.year if as_of.month >= 4 else as_of.year - 1, 4, 1), as_of),
           "Last 12 months": (as_of - pd.DateOffset(months=12) + pd.Timedelta(days=1), as_of)}
f = st.columns([1.2, 1, 1, 1])
period = f[0].selectbox("Period", list(presets), index=1)
execs = f[1].multiselect("Executive", sorted(sales["executive"].unique()))
cats = f[2].multiselect("Category", sorted(sales["category"].unique()))
vtypes = f[3].multiselect("Voucher type", sorted(sales["vtype"].unique()))

lo, hi = presets[period]
span = (hi - lo).days + 1
flt = pd.Series(True, index=sales.index)
if execs:
    flt &= sales["executive"].isin(execs)
if cats:
    flt &= sales["category"].isin(cats)
if vtypes:
    flt &= sales["vtype"].isin(vtypes)
S = sales[flt]
cur = S[(S["date"] >= lo) & (S["date"] <= hi)]
prev = S[(S["date"] >= lo - pd.Timedelta(days=span)) & (S["date"] < lo)]

# ---- KPIs -----------------------------------------------------------------
c = st.columns(5)
c[0].metric("Sales", inr(cur["amount"].sum()), delta_str(pct(cur["amount"].sum(), prev["amount"].sum())),
            help=f"vs previous {span} days")
mp = cur["margin"].sum() / cur["amount"].sum() * 100 if cur["amount"].sum() else np.nan
mpp = prev["margin"].sum() / prev["amount"].sum() * 100 if prev["amount"].sum() else np.nan
c[1].metric("Gross margin", f"{mp:.1f}%", delta_str(mp - mpp, " pts"))
c[2].metric("Dealers billed", cur["cust_code"].nunique(), delta_str(cur["cust_code"].nunique() - prev["cust_code"].nunique(), ""))
c[3].metric("Invoices", cur["voucher"].nunique())
aov = cur["amount"].sum() / max(cur["voucher"].nunique(), 1)
c[4].metric("Avg invoice value", inr(aov))

# ---- Trend ------------------------------------------------------------------
tab1, tab2, tab3, tab4, tab5 = st.tabs(["Trend", "Products", "Dealers", "Executives", "Exceptions"])

with tab1:
    m = S[S["date"] > as_of - pd.DateOffset(months=13)].groupby(["month", "category"])["amount"].sum().reset_index()
    topcats = S.groupby("category")["amount"].sum().nlargest(7).index
    m["cat"] = np.where(m["category"].isin(topcats), m["category"], "Other")
    m = m.groupby(["month", "cat"])["amount"].sum().reset_index()
    order = list(topcats) + (["Other"] if (m["cat"] == "Other").any() else [])
    fig = go.Figure()
    for i, cat in enumerate(order):
        d = m[m["cat"] == cat]
        fig.add_bar(x=d["month"], y=d["amount"], name=cat, marker_color=SERIES[i] if cat != "Other" else "#9a9892",
                    marker_line=dict(width=1, color="rgba(255,255,255,.9)"),
                    hovertemplate=f"{cat}<br>%{{x|%b %Y}}: ₹%{{y:,.0f}}<extra></extra>")
    fig.update_layout(barmode="stack", title="Monthly sales by category (top 7 + Other)")
    fig.update_xaxes(tickformat="%b %y")
    show(money_axis(fig), 380)

    cc = cur.groupby("category").agg(sales=("amount", "sum"), margin=("margin", "sum")).reset_index()
    pc = prev.groupby("category")["amount"].sum().rename("prev")
    cc = cc.merge(pc, on="category", how="left").fillna({"prev": 0})
    cc["growth %"] = np.where(cc["prev"] > 0, (cc["sales"] - cc["prev"]) / cc["prev"] * 100, np.nan)
    cc["margin %"] = cc["margin"] / cc["sales"] * 100
    cc["share %"] = cc["sales"] / cc["sales"].sum() * 100
    st.markdown("##### Category scorecard — selected period vs previous")
    st.dataframe(cc.sort_values("sales", ascending=False)[["category", "sales", "prev", "growth %", "margin %", "share %"]],
                 hide_index=True, use_container_width=True,
                 column_config={"sales": st.column_config.NumberColumn("Sales ₹", format="%.0f"),
                                "prev": st.column_config.NumberColumn("Previous ₹", format="%.0f"),
                                "growth %": st.column_config.NumberColumn(format="%.1f%%"),
                                "margin %": st.column_config.NumberColumn(format="%.1f%%"),
                                "share %": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100)})

with tab2:
    p = cur.groupby(["item_code", "item", "category"]).agg(qty=("qty", "sum"), sales=("amount", "sum"),
                                                            margin=("margin", "sum")).reset_index()
    p["margin %"] = p["margin"] / p["sales"] * 100
    pp = prev.groupby("item_code")["amount"].sum().rename("prev")
    p = p.merge(pp, on="item_code", how="left").fillna({"prev": 0})
    p["growth %"] = np.where(p["prev"] > 0, (p["sales"] - p["prev"]) / p["prev"] * 100, np.nan)
    a, bb = st.columns(2)
    with a:
        hbar(p.nlargest(10, "sales"), "sales", "item", "Top 10 products by sales")
    with bb:
        dec = p[p["prev"] >= 20000].nsmallest(10, "growth %")
        dec = dec.assign(drop=dec["prev"] - dec["sales"])
        hbar(dec, "drop", "item", "Biggest product declines vs previous period (₹ drop)", color=SERIES[1])
    st.markdown("##### All products")
    st.dataframe(p.sort_values("sales", ascending=False), hide_index=True, use_container_width=True,
                 column_config={"sales": st.column_config.NumberColumn("Sales ₹", format="%.0f"),
                                "prev": st.column_config.NumberColumn("Previous ₹", format="%.0f"),
                                "margin": None, "margin %": st.column_config.NumberColumn(format="%.1f%%"),
                                "growth %": st.column_config.NumberColumn(format="%.0f%%")})
    download(p, "sunlit_product_sales")

with tab3:
    d = cur.groupby(["cust_code", "party", "executive"]).agg(sales=("amount", "sum"), margin=("margin", "sum"),
                                                             invoices=("voucher", "nunique")).reset_index()
    dp = prev.groupby("cust_code")["amount"].sum().rename("prev")
    d = d.merge(dp, on="cust_code", how="left").fillna({"prev": 0})
    d["growth %"] = np.where(d["prev"] > 0, (d["sales"] - d["prev"]) / d["prev"] * 100, np.nan)
    a, bb = st.columns(2)
    with a:
        hbar(d.nlargest(10, "sales"), "sales", "party", "Top 10 dealers")
    with bb:
        lost = dp[~dp.index.isin(d["cust_code"])].nlargest(10)
        names = prev.drop_duplicates("cust_code").set_index("cust_code")["party"]
        ld = pd.DataFrame({"party": names.reindex(lost.index).values, "prev": lost.values})
        if ld.empty:
            st.info("Every dealer from the previous period has billed again.")
        else:
            hbar(ld, "prev", "party", "Billed last period, nothing this period", color=SERIES[1])
    act = dealer_activity(S, as_of)
    key = act[act["last12m"] >= T["dealer_key_min_12m"]].copy()
    key["silent vs usual"] = key["days_silent"] / key["typical_gap"].clip(lower=1)
    st.markdown(f"##### Key dealers (12-month billing ≥ {inr(T['dealer_key_min_12m'])}) — reorder watch")
    st.dataframe(key.sort_values("silent vs usual", ascending=False)[
        ["party", "executive", "last_order", "days_silent", "typical_gap", "silent vs usual", "last12m", "last90", "prev90"]],
        hide_index=True, use_container_width=True,
        column_config={"last_order": st.column_config.DateColumn("Last order", format="DD-MMM-YY"),
                       "typical_gap": st.column_config.NumberColumn("Usual gap (d)", format="%.0f"),
                       "silent vs usual": st.column_config.NumberColumn("× usual gap", format="%.1f"),
                       "last12m": st.column_config.NumberColumn("12M ₹", format="%.0f"),
                       "last90": st.column_config.NumberColumn("Last 90D ₹", format="%.0f"),
                       "prev90": st.column_config.NumberColumn("Prior 90D ₹", format="%.0f")})
    download(d, "sunlit_dealer_sales")

with tab4:
    tg = b.get("exec_targets")
    m_start = as_of.replace(day=1)
    dim = pd.Period(as_of, "M").days_in_month
    e = sales[sales["date"] >= m_start].groupby("executive").agg(mtd=("amount", "sum"), dealers=("cust_code", "nunique")).reset_index()
    if not tg.empty:
        e = e.merge(tg, on="executive", how="outer").fillna({"mtd": 0, "dealers": 0})
    else:
        e["target"] = np.nan
    e["projection"] = e["mtd"] / as_of.day * dim
    e["achieved %"] = np.where(e["target"] > 0, e["mtd"] / e["target"] * 100, np.nan)
    e["projected %"] = np.where(e["target"] > 0, e["projection"] / e["target"] * 100, np.nan)
    e = e[(e["mtd"] > 0) | (e["target"] > 0)]
    fig = go.Figure()
    fig.add_bar(x=e["executive"], y=e["mtd"], name="MTD sales", marker_color=SERIES[0],
                hovertemplate="%{x}<br>MTD ₹%{y:,.0f}<extra></extra>")
    fig.add_bar(x=e["executive"], y=e["projection"], name="Projected month-end", marker_color=SERIES[2],
                hovertemplate="%{x}<br>Projected ₹%{y:,.0f}<extra></extra>")
    fig.add_scatter(x=e["executive"], y=e["target"], mode="markers", name="Target",
                    marker=dict(symbol="line-ew", size=36, line=dict(width=3, color=SERIES[1])),
                    hovertemplate="%{x}<br>Target ₹%{y:,.0f}<extra></extra>")
    fig.update_layout(barmode="group", title=f"Executives — {as_of:%B} progress vs target")
    show(money_axis(fig), 360)
    st.dataframe(e, hide_index=True, use_container_width=True,
                 column_config={k: st.column_config.NumberColumn(format="%.0f") for k in ["mtd", "target", "projection"]} |
                               {k: st.column_config.NumberColumn(format="%.0f%%") for k in ["achieved %", "projected %"]})

with tab5:
    ex = cur[((cur["margin_pct"] < T["low_margin_pct"]) | (cur["discount_pct"] > T["high_discount_pct"])) & (cur["amount"] > 0)]
    st.caption(f"Invoice lines with margin below {T['low_margin_pct']}% or discount above {T['high_discount_pct']}% in the selected period.")
    c = st.columns(3)
    c[0].metric("Exception lines", len(ex))
    c[1].metric("Sales value", inr(ex["amount"].sum()))
    c[2].metric("Discount given", inr(ex["discount_amt"].sum()))
    st.dataframe(ex.sort_values("amount", ascending=False)[
        ["date", "voucher", "party", "executive", "item", "qty", "rate", "cost_rate", "discount_pct", "margin_pct", "amount"]],
        hide_index=True, use_container_width=True,
        column_config={"date": st.column_config.DateColumn(format="DD-MMM-YY"),
                       "discount_pct": st.column_config.NumberColumn("Disc %", format="%.0f"),
                       "margin_pct": st.column_config.NumberColumn("Margin %", format="%.1f")})
    download(ex, "sunlit_sales_exceptions")
