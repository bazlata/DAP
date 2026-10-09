import argparse
import os
import re
import sqlite3
import time
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright, Page, BrowserContext

DB_PATH = "data/persistence/kikeriki.db"
OUTPUT_DIR = "data/raw/pages"
ANNO_BASE_URL = "https://anno.onb.ac.at/cgi-content/anno"
CHROME_PROFILE_DIR = os.path.expanduser("~/.config/chrome_kikeriki_profile")


def get_pending_issues(db_path: str = DB_PATH, year: int = 1903) -> list:
    """Retrieves harvested issue metadata from the database for the target year."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT issue_id, issue_date, year, liturgical_cycle, delta_days, page_count
            FROM issues
            WHERE year = ?
            ORDER BY issue_date ASC;
            """,
            (year,)
        )
        return [dict(row) for row in cursor.fetchall()]


def handle_cloudflare_challenge(page: Page, timeout_ms: int = 45000) -> None:
    """Waits for Cloudflare Turnstile verification if an interstitial appears."""
    page.wait_for_timeout(1000)
    if "Sicherheits" in page.title():
        print("Waiting for Cloudflare verification to clear...")
        page.wait_for_function("document.title.indexOf('Sicherheits') === -1", timeout=timeout_ms)
        page.wait_for_timeout(2000)


def extract_scan_image_url(page: Page) -> str:
    """
    Identifies the primary newspaper scan image on the viewer page across all frames
    by locating image elements with scan/zoom parameters and filtering out navigation icons.
    """
    for frame in page.frames:
        try:
            img_urls = frame.evaluate("""() => {
                const imgs = Array.from(document.querySelectorAll('img'));
                return imgs.map(img => img.getAttribute('src') || '').filter(src => src.length > 0);
            }""")

            # Match images carrying issue zoom parameters or scan identifiers
            scan_candidates = [
                u for u in img_urls
                if not any(token in u.lower() for token in ["gfx", "logo", "button", "icon", "nav"])
                and any(token in u for token in ["zoom", "datum", "aid=", "scan"])
            ]

            if scan_candidates:
                return scan_candidates[0]

            # Fallback: find the largest rendered image element in the DOM
            largest_src = frame.evaluate("""() => {
                const imgs = Array.from(document.querySelectorAll('img')).filter(i => {
                    const src = i.getAttribute('src') || '';
                    return !src.includes('gfx') && !src.includes('logo');
                });
                if (imgs.length === 0) return null;
                imgs.sort((a, b) => (b.naturalWidth * b.naturalHeight) - (a.naturalWidth * a.naturalHeight));
                return imgs[0].getAttribute('src');
            }""")
            if largest_src:
                return largest_src

        except Exception:
            continue

    raise RuntimeError("Failed to detect scan image URL on current page")


def download_issue_pages(context: BrowserContext, issue: dict, max_retries: int = 3) -> None:
    """Downloads all physical pages for an individual issue using authenticated context requests."""
    issue_id = issue["issue_id"]
    date_str = issue["issue_date"].replace("-", "")
    page_count = issue["page_count"] or 1
    issue_dir = os.path.join(OUTPUT_DIR, issue_id)
    os.makedirs(issue_dir, exist_ok=True)

    page = context.pages[0] if context.pages else context.new_page()
    print(f"[{issue_id}] Starting download ({page_count} pages, {issue['liturgical_cycle']}, delta={issue['delta_days']})")

    for page_num in range(1, page_count + 1):
        target_path = os.path.join(issue_dir, f"page_{page_num:03d}.jpg")
        if os.path.exists(target_path) and os.path.getsize(target_path) > 10000:
            continue

        viewer_url = f"{ANNO_BASE_URL}?aid=kik&datum={date_str}&seite={page_num}"
        success = False

        for attempt in range(1, max_retries + 1):
            try:
                page.goto(viewer_url, timeout=30000)
                handle_cloudflare_challenge(page)
                page.wait_for_timeout(800)

                raw_img_src = extract_scan_image_url(page)
                full_img_url = urljoin(viewer_url, raw_img_src)

                # Request binary JPEG using context-shared cookies and headers
                response = context.request.get(full_img_url, timeout=30000)
                if response.status == 200 and len(response.body()) > 5000:
                    with open(target_path, "wb") as f:
                        f.write(response.body())
                    print(f"  -> Page {page_num:02d}/{page_count:02d}: {len(response.body()) // 1024} KB saved.")
                    success = True
                    break
                else:
                    print(f"  -> Page {page_num:02d}: Unexpected status {response.status} (attempt {attempt})")
            except Exception as err:
                print(f"  -> Page {page_num:02d}: Error on attempt {attempt}: {err}")
                time.sleep(1.5)

        if not success:
            print(f"  [ERROR] Failed to download page {page_num} of {issue_id} after {max_retries} attempts.")

        time.sleep(0.4)


def run_page_ingestion(year: int = 1903, issue_limit: int = None) -> None:
    """Executes sequential page scan downloads for indexed newspaper issues."""
    issues = get_pending_issues(DB_PATH, year=year)
    if not issues:
        print(f"No harvested issues found in {DB_PATH} for year {year}.")
        return

    if issue_limit:
        issues = issues[:issue_limit]

    print(f"Found {len(issues)} issues to process for year {year}. Output path: {OUTPUT_DIR}")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=CHROME_PROFILE_DIR,
            channel="chrome",
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 800}
        )

        for issue in issues:
            download_issue_pages(context, issue)

        context.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download ANNO page scans for indexed Kikeriki issues.")
    parser.add_argument("--year", type=int, default=1903, help="Publication year to ingest")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of issues to process (for testing)")
    args = parser.parse_args()

    run_page_ingestion(year=args.year, issue_limit=args.limit)