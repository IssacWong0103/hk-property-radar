"""One-off: build the compact 18-district outline the map view draws.

District boundaries don't change, so this is NOT part of run_all — run it by hand
if you ever need to refresh the shape:

    python pipeline/fetch_boundaries.py

Source: the `dc_land` District Council LAND boundaries from the open-source
geohk project (github.com/hupili/geohk, census-2001 base). We deliberately use the
LAND version, not the Home Affairs Dept "administrative" boundary: the latter
extends each district out to its sea limit, so filling the polygons paints the
whole harbour and open water and the result reads as a shapeless blob — no islands,
no Victoria Harbour. `dc_land` is clipped to the coastline, so Hong Kong Island,
Kowloon, Lantau and the outlying islands are all recognisable.

The raw file is ~210 KB. We simplify it (Ramer–Douglas–Peucker + coordinate
rounding, pure Python, no geo deps), keeping the islands that make the territory
recognisable and dropping only specks, then emit a slim custom shape file to
site/data/districts_geo.json for app.js to project to SVG.
"""
from __future__ import annotations

import json
import os
import urllib.request

from common import SITE_DATA_DIR

SRC = ("https://raw.githubusercontent.com/hupili/geohk/master/"
       "census2001/dc_land.lowres.geo.json")

TOLERANCE = 0.0004     # RDP tolerance in degrees (~44 m) — keeps island outlines legible
PRECISION = 4          # decimal places kept (~11 m)
MIN_RING_AREA = 1.5e-6  # drop specks below this; always keep a district's largest ring
MAX_RINGS = 40         # HK is an archipelago — keep the significant outlying islands


def _perp(pt, a, b):
    (x, y), (x1, y1), (x2, y2) = pt, a, b
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
    t = ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    px, py = x1 + t * dx, y1 + t * dy
    return ((x - px) ** 2 + (y - py) ** 2) ** 0.5


def rdp(points, eps):
    """Ramer–Douglas–Peucker line simplification."""
    if len(points) < 3:
        return points[:]
    dmax, idx = 0.0, 0
    for i in range(1, len(points) - 1):
        d = _perp(points[i], points[0], points[-1])
        if d > dmax:
            dmax, idx = d, i
    if dmax > eps:
        left = rdp(points[:idx + 1], eps)
        right = rdp(points[idx:], eps)
        return left[:-1] + right
    return [points[0], points[-1]]


def ring_area(ring):
    """Absolute shoelace area (degrees²) — only used for relative size ranking."""
    s = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def outer_rings(geom):
    """Yield the outer ring of each polygon (holes dropped — invisible in a fill)."""
    t, coords = geom["type"], geom["coordinates"]
    if t == "Polygon":
        yield coords[0]
    elif t == "MultiPolygon":
        for poly in coords:
            yield poly[0]


def simplify_feature(feat):
    rings = []
    for ring in outer_rings(feat["geometry"]):
        pts = [(round(x, PRECISION), round(y, PRECISION)) for x, y in ring]
        simp = rdp(pts, TOLERANCE)
        if len(simp) >= 4:
            rings.append((ring_area(simp), simp))
    if not rings:
        return None
    rings.sort(key=lambda r: -r[0])
    biggest = rings[0][0]
    kept = [r for i, (a, r) in enumerate(rings)
            if i == 0 or (a >= MIN_RING_AREA and i < MAX_RINGS)]
    return kept


def main():
    print("Fetching HAD 18-district boundary …")
    with urllib.request.urlopen(SRC, timeout=60) as r:
        gj = json.loads(r.read().decode("utf-8", "replace"))

    out = []
    minx = miny = 1e9
    maxx = maxy = -1e9
    for feat in gj["features"]:
        p = feat["properties"]
        rings = simplify_feature(feat)
        if not rings:
            print(f"  ! {p.get('District')} produced no rings — skipped")
            continue
        for ring in rings:
            for x, y in ring:
                minx, miny = min(minx, x), min(miny, y)
                maxx, maxy = max(maxx, x), max(maxy, y)
        out.append({
            "code": p.get("DC_CODE"),
            "name": p.get("DC_ENG"),
            "name_cn": p.get("DC_CHIN"),
            # flatten each ring to [x0,y0,x1,y1,…] to shave JSON bytes
            "rings": [[c for pt in ring for c in pt] for ring in rings],
        })

    doc = {"bbox": [round(minx, PRECISION), round(miny, PRECISION),
                    round(maxx, PRECISION), round(maxy, PRECISION)],
           "districts": out}
    os.makedirs(SITE_DATA_DIR, exist_ok=True)
    path = os.path.join(SITE_DATA_DIR, "districts_geo.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    pts = sum(len(r) // 2 for d in out for r in d["rings"])
    print(f"  wrote districts_geo.json — {len(out)} districts, {pts:,} points, "
          f"{os.path.getsize(path):,} bytes")


if __name__ == "__main__":
    main()
