import os
import re
import csv
import time
import argparse
from datetime import datetime, timezone, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

# Configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_URL = "https://mgronline.com"
CSV_FILE = os.path.join(SCRIPT_DIR, "mgronline_crime.csv")
CATEGORY = "อาชญากรรม"

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
    
    # Add common headers to avoid detection
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(options=chrome_options)
    driver.set_page_load_timeout(30)
    
    # Native CDP Ad blocker
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

def normalize_mgronline_date(date_text):
    """Parses MGR Online date format (e.g. '2026/06/11 15:59:00')
    to absolute BE short format and datetime object."""
    date_text = date_text.strip()
    if not date_text:
        return "N/A", None
        
    try:
        dt = datetime.strptime(date_text, "%Y/%m/%d %H:%M:%S")
        year = dt.year
        month = dt.month
        day = dt.day
        hour = dt.hour
        minute = dt.minute
        
        be_year = year + 543
        
        short_months = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
        month_str = short_months[month - 1]
        
        formatted = f"{day} {month_str} {be_year} {hour:02d}:{minute:02d} น."
        
        tz_ict = timezone(timedelta(hours=7))
        dt_obj = datetime(year, month, day, hour, minute, tzinfo=tz_ict)
        return formatted, dt_obj
    except Exception:
        return date_text, None

def get_detail_page_date(driver, url, max_retries=3):
    """Navigates to the article detail page and scrapes its publication date.
    Returns (date_text, date_obj)."""
    for attempt in range(max_retries):
        try:
            driver.get(url)
            time.sleep(1)
            html = driver.page_source
            
            # Find datePublished
            match_pub = re.search(r'"datePublished"\s*:\s*"([^"]+)"', html)
            if match_pub:
                iso_str = match_pub.group(1)
                try:
                    if iso_str.endswith("Z"):
                        iso_str = iso_str.replace("Z", "+00:00")
                    dt = datetime.fromisoformat(iso_str)
                    
                    year = dt.year
                    month = dt.month
                    day = dt.day
                    hour = dt.hour
                    minute = dt.minute
                    
                    be_year = year + 543
                    
                    short_months = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
                    month_str = short_months[month - 1]
                    
                    formatted = f"{day} {month_str} {be_year} {hour:02d}:{minute:02d} น."
                    
                    tz_ict = timezone(timedelta(hours=7))
                    dt_obj = dt.astimezone(tz_ict)
                    return formatted, dt_obj
                except Exception:
                    pass
            
            # Fallback to searching meta tags
            match_meta = re.search(r'meta[^>]+property="article:published_time"[^>]+content="([^"]+)"', html)
            if match_meta:
                content_str = match_meta.group(1).strip()
                try:
                    iso_str = content_str.replace(" ", "T")
                    dt = datetime.fromisoformat(iso_str)
                    
                    year = dt.year
                    month = dt.month
                    day = dt.day
                    hour = dt.hour
                    minute = dt.minute
                    
                    be_year = year + 543
                    
                    short_months = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
                    month_str = short_months[month - 1]
                    
                    formatted = f"{day} {month_str} {be_year} {hour:02d}:{minute:02d} น."
                    
                    tz_ict = timezone(timedelta(hours=7))
                    dt_obj = dt.astimezone(tz_ict)
                    return formatted, dt_obj
                except Exception:
                    pass
                    
        except Exception as e:
            print(f"    [Attempt {attempt+1}/{max_retries}] Error loading detail page {url}: {e}")
            time.sleep(2)
            
    return "N/A", None

def get_page_articles(driver):
    """Finds and parses all articles on current page."""
    # We look for a.link where href contains '/crime/detail/'
    cards = driver.find_elements(By.CSS_SELECTOR, "a.link[href*='/crime/detail/']")
    articles = []
    
    for card in cards:
        try:
            # Find Link
            href = card.get_attribute("href")
            
            # Find Title in figcaption
            fig = card.find_element(By.CSS_SELECTOR, "figcaption")
            title = fig.get_attribute("textContent").strip()
            
            # Find Date inside time.p-date-time-item (optional)
            raw_date = None
            try:
                time_el = card.find_element(By.CSS_SELECTOR, "time.p-date-time-item")
                raw_date = time_el.get_attribute("data-pdatatimedata").strip()
            except Exception:
                pass
            
            articles.append({
                "title": title,
                "url": href,
                "raw_date": raw_date
            })
        except Exception:
            pass
            
    # Deduplicate
    unique = []
    seen = set()
    for art in articles:
        if art["url"] not in seen:
            seen.add(art["url"])
            unique.append(art)
    return unique

