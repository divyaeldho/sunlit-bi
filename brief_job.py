"""
Automated AI Management Brief — runs on a schedule (GitHub Actions or Windows
Task Scheduler), reads live Sunlit data, builds alerts, writes the brief and
emails it to management with the full alert list attached.

Usage:
    python brief_job.py --kind daily            # email the brief
    python brief_job.py --kind weekly
    python brief_job.py --kind daily --dry-run  # print only, no email

Environment variables (or .streamlit/secrets.toml when run locally):
    GOOGLE_SERVICE_ACCOUNT_JSON   service-account JSON (one line)
    AI_PROVIDER, ANTHROPIC_API_KEY / GEMINI_API_KEY, AI_MODEL (optional)
    SMTP_USER, SMTP_APP_PASSWORD  Gmail address + 16-char app password
    BRIEF_TO                      comma-separated recipients
    DASHBOARD_URL                 link shown at the bottom of the email
"""
from __future__ import annotations

import argparse
import os
import smtplib
import sys
import tomllib
from email.message import EmailMessage
from pathlib import Path

import markdown

sys.path.insert(0, str(Path(__file__).parent))
from core.ai import management_brief          # noqa: E402
from core.analytics import alert_summary, build_alerts, inr  # noqa: E402
from core.data import load_all                 # noqa: E402


def local_secrets() -> dict | None:
    p = Path(__file__).parent / ".streamlit" / "secrets.toml"
    if p.exists():
        with open(p, "rb") as f:
            return tomllib.load(f)
    return None


def cfg(secrets, key, default=""):
    if secrets and key in secrets:
        return secrets[key]
    return os.environ.get(key, default)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["daily", "weekly"], default="daily")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    secrets = local_secrets()
    b = load_all(secrets)
    bad = [h for h in b.health if h["status"] == "ERROR"]
    alerts = build_alerts(b)
    text, src = management_brief(b, alerts, args.kind, secrets)

    health = "".join(f"<li>{h['source']} ({h['sheet_tab']}): {h['status']} — {h['rows']:,} rows</li>" for h in b.health)
    summ = alert_summary(alerts)
    summ_html = summ.assign(**{"₹ at stake": summ["₹ at stake"].map(inr)}).to_html(index=False, border=0) if not summ.empty else ""
    url = cfg(secrets, "DASHBOARD_URL")
    html = f"""<div style="font-family:Segoe UI,Arial,sans-serif;max-width:760px;font-size:14px;line-height:1.5">
      {markdown.markdown(text)}
      <h4>Alert counts</h4>{summ_html}
      {'<p><a href="' + url + '">Open the live dashboard →</a></p>' if url else ''}
      <p style="color:#888;font-size:12px">Generated {'by AI' if src == 'ai' else 'by rules'} from live data as of {b.as_of:%d-%b-%Y}.
      {'<b>Data warnings:</b> ' + ', '.join(h['source'] for h in bad) if bad else ''}</p>
      <details><summary style="color:#888;font-size:12px">Data sources</summary><ul style="font-size:12px;color:#888">{health}</ul></details>
    </div>"""

    if args.dry_run:
        print(text)
        print("\n--- alerts:", len(alerts), "| sources:", [(h["source"], h["status"], h["rows"]) for h in b.health])
        return

    user, pw, to = cfg(secrets, "SMTP_USER"), cfg(secrets, "SMTP_APP_PASSWORD"), cfg(secrets, "BRIEF_TO")
    if not (user and pw and to):
        sys.exit("SMTP_USER, SMTP_APP_PASSWORD and BRIEF_TO must be set to send email")
    msg = EmailMessage()
    crit = int((alerts["severity"] == "Critical").sum()) if not alerts.empty else 0
    msg["Subject"] = f"Sunlit {args.kind.title()} Brief · {b.as_of:%d %b %Y} · {crit} critical alerts"
    msg["From"] = user
    msg["To"] = to
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    if not alerts.empty:
        msg.add_attachment(alerts.to_csv(index=False).encode("utf-8"), maintype="text", subtype="csv",
                           filename=f"sunlit_alerts_{b.as_of:%Y%m%d}.csv")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, pw)
        s.send_message(msg)
    print(f"Sent {args.kind} brief to {to} ({len(alerts)} alerts, source={src})")


if __name__ == "__main__":
    main()
