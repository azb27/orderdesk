"""Record the README demo: an Arabizi WhatsApp order becomes a draft, is confirmed, posts to the ERP and gets a
reply; then a photo of a handwritten list. Needs a running Orderdesk with a model key (it spends about $0.05).

    python scripts/demo_video.py [--base URL] [--out docs/images/demo.gif]

Writes a .webm with Playwright, then a palette-optimised GIF with ffmpeg.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

W, H = 1600, 900


def pause(s: float) -> None:
    time.sleep(s)


def arabizi_customer(base: str, page: Page) -> str:
    cookies = "; ".join(f"{c['name']}={c['value']}" for c in page.context.cookies())
    req = urllib.request.Request(base + "/api/simulator/customers", headers={"Cookie": cookies})
    custs = json.loads(urllib.request.urlopen(req).read())
    return next(c["phone"] for c in custs if c["language"] == "arabizi")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--out", default="docs/images/demo.gif")
    ap.add_argument("--speed", type=float, default=1.8, help="playback speed-up for the GIF")
    a = ap.parse_args()
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": W, "height": H}, record_video_dir=tmp, record_video_size={"width": W, "height": H})
        page = ctx.new_page()
        page.goto(a.base + "/login")
        pause(1.2)
        page.get_by_role("button", name="Sign in as Maria").click()
        page.wait_for_selector(".desk")
        page.get_by_role("button", name="Retailer phone (demo)").click()
        phone = page.get_by_role("complementary", name="Retailer phone (demo)")
        phone.get_by_label("Sending as").select_option(arabizi_customer(a.base, page))
        pause(0.8)
        phone.get_by_role("button", name="Arabizi", exact=True).click()
        pause(1.5)
        phone.get_by_role("button", name="Send", exact=True).click()
        # the draft arrives by itself over server-sent events
        item = page.locator(".queue-item").first
        item.wait_for(timeout=90_000)
        pause(0.8)
        item.click()
        page.wait_for_selector(".pad-line")
        pause(1.0)
        for ln in page.locator(".pad-line").all()[:3]:
            ln.hover()
            pause(1.1)
        subs = page.locator(".pad-subs .pad-alt")
        if subs.count():  # out of stock: take the first substitute the draft offers
            subs.first.click()
            pause(1.5)
        page.keyboard.press("Enter")  # confirm
        page.wait_for_selector(".stamp", timeout=30_000)
        pause(2.5)
        phone.locator(".pbubble--them").first.wait_for(timeout=60_000)  # the templated reply, in Arabizi
        pause(2.0)
        # a photo of a handwritten list
        phone.get_by_role("button", name="Send handwritten list 1").click()
        page.get_by_role("button", name="To check").click()
        page.locator(".queue-item").first.wait_for(timeout=120_000)
        pause(0.8)
        page.locator(".queue-item").first.click()
        page.wait_for_selector(".pad-line")
        pause(1.0)
        for ln in page.locator(".pad-line").all()[:3]:
            ln.hover()
            pause(1.0)
        pause(1.5)
        video = page.video.path() if page.video else None
        ctx.close()
        b.close()
        assert video
        webm = out.with_suffix(".webm")
        Path(video).replace(webm)
    vf = f"setpts=PTS/{a.speed},fps=10,scale=1120:-1:flags=lanczos"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(webm), "-vf", f"{vf},palettegen=stats_mode=diff:max_colors=128", "/tmp/od_palette.png"], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(webm), "-i", "/tmp/od_palette.png",
                    "-lavfi", f"{vf}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle", str(out)], check=True)  # fmt: skip
    print(f"wrote {out} ({out.stat().st_size // 1024} KB) and {webm}")


if __name__ == "__main__":
    main()
