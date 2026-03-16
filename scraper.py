"""
Job Scraper — EURAXESS & jobRxiv
==================================
Scrapes job listings from EURAXESS or jobRxiv and saves them to a JSON file.
Run this once to collect jobs, then use run_agents.py to evaluate them.

Usage:
  python scraper.py                          # uses SOURCE setting below
  python scraper.py --source euraxess
  python scraper.py --source jobrxiv
  python scraper.py --source euraxess --pages 20
  python scraper.py --source jobrxiv --pages 10 --output jobrxiv_jobs.json
"""

import requests
from bs4 import BeautifulSoup
import json
import time
import random
import re
import os
import sys
import argparse
from datetime import datetime
from typing import Optional

# ─────────────────────────────────────────────────────────────
# CONFIGURATION — edit these before running
# ─────────────────────────────────────────────────────────────

# Which source to scrape: "euraxess" or "jobrxiv"
SOURCE = "euraxess"

# --- EURAXESS ---
# Build your custom filter URL at euraxess.ec.europa.eu/jobs/search
# then paste it here. The one below filters by country + research field.
EURAXESS_URL = (
    "https://euraxess.ec.europa.eu/jobs/search?f%5B0%5D=job_country%3A792&f%5B1%5D=offer_type%3Ajob_offer"
)

# --- jobRxiv ---
# Go to jobrxiv.org, apply your filters (category, region, tags etc.),
# copy the URL from your browser and paste it below — or pass via --url.
#
# Examples:
#   Category + region: https://jobrxiv.org/job-category/postdoc/?job_region=27628&search_categories=95,102
#   Region only:       https://jobrxiv.org/job-region/europe/
#   Keyword search:    https://jobrxiv.org/?search_keywords=data+scientist&search_location=Belgium
#
# Set to None to require --url argument at runtime (recommended).
JOBRXIV_URL = "https://jobrxiv.org/"

# Max pages to scrape per source. Set 0 for all pages.
MAX_PAGES = 10

# Output file
OUTPUT_JSON = "jobs.json"

# Delays (seconds) — randomised between min and max to avoid 429s
SCRAPE_DELAY_MIN = 3.0
SCRAPE_DELAY_MAX = 5.5

# ─────────────────────────────────────────────────────────────
# ARGUMENT PARSING
# ─────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(description="Scrape jobs from EURAXESS or jobRxiv")
    parser.add_argument("--source",  choices=["euraxess", "jobrxiv"], default=SOURCE)
    parser.add_argument("--pages",   type=int, default=MAX_PAGES,
                        help="Max pages to scrape (0 = all)")
    parser.add_argument("--output",  default=OUTPUT_JSON,
                        help="Output JSON filename")
    parser.add_argument("--url",     default=None,
                        help="Override the default search URL for this source")
    return parser.parse_args()

# ─────────────────────────────────────────────────────────────
# HTTP SESSION
# ─────────────────────────────────────────────────────────────

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection":      "keep-alive",
})

# ─────────────────────────────────────────────────────────────
# SHARED HELPERS
# ─────────────────────────────────────────────────────────────

def fetch(url: str, retries: int = 3) -> Optional[BeautifulSoup]:
    """Fetch URL with 429 exponential backoff retry."""
    for attempt in range(retries):
        try:
            resp = SESSION.get(url, timeout=20)
            if resp.status_code == 429:
                wait = 30 * (attempt + 1)
                print(f"    ⏳ 429 Rate limited — waiting {wait}s "
                      f"(attempt {attempt+1}/{retries})")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "lxml")
        except requests.HTTPError as e:
            print(f"    ⚠️  HTTP {e.response.status_code}: {url}")
            if attempt < retries - 1:
                time.sleep(10)
        except requests.RequestException as e:
            print(f"    ⚠️  Request error: {e}")
            if attempt < retries - 1:
                time.sleep(5)
    return None


def polite_delay():
    """Random delay between job page fetches."""
    time.sleep(random.uniform(SCRAPE_DELAY_MIN, SCRAPE_DELAY_MAX))


