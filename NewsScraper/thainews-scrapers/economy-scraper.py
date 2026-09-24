import os
import re
import csv
import time
import argparse
import urllib.request
from datetime import datetime, timezone, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

# Configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_URL = "https://www.thainewsonline.co"
CATEGORY_URL = "https://www.thainewsonline.co/tags/%E0%B8%82%E0%B9%88%E0%B8%B2%E0%B8%A7%E0%B9%80%E0%B8%A8%E0%B8%A3%E0%B8%A9%E0%B8%90%E0%B8%81%E0%B8%B4%E0%B8%88"
CATEGORY_NAME = "เศรษฐกิจ"
CSV_FILE = os.path.join(SCRIPT_DIR, "thainews_economy.csv")

def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    
    # Speed optimization
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

def normalize_thainews_date(raw_date_str):
    """Parses Thai date and time from ThaiNewsOnline detail page to standard BE date and datetime."""
    if not raw_date_str or raw_date_str == "N/A":
        return "N/A", None
        
    tz_ict = timezone(timedelta(hours=7))
    thai_months = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
    
    clean = raw_date_str.strip()
    
    # e.g. "13 ส.ค. 2569 | 11:27 น." or "13 ส.ค. 2569 11:27 น."
    m = re.search(r"(\d+)\s+([ก-์\.]+)\s+(\d+)(?:[^\d]*(\d{1,2})[:\.](\d{2}))?", clean)
    if m:
        day = int(m.group(1))
        month_str = m.group(2)
        year_str = m.group(3)
        h = int(m.group(4)) if m.group(4) else 0
        minute = int(m.group(5)) if m.group(5) else 0
        
        month_idx = 1
        for idx, month_name in enumerate(thai_months):
            if month_name in month_str or month_name.replace(".", "") in month_str:
                month_idx = idx + 1
                break
                
        year = int(year_str)
        if year < 100:
            year += 2500
            
        gregorian_year = year - 543
        dt_obj = datetime(gregorian_year, month_idx, day, h, minute, tzinfo=tz_ict)
        time_part = f"{h:02d}:{minute:02d} น." if m.group(4) else "00:00 น."
        formatted = f"{day} {thai_months[month_idx - 1]} {year} {time_part}"
        return formatted, dt_obj
        
    return clean, None

def get_page_articles(driver):
    """Finds all news articles on current ThaiNews tag listing page."""
    articles = driver.execute_script("""
    var out = [];
    var seen = new Set();
    
    var links = document.querySelectorAll('#section-1 a, a[href*="/news/"]');
    for (var a of links) {
        var href = a.href;
        if (!href || !href.includes('/news/')) continue;
        if (seen.has(href)) continue;
        
        var h3 = a.querySelector('h3, h2, h4');
        var title = h3 ? h3.innerText.trim() : a.innerText.trim();
        if (!title) continue;
        
        seen.add(href);
        out.push({url: href, title: title});
    }
    return out;
    """)
    return articles

def get_article_detail_info(url, max_retries=3):
    """Visits the ThaiNews article detail page and extracts exact title, published date and time."""
    # Fast path: fetch HTML directly via HTTP (takes ~50ms instead of 4s Chrome launch)
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=5) as response:
            html = response.read().decode('utf-8', errors='ignore')
            h1_match = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL)
            date_match = re.search(r'(\d{1,2}\s+[ก-๙\.]+\s+\d{2,4}\s*(?:\|\s*)?\d{1,2}[:\.]\d{2}\s*น\.)', html)
            if h1_match and date_match:
                title = re.sub(r'<[^>]+>', '', h1_match.group(1)).strip()
                date_str = date_match.group(1).strip()
                formatted_date, dt_obj = normalize_thainews_date(date_str)
                if dt_obj:
                    return title, formatted_date, dt_obj
    except Exception:
        pass

    for attempt in range(max_retries):
        driver = None
        try:
            driver = setup_driver()
            driver.get(url)
            
            # Wait for detail page elements
            res = None
            for _ in range(25):
                res = driver.execute_script("""
                    var h1 = document.querySelector('h1');
                    var dateEl = document.querySelector('.date, small.date, [class*="date"]');
                    
                    if (h1 && dateEl) {
                        return {
                            title: h1.innerText.trim(),
                            date_str: dateEl.innerText.trim()
                        };
                    }
                    return null;
                """)
                if res:
                    break
                time.sleep(0.3)
                
            if res:
                formatted_date, dt_obj = normalize_thainews_date(res.get('date_str'))
                title = res.get('title')
                return title, formatted_date, dt_obj
        except Exception:
            pass
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
    return None, "N/A", None

