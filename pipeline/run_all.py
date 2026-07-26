"""Orchestrator run by GitHub Actions on a schedule.

Order: (1) fetch + convert latest RVD data → CSVs [optional until converters land],
(2) build the site JSON, (3) refresh the AI news feed, (4) send the email brief
[only if enabled + creds present]. Each stage is guarded so one failure does not
sink the others — a partial refresh still ships.
"""
from __future__ import annotations

import importlib
import sys
import traceback


def stage(label: str, module: str, optional: bool = False) -> bool:
    try:
        mod = importlib.import_module(module)
    except ImportError:
        if optional:
            print(f"· skip {label} ({module} not present yet)")
            return True
        print(f"✗ {label}: cannot import {module}")
        return False
    try:
        print(f"▶ {label} …")
        mod.main()
        return True
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        print(f"✗ {label} failed:\n{traceback.format_exc()}")
        return False


def main() -> int:
    ok = True
    # 1) Self-source the latest official data from the internet (RVD + HKMA).
    #    If the network hiccups, the build below still runs on the last-good CSVs.
    stage("fetch RVD + HKMA data", "fetch_rvd")
    stage("fetch Land Registry transaction volume", "fetch_landreg", optional=True)
    stage("fetch 18-district second-hand prices (Centaline)", "fetch_centaline", optional=True)
    # 2) Rebuild the dashboard JSON from data/clean/
    ok &= stage("build site data", "build_figures")
    # 3) Refresh the news feed (works with or without a DeepSeek key)
    stage("news RAG", "news_rag")
    # 4) Email brief — only acts if subscribers + creds exist
    stage("email brief", "send_email", optional=True)
    print("done." if ok else "done with errors.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