def main():
    parser = argparse.ArgumentParser(description="Scrape MGR Online crime section.")
    parser.add_argument(
        "-p", "--pages",
        type=int,
        default=None,
        help="Max pages to scrape"
    )
    parser.add_argument(
        "-d", "--days",
        type=int,
        default=None,
        help="Max days to scrape (1 for today only, 2 for today and yesterday, etc.)"
    )
    args = parser.parse_args()
    max_pages = args.pages
    max_days = args.days
    
    cutoff_date = None
    if max_days is not None:
        tz_ict = timezone(timedelta(hours=7))
        now_ict = datetime.now(tz_ict)
        cutoff_date = (now_ict - timedelta(days=max_days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
        print(f"Scraping articles published on or after: {cutoff_date.strftime('%Y-%m-%d %H:%M:%S %Z')}")

    driver = setup_driver()
    
    # Initialize CSV
    os.makedirs(SCRIPT_DIR, exist_ok=True)
    file_exists = os.path.exists(CSV_FILE)
    csv_file = open(CSV_FILE, "a", encoding="utf-8", newline="")
    csv_writer = csv.writer(csv_file)
    if not file_exists:
        csv_writer.writerow(["date", "category", "article title", "article link"])
        csv_file.flush()
        
    scraped_urls = set()
    if file_exists:
        try:
            with open(CSV_FILE, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                next(reader, None)
                for row in reader:
                    if len(row) >= 4:
                        scraped_urls.add(row[3])
            print(f"Loaded {len(scraped_urls)} already scraped articles from {CSV_FILE}.")
        except Exception as e:
            print("Error reading existing CSV:", e)
            
    print("Starting MGR Online Crime scraper...")
    try:
        page = 1
        hit_cutoff = False
        consecutive_empty_batches = 0
        
        while True:
            if hit_cutoff:
                break
                
            if max_pages is not None and page > max_pages:
                print(f"\nReached max pages limit of {max_pages}. Stopping.")
                break
                
            # MGR Online crime pagination formula
            start_val = (page - 1) * 10
            list_url = f"{BASE_URL}/crime/4012/start={start_val}"
                
            print(f"\n--- Scraping Page {page} ---")
            print(f"Loading URL: {list_url}")
            
            try:
                driver.get(list_url)
                time.sleep(3)
            except Exception as e:
                print(f"Error loading page {page}: {e}")
                if page == 1:
                    import sys
                    sys.exit(1)
                else:
                    break
                    
            articles = get_page_articles(driver)
            new_articles = [art for art in articles if art["url"] not in scraped_urls]
            print(f"Found {len(articles)} total articles on page (newly discovered: {len(new_articles)}).")
            
            if page == 1 and not articles:
                print("Error: No articles found on page 1. Target structure might have changed.")
                import sys
                sys.exit(1)
                
            if not articles:
                print("No articles found on this page. Stopping.")
                break
                
            if len(new_articles) == 0:
                consecutive_empty_batches += 1
            else:
                consecutive_empty_batches = 0
                
            if consecutive_empty_batches >= 3:
                print(f"No new articles found for {consecutive_empty_batches} consecutive pages. Stopping.")
                break
                
            for idx, art in enumerate(new_articles):
                title = art["title"]
                art_url = art["url"]
                raw_date = art["raw_date"]
                
                print(f"  [{idx+1}/{len(new_articles)}] Scraping: {title}")
                
                if raw_date:
                    date_posted, date_obj = normalize_mgronline_date(raw_date)
                else:
                    # Fetch from detail page in background tab
                    print(f"    No visible date. Loading detail page in tab...")
                    main_handle = driver.current_window_handle
                    try:
                        driver.execute_script("window.open(arguments[0], '_blank');", art_url)
                        driver.switch_to.window(driver.window_handles[-1])
                        date_posted, date_obj = get_detail_page_date(driver, art_url)
                        driver.close()
                    except Exception as e:
                        print(f"      Error loading detail page in tab: {e}")
                        date_posted, date_obj = "N/A", None
                        try:
                            if len(driver.window_handles) > 1:
                                driver.close()
                        except:
                            pass
                    driver.switch_to.window(main_handle)
                    
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
                
            if hit_cutoff:
                break
                
            page += 1
            
    finally:
        csv_file.close()
        driver.quit()
        print("\nMGR Online Crime Scraper finished successfully.")

if __name__ == "__main__":
    main()
