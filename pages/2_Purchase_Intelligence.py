import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.analytics import cost_rate_changes, inr, pct, purchase_price_changes, window
from core.config import THRESHOLDS as T
from core.ui import SERIES, delta_str, download, get_data, hbar, money_axis, page_setup, show, sidebar

page_setup("Purchase Intelligence", "🛒")
b, alerts = get_data()
sidebar(b)
st.title("🛒 Purchase Intelligence")

pur, rm, sales = b.get("purchases"), b.get("rm_stock"), b.get("sales")
as_of = b.as_of

tabs = st.tabs(["Supplier spend & prices", "Reorder plan (RM)", "Product cost-rate changes"])

# ---- 1. Purchase Register based ----------------------------------------------
with tabs[0]:
    if pur.empty:
        st.warning(
            "**Purchase Register not connected yet.** To switch on supplier-wise spend and price comparison:\n\n"
            "1. In Tally: *Display → Account Books → Purchase Register* → select the period → **Alt+F1 (detailed)** "
            "so item lines show → export to Excel.\n"
            "2. In **Inventory Purchase Management Ver2.1**, create a tab named **`Purchase_Register`** and paste the export "
            "(columns needed: Date, Supplier/Party, Item, Qty, Rate, Amount).\n"
            "3. Press **🔄 Refresh data** in the sidebar.\n\n"
            "Meanwhile the other two tabs work from RM stock data and Tally cost rates.")
    else:
        l90, p90 = window(pur, as_of, 90), window(pur, as_of, 90, 90)
        c = st.columns(4)
        c[0].metric("Purchases — last 90 days", inr(l90["amount"].sum()), delta_str(pct(l90["amount"].sum(), p90["amount"].sum())))
        c[1].metric("Active suppliers", l90["supplier"].nunique())
        c[2].metric("Items bought", l90["item"].nunique())
        top_share = l90.groupby("supplier")["amount"].sum().nlargest(3).sum() / max(l90["amount"].sum(), 1) * 100
        c[3].metric("Top-3 supplier share", f"{top_share:.0f}%", help="Supplier concentration risk")

        m = pur[pur["date"] > as_of - pd.DateOffset(months=13)].groupby("month")["amount"].sum().reset_index()
        fig = go.Figure(go.Bar(x=m["month"], y=m["amount"], marker_color=SERIES[0],
                               hovertemplate="%{x|%b %Y}: ₹%{y:,.0f}<extra></extra>"))
        fig.update_layout(title="Monthly purchases")
        fig.update_xaxes(tickformat="%b %y")
        show(money_axis(fig), legend=False)

        a, bb = st.columns(2)
        with a:
            s = l90.groupby("supplier")["amount"].sum().nlargest(12).reset_index()
            hbar(s, "amount", "supplier", "Top suppliers — last 90 days")
        with bb:
            pc = purchase_price_changes(pur, as_of)
            if not pc.empty:
                up = pc[pc["change_pct"] >= T["price_variation_pct"]].nlargest(12, "change_pct")
                if not up.empty:
                    hbar(up.assign(lbl=up["change_pct"]), "lbl", "item", "Largest price increases (%)", color=SERIES[1], fmt="n")

        st.markdown("##### Price comparison — same item across suppliers (last 12 months)")
        y = pur[pur["date"] > as_of - pd.DateOffset(months=12)]
        cmp_ = y.groupby(["item", "supplier"]).agg(avg_rate=("rate", "mean"), last_rate=("rate", "last"),
                                                  qty=("qty", "sum"), bills=("date", "count")).reset_index()
        multi = cmp_.groupby("item")["supplier"].transform("nunique") > 1
        cmp_ = cmp_[multi]
        if cmp_.empty:
            st.info("No item was bought from more than one supplier in the last 12 months.")
        else:
            best = cmp_.groupby("item")["avg_rate"].transform("min")
            cmp_["vs best %"] = (cmp_["avg_rate"] - best) / best * 100
            cmp_["extra paid ₹"] = (cmp_["avg_rate"] - best) * cmp_["qty"]
            st.dataframe(cmp_.sort_values(["extra paid ₹"], ascending=False), hide_index=True, use_container_width=True,
                         column_config={"avg_rate": st.column_config.NumberColumn("Avg rate", format="₹%.2f"),
                                        "last_rate": st.column_config.NumberColumn("Last rate", format="₹%.2f"),
                                        "vs best %": st.column_config.NumberColumn(format="%.1f%%"),
                                        "extra paid ₹": st.column_config.NumberColumn(format="%.0f")})
            download(cmp_, "sunlit_supplier_price_comparison")
        if not pc.empty:
            st.markdown(f"##### Price variation ≥ {T['price_variation_pct']}% (latest bill vs earlier average)")
            st.dataframe(pc[pc["change_pct"].abs() >= T["price_variation_pct"]].sort_values("change_pct", ascending=False),
                         hide_index=True, use_container_width=True,
                         column_config={"last_date": st.column_config.DateColumn(format="DD-MMM-YY"),
                                        "change_pct": st.column_config.NumberColumn("Change %", format="%.1f%%")})

