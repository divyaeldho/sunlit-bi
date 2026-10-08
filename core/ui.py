"""Shared Streamlit helpers: auth gate, cached data, sidebar, chart styling."""
from __future__ import annotations

import hmac

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from core.analytics import build_alerts, inr
from core.config import CACHE_MINUTES
from core.data import load_all

# Validated categorical order (dataviz reference palette) — fixed, never cycled
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
STATUS = {"Critical": "#d03b3b", "High": "#ec835a", "Medium": "#fab219", "Good": "#0ca30c"}
SEV_ICON = {"Critical": "🔴", "High": "🟠", "Medium": "🟡"}
MUTED = "#898781"


def page_setup(title: str, icon: str = "💡"):
    st.set_page_config(page_title=f"{title} · Sunlit BI", page_icon=icon, layout="wide")
    st.markdown("""<style>
      [data-testid="stMetricValue"]{font-size:1.55rem}
      .block-container{padding-top:1.6rem}
      div[data-testid="stMetric"]{border:1px solid rgba(128,128,128,.18);border-radius:10px;padding:10px 14px}
    </style>""", unsafe_allow_html=True)
    _gate()


def _gate():
    """Simple shared-password gate (APP_PASSWORD in secrets). Skipped if not set."""
    try:
        pw = st.secrets.get("APP_PASSWORD")
    except Exception:
        pw = None
    if not pw or st.session_state.get("auth_ok"):
        return
    st.title("Sunlit Business Intelligence")
    entered = st.text_input("Password", type="password")
    if entered:
        if hmac.compare_digest(entered, str(pw)):
            st.session_state["auth_ok"] = True
            st.rerun()
        else:
            st.error("Incorrect password")
    st.stop()


def _secrets():
    try:
        return st.secrets
    except Exception:
        return None


@st.cache_data(ttl=CACHE_MINUTES * 60, show_spinner="Reading Sunlit data from Google Sheets…")
def _cached_bundle():
    return load_all(_secrets())


def get_data():
    b = _cached_bundle()
    alerts = _cached_alerts(b.loaded_at)
    return b, alerts


@st.cache_data(ttl=CACHE_MINUTES * 60, show_spinner=False)
def _cached_alerts(stamp):
    return build_alerts(_cached_bundle())


def sidebar(b):
    with st.sidebar:
        st.markdown("### ☀️ Sunlit BI")
        if getattr(b, "test_mode", False):
            st.warning("**TEST DATA** — not real Sunlit figures. Connect Google Sheets (SETUP_GUIDE Step 2–3) to see live data.")
        st.caption(f"Business date: **{b.as_of:%d %b %Y}**  \nLoaded: {b.loaded_at:%d %b, %H:%M}")
        if st.button("🔄 Refresh data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
        with st.expander("Data sources", expanded=False):
            for h in b.health:
                icon = "✅" if h["status"] == "OK" else ("⚪" if "optional" in h["status"] else "❌")
                st.markdown(f"{icon} **{h['source']}** · `{h['sheet_tab']}` · {h['rows']:,} rows")
                if h["status"] != "OK":
                    st.caption(h["detail"])


def style(fig: go.Figure, height: int = 340, legend: bool = True) -> go.Figure:
    many = legend and len(fig.data) > 1
    fig.update_layout(
        height=height, margin=dict(l=8, r=8, t=78 if many else 40, b=8),
        title=dict(x=0, xanchor="left", y=1, yref="container", yanchor="top", pad=dict(t=10, l=4)),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family='system-ui,-apple-system,"Segoe UI",sans-serif', size=13),
        hovermode="x unified" if fig.data and fig.data[0].type == "scatter" else "closest",
        showlegend=many, legend=dict(orientation="h", y=1.01, yanchor="bottom", x=0, title=None, traceorder="normal"),
        colorway=SERIES, bargap=0.25,
    )
    fig.update_xaxes(showgrid=False, linecolor="rgba(128,128,128,.35)", title=None)
    fig.update_yaxes(gridcolor="rgba(128,128,128,.15)", zeroline=False, title=None)
    fig.update_traces(selector=dict(type="bar"), marker_cornerradius=4)
    fig.update_traces(selector=dict(type="scatter"), line_width=2)
    return fig


def show(fig, height=340, legend=True):
    st.plotly_chart(style(fig, height, legend), use_container_width=True, theme="streamlit")


def money_axis(fig):
    """Y-axis ticks in Indian units (₹ 5 L, ₹ 1.2 Cr) instead of 5M."""
    import numpy as np
    ys = [np.asarray(t.y, dtype=float) for t in fig.data if t.y is not None and len(t.y)]
    if not ys:
        return fig
    if fig.layout.barmode == "stack":
        top = max(np.nansum([y for y in ys if len(y) == len(ys[0])], axis=0).max(), 0)
    else:
        top = max(np.nanmax(y) for y in ys)
    if not top or np.isnan(top):
        return fig
    raw = top / 5
    mag = 10 ** np.floor(np.log10(raw))
    step = min((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw), default=raw)
    vals = np.arange(0, top + step, step)
    fig.update_yaxes(tickmode="array", tickvals=vals, ticktext=[inr(v).replace("₹", "₹ ") for v in vals])
    return fig


def hbar(df, x, y, title, color=SERIES[0], height=None, fmt="₹"):
    d = df.sort_values(x)
    fig = go.Figure(go.Bar(x=d[x], y=d[y], orientation="h", marker_color=color,
                           text=[inr(v) if fmt == "₹" else f"{v:,.0f}" for v in d[x]],
                           textposition="outside", cliponaxis=False,
                           hovertemplate="%{y}<br>%{text}<extra></extra>"))
    fig.update_layout(title=title)
    fig.update_xaxes(visible=False, range=[0, d[x].max() * 1.28 if len(d) and d[x].max() > 0 else 1])
    fig = style(fig, height or max(260, 28 * len(d) + 60), legend=False)
    st.plotly_chart(fig, use_container_width=True, theme="streamlit")


def alert_cards(alerts: pd.DataFrame, n: int = 6):
    for r in alerts.head(n).itertuples():
        st.markdown(
            f"{SEV_ICON.get(r.severity, '')} **{r.severity}** · {r.category}  \n"
            f"**{r.title}** — {inr(r.value)}  \n"
            f"<span style='opacity:.75'>{r.detail}</span>  \n"
            f"👤 **{r.owner}** → {r.action}", unsafe_allow_html=True)
        st.divider()


def download(df: pd.DataFrame, name: str, label="⬇️ Download CSV"):
    st.download_button(label, df.to_csv(index=False).encode("utf-8"), file_name=f"{name}.csv", mime="text/csv")


def delta_str(v, suffix="%"):
    if v is None or pd.isna(v):
        return None
    return f"{v:+.1f}{suffix}"
