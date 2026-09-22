import os
import re
import csv
import time
import argparse
from datetime import datetime, timezone, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_URL = "https://www.thairath.co.th"
CSV_FILE = os.path.join(SCRIPT_DIR, "thairath_society.csv")
CATEGORY = "สังคม"

def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    # Speed optimization: block images and set eager page load strategy
    chrome_options.page_load_strategy = 'eager'
    chrome_prefs = {
        "profile.default_content_setting_values.images": 2
    }
    chrome_options.add_experimental_option("prefs", chrome_prefs)
    # Add common headers to avoid detection
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    driver = webdriver.Chrome(options=chrome_options)
    driver.set_page_load_timeout(30)

    try:


        driver.execute_cdp_cmd('Network.enable', {})


        driver.execute_cdp_cmd('Network.setBlockedURLs', {


            'urls': [


                '*google-analytics.com*', '*doubleclick.net*', '*googlesyndication.com*',


                '*adnxs.com*', '*taboola.com*', '*outbrain.com*', '*adsystem*',


                '*adservice*', '*googleadservices*', '*facebook.net*', '*facebook.com/tr*',


                '*pubmatic.com*', '*criteo.com*', '*rubiconproject.com*', '*casalemedia.com*',


                '*openx.net*', '*adtech*', '*adform*', '*smartadserver*', '*adroll*'


            ]


        })


    except Exception as e:


        print(f"Warning: Failed to enable ad blocker: {e}")


    return driver

def extract_article_id(href):
    """Extracts article ID from Thairath URL href."""
    if not href:
        return None
    match = re.search(r"news/local/(\d+)", href)
    if match:
        return match.group(1)
    return None

def get_article_date(driver, url, max_retries=3):
    """Navigates to the article page and scrapes its publication date.
    Returns (date_text, date_obj)."""
    for attempt in range(max_retries):
        try:
            driver.get(url)
            # Give it a moment to load (0.5s is plenty for eager strategy)
            time.sleep(0.5)
            
            # 1. Try finding the visible date div
            date_text = None
            try:
                date_el = driver.find_element(By.CSS_SELECTOR, "div[class*='__item_article-date']")
                date_text = date_el.text.strip()
            except Exception:
                pass
                
            # 2. Try scraping the ISO string from meta tags
            iso_str = None
            try:
                meta_el = driver.find_element(By.XPATH, "//meta[@property='og:article:published_time' or @property='article:published_time']")
                iso_str = meta_el.get_attribute("content")
            except Exception:
                pass
                
            # 3. Fallback for ISO string from JSON-LD schema if meta tag missing
            if not iso_str:
                try:
                    scripts = driver.find_elements(By.XPATH, "//script[@type='application/ld+json']")
                    for script in scripts:
                        content = script.get_attribute("innerHTML")
                        match = re.search(r'"datePublished"\s*:\s*"([^"]+)"', content)
                        if match:
                            iso_str = match.group(1)
                            break
                except Exception:
                    pass
            
            # Parse ISO string to datetime object
            date_obj = None
            if iso_str:
                try:
                    date_obj = datetime.fromisoformat(iso_str)
                except Exception:
                    pass
            
            # If we don't have date_text, fallback to iso_str
            if not date_text:
                date_text = iso_str if iso_str else "N/A"
                
            return date_text, date_obj
                
        except Exception as e:
            print(f"  [Attempt {attempt+1}/{max_retries}] Error loading article {url}: {e}")
            time.sleep(2)
            
    return "N/A", None

