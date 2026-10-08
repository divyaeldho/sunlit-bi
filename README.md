# Sunlit AI Business Intelligence & Decision Support System — Phase 1

An AI-powered, centralised BI system for Sunlit Electro Controls. It reads live
operational data from Google Sheets and turns it into KPIs, intelligence modules,
early-warning alerts with owners and actions, and an automated AI management brief.

**Design principle (Module 56, Digital Early-Warning System):**
`Data → Trend → Risk → Alert → Owner → Action`, moving from reporting to predictive visibility.

---

## 1. What's inside

| Component | File | What it does |
|---|---|---|
| Centralised BI data layer | `core/data.py` | Reads 8 live data tabs from 4 Google Sheets, finds header rows, cleans ₹/dates/codes, joins dealer → executive |
| Executive Management Dashboard | `Executive_Dashboard.py` | 8 headline KPIs, monthly sales and margin trend, daily sales with anomaly markers, alert summary, top issues |
| Sales Intelligence | `pages/1_Sales_Intelligence.py` | Filters (period, executive, category, voucher type); category and product trend; top and bottom products and dealers; key-dealer reorder watch; executive vs target; margin/discount exceptions |
| Purchase Intelligence | `pages/2_Purchase_Intelligence.py` | Supplier spend, supplier concentration, same-item price comparison across suppliers, price variation (with Purchase Register); RM purchase action list; product cost-rate drift |
| Inventory Intelligence | `pages/3_Inventory_Intelligence.py` | FG and RM stock value, days-of-cover buckets, consumption, stock-out risk, slow-moving/dead stock, excess and idle RM |
| Receivables Intelligence | `pages/4_Receivables_Intelligence.py` | Outstanding, ageing (≤60 / >60), DSO, collection priority list, collections vs billing trend, by executive |
| AI Decision Support | `core/ai.py`, `pages/5_Alerts_and_AI_Brief.py` | AI brief, "Ask the data" Q&A, category momentum, statistical anomaly detection |
| Automated Alerts | `core/analytics.py` | 9 alert categories, each with severity, ₹ impact, owner and recommended action |
| AI Management Brief | `brief_job.py` + `.github/workflows/` | Daily (Mon–Sat) and weekly brief emailed automatically, with the alert list attached |

## 2. Data sources (all live, actual Sunlit data)

| # | Business area | Google Sheet → Tab |
|---|---|---|
| 1 | Sales (invoice lines incl. cost and margin) | Sunlit_Sales_Intelligence → Dealer_Sales |
| 2 | Dealer master / executives / targets | Sunlit_Sales_Intelligence → SI_Customer_Master, SI_Executive_Performance |
| 3 | Inventory: raw materials and purchase planning | Inventory Purchase Management Ver2.1 → RM_Purch |
| 4 | Inventory: finished goods | FG Inventory Management - Sunlit → Item_Aging_Analysis |
| 5 | Receivables outstanding | Dealer Discounts Management Ver4 → Outstanding@Tally |
| 6 | Collections (bank + cash) | Dealer Discounts Management Ver4 → Combined |
| 7 | Purchases by supplier (optional) | Inventory Purchase Management Ver2.1 → Purchase_Register |

Sheet IDs, tab names, thresholds and alert owners are all in **`core/config.py`**.

## 3. Alert categories

| # | Alert | Rule (default) | Owner |
|---|---|---|---|
| 1 | Stock-out risk (RM) | RM at ORDER NOW and in use; Critical if cover < ½ lead time | Purchase (Aneesh) |
| 2 | Stock-out risk (FG) | Selling item with < 7 days of stock | Production (Jenish) |
| 3 | Sales decline | Category down ≥ 20% (last 30D vs prior 30D); executive projected < 90% of target | Sales (Subhin / executive) |
| 4 | Dealer inactivity | Key dealer (≥ ₹2 L/yr) silent > 1.5× their usual reorder gap | Dealer's executive |
| 5 | Price variation | Purchase rate (or Tally cost rate) moved ≥ 5% vs earlier average | Purchase (Aneesh) |
| 6 | Overdue payment | Dealer > 60-day dues ≥ ₹25,000; Critical ≥ ₹1 L | Finance (Dhaya) + executive |
| 7 | Slow-moving stock | FG with > 180 days of cover and ≥ ₹5,000 value | Sales |
| 8 | Margin / discount exception | Lines with margin < 15% or discount > 10% (last 30D) | Sales |
| 9 | Sales anomaly | Daily sales z-score ≥ 2.5 vs 20-day baseline | Sales / Management |

## 4. Completion-standard checklist

| Standard | Status |
|---|---|
| End-to-end BI system on **actual Sunlit data** | ✅ Reads live Google Sheets (no mock data in production) |
| Minimum **4 business data sources** | ✅ 6 live (Sales, Dealer master, RM inventory, FG inventory, Outstanding, Collections) + optional Purchase Register |
| Minimum **5 intelligence modules** | ✅ Executive, Sales, Purchase, Inventory, Receivables, AI Decision Support |
| Minimum **5 AI alert/insight categories**, tested | ✅ 9 alert categories + AI brief + Q&A |
| Live/refreshable Streamlit dashboard deployed | ⏳ Follow SETUP_GUIDE.md Step 5 |
| Automated management summary from current data | ✅ `brief_job.py` + GitHub Actions schedule |
| Demonstrated to management | ⏳ Demo using the Executive Dashboard → Alert Centre → Generate brief |
| Documentation and handover | ✅ README.md, SETUP_GUIDE.md, USER_GUIDE.md |

## 5. Quick start

```
pip install -r requirements.txt
streamlit run Executive_Dashboard.py
```
Full setup: **SETUP_GUIDE.md**. Daily use: **USER_GUIDE.md**.