def main():
    parser = argparse.ArgumentParser(description="Scrape ThaiNews economy news.")
    parser.add_argument(
        "-p", "--pages",
        type=int,
        default=None,
        help="Max pages/clicks to load more"
    )
    parser.add_argument(
        "-d", "--days",
        type=int,
        default=None,
        help="Max days to scrape (1 for today only, 2 for today and yesterday, -1 for yesterday only, etc.)"
    )
    parser.add_argument(
        "-a", "--articles",
        type=int,
        default=None,
        help="Max number of articles to scrape (e.g. 1 for testing)"
    )
    parser.add_argument(
        "--single",
        action="store_true",
        help="Scrape exactly 1 article for testing"
    )
    args = parser.parse_args()
    max_pages = args.pages
    max_days = args.days
    max_articles = 1 if args.single else args.articles
    
    start_date = None
    end_date = None
    
    if max_days is not None:
        tz_ict = timezone(timedelta(hours=7))
        now_ict = datetime.now(tz_ict)
        today_start = now_ict.replace(hour=0, minute=0, second=0, microsecond=0)
        
        if max_days == -1:
            start_date = today_start - timedelta(days=1)
            end_date = today_start
            print(f"Scraping articles strictly published yesterday: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
        elif max_days < -1:
            days_back = abs(max_days)
            start_date = today_start - timedelta(days=days_back)
            end_date = today_start
            print(f"Scraping articles strictly published in past {days_back} days (excluding today): {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
        else:
            start_date = (today_start - timedelta(days=max_days - 1))
            print(f"Scraping articles published on or after: {start_date.strftime('%Y-%m-%d %H:%M:%S %Z')}")

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
            
    print("Starting ThaiNews economy news scraper...")
    driver = setup_driver()
    page = 1
    hit_cutoff = False
    scraped_count = 0
    
    try:
        print(f"Loading URL: {CATEGORY_URL}")
        driver.get(CATEGORY_URL)
        time.sleep(5)
        
        # Paginate / Click load more until max_pages or cutoff
        if max_pages is not None:
            max_auto_pages = max_pages
        elif max_days is not None:
            days_count = abs(max_days)
            max_auto_pages = 5 if days_count <= 2 else min(days_count * 3, 15)
        else:
            max_auto_pages = 5

        should_paginate = max_auto_pages > 1
        while should_paginate:
            if page >= max_auto_pages:
                print(f"Reached pagination limit of {max_auto_pages} pages. Proceeding to extract articles.")
                break
                
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.5)
            
            try:
                btn = driver.find_element(By.XPATH, "//button[contains(., 'ดูเพิ่มเติม') or @title='ดูทั้งหมด']")
            except Exception:
                try:
                    btn = driver.find_element(By.CSS_SELECTOR, "button.flex-center:nth-child(1), .widget-loading button")
                except Exception:
                    btn = None
                    
            if not btn:
                print("No more 'ดูเพิ่มเติม' button found.")
                break
                
            initial_count = len(get_page_articles(driver))
            print(f"Clicking 'ดูเพิ่มเติม' (button.flex-center) - page {page + 1}/{max_auto_pages}...")
            try:
                driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", btn)
                time.sleep(0.5)
                driver.execute_script("arguments[0].click();", btn)
                
                for _ in range(40):
                    time.sleep(0.3)
                    if len(get_page_articles(driver)) > initial_count:
                        break
            except Exception as e:
                print(f"Error clicking load more button: {e}")
                break
            page += 1
            
        # Extract articles
        articles = get_page_articles(driver)
        new_articles = [art for art in articles if art["url"] not in scraped_urls]
        print(f"\nFound {len(articles)} total articles on page (newly discovered: {len(new_articles)}).")
        
        for idx, art in enumerate(new_articles):
            art_url = art["url"]
            list_title = art["title"]
            
            print(f"  [{idx+1}/{len(new_articles)}] Scraping: {list_title}")
            
            # Fetch exact detail page timestamp and headline
            detail_title, date_posted, date_obj = get_article_detail_info(art_url)
            title = detail_title or list_title
            print(f"    Date: {date_posted} | Title: {title}")
            
            # Check start date cutoff
            if start_date is not None and date_obj is not None:
                if date_obj < start_date:
                    print(f"    Article date ({date_obj}) is older than start date ({start_date}). Stopping.")
                    hit_cutoff = True
                    break
                    
            # Check end date cutoff
            if end_date is not None and date_obj is not None:
                if date_obj >= end_date:
                    print(f"    Skipping article from today ({date_obj}) since target range is before {end_date}.")
                    continue
                    
            # Write to CSV
            csv_writer.writerow([date_posted, CATEGORY_NAME, title, art_url])
            csv_file.flush()
            scraped_urls.add(art_url)
            scraped_count += 1
            
            if max_articles is not None and scraped_count >= max_articles:
                print(f"\nReached article limit of {max_articles}. Stopping.")
                break
                
    finally:
        csv_file.close()
        driver.quit()
        print(f"\nThaiNews Scraper finished successfully. Total articles scraped: {scraped_count}")

if __name__ == "__main__":
    main()
