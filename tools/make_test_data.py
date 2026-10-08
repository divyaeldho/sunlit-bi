"""
Generates OFFLINE TEST data that mimics the exact layout of each Sunlit sheet
(blank leading rows, ₹/comma formatting, emoji status, mixed date formats).
Used only to test the code without Google access:

    python tools/make_test_data.py
    set SUNLIT_BI_LOCAL_DIR=test_data   (Windows)   /  export SUNLIT_BI_LOCAL_DIR=test_data
    streamlit run app.py

The live system never uses this — it reads the real Google Sheets.
"""
import csv
import os
import random
from datetime import date, timedelta

random.seed(7)
OUT = os.path.join(os.path.dirname(__file__), "..", "test_data")
os.makedirs(OUT, exist_ok=True)
TODAY = date(2026, 9, 24)

CATS = {"Vega": 85, "Vega+": 150, "Lyra": 420, "Capella": 110, "Solaris": 330, "Lucent": 70,
        "Cygnus": 130, "Polaris": 210, "Nova": 95, "Aquilla": 45, "Spica": 30, "Rigel": 95}
ITEMS = []
code = 80001
for cat, cost in CATS.items():
    for w in (10, 20, 36):
        ITEMS.append((str(code), cat, f"{cat} LED Light-{w:02d}W-6000K", round(cost * (0.6 + w / 30), 2)))
        code += 1
DEALERS = [(str(410001 + i), f"TEST DEALER {i+1:03d}", random.choice(["Syju", "Xavier", "Subhin"]))
           for i in range(120)]