def save_json(jobs: list, output_path: str, source: str):
    """Save collected jobs to JSON."""
    output = {
        "source":     source,
        "scraped_at": datetime.now().isoformat(),
        "total_jobs": len(jobs),
        "jobs":       jobs,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n💾 Saved {len(jobs)} jobs → {output_path}")


def clean_text(text: str) -> str:
    """Remove excessive blank lines and whitespace."""
    return re.sub(r'\n{3,}', '\n\n', text).strip() if text else ""


# ─────────────────────────────────────────────────────────────
# EURAXESS — collect links
# ─────────────────────────────────────────────────────────────

EURAXESS_BASE = "https://euraxess.ec.europa.eu"


def euraxess_collect_links(start_url: str, max_pages: int) -> list[dict]:
    """
    Walk EURAXESS search result pages and collect job links + titles.
    Job links: h3 > a[href^="/jobs/NUMERIC_ID"]
    Pagination: <a> with text "Next", href starts with "?"
    """
    links = []
    seen  = set()
    url   = start_url
    page  = 1

    while url:
        if max_pages > 0 and page > max_pages:
            break

        limit = f"/{max_pages}" if max_pages else ""
        print(f"  Listing page {page}{limit}...")
        soup = fetch(url)
        if not soup:
            print("  ❌ Failed — stopping.")
            break

        found = 0
        for h3 in soup.find_all("h3"):
            a = h3.find("a", href=True)
            if not a:
                continue
            href = a["href"].strip()
            if not href.startswith("/jobs/"):
                continue
            job_id = href.split("/jobs/")[-1].split("/")[0]
            if not job_id.isdigit():
                continue
            full_url = EURAXESS_BASE + href
            if full_url in seen:
                continue
            seen.add(full_url)
            links.append({"url": full_url, "title": a.get_text(strip=True)})
            found += 1

        print(f"  → {found} jobs  (total: {len(links)})")
        if found == 0:
            break

        # Find "Next" pagination link
        next_url = None
        for a in soup.find_all("a", href=True):
            if a.get_text(strip=True).lower() in ("next", "›", "»"):
                href = a["href"].strip()
                if href.startswith("http"):
                    next_url = href
                elif href.startswith("/"):
                    next_url = EURAXESS_BASE + href
                elif href.startswith("?"):
                    next_url = EURAXESS_BASE + "/jobs/search" + href
                break

        if not next_url:
            print("  No next page — done.")
            break

        url = next_url
        page += 1
        time.sleep(random.uniform(1.5, 2.5))

    return links


def euraxess_scrape_job(url: str) -> Optional[dict]:
    """
    Fetch a single EURAXESS job page.
    Extracts: title, organization, country, deadline, contract type, description.
    """
    soup = fetch(url)
    if not soup:
        return None

    # Title
    h1    = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else "Unknown"

    # Structured metadata from dt/dd pairs
    fields = {}
    for dt in soup.find_all("dt"):
        label = dt.get_text(strip=True).lower().rstrip(":").strip()
        dd    = dt.find_next_sibling("dd")
        if dd and label:
            fields[label] = dd.get_text(strip=True)

    def f(*keys):
        for k in keys:
            if k in fields:
                return fields[k]
        return "N/A"

    # Deadline — dt/dd first, then regex fallback
    deadline = f("application deadline", "deadline", "closing date")
    if deadline == "N/A":
        m = re.search(
            r'(?:deadline|closing)[^\d]{0,30}(\d{1,2}\s+\w+\s+\d{4})',
            soup.get_text(" ", strip=True), re.IGNORECASE
        )
        if m:
            deadline = m.group(1)

    # Description
    description = ""
    for cls_frag in ["field--name-body", "field-body", "job-description"]:
        block = soup.find("div", class_=lambda c: c and cls_frag in c)
        if block and len(block.get_text(strip=True)) > 200:
            description = block.get_text(separator="\n", strip=True)
            break
    if len(description) < 200:
        main = soup.find("main") or soup.find("article")
        if main:
            for tag in main.find_all(["nav", "header", "footer", "aside", "script", "style"]):
                tag.decompose()
            description = main.get_text(separator="\n", strip=True)

    return {
        "job_id":       url.split("/jobs/")[-1].rstrip("/"),
        "source":       "euraxess",
        "title":        title,
        "company":      f("organisation", "organization", "institution", "employer"),
        "location":     f("country", "location", "work location"),
        "deadline":     deadline,
        "contract":     f("type of contract", "contract type", "employment type"),
        "description":  clean_text(description),
        "url":          url,
        "scraped_at":   datetime.now().isoformat(),
    }


# ─────────────────────────────────────────────────────────────
# jobRxiv — collect links
# ─────────────────────────────────────────────────────────────

def _parse_jobrxiv_links(soup: BeautifulSoup, seen: set) -> list[dict]:
    """Extract job links from a jobRxiv HTML page or fragment."""
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not re.match(r'https://jobrxiv\.org/job/[^/]+/?$', href):
            continue
        if href in seen:
            continue
        seen.add(href)
        title = a.get_text(strip=True)
        if not title or len(title) < 3:
            continue
        links.append({"url": href, "title": title})
    return links


def jobrxiv_collect_links(start_url: str, max_pages: int) -> list[dict]:
    """
    Collect job links from jobRxiv. Supports two modes automatically:

    MODE 1 — Direct HTML scrape (category/tag/region filter URLs):
      Used when the URL path contains a taxonomy slug like:
        jobrxiv.org/job-category/postdoc/
        jobrxiv.org/job-region/europe/
        jobrxiv.org/job-tag/machine-learning/
      These pages render all matching jobs directly in HTML — no AJAX needed.
      Pagination uses /page/N/ if there are more than 25 results.

    MODE 2 — AJAX endpoint (homepage or keyword/location search):
      Used when the URL is the homepage or has search_keywords/search_location.
        jobrxiv.org/
        jobrxiv.org/?search_keywords=data+scientist&search_location=Europe
      POSTs to jm-ajax/get_listings/ and paginates via page number.
    """
    from urllib.parse import urlparse, parse_qs

    parsed = urlparse(start_url)
    qs     = parse_qs(parsed.query)
    path   = parsed.path.rstrip("/")

    # Detect taxonomy URLs — any path beyond the root
    TAXONOMY_SLUGS = ("/job-category/", "/job-region/", "/job-tag/")
    is_taxonomy = any(slug in path for slug in TAXONOMY_SLUGS)

    links = []
    seen  = set()

    # ── MODE 1: Direct HTML scrape for taxonomy/filter URLs ──────────────
    if is_taxonomy:
        print(f"  (filter URL detected — scraping HTML directly)")
        base = start_url.rstrip("/")
        page = 1

        while True:
            if max_pages > 0 and page > max_pages:
                break

            url   = base if page == 1 else f"{base}/page/{page}/"
            limit = f"/{max_pages}" if max_pages else ""
            print(f"  Page {page}{limit}...")

            soup = fetch(url)
            if not soup:
                print("  ❌ Failed — stopping.")
                break

            new_links = _parse_jobrxiv_links(soup, seen)
            links.extend(new_links)
            print(f"  → {len(new_links)} jobs  (total: {len(links)})")

            if len(new_links) == 0:
                print("  No more jobs — done.")
                break

            # Check if a next page exists
            next_page = soup.find("a", class_=lambda c: c and "next" in c.lower())
            if not next_page:
                # Also check for standard WordPress pagination link
                next_page = soup.find("a", string=re.compile(r"next|›|»", re.IGNORECASE))
            if not next_page:
                print("  No next page — done.")
                break

            page += 1
            time.sleep(random.uniform(1.5, 2.5))

    # ── MODE 2: AJAX endpoint for homepage / keyword search ───────────────
    else:
        AJAX_ENDPOINT = "https://jobrxiv.org/jm-ajax/get_listings/"
        PER_PAGE      = 25
        print(f"  (search URL detected — using AJAX endpoint)")

        page = 1
        while True:
            if max_pages > 0 and page > max_pages:
                break

            limit = f"/{max_pages}" if max_pages else ""
            print(f"  Batch {page}{limit} (25 jobs)...")

            # Pass all query params from the URL through to the endpoint
            payload = {
                "page":     page,
                "per_page": PER_PAGE,
                "orderby":  "date",
                "action":   "job_manager_get_listings",
            }
            for key, values in qs.items():
                payload[key] = values[0]

            try:
                resp = SESSION.post(AJAX_ENDPOINT, data=payload, timeout=20)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                print(f"  ⚠️  AJAX request failed: {e}")
                break

            if not data.get("found_jobs", False):
                print("  No more jobs — reached end of results.")
                break

            soup      = BeautifulSoup(data.get("html", ""), "lxml")
            new_links = _parse_jobrxiv_links(soup, seen)
            links.extend(new_links)
            print(f"  → {len(new_links)} new jobs  (total: {len(links)})")

            max_num_pages = data.get("max_num_pages", 1)
            if page >= max_num_pages:
                print(f"  Reached last page ({max_num_pages}) — done.")
                break

            if len(new_links) == 0:
                break

            page += 1
            time.sleep(random.uniform(1.5, 2.5))

    return links


def jobrxiv_scrape_job(url: str) -> Optional[dict]:
    """
    Fetch a single jobRxiv job page (WordPress WP Job Manager).
    Extracts: title, company, location, date_posted, description.
    """
    soup = fetch(url)
    if not soup:
        return None

    # Title — h1, strip "Full-time" / "Part-time" suffix
    h1    = soup.find("h1")
    title = re.sub(r'\s+(Full-time|Part-time|Contract|Temporary)$', '',
                   h1.get_text(strip=True), flags=re.IGNORECASE) if h1 else "Unknown"

    # Company — strong tag inside the employer section
    company = "N/A"
    for strong in soup.find_all("strong"):
        text = strong.get_text(strip=True)
        if text and len(text) > 3 and len(text) < 120:
            company = text
            break

    # Location — look for the location meta div
    location = "N/A"
    loc_div  = soup.find("li", class_=lambda c: c and "location" in c.lower())
    if loc_div:
        location = loc_div.get_text(strip=True)
    else:
        # Fallback: find city/country pattern near "Posted"
        full_text = soup.get_text(" ", strip=True)
        m = re.search(r'Posted on\s+[\d\w\s]+\n(.+?\n.+?)(?:Posted|Apply|$)',
                      soup.get_text("\n", strip=True))
        if m:
            location = m.group(1).replace("\n", ", ").strip()

    # Date posted
    date_posted = "N/A"
    date_pattern = re.compile(r'Posted on\s+(\d{1,2}\s+\w+\s+\d{4})', re.IGNORECASE)
    m = date_pattern.search(soup.get_text(" ", strip=True))
    if m:
        date_posted = m.group(1)

    # Description — main job content div
    description = ""
    for cls in ["job_description", "job-description", "entry-content", "wpjm-job-description"]:
        block = soup.find("div", class_=lambda c: c and cls in c)
        if block and len(block.get_text(strip=True)) > 100:
            description = block.get_text(separator="\n", strip=True)
            break

    if len(description) < 100:
        # Broader fallback — take main content area
        main = soup.find("main") or soup.find("article")
        if main:
            for tag in main.find_all(["nav", "header", "footer", "aside",
                                      "script", "style", "ul.job-categories"]):
                tag.decompose()
            description = main.get_text(separator="\n", strip=True)

    # Deadline — often mentioned in description text
    deadline = "N/A"
    m = re.search(
        r'(?:deadline|apply by|closing date|until)[^\d]{0,30}(\d{1,2}[\.\s]\d{1,2}[\.\s]\d{4}|\d{1,2}\s+\w+\s+\d{4})',
        description, re.IGNORECASE
    )
    if m:
        deadline = m.group(1).strip()

    # Build slug-based job_id from URL
    job_id = url.rstrip("/").split("/job/")[-1].rstrip("/")

    return {
        "job_id":      job_id,
        "source":      "jobrxiv",
        "title":       title,
        "company":     company,
        "location":    location,
        "deadline":    deadline,
        "contract":    "N/A",
        "description": clean_text(description),
        "url":         url,
        "scraped_at":  datetime.now().isoformat(),
    }


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():
    args       = parse_args()
    source     = args.source
    max_pages  = args.pages
    output     = args.output
    custom_url = args.url

    # Resolve search URL
    if custom_url:
        search_url = custom_url
    elif source == "euraxess":
        search_url = EURAXESS_URL
    elif JOBRXIV_URL:
        search_url = JOBRXIV_URL
    else:
        print("\n❌ No jobRxiv URL provided.")
        print("   Go to jobrxiv.org, apply your filters, copy the URL, then either:")
        print("   • Pass it as an argument:")
        print('     python scraper.py --source jobrxiv --url "https://jobrxiv.org/job-category/postdoc/..."')
        print("   • Or paste it into JOBRXIV_URL in scraper.py")
        sys.exit(1)

    print("\n" + "═"*62)
    print(f"  🔍  JOB SCRAPER — {source.upper()}")
    print(f"  URL:    {search_url[:70]}{'...' if len(search_url)>70 else ''}")
    print(f"  Pages:  {max_pages if max_pages else 'ALL'}")
    print(f"  Output: {output}")
    print("═"*62 + "\n")

    # Step 1: Collect all job links from listing pages
    print("📋 Collecting job links...\n")
    if source == "euraxess":
        links = euraxess_collect_links(search_url, max_pages)
    else:
        links = jobrxiv_collect_links(search_url, max_pages)

    if not links:
        print("❌ No job links found. Check URL or connection.")
        sys.exit(1)

    print(f"\n✅ {len(links)} jobs found. Fetching full details...\n")
    print("─"*62)

    # Step 2: Fetch full details for each job
    jobs   = []
    errors = 0

    for i, link in enumerate(links, 1):
        title_preview = (link["title"][:58] + "…") \
            if len(link["title"]) > 59 else link["title"]
        print(f"[{i}/{len(links)}] {title_preview}")

        if source == "euraxess":
            job = euraxess_scrape_job(link["url"])
        else:
            job = jobrxiv_scrape_job(link["url"])

        if not job:
            print("  ⚠️  Failed to fetch — skipping.\n")
            errors += 1
            polite_delay()
            continue

        desc_preview = job["description"][:80].replace("\n", " ")
        print(f"  📍 {job['location']}  |  ⏰ {job['deadline']}")
        print(f"  📝 {desc_preview}...\n")
        jobs.append(job)
        polite_delay()

    # Step 3: Save
    save_json(jobs, output, source)

    print("\n" + "═"*62)
    print("  📈  SCRAPE SUMMARY")
    print("═"*62)
    print(f"  Jobs scraped:   {len(jobs)}")
    print(f"  Errors/skipped: {errors}")
    print(f"\n  Next step → run:  python run_agents.py --input {output}\n")


if __name__ == "__main__":
    main()
