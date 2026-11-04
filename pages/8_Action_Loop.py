import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.actions import (AUTO, LATE, MISSED, ON_TIME, OUTCOMES, PENDING, TYPE_ORDER, kpis, owner_view, prepare,
                          today, weekly)
from core.analytics import inr
from core.config import ACT_TARGET_PCT, ACT_WITHIN_DAYS, SHEETS
from core.ui import SERIES, STATUS, download, get_data, page_setup, show, sidebar

page_setup("Alert Action Loop", "✅", key="actions")
b, _ = get_data()
sidebar(b)
st.title("✅ Alert Action Loop")
st.caption(f"Data → Trend → Risk → Alert → **Owner → Action**. Alerts are raised each morning by the Sunlit Alert Tracker; "
           f"owners record what they did in its web form. Target: every alert acted on within {ACT_WITHIN_DAYS} days.")

log = b.get("alert_log")
if log.empty:
    h = next((x for x in b.health if x["source"] == "alert_log"), {})
    st.error("Alert Tracker not readable yet. Share the **Sunlit Alert Tracker** sheet with the BI service account "
             "(Viewer) and press 🔄 Refresh data.")
    if h.get("detail"):
        st.caption(h["detail"])
    st.stop()

as_of = today()
a = prepare(log, as_of)
k = kpis(a, as_of)

# ---- headline ---------------------------------------------------------------------------------
c = st.columns(5)
lp, pp = k["last_pct"], k["prev_pct"]
c[0].metric(f"Acted ≤ {ACT_WITHIN_DAYS} days — last full week",
            "–" if np.isnan(lp) else f"{lp:.0f}%",
            None if np.isnan(lp) or np.isnan(pp) else f"{lp - pp:+.0f} pts vs week before",
            help=f"Week of {k['last_week']:%d-%b} (Mon–Sat). A week is final once its last alert has had {ACT_WITHIN_DAYS} days. "
                 f"Target {ACT_TARGET_PCT}%." if k["last_week"] is not None else None)
c[1].metric("Open alerts", k["open"], inr(k["open_value"]) + " at stake", delta_color="off", delta_arrow="off")
c[2].metric("Waiting for first action", k["waiting"],
            f"{k['overdue']} past {ACT_WITHIN_DAYS} days" if k["overdue"] else "none overdue",
            delta_color="inverse" if k["overdue"] else "off", delta_arrow="off")
c[3].metric("Promise / target date reached", k["promise_due"], "follow up" if k["promise_due"] else None,
            delta_color="off", delta_arrow="off")
c[4].metric("New alerts — last 7 days", k["raised_7d"], f"{k['rising']} open alerts rising" if k["rising"] else None,
            delta_color="inverse" if k["rising"] else "off", delta_arrow="off")

tabs = st.tabs(["📈 Weekly action %", "👤 By owner", "🚨 Open alerts", "🗂 All alerts"])

# ---- weekly ---------------------------------------------------------------------------------
with tabs[0]:
    wk = weekly(a, as_of=as_of)
    wt = weekly(a, by_type=True, as_of=as_of)
    fig = go.Figure()
    for i, t in enumerate([t for t in TYPE_ORDER if t in set(wt["type"])]):
        d = wt[wt["type"] == t]
        fig.add_trace(go.Scatter(x=d["week"], y=d["pct_on_time"], name=t, mode="lines+markers",
                                 line=dict(color=SERIES[i + 1], width=2), marker=dict(size=7),
                                 hovertemplate="%{x|%d-%b}: %{y:.0f}%<extra>" + t + "</extra>"))
    fig.add_trace(go.Scatter(x=wk["week"], y=wk["pct_on_time"], name="All alerts", mode="lines+markers",
                             line=dict(color=SERIES[0], width=3), marker=dict(size=9),
                             hovertemplate="%{x|%d-%b}: %{y:.0f}%<extra>All alerts</extra>"))
    fig.add_hline(y=ACT_TARGET_PCT, line_dash="dot", line_color="rgba(128,128,128,.6)",
                  annotation_text=f"Target {ACT_TARGET_PCT}%", annotation_position="top left")
    fig.update_layout(title=f"% of alerts acted on within {ACT_WITHIN_DAYS} days, by week raised (Mon–Sat)")
    fig.update_yaxes(range=[0, 105], ticksuffix="%")
    fig.update_xaxes(tickformat="%d-%b", dtick=7 * 86400000)
    show(fig, 360)

    # outcome mix per week
    mix_colors = {ON_TIME: STATUS["Good"], LATE: STATUS["Medium"], PENDING: "#9a9892", MISSED: STATUS["Critical"], AUTO: "#c9c7c0"}
    fig2 = go.Figure()
    for o in OUTCOMES:
        fig2.add_trace(go.Bar(x=wk["week"], y=wk[o], name=o, marker_color=mix_colors[o],
                              hovertemplate="%{x|%d-%b}: %{y}<extra>" + o + "</extra>"))
    fig2.update_layout(barmode="stack", title="What happened to each week's alerts")
    fig2.update_xaxes(tickformat="%d-%b", dtick=7 * 86400000)
    show(fig2, 320)

    rep = wt.assign(status=np.where(wt["final"], "Final", "In progress"))
    rep = rep[["week", "week_end", "type", "raised", ON_TIME, LATE, MISSED, AUTO, PENDING, "pct_on_time", "status"]]
    st.markdown("##### Weekly action report")
    st.dataframe(rep.sort_values(["week", "type"], ascending=[False, True]), hide_index=True, use_container_width=True,
                 column_config={"week": st.column_config.DateColumn("Week (Mon)", format="DD-MMM-YY"),
                                "week_end": st.column_config.DateColumn("To (Sat)", format="DD-MMM-YY"),
                                "raised": "Raised",
                                "pct_on_time": st.column_config.NumberColumn(f"% ≤ {ACT_WITHIN_DAYS} days", format="%.0f%%")})
    st.caption("Same rules as the tracker's Weekly_Score tab: out-of-scope alerts are excluded; "
               "'In progress' weeks still have alerts inside their 7-day window.")
    download(rep, f"sunlit_weekly_action_report_{as_of:%Y%m%d}")

