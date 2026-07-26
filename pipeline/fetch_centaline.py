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
import re
import statistics
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict

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


def _post(body: dict, tries: int = 3, headers: dict | None = None):
    data = json.dumps(body).encode()
    for i in range(tries):
        try:
            req = urllib.request.Request(API, data=data, headers=headers or HEADERS, method="POST")
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except (urllib.error.URLError, TimeoutError, ValueError):
            if i == tries - 1:
                raise
            time.sleep(1.0 + i)
    return None


_YEAR_RE = re.compile(r"(\d{4})")


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


def _estate_name(rec) -> str:
    """Canonical estate label. Centaline splits phased developments so the phase
    ('1期') lands in estateName and the real estate in bigEstateName — keying on
    estateName alone would merge different estates' phases, so combine them.
      Phase  → "<big estate> <phase>"   e.g. 日出康城 4期A 晉海
      Normal → estateName               e.g. 昇悅居
      Single → buildingName             e.g. 鑽嶺
    """
    big = (rec.get("bigEstateName") or "").strip()
    est = (rec.get("estateName") or "").strip()
    bld = (rec.get("buildingName") or "").strip()
    if rec.get("estateType") == "Phase" and big:
        return f"{big} {est}".strip()
    return est or bld


def _built_year(rec):
    m = _YEAR_RE.search(str(rec.get("opYear") or ""))
    return int(m.group(1)) if m else None


def _norm(rec) -> dict | None:
    """Reduce one API record to the fields we keep, applying the same quality
    gates as before; None drops the row."""
    if rec.get("firstOrSecondHand") != "SecondHand":
        return None
    code = _district_code(rec)
    if not code:
        return None
    area, price = rec.get("nArea"), rec.get("transactionPrice")
    if not area or not price or area < AREA_MIN:
        return None
    # Centaline's own saleable $/sq.ft when present, else compute it.
    psf = rec.get("nUnitPrice") or (price / area)
    try:
        psf = float(psf)
    except (TypeError, ValueError):
        return None
    if not (PSF_MIN <= psf <= PSF_MAX):
        return None
    return {"id": rec.get("id"), "code": code, "estate": _estate_name(rec),
            "en": "", "built": _built_year(rec),
            "psf": psf, "price": float(price), "area": float(area),
            "url": rec.get("detailUrl") or ""}


def fetch_records() -> list[dict]:
    """Page the recent second-hand sales → list of normalised deal records."""
    out: list[dict] = []
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
            nr = _norm(rec)
            if nr:
                out.append(nr)
        if len(data) < PAGE:
            break
        time.sleep(DELAY)
    return out


def fetch_en_names() -> dict:
    """Second pass with the `Lang: EN` header — the API returns the official
    English estate name for the same records. Pair by transaction id → {id: en}.
    Best-effort: any failure leaves estates on their Chinese name + curated map."""
    headers = {**HEADERS, "Lang": "EN"}
    out: dict[str, str] = {}
    seen: set = set()
    for page in range(MAX_PAGES):
        body = {"postType": "Sale", "day": f"Day{DAYS}", "sort": "InsOrRegDate",
                "order": "Descending", "size": PAGE, "offset": page * PAGE, "pageSource": "search"}
        data = (_post(body, headers=headers) or {}).get("data") or []
        if not data:
            break
        for rec in data:
            rid = rec.get("id")
            if rid in seen:
                continue
            seen.add(rid)
            if rec.get("firstOrSecondHand") != "SecondHand":
                continue
            name = _estate_name(rec)
            if name:
                out[rid] = name
        if len(data) < PAGE:
            break
        time.sleep(DELAY)
    return out


