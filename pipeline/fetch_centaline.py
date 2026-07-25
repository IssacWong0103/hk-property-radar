"""Self-source the 18-district SECOND-HAND price view from Centaline's public
transaction feed → data/clean/(17)*.csv for build_figures.build_districts().

Why Centaline: Hong Kong has no free, official 18-district *secondary-market*
$/sq.ft feed — the RVD open data (which powers the rest of this dashboard) only
breaks prices down to 3 broad regions. Centaline's "Find Property" transaction
search, however, is a public JSON API (no auth) where every sale already carries
the official 18-District Council district code (scope.db_code) plus the saleable
area and price. So a median HK$/sq.ft per district drops straight out — no PDF
parsing and no fuzzy name-matching.

Source / attribution: Centaline Property (hk.centanet.com). The underlying deals
are Land Registry records; the saleable areas are supplied by Centaline. This is
surfaced as the data source in the dashboard's Districts tab.

Politeness & safety: only the recent window is paged (~70 small requests for the
default 30 days), with delays + retries. main() is a safe no-op on any failure,
so the pipeline never breaks — build_figures then keeps the last-good (17) file,
or falls back to the official RVD 3-region view if none exists.

Run:  python pipeline/fetch_centaline.py
"""
from __future__ import annotations

import csv
import json
import os
import statistics
import time
import urllib.error
import urllib.request

from common import CLEAN_DIR

API = "https://hk.centanet.com/findproperty/api/Transaction/Search"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (HK-Property-Radar; +https://github.com/)",
    "Content-Type": "application/json",
    "Platform": "Web",
}

# ---- config (env-overridable) ----
DAYS = os.environ.get("CENTALINE_DAYS", "30")          # lookback; >30d hits the API's ~10k offset cap
PAGE = 100                                              # max page size the API allows
MAX_PAGES = int(os.environ.get("CENTALINE_MAX_PAGES", "120"))
DELAY = float(os.environ.get("CENTALINE_DELAY", "0.2"))  # seconds between page requests
MIN_DISTRICTS = 15                                     # require near-full coverage before overwriting (17)
PSF_MIN, PSF_MAX, AREA_MIN = 1500, 100000, 100         # drop car-parks / village houses / garbage rows

# Centaline official district code -> (Chinese district, English district [== DISTRICTS_18], Chinese region)
DISTRICT_BY_CODE = {
    "A": ("中西區", "Central & Western", "港島"),
    "B": ("灣仔區", "Wan Chai", "港島"),
    "C": ("東區", "Eastern", "港島"),
    "D": ("南區", "Southern", "港島"),
    "E": ("油尖旺區", "Yau Tsim Mong", "九龍"),
    "F": ("深水埗區", "Sham Shui Po", "九龍"),
    "G": ("九龍城區", "Kowloon City", "九龍"),
    "H": ("黃大仙區", "Wong Tai Sin", "九龍"),
    "J": ("觀塘區", "Kwun Tong", "九龍"),
    "K": ("荃灣區", "Tsuen Wan", "新界"),
    "L": ("屯門區", "Tuen Mun", "新界"),
    "M": ("元朗區", "Yuen Long", "新界"),
    "N": ("北區", "North", "新界"),
    "P": ("大埔區", "Tai Po", "新界"),
    "R": ("沙田區", "Sha Tin", "新界"),
    "S": ("葵青區", "Kwai Tsing", "新界"),
    "T": ("離島區", "Islands", "新界"),
    "U": ("西貢區", "Sai Kung", "新界"),
}
CN_TO_CODE = {cn: code for code, (cn, _en, _reg) in DISTRICT_BY_CODE.items()}


def _post(body: dict, tries: int = 3):
    data = json.dumps(body).encode()
    for i in range(tries):
        try:
            req = urllib.request.Request(API, data=data, headers=HEADERS, method="POST")
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except (urllib.error.URLError, TimeoutError, ValueError):
            if i == tries - 1:
                raise
            time.sleep(1.0 + i)
    return None


def _district_code(rec) -> str | None:
    """Official 18-district code for a transaction; recovers rare sub-scope codes
    (e.g. 'V') by reading the parent district out of the label '… (X區)'."""
    scope = rec.get("scope") or {}
    code = scope.get("db_code")
    if code in DISTRICT_BY_CODE:
        return code
    label = scope.get("db") or ""
    for cn, c in CN_TO_CODE.items():
        if cn in label:
            return c
    return None


def fetch_psf_by_district() -> dict:
    """Page the recent second-hand sales → {district_code: [psf, ...]}."""
    buckets: dict[str, list] = {}
    seen: set = set()
    for page in range(MAX_PAGES):
        body = {"postType": "Sale", "day": f"Day{DAYS}", "sort": "InsOrRegDate",
                "order": "Descending", "size": PAGE, "offset": page * PAGE, "pageSource": "search"}
        data = (_post(body) or {}).get("data") or []
        if not data:
            break
        for rec in data:
            rid = rec.get("id")
            if rid in seen:
                continue
            seen.add(rid)
            if rec.get("firstOrSecondHand") != "SecondHand":
                continue
            code = _district_code(rec)
            if not code:
                continue
            area, price = rec.get("nArea"), rec.get("transactionPrice")
            if not area or not price or area < AREA_MIN:
                continue
            psf = price / area
            if PSF_MIN <= psf <= PSF_MAX:
                buckets.setdefault(code, []).append(psf)
        if len(data) < PAGE:
            break
        time.sleep(DELAY)
    return buckets


def write_csv(buckets: dict) -> str:
    rows = []
    for code, (cn, _en, reg) in DISTRICT_BY_CODE.items():
        vals = buckets.get(code) or []
        if not vals:
            continue
        rows.append({
            "地區": cn,
            "區域": reg,
            "單位總數": len(vals),                       # sample size (transactions), reused as the psf weight
            "二手成交中位呎價": round(statistics.median(vals)),
        })
    os.makedirs(CLEAN_DIR, exist_ok=True)
    path = os.path.join(CLEAN_DIR, "(17)Centaline_secondhand_districts.csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["地區", "區域", "單位總數", "二手成交中位呎價"])
        w.writeheader()
        w.writerows(rows)
    print(f"  wrote {os.path.basename(path)} ({len(rows)} districts)")
    return path


def main():
    try:
        print(f"Fetching Centaline second-hand sales (last {DAYS} days) …")
        buckets = fetch_psf_by_district()
        covered = sum(1 for c in DISTRICT_BY_CODE if buckets.get(c))
        total = sum(len(v) for v in buckets.values())
        print(f"  {total:,} second-hand sales across {covered}/18 districts")
        if covered < MIN_DISTRICTS:
            print(f"  (fetch_centaline: only {covered}/18 districts — keeping last-good (17), not overwriting)")
            return
        write_csv(buckets)
        print("Done — 18-district second-hand $/sq.ft refreshed from Centaline.")
    except Exception as e:  # noqa: BLE001 — a scraper hiccup must never break the build
        print(f"  (fetch_centaline: failed [{type(e).__name__}: {e}] — keeping last-good district data)")


if __name__ == "__main__":
    main()