# ---- by owner -------------------------------------------------------------------------------------
with tabs[1]:
    ov = owner_view(a, 4, as_of)
    l, r = st.columns([3, 2])
    with l:
        d = ov.sort_values("open_alerts")
        fig = go.Figure()
        fig.add_trace(go.Bar(y=d["owner"], x=d["overdue_no_action"], name=f"No action > {ACT_WITHIN_DAYS} days",
                             orientation="h", marker_color=STATUS["Critical"]))
        fig.add_trace(go.Bar(y=d["owner"], x=d["waiting_action"] - d["overdue_no_action"], name="Waiting (within 7 days)",
                             orientation="h", marker_color=STATUS["Medium"]))
        fig.add_trace(go.Bar(y=d["owner"], x=d["open_alerts"] - d["waiting_action"], name="Actioned, still open",
                             orientation="h", marker_color=SERIES[0]))
        fig.update_layout(barmode="stack", title="Open alerts by owner")
        show(fig, max(260, 46 * len(d) + 110))
    with r:
        d = ov.dropna(subset=["pct_on_time"]).sort_values("pct_on_time")
        fig = go.Figure(go.Bar(y=d["owner"], x=d["pct_on_time"], orientation="h",
                               marker_color=[STATUS["Good"] if v >= ACT_TARGET_PCT else STATUS["Critical"] for v in d["pct_on_time"]],
                               text=[f"{v:.0f}%" for v in d["pct_on_time"]], textposition="outside", cliponaxis=False,
                               hovertemplate="%{y}: %{text}<extra></extra>"))
        fig.update_layout(title=f"Acted ≤ {ACT_WITHIN_DAYS} days — last 4 weeks")
        fig.update_xaxes(range=[0, 115], visible=False)
        show(fig, max(260, 46 * len(d) + 80), legend=False)
    st.dataframe(ov[["owner", "alert_types", "open_alerts", "waiting_action", "overdue_no_action", "value_open",
                     "raised_recent", "on_time_recent", "pct_on_time"]],
                 hide_index=True, use_container_width=True,
                 column_config={"owner": "Owner", "alert_types": "Alert types", "open_alerts": "Open",
                                "waiting_action": "Waiting for action",
                                "overdue_no_action": st.column_config.NumberColumn(f"No action > {ACT_WITHIN_DAYS}d"),
                                "value_open": st.column_config.NumberColumn("₹ open", format="%.0f"),
                                "raised_recent": "Raised (4 wks)", "on_time_recent": "On time (4 wks)",
                                "pct_on_time": st.column_config.NumberColumn("% on time", format="%.0f%%")})

# ---- open alerts ----------------------------------------------------------------------------------
def alert_table(df: pd.DataFrame, height: int = 480):
    view = df.assign(state=np.where(df["overdue"], f"🔴 No action > {ACT_WITHIN_DAYS}d",
                                    np.where(df["open_no_action"], "🟡 Waiting", "🔵 Actioned")),
                     # blank instead of "None" when there is no promise / target date
                     promise=df["promise"].dt.strftime("%d-%b").fillna(""))
    st.dataframe(view[["alert_id", "state", "type", "name", "owner", "raised", "age", "amount", "latest", "trend",
                       "action", "promise", "detail"]].sort_values(["state", "age"], ascending=[False, False]),
                 hide_index=True, use_container_width=True, height=height,
                 column_config={"alert_id": "ID", "state": "Status", "type": "Type", "name": st.column_config.TextColumn("Dealer / item", width="medium"),
                                "owner": "Owner", "raised": st.column_config.DateColumn("Raised", format="DD-MMM"),
                                "age": st.column_config.NumberColumn("Days", format="%d"),
                                "amount": st.column_config.NumberColumn("₹ when raised", format="%.0f"),
                                "latest": st.column_config.NumberColumn("₹ now", format="%.0f"),
                                "trend": st.column_config.TextColumn("Trend", width="medium"),
                                "action": "Last action", "promise": "Promise / target",
                                "detail": st.column_config.TextColumn("Detail", width="large")})


with tabs[2]:
    live = a[~a["closed_flag"]]
    f = st.columns(3)
    ty = f[0].multiselect("Type", [t for t in TYPE_ORDER if t in set(live["type"])])
    ow = f[1].multiselect("Owner", sorted(live["owner"].unique()))
    only = f[2].radio("Show", ["All open", "Waiting for action", f"No action > {ACT_WITHIN_DAYS} days"], horizontal=True)
    v = live
    if ty: v = v[v["type"].isin(ty)]
    if ow: v = v[v["owner"].isin(ow)]
    if only == "Waiting for action": v = v[v["open_no_action"]]
    elif only.startswith("No action"): v = v[v["overdue"]]
    st.caption(f"{len(v)} alerts · {inr(v['latest'].sum())} at stake")
    alert_table(v)
    download(v.drop(columns=["closed_flag"]), f"sunlit_open_alerts_{as_of:%Y%m%d}")

with tabs[3]:
    alert_table(a, 560)
    download(a, f"sunlit_alert_log_{as_of:%Y%m%d}")
    st.caption(f"Source: Google Sheet **Sunlit Alert Tracker → {SHEETS['alert_log']['tab']}** "
               "(out-of-scope alerts hidden).")
