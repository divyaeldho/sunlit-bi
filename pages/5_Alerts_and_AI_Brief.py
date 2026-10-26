import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.ai import ai_status, ask, build_context, management_brief
from core.analytics import alert_summary, category_trend, inr
from core.ui import SERIES, SEV_ICON, STATUS, download, get_data, page_setup, show, sidebar

page_setup("Alerts & AI Brief", "🧠", key="alerts")
b, alerts = get_data()
sidebar(b)
st.title("🧠 Alert Centre & AI Decision Support")

try:
    secrets = st.secrets
except Exception:
    secrets = None
ok, label = ai_status(secrets)
st.caption(f"AI engine: **{label}**")

tab_brief, tab_alerts, tab_ask, tab_trend = st.tabs(["📝 Management brief", "🚨 Alert centre", "💬 Ask the data", "📊 Trend signals"])

with tab_brief:
    c = st.columns([1, 1, 3])
    kind = c[0].radio("Brief type", ["daily", "weekly"], horizontal=True, label_visibility="collapsed")
    if c[1].button("Generate brief", type="primary", use_container_width=True):
        with st.spinner("Analysing current data…"):
            text, src = management_brief(b, alerts, kind, secrets)
        st.session_state["brief"] = (text, src, kind)
    if "brief" in st.session_state:
        text, src, k = st.session_state["brief"]
        with st.container(border=True):
            st.markdown(text)
        st.download_button("⬇️ Download brief (.md)", text.encode("utf-8"),
                           file_name=f"sunlit_{k}_brief_{b.as_of:%Y%m%d}.md")
    else:
        st.info("Click **Generate brief**. The same brief is emailed automatically each morning (see SETUP_GUIDE.md).")
    with st.expander("Fact sheet sent to the AI (audit trail)"):
        st.code(build_context(b, alerts, 1 if kind == "daily" else 7), language="markdown")

with tab_alerts:
    if alerts.empty:
        st.success("No active alerts.")
    else:
        summ = alert_summary(alerts)
        cols = st.columns(len(summ) if len(summ) <= 6 else 6)
        for i, r in enumerate(summ.head(6).itertuples()):
            cols[i].metric(r.category, r.Total, f"{r.Critical} critical" if r.Critical else None, delta_color="inverse")
        f = st.columns(3)
        cats = f[0].multiselect("Category", sorted(alerts["category"].unique()))
        sev = f[1].multiselect("Severity", ["Critical", "High", "Medium"])
        own = f[2].multiselect("Owner / department", sorted(alerts["department"].unique()))
        a = alerts
        if cats: a = a[a["category"].isin(cats)]
        if sev: a = a[a["severity"].isin(sev)]
        if own: a = a[a["department"].isin(own)]
        view = a.assign(severity=a["severity"].map(lambda s: f"{SEV_ICON.get(s, '')} {s}"))
        st.dataframe(view[["severity", "category", "title", "detail", "value", "department", "owner", "action"]],
                     hide_index=True, use_container_width=True, height=520,
                     column_config={"value": st.column_config.NumberColumn("₹ impact", format="%.0f"),
                                    "title": st.column_config.TextColumn("Issue", width="large"),
                                    "action": st.column_config.TextColumn("Recommended action", width="large")})
        download(a, f"sunlit_alerts_{b.as_of:%Y%m%d}")
        st.caption("Flow: **Data → Trend → Risk → Alert → Owner → Action**. Thresholds and owners are set in `core/config.py`.")

with tab_ask:
    if not ok:
        st.warning("Add an AI API key in secrets to enable Q&A (see SETUP_GUIDE.md).")
    examples = ["Which 5 dealers should Subhin call this week and why?",
                "Where is our cash stuck — receivables or inventory?",
                "Which product ranges are growing and which are declining?",
                "What are the three biggest risks for next month's sales?"]
    ex = st.selectbox("Example questions", [""] + examples)
    q = st.text_area("Your question", value=ex, height=80)
    if st.button("Ask", type="primary", disabled=not ok or not q.strip()):
        with st.spinner("Thinking…"):
            try:
                st.markdown(ask(q, b, alerts, secrets))
            except Exception as e:
                st.error(f"AI call failed: {e}")

with tab_trend:
    s = b.get("sales")
    if s.empty:
        st.info("No sales data.")
    else:
        ct = category_trend(s, b.as_of)
        ct = ct[ct["prev30"] >= 20000].dropna(subset=["change_pct"]).sort_values("change_pct")
        fig = go.Figure(go.Bar(
            x=ct["change_pct"], y=ct["category"], orientation="h",
            marker_color=[STATUS["Critical"] if v <= -20 else STATUS["Good"] if v >= 20 else "#9a9892" for v in ct["change_pct"]],
            text=[f"{v:+.0f}%  ({inr(a)})" for v, a in zip(ct["change_pct"], ct["last30"])], textposition="outside", cliponaxis=False,
            hovertemplate="%{y}: %{text}<extra></extra>"))
        fig.update_layout(title="Category momentum — last 30 days vs previous 30 days")
        fig.update_xaxes(ticksuffix="%", zeroline=True, zerolinecolor="rgba(128,128,128,.5)")
        show(fig, max(300, 30 * len(ct) + 80), legend=False)
        st.caption("Red = down ≥ 20% · Green = up ≥ 20% · Grey = stable. Only ranges with ≥ ₹20,000 in the previous 30 days.")
