"""
AI Decision Support.

* build_context()   -> a compact, numbers-only fact sheet from current data
* lookup_context()  -> exact item / dealer figures for a specific question
* management_brief() -> AI-written daily/weekly brief (falls back to a
                         rule-based brief if no API key / API error)
* ask()             -> free-form management Q&A grounded on the fact sheet

Providers (set in secrets or environment):
    AI_PROVIDER = "anthropic" | "gemini"
    ANTHROPIC_API_KEY / GEMINI_API_KEY
    AI_MODEL    (optional override)
"""
from __future__ import annotations

import os
import re

import numpy as np
import pandas as pd
import requests

from core.analytics import (alert_summary, category_trend, dealer_activity, diverse_top, inr,
                            sales_kpis, window)
from core.config import COMPANY

DEFAULT_MODELS = {"anthropic": "claude-sonnet-5", "gemini": "gemini-3.5-flash"}

SYSTEM = f"""You are the business-intelligence analyst for {COMPANY}, an LED lighting
manufacturer in Kerala that sells through ~200 dealers. You write for the Managing
Director. Rules:
- Use ONLY the facts and numbers given in the fact sheet. Never invent figures.
- If something cannot be concluded from the facts, say so briefly.
- Indian number style (₹ lakh / crore). Plain, direct business English.
- Every issue must name an OWNER and a concrete ACTION.
"""


def _cfg(secrets, key, default=None):
    try:
        if secrets is not None and key in secrets:
            return secrets[key]
    except Exception:
        pass
    return os.environ.get(key, default)


def ai_status(secrets=None) -> tuple[bool, str]:
    prov = (_cfg(secrets, "AI_PROVIDER") or "").lower()
    if prov == "anthropic" and _cfg(secrets, "ANTHROPIC_API_KEY"):
        return True, f"Anthropic ({_cfg(secrets, 'AI_MODEL') or DEFAULT_MODELS['anthropic']})"
    if prov == "gemini" and _cfg(secrets, "GEMINI_API_KEY"):
        return True, f"Gemini ({_cfg(secrets, 'AI_MODEL') or DEFAULT_MODELS['gemini']})"
    return False, "Not configured — using rule-based summary"


def _call_llm(prompt: str, secrets=None, max_tokens: int = 1500) -> str:
    prov = (_cfg(secrets, "AI_PROVIDER") or "").lower()
    model = _cfg(secrets, "AI_MODEL") or DEFAULT_MODELS.get(prov)
    if prov == "anthropic":
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": _cfg(secrets, "ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": model, "max_tokens": max_tokens, "system": SYSTEM,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=90,
        )
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json()["content"])
    if prov == "gemini":
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": _cfg(secrets, "GEMINI_API_KEY")},
            json={"systemInstruction": {"parts": [{"text": SYSTEM}]},
                  "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                  "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.3}},
            timeout=90,
        )
        r.raise_for_status()
        return "".join(p.get("text", "") for p in r.json()["candidates"][0]["content"]["parts"])
    raise RuntimeError("AI provider not configured")


# ---------------------------------------------------------------------------
# Fact sheet
# ---------------------------------------------------------------------------

