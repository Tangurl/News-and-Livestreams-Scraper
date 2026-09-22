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
BASE_URL = "https://www.dailynews.co.th"
CSV_FILE = os.path.join(SCRIPT_DIR, "dailynews_foreign.csv")
CATEGORY = "ต่างประเทศ"

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
    
    # Anti-detection settings to bypass Cloudflare
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

def normalize_dailynews_date(date_text, time_text):
    """Parses Daily News date format (e.g. '11 มิถุนายน 2569' and '10:24 น.')
    to absolute BE short format and datetime object."""
    date_text = date_text.strip()
    time_text = time_text.strip()
    
    if not date_text:
        return "N/A", None
        
    long_months = ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน", "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]
    short_months = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
    
    # Replace long month with short month
    for lm, sm in zip(long_months, short_months):
        if lm in date_text:
            date_text = date_text.replace(lm, sm)
            break
            
    formatted = f"{date_text} {time_text}"
    formatted = re.sub(r"\s+", " ", formatted).strip()
    
    # Parse to datetime (ICT timezone)
    try:
        parts = date_text.split()
        day = int(parts[0])
        month_str = parts[1]
        year = int(parts[2])
        
        month_idx = short_months.index(month_str) + 1
        gregorian_year = year - 543
        
        time_part = time_text.replace(" น.", "").strip()
        h, m = map(int, time_part.split(":"))
        
        tz_ict = timezone(timedelta(hours=7))
        dt_obj = datetime(gregorian_year, month_idx, day, h, m, tzinfo=tz_ict)
        return formatted, dt_obj
    except Exception:
        return formatted, None

def get_page_articles(driver):
    """Finds and parses all articles inside Elementor loop cards on current page."""
    cards = driver.find_elements(By.CSS_SELECTOR, "article[class*='elementor-post']")
    articles = []
    
    for card in cards:
        try:
            # Find Title & Link
            a = card.find_element(By.CSS_SELECTOR, "h3[class*='elementor-post__title'] a")
            title = a.get_attribute("textContent").strip()
            href = a.get_attribute("href")
            
            # Find Date & Time inside elementor-post__meta-data
            date_el = card.find_element(By.CSS_SELECTOR, "span.elementor-post-date")
            time_el = card.find_element(By.CSS_SELECTOR, "span.elementor-post-time")
            
            raw_date = date_el.get_attribute("textContent").strip()
            raw_time = time_el.get_attribute("textContent").strip()
            
            articles.append({
                "title": title,
                "url": href,
                "raw_date": raw_date,
                "raw_time": raw_time
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
    parser = argparse.ArgumentParser(description="Scrape Daily News foreign section.")
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
            
    print("Starting Daily News Foreign scraper...")
    try:
        page = 1
        hit_cutoff = False
        
        while True:
            if hit_cutoff:
                break
                
            if max_pages is not None and page > max_pages:
                print(f"\nReached max pages limit of {max_pages}. Stopping.")
                break
                
            if page == 1:
                list_url = f"{BASE_URL}/news/news_group/foreign/"
            else:
                list_url = f"{BASE_URL}/news/news_group/foreign/page/{page}/"
                
            print(f"\n--- Scraping Page {page} ---")
            print(f"Loading URL: {list_url}")
            
            try:
                driver.get(list_url)
                time.sleep(4)
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
                
            for idx, art in enumerate(new_articles):
                title = art["title"]
                art_url = art["url"]
                raw_date = art["raw_date"]
                raw_time = art["raw_time"]
                
                print(f"  [{idx+1}/{len(new_articles)}] Scraping: {title}")
                date_posted, date_obj = normalize_dailynews_date(raw_date, raw_time)
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
        print("\nDaily News Foreign Scraper finished successfully.")

if __name__ == "__main__":
    main()
