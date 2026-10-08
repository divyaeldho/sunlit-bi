"""
Sunlit BI — central configuration.

Everything a non-programmer may need to change lives here:
  * which Google Sheet / tab feeds each module
  * alert thresholds
  * who owns each alert (Data -> Risk -> Alert -> OWNER -> Action)
"""

# ---------------------------------------------------------------------------
# 1. DATA SOURCES  (Google Sheet ID = the long code in the sheet's URL)
# ---------------------------------------------------------------------------
SHEETS = {
    # Sales invoice lines (Tally sales register, item-wise, with Purchase Rate & Margin)
    "sales": {
        "sheet_id": "1NsMIx-aL_eD6di06Q_0eM5lRRnLhoaiXzjzDwf1RfPM",   # Sunlit_Sales_Intelligence
        "tab": "Dealer_Sales",
        "header_hint": "Voucher Number",
    },
    # Dealer master -> executive mapping
    "customers": {
        "sheet_id": "1NsMIx-aL_eD6di06Q_0eM5lRRnLhoaiXzjzDwf1RfPM",
        "tab": "SI_Customer_Master",
        "header_hint": "Dealer Code",
    },
    # Monthly executive targets
    "exec_targets": {
        "sheet_id": "1NsMIx-aL_eD6di06Q_0eM5lRRnLhoaiXzjzDwf1RfPM",
        "tab": "SI_Executive_Performance",
        "header_hint": "Executive",
    },
    # Raw-material stock position, coverage, reorder status
    "rm_stock": {
        "sheet_id": "1jZ1julwHS8jbt8CQAALabhmWusQLLhD0H-Nx3mSCFnQ",   # Inventory Purchase Management Ver2.1
        "tab": "RM_Purch",
        "header_hint": "Item Code",
    },
    # OPTIONAL — Tally Purchase Register (item-wise). Paste the export into this tab.
    "purchases": {
        "sheet_id": "1jZ1julwHS8jbt8CQAALabhmWusQLLhD0H-Nx3mSCFnQ",
        "tab": "Purchase_Register",
        "header_hint": "Date",
        "optional": True,
    },
    # Finished-goods PHYSICAL stock + rate (live FG app stock)
    "fg_stock": {
        "sheet_id": "1E_hFuqEpWCIUZhSiLwJNaY7IOZQ5MV1ex_6F6Szns98",   # FG Inventory Management - Sunlit
        "tab": "FG_Stock",
        "header_hint": "Item Code",
    },
    # Finished-goods SALES history from Tally (14D / 30D / 60D / 90D / 180D / 365D)
    "fg_sales": {
        "sheet_id": "1E_hFuqEpWCIUZhSiLwJNaY7IOZQ5MV1ex_6F6Szns98",   # FG Inventory Management - Sunlit
        "tab": "Sale_in-Days",
        "header_hint": "Code",
    },
    # Dealer outstanding (Tally) with 0-60 / >60 day split
    "outstanding": {
        "sheet_id": "1xNglpPFKWeClLISdnQ_fQcL5QoYt_xksZAfrcPvbFso",   # Dealer Discounts Management Ver4
        "tab": "Outstanding@Tally",
        "header_hint": "Dealer Code",
    },
    # Collections received (bank + cash, combined)
    "collections": {
        "sheet_id": "1xNglpPFKWeClLISdnQ_fQcL5QoYt_xksZAfrcPvbFso",
        "tab": "Combined",
        "header_hint": "Dealer Code",
    },
}

# Finance "Daily report on cash flow" — ONE TAB PER DAY (03.10, 01.10 ...), read by core/cashflow.py
CASHFLOW = {
    "sheet_id": "1MrTfl5knMNEZq6CE6zXhacJ4dWuopnh0womyH6Gf6RA",   # Daily report on cash flow
    "max_tabs": 200,          # read only the latest N daily tabs (all in one API call)
}

# Company monthly target — Net Operating Cash Flow (cash in − cash out, excluding approved non-operating items)
#   Change "month" each month (and "target" if management revises it).
CASH_TARGET = {
    "month": "2026-10",
    "target": 500000,
}

# Minutes to cache sheet data before re-reading Google Sheets
CACHE_MINUTES = 30

# ---------------------------------------------------------------------------
# 2. ALERT THRESHOLDS
# ---------------------------------------------------------------------------
THRESHOLDS = {
    # Sales
    "sales_decline_pct": 20,          # category/executive last-30D vs prior-30D drop (%)
    "sales_decline_min_value": 50000, # ignore categories smaller than this in prior 30D (₹)
    "dealer_silent_gap_mult": 1.5,    # key dealer silent > 1.5 x their normal reorder gap
    "dealer_key_min_12m": 200000,     # "key dealer" = last-12M billing above this (₹)
    "low_margin_pct": 15,             # invoice line margin below this % of amount
    "high_discount_pct": 10,          # line discount above this %
    "anomaly_z": 2.5,                 # daily-sales anomaly z-score
    # Inventory
    "fg_stockout_days": 7,            # FG with < N days of stock while still selling
    "fg_slow_days": 180,              # FG with > N days of stock = slow-moving
    "rm_min_value_alert": 0,          # only alert RM shortages above this ₹ (0 = all)
    # Purchase
    "price_variation_pct": 5,         # latest purchase rate vs previous average (%)
    # Receivables
    "overdue_min_value": 25000,       # dealer >60-day dues above this (₹)
    "overdue_critical_value": 100000, # dealer >60-day dues above this = critical
    # Cash flow (Finance KPIs: net cash flow positive every week, operating cash flow >= ₹5 L / week)
    "weekly_net_target": 500000,      # ₹ net cash flow target per week
    "cash_cover_min": 1.5,            # closing funds should be >= 1.5 x next-7-day obligations
    "cash_drop_pct": 25,              # closing funds down more than this % vs ~30 days ago
    "recon_gap_min": 10000,           # opening + in - out vs closing mismatch worth flagging (₹)
    "unplanned_payment_pct": 50,      # actual payments above plan by more than this % (last 30 days)
    "cash_report_stale_days": 2,      # report older than this many days (vs latest sales date)
}

# ---------------------------------------------------------------------------
# 3. ALERT OWNERS  (edit names/emails freely)
# ---------------------------------------------------------------------------
OWNERS = {
    "Purchase":   {"name": "Aneesh", "email": ""},
    "Production": {"name": "Jenish", "email": ""},
    "Sales":      {"name": "Subhin", "email": ""},
    "Finance":    {"name": "Dhaya",  "email": ""},
    "Management": {"name": "Robin",  "email": ""},
}

COMPANY = "Sunlit Electro Controls Pvt. Ltd."
