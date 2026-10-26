import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.analytics import inr, window
from core.config import THRESHOLDS as T
from core.ui import SERIES, STATUS, download, get_data, hbar, money_axis, page_setup, show, sidebar

page_setup("Receivables Intelligence", "💰", key="receivables")
b, alerts = get_data()
sidebar(b)
st.title("💰 Receivables Intelligence")

osd, col, sales = b.get("outstanding"), b.get("collections"), b.get("sales")
as_of = b.as_of
if osd.empty:
    st.error("Outstanding data not available — check Data sources.")
    st.stop()

o = osd[osd["amount"] > 0].copy()
if not col.empty:
    last_pay = col.groupby("dealer_code")["date"].max().rename("last_payment")
    paid30 = window(col, as_of, 30).groupby("dealer_code")["amount"].sum().rename("paid_30d")
    o = o.merge(last_pay, on="dealer_code", how="left").merge(paid30, on="dealer_code", how="left")
    o["paid_30d"] = o["paid_30d"].fillna(0)
    o["days_since_payment"] = (as_of - o["last_payment"]).dt.days
else:
    o["last_payment"], o["paid_30d"], o["days_since_payment"] = pd.NaT, 0, np.nan

tot, above = o["amount"].sum(), o["above60"].sum()
c = st.columns(4)
c[0].metric("Total outstanding", inr(tot), f"{len(o)} dealers", delta_color="off", delta_arrow="off")
c[1].metric("Overdue > 60 days", inr(above), f"{above / max(tot, 1) * 100:.0f}% of total", delta_color="off", delta_arrow="off")
if not col.empty:
    l30 = window(col, as_of, 30)["amount"].sum()
    c[2].metric("Collections — last 30 days", inr(l30))
    if not sales.empty:
        s90 = window(sales, as_of, 90)["amount"].sum() * 1.18       # sales are pre-GST; receivables include GST
        dso = tot / max(s90 / 90, 1)
        c[3].metric("Days sales outstanding (DSO)", f"{dso:.0f} days", help="Outstanding ÷ avg daily billing incl. 18% GST, last 90 days")

tabs = st.tabs(["Ageing & overdue", "Collections trend", "By executive", "All dealers"])

with tabs[0]:
    a, bb = st.columns([2, 3])
    with a:
        fig = go.Figure(go.Bar(x=["Up to 60 days", "Above 60 days"], y=[o["upto60"].sum(), above],
                               marker_color=[SERIES[0], STATUS["Critical"]],
                               text=[inr(o["upto60"].sum()), inr(above)], textposition="outside", cliponaxis=False,
                               hovertemplate="%{x}: %{text}<extra></extra>"))
        fig.update_layout(title="Outstanding by age")
        fig.update_yaxes(visible=False)
        show(fig, legend=False)
    with bb:
        hbar(o.nlargest(10, "above60"), "above60", "dealer", "Top 10 overdue dealers (> 60 days)", color=STATUS["Critical"])
    st.markdown(f"##### 🔴 Collection priority list — overdue ≥ {inr(T['overdue_min_value'])}")
    pr = o[o["above60"] >= T["overdue_min_value"]].copy()
    pr["risk"] = np.where(pr["paid_30d"] <= 0, "No payment in 30 days", "Paying")
    st.dataframe(pr.sort_values(["above60"], ascending=False)[
        ["dealer_code", "dealer", "executive", "amount", "upto60", "above60", "paid_30d", "last_payment", "days_since_payment", "risk", "remarks"]],
        hide_index=True, use_container_width=True,
        column_config={"amount": st.column_config.NumberColumn("Total ₹", format="%.0f"),
                       "upto60": st.column_config.NumberColumn("≤60d ₹", format="%.0f"),
                       "above60": st.column_config.NumberColumn(">60d ₹", format="%.0f"),
                       "paid_30d": st.column_config.NumberColumn("Paid 30D ₹", format="%.0f"),
                       "last_payment": st.column_config.DateColumn("Last payment", format="DD-MMM-YY"),
                       "days_since_payment": st.column_config.NumberColumn("Days since paid", format="%.0f")})
    download(pr, "sunlit_collection_priority")

with tabs[1]:
    if col.empty:
        st.info("Collections data not available.")
    else:
        cm = col[col["date"] > as_of - pd.DateOffset(months=12)].copy()
        cm["month"] = cm["date"].dt.to_period("M").dt.to_timestamp()
        mm = cm.groupby("month")["amount"].sum().reset_index()
        fig = go.Figure()
        fig.add_bar(x=mm["month"], y=mm["amount"], name="Collections", marker_color=SERIES[2],
                    hovertemplate="%{x|%b %Y}: ₹%{y:,.0f}<extra></extra>")
        if not sales.empty:
            sm = sales[sales["date"] > as_of - pd.DateOffset(months=12)].groupby("month")["amount"].sum() * 1.18
            sm = sm.reindex(mm["month"]).reset_index()
            fig.add_bar(x=sm["month"], y=sm["amount"], name="Billing incl. GST (est.)", marker_color=SERIES[0],
                        hovertemplate="%{x|%b %Y}: ₹%{y:,.0f}<extra></extra>")
        fig.update_layout(barmode="group", title="Monthly collections vs billing (current month partial)")
        fig.update_xaxes(tickformat="%b %y")
        show(money_axis(fig), 360)
        top = window(col, as_of, 30).groupby("dealer")["amount"].sum().nlargest(10).reset_index()
        hbar(top, "amount", "dealer", "Top paying dealers — last 30 days", color=SERIES[2])

with tabs[2]:
    e = o.groupby("executive").agg(dealers=("dealer_code", "count"), outstanding=("amount", "sum"),
                                   overdue=("above60", "sum"), paid_30d=("paid_30d", "sum")).reset_index()
    e["overdue %"] = e["overdue"] / e["outstanding"].replace(0, np.nan) * 100
    fig = go.Figure()
    fig.add_bar(x=e["executive"], y=e["outstanding"] - e["overdue"], name="≤ 60 days", marker_color=SERIES[0],
                marker_line=dict(width=1, color="rgba(255,255,255,.9)"), hovertemplate="%{x} ≤60d: ₹%{y:,.0f}<extra></extra>")
    fig.add_bar(x=e["executive"], y=e["overdue"], name="> 60 days", marker_color=STATUS["Critical"],
                marker_line=dict(width=1, color="rgba(255,255,255,.9)"), hovertemplate="%{x} >60d: ₹%{y:,.0f}<extra></extra>")
    fig.update_layout(barmode="stack", title="Outstanding by sales executive")
    show(money_axis(fig))
    st.dataframe(e.sort_values("overdue", ascending=False), hide_index=True, use_container_width=True,
                 column_config={k: st.column_config.NumberColumn(format="%.0f") for k in ["outstanding", "overdue", "paid_30d"]} |
                               {"overdue %": st.column_config.NumberColumn(format="%.0f%%")})

with tabs[3]:
    st.dataframe(o.sort_values("amount", ascending=False), hide_index=True, use_container_width=True)
    download(o, "sunlit_receivables")
