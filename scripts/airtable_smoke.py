"""Probe public Airtable calendar export without storing expiring signed URLs."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "https://airtable.com/appIAfygGZFs7eJr6/shrSKjBHwNBId5Mjx/tblWCjX1JWEWWcuuQ"


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            accept_downloads=True,
            locale="en-US",
            timezone_id="America/New_York",
        )
        page = context.new_page()
        try:
            page.goto(URL, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(7000)
            print("Page:", page.title(), "buttons:", page.locator("button").count())
            buttons = page.locator("button")
            for i in range(min(buttons.count(), 50)):
                button = buttons.nth(i)
                label = (
                    button.get_attribute("aria-label") or button.get_attribute("title")
                    or button.inner_text(timeout=1000)
                ).strip()
                if label:
                    print("Button", i, repr(label[:90]))

            # Try semantic button labels first, and fall back to the literal menu glyph.
            menu_selectors = [
                'button[aria-label*="more" i]',
                'button[aria-label*="view options" i]',
                'button[aria-label*="menu" i]',
                'button[title*="more" i]',
                'button:has-text("...")',
                '[role="button"][aria-label*="more" i]',
            ]
            options = page.get_by_text("Download iCal", exact=True)
            for selector in menu_selectors:
                if options.is_visible():
                    break
                loc = page.locator(selector)
                if loc.count():
                    try:
                        loc.first.click(timeout=3000)
                        page.wait_for_timeout(350)
                        print("Clicked menu selector", selector)
                    except Exception as exc:
                        print("Menu click failed", selector, type(exc).__name__)
            if not options.is_visible():
                print("Download iCal not visible. Nearby menu text:",
                      [x[:80] for x in page.locator('[role="menuitem"]').all_text_contents()][:20])
                return 2
            with page.expect_download(timeout=30000) as download_info:
                options.click()
            download = download_info.value
            output = Path("/tmp/school-house-airtable-test.ics")
            download.save_as(output)
            body = output.read_bytes()
            n = body.count(b"BEGIN:VEVENT")
            print("Downloaded valid ICS?", body.startswith(b"BEGIN:VCALENDAR"), "VEVENTs", n,
                  "size", len(body))
            if not body.startswith(b"BEGIN:VCALENDAR") or n < 50:
                return 3
            return 0
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    sys.exit(main())
