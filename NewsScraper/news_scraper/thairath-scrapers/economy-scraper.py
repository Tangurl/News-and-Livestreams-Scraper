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
LIST_URL = "https://www.thairath.co.th/money/latest"
CSV_FILE = os.path.join(SCRIPT_DIR, "thairath_economy.csv")
CATEGORY = "เศรษฐกิจ"

THAI_MONTHS = [
    "", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
    "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."
]

def format_thai_date(dt):
    if not dt:
        return "N/A"
    tz_ict = timezone(timedelta(hours=7))
    if dt.tzinfo is not None:
        dt_ict = dt.astimezone(tz_ict)
    else:
        dt_ict = dt.replace(tzinfo=tz_ict)
        
    day = dt_ict.day
    month_str = THAI_MONTHS[dt_ict.month]
    year = dt_ict.year + 543
    time_str = dt_ict.strftime("%H:%M")
    return f"{day} {month_str} {year} {time_str} น."

def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    # Speed optimization: block images and set eager page load strategy
    chrome_options.page_load_strategy = 'eager'
    chrome_prefs = {
        "profile.default_content_setting_values.images": 2
    }
    chrome_options.add_experimental_option("prefs", chrome_prefs)
    
    # Anti-detection settings
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(options=chrome_options)
    driver.set_page_load_timeout(30)
    
    # Hide webdriver property
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    

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

def clean_article_url(href):
    if not href:
        return None
    # Strip any fragments or query params
    url = href.split('#')[0].split('?')[0]
    return url.strip()

def extract_article_id(href):
    """Extracts article ID from Thairath Money URL href."""
    clean_url = clean_article_url(href)
    if not clean_url:
        return None
    match = re.search(r"money/(?:[^/]+/)+(\d+)", clean_url)
    if match:
        return match.group(1)
    return None

def get_article_date_in_tab(driver, url, max_retries=3):
    """Opens the article URL in a new tab, scrapes its date, closes the tab, and returns to the original tab."""
    main_window = driver.current_window_handle
    date_text, date_obj = "N/A", None
    
    try:
        driver.execute_script("window.open(arguments[0], '_blank');", url)
        time.sleep(0.2)
        driver.switch_to.window(driver.window_handles[-1])
        
        # Explicit wait for page metadata elements to load
        try:
            WebDriverWait(driver, 8).until(
                lambda d: d.find_elements(By.XPATH, "//meta[@property='og:article:published_time' or @property='article:published_time']") or 
                          d.find_elements(By.XPATH, "//script[@type='application/ld+json']")
            )
        except Exception:
            pass
            
        for attempt in range(max_retries):
            try:
                # Extract ISO string from meta tags
                iso_str = None
                try:
                    meta_el = driver.find_element(By.XPATH, "//meta[@property='og:article:published_time' or @property='article:published_time']")
                    iso_str = meta_el.get_attribute("content")
                except Exception:
                    pass
                    
                # Fallback for ISO string from JSON-LD schema if meta tag missing
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
                if iso_str:
                    try:
                        date_obj = datetime.fromisoformat(iso_str)
                        date_text = format_thai_date(date_obj)
                        break
                    except Exception:
                        pass
                        
                time.sleep(1.0)
            except Exception as e:
                print(f"  [Attempt {attempt+1}/{max_retries}] Error scraping {url}: {e}")
                time.sleep(1)
                
    except Exception as e:
        print(f"Error handling tab for {url}: {e}")
    finally:
        try:
            if len(driver.window_handles) > 1:
                driver.close()
        except Exception:
            pass
        try:
            driver.switch_to.window(main_window)
        except Exception:
            pass
            
    return date_text, date_obj

def find_load_more_button(driver):
    try:
        buttons = driver.find_elements(By.TAG_NAME, "button")
        for btn in buttons:
            if "Load More" in btn.text:
                return btn
    except Exception:
        pass
    return None

