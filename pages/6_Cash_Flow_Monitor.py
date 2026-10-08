"""
Cash Flow Monitor — reads Finance's "Daily report on cash flow" sheet (one tab per day).

Answers: How much money do we have? Can we cover the next 7 days? Are collections
and payments going to plan? Is the weekly net cash flow positive / above ₹5 L?
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.analytics import inr
from core.cashflow import collector_accuracy, month_tracker, weekly
from core.config import CASH_TARGET as CI, THRESHOLDS as T
from core.ui import MUTED, SERIES, STATUS, alert_cards, download, get_data, hbar, money_axis, page_setup, show, sidebar

page_setup("Cash Flow Monitor", "💵")
b, alerts = get_data()
sidebar(b)
st.title("💵 Cash Flow Monitor")

cf, cc = b.get("cashflow"), b.get("cash_collectors")
if cf.empty:
    st.error("Cash flow data not available. Share the **Daily report on cash flow** sheet with the BI service "
             "account (Viewer) and press 🔄 Refresh data. See *Data sources* in the sidebar for the error.")
    st.stop()

last = cf.iloc[-1]
day = last["date"]
st.caption(f"From Finance's daily report · latest tab **{last['tab']}** ({day:%A, %d %B %Y}) · "
           f"{len(cf)} report days since {cf['date'].min():%d %b %Y}")
if (b.as_of - day).days > T["cash_report_stale_days"]:
    st.warning(f"The cash flow report was last updated on {day:%d %b} — {(b.as_of - day).days} days behind sales data.")

# ==== Company monthly target: Net Operating Cash Flow ===================================
mt = month_tracker(cf, CI)
excl = b.get("cash_exclusions")
m_name = pd.Timestamp(CI["month"] + "-01").strftime("%B %Y")
st.subheader(f"🎯 {m_name} — Net Operating Cash Flow target {inr(CI['target'])}")
if mt is None:
    st.info(f"No daily tabs with actual figures for {m_name} yet.")
else:
    c = st.columns(4)
    c[0].metric("MTD net operating", inr(mt["mtd"]),
                f"{mt['pct']:.0f}% of target · up to {mt['last_day']:%d %b}", delta_color="off", delta_arrow="off",
                help="Actual cash in − actual cash out from the daily tabs, minus APPROVED rows on the Exclusions tab")
    c[1].metric("Cash in (MTD, operating)", inr(mt["inflow"]), f"cash out {inr(mt['outflow'])}",
                delta_color="off", delta_arrow="off")
    need_txt = "target reached ✅" if mt["need"] <= 0 else f"{inr(mt['need'])} more in {mt['left_days']} working days"
    c[2].metric("Needed per working day", inr(max(mt["need_per_day"], 0)) if mt["left_days"] else "–", need_txt,
                delta_color="off", delta_arrow="off", help="Mon–Sat days left in the month (holidays not deducted)")
    c[3].metric("Month-end at current pace", inr(mt["run_rate"]),
                f"{mt['run_rate'] / CI['target'] * 100:.0f}% of target" if pd.notna(mt["run_rate"]) else None,
                delta_color="off", delta_arrow="off",
                help=f"MTD ÷ {mt['done_days']} working days × {mt['done_days'] + mt['left_days']}. Does not yet include month-end salary & statutory payments.")

    a, bb = st.columns([3, 2])
    with a:
        dd_ = mt["days"]
        fig = go.Figure()
        fig.add_scatter(x=[mt["month"], mt["month_end"]], y=[0, CI["target"]], mode="lines", name="Even pace to target",
                        line=dict(color=MUTED, dash="dash"), hoverinfo="skip")
        fig.add_hline(y=CI["target"], line_dash="dot", line_color=STATUS["Good"],
                      annotation_text=f"Target {inr(CI['target'])}", annotation_position="top left")
        fig.add_bar(x=dd_["date"], y=dd_["net_op"], name="Daily net", marker_color=SERIES[0], opacity=0.55,
                    hovertemplate="%{x|%a %d %b} net: ₹%{y:,.0f}<extra></extra>")
        fig.add_scatter(x=dd_["date"], y=dd_["cum_net"], mode="lines+markers", name="Cumulative (MTD)", marker_size=8,
                        line_color=SERIES[2], hovertemplate="%{x|%d %b} MTD: ₹%{y:,.0f}<extra></extra>")
        fig.update_layout(title=f"{m_name}: cumulative net operating cash flow vs target")
        fig.update_xaxes(range=[mt["month"] - pd.Timedelta(days=1), mt["month_end"] + pd.Timedelta(days=1)], tickformat="%d %b")
        show(money_axis(fig), 360)
    with bb:
        st.markdown(f"##### {m_name} so far")
        summ = pd.DataFrame({"": ["Operating cash in", "Operating cash out", "Net operating cash flow",
                                  "Monthly target", "Still needed"],
                             "₹": [inr(mt["inflow"]), inr(mt["outflow"]), inr(mt["mtd"]),
                                   inr(CI["target"]), inr(max(mt["need"], 0))]})
        st.dataframe(summ, hide_index=True, use_container_width=True)
        notes = []
        if pd.notna(mt["prev_month_end_out"]) and mt["left_days"]:
            notes.append(f"⚠️ Last month's final week (25th → month-end) paid out **{inr(mt['prev_month_end_out'])}** "
                         f"(net {inr(mt['prev_month_end_net'])}) — salary, ESI/PF, OD interest. Plan collections to cover it.")
        if mt["excluded_in"] or mt["excluded_out"]:
            notes.append(f"Excluded as non-operating (approved): in {inr(mt['excluded_in'])}, out {inr(mt['excluded_out'])}.")
        if mt["pending_in"] or mt["pending_out"]:
            notes.append(f"🕓 Awaiting Management approval on the Exclusions tab: in {inr(mt['pending_in'])}, "
                         f"out {inr(mt['pending_out'])} — not yet applied.")
        for n in notes:
            st.caption(n)
st.divider()

act = cf[cf["has_actual"]]
wk = weekly(act)
cur_week = (day - pd.Timedelta(days=(day.dayofweek + 1) % 7)).normalize()
done = wk[wk["week"] < cur_week]
this_w = wk[wk["week"] == cur_week]

# ---- KPI row 1: position & next 7 days -------------------------------------------
c = st.columns(4)
prev = cf.iloc[-2]["close_total"] if len(cf) > 1 else np.nan
c[0].metric("Available funds (closing)", inr(last["close_total"]),
            f"{inr(last['close_total'] - prev)} vs previous day" if pd.notna(prev) else None,
            help="Cash in hand + Federal Bank OD available balance + SBI, as closed on the latest report day")
cover = last["close_total"] / last["oblig_7d"] if last["oblig_7d"] else np.nan
c[1].metric("Payments due — next 7 days", inr(last["oblig_7d"]),
            f"funds cover {cover:.1f}x" if pd.notna(cover) else "nothing listed",
            delta_color="normal" if pd.isna(cover) or cover >= T["cash_cover_min"] else "inverse", delta_arrow="off",
            help=f"Section 3 of the daily report. Alert when funds < {T['cash_cover_min']}x of this.")
c[2].metric("Expected collections — next 14 days", inr(last["recv_14d"]), help="Section 4 of the daily report (all collectors)")
if not this_w.empty:
    r = this_w.iloc[0]
    c[3].metric("Net cash flow — this week", inr(r["net"]), f"{int(r['days'])} days so far · target {inr(T['weekly_net_target'])}",
                delta_color="off", delta_arrow="off")

# ---- KPI row 2: performance --------------------------------------------------------
c = st.columns(4)
if not done.empty:
    r = done.iloc[-1]
    ok = r["net"] >= T["weekly_net_target"]
    c[0].metric("Net cash flow — last full week", inr(r["net"]),
                ("✅ above" if ok else "⚠️ below" if r["net"] >= 0 else "🔴 negative") + f" · week of {r['week']:%d %b}",
                delta_color="off", delta_arrow="off")
    last8 = done.tail(8)
    hit = int((last8["net"] >= 0).sum())
    c[1].metric("Positive weeks (last 8)", f"{hit} / {len(last8)}",
                f"{int((last8['net'] >= T['weekly_net_target']).sum())} met the ₹5 L target", delta_color="off", delta_arrow="off")
l30 = act[act["date"] > day - pd.Timedelta(days=30)]
if not l30.empty:
    c[2].metric("Collected — last 30 days", inr(l30["inflow_act"].sum()),
                f"plan was {inr(l30['inflow_exp'].sum())}", delta_color="off", delta_arrow="off")
    c[3].metric("Paid — last 30 days", inr(l30["outflow_act"].sum()),
                f"plan was {inr(l30['outflow_exp'].sum())}", delta_color="off", delta_arrow="off")

cash_al = alerts[alerts["category"] == "Cash flow"] if not alerts.empty else alerts
if not cash_al.empty:
    with st.expander(f"🚨 {len(cash_al)} cash flow alert(s) — owner: Finance", expanded=False):
        alert_cards(cash_al, 6)

tabs = st.tabs(["Funds position", "Weekly cash flow", "Plan vs actual", "Collectors (14-day list)", "Exclusions", "Data checks", "Daily data"])

# ---- 1. Funds position ----------------------------------------------------------------
with tabs[0]:
    rng = st.radio("Period", ["Last 60 days", "Last 120 days", "All"], horizontal=True, index=1, key="cf_rng")
    days = {"Last 60 days": 60, "Last 120 days": 120}.get(rng)
    v = cf if days is None else cf[cf["date"] > day - pd.Timedelta(days=days)]
    fig = go.Figure()
    fig.add_scatter(x=v["date"], y=v["close_total"], mode="lines+markers", name="Available funds", marker_size=8,
                    line_color=SERIES[0], hovertemplate="%{x|%a %d %b}: ₹%{y:,.0f}<extra></extra>")
    fig.add_scatter(x=v["date"], y=v["oblig_7d"], mode="lines", name="Payments due next 7 days",
                    line=dict(color=SERIES[1], dash="dot"), hovertemplate="due 7d: ₹%{y:,.0f}<extra></extra>")
    fig.update_layout(title="Closing funds vs next-7-day obligations")
    fig.update_xaxes(tickformat="%d %b")
    show(money_axis(fig), 380)

    a, bb = st.columns([3, 2])
    with a:
        fig = go.Figure()
        for i, (k, lab) in enumerate([("close_federal", "Federal Bank (OD available)"), ("close_sbi", "SBI"), ("close_cash", "Cash in hand")]):
            fig.add_scatter(x=v["date"], y=v[k], mode="lines", name=lab, line_color=SERIES[i],
                            hovertemplate=f"{lab}: ₹%{{y:,.0f}}<extra></extra>")
        fig.update_layout(title="Closing balance by account")
        fig.update_xaxes(tickformat="%d %b")
        show(money_axis(fig), 340)
    with bb:
        acc = pd.DataFrame({"account": ["Federal Bank (OD available)", "SBI", "Cash in hand"],
                            "amount": [last["close_federal"], last["close_sbi"], last["close_cash"]]}).fillna(0)
        hbar(acc, "amount", "account", f"Where the money is — {day:%d %b}")
    st.caption("Federal Bank is the **OD available balance**, so falling funds can mean more OD being used, not only less cash.")

# ---- 2. Weekly cash flow ----------------------------------------------------------------
with tabs[1]:
    w = wk.tail(16).copy()
    w["label"] = w["week"].dt.strftime("%d %b") + np.where(w["week"] == cur_week, " (part)", "")
    fig = go.Figure()
    fig.add_bar(x=w["label"], y=w["inflow"], name="Cash in (actual)", marker_color=SERIES[2],
                hovertemplate="%{x}<br>In: ₹%{y:,.0f}<extra></extra>")
    fig.add_bar(x=w["label"], y=w["outflow"], name="Cash out (actual)", marker_color=SERIES[1],
                hovertemplate="%{x}<br>Out: ₹%{y:,.0f}<extra></extra>")
    fig.update_layout(barmode="group", title="Weekly cash in vs cash out (weeks start Sunday)")
    show(money_axis(fig), 360)

    colors = [STATUS["Critical"] if n < 0 else STATUS["Medium"] if n < T["weekly_net_target"] else STATUS["Good"] for n in w["net"]]
    fig = go.Figure(go.Bar(x=w["label"], y=w["net"], marker_color=colors, name="Net cash flow",
                           text=[inr(n) for n in w["net"]], textposition="outside", cliponaxis=False,
                           hovertemplate="%{x}<br>Net: %{text}<extra></extra>"))
    fig.add_hline(y=T["weekly_net_target"], line_dash="dash", line_color=MUTED,
                  annotation_text=f"Target {inr(T['weekly_net_target'])}", annotation_position="top right")
    fig.add_hline(y=0, line_color="rgba(128,128,128,.5)", line_width=1)
    fig.update_layout(title="Net cash flow per week — 🟢 ≥ target · 🟡 positive · 🔴 negative")
    fig.update_yaxes(visible=False)
    show(fig, 340, legend=False)
    view = w[["week", "days", "inflow", "outflow", "net", "closing"]].sort_values("week", ascending=False)
    st.dataframe(view, hide_index=True, use_container_width=True,
                 column_config={"week": st.column_config.DateColumn("Week from", format="DD-MMM-YY"),
                                **{k: st.column_config.NumberColumn(k.title() + " ₹", format="%.0f")
                                   for k in ["inflow", "outflow", "net", "closing"]}})

# ---- 3. Plan vs actual ----------------------------------------------------------------------
with tabs[2]:
    m = collector_accuracy(cf)
    a, bb = st.columns(2)
    for col_, (e, ac, ttl, clr) in zip([a, bb], [("expected", "actual", "Collections: planned vs received", SERIES[2]),
                                                  ("pay_exp", "pay_act", "Payments: planned vs paid", SERIES[1])]):
        with col_:
            fig = go.Figure()
            fig.add_bar(x=m["month"], y=m[e], name="Planned", marker_color=SERIES[0],
                        hovertemplate="%{x|%b %Y} planned: ₹%{y:,.0f}<extra></extra>")
            fig.add_bar(x=m["month"], y=m[ac], name="Actual", marker_color=clr,
                        hovertemplate="%{x|%b %Y} actual: ₹%{y:,.0f}<extra></extra>")
            fig.update_layout(barmode="group", title=ttl)
            fig.update_xaxes(tickformat="%b %y")
            show(money_axis(fig), 330)
    st.markdown("##### What this means")
    l = m.iloc[-2] if len(m) > 1 and m.iloc[-1]["month"] == day.replace(day=1) and day.day < 10 else m.iloc[-1]
    st.markdown(
        f"- In **{l['month']:%B}**, actual collections were **{l['inflow_var_pct']:+.0f}%** vs the daily plan, "
        f"and payments **{l['outflow_var_pct']:+.0f}%** vs the payment list.\n"
        "- Large positive gaps mean money is arriving / going out **without being listed in advance** — "
        "the plan should capture it so the 7-day view can be trusted.")
    dd = act[["date", "tab", "inflow_exp", "inflow_act", "outflow_exp", "outflow_act", "net_act"]].tail(30).iloc[::-1]
    st.dataframe(dd, hide_index=True, use_container_width=True,
                 column_config={"date": st.column_config.DateColumn("Date", format="ddd DD-MMM"),
                                "tab": st.column_config.TextColumn("Tab"),
                                **{k: st.column_config.NumberColumn(lab, format="%.0f") for k, lab in
                                   [("inflow_exp", "In — plan ₹"), ("inflow_act", "In — actual ₹"),
                                    ("outflow_exp", "Out — plan ₹"), ("outflow_act", "Out — actual ₹"), ("net_act", "Net ₹")]}})

# ---- 4. Collectors -------------------------------------------------------------------------------
with tabs[3]:
    if cc.empty:
        st.info("No collector-wise 14-day list found.")
    else:
        latest = cc[cc["date"] == cc["date"].max()]
        a, bb = st.columns([2, 3])
        with a:
            hbar(latest, "expected_14d", "collector", f"Expected in next 14 days — {cc['date'].max():%d %b}", color=SERIES[2])
        with bb:
            t = cc[cc["date"] > day - pd.Timedelta(days=90)]
            fig = go.Figure()
            for i, name in enumerate(sorted(t["collector"].unique())):
                s = t[t["collector"] == name]
                fig.add_scatter(x=s["date"], y=s["expected_14d"], mode="lines", name=name, line_color=SERIES[i % len(SERIES)],
                                hovertemplate=f"{name}: ₹%{{y:,.0f}}<extra></extra>")
            fig.update_layout(title="14-day expected collections by collector — last 90 days")
            fig.update_xaxes(tickformat="%d %b")
            show(money_axis(fig), 340)
        stuck = t.groupby("collector")["expected_14d"].agg(lambda s: s.tail(10).nunique() == 1 and s.iloc[-1] > 0)
        stuck = [k for k, v in stuck.items() if v]
        if stuck:
            st.info("Not updated for the last 10 report days: **" + ", ".join(stuck) +
                    "** — the 14-day list should change as money comes in.")

# ---- Exclusions (non-operating items) ------------------------------------------------------------
with tabs[4]:
    st.markdown("Receipts / payments that are **not normal operations** (OD or loan, transfers between own accounts, "
                "capital, capex, FD, one-time items). Finance adds them on the **Exclusions** tab of the cash flow sheet; "
                "only rows ticked **Approved** by Management are removed from the operating figures.")
    if excl is None or excl.empty:
        st.info("No exclusions entered yet.")
    else:
        v = excl.sort_values("date", ascending=False)
        a, bb = st.columns(2)
        a.metric("Approved", inr(v.loc[v["approved"], "amount"].sum()), f"{int(v['approved'].sum())} rows", delta_color="off", delta_arrow="off")
        bb.metric("Awaiting approval", inr(v.loc[~v["approved"], "amount"].sum()), f"{int((~v['approved']).sum())} rows", delta_color="off", delta_arrow="off")
        st.dataframe(v, hide_index=True, use_container_width=True,
                     column_config={"date": st.column_config.DateColumn("Date", format="DD-MMM-YY"),
                                    "amount": st.column_config.NumberColumn("Amount ₹", format="%.0f"),
                                    "approved": st.column_config.CheckboxColumn("Approved")})

# ---- 5. Data checks --------------------------------------------------------------------------------------
with tabs[5]:
    st.markdown("The dashboard checks every tab so wrong numbers are caught early.")
    chk = cf.copy()
    issues = []
    for _, r in chk.iterrows():
        if pd.notna(r["carry_gap"]) and abs(r["carry_gap"]) >= 1:
            issues.append((r["date"], r["tab"], "Opening ≠ previous day's closing", r["carry_gap"]))
        if pd.notna(r["recon_gap"]) and abs(r["recon_gap"]) >= T["recon_gap_min"]:
            issues.append((r["date"], r["tab"], "Opening + in − out ≠ closing", r["recon_gap"]))
        if not r["has_actual"]:
            issues.append((r["date"], r["tab"], "No actual inflow / outflow entered", np.nan))
    iss = pd.DataFrame(issues, columns=["date", "tab", "check", "difference"]).sort_values("date", ascending=False)
    a, bb, cc_ = st.columns(3)
    a.metric("Days checked", len(chk))
    bb.metric("Days with an issue", iss["date"].nunique() if not iss.empty else 0)
    cc_.metric("Issues in last 30 days", int((iss["date"] > day - pd.Timedelta(days=30)).sum()) if not iss.empty else 0)
    st.dataframe(iss, hide_index=True, use_container_width=True,
                 column_config={"date": st.column_config.DateColumn("Date", format="DD-MMM-YY"),
                                "difference": st.column_config.NumberColumn("Difference ₹", format="%.0f")})
    download(iss, "sunlit_cashflow_data_checks")

# ---- 6. Daily data ----------------------------------------------------------------------------------------
with tabs[6]:
    cols = ["date", "tab", "open_total", "inflow_exp", "inflow_act", "outflow_exp", "outflow_act", "close_total",
            "close_cash", "close_federal", "close_sbi", "oblig_7d", "recv_14d", "recon_gap"]
    st.dataframe(cf[cols].iloc[::-1], hide_index=True, use_container_width=True,
                 column_config={"date": st.column_config.DateColumn("Date", format="ddd DD-MMM-YY"),
                                **{k: st.column_config.NumberColumn(format="%.0f") for k in cols[2:]}})
    download(cf[cols], "sunlit_cashflow_daily")
