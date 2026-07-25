"""Shared helpers for the HK Property Radar pipeline.

Paths, CSV lookup, value cleaning (reused by the headless RVD converters),
and the canonical flat-class ordering used across the dashboard.
"""
from __future__ import annotations

import glob
import os
import re

import pandas as pd

# ---------------------------------------------------------------- paths
PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(PIPELINE_DIR)
CLEAN_DIR = os.path.join(REPO_ROOT, "data", "clean")          # cleaned CSVs (seed + converter output)
SITE_DATA_DIR = os.path.join(REPO_ROOT, "site", "data")       # generated JSON the site reads


def _load_dotenv():
    """Load a local .env (gitignored) into the environment for local runs.
    No dependency; real env vars (e.g. GitHub Actions secrets) always win."""
    path = os.path.join(REPO_ROOT, ".env")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


# ---------------------------------------------------------------- flat classes
# RVD private-domestic size bands (Class A–E) plus the aggregate rows.
CLASS_ORDER = [
    "Less than 40 m2",       # Class A
    "40 m2 to 69.9 m2",      # Class B
    "70 m2 to 99.9 m2",      # Class C
    "100 m2 to 159.9 m2",    # Class D
    "160 m2 or above",       # Class E
    "Less than 100 m2",
    "100 m2 or above",
    "All Classes",
]
# Sizes a family would realistically consider (Class C+).
FAMILY_CLASSES = ["70 m2 to 99.9 m2", "100 m2 to 159.9 m2", "160 m2 or above"]
DEFAULT_CLASS = "70 m2 to 99.9 m2"

# English labels for RVD broad areas and (17) first-hand regions.
REGION_EN = {
    "Hong Kong": "HK Island",
    "Kowloon": "Kowloon",
    "New Territories": "New Territories",
    "港島": "HK Island",
    "九龍": "Kowloon",
    "新界": "New Territories",
    "Urban": "Urban",
    "N.T.": "New Territories",
    "All": "All HK",
}


def find_csv(prefix: str, contains: str | None = None) -> str | None:
    """Return the path of a cleaned CSV by its numeric prefix, e.g. find_csv('(13)').

    Tolerant of the messy real filenames ('(13)Quarterly_Price.csv') and slight
    renames, so the pipeline does not break when a file is re-exported.
    """
    pats = sorted(glob.glob(os.path.join(CLEAN_DIR, f"{prefix}*.csv")))
    if contains:
        pats = [p for p in pats if contains.lower() in os.path.basename(p).lower()]
    return pats[0] if pats else None


def load_csv(prefix: str, contains: str | None = None) -> pd.DataFrame:
    path = find_csv(prefix, contains)
    if not path:
        raise FileNotFoundError(f"No cleaned CSV matching prefix {prefix!r} (contains={contains!r}) in {CLEAN_DIR}")
    # utf-8-sig strips the BOM the converters write.
    return pd.read_csv(path, encoding="utf-8-sig")


def yyyymm_to_iso(v) -> str | None:
    """'199903' -> '1999-03-01' (first of the quarter-end month). None if unparseable."""
    s = re.sub(r"\D", "", str(v))
    if len(s) == 6:
        return f"{s[:4]}-{s[4:6]}-01"
    if len(s) == 4:
        return f"{s}-12-01"
    return None


def num(series) -> pd.Series:
    """Coerce a column (which may contain '' for missing) to float."""
    return pd.to_numeric(series, errors="coerce")


def clean_val(val):
    """Excel cell -> clean number/str/''  (reused by the headless RVD converters).

    Mirrors the logic from the original tkinter converters: handles dashes,
    provisional values in parentheses, and NaN.
    """
    try:
        f_val = float(val)
        if pd.isna(f_val):
            return ""
        return int(f_val) if float(f_val).is_integer() else f_val
    except (TypeError, ValueError):
        s_val = str(val).strip()
        if s_val in ["-", "–", "—", "nan", "NaN", "NA", "na", ""]:
            return ""
        s_val = s_val.replace("(", "").replace(")", "").strip()
        try:
            return float(s_val)
        except ValueError:
            return s_val