def build_context(b, alerts: pd.DataFrame, period_days: int = 1) -> str:
    as_of = b.as_of
    L = [f"FACT SHEET — data as of {as_of:%d-%b-%Y} (business days Mon–Sat)"]
    s = b.get("sales")
    if not s.empty:
        k = sales_kpis(s, as_of)
        L += ["", "## SALES",
              f"- Month-to-date sales {inr(k['mtd_sales'])} vs {inr(k['mtd_prev_same'])} same period last month ({k['mtd_growth']:+.1f}%)",
              f"- MTD gross margin {k['mtd_margin_pct']:.1f}%; month-end projection {inr(k['mtd_projection'])}",
              f"- Last 30 days {inr(k['l30_sales'])} vs previous 30 days {inr(k['p30_sales'])} ({k['l30_growth']:+.1f}%)",
              f"- Billing dealers this month: {k['mtd_dealers']}; invoices: {k['mtd_invoices']}; FY-to-date {inr(k['fy_sales'])}"]
        recent = window(s, as_of, period_days)
        if period_days <= 7:
            L.append(f"- Sales in the last {period_days} day(s): {inr(recent['amount'].sum())} from {recent['cust_code'].nunique()} dealers")
        ct = category_trend(s, as_of).head(10)
        L.append("- Category last-30D vs prior-30D: " + "; ".join(
            f"{r.category} {inr(r.last30)} ({r.change_pct:+.0f}%)" for r in ct.itertuples() if not np.isnan(r.change_pct)))
        ex = window(s, as_of, 30).groupby("executive")["amount"].sum().sort_values(ascending=False)
        L.append("- Executive sales last 30D: " + "; ".join(f"{e} {inr(v)}" for e, v in ex.items()))
        top = window(s, as_of, 30).groupby("party")["amount"].sum().nlargest(5)
        L.append("- Top dealers last 30D: " + "; ".join(f"{p} {inr(v)}" for p, v in top.items()))
        act = dealer_activity(s, as_of)
        grow = act[(act["prev90"] > 50000)].assign(chg=lambda d: (d["last90"] - d["prev90"]) / d["prev90"] * 100)
        L.append("- Biggest dealer declines (90D vs prior 90D): " + "; ".join(
            f"{r.party} {r.chg:+.0f}%" for r in grow.nsmallest(5, "chg").itertuples()))
        L.append("- Biggest dealer growth (90D vs prior 90D): " + "; ".join(
            f"{r.party} {r.chg:+.0f}%" for r in grow.nlargest(5, "chg").itertuples()))
    fg, rm = b.get("fg_stock"), b.get("rm_stock")
    if not fg.empty or not rm.empty:
        L += ["", "## INVENTORY"]
        if not fg.empty:
            L.append(f"- FG stock value {inr(fg['stock_value'].sum())} across {int((fg['stock'] > 0).sum())} items; "
                     f"slow-moving (>180 days cover) {inr(fg.loc[fg['days_of_stock'] > 180, 'stock_value'].sum())}")
        if not rm.empty:
            L.append(f"- RM stock value {inr(rm['stock_value'].sum())}; items at ORDER NOW: {int(rm['status'].str.contains('ORDER NOW').sum())}; "
                     f"value to order {inr(rm['shortage_value'].sum())}")
    osd = b.get("outstanding")
    if not osd.empty:
        col = b.get("collections")
        L += ["", "## RECEIVABLES",
              f"- Total outstanding {inr(osd['amount'].sum())}; above 60 days {inr(osd['above60'].sum())} "
              f"({osd['above60'].sum() / max(osd['amount'].sum(), 1) * 100:.0f}%) across {int((osd['above60'] > 0).sum())} dealers"]
        if not col.empty:
            m_start = as_of.replace(day=1)
            L.append(f"- Collections this month {inr(col.loc[col['date'] >= m_start, 'amount'].sum())}; last 30 days {inr(window(col, as_of, 30)['amount'].sum())}")
    pur = b.get("purchases")
    if not pur.empty:
        l30 = window(pur, as_of, 30)
        L += ["", "## PURCHASE",
              f"- Purchases last 30 days {inr(l30['amount'].sum())} from {l30['supplier'].nunique()} suppliers",
              "- Top suppliers last 30D: " + "; ".join(f"{k} {inr(v)}" for k, v in l30.groupby('supplier')['amount'].sum().nlargest(5).items())]
    if not alerts.empty:
        L += ["", "## ALERTS (severity | category | issue | ₹ | owner | action)"]
        summ = alert_summary(alerts)
        L.append("- Counts: " + "; ".join(f"{r.category}: {r.Total} ({r.Critical} critical)" for r in summ.itertuples()))
        for r in diverse_top(alerts, per_cat=4, n=36).itertuples():
            L.append(f"- {r.severity} | {r.category} | {r.title} | {inr(r.value)} | {r.owner} | {r.action}")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Question-specific lookup (item codes / dealer names)
