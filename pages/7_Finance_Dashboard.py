"""
Finance Dashboard — one screen for the Finance team (Dhaya).

Cash position, the monthly net operating cash flow target, receivables and collections,
and every alert owned by Finance. Detail stays on the Cash Flow Monitor and
Receivables Intelligence pages.
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.analytics import inr, window
from core.cashflow import month_tracker
from core.config import CASH_TARGET as CI, PAGES, THRESHOLDS as T
from core.ui import (MUTED, SERIES, STATUS, alert_cards, download, get_data, hbar, money_axis,
                     page_setup, show, sidebar)

page_setup("Finance Dashboard", "🏦", key="finance")
b, alerts = get_data()
sidebar(b)

st.title("🏦 Finance Dashboard")
st.caption(f"Cash, receivables and Finance alerts · data up to **{b.as_of:%A, %d %B %Y}**")

cf, osd, col, sales = b.get("cashflow"), b.get("outstanding"), b.get("collections"), b.get("sales")
fin_al = alerts[alerts["department"] == "Finance"] if not alerts.empty else alerts

# ==== 1. Cash position ===================================================================
st.subheader("💵 Cash")
if cf.empty:
    st.info("Cash flow report not connected — see *Data sources* in the sidebar.")
    mt = None
else:
    last = cf.iloc[-1]
    day = last["date"]
    if (b.as_of - day).days > T["cash_report_stale_days"]:
        st.warning(f"Cash flow report last updated **{day:%d %b}** — {(b.as_of - day).days} days behind sales data.")
    mt = month_tracker(cf, CI)
    c = st.columns(4)
    prev = cf.iloc[-2]["close_total"] if len(cf) > 1 else np.nan
    c[0].metric("Available funds", inr(last["close_total"]),
                f"{inr(last['close_total'] - prev)} vs previous day" if pd.notna(prev) else None,
                help=f"Cash + Federal Bank OD available + SBI, closing on {day:%d %b}")
    cover = last["close_total"] / last["oblig_7d"] if last["oblig_7d"] else np.nan
    c[1].metric("Payments due — next 7 days", inr(last["oblig_7d"]),
                f"funds cover {cover:.1f}x" if pd.notna(cover) else "nothing listed",
                delta_color="normal" if pd.isna(cover) or cover >= T["cash_cover_min"] else "inverse", delta_arrow="off")
    c[2].metric("Expected collections — next 14 days", inr(last["recv_14d"]))
    if mt is not None:
        c[3].metric("Net operating cash flow (MTD)", inr(mt["mtd"]),
                    f"{mt['pct']:.0f}% of {inr(CI['target'])} target", delta_color="off", delta_arrow="off")

# ==== 2. Receivables =====================================================================
st.subheader("💰 Receivables")
o = osd[osd["amount"] > 0].copy() if not osd.empty else pd.DataFrame()
c = st.columns(4)
if not o.empty:
    tot, above = o["amount"].sum(), o["above60"].sum()
    c[0].metric("Total outstanding", inr(tot), f"{len(o)} dealers", delta_color="off", delta_arrow="off")
    c[1].metric("Overdue > 60 days", inr(above), f"{above / max(tot, 1) * 100:.0f}% of total",
                delta_color="off", delta_arrow="off")
if not col.empty:
    l30, p30 = window(col, b.as_of, 30)["amount"].sum(), window(col, b.as_of, 30, 30)["amount"].sum()
    c[2].metric("Collections — last 30 days", inr(l30),
                f"{(l30 - p30) / p30 * 100:+.0f}% vs previous 30" if p30 else None)
    if not o.empty and not sales.empty:
        s90 = window(sales, b.as_of, 90)["amount"].sum() * 1.18          # sales pre-GST; receivables incl. GST
        c[3].metric("Days sales outstanding", f"{o['amount'].sum() / max(s90 / 90, 1):.0f} days",
                    help="Outstanding ÷ avg daily billing incl. 18% GST, last 90 days")

st.write("")

# ==== 3. Charts ==========================================================================
left, right = st.columns([3, 2])
with left:
    if mt is not None:
        dd_ = mt["days"]
        fig = go.Figure()
        fig.add_scatter(x=[mt["month"], mt["month_end"]], y=[0, CI["target"]], mode="lines", name="Even pace",
                        line=dict(color=MUTED, dash="dash"), hoverinfo="skip")
        fig.add_bar(x=dd_["date"], y=dd_["net_op"], name="Daily net", marker_color=SERIES[0], opacity=0.55,
                    hovertemplate="%{x|%a %d %b} net: ₹%{y:,.0f}<extra></extra>")
        fig.add_scatter(x=dd_["date"], y=dd_["cum_net"], mode="lines+markers", name="Cumulative", marker_size=7,
                        line_color=SERIES[2], hovertemplate="%{x|%d %b} MTD: ₹%{y:,.0f}<extra></extra>")
        fig.update_layout(title=f"{pd.Timestamp(CI['month'] + '-01'):%B}: net operating cash flow vs {inr(CI['target'])} target")
        fig.update_xaxes(range=[mt["month"] - pd.Timedelta(days=1), mt["month_end"] + pd.Timedelta(days=1)], tickformat="%d %b")
        show(money_axis(fig), 340)
    elif not col.empty:
        st.info("No daily cash flow figures for this month yet.")
with right:
    if not o.empty:
        fig = go.Figure(go.Bar(x=["Up to 60 days", "Above 60 days"], y=[o["upto60"].sum(), o["above60"].sum()],
                               marker_color=[SERIES[0], STATUS["Critical"]],
                               text=[inr(o["upto60"].sum()), inr(o["above60"].sum())], textposition="outside",
                               cliponaxis=False, hovertemplate="%{x}: %{text}<extra></extra>"))
        fig.update_layout(title="Outstanding by age")
        fig.update_yaxes(visible=False)
        show(fig, 340, legend=False)

left, right = st.columns([3, 2])
with left:
    if not col.empty:
        cm = col[col["date"] > b.as_of - pd.DateOffset(months=12)].copy()
        cm["month"] = cm["date"].dt.to_period("M").dt.to_timestamp()
        mm = cm.groupby("month")["amount"].sum().reset_index()
        fig = go.Figure()
        fig.add_bar(x=mm["month"], y=mm["amount"], name="Collections", marker_color=SERIES[2],
                    hovertemplate="%{x|%b %Y}: ₹%{y:,.0f}<extra></extra>")
        if not sales.empty:
            sm = (sales[sales["date"] > b.as_of - pd.DateOffset(months=12)].groupby("month")["amount"].sum() * 1.18)
            sm = sm.reindex(mm["month"]).reset_index()
            fig.add_bar(x=sm["month"], y=sm["amount"], name="Billing incl. GST (est.)", marker_color=SERIES[0],
                        hovertemplate="%{x|%b %Y}: ₹%{y:,.0f}<extra></extra>")
        fig.update_layout(barmode="group", title="Monthly collections vs billing (current month partial)")
        fig.update_xaxes(tickformat="%b %y")
        show(money_axis(fig), 340)
with right:
    if not o.empty:
        hbar(o.nlargest(8, "above60"), "above60", "dealer", "Top overdue dealers (> 60 days)", color=STATUS["Critical"])

# ==== 4. Collection priority list ========================================================
if not o.empty:
    st.markdown(f"#### 🔴 Collection priority — overdue ≥ {inr(T['overdue_min_value'])}")
    pr = o[o["above60"] >= T["overdue_min_value"]].copy()
    if not col.empty:
        paid30 = window(col, b.as_of, 30).groupby("dealer_code")["amount"].sum().rename("paid_30d")
        last_pay = col.groupby("dealer_code")["date"].max().rename("last_payment")
        pr = pr.merge(paid30, on="dealer_code", how="left").merge(last_pay, on="dealer_code", how="left")
        pr["paid_30d"] = pr["paid_30d"].fillna(0)
    else:
        pr["paid_30d"], pr["last_payment"] = 0, pd.NaT
    pr = pr.sort_values(["paid_30d", "above60"], ascending=[True, False])
    st.dataframe(pr[["dealer", "executive", "amount", "above60", "paid_30d", "last_payment"]].head(15),
                 hide_index=True, use_container_width=True,
                 column_config={"amount": st.column_config.NumberColumn("Total ₹", format="%.0f"),
                                "above60": st.column_config.NumberColumn(">60d ₹", format="%.0f"),
                                "paid_30d": st.column_config.NumberColumn("Paid 30D ₹", format="%.0f"),
                                "last_payment": st.column_config.DateColumn("Last payment", format="DD-MMM-YY")})
    st.caption(f"{len(pr)} dealers · those with no payment in 30 days first")
    download(pr, "sunlit_finance_collection_priority")

# ==== 5. Finance alerts ==================================================================
st.markdown(f"#### 🚨 Finance alerts ({len(fin_al)})")
if fin_al.empty:
    st.success("No open Finance alerts.")
else:
    cols = st.columns(2)
    with cols[0]:
        alert_cards(fin_al.iloc[::2], 4)
    with cols[1]:
        alert_cards(fin_al.iloc[1::2], 4)

st.divider()
c = st.columns(2)
for col_, k in zip(c, ["cashflow", "receivables"]):
    path, label, icon = PAGES[k]
    col_.page_link(path, label=f"Open {label} for full detail →", icon=icon)
