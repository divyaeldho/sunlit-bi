"""
Sunlit AI Business Intelligence & Decision Support System — Phase 1
Executive Management Dashboard (home page)

Run:  streamlit run Executive_Dashboard.py
"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.analytics import alert_summary, daily_series, diverse_top, inr, sales_kpis, window
from core.ui import (SERIES, STATUS, alert_cards, delta_str, get_data, money_axis,
                     page_setup, show, sidebar)

page_setup("Executive Dashboard", "☀️", key="exec")
b, alerts = get_data()
sidebar(b)

st.title("Executive Management Dashboard")
st.caption(f"Sunlit Electro Controls · data up to **{b.as_of:%A, %d %B %Y}**")

sales, osd, fg, rm, col = b.get("sales"), b.get("outstanding"), b.get("fg_stock"), b.get("rm_stock"), b.get("collections")
k = sales_kpis(sales, b.as_of) if not sales.empty else {}

# ---- KPI row 1: sales ---------------------------------------------------------
c = st.columns(4)
if k:
    c[0].metric("Sales — month to date", inr(k["mtd_sales"]), delta_str(k["mtd_growth"]),
                help="vs the same number of days last month")
    c[1].metric("Month-end projection", inr(k["mtd_projection"]), help="Run-rate: MTD ÷ days elapsed × days in month")
    c[2].metric("Gross margin (MTD)", f"{k['mtd_margin_pct']:.1f}%")
    c[3].metric("Dealers billed (MTD)", f"{k['mtd_dealers']}", help=f"{k['mtd_invoices']} invoices")

# ---- KPI row 2: cash, stock, risk --------------------------------------------------
c = st.columns(4)
if not osd.empty:
    share = osd["above60"].sum() / max(osd["amount"].sum(), 1) * 100
    c[0].metric("Receivables outstanding", inr(osd["amount"].sum()), f"{share:.0f}% above 60 days",
                delta_color="off", delta_arrow="off")
if not col.empty:
    m_start = b.as_of.replace(day=1)
    c[1].metric("Collections (MTD)", inr(col.loc[col["date"] >= m_start, "amount"].sum()))
stock_val = (fg["stock_value"].sum() if not fg.empty else 0) + (rm["stock_value"].sum() if not rm.empty else 0)
c[2].metric("Inventory value (RM + FG)", inr(stock_val),
            f"RM {inr(rm['stock_value'].sum()) if not rm.empty else '–'} · FG {inr(fg['stock_value'].sum()) if not fg.empty else '–'}",
            delta_color="off", delta_arrow="off")
crit = int((alerts["severity"] == "Critical").sum()) if not alerts.empty else 0
c[3].metric("Open alerts", f"{len(alerts)}", f"{crit} critical", delta_color="inverse" if crit else "off")

st.write("")

# ---- Charts -----------------------------------------------------------------
left, right = st.columns([3, 2])
with left:
    if not sales.empty:
        m = sales[sales["date"] > b.as_of - pd.DateOffset(months=13)].groupby("month").agg(
            amount=("amount", "sum"), margin=("margin", "sum")).reset_index()
        fig = go.Figure(go.Bar(x=m["month"], y=m["amount"], marker_color=SERIES[0], name="Sales",
                               hovertemplate="%{x|%b %Y}<br>₹%{y:,.0f}<extra></extra>"))
        fig.update_layout(title="Monthly sales (current month is partial)")
        fig.update_xaxes(tickformat="%b %y")
        show(money_axis(fig), legend=False)
with right:
    if not sales.empty:
        m["margin_pct"] = m["margin"] / m["amount"] * 100
        fig = go.Figure(go.Scatter(x=m["month"], y=m["margin_pct"], mode="lines+markers", marker_size=8,
                                   line_color=SERIES[2], name="Margin %",
                                   hovertemplate="%{x|%b %Y}: %{y:.1f}%<extra></extra>"))
        fig.update_layout(title="Gross margin % by month")
        fig.update_yaxes(ticksuffix="%")
        fig.update_xaxes(tickformat="%b %y")
        show(fig, legend=False)

left, right = st.columns([3, 2])
with left:
    if not sales.empty:
        ds = daily_series(sales, b.as_of, 90)
        fig = go.Figure()
        fig.add_bar(x=ds["date"], y=ds["amount"], marker_color=SERIES[0], name="Daily sales",
                    hovertemplate="%{x|%a %d %b}<br>₹%{y:,.0f}<extra></extra>")
        fig.add_scatter(x=ds["date"], y=ds["rolling"], mode="lines", line_color=SERIES[1], name="20-day average",
                        hovertemplate="avg ₹%{y:,.0f}<extra></extra>")
        an = ds[ds["z"].abs() >= 2.5]
        if not an.empty:
            fig.add_scatter(x=an["date"], y=an["amount"], mode="markers", name="Anomaly",
                            marker=dict(size=11, color=STATUS["Critical"], symbol="diamond", line=dict(width=2, color="white")),
                            hovertemplate="Anomaly %{x|%d %b}: ₹%{y:,.0f}<extra></extra>")
        fig.update_layout(title="Daily sales — last 90 days (Sundays excluded)", hovermode="x unified")
        show(money_axis(fig))
with right:
    summ = alert_summary(alerts)
    st.markdown("##### Early-warning summary")
    if summ.empty:
        st.success("No active alerts.")
    else:
        view = summ.assign(**{"₹ at stake": summ["₹ at stake"].map(inr)})
        st.dataframe(view, hide_index=True, use_container_width=True,
                     column_config={"category": st.column_config.TextColumn("Alert category", width="medium"),
                                    "Critical": st.column_config.NumberColumn("🔴", width="small"),
                                    "High": st.column_config.NumberColumn("🟠", width="small"),
                                    "Medium": st.column_config.NumberColumn("🟡", width="small"),
                                    "Total": st.column_config.NumberColumn(width="small"),
                                    "₹ at stake": st.column_config.TextColumn(width="small")})

st.markdown("#### 🚨 Top issues needing attention")
if alerts.empty:
    st.success("Nothing critical right now.")
else:
    cols = st.columns(2)
    top = diverse_top(alerts, per_cat=1, n=8)
    with cols[0]:
        alert_cards(top.iloc[::2], 4)
    with cols[1]:
        alert_cards(top.iloc[1::2], 4)
    st.page_link("pages/5_Alerts_and_AI_Brief.py", label="Open full Alert Centre & AI Brief →", icon="🧠")