# ---------------------------------------------------------------------------

def _pick(df, names):
    for n in names:
        if n in df.columns:
            return n
    return None


def lookup_context(question: str, b) -> str:
    """Exact item / dealer figures computed from the sales data for this question."""
    s = b.get("sales")
    if s is None or s.empty:
        return ""
    q = question.lower()
    as_of = pd.Timestamp(b.as_of).normalize()
    item_col = _pick(s, ["item_code", "item", "stock_item", "item_name", "product"])
    name_col = _pick(s, ["item_name", "description", "product"])
    qty_col = _pick(s, ["qty", "quantity", "units"])

    def tot(d):
        return (f"qty {d[qty_col].sum():,.0f}, " if qty_col else "") + inr(d["amount"].sum())

    def summarise(sub, label):
        out = ["", f"## LOOKUP (exact figures computed from sales data): {label}"]
        if sub.empty:
            return out + ["- No sales found for this in the loaded data"]
        today = pd.Timestamp.today().normalize()
        lw_end = today - pd.Timedelta(days=today.weekday() + 1)      # last Sunday before today
        lw_start = lw_end - pd.Timedelta(days=6)                       # Monday before it
        out.append(f"- Last sale date in data: {sub['date'].max():%d-%b-%Y}")
        for lbl, a, z in [(f"Last calendar week {lw_start:%d-%b}–{lw_end:%d-%b}", lw_start, lw_end),
                          (f"Last 7 days to {as_of:%d-%b}", as_of - pd.Timedelta(days=6), as_of),
                          ("Last 30 days", as_of - pd.Timedelta(days=29), as_of)]:
            d = sub[(sub["date"] >= a) & (sub["date"] <= z)]
            out.append(f"- {lbl}: {tot(d)} to {d['party'].nunique()} dealers")
        out.append(f"- All loaded data: {tot(sub)}")
        agg = {"amount": "sum"}
        if qty_col:
            agg[qty_col] = "sum"
        wk = (sub[sub["date"] > as_of - pd.Timedelta(weeks=8)]
              .set_index("date").resample("W-SUN").agg(agg))
        if not wk.empty:
            out.append("- Weekly (week ending): " + "; ".join(
                f"{i:%d-%b} " + (f"qty {r[qty_col]:,.0f} " if qty_col else "") + inr(r["amount"])
                for i, r in wk.iterrows()))
        top = sub[sub["date"] > as_of - pd.Timedelta(days=30)].groupby("party")["amount"].sum().nlargest(5)
        if not top.empty:
            out.append("- Top buyers last 30D: " + "; ".join(f"{p} {inr(v)}" for p, v in top.items()))
        return out

    L = []
    # --- item codes (any word containing 3+ digits) ---
    if item_col:
        codes = (s[item_col].astype(str).str.strip().str.lower()
                 .str.replace(r"\.0$", "", regex=True))
        for tok in re.findall(r"\b[a-z]*\d{3,}[a-z0-9\-/]*\b", q)[:3]:
            sub = s[codes == tok]
            if sub.empty:
                sub = s[codes.str.contains(tok, regex=False)]
            name = (f" ({sub[name_col].iloc[0]})"
                    if name_col and name_col != item_col and not sub.empty else "")
            L += summarise(sub, f"item {tok.upper()}{name}")
    elif re.search(r"\d{3,}", q):
        L += ["", f"## LOOKUP: item code column not found in sales data (columns: {', '.join(map(str, s.columns))})"]

    # --- dealer names (full name, or first word of 5+ letters) ---
    found = 0
    for p in s["party"].dropna().unique():
        pl = str(p).lower()
        first = pl.split()[0] if pl.split() else ""
        if pl in q or (len(first) >= 5 and re.search(rf"\b{re.escape(first)}\b", q)):
            L += summarise(s[s["party"] == p], f"dealer {p}")
            found += 1
            if found >= 3:
                break
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Brief & Q&A
# ---------------------------------------------------------------------------

