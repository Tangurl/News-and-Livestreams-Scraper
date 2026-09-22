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
BASE_URL = "https://www.khaosod.co.th"
SECTION_PATH = "economics"
CSV_FILE = os.path.join(SCRIPT_DIR, "khaosod_economy.csv")
CATEGORY = "เศรษฐกิจ"

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

def normalize_khaosod_date(raw_date):
    """
    Normalizes Khaosod raw date text (relative or absolute Thai BE)
    into standard Thai date string 'DD Mon YYYY HH:MM น.' and timezone-aware datetime.
    """
    raw_date = raw_date.strip()
    if not raw_date:
        return "N/A", None
        
    thai_months = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
    tz_ict = timezone(timedelta(hours=7))
    now_ict = datetime.now(tz_ict)
    
    # Relative: X นาทีที่แล้ว / X นาทีก่อน
    m_min = re.search(r"(\d+)\s*นาที", raw_date)
    if m_min:
        dt = now_ict - timedelta(minutes=int(m_min.group(1)))
        day = dt.day
        month_str = thai_months[dt.month - 1]
        be_year = dt.year + 543
        time_str = dt.strftime("%H:%M น.")
        formatted = f"{day} {month_str} {be_year} {time_str}"
        return formatted, dt
        
    # Relative: X ชั่วโมงที่แล้ว / X ชั่วโมงก่อน
    m_hr = re.search(r"(\d+)\s*ชั่วโมง", raw_date)
    if m_hr:
        dt = now_ict - timedelta(hours=int(m_hr.group(1)))
        day = dt.day
        month_str = thai_months[dt.month - 1]
        be_year = dt.year + 543
        time_str = dt.strftime("%H:%M น.")
        formatted = f"{day} {month_str} {be_year} {time_str}"
        return formatted, dt
        
    # Relative: X วันที่แล้ว / X วันก่อน
    m_day = re.search(r"(\d+)\s*วัน", raw_date)
    if m_day:
        dt = now_ict - timedelta(days=int(m_day.group(1)))
        day = dt.day
        month_str = thai_months[dt.month - 1]
        be_year = dt.year + 543
        time_str = dt.strftime("%H:%M น.")
        formatted = f"{day} {month_str} {be_year} {time_str}"
        return formatted, dt

    # Relative: วันนี้
    if "วันนี้" in raw_date:
        match_time = re.search(r"(\d{1,2})[:\.](\d{2})", raw_date)
        h, m = map(int, match_time.groups()) if match_time else (0, 0)
        dt = now_ict.replace(hour=h, minute=m, second=0, microsecond=0)
        day = dt.day
        month_str = thai_months[dt.month - 1]
        be_year = dt.year + 543
        time_str = dt.strftime("%H:%M น.")
        return f"{day} {month_str} {be_year} {time_str}", dt

    # Relative: เมื่อวานนี้
    if "เมื่อวาน" in raw_date:
        match_time = re.search(r"(\d{1,2})[:\.](\d{2})", raw_date)
        h, m = map(int, match_time.groups()) if match_time else (0, 0)
        yesterday = now_ict - timedelta(days=1)
        dt = yesterday.replace(hour=h, minute=m, second=0, microsecond=0)
        day = dt.day
        month_str = thai_months[dt.month - 1]
        be_year = dt.year + 543
        time_str = dt.strftime("%H:%M น.")
        return f"{day} {month_str} {be_year} {time_str}", dt

    # Absolute: e.g. '26 ส.ค. 2569' or '26 ส.ค. 2569 14:30 น.'
    clean_date = raw_date.replace(" น.", "").strip()
    parts = clean_date.split()
    if len(parts) >= 3 and parts[1] in thai_months:
        try:
            day = int(parts[0])
            month_idx = thai_months.index(parts[1]) + 1
            year_val = int(parts[2])
            be_year = year_val if year_val > 2400 else year_val + 543
            greg_year = be_year - 543
            
            time_part = parts[3] if len(parts) >= 4 and ":" in parts[3] else "00:00"
            h, m = map(int, time_part.split(":"))
            
            formatted = f"{day} {parts[1]} {be_year} {time_part} น."
            dt = datetime(greg_year, month_idx, day, h, m, tzinfo=tz_ict)
            return formatted, dt
        except Exception:
            pass
            
    return raw_date, None


