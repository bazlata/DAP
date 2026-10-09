import os
import re
import sqlite3
import time
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Set

from dateutil.easter import easter
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, Page

DB_PATH = "data/persistence/kikeriki.db"
ANNO_BASE_URL = "https://anno.onb.ac.at/cgi-content/anno"
CHROME_PROFILE_DIR = os.path.expanduser("~/.config/chrome_kikeriki_profile")


def init_metadata_database(db_path: str = DB_PATH) -> None:
    """Initializes the SQLite schema and indexes for newspaper issue metadata."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS issues (
                issue_id TEXT PRIMARY KEY,
                issue_date TEXT NOT NULL,
                year INTEGER NOT NULL,
                era TEXT NOT NULL,
                liturgical_cycle TEXT NOT NULL,
                feast_date TEXT NOT NULL,
                delta_days INTEGER NOT NULL,
                anno_url TEXT NOT NULL,
                page_count INTEGER,
                harvested_at TEXT NOT NULL
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_issues_date ON issues(issue_date);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_issues_cycle_era ON issues(liturgical_cycle, era);")
        conn.commit()


def compute_target_windows(start_year: int, end_year: int, window_days: int = 14) -> List[Dict]:
    """Computes liturgical observation windows (±14 days) around Easter, Pentecost, and Christmas."""
    windows = []
    for year in range(start_year, end_year + 1):
        if 1915 <= year <= 1918:
            continue

        era = "late_habsburg" if year <= 1914 else "first_republic"
        easter_d = easter(year)
        pentecost_d = easter_d + timedelta(days=49)
        christmas_d = date(year, 12, 25)

        feasts = [
            ("easter", easter_d),
            ("pentecost", pentecost_d),
            ("christmas", christmas_d),
        ]

        for feast_name, feast_d in feasts:
            if year == 1914 and feast_name == "christmas":
                continue

            windows.append({
                "year": year,
                "era": era,
                "liturgical_cycle": feast_name,
                "feast_date": feast_d,
                "start_date": feast_d - timedelta(days=window_days),
                "end_date": feast_d + timedelta(days=window_days),
            })
    return windows


def handle_cloudflare_challenge(page: Page, timeout_ms: int = 45000) -> None:
    """Waits for Cloudflare Turnstile verification to clear if an interstitial appears."""
    page.wait_for_timeout(1500)
    if "Sicherheits" in page.title():
        print("Waiting for verification to pass...")
        page.wait_for_function("document.title.indexOf('Sicherheits') === -1", timeout=timeout_ms)
        page.wait_for_timeout(2500)


def extract_all_frame_html(page: Page) -> str:
    """Gathers and concatenates HTML content from the top frame and all embedded child frames."""
    html_parts = []
    for frame in page.frames:
        try:
            html_parts.append(frame.content())
        except Exception:
            pass
    return "\n".join(html_parts)


def fetch_annual_published_dates(page: Page, publication_id: str, year: int) -> Set[str]:
    """Navigates to the ANNO yearly calendar overview and retrieves published issue dates across all frames."""
    url = f"{ANNO_BASE_URL}?aid={publication_id}&jahr={year}"
    page.goto(url)
    handle_cloudflare_challenge(page)
    page.wait_for_timeout(2000)

    combined_html = extract_all_frame_html(page)
    dates = set(re.findall(r"datum=(\d{8})", combined_html))
    return {d for d in dates if d.startswith(str(year))}


def inspect_issue_page_count(page: Page, publication_id: str, date_str: str) -> Optional[int]:
    """Inspects an individual issue viewer across all frames to determine total physical pages."""
    url = f"{ANNO_BASE_URL}?aid={publication_id}&datum={date_str}"
    try:
        page.goto(url)
        handle_cloudflare_challenge(page)
        page.wait_for_timeout(1000)

        combined_html = extract_all_frame_html(page)
        soup = BeautifulSoup(combined_html, "html.parser")

        page_select = soup.find("select", {"name": "seite"})
        if page_select:
            return len(page_select.find_all("option"))

        page_links = re.findall(r"seite=(\d+)", combined_html)
        if page_links:
            return max(int(num) for num in page_links)
    except Exception as err:
        print(f"Notice: unable to extract page count for {date_str} ({err})")
    return None


def run_metadata_harvest(start_year: int, end_year: int, publication_id: str = "kik") -> None:
    """Harvests issue metadata across designated liturgical windows and saves to SQLite."""
    init_metadata_database(DB_PATH)
    windows = compute_target_windows(start_year, end_year, window_days=14)
    years = sorted(list({w["year"] for w in windows}))

    print(f"Starting metadata harvest for '{publication_id}' across years: {years}")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=CHROME_PROFILE_DIR,
            channel="chrome",
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 800}
        )
        page = context.pages[0] if context.pages else context.new_page()

        for year in years:
            print(f"Fetching published issue registry for {year}...")
            published_dates = fetch_annual_published_dates(page, publication_id, year)
            print(f"[{year}] Total published issues found on ANNO: {len(published_dates)}")

            if not published_dates:
                print(f"Warning: No published dates found for {year}. Skipping.")
                continue

            records_to_insert = []
            year_windows = [w for w in windows if w["year"] == year]

            for win in year_windows:
                cycle = win["liturgical_cycle"]
                feast_d = win["feast_date"]
                matching_dates = sorted([
                    d for d in published_dates
                    if win["start_date"] <= datetime.strptime(d, "%Y%m%d").date() <= win["end_date"]
                ])

                print(f"  -> Feast '{cycle}' ({feast_d}): found {len(matching_dates)} issues within window.")

                for d_str in matching_dates:
                    issue_d = datetime.strptime(d_str, "%Y%m%d").date()
                    delta = (issue_d - feast_d).days
                    issue_id = f"{publication_id}_{d_str}"
                    anno_url = f"{ANNO_BASE_URL}?aid={publication_id}&datum={d_str}"

                    page_count = inspect_issue_page_count(page, publication_id, d_str)
                    time.sleep(0.3)

                    records_to_insert.append((
                        issue_id,
                        issue_d.isoformat(),
                        year,
                        win["era"],
                        cycle,
                        feast_d.isoformat(),
                        delta,
                        anno_url,
                        page_count,
                        datetime.utcnow().isoformat(),
                    ))

            with sqlite3.connect(DB_PATH) as conn:
                conn.executemany("""
                    INSERT OR REPLACE INTO issues (
                        issue_id, issue_date, year, era, liturgical_cycle,
                        feast_date, delta_days, anno_url, page_count, harvested_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, records_to_insert)
                conn.commit()

            print(f"Committed {len(records_to_insert)} records for {year} into {DB_PATH}.\n")

        context.close()


if __name__ == "__main__":
    run_metadata_harvest(start_year=1903, end_year=1903)