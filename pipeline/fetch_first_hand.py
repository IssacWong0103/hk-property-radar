"""Self-source the 18-district NEW-LAUNCH view from the government's first-hand
sales platform (SRPE), writing data/clean/(17)*.csv for build_figures.

STATUS: scaffold. Until implemented, build_figures falls back to the official
RVD 3-region average (see build_figures._districts_from_regions), so the app
stays live and CITIC-free. main() is a safe no-op so the pipeline never breaks.

── What was discovered (entry points for the scraper) ──────────────────────────
The SRPE is a JS SPA backed by a web service. From its JS bundle:
  • API base:   https://www.srpe.gov.hk/api/SrpeWebService
  • Routes incl: /all_development , /all_development_t18m ,
                 /district_search , /district_area_search[_result] ,
                 /selected_dev_search_residential_development_all_sb ,
                 /year_search[_result]
Each first-hand development exposes a **Register of Transactions** (成交紀錄冊) and
**Price Lists**; the register gives, per transaction, the price + saleable area
(→ HK$/sq.ft) and lets us count sold units; the development record gives its
District (→ map to the 18 districts via districts_en.AREA / DISTRICTS_18).

── Build plan (next step) ───────────────────────────────────────────────────────
1. Call the web service to enumerate active residential developments
   (district_search / all_development), capturing name, developer, district,
   total units.
2. For each, fetch its Register of Transactions; compute unit-weighted avg
   HK$/sq.ft, sold count, remaining = total - sold.
3. Map each development's district → one of the 18 (reuse pipeline/districts_en).
4. Write data/clean/(17)Sales_progress...csv with columns matching build_districts
   (地區/區域/單位總數/累沽/餘貨/首張價單平均折實呎價) OR emit tidy rows directly.
Note: external gov navigation was blocked in this environment, so the exact
request envelope for /api/SrpeWebService still needs to be captured (browser
devtools on srpe.gov.hk, or the JS bundle's request builder).
"""
from __future__ import annotations

SRPE_API = "https://www.srpe.gov.hk/api/SrpeWebService"


def main():
    # No-op until the SRPE request schema is captured. The dashboard uses the
    # official RVD 3-region fallback in the meantime (fully live, CITIC-free).
    print("  (fetch_first_hand: scaffold — using official RVD region fallback for districts)")


if __name__ == "__main__":
    main()
