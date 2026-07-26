"""Self-source total monthly residential transaction volume from the Land Registry.

The Land Registry publishes, as open data, the monthly count of Agreements for
Sale & Purchase of residential building units received for registration, broken
down by consideration (price) band. We take the "Total" row → one clean monthly
volume series. This is the single most direct "is the market active or quiet?"
signal for a buyer timing a purchase.

Note: the open data does NOT split primary vs secondary — that breakdown is only
in commercial (Centaline/Midland) research — so we report the official total.

Source: Land Registry via data.gov.hk (landreg.gov.hk/datagovhk/consideration_YYYY.json).
Run:  python pipeline/fetch_landreg.py
"""
from __future__ import annotations

import csv
import json
import os
import urllib.request
from datetime import datetime, timezone

from common import CLEAN_DIR

BASE = "https://www.landreg.gov.hk/datagovhk/consideration_{year}.json"
UA = {"User-Agent": "Mozilla/5.0 (HK-Property-Radar)"}
START_YEAR = int(os.environ.get("LANDREG_START_YEAR", "2015"))
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _get(url: str):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=45) as r:
        # the LR files carry a UTF-8 BOM
        return json.loads(r.read().decode("utf-8-sig", "replace"))


def fetch_rows() -> list[dict]:
    rows = []
    this_year = datetime.now(timezone.utc).year
    for year in range(START_YEAR, this_year + 1):
        try:
            data = _get(BASE.format(year=year))
        except Exception:  # noqa: BLE001 — a missing/late year must not sink the rest
            continue
        recs = data if isinstance(data, list) else (data.get("records") or data.get("data") or [])
        total = next((r for r in recs
                      if str(r.get("Range of Consideration ($ million)", "")).strip().lower() == "total"), None)
        if not total:
            continue
        for i, m in enumerate(MONTHS, start=1):
            raw = str(total.get(m, "")).replace(",", "").strip()
            if not raw:
                continue
            try:
                val = int(float(raw))
            except ValueError:
                continue
            rows.append({"Period": f"{year}-{i:02d}-01", "Total": val})
    return rows


def main():
    try:
        print("Fetching Land Registry monthly transaction volume …")
        rows = fetch_rows()
        if len(rows) < 12:
            print(f"  (fetch_landreg: only {len(rows)} months — keeping last-good, not overwriting)")
            return
        os.makedirs(CLEAN_DIR, exist_ok=True)
        path = os.path.join(CLEAN_DIR, "(15)LandReg_transactions.csv")
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["Period", "Total"])
            w.writeheader()
            w.writerows(rows)
        print(f"  wrote {os.path.basename(path)} ({len(rows)} months, latest {rows[-1]['Period'][:7]})")
    except Exception as e:  # noqa: BLE001
        print(f"  (fetch_landreg failed [{type(e).__name__}: {e}] — keeping last-good volume data)")


if __name__ == "__main__":
    main()