def main():
    parser = argparse.ArgumentParser(description="Scrape Thairath society section.")
    parser.add_argument(
        "-p", "--pages",
        type=int,
        default=None,
        help="Max number of pages to scrape (default: scrape all pages until the end)"
    )
    parser.add_argument(
        "-d", "--days",
        type=int,
        default=None,
        help="Max number of days to scrape (e.g. 1 for today only, 2 for today and yesterday)"
    )
    args = parser.parse_args()
    max_pages = args.pages
    max_days = args.days

    cutoff_date = None
    if max_days is not None:
        tz_ict = timezone(timedelta(hours=7))
        now_ict = datetime.now(tz_ict)
        # Cutoff is start of today minus (max_days - 1) days
        cutoff_date = (now_ict - timedelta(days=max_days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
        print(f"Scraping articles published on or after: {cutoff_date.strftime('%Y-%m-%d %H:%M:%S %Z')}")

    driver = setup_driver()
    
    # Initialize CSV file and write header if it doesn't exist
    file_exists = os.path.exists(CSV_FILE)
    csv_file = open(CSV_FILE, "a", encoding="utf-8", newline="")
    csv_writer = csv.writer(csv_file)
    if not file_exists:
        csv_writer.writerow(["date", "category", "article title", "article link"])
        csv_file.flush()
        
    page = 1
    scraped_urls = set()
    
    # If file exists, read existing URLs to avoid duplicate scraping
    if file_exists:
        try:
            with open(CSV_FILE, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                next(reader, None)  # Skip header
                for row in reader:
                    if len(row) >= 4:
                        scraped_urls.add(row[3])
            print(f"Loaded {len(scraped_urls)} already scraped articles from {CSV_FILE}.")
        except Exception as e:
            print("Error reading existing CSV:", e)

    print("Starting scraper...")
    try:
        hit_cutoff = False
        while True:
            if hit_cutoff:
                break

            if max_pages is not None and page > max_pages:
                print(f"\nReached the max page limit of {max_pages}. Stopping.")
                break

            list_url = f"{BASE_URL}/news/local/all-latest?filter=30&page={page}"
            print(f"\n--- Scraping Page {page} ---")
            print(f"Loading {list_url}...")
            
            # Load list page
            try:
                driver.get(list_url)
                time.sleep(1.5)  # Wait for page elements to load
            except Exception as e:
                print(f"Error loading page {page}: {e}. Retrying...")
                time.sleep(5)
                continue
                
            # Check for the presence of "Last" pagination button immediately
            try:
                last_buttons = driver.find_elements(By.XPATH, "//a[contains(text(), 'Last')]")
                has_last_button = len(last_buttons) > 0
            except Exception as e:
                print(f"Error checking pagination on page {page}: {e}")
                has_last_button = False

            # Find all article links inside h3 elements
            h3_elements = driver.find_elements(By.TAG_NAME, "h3")
            articles_to_scrape = []
            
            for h3 in h3_elements:
                try:
                    a_elements = h3.find_elements(By.TAG_NAME, "a")
                    for a in a_elements:
                        href = a.get_attribute("href")
                        title = a.text.strip() or a.get_attribute("title") or ""
                        title = title.strip()
                        
                        art_id = extract_article_id(href)
                        if art_id and title:
                            art_url = f"{BASE_URL}/news/local/{art_id}"
                            articles_to_scrape.append((title, art_url))
                except Exception:
                    pass
            
            # Deduplicate articles on this page
            unique_articles = []
            seen = set()
            for title, url in articles_to_scrape:
                if url not in seen:
                    seen.add(url)
                    unique_articles.append((title, url))
                    
            print(f"Found {len(unique_articles)} articles on page {page}.")
            
            # Scrape each article
            for idx, (title, art_url) in enumerate(unique_articles):
                if art_url in scraped_urls:
                    print(f"  [{idx+1}/{len(unique_articles)}] Already scraped: {title}")
                    continue
                    
                print(f"  [{idx+1}/{len(unique_articles)}] Scraping: {title}")
                date_posted, date_obj = get_article_date(driver, art_url)
                print(f"    Date: {date_posted}")
                
                # Check cutoff date
                if cutoff_date is not None and date_obj is not None:
                    if date_obj < cutoff_date:
                        print(f"    Article date ({date_obj}) is older than cutoff ({cutoff_date}). Stopping.")
                        hit_cutoff = True
                        break

                # Write to CSV
                csv_writer.writerow([date_posted, CATEGORY, title, art_url])
                csv_file.flush()
                scraped_urls.add(art_url)
                
                # Sleep between articles to be polite
                time.sleep(0.5)
                
            if hit_cutoff:
                break

            if not has_last_button:
                print(f"\nNo 'Last' button found on page {page}. Reached the last page!")
                break
                
            page += 1
            
    finally:
        csv_file.close()
        driver.quit()
        print("\nSociety-Scraper(Thairath) finished successfully.")

if __name__ == "__main__":
    main()
