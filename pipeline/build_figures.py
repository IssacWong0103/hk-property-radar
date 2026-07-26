"""Build the compact JSON the static dashboard reads.

Reads the cleaned RVD/market CSVs in data/clean/ and writes tidy JSON into
site/data/. The site (app.js + Plotly.js) renders these client-side, so
dropdowns/toggles need no backend.

Framing = a family buyer/renter (YR): rent-vs-buy, family-sized flats,
concrete $ levels, new-launch $/sqft by district, mortgage-cost context.

Run:  python pipeline/build_figures.py
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pandas as pd

from common import (
    CLASS_ORDER,
    DEFAULT_CLASS,
    FAMILY_CLASSES,
    REGION_EN,
    SITE_DATA_DIR,
    load_csv,
    num,
    yyyymm_to_iso,
)
from districts_en import DISTRICT_REGION, DISTRICTS_18, area_district, area_en, estate_en

ROUND_IDX = 1     # index values
ROUND_YIELD = 2   # % yields
MAX_ESTATES_PER_DISTRICT = 60   # cap the estate drill-down; drops the 1-deal long tail


def _write(name: str, obj) -> None:
    os.makedirs(SITE_DATA_DIR, exist_ok=True)
    path = os.path.join(SITE_DATA_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    print(f"  wrote {name} ({os.path.getsize(path):,} bytes)")


def _pct(new, old):
    if new is None or old is None or old == 0:
        return None
    return round((new - old) / old * 100, 1)


# --------------------------------------------------------------- price/rent/yield index
def build_price_rent_index() -> dict:
    """Quarterly price index (13), rent index (12), rental yield (16) by flat class."""
    price = load_csv("(13)", "quarterly")
    rent = load_csv("(12)", "quarterly")
    yld = load_csv("(16)", "quarterly")
    # RVD publishes some aggregate rows (e.g. rent 'All Classes') only annually,
    # leaving them blank in the quarterly file — fall back to the annual file.
    price_a = load_csv("(13)", "annual")
    rent_a = load_csv("(12)", "annual")

    def to_map(df):
        # columns: Time, Class, <value>  (value col name varies / is mislabeled)
        vcol = df.columns[-1]
        df = df.copy()
        df["iso"] = df["Time"].map(yyyymm_to_iso)
        df["val"] = num(df[vcol])
        out = {}
        for cls, g in df.groupby("Class"):
            out[cls] = {i: v for i, v in zip(g["iso"], g["val"]) if i and pd.notna(v)}
        return out

    pmap, rmap, ymap = to_map(price), to_map(rent), to_map(yld)
    pmap_a, rmap_a = to_map(price_a), to_map(rent_a)

    def series(qmap, amap, cls):
        m = qmap.get(cls) or {}
        return m if m else (amap.get(cls) or {})   # annual fallback when quarterly is empty

    periods = sorted({iso for m in pmap.values() for iso in m if iso})
    classes = {}
    for cls in CLASS_ORDER:
        pm, rm, ym = series(pmap, pmap_a, cls), series(rmap, rmap_a, cls), ymap.get(cls, {})
        if not pm and not rm:
            continue
        classes[cls] = {
            "price": [_r(pm.get(p), ROUND_IDX) for p in periods],
            "rent": [_r(rm.get(p), ROUND_IDX) for p in periods],
            "yield": [_r(ym.get(p), ROUND_YIELD) for p in periods],
        }
    return {
        "periods": periods,
        "classes": classes,
        "default_class": DEFAULT_CLASS,
        "family_classes": FAMILY_CLASSES,
        "class_order": [c for c in CLASS_ORDER if c in classes],
    }


def _r(v, nd):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return round(float(v), nd)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------- average $ price / rent
def build_avg_price_rent() -> dict:
    """Actual average price (11) and rent (10) by class x region (HK Is / Kln / NT)."""
    ap = load_csv("(11)")
    ar = load_csv("(10)")

    def latest_matrix(df, vname):
        df = df.copy()
        df["val"] = num(df[df.columns[-1]])
        df["iso"] = df["Time"].map(yyyymm_to_iso)
        latest = df["iso"].max()
        cur = df[df["iso"] == latest]
        regions = [r for r in ["Hong Kong", "Kowloon", "New Territories"] if r in set(df["Region"])]
        mat = {}
        for reg in regions:
            g = cur[cur["Region"] == reg]
            mat[REGION_EN.get(reg, reg)] = {
                cls: _r(v, 0) for cls, v in zip(g["Class"], g["val"])
            }
        return latest, regions, mat

    lp, regions, price_mat = latest_matrix(ap, "price")
    lr, _, rent_mat = latest_matrix(ar, "rent")

    # Time series of average price for the family default class, per region.
    ap = ap.copy()
    ap["val"] = num(ap[ap.columns[-1]])
    ap["iso"] = ap["Time"].map(yyyymm_to_iso)
    fam = ap[ap["Class"] == DEFAULT_CLASS]
    periods = sorted(fam["iso"].dropna().unique().tolist())
    series = {}
    for reg in regions:
        g = fam[fam["Region"] == reg]
        m = dict(zip(g["iso"], g["val"]))
        series[REGION_EN.get(reg, reg)] = [_r(m.get(p), 0) for p in periods]

    return {
        "latest_period": lp,
        "regions_en": [REGION_EN.get(r, r) for r in regions],
        "classes": [c for c in CLASS_ORDER if c in set(load_csv("(11)")["Class"])],
        "price_matrix": price_mat,
        "rent_matrix": rent_mat,
        "series_class": DEFAULT_CLASS,
        "series_periods": periods,
        "series_price": series,
    }


# --------------------------------------------------------------- districts (first-hand launches)
def _find_col(cols, *keywords):
    for c in cols:
        name = str(c)
        if all(k in name for k in keywords):
            return c
    return None


def _districts_from_regions() -> dict:
    """Official live fallback when no first-hand register data is present:
    RVD average price for family flats, by broad region (HK Island / Kowloon / NT)."""
    ap = load_csv("(11)").copy()
    ap["val"] = num(ap[ap.columns[-1]])
    ap["iso"] = ap["Time"].map(yyyymm_to_iso)
    latest = ap["iso"].max()
    cur = ap[(ap["iso"] == latest) & (ap["Class"] == DEFAULT_CLASS)]
    rows = []
    for reg in ["Hong Kong", "Kowloon", "New Territories"]:
        g = cur[cur["Region"] == reg]
        if len(g) and pd.notna(g["val"].iloc[0]):
            rows.append({"district": REGION_EN.get(reg, reg), "region": REGION_EN.get(reg, reg),
                         "avg_psf": _r(g["val"].iloc[0] / 10.7639, 0),  # HK$/m² → HK$/sq.ft
                         "units": None, "sold": None, "remaining": None, "sold_pct": None, "projects": 0})
    return {"by_district": rows, "areas": [], "totals": {"mode": "regions"},
            "source": f"Official RVD average price, family flats (70–100 m²), by broad region · "
                      f"{latest[:7] if latest else ''} — interim while the 18-district new-launch "
                      f"feed (SRPE first-hand register) is wired up"}


def build_districts() -> dict:
    """New-launch primary market by district from (17): avg $/sqft, units, remaining.

    Interim 'where to buy' geographic view. Falls back to the official RVD
    3-region average when no first-hand register file is present.
    """
    try:
        df = load_csv("(17)")
    except FileNotFoundError:
        return _districts_from_regions()
    cols = list(df.columns)
    c_district = _find_col(cols, "地區")
    c_region = _find_col(cols, "區域")
    c_units = _find_col(cols, "單位總數")
    c_sold = _find_col(cols, "累沽", "伙") or _find_col(cols, "累沽 ")
    c_remain = _find_col(cols, "餘貨")
    c_psf = _find_col(cols, "呎價")
    c_proj = _find_col(cols, "項目")

    df = df.copy()
    df["_units"] = num(df[c_units]) if c_units else pd.NA
    df["_sold"] = num(df[c_sold]) if c_sold else pd.NA
    df["_remain"] = num(df[c_remain]) if c_remain else pd.NA
    df["_psf"] = num(df[c_psf]) if c_psf else pd.NA
    df["_area"] = df[c_district].astype(str)
    df["_official"] = df["_area"].map(area_district)

    def agg(g):
        units = g["_units"].sum(min_count=1)
        sold = g["_sold"].sum(min_count=1)
        remain = g["_remain"].sum(min_count=1)
        priced = g.dropna(subset=["_psf"])
        pw = priced["_units"].sum(min_count=1)
        if len(priced) and pw:
            psf = (priced["_psf"] * priced["_units"]).sum() / pw   # unit-weighted $/sqft
        elif len(priced):
            psf = priced["_psf"].mean()
        else:
            psf = None
        return units, sold, remain, psf

    def row(name, region, g):
        units, sold, remain, psf = agg(g) if len(g) else (None, None, None, None)
        return {
            "district": name, "region": region,
            "avg_psf": _r(psf, 0), "units": _r(units, 0), "sold": _r(sold, 0),
            "remaining": _r(remain, 0),
            "sold_pct": _r((sold / units * 100) if units else None, 0),
            "projects": int(len(g)),
        }

    # Granular launch areas (English), sorted by $/sqft
    areas = []
    for area, g in df.groupby("_area"):
        if not area.strip() or area == "nan":
            continue
        r = row(area_en(area), REGION_EN.get(str(g[c_region].iloc[0]), str(g[c_region].iloc[0])) if c_region else "", g)
        r["area_cn"] = area
        r["official_district"] = area_district(area)
        areas.append(r)
    areas.sort(key=lambda r: (r["avg_psf"] is None, -(r["avg_psf"] or 0)))

    # Official 18-district roll-up (all 18 present; null where no current launches)
    by_district = [row(name, region, df[df["_official"] == name]) for name, region in DISTRICTS_18]

    totals = {
        "mode": "secondhand",
        "units": _r(df["_units"].sum(min_count=1), 0),        # total transactions in the sample
        "sold": _r(df["_sold"].sum(min_count=1), 0),
        "remaining": _r(df["_remain"].sum(min_count=1), 0),
        "projects": int(len(df)),
        "areas": len(areas),
        "districts_with_data": int(sum(1 for d in by_district if d["avg_psf"] is not None)),
        "unmapped_areas": sorted(set(df.loc[df["_official"].isna(), "_area"]) - {"nan", ""}),
    }
    return {"by_district": by_district, "areas": areas, "totals": totals,
            "source": "Centaline second-hand transaction records — median saleable HK$/sq.ft by district (recent ~30 days)"}


# --------------------------------------------------------------- estates (second-hand, by district)
def build_estates() -> dict:
    """Per-estate second-hand medians from (18), grouped under each official
    English district. Powers the district → estate drill-down. Absent file →
    FileNotFoundError, handled by safe() so the rest of the build proceeds."""
    df = load_csv("(18)")
    cols = list(df.columns)
    c_dist = _find_col(cols, "地區")
    c_estate_en = _find_col(cols, "屋苑英文")   # match the longer name before the substring "屋苑"
    c_estate = next((c for c in cols if "屋苑" in str(c) and c != c_estate_en), None)
    c_built = _find_col(cols, "落成")
    c_deals = _find_col(cols, "成交宗數")
    c_psf = _find_col(cols, "中位呎價")
    c_price = _find_col(cols, "中位售價")
    c_amin = _find_col(cols, "最細面積")
    c_amax = _find_col(cols, "最大面積")
    c_url = _find_col(cols, "細節連結")

    by_district: dict[str, list] = {}
    for _, r in df.iterrows():
        en = area_district(str(r[c_dist]))
        if not en:
            continue
        name_cn = str(r[c_estate]).strip()
        if not name_cn or name_cn == "nan":
            continue
        built = num(pd.Series([r[c_built]])).iloc[0] if c_built else None
        # Official English from the Centaline EN pass; fall back to the curated map.
        api_en = str(r[c_estate_en]).strip() if c_estate_en and pd.notna(r[c_estate_en]) else ""
        name_en = api_en or estate_en(name_cn)
        est = {
            "name": name_cn,
            "name_en": name_en or None,
            "built": int(built) if pd.notna(built) else None,
            "deals": _r(num(pd.Series([r[c_deals]])).iloc[0], 0),
            "psf": _r(num(pd.Series([r[c_psf]])).iloc[0], 0),
            "price": _r(num(pd.Series([r[c_price]])).iloc[0], 0),
            "area_min": _r(num(pd.Series([r[c_amin]])).iloc[0], 0),
            "area_max": _r(num(pd.Series([r[c_amax]])).iloc[0], 0),
            "url": str(r[c_url]).strip() if c_url and pd.notna(r[c_url]) else "",
        }
        by_district.setdefault(en, []).append(est)

    total_estates = sum(len(v) for v in by_district.values())
    total_deals = int(sum(e["deals"] or 0 for v in by_district.values() for e in v))

    # Keep each district's most-traded estates and drop the long single-deal tail
    # (a 1-deal median is noise, and 2,000+ estates bloat the offline payload).
    for name, lst in by_district.items():
        lst.sort(key=lambda e: (-(e["deals"] or 0), -(e["psf"] or 0)))
        by_district[name] = lst[:MAX_ESTATES_PER_DISTRICT]

    shown_estates = sum(len(v) for v in by_district.values())
    totals = {
        "estates": shown_estates,
        "estates_total": total_estates,   # before the per-district cap
        "deals": total_deals,
        "districts": len(by_district),
        "cap": MAX_ESTATES_PER_DISTRICT,
    }
    return {
        "by_district": by_district,
        "regions": {name: DISTRICT_REGION.get(name, "") for name in by_district},
        "totals": totals,
        "source": "Centaline second-hand transactions grouped by estate (recent ~30 days). "
                  "A median over few deals is noisy — always read it with the transaction count.",
    }


# --------------------------------------------------------------- transaction volume
def build_volume() -> dict:
    df = load_csv("(15)", "agreements")
    df = df.copy()
    df["iso"] = df["Period"].map(yyyymm_to_iso)
    df["val"] = num(df["Value"])
    periods = sorted(df["iso"].dropna().unique().tolist())

    def series_for(type_key):
        g = df[df["Type"].str.contains(type_key, case=False, na=False)]
        m = dict(zip(g["iso"], g["val"]))
        return [_r(m.get(p), 0) for p in periods]

    return {"periods": periods, "primary": series_for("Prim"), "secondary": series_for("Second")}


# --------------------------------------------------------------- supply / vacancy
def build_supply() -> dict:
    comp = load_csv("(9)", "completions")
    vac = load_csv("(9)", "vacancy")

    def total_units(df):
        col = _find_col(df.columns, "Total", "No. of units")
        return dict(zip(df["Year"].astype(int), num(df[col])))

    def total_pct(df):
        col = _find_col(df.columns, "Total", "% of stock")
        return dict(zip(df["Year"].astype(int), num(df[col])))

    comp_u = total_units(comp)
    vac_pct = total_pct(vac)
    years = sorted(set(comp_u) | set(vac_pct))

    def vac_disp(v):
        if v is None or pd.isna(v) or v <= 0:
            return None
        return round(v * 100, 2) if v < 1 else round(v, 2)

    return {
        "years": years,
        "completions": [_r(comp_u.get(y), 0) for y in years],
        "vacancy_pct": [vac_disp(vac_pct.get(y)) for y in years],
    }


# --------------------------------------------------------------- macro (HIBOR, HSI)
def build_macro() -> dict:
    def monthly(prefix, contains, datecol="Date"):
        df = load_csv(prefix, contains)
        df = df.copy()
        df[datecol] = pd.to_datetime(df[datecol], errors="coerce")
        df["val"] = num(df[df.columns[-1]])
        df = df.dropna(subset=[datecol]).set_index(datecol).sort_index()
        m = df["val"].resample("MS").mean().dropna()
        return [d.strftime("%Y-%m-01") for d in m.index], [_r(v, 3) for v in m.values]

    hib_d, hib_v = monthly("(5)", "hibor")
    try:
        hsi_d, hsi_v = monthly("(6)", "hang")   # optional; not charted in the current UI
    except FileNotFoundError:
        hsi_d, hsi_v = [], []
    return {"hibor": {"dates": hib_d, "values": hib_v},
            "hsi": {"dates": hsi_d, "values": hsi_v}}


# --------------------------------------------------------------- headline KPIs
def build_kpis(pri: dict, vol: dict, macro: dict) -> list:
    kpis = []
    per = pri["periods"]
    allc = pri["classes"].get("All Classes", {})

    def last_valid(arr):
        for i in range(len(arr) - 1, -1, -1):
            if arr[i] is not None:
                return i, arr[i]
        return None, None

    if allc:
        pidx = allc["price"]
        i, latest = last_valid(pidx)
        if i is not None:
            qoq = _pct(latest, pidx[i - 1]) if i >= 1 else None
            yoy = _pct(latest, pidx[i - 4]) if i >= 4 else None
            kpis.append({"label": "Home price index (All classes)", "value": latest,
                         "sub": _trend_sub(qoq, "QoQ"), "yoy": yoy, "period": per[i]})
        ridx = allc["rent"]
        j, rlatest = last_valid(ridx)
        if j is not None:
            ryoy = _pct(rlatest, ridx[j - 4]) if j >= 4 else None
            kpis.append({"label": "Rent index (All classes)", "value": rlatest,
                         "sub": _trend_sub(ryoy, "YoY"), "yoy": ryoy, "period": per[j]})
        yld = allc["yield"]
        k, ylatest = last_valid(yld)
        if k is not None:
            kpis.append({"label": "Gross rental yield", "value": ylatest, "unit": "%",
                         "sub": "All classes, latest", "period": per[k]})

    hv = macro["hibor"]["values"]
    if hv:
        kpis.append({"label": "1M HIBOR (mortgage cost)", "value": hv[-1], "unit": "%",
                     "sub": macro["hibor"]["dates"][-1][:7]})

    if vol["periods"]:
        p = vol["primary"][-1]
        s = vol["secondary"][-1]
        kpis.append({"label": "Transactions (latest qtr)",
                     "value": (int(p or 0) + int(s or 0)),
                     "sub": f"{int(p or 0):,} primary · {int(s or 0):,} secondary",
                     "period": vol["periods"][-1]})
    return kpis


def _trend_sub(pct, tag):
    if pct is None:
        return tag
    arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "▬")
    return f"{arrow} {abs(pct)}% {tag}"


def safe(fn, default, label):
    """Optional sections (volume, districts, supply) shouldn't crash the whole build
    if their source file is absent — return an empty shape and carry on."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        print(f"  · {label}: no data ({type(e).__name__}) — leaving empty")
        return default