def get_article_detail_time(driver, url, max_retries=3):
    """Visits the article page and extracts exact date & time from span.udsg__meta."""
    for attempt in range(max_retries):
        try:
            driver.get(url)
            time.sleep(0.6)
            
            metas = driver.find_elements(By.CSS_SELECTOR, "span.udsg__meta")
            date_str = None
            time_str = None
            if len(metas) >= 3:
                date_str = metas[0].text.strip()
                time_str = metas[2].text.strip()
            elif len(metas) >= 1:
                try:
                    t_el = driver.find_element(By.CSS_SELECTOR, "span.udsg__meta:nth-child(3)")
                    time_str = t_el.text.strip()
                except Exception:
                    pass
                date_str = metas[0].text.strip()
                
            if date_str and time_str:
                if not time_str.endswith("น."):
                    time_str += " น."
                full_raw = f"{date_str} {time_str}"
                formatted, dt_obj = normalize_khaosod_date(full_raw)
                if dt_obj:
                    return formatted, dt_obj
            elif date_str:
                formatted, dt_obj = normalize_khaosod_date(date_str)
                if dt_obj:
                    return formatted, dt_obj
        except Exception:
            pass
    return None, None

def get_page_articles(driver):
    """Finds and parses all articles inside card elements on the current page."""
    cards = driver.find_elements(By.CSS_SELECTOR, "div.col-md-6, div.col-md-4")
    articles = []
    
    for card in cards:
        try:
            # Find Title & Link inside h3 a
            h3_links = card.find_elements(By.CSS_SELECTOR, "h3 a")
            if not h3_links:
                continue
            a_tag = h3_links[0]
            href = a_tag.get_attribute("href")
            title = a_tag.get_attribute("textContent").strip()
            
            if not href or not title:
                continue
                
            # Filter out non-article links if any
            if f"/{SECTION_PATH}/" not in href:
                continue
                
            # Find Date / Time span
            raw_date = ""
            spans = card.find_elements(By.CSS_SELECTOR, "span")
            for s in spans:
                txt = s.get_attribute("textContent").strip()
                if txt and (any(x in txt for x in ['ก่อน', 'ที่แล้ว', 'วันนี้', 'เมื่อวาน', 'ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.', 'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.', '256'])):
                    raw_date = txt
                    break
                    
            articles.append({
                "title": title,
                "url": href,
                "raw_date": raw_date
            })
        except Exception:
            pass
            
    # Deduplicate within the page
    unique = []
    seen = set()
    for art in articles:
        if art["url"] not in seen:
            seen.add(art["url"])
            unique.append(art)
    return unique

def main():
    parser = argparse.ArgumentParser(description=f"Scrape Khaosod {CATEGORY} section.")
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
        help="Max days to scrape (1 for today only, 2 for today and yesterday, etc., or -1 for yesterday only)"
    )
    args = parser.parse_args()
    max_pages = args.pages
    max_days = args.days
    
    start_date = None
    end_date = None
    if max_days is not None:
        tz_ict = timezone(timedelta(hours=7))
        now_ict = datetime.now(tz_ict)
        start_of_today = now_ict.replace(hour=0, minute=0, second=0, microsecond=0)
        
        if max_days > 0:
            start_date = start_of_today - timedelta(days=max_days - 1)
        else:
            start_date = start_of_today - timedelta(days=abs(max_days))
            end_date = start_of_today
            
        if end_date:
            print(f"Scraping articles in date range: [{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}) (Yesterday only)")
        else:
            print(f"Scraping articles published on or after: {start_date.strftime('%Y-%m-%d %H:%M:%S %Z')}")

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
                next(reader, None) # Skip header
                for row in reader:
                    if len(row) >= 4:
                        scraped_urls.add(row[3])
            print(f"Loaded {len(scraped_urls)} already scraped articles from {CSV_FILE}.")
        except Exception as e:
            print("Error reading existing CSV:", e)
            
    print(f"Starting Khaosod {CATEGORY} scraper...")
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
                list_url = f"{BASE_URL}/{SECTION_PATH}"
            else:
                list_url = f"{BASE_URL}/{SECTION_PATH}/page/{page}"
                
            print(f"\n--- Scraping Page {page} ---")
            print(f"Loading URL: {list_url}")
            
            try:
                driver.get(list_url)
                time.sleep(5)
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
                
                print(f"  [{idx+1}/{len(new_articles)}] Scraping: {title}")
                # Fetch exact posted timestamp from article detail page
                detail_date, detail_dt = get_article_detail_time(driver, art_url)
                if detail_dt is not None:
                    date_posted = detail_date
                    date_obj = detail_dt
                else:
                    date_posted, date_obj = normalize_khaosod_date(raw_date)
                print(f"    Date: {date_posted}")
                
                # Check start date cutoff (older than start_date -> stop)
                if start_date is not None and date_obj is not None:
                    if date_obj < start_date:
                        print(f"    Article date ({date_obj}) is older than start date ({start_date}). Stopping.")
                        hit_cutoff = True
                        break
                        
                # Check end date cutoff (today's articles if scraping yesterday only -> skip writing)
                if end_date is not None and date_obj is not None:
                    if date_obj >= end_date:
                        print(f"    Skipping article from today ({date_obj}) since target range is before {end_date}.")
                        continue
                        
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
        print(f"\nKhaosod {CATEGORY} Scraper finished successfully.")

if __name__ == "__main__":
    main()
