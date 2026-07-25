"""Self-source the dashboard's data from official Hong Kong internet endpoints.

No dependency on any local/prior dataset — every run downloads fresh from:
  • RVD open data  (rvd.gov.hk/datagovhk/*.csv)  — price/rent indices, avg $, stock/vacancy/completions
  • HKMA open API  (api.hkma.gov.hk)             — 1-month HIBOR (daily)

and writes tidy CSVs into data/clean/ in the schema build_figures.py expects.
Rental yield is derived (avg rent × 12 ÷ avg price). Run: python pipeline/fetch_rvd.py
"""
from __future__ import annotations

import io
import json
import os
import re
import urllib.request

import pandas as pd

from common import CLEAN_DIR

UA = {"User-Agent": "Mozilla/5.0 (HK-Property-Radar)"}
RVD = "http://www.rvd.gov.hk/datagovhk/"
HKMA = ("https://api.hkma.gov.hk/public/market-data-and-statistics/"
        "monthly-statistical-bulletin/er-ir/hk-interbank-ir-daily")

# official class column  ->  dashboard class label
CLASS_MAP = {
    "Class A": "Less than 40 m2", "Class B": "40 m2 to 69.9 m2", "Class C": "70 m2 to 99.9 m2",
    "Class D": "100 m2 to 159.9 m2", "Class E": "160 m2 or above",
    "Classes A, B & C": "Less than 100 m2", "Classes D & E": "100 m2 or above",
    "All Classes": "All Classes",
}
REGIONS = ["Hong Kong", "Kowloon", "New Territories"]


def get(url: str) -> str:
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=45).read().decode("utf-8", "replace")


def to_time(s: str):
    s = str(s).strip()
    if "/" in s:                                   # quarterly "10-12/1979"
        rng, yr = s.split("/"); return f"{yr}{rng.split('-')[1]}"
    if re.match(r"^\d{2}-\d{4}$", s):              # monthly "01-1993"
        m, y = s.split("-"); return f"{y}{m}"
    d = re.sub(r"\D", "", s)
    return d[:4] if len(d) >= 4 else None          # annual


def clean(v):
    s = str(v).strip()
    if s in ("-", "", "nan", "N/A", "Z", "z", "#"):
        return ""
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return ""


def _df(url: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(get(url)), skiprows=1, dtype=str)   # skip the title row
    return df.rename(columns={df.columns[0]: "period"})


def index_by_class(url: str) -> pd.DataFrame:
    df = _df(url)
    rows = []
    for off, label in CLASS_MAP.items():
        if off in df.columns:
            for _, r in df.iterrows():
                t = to_time(r["period"])
                if t:
                    rows.append((t, label, clean(r[off])))
    return pd.DataFrame(rows, columns=["Time", "Class", "Value"])


def avg_by_class_region(url: str) -> pd.DataFrame:
    df = _df(url)
    rows = []
    for col in df.columns:
        if col == "period" or "Remarks" in col:
            continue
        cls = next((c for c in CLASS_MAP if col.startswith(c)), None)
        reg = next((rg for rg in REGIONS if col.endswith(rg)), None)
        if not cls or not reg:
            continue
        for _, r in df.iterrows():
            t = to_time(r["period"])
            if t:
                rows.append((t, CLASS_MAP[cls], reg, clean(r[col])))
    return pd.DataFrame(rows, columns=["Time", "Class", "Region", "Value"])


def total_series(url: str, want: str) -> pd.DataFrame:
    """Year + the 'Total' column matching `want` ('unit' or 'pct')."""
    df = _df(url).rename(columns={"period": "Year"})
    cand = [c for c in df.columns if "total" in c.lower()]
    if want == "pct":
        col = next((c for c in cand if "%" in c), None)
    else:
        col = next((c for c in cand if "%" not in c), cand[0] if cand else None)
    out = pd.DataFrame({"Year": df["Year"].map(lambda s: re.sub(r"\D", "", str(s))[:4])})
    out["val"] = df[col].map(clean) if col else ""
    return out[out["Year"].str.len() == 4]


def hibor_1m() -> pd.DataFrame:
    """Daily 1-month HIBOR back to ~2016 (paginated, newest-first)."""
    rows, offset = [], 0
    for _ in range(30):
        j = json.loads(get(f"{HKMA}?segment=hibor.fixing&sortorder=desc&pagesize=100&offset={offset}"))
        recs = j.get("result", {}).get("records", [])
        if not recs:
            break
        for r in recs:
            if r.get("ir_1m") is not None:
                rows.append((r["end_of_day"], r["ir_1m"]))
        if recs[-1]["end_of_day"] < "2016-01-01":
            break
        offset += 100
    return pd.DataFrame(rows, columns=["Date", "HIBOR Rate"])


def derive_yield(price: pd.DataFrame, rent: pd.DataFrame) -> pd.DataFrame:
    """Gross rental yield % = avg monthly rent × 12 ÷ avg price × 100, averaged over regions."""
    p = price.rename(columns={"Value": "price"}); r = rent.rename(columns={"Value": "rent"})
    m = p.merge(r, on=["Time", "Class", "Region"])
    m["price"] = pd.to_numeric(m["price"], errors="coerce")
    m["rent"] = pd.to_numeric(m["rent"], errors="coerce")
    m = m[(m["price"] > 0) & (m["rent"] > 0)]
    m["y"] = m["rent"] * 12 / m["price"] * 100
    by_cls = m.groupby(["Time", "Class"])["y"].mean().reset_index()
    allc = by_cls.groupby("Time")["y"].mean().reset_index(); allc["Class"] = "All Classes"
    out = pd.concat([by_cls, allc], ignore_index=True).rename(columns={"y": "Value"})
    out["Value"] = out["Value"].round(2)
    return out[["Time", "Class", "Value"]]


def save(df: pd.DataFrame, name: str):
    df.to_csv(os.path.join(CLEAN_DIR, name), index=False, encoding="utf-8-sig")
    print(f"  wrote {name} ({len(df)} rows)")


def main():
    os.makedirs(CLEAN_DIR, exist_ok=True)
    print("Fetching official RVD + HKMA data …")

    save(index_by_class(RVD + "1.4Q.csv"), "(13)Quarterly_Price.csv")
    save(index_by_class(RVD + "1.4A.csv"), "(13)Annual_Price.csv")
    save(index_by_class(RVD + "1.3Q.csv"), "(12)Quarterly_Rents.csv")
    save(index_by_class(RVD + "1.3A.csv"), "(12)Annual_Rents.csv")

    ap = avg_by_class_region(RVD + "1.2Q(from_99).csv")
    ar = avg_by_class_region(RVD + "1.1Q(from_99).csv")
    save(ap.rename(columns={"Value": "Average Price"}), "(11)Quarterly_from99.csv")
    save(ar.rename(columns={"Value": "Average Rent"}), "(10)Quarterly_from99.csv")
    save(derive_yield(ap, ar), "(16)Quarterly_Domestic.csv")

    comp = total_series(RVD + "Private_Domestic-Completions.csv", "unit")
    save(comp.rename(columns={"val": "Total (No. of units)"}), "(9)Completions.csv")
    vac = total_series(RVD + "Private_Domestic-Vacancy.csv", "pct")
    save(vac.rename(columns={"val": "Total (% of stock)"}), "(9)Vacancy.csv")

    save(hibor_1m(), "(5)Combined_HIBOR_Data.csv")
    print("Done — data/clean refreshed from the internet.")


if __name__ == "__main__":
    main()
