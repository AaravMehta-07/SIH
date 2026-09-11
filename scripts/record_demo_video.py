"""Judge demonstration video (Section 30): a real screen recording of the
FORESIGHT console executing the complete demonstration flow.

Records the actual browser — the real trained bundle, real forecasts, real
reveal — with deliberate pacing for a 90-110 second walkthrough:

    sessions -> open capture -> workspace (entity risk, network, ETA, novelty)
    -> horizon change -> evidence attribution -> sealed replay + REVEAL
    (predicted vs actual with advance warning) -> evaluation gates
    -> attack-path hypotheses.

Output: artifacts/demo/foresight-demo.webm (mp4 if ffmpeg is available).

    python scripts/record_demo_video.py [--base http://127.0.0.1:8001]
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "artifacts" / "demo"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8001")
    parser.add_argument("--catalog-id", default=None)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    args = parser.parse_args()
    base = args.base.rstrip("/")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport={"width": args.width, "height": args.height},
            record_video_dir=str(OUT_DIR),
            record_video_size={"width": args.width, "height": args.height},
        )
        page = context.new_page()
        page.on("pageerror", lambda e: print("PAGE ERROR:", str(e)[:200]))

        # 1. entry: the catalog (real + synthetic captures)
        page.goto(base, wait_until="networkidle")
        page.wait_for_selector(".catalog-card", timeout=60000)
        time.sleep(7.0)

        catalog_id = args.catalog_id or "demo-02"
        card = page.locator(".catalog-card", has_text="Web compromise")
        if card.count() == 0:
            card = page.locator(".catalog-card").first
        # 2. open the capture -> workspace
        card.locator("button", has_text="Open session").click()
        page.wait_for_selector(".task-row", timeout=180000)
        time.sleep(8.0)

        # 3. select the compromised host (web server) — inspection panel
        page.locator(".entity-row", has_text="web-01").first.click()
        time.sleep(8.0)

        # 4. switch horizon to 30 min — trajectory change
        page.locator(".horizon-tabs button", has_text="30 min").click()
        time.sleep(6.0)

        # 5. evidence: deletion-tested attribution
        page.locator(".nav button", has_text="Evidence").click()
        page.wait_for_selector(".tiles", timeout=120000)
        time.sleep(10.0)

        # 6. sealed replay: commitment theater + REVEAL
        page.locator(".nav button", has_text="Replay").click()
        page.wait_for_selector(".theater", timeout=60000)
        time.sleep(8.0)
        page.locator("button", has_text="Reveal future").click()
        page.wait_for_selector(".pva-board", timeout=120000)
        time.sleep(10.0)

        # 7. evaluation: honest gates
        page.locator(".nav button", has_text="Evaluation").click()
        page.wait_for_selector("text=Golden contract check", timeout=60000)
        time.sleep(8.0)

        # 8. attack-path hypotheses
        page.locator(".nav button", has_text="Paths").click()
        page.wait_for_selector(".paths-list", timeout=60000)
        time.sleep(8.0)

        # 9. close on the workspace
        page.locator(".nav button", has_text="Forecast").click()
        time.sleep(5.0)

        video = page.video.path()
        context.close()
        browser.close()

    src = Path(video)
    webm = OUT_DIR / "foresight-demo.webm"
    shutil.move(str(src), webm)
    print(f"video -> {webm} ({webm.stat().st_size / 1e6:.1f} MB)")

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        mp4 = OUT_DIR / "foresight-demo.mp4"
        result = subprocess.run(
            [ffmpeg, "-y", "-i", str(webm), "-c:v", "libx264",
             "-pix_fmt", "yuv420p", "-preset", "slow", "-crf", "17", str(mp4)],
            capture_output=True, text=True,
        )
        if result.returncode == 0 and mp4.exists():
            print(f"mp4  -> {mp4} ({mp4.stat().st_size / 1e6:.1f} MB)")
        else:
            print("ffmpeg conversion failed; webm retained")
    else:
        print("ffmpeg not found; webm retained (browsers play webm natively)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
