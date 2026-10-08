import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.analytics import inr
from core.config import THRESHOLDS as T
from core.ui import SERIES, STATUS, download, get_data, hbar, page_setup, show, sidebar

page_setup("Inventory Intelligence", "📦")
b, alerts = get_data()
sidebar(b)
st.title("📦 Inventory Intelligence")

fg, rm = b.get("fg_stock"), b.get("rm_stock")
tab_fg, tab_rm = st.tabs(["Finished goods (FG)", "Raw materials (RM)"])

BUCKETS = [(-1, 0, "Out of stock"), (0, 7, "< 7 days"), (7, 30, "7–30 days"), (30, 90, "30–90 days"),
           (90, 180, "90–180 days"), (180, np.inf, "> 180 days / no sales")]


def bucket(d):
    for lo, hi, name in BUCKETS:
        if lo < d <= hi:
            return name
    return "> 180 days / no sales"


with tab_fg:
    if fg.empty:
        st.error("FG data not available.")
    else:
        f = fg.copy()
        f["cover"] = [("Out of stock" if s <= 0 else bucket(d)) for s, d in zip(f["stock"], f["days_of_stock"])]
        f["consumption_30d_value"] = f["s30"] * f["rate"]
        instock = f[f["stock"] > 0]
        slow = instock[instock["days_of_stock"] > T["fg_slow_days"]]
        risk = f[(f["s30"] > 0) & (f["days_of_stock"] < T["fg_stockout_days"])]
        c = st.columns(4)
        c[0].metric("FG stock value", inr(f["stock_value"].sum()), f"{len(instock)} items in stock", delta_color="off", delta_arrow="off")
        cov_days = f["stock_value"].sum() / max(f["consumption_30d_value"].sum() / 30, 1)
        c[1].metric("Overall stock cover", f"{cov_days:.0f} days", help="FG value ÷ average daily sales at cost")
        c[2].metric("Stock-out risk items", len(risk), f"< {T['fg_stockout_days']} days cover, still selling", delta_color="off", delta_arrow="off")
        c[3].metric("Slow-moving value", inr(slow["stock_value"].sum()), f"{len(slow)} items > {T['fg_slow_days']} days", delta_color="off", delta_arrow="off")

        a, bb = st.columns([3, 2])
        with a:
            order = [n for *_, n in BUCKETS]
            g = f.groupby("cover")["stock_value"].sum().reindex(order).fillna(0).reset_index()
            colors = [STATUS["Critical"], STATUS["High"], SERIES[2], SERIES[0], STATUS["Medium"], STATUS["Critical"]]
            fig = go.Figure(go.Bar(x=g["cover"], y=g["stock_value"], marker_color=colors,
                                   text=[inr(v) for v in g["stock_value"]], textposition="outside", cliponaxis=False,
                                   hovertemplate="%{x}<br>%{text}<extra></extra>"))
            fig.update_layout(title="FG stock value by days of cover")
            fig.update_yaxes(visible=False)
            show(fig, legend=False)
        with bb:
            cv = f.groupby("category")["stock_value"].sum().nlargest(10).reset_index()
            hbar(cv, "stock_value", "category", "FG stock value by range")

        st.markdown(f"##### 🔴 Stock-out risk — selling items with less than {T['fg_stockout_days']} days of stock")
        rv = risk.assign(suggested_qty=(risk["s30"] - risk["stock"]).clip(lower=0)).sort_values("s30", ascending=False)
        st.dataframe(rv[["item_code", "item", "stock", "s14", "s30", "days_of_stock", "suggested_qty", "rate"]],
                     hide_index=True, use_container_width=True,
                     column_config={"s14": "Sold 14D", "s30": "Sold 30D",
                                    "days_of_stock": st.column_config.NumberColumn("Days left", format="%.1f"),
                                    "suggested_qty": st.column_config.NumberColumn("Make/refill qty", format="%.0f")})
        st.markdown(f"##### 🐢 Slow-moving & dead stock — more than {T['fg_slow_days']} days of cover")
        sv = slow.replace({"days_of_stock": {np.inf: np.nan}}).sort_values("stock_value", ascending=False)
        st.dataframe(sv[["item_code", "item", "stock", "rate", "stock_value", "s30", "s90", "s365", "days_of_stock", "status"]],
                     hide_index=True, use_container_width=True,
                     column_config={"stock_value": st.column_config.NumberColumn("Value ₹", format="%.0f"),
                                    "days_of_stock": st.column_config.NumberColumn("Days of stock (blank = no 30D sales)", format="%.0f")})
        download(f.replace({"days_of_stock": {np.inf: np.nan}}), "sunlit_fg_inventory")

with tab_rm:
    if rm.empty:
        st.error("RM data not available.")
    else:
        r = rm.copy()
        on = r[r["status"].str.contains("ORDER NOW")]
        c = st.columns(4)
        c[0].metric("RM stock value", inr(r["stock_value"].sum()), f"{int((r['stock_qty'] > 0).sum())} items", delta_color="off", delta_arrow="off")
        cons = r["consumption_30d_value"].sum()
        c[1].metric("30-day consumption (est.)", inr(cons), help="Daily RM requirement × 30 × rate")
        c[2].metric("Overall RM cover", f"{r['stock_value'].sum() / max(cons / 30, 1):.0f} days")
        c[3].metric("Items at ORDER NOW", len(on), inr(on["shortage_value"].sum()) + " to order", delta_color="off", delta_arrow="off")

        r["cover"] = [("Out of stock" if q <= 0 else bucket(d if pd.notna(d) else np.inf)) for q, d in zip(r["stock_qty"], r["coverage_days"])]
        used = r[r["daily_req"].fillna(0) > 0]
        a, bb = st.columns(2)
        with a:
            order = [n for *_, n in BUCKETS]
            g = used.groupby("cover")["item_code"].count().reindex(order).fillna(0).reset_index()
            colors = [STATUS["Critical"], STATUS["High"], SERIES[2], SERIES[0], STATUS["Medium"], STATUS["Critical"]]
            fig = go.Figure(go.Bar(x=g["cover"], y=g["item_code"], marker_color=colors, text=g["item_code"].astype(int),
                                   textposition="outside", cliponaxis=False, hovertemplate="%{x}: %{y} items<extra></extra>"))
            fig.update_layout(title="RM items in active use — days of cover")
            fig.update_yaxes(visible=False)
            show(fig, legend=False)
        with bb:
            excess = r[(r["excess_shortage"] > 0)].assign(excess_value=lambda d: d["excess_shortage"] * d["rate"])
            hbar(excess.nlargest(10, "excess_value"), "excess_value", "item", "Largest excess RM (above need + lead time)", color=SERIES[3])
        idle = r[(r["daily_req"].fillna(0) == 0) & (r["stock_value"] > 0)]
        st.markdown(f"##### 💤 RM with stock but no current consumption — {inr(idle['stock_value'].sum())} across {len(idle)} items")
        st.dataframe(idle.sort_values("stock_value", ascending=False)[["item_code", "item", "unit", "stock_qty", "rate", "stock_value", "phy_date"]],
                     hide_index=True, use_container_width=True,
                     column_config={"stock_value": st.column_config.NumberColumn("Value ₹", format="%.0f"),
                                    "phy_date": st.column_config.DateColumn("Last physical count", format="DD-MMM-YY")})
        download(r, "sunlit_rm_inventory")
