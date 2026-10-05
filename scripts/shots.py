"""Headless screenshots of a running Orderdesk (default http://127.0.0.1:8000). Sends one demo order.

    python scripts/shots.py [--base URL] [--out DIR]
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--out", default="docs/images")
    ap.add_argument("--password", default="orderdesk-demo")
    ap.add_argument("--dark", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1600, "height": 940}, color_scheme="dark" if a.dark else "light")
        page.goto(a.base + "/login")
        page.screenshot(path=out / "login.png")
        page.get_by_role("button", name="Sign in as Maria").click()
        page.wait_for_selector(".desk")
        page.get_by_role("button", name="Retailer phone (demo)").click()
        page.wait_for_selector(".phone")
        page.get_by_role("button", name="Roman Urdu").click() if page.get_by_role("button", name="Roman Urdu").count() else page.locator(".phone-samples .btn").first.click()
        page.get_by_role("button", name="Send", exact=True).click()
        page.wait_for_selector(".queue-item", timeout=90_000)
        time.sleep(1)
        page.locator(".queue-item").first.click()
        page.wait_for_selector(".pad-line", timeout=30_000)
        page.locator(".pad-line").first.hover()
        time.sleep(0.5)
        page.screenshot(path=out / ("desk-dark.png" if a.dark else "desk.png"))
        b.close()


if __name__ == "__main__":
    main()