# ---- 2. RM reorder plan ----------------------------------------------------------
with tabs[1]:
    if rm.empty:
        st.error("RM stock data not available.")
    else:
        on = rm[rm["status"].str.contains("ORDER NOW")]
        c = st.columns(4)
        c[0].metric("Items at ORDER NOW", len(on))
        c[1].metric("Value to order", inr(on["shortage_value"].sum()))
        c[2].metric("Overdue orders", int((on["delay_days"] > 0).sum()), help="Order due date already passed")
        c[3].metric("Avg delay (overdue)", f"{on.loc[on['delay_days'] > 0, 'delay_days'].mean():.0f} days" if (on["delay_days"] > 0).any() else "–")
        st.markdown("##### Purchase action list — sorted by urgency")
        view = on.sort_values(["priority", "coverage_days", "shortage_value"], ascending=[True, True, False])
        st.dataframe(view[["item_code", "item", "unit", "stock_qty", "daily_req", "coverage_days", "lead_time",
                           "excess_shortage", "shortage_value", "order_due", "delay_days"]],
                     hide_index=True, use_container_width=True,
                     column_config={"stock_qty": "Stock", "daily_req": st.column_config.NumberColumn("Daily need", format="%.1f"),
                                    "coverage_days": st.column_config.NumberColumn("Cover (days)", format="%.0f"),
                                    "lead_time": st.column_config.NumberColumn("Lead time", format="%.0f"),
                                    "excess_shortage": st.column_config.NumberColumn("Shortage qty", format="%.0f"),
                                    "shortage_value": st.column_config.NumberColumn("Order value ₹", format="%.0f"),
                                    "order_due": st.column_config.DateColumn("Order due", format="DD-MMM-YY"),
                                    "delay_days": st.column_config.NumberColumn("Days late", format="%.0f")})
        download(view, "sunlit_rm_purchase_action_list")

# ---- 3. Cost-rate drift from Tally -------------------------------------------------
with tabs[2]:
    st.caption("Tally 'Purchase Rate' (cost) on each sale line — latest in the last 30 days vs the median of the 90 days before. "
               "Shows cost changes flowing into margins even without a Purchase Register.")
    cr = cost_rate_changes(sales, as_of) if not sales.empty else pd.DataFrame()
    if cr.empty:
        st.info("Not enough cost-rate history.")
    else:
        big = cr[cr["change_pct"].abs() >= T["price_variation_pct"]].sort_values("change_pct", ascending=False)
        c = st.columns(3)
        c[0].metric("Products with cost change ≥ " + f"{T['price_variation_pct']}%", len(big))
        c[1].metric("Cost increases", int((big["change_pct"] > 0).sum()))
        c[2].metric("30-day margin impact", inr(-big["impact_30d"].sum()), help="Negative = margin lost to higher cost")
        st.dataframe(big, hide_index=True, use_container_width=True,
                     column_config={"latest_rate": st.column_config.NumberColumn("Latest cost", format="₹%.2f"),
                                    "prev_rate": st.column_config.NumberColumn("Earlier cost", format="₹%.2f"),
                                    "qty_30d": st.column_config.NumberColumn("Qty sold 30D", format="%.0f"),
                                    "change_pct": st.column_config.NumberColumn("Change %", format="%.1f%%"),
                                    "impact_30d": st.column_config.NumberColumn("₹ impact 30D", format="%.0f")})
