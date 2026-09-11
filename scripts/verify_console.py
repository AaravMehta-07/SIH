"""Browser verification of the FORESIGHT console (K.3 interaction tests).

Drives the built console against the live API: opens each screen, captures
screenshots, collects console errors, and exercises the golden path (open
session -> forecast -> evidence -> reveal -> evaluation) plus edge cases
(narrow viewport, long host names are inherent to the corpus).
"""

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8031"
OUT = Path(__file__).resolve().parents[1] / "artifacts" / "screens"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> int:
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        # 1. sessions screen
        page.goto(BASE, wait_until="networkidle")
        page.wait_for_selector(".catalog-card", timeout=30000)
        time.sleep(0.6)
        page.screenshot(path=str(OUT / "01-sessions.png"), full_page=False)
        print("sessions: cards =", page.locator(".catalog-card").count())

        # 2. open the web-to-lateral session -> forecast
        card = page.locator(".catalog-card", has_text="Web compromise")
        card.locator("button", has_text="Open session").click()
        page.wait_for_selector(".panel", timeout=60000)
        page.wait_for_selector(".tiles", timeout=60000)
        # the entity table fills when the forecast payload lands (the first
        # forecast on a cold server can outlive any fixed sleep)
        page.wait_for_selector("table.data tbody tr", timeout=120000)
        page.wait_for_timeout(1500)
        page.screenshot(path=str(OUT / "02-forecast.png"))
        print("forecast: entities rows =", page.locator("table.data tbody tr").count())

        # 3. evidence screen (attribution takes a few seconds)
        page.locator(".nav button", has_text="Evidence").click()
        page.wait_for_timeout(4000)
        page.wait_for_selector(".tiles", timeout=60000)
        time.sleep(1.0)
        page.screenshot(path=str(OUT / "03-evidence.png"), full_page=False)
        print("evidence: flagged rows =", page.locator("table.data tbody tr").count())

        # 4. replay + reveal
        page.locator(".nav button", has_text="Replay").click()
        page.wait_for_selector(".scrubber", timeout=30000)
        time.sleep(1.0)
        page.locator("button", has_text="Reveal ground truth").click()
        page.wait_for_selector("text=Scored comparison", timeout=60000)
        time.sleep(0.8)
        page.screenshot(path=str(OUT / "04-replay.png"), full_page=False)
        print("reveal: comparison rows visible")

        # 5. evaluation
        page.locator(".nav button", has_text="Evaluation").click()
        page.wait_for_selector("text=Golden contract check", timeout=30000)
        time.sleep(0.8)
        page.screenshot(path=str(OUT / "05-evaluation.png"), full_page=False)
        print("evaluation: golden check visible")

        # 5b. Tier B: paths screen (supported after train_paths.py, else the
        # honest not_supported empty state — both must render cleanly)
        page.locator(".nav button", has_text="Paths").click()
        page.wait_for_selector(".panel", timeout=30000)
        time.sleep(1.2)
        page.screenshot(path=str(OUT / "05b-paths.png"), full_page=False)
        supported = page.locator(".paths-list .path-row").count()
        print("paths: ranked path rows =", supported)

        # 5c. Tier B: evidence query screen (Section 21)
        page.locator(".nav button", has_text="Query").click()
        page.wait_for_selector(".tile", timeout=30000)
        time.sleep(1.0)
        page.screenshot(path=str(OUT / "05c-query.png"), full_page=False)
        proposals = page.locator(".query-row").count()
        print("query: proposal rows =", proposals)
        # execute the first proposal when present (answered/unavailable/
        # denied states must all render without console errors)
        if proposals:
            page.locator(".query-row button", has_text="Request").first.click()
            page.wait_for_selector(".query-answer", timeout=30000)
            time.sleep(0.8)
            page.screenshot(path=str(OUT / "05c-query-answered.png"), full_page=False)
            print("query: answer rendered =", page.locator(".query-answer").count())

        # 5d. Tier B: range action screen (Sections 22-23) — propose,
        # authorize, dry-run the paired trial
        page.locator(".nav button", has_text="Action").click()
        page.wait_for_selector(".action-select", timeout=30000)
        page.locator(".action-select").first.select_option(index=1)
        page.locator(".action-select").nth(1).select_option(index=1)
        page.locator("button", has_text="Propose action").click()
        page.wait_for_selector("text=Authorize", timeout=30000)
        time.sleep(0.6)
        page.screenshot(path=str(OUT / "05d-action-proposal.png"), full_page=False)
        page.locator("button", has_text="Authorize").click()
        page.wait_for_selector("text=Dry-run paired trial", timeout=30000)
        page.locator("button", has_text="Dry-run paired trial").click()
        page.wait_for_selector("text=Paired trial outcome", timeout=120000)
        time.sleep(1.0)
        page.screenshot(path=str(OUT / "05d-action-trial.png"), full_page=False)
        print("action: trial outcome rendered")

        # 6. narrow viewport (K.3)
        page.set_viewport_size({"width": 420, "height": 900})
        page.locator(".nav button", has_text="Forecast").click()
        time.sleep(1.2)
        page.screenshot(path=str(OUT / "06-narrow.png"), full_page=False)
        # horizontal overflow check
        overflow = page.evaluate(
            "document.documentElement.scrollWidth > document.documentElement.clientWidth + 1"
        )
        print("narrow viewport horizontal overflow:", overflow)

        browser.close()

    print("\nconsole errors:", len(errors))
    for e in errors[:8]:
        print("  -", e[:160])
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