def w(name, rows):
    with open(os.path.join(OUT, f"{name}.csv"), "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)


def inr(x):
    return f"₹{x:,.0f}"


# ---- sales (Dealer_Sales) ------------------------------------------------------
rows = [["Voucher Number", "Sale Date", "Voucher Type", "Cust Code", "Party Name", "Item Code", "Item Cat", "Item Name",
         "Godown", "Item Batch", "Billed Quantity", "Rate", "Purchase Rate", "Unit", "Discount", "Discount Amount", "Margin", "Amount"]]
vno = 1
d = date(2025, 4, 1)
weights = [random.random() ** 2 for _ in DEALERS]
while d <= TODAY:
    if d.weekday() != 6:
        n = random.randint(6, 14)
        if d > TODAY - timedelta(days=40):     # recent weakness in Cygnus for alerts
            pass
        for _ in range(n):
            dl = random.choices(DEALERS, weights)[0]
            if dl[0] in ("410003", "410007") and d > TODAY - timedelta(days=60):
                continue                          # two dealers go silent
            for it in random.sample(ITEMS, random.randint(1, 4)):
                if it[1] == "Cygnus" and d > TODAY - timedelta(days=30) and random.random() < .8:
                    continue
                qty = random.choice([5, 10, 10, 20, 25, 50])
                cost = it[3] * (1.12 if (it[1] == "Solaris" and d > TODAY - timedelta(days=25)) else 1)
                rate = round(it[3] * random.uniform(1.45, 1.9), 2)
                disc = random.choice([0, 0, 0, 5, 8, 12])
                amt = round(qty * rate * (1 - disc / 100), 2)
                rows.append([f"D-2526{vno:04d}", d.strftime("%-d-%b-%y"), "Sales GST Traders", dl[0], f"{dl[1]} |{dl[0]}",
                             it[0], it[1], f"{it[2]}//{it[0]}", "Main Location 1", "Primary Batch", qty, rate, round(cost, 2),
                             "Nos", disc, round(qty * rate * disc / 100, 2) if disc else "", round(amt - qty * cost, 2), amt])
            vno += 1
    d += timedelta(days=1)
# one abnormal day
for it in ITEMS[:6]:
    rows.append([f"D-2526{vno:04d}", (TODAY - timedelta(days=3)).strftime("%-d-%b-%y"), "Sales GST Project", "410050",
                 "TEST DEALER 050 |410050", it[0], it[1], it[2], "Main Location 1", "Primary Batch", 400, it[3] * 1.5, it[3],
                 "Nos", 0, "", 400 * it[3] * .5, 400 * it[3] * 1.5])
w("sales", rows)

# ---- customers (SI_Customer_Master) -------------------------------------------------
w("customers", [["Dealer Code", "Dealer Name", "Executive", "Avg Gap (days)", "Last 12M Billing", "Status"]] +
  [[c, n, e, 10, inr(100000), "ACTIVE"] for c, n, e in DEALERS])

# ---- exec targets ---------------------------------------------------------------
w("exec_targets", [["Executive", "Apr-26", "Current Month Target"], ["Syju", "", "₹750,000"], ["Xavier", "", "₹600,000"],
                   ["Subhin", "", "₹450,000"], ["Unassigned", "", "₹0"]])

# ---- RM_Purch (header on row 2, emoji status) ----------------------------------------
rm = [[""] * 22, ["Srl No", "Item Code", "Item Name", "Unit", "Tally Stock Qty", "Rate", "Physical Stock Qty", "Phy.St.Date",
                  "Gross RM Need (30D)", "RM Covered by FG/SFG Stock", "Net RM Requirement (30D)", "Daily RM Requirement",
                  "Stock Coverage (Days)", "Lead Time (Days)", "LT Requirement", "Total RM Requirement", "Excess / Shortage",
                  "Status", "Priority", "Order Due Date", "Delay Days", "Next Order Date"]]
for i in range(150):
    rate = round(random.choice([0.1, 0.4, 2, 8, 35, 120]), 2)
    daily = random.choice([0, 0, 1.5, 6, 20, 45])
    stock = random.choice([0, 20, 150, 800, 5000])
    lt = random.choice([10, 12, 18, 20])
    cov = stock / daily if daily else 999
    need = daily * 30
    tot = need + daily * lt
    ex = stock - tot
    status = "🔴 ORDER NOW" if ex < 0 else "🟢 Stock Ok"
    due = (TODAY - timedelta(days=random.randint(1, 40))).strftime("%d/%m/%Y") if ex < 0 else ""
    rm.append([i + 1, 10000 + i, f"RM-TEST-PART-{i:03d}", "Nos", stock, rate, f"{stock:,.2f}", "23/09/2026",
               f"{need:,.2f}", "0", f"{need:,.2f}", f"{daily:.2f}", f"{min(cov, 999):.2f}", f"{lt:.2f}", "", f"{tot:,.2f}",
               f"{ex:,.2f}", status, 1 if ex < 0 else 3, due, (TODAY - timedelta(days=1)).day if ex < 0 else "", ""])
w("rm_stock", rm)

# ---- FG Item_Aging_Analysis -------------------------------------------------------------
fg = [["Item Code", "Item Name", "Physical Stock", "Rate", "Months in Stock", "14D", "30D", "60D", "90D", "180D", "365D",
       "Days of Stock", "Status"]]
for c, cat, name, cost in ITEMS:
    s30 = random.choice([0, 5, 20, 60, 200])
    stock = random.choice([0, 3, 40, 150, 600]) if s30 else random.choice([0, 30, 120])
    fg.append([c, name, stock, cost, "", s30 // 2, s30, s30 * 2, s30 * 3, s30 * 6, s30 * 12, "", "GOOD"])
w("fg_stock", fg)

# ---- Outstanding@Tally (header row 2) ------------------------------------------------------
os_ = [[""] * 7, ["SRL", "Dealer Code", "Party Name", "Amount", "Upto 60 days", "Above 60 days", "Remarks"]]
for i, (c, n, e) in enumerate(DEALERS[:90]):
    u, a = random.choice([0, 12000, 45000]), random.choice([0, 0, 8000, 30000, 140000])
    os_.append([i + 1, c, f"{n} |{c}", f"{u + a:,.2f}", f"{u:,.2f}" if u else "", f"{a:,.2f}" if a else "", ""])
w("outstanding", os_)

# ---- Combined collections (header row 3) ----------------------------------------------------
cl = [["Collection From Dealers"] + [""] * 9, [""] * 10,
      ["Date", "Dealer Code", "Dealer Name", "Vch Type", "Inst No", "Inst Date", "Bank", "Deposit", "Withdrawal", "Source"]]
d = date(2026, 1, 1)
while d <= TODAY:
    for _ in range(random.randint(2, 6)):
        c, n, e = random.choice(DEALERS)
        cl.append([d.strftime("%d/%m/%Y"), c, f"{n} |{c}", "Receipt Sales", "", d.strftime("%d-%b-%y"), "",
                   f"{random.choice([5000, 12000, 25000, 60000]):,.2f}", "0.00", random.choice(["SBI", "FED", "CASH"])])
    d += timedelta(days=1)
w("collections", cl)

# ---- Purchase_Register (optional) -----------------------------------------------------------
pr = [["Date", "Supplier", "Item Name", "Qty", "Rate", "Amount"]]
sups = ["ALPHA COMPONENTS", "BETA ELECTRONICS", "GAMMA METALS", "DELTA PACK"]
d = date(2025, 10, 1)
while d <= TODAY:
    if d.weekday() < 5 and random.random() < .5:
        i = random.randint(0, 20)
        s = random.choice(sups)
        base = 5 + i
        rate = base * (1.1 if s == "BETA ELECTRONICS" else 1) * (1.09 if d > TODAY - timedelta(days=20) else 1)
        q = random.choice([100, 500, 1000])
        pr.append([d.strftime("%d-%b-%Y"), s, f"RM-TEST-PART-{i:03d}", q, round(rate, 2), round(q * rate, 2)])
    d += timedelta(days=1)
w("purchases", pr)
print("Test data written to", os.path.abspath(OUT))