def write_district_csv(records: list[dict]) -> str:
    """(17): median saleable $/sq.ft + transaction count per district. Unchanged
    schema — build_figures.build_districts() still reads exactly this."""
    buckets: dict[str, list] = defaultdict(list)
    for r in records:
        buckets[r["code"]].append(r["psf"])
    rows = []
    for code, (cn, _en, reg) in DISTRICT_BY_CODE.items():
        vals = buckets.get(code) or []
        if not vals:
            continue
        rows.append({"地區": cn, "區域": reg, "單位總數": len(vals),
                     "二手成交中位呎價": round(statistics.median(vals))})
    path = os.path.join(CLEAN_DIR, "(17)Centaline_secondhand_districts.csv")
    _write_csv(path, ["地區", "區域", "單位總數", "二手成交中位呎價"], rows)
    print(f"  wrote {os.path.basename(path)} ({len(rows)} districts)")
    return path


def write_estate_csv(records: list[dict]) -> str:
    """(18): one row per estate within a district — median $/sq.ft, median price,
    built year, size range, sample size and a link to the underlying deals."""
    groups: dict[tuple, list] = defaultdict(list)
    for r in records:
        if r["estate"]:
            groups[(r["code"], r["estate"])].append(r)
    rows = []
    for (code, estate), items in groups.items():
        cn, _en, reg = DISTRICT_BY_CODE[code]
        builts = [x["built"] for x in items if x["built"]]
        areas = [x["area"] for x in items]
        # Official English name from the EN pass; most common non-empty wins.
        en_names = [x["en"] for x in items if x.get("en")]
        estate_en = Counter(en_names).most_common(1)[0][0] if en_names else ""
        rows.append({
            "地區": cn, "區域": reg, "屋苑": estate, "屋苑英文": estate_en,
            "落成年份": min(builts) if builts else "",
            "成交宗數": len(items),
            "中位呎價": round(statistics.median(x["psf"] for x in items)),
            "中位售價": round(statistics.median(x["price"] for x in items)),
            "最細面積": round(min(areas)),
            "最大面積": round(max(areas)),
            "細節連結": next((x["url"] for x in items if x["url"]), ""),
        })
    # District, then most-traded estate first.
    order = {c: i for i, c in enumerate(DISTRICT_BY_CODE)}
    rows.sort(key=lambda r: (order.get(CN_TO_CODE.get(r["地區"], "Z"), 99), -r["成交宗數"]))
    path = os.path.join(CLEAN_DIR, "(18)Centaline_secondhand_estates.csv")
    _write_csv(path, ["地區", "區域", "屋苑", "屋苑英文", "落成年份", "成交宗數",
                      "中位呎價", "中位售價", "最細面積", "最大面積", "細節連結"], rows)
    print(f"  wrote {os.path.basename(path)} ({len(rows)} estates)")
    return path


def _write_csv(path: str, fields: list[str], rows: list[dict]) -> None:
    os.makedirs(CLEAN_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main():
    try:
        print(f"Fetching Centaline second-hand sales (last {DAYS} days) …")
        records = fetch_records()
        covered = len({r["code"] for r in records})
        print(f"  {len(records):,} second-hand sales across {covered}/18 districts")
        if covered < MIN_DISTRICTS:
            print(f"  (fetch_centaline: only {covered}/18 districts — keeping last-good, not overwriting)")
            return
        try:
            en = fetch_en_names()   # {id: official English estate name}
            for r in records:
                r["en"] = en.get(r["id"], "")
            print(f"  matched {sum(1 for r in records if r['en']):,}/{len(records):,} deals to English names")
        except Exception as e:  # noqa: BLE001 — English is a nice-to-have, never fatal
            print(f"  (English name pass failed [{type(e).__name__}] — falling back to Chinese + curated map)")
        write_district_csv(records)
        write_estate_csv(records)
        print("Done — district + estate second-hand $/sq.ft refreshed from Centaline.")
    except Exception as e:  # noqa: BLE001 — a scraper hiccup must never break the build
        print(f"  (fetch_centaline: failed [{type(e).__name__}: {e}] — keeping last-good district data)")


if __name__ == "__main__":
    main()
