# Sunlit BI — Setup Guide

Time needed: about 45 minutes, done once. Everything can be done from home.

---

## Step 1 — Install and run locally (VS Code)

1. Open this folder in VS Code (**File → Open Folder**).
2. Open a terminal (**Terminal → New Terminal**) and run:
   ```
   python --version            # must be 3.11 or newer
   pip install -r requirements.txt
   ```
3. **Test with sample data first** (no Google access needed):
   ```
   python tools/make_test_data.py
   $env:SUNLIT_BI_LOCAL_DIR="test_data"     # PowerShell
   streamlit run Executive_Dashboard.py
   ```
   The browser opens at http://localhost:8501. Close it with **Ctrl+C**, then
   `Remove-Item Env:SUNLIT_BI_LOCAL_DIR` before connecting real data.

---

## Step 2 — Give the app read access to Google Sheets (service account)

A *service account* is a robot Google user that the app logs in as.

1. Go to https://console.cloud.google.com → create a project named **sunlit-bi**.
2. **APIs & Services → Library** → enable **Google Sheets API** and **Google Drive API**.
3. **APIs & Services → Credentials → Create credentials → Service account**
   → name it `sunlit-bi` → Done.
4. Open the service account → **Keys → Add key → JSON**. A `.json` file downloads.
   **Keep it private.**
5. Copy the service-account email (like `sunlit-bi@sunlit-bi.iam.gserviceaccount.com`).
6. **Share these 4 Google Sheets with that email as *Viewer*** (Share button, same as sharing with a person):
   | Sheet | Tabs used |
   |---|---|
   | Sunlit_Sales_Intelligence | Dealer_Sales, SI_Customer_Master, SI_Executive_Performance |
   | Inventory Purchase Management Ver2.1 | RM_Purch, *Purchase_Register (optional)* |
   | FG Inventory Management - Sunlit | Item_Aging_Analysis |
   | Dealer Discounts Management Ver4 | Outstanding@Tally, Combined |

---

## Step 3 — Secrets file

1. Copy `.streamlit/secrets.toml.example` → `.streamlit/secrets.toml`.
2. Open the downloaded JSON key and copy each field into the `[gcp_service_account]` section.
   For `private_key`, keep the `\n` characters exactly as they are in the JSON.
3. Set `APP_PASSWORD` (the dashboard asks for it — opens every page). Optionally add `[ROLE_PASSWORDS]` → `finance = "..."`; that password opens only the Finance pages (edit `ROLES` in `core/config.py` to change which).
4. **AI key** (pick one):
   * **Gemini** (free tier): https://aistudio.google.com/apikey → `AI_PROVIDER="gemini"`, paste into `GEMINI_API_KEY`.
   * **Anthropic Claude**: https://console.anthropic.com → `AI_PROVIDER="anthropic"`, paste into `ANTHROPIC_API_KEY`.
   Without a key, everything still works and the brief is rule-based.
5. Run `streamlit run Executive_Dashboard.py`. Open **Data sources** in the sidebar;
   every source should show ✅.

---

## Step 4 — (Optional) Purchase Register for supplier intelligence

1. Tally → **Display → Account Books → Purchase Register** → select the period (e.g. 1-Apr-2025 to today).
2. Press **Alt+F1** (detailed) so item lines show → **Export → Excel**.
3. In **Inventory Purchase Management Ver2.1**, add a tab named exactly **`Purchase_Register`**
   and paste. The columns needed are Date, Supplier (or Party / Particulars), Item, Qty, Rate, Amount.
   The app matches common Tally column names automatically.
4. Refresh the dashboard. The **Purchase Intelligence → Supplier spend & prices** tab switches on.
   Update the tab monthly, or whenever you want fresh price comparison.

---

## Step 5 — Deploy the live dashboard (Streamlit Community Cloud, free)

1. Create a **private** GitHub repository and upload this folder.
   `secrets.toml` is excluded by `.gitignore`, so never upload it.
2. Go to https://share.streamlit.io → **Create app** → pick the repo →
   Main file: `Executive_Dashboard.py` → App URL e.g. `sunlit-bi`.
3. **Advanced settings → Secrets**: paste the full contents of your local `secrets.toml`.
4. Deploy. Under **Settings → Sharing**, restrict viewers to invited emails (Robin, department heads).
   The APP_PASSWORD adds a second lock.

Data refreshes every 30 minutes, or immediately with **🔄 Refresh data**.

---

## Step 6 — Automated AI Management Brief by email

**Option A: GitHub Actions (recommended; runs even when your PC is off)**

1. Gmail: turn on 2-Step Verification → https://myaccount.google.com/apppasswords → create
   an app password named "Sunlit BI" and copy the 16 characters.
2. GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**. Add:
   | Secret | Value |
   |---|---|
   | GOOGLE_SERVICE_ACCOUNT_JSON | whole JSON key file content |
   | AI_PROVIDER | `gemini` or `anthropic` |
   | GEMINI_API_KEY or ANTHROPIC_API_KEY | your key |
   | SMTP_USER | the Gmail address |
   | SMTP_APP_PASSWORD | 16-char app password |
   | BRIEF_TO | `robin@...,divya@...` |
   | DASHBOARD_URL | your streamlit.app link |
3. **Actions** tab → *Sunlit management brief* → **Run workflow** to test.
   After that it runs **Mon–Sat 8:15 AM (daily)** and **Monday 8:30 AM (weekly)**.

**Option B: Windows Task Scheduler (PC must be on)**
Create a task that runs daily at 8:15 AM:
`python C:\path\to\sunlit_bi\brief_job.py --kind daily` (Start in: the sunlit_bi folder).
It reads SMTP and AI settings from `.streamlit/secrets.toml`.

Test without sending: `python brief_job.py --kind daily --dry-run`

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| ❌ source with "SpreadsheetNotFound" / 403 | The sheet is not shared with the service-account email |
| ❌ "WorksheetNotFound" | Tab was renamed. Update `tab` in `core/config.py` |
| ❌ "Header row with … not found" | A column heading changed. Update `header_hint` or the column names in `core/data.py` |
| Brief says "AI call failed" | Check the API key or model name (`AI_MODEL`); the rule-based brief is sent instead |
| Numbers look old | Press 🔄 Refresh data; check that the source sheet itself is updated from Tally |
