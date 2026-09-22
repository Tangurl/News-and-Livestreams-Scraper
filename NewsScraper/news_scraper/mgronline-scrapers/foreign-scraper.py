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
CSV_FILE = os.path.join(SCRIPT_DIR, "mgronline_foreign.csv")
CATEGORY = "ต่างประเทศ"

# Subcategories under around/9040
SUBCATEGORIES = [
    {"id": "9100", "name": "อเมริกา"},
    {"id": "9101", "name": "ยุโรป"},
    {"id": "9104", "name": "ตะวันออกกลาง"},
    {"id": "9106", "name": "เอเชีย"},
    {"id": "9107", "name": "อาเซียน"},
    {"id": "9103", "name": "แอฟริกา"},
    {"id": "9105", "name": "โอเชียเนีย"},
    {"id": "9109", "name": "องค์กรระหว่างประเทศ"},
    {"id": "9102", "name": "รัสเซียและกลุ่มประเทศสัจจะ"}
]

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

def get_page_articles(driver):
    """Finds and parses all articles on current page."""
    # We look for a.link where href contains '/around/detail/'
    cards = driver.find_elements(By.CSS_SELECTOR, "a.link[href*='/around/detail/']")
    articles = []
    
    for card in cards:
        try:
            # Find Link
            href = card.get_attribute("href")
            
            # Find Title in figcaption
            fig = card.find_element(By.CSS_SELECTOR, "figcaption")
            title = fig.get_attribute("textContent").strip()
            
            # Find Date inside time.p-date-time-item
            time_el = card.find_element(By.CSS_SELECTOR, "time.p-date-time-item")
            raw_date = time_el.get_attribute("data-pdatatimedata").strip()
            
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
    parser = argparse.ArgumentParser(description="Scrape MGR Online foreign section (Around the World).")
    parser.add_argument(
        "-p", "--pages",
        type=int,
        default=None,
        help="Max pages to scrape per subcategory"
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
            
    print("Starting MGR Online Around (Foreign) scraper across all subsections...")
    try:
        # Loop through each subcategory
        for subcat in SUBCATEGORIES:
            subcat_id = subcat["id"]
            subcat_name = subcat["name"]
            print(f"\n==========================================")
            print(f"Scraping Subsection: {subcat_name} (ID: {subcat_id})")
            print(f"==========================================")
            
            page = 1
            hit_cutoff = False
            consecutive_empty_batches = 0
            
            while True:
                if hit_cutoff:
                    break
                    
                if max_pages is not None and page > max_pages:
                    print(f"  Reached max pages limit of {max_pages} for {subcat_name}. Moving to next subsection.")
                    break
                    
                # MGR Online query parameter pagination
                start_val = (page - 1) * 10
                list_url = f"{BASE_URL}/around/9040/{subcat_id}/start={start_val}"
                
                print(f"  --- [{subcat_name}] Scraping Page {page} ---")
                print(f"  Loading URL: {list_url}")
                
                try:
                    driver.get(list_url)
                    time.sleep(3)
                except Exception as e:
                    print(f"  Error loading page {page}: {e}")
                    break
                    
                articles = get_page_articles(driver)
                new_articles = [art for art in articles if art["url"] not in scraped_urls]
                print(f"  Found {len(articles)} total articles on page (newly discovered: {len(new_articles)}).")
                
                if not articles:
                    print("  No articles found on this page. Moving to next subsection.")
                    break
                    
                if len(new_articles) == 0:
                    consecutive_empty_batches += 1
                else:
                    consecutive_empty_batches = 0
                    
                if consecutive_empty_batches >= 3:
                    print(f"  No new articles found for {consecutive_empty_batches} consecutive pages. Stopping this subsection.")
                    break
                    
                for idx, art in enumerate(new_articles):
                    title = art["title"]
                    art_url = art["url"]
                    raw_date = art["raw_date"]
                    
                    print(f"    [{idx+1}/{len(new_articles)}] Scraping: {title}")
                    date_posted, date_obj = normalize_mgronline_date(raw_date)
                    print(f"      Date: {date_posted}")
                    
                    # Check cutoff date
                    if cutoff_date is not None and date_obj is not None:
                        if date_obj < cutoff_date:
                            print(f"      Article date ({date_obj}) is older than cutoff ({cutoff_date}). Stopping this subsection.")
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
        print("\nMGR Online Around (Foreign) Scraper finished successfully.")

if __name__ == "__main__":
    main()