BRIEF_PROMPT = """Write the {kind} MANAGEMENT BRIEF from the fact sheet below.

Format (Markdown, max ~350 words):
**Headline** — one sentence: the single most important thing today.
**Business pulse** — 3-4 bullets: sales vs last month, margin, collections, stock.
**Needs attention now** — the 5 most important issues, each: issue → ₹ impact → OWNER → action.
**Trends & signals** — 2-3 bullets on what is improving / deteriorating and why it matters.
**Opportunity** — 1-2 bullets (e.g. fast-growing category, dealers to push, slow stock to liquidate).

FACT SHEET
----------
{facts}
"""


def rule_based_brief(b, alerts: pd.DataFrame, kind: str = "daily") -> str:
    s = b.get("sales")
    out = [f"### {kind.title()} Management Brief — {b.as_of:%d %b %Y}", "_Rule-based summary (AI not configured)_", ""]
    if not s.empty:
        k = sales_kpis(s, b.as_of)
        out += ["**Business pulse**",
                f"- MTD sales {inr(k['mtd_sales'])} ({k['mtd_growth']:+.1f}% vs same period last month); projection {inr(k['mtd_projection'])}",
                f"- MTD margin {k['mtd_margin_pct']:.1f}%; {k['mtd_dealers']} dealers billed"]
    osd = b.get("outstanding")
    if not osd.empty:
        out.append(f"- Outstanding {inr(osd['amount'].sum())}, of which {inr(osd['above60'].sum())} is above 60 days")
    if not alerts.empty:
        out += ["", "**Needs attention now**"]
        for r in diverse_top(alerts, per_cat=1, n=8).itertuples():
            out.append(f"- **{r.severity}** · {r.title} — {inr(r.value)} → **{r.owner}**: {r.action}")
        summ = alert_summary(alerts)
        out += ["", "**Alert counts**: " + ", ".join(f"{r.category} {r.Total}" for r in summ.itertuples())]
    return "\n".join(out)


def management_brief(b, alerts: pd.DataFrame, kind: str = "daily", secrets=None) -> tuple[str, str]:
    """Returns (markdown, source) where source is 'ai' or 'rules'."""
    ok, _ = ai_status(secrets)
    if ok:
        try:
            facts = build_context(b, alerts, period_days=1 if kind == "daily" else 7)
            return _call_llm(BRIEF_PROMPT.format(kind=kind.upper(), facts=facts), secrets), "ai"
        except Exception as e:
            fb = rule_based_brief(b, alerts, kind)
            return fb + f"\n\n_AI call failed: {str(e)[:150]}_", "rules"
    return rule_based_brief(b, alerts, kind), "rules"


def ask(question: str, b, alerts: pd.DataFrame, secrets=None) -> str:
    facts = build_context(b, alerts, period_days=7)
    extra = lookup_context(question, b)
    if extra:
        facts += "\n" + extra
    prompt = (f"Management question: {question}\n\nAnswer from the fact sheet only, in under 200 words, "
              f"with specific numbers, owner and next action where relevant. LOOKUP sections are exact "
              f"figures computed from the sales data — use them directly. 'Last week' means the last "
              f"calendar week shown in the LOOKUP. If the last sale date in the data is before the period "
              f"asked, say the sales data may not be updated yet. If the fact sheet does not contain the "
              f"answer, say which data would be needed.\n\nFACT SHEET\n----------\n{facts}")
    answer = _call_llm(prompt, secrets, max_tokens=800)
    debug = extra.strip() or "No item code or dealer name matched in the question."
    return answer + "\n\n---\n**Data lookup (for checking):**\n```\n" + debug + "\n```"
