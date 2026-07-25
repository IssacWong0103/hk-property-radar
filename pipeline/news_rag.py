"""News pusher: retrieve HK residential-property news, summarise with DeepSeek,
write site/data/news.json + top3.json for the in-app feed.

Grounding rule: DeepSeek only *summarises* and *ranks* the retrieved articles and
refers to them by index — every output item's `url` is copied from the real
retrieved article, never generated. Works without a key too (falls back to the
RSS snippets), so the feed always has real, clickable sources.

Env:  DEEPSEEK_API_KEY (optional)   Run:  python pipeline/news_rag.py
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

from common import SITE_DATA_DIR

# Buyer/renter-relevant Google News RSS queries (free, reliable, returns links).
QUERIES = [
    "Hong Kong residential property price",
    "Hong Kong home prices mortgage rate",
    "Hong Kong property stamp duty policy",
    "Hong Kong rental market flats",
    "Hong Kong new residential launch",
]
GNEWS = "https://news.google.com/rss/search?q={q}&hl=en-HK&gl=HK&ceid=HK:en"
MAX_ITEMS = 12
UA = {"User-Agent": "Mozilla/5.0 (HK-Property-Radar news bot)"}
KEYWORDS = ("propert", "flat", "home", "housing", "residential", "mortgage", "rent",
            "stamp duty", "developer", "price", "estate", "hkma", "hibor")


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read()


def retrieve() -> list[dict]:
    seen, items = set(), []
    for q in QUERIES:
        try:
            xml = _fetch(GNEWS.format(q=urllib.parse.quote(q)))
        except Exception as e:  # noqa: BLE001
            print(f"  ! fetch failed for {q!r}: {e}")
            continue
        root = ET.fromstring(xml)
        for it in root.iterfind(".//item"):
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            if not title or not link:
                continue
            src_el = it.find("{http://news.google.com}source") or it.find("source")
            publisher = (src_el.text.strip() if src_el is not None and src_el.text else "")
            # Google News titles end with " - Publisher"; strip it when we know the source.
            if publisher and title.endswith(f" - {publisher}"):
                title = title[: -(len(publisher) + 3)].strip()
            key = re.sub(r"\W+", "", title.lower())[:60]
            if key in seen:
                continue
            desc = re.sub(r"<[^>]+>", "", it.findtext("description") or "").strip()
            try:
                dt = parsedate_to_datetime(it.findtext("pubDate"))
                date = dt.astimezone(timezone.utc).strftime("%Y-%m-%d")
                ts = dt.timestamp()
            except Exception:  # noqa: BLE001
                date, ts = "", 0
            text = (title + " " + desc).lower()
            if not any(k in text for k in KEYWORDS):
                continue
            seen.add(key)
            items.append({"title": title, "url": link, "publisher": publisher,
                          "date": date, "snippet": desc[:300], "_ts": ts})
    items.sort(key=lambda x: x["_ts"], reverse=True)
    return items[:MAX_ITEMS]


def kpi_context() -> str:
    try:
        k = json.load(open(os.path.join(SITE_DATA_DIR, "kpis.json"), encoding="utf-8"))
        return " | ".join(f"{x['label']}: {x.get('value')} ({x.get('sub','')})" for x in k)
    except Exception:  # noqa: BLE001
        return ""


def summarise(items: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return (feed, top3). Uses DeepSeek if a key is set; else RSS-snippet fallback."""
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        print("  (no DEEPSEEK_API_KEY — using RSS snippets, no AI summary)")
        feed = [{"title": it["title"], "summary": it["snippet"] or "",
                 "publisher": it["publisher"], "date": it["date"], "url": it["url"]} for it in items]
        top3 = [{"title": it["title"], "summary": it["snippet"][:160] if it["snippet"] else "",
                 "url": it["url"]} for it in items[:3]]
        return feed, top3

    from openai import OpenAI
    client = OpenAI(api_key=key, base_url="https://api.deepseek.com")
    listing = "\n".join(f"[{i}] {it['title']} — {it['publisher']} ({it['date']})\n    {it['snippet']}"
                        for i, it in enumerate(items))
    prompt = (
        "You are briefing YR, a non-technical family buyer/renter deciding where and when to buy or rent "
        "a home in Hong Kong. Below are real news articles (indexed). Latest market data: "
        f"{kpi_context()}.\n\nARTICLES:\n{listing}\n\n"
        "Return STRICT JSON only, no prose:\n"
        '{ "feed":[{"i":<index>,"summary":"1-2 plain-English sentences on why this matters to a home buyer/renter"}], '
        '"top3":[{"i":<index>,"headline":"punchy <=8 word headline","why":"1 sentence why it matters"}] }\n'
        "Rules: only use the articles above; refer to them by their index i; do NOT invent facts or URLs; "
        "top3 = the three most decision-relevant moves for a HK home buyer/renter."
    )
    try:
        resp = client.chat.completions.create(
            model="deepseek-chat", temperature=0.3,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
        )
        data = json.loads(resp.choices[0].message.content)
    except Exception as e:  # noqa: BLE001
        print(f"  ! DeepSeek failed ({e}); falling back to snippets")
        return summarise_fallback(items)

    def art(i):
        return items[i] if isinstance(i, int) and 0 <= i < len(items) else None
    feed = []
    for row in data.get("feed", []):
        it = art(row.get("i"))
        if it:
            feed.append({"title": it["title"], "summary": row.get("summary", "").strip(),
                         "publisher": it["publisher"], "date": it["date"], "url": it["url"]})
    for it in items:  # ensure every article appears even if the model skipped it
        if not any(f["url"] == it["url"] for f in feed):
            feed.append({"title": it["title"], "summary": it["snippet"], "publisher": it["publisher"],
                         "date": it["date"], "url": it["url"]})
    top3 = []
    for row in data.get("top3", [])[:3]:
        it = art(row.get("i"))
        if it:
            top3.append({"title": row.get("headline") or it["title"],
                         "summary": row.get("why", "").strip(), "url": it["url"]})
    return feed, (top3 or [{"title": f["title"], "summary": f["summary"], "url": f["url"]} for f in feed[:3]])


def summarise_fallback(items):
    feed = [{"title": it["title"], "summary": it["snippet"] or "", "publisher": it["publisher"],
             "date": it["date"], "url": it["url"]} for it in items]
    return feed, [{"title": it["title"], "summary": it["snippet"][:160], "url": it["url"]} for it in items[:3]]


def main():
    print("Retrieving HK property news …")
    items = retrieve()
    print(f"  {len(items)} relevant articles")
    feed, top3 = summarise(items)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    os.makedirs(SITE_DATA_DIR, exist_ok=True)
    json.dump({"generated_at": now, "items": feed},
              open(os.path.join(SITE_DATA_DIR, "news.json"), "w", encoding="utf-8"), ensure_ascii=False)
    json.dump({"generated_at": now, "items": top3},
              open(os.path.join(SITE_DATA_DIR, "top3.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print(f"  wrote news.json ({len(feed)} items) + top3.json ({len(top3)} items)")


if __name__ == "__main__":
    main()