def main():
    print("Building site data JSON from data/clean/ ...")
    pri = build_price_rent_index()
    avg = build_avg_price_rent()
    dist = safe(build_districts, {"by_district": [], "areas": [], "totals": {}, "source": "live source pending"}, "districts")
    est = safe(build_estates, {"by_district": {}, "regions": {}, "totals": {}, "source": "estate data pending"}, "estates")
    vol = safe(build_volume, {"periods": [], "primary": [], "secondary": []}, "volume")
    sup = safe(build_supply, {"years": [], "completions": [], "vacancy_pct": []}, "supply")
    macro = build_macro()
    kpis = build_kpis(pri, vol, macro)

    _write("price_rent_index.json", pri)
    _write("avg_price_rent.json", avg)
    _write("districts.json", dist)
    _write("estates.json", est)
    _write("volume.json", vol)
    _write("supply.json", sup)
    _write("macro.json", macro)
    _write("kpis.json", kpis)
    _write("meta.json", {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_through": pri["periods"][-1] if pri["periods"] else None,
        "districts_source": dist["source"],
        "estates_source": est.get("source"),
        "notes": "Price/rent indices are RVD by flat-size class (data through the latest published "
                 "quarter). District and estate $/sq.ft are Centaline second-hand transaction "
                 "medians over roughly the last 30 days — read them with the transaction count.",
    })
    print("Done.")


if __name__ == "__main__":
    main()
