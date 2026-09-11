"""Programmatic layout verification (K.3): overflow at multiple widths,
chart rendering, element visibility and label collisions.

Complements the screenshots: every check here is an invariant, not a taste
judgment — no horizontal overflow, charts have drawn marks, panels stack,
and the timeline's direct labels do not collide.
"""

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8031"
OUT = Path(__file__).resolve().parents[1] / "artifacts" / "screens"

WIDTHS = [1440, 1180, 900, 640, 420]


def check_overflow(page) -> bool:
    return page.evaluate(
        "document.documentElement.scrollWidth > document.documentElement.clientWidth + 1"
    )


def main() -> int:
    failures = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(BASE, wait_until="networkidle")
        page.wait_for_selector(".catalog-card", timeout=30000)
        page.locator(".catalog-card", has_text="Web compromise").locator(
            "button", has_text="Open session"
        ).click()
        page.wait_for_selector(".tiles", timeout=60000)
        # the forecast payload must land before chart marks exist (the first
        # forecast on a cold server can outlive any fixed sleep)
        page.wait_for_selector("table.data tbody tr", timeout=120000)
        time.sleep(1.2)

        # Chart rendered with marks
        series_paths = page.locator("svg path[stroke]").count()
        if series_paths < 5:
            failures.append(f"timeline series paths = {series_paths} (expected >= 5)")
        legend_items = page.locator(".chart-legend .lg-item").count()
        if legend_items < 5:
            failures.append(f"legend items = {legend_items} (expected >= 5)")

        # Direct labels on the timeline must not collide
        labels = page.locator("svg text").all()
        boxes = []
        for l in labels:
            box = l.bounding_box()
            if box and l.text_content().strip() and len(l.text_content().strip()) > 3:
                boxes.append((box["x"], box["y"], box["width"], box["height"]))
        collisions = 0
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                if (a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and
                        a[1] < b[1] + b[3] and b[1] < a[1] + a[3]):
                    collisions += 1
        if collisions:
            failures.append(f"timeline label collisions: {collisions}")

        # Graph nodes rendered
        graph_nodes = page.locator("svg circle").count()
        if graph_nodes < 13:
            failures.append(f"graph circles = {graph_nodes} (expected >= 13)")

        # Overflow at every width across screens
        for width in WIDTHS:
            page.set_viewport_size({"width": width, "height": 900})
            time.sleep(0.5)
            for screen in ("Forecast", "Sessions", "Evaluation"):
                btn = page.locator(".nav button", has_text=screen)
                if btn.is_disabled():
                    continue
                btn.click()
                time.sleep(0.9)
                if check_overflow(page):
                    failures.append(f"horizontal overflow at {width}px on {screen}")
        page.set_viewport_size({"width": 1440, "height": 900})

        # Status strip carries the full Section-18 axes
        page.locator(".nav button", has_text="Forecast").click()
        time.sleep(0.8)
        axes = [t.strip() for t in page.locator(".axis-chip .axis").all_text_contents()]
        for expected in ("Forecast support", "Threat evidence", "Novelty", "Health", "Action authority"):
            if expected.upper() not in [a.upper() for a in axes]:
                failures.append(f"missing status axis: {expected}")

        # Keyboard: screen switching
        page.keyboard.press("5")
        time.sleep(0.6)
        if "Evaluation" not in page.locator(".nav button.active").text_content():
            failures.append("keyboard screen switching (key 5) failed")

        page.screenshot(path=str(OUT / "02-forecast.png"))
        browser.close()

    if errors:
        failures.extend(f"console error: {e[:120]}" for e in errors[:5])
    print("checks complete")
    for f in failures:
        print("FAIL:", f)
    print("PASS" if not failures else f"{len(failures)} FAILURES")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
