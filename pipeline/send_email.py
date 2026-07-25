"""Email the 'Top 3 moves' brief to opted-in subscribers.

Subscribers live in Cloudflare KV (written by the Worker when YR toggles the
in-app switch). This reads them via the Cloudflare API and sends via Gmail SMTP.
No-ops safely when creds or subscribers are absent, so the pipeline never breaks.

Env: CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN, CLOUDFLARE_KV_NAMESPACE_ID,
     GMAIL_ADDRESS, GMAIL_APP_PASSWORD, [DASHBOARD_URL]
"""
from __future__ import annotations

import json
import os
import smtplib
import ssl
import urllib.parse
import urllib.request
from email.mime.text import MIMEText

from common import SITE_DATA_DIR

DASH = os.environ.get("DASHBOARD_URL", "")


def kv_subscribers() -> list[str]:
    acc = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    tok = os.environ.get("CLOUDFLARE_API_TOKEN")
    ns = os.environ.get("CLOUDFLARE_KV_NAMESPACE_ID")
    if not all([acc, tok, ns]):
        return []
    base = f"https://api.cloudflare.com/client/v4/accounts/{acc}/storage/kv/namespaces/{ns}"
    hdr = {"Authorization": f"Bearer {tok}"}

    def api(path):
        return urllib.request.urlopen(urllib.request.Request(base + path, headers=hdr), timeout=25)

    subs, cursor = [], ""
    while True:
        res = json.load(api(f"/keys?prefix=sub:&cursor={urllib.parse.quote(cursor)}"))
        for k in res.get("result", []):
            raw = api("/values/" + urllib.parse.quote(k["name"])).read().decode()
            try:
                d = json.loads(raw)
                if d.get("enabled") and d.get("email"):
                    subs.append(d["email"])
            except json.JSONDecodeError:
                pass
        cursor = res.get("result_info", {}).get("cursor", "")
        if not cursor:
            break
    return subs


def build_html() -> tuple[str, str]:
    def load(n):
        try:
            return json.load(open(os.path.join(SITE_DATA_DIR, n), encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    top3 = (load("top3.json") or {}).get("items", [])
    kpis = load("kpis.json") or []
    kline = " · ".join(f"{k['label'].split('(')[0].strip()}: {k.get('value')}{k.get('unit','')}"
                       for k in kpis[:4])
    items = "".join(
        f'<li style="margin:0 0 12px"><b>{t.get("title","")}</b><br>'
        f'<span style="color:#444">{t.get("summary","")}</span> '
        f'{f"<a href={t["url"]}>Read more &rarr;</a>" if t.get("url") else ""}</li>'
        for t in top3) or "<li>No items this run.</li>"
    link = f'<p><a href="{DASH}">Open the dashboard &rarr;</a></p>' if DASH else ""
    html = (f'<div style="font-family:system-ui,sans-serif;max-width:560px">'
            f'<h2>HK Property Radar — Top 3 moves</h2>'
            f'<p style="color:#666;font-size:13px">{kline}</p>'
            f'<ol>{items}</ol>{link}'
            f'<p style="color:#999;font-size:12px">You get this because you switched the email brief on in the app. '
            f'Turn it off any time in Settings.</p></div>')
    return "HK Property Radar — Top 3 moves this week", html


def main():
    addr = os.environ.get("GMAIL_ADDRESS")
    pw = os.environ.get("GMAIL_APP_PASSWORD")
    subs = kv_subscribers()
    if not subs:
        print("  (email: no enabled subscribers — nothing to send)")
        return
    if not (addr and pw):
        print("  (email: subscribers exist but GMAIL_* not set — skipping)")
        return
    subject, html = build_html()
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as s:
        s.login(addr, pw)
        for to in subs:
            msg = MIMEText(html, "html", "utf-8")
            msg["Subject"] = subject
            msg["From"] = addr
            msg["To"] = to
            s.sendmail(addr, [to], msg.as_string())
    print(f"  email: sent to {len(subs)} subscriber(s)")


if __name__ == "__main__":
    main()