def get_unique_articles(driver):
    try:
        anchors = driver.find_elements(By.TAG_NAME, "a")
        article_links = []
        pattern = re.compile(r"money/(?:[^/]+/)+(\d+)")
        for a in anchors:
            try:
                href = a.get_attribute("href")
                title = a.text.strip() or a.get_attribute("title") or ""
                title = title.replace("\n", " ").strip()
                if href and title:
                    clean_url = clean_article_url(href)
                    if pattern.search(clean_url):
                        article_links.append((clean_url, title))
            except Exception:
                pass
        unique_articles = []
        seen = set()
        for url, title in article_links:
            if url not in seen:
                seen.add(url)
                unique_articles.append((url, title))
        return unique_articles
    except Exception:
        return []

def main():
    parser = argparse.ArgumentParser(description="Scrape Thairath Money economy section.")
    parser.add_argument(
        "-p", "--pages",
        type=int,
        default=None,
        help="Max number of pages/clicks to load (default: scrape all content until the end)"
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
        print(f"Loading {LIST_URL}...")
        driver.get(LIST_URL)
        
        # Wait up to 10 seconds for at least one article link to appear
        try:
            WebDriverWait(driver, 10).until(
                lambda d: len(get_unique_articles(d)) > 0
            )
        except Exception:
            print("Timed out waiting for initial article list to load.")
        
        clicks_done = 0
        processed_urls = set()
        hit_cutoff = False
        
        while True:
            unique_articles = get_unique_articles(driver)
            print(f"\nFound {len(unique_articles)} unique articles on the page (clicks done: {clicks_done}).")
            
            # Filter to only articles we haven't processed in this run yet
            unprocessed_articles = [x for x in unique_articles if x[0] not in processed_urls]
            print(f"{len(unprocessed_articles)} of them are new to process in this run.")
            
            if not unprocessed_articles and clicks_done > 0:
                print("No new articles found. Reached the end of content.")
                break
                
            for url, title in unprocessed_articles:
                processed_urls.add(url)
                
                if url in scraped_urls:
                    print(f"  Already scraped (in CSV): {title}")
                    continue
                    
                print(f"  Scraping: {title} ({url})")
                date_posted, date_obj = get_article_date_in_tab(driver, url)
                print(f"    Date: {date_posted}")
                
                # Check cutoff date
                if cutoff_date is not None and date_obj is not None:
                    tz_ict = timezone(timedelta(hours=7))
                    if date_obj.tzinfo is None:
                        date_obj_ict = date_obj.replace(tzinfo=tz_ict)
                    else:
                        date_obj_ict = date_obj.astimezone(tz_ict)
                        
                    if date_obj_ict < cutoff_date:
                        print(f"    Article date ({date_obj_ict}) is older than cutoff ({cutoff_date}). Stopping.")
                        hit_cutoff = True
                        break
                
                # Write to CSV
                csv_writer.writerow([date_posted, CATEGORY, title, url])
                csv_file.flush()
                scraped_urls.add(url)
                
                time.sleep(0.5)
                
            if hit_cutoff:
                break
                
            # Check page limit
            if max_pages is not None and (clicks_done + 1) >= max_pages:
                print(f"\nReached page limit ({max_pages}). Stopping.")
                break
                
            # Find and click Load More button
            btn = find_load_more_button(driver)
            if not btn:
                print("\nNo 'Load More' button found. Reached the end of content.")
                break
                
            print(f"\nClicking 'Load More' button (click #{clicks_done + 1})...")
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
            time.sleep(0.5)
            driver.execute_script("arguments[0].click();", btn)
            clicks_done += 1
            
            # Wait dynamically for the number of unique articles to increase
            prev_count = len(unique_articles)
            try:
                WebDriverWait(driver, 10).until(
                    lambda d: len(get_unique_articles(d)) > prev_count
                )
            except Exception:
                print("Timed out waiting for new articles to load after clicking Load More.")
            
    finally:
        csv_file.close()
        driver.quit()
        print("\nThairath Money Economy scraper finished successfully.")

if __name__ == "__main__":
    main()
