import os
import re
from playwright.sync_api import sync_playwright

url = "https://anno.onb.ac.at/cgi-content/anno?aid=kik&jahr=1903"
profile_dir = os.path.expanduser("~/.config/chrome_kikeriki_profile")

with sync_playwright() as p:
    # Launch system Google Chrome with a persistent user profile
    context = p.chromium.launch_persistent_context(
        user_data_dir=profile_dir,
        channel="chrome",
        headless=False,
        args=[
            "--disable-blink-features=AutomationControlled",
        ],
        viewport={"width": 1280, "height": 800}
    )
    
    page = context.pages[0] if context.pages else context.new_page()
    print("Navigating to ANNO via installed Google Chrome...")
    page.goto(url)

    print("Solve the Cloudflare checkbox if prompted...")
    page.wait_for_function("document.title.indexOf('Sicherheits') === -1", timeout=60000)
    page.wait_for_timeout(3000)

    html = page.content()
    dates = set(re.findall(r"datum=(\d{8})", html))

    print(f"\nFinal Title: {page.title()}")
    print(f"HTML characters: {len(html)}")
    print(f"Discovered dates: {len(dates)}")
    if dates:
        print("Sample dates:", sorted(list(dates))[:5])

    context.close()