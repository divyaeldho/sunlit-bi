# Sunlit BI — User Guide (Handover)

## Who uses what

| Person | Start here | Daily routine (5 min) |
|---|---|---|
| **Robin (MD)** | Morning brief email → Executive Dashboard | Read the brief; open the Alert Centre and filter **Critical** |
| **Subhin (Sales)** | Sales Intelligence → Dealers / Executives | Key-dealer reorder watch; filter the Alert Centre by owner **Sales** |
| **Aneesh (Purchase)** | Purchase Intelligence → Reorder plan | Place POs for the top of the action list; check price-variation alerts |
| **Jenish (Production)** | Inventory Intelligence → FG | Plan production for FG stock-out risk items |
| **Dhaya (Finance)** | Finance Dashboard (finance password) | Check funds vs next-7-day payments; work the collection priority list |

## The pages

**Executive Dashboard**: the one-screen view. The top row shows sales, margin and dealers.
The second row shows cash, stock and risk. Below are monthly trends, daily sales
(◆ marks unusual days), the early-warning summary, and the top issue from each alert category.

**Sales Intelligence**: pick a period (MTD, 30D, 90D, FY, 12M) and optionally an executive,
category or voucher type. Every number compares against the previous period of the same length.
* *Trend*: category mix by month and the category scorecard.
* *Products*: top 10, biggest declines, and a full downloadable list.
* *Dealers*: top dealers, dealers who stopped billing, and the **reorder watch**. The
  "× usual gap" column is how many normal reorder cycles have passed since the last order.
  Anything above 1.5 needs a call.
* *Executives*: MTD vs projection vs target.
* *Exceptions*: low-margin and high-discount invoice lines.

**Purchase Intelligence**
* *Supplier spend & prices* needs the `Purchase_Register` tab (SETUP_GUIDE Step 4).
* *Reorder plan (RM)*: every ORDER NOW item with shortage quantity, ₹ value and days late.
* *Product cost-rate changes*: cost movements taken from Tally sales lines.

**Inventory Intelligence**: FG and RM tabs. "Days of cover" = stock ÷ average daily sales
(FG) or daily requirement (RM).

**Finance Dashboard**: the Finance team's one-screen view — available funds, payments due in
7 days, expected collections, the monthly net operating cash flow target, receivables ageing,
collections vs billing, the collection priority list and every Finance alert. Logging in with
the **finance password** shows only this page, the Cash Flow Monitor and Receivables Intelligence.

**Receivables Intelligence**: outstanding, >60-day overdue, DSO, and the collection priority
list. "No payment in 30 days" dealers come first.

**Alerts & AI Brief**
* *Management brief*: generate the daily or weekly brief on demand, or download it.
  The "Fact sheet" box shows exactly what the AI was given (audit trail).
* *Alert centre*: filter by category, severity or owner, then download CSV to share.
* *Ask the data*: plain-English questions. Answers use only current Sunlit data.
* *Trend signals*: category momentum chart.

## Changing things (no programming needed, just edit `core/config.py`)

* **Thresholds**: e.g. change `"overdue_min_value": 25000` to `50000`.
* **Owners**: change names in `OWNERS`.
* **A tab was renamed**: change the `tab` value for that source.

After editing, restart the app (or push to GitHub for the live version).

## Keeping data fresh

The dashboard is only as current as the source sheets. Keep the existing routines going:
Tally sales upload to `Dealer_Sales`, `Outstanding@Tally` and collections updates,
the FG/RM app entries, and a monthly `Purchase_Register` paste.

## Monthly review (15 min)

1. Are alert thresholds producing too many or too few alerts? Adjust `core/config.py`.
2. Did owners act on last month's critical alerts? Compare the alert CSVs.
3. Is there a new data source to add (e.g. job work, production output)? Add a loader in `core/data.py`.
