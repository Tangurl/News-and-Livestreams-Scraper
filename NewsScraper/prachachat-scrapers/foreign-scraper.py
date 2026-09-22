import os
import re
import csv
import time
import argparse
from datetime import datetime, timezone, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException

# Configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_URL = "https://www.prachachat.net"
CATEGORY_URL = "https://www.prachachat.net/world"
CSV_FILE = os.path.join(SCRIPT_DIR, "prachachat_foreign.csv")
CATEGORY_NAME = "ต่างประเทศ"

def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.page_load_strategy = 'eager'
    chrome_options.add_argument("--window-size=1920,1080")
    
    chrome_prefs = {
        "profile.default_content_setting_values.images": 2
    }
    chrome_options.add_experimental_option("prefs", chrome_prefs)
    
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(options=chrome_options)
    driver.set_page_load_timeout(30)
    
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

def normalize_prachachat_date(raw_date_str):
    """Parses Thai date string from Prachachat (e.g. '29 ส.ค. 2569 | 17:20น.')
    to standard BE date format and datetime object."""
    if not raw_date_str or raw_date_str == "N/A":
        return "N/A", None
        
    tz_ict = timezone(timedelta(hours=7))
    thai_months = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
    
    clean = raw_date_str.strip()
    m = re.search(r"(\d{1,2})\s+([ก-์\.]+)\s+(\d{4})(?:[^\d]*(\d{1,2})[\.:](\d{2}))?", clean)
    if m:
        day = int(m.group(1))
        month_str = m.group(2)
        year_num = int(m.group(3))
        h = int(m.group(4)) if m.group(4) else 0
        minute = int(m.group(5)) if m.group(5) else 0
        
        month_idx = 1
        for idx, month_name in enumerate(thai_months):
            if month_name in month_str or month_name.replace(".", "") in month_str:
                month_idx = idx + 1
                break
                
        if year_num < 2400:
            gregorian_year = year_num
            be_year = year_num + 543
        else:
            be_year = year_num
            gregorian_year = year_num - 543
            
        dt_obj = datetime(gregorian_year, month_idx, day, h, minute, tzinfo=tz_ict)
        time_part = f"{h:02d}:{minute:02d} น." if m.group(4) else "00:00 น."
        formatted = f"{day} {thai_months[month_idx - 1]} {be_year} {time_part}"
        return formatted, dt_obj
        
    return clean, None

def get_page_articles(driver):
    """Finds all article cards on the current category page specifically in the category list container."""
    articles = driver.execute_script(r"""
    var articles = Array.from(document.querySelectorAll('.grid > article, article.group'));
    var res = [];
    var seen = new Set();
    
    for (var art of articles) {
        var a = art.querySelector('a');
        if (!a || !a.href || seen.has(a.href) || !a.href.includes('/news-')) continue;
        seen.add(a.href);
        
        var h = art.querySelector('h2.text-xl, h2, h3, .text-xl, .text-lg');
        var rawTitle = h ? h.innerText.trim() : a.innerText.trim();
        
        // Clean out category header if present (e.g. "Economic\nTitle...")
        var lines = rawTitle.split('\n').map(l => l.trim()).filter(l => l.length > 0);
        var title = lines.length > 0 ? lines[lines.length - 1] : rawTitle;
        if (!title || title.length < 5) continue;
        
        res.push({
            url: a.href,
            title: title
        });
    }
    return res;
    """)
    return articles

def get_article_detail(driver, url, max_retries=2):
    """Opens detail page in a separate tab to extract publish date and clean headline."""
    main_window = driver.current_window_handle
    for attempt in range(max_retries):
        try:
            driver.execute_script("window.open(arguments[0], '_blank');", url)
            time.sleep(0.5)
            windows = driver.window_handles
            if len(windows) > 1:
                driver.switch_to.window(windows[-1])
            else:
                driver.get(url)
                
            res = None
            for _ in range(15):
                res = driver.execute_script(r"""
                    var h1 = document.querySelector('h1');
                    var pubDate = document.querySelector('.publish-date');
                    if (pubDate && pubDate.innerText.trim().length > 0) {
                        return {
                            title: h1 ? h1.innerText.trim() : document.title,
                            raw_date: pubDate.innerText.trim()
                        };
                    }
                    return null;
                """)
                if res:
                    break
                time.sleep(0.3)
                
            if len(driver.window_handles) > 1:
                driver.close()
                driver.switch_to.window(main_window)
                
            if res:
                formatted_date, dt_obj = normalize_prachachat_date(res.get('raw_date'))
                return res.get('title'), formatted_date, dt_obj
        except Exception:
            try:
                if len(driver.window_handles) > 1:
                    driver.close()
                driver.switch_to.window(main_window)
            except Exception:
                pass
    return None, "N/A", None

def main():
    parser = argparse.ArgumentParser(description="Scrape Prachachat world news.")
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
        help="Max days to scrape (1 for today only, 2 for today and yesterday, -1 for yesterday only, etc.)"
    )
    parser.add_argument(
        "-a", "--articles",
        type=int,
        default=None,
        help="Max number of articles to scrape"
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
            
    print("Starting Prachachat World news scraper...")
    driver = setup_driver()
    page = 1
    hit_cutoff = False
    scraped_count = 0
    
    try:
        while True:
            if hit_cutoff:
                break
                
            if max_pages is not None and page > max_pages:
                print(f"\nReached max pages limit of {max_pages}. Stopping.")
                break
                
            if max_articles is not None and scraped_count >= max_articles:
                break
                
            page_url = f"{CATEGORY_URL}/page/{page}" if page > 1 else CATEGORY_URL
            print(f"\n--- [Page {page}] Loading: {page_url} ---")
            try:
                driver.get(page_url)
            except TimeoutException:
                driver.execute_script("window.stop();")
            time.sleep(3)
            
            articles = []
            for _ in range(15):
                articles = get_page_articles(driver)
                if articles:
                    break
                time.sleep(0.5)
                
            if not articles:
                print("No articles found on page.")
                break
                
            new_articles = [art for art in articles if art["url"] not in scraped_urls]
            print(f"Found {len(articles)} total articles on page (newly discovered: {len(new_articles)}).")
            
            for idx, art in enumerate(new_articles):
                art_url = art["url"]
                title = art["title"]
                
                print(f"  [{idx+1}/{len(new_articles)}] Scraping: {title}")
                
                d_title, formatted_date, date_obj = get_article_detail(driver, art_url)
                if d_title:
                    title = d_title
                    
                print(f"    Date: {formatted_date} | Cat: {CATEGORY_NAME} | Title: {title}")
                
                if start_date is not None and date_obj is not None:
                    if date_obj < start_date:
                        print(f"    Article date ({date_obj}) is older than start date ({start_date}). Stopping.")
                        hit_cutoff = True
                        break
                        
                if end_date is not None and date_obj is not None:
                    if date_obj >= end_date:
                        print(f"    Skipping article from today ({date_obj}) since target range is before {end_date}.")
                        continue
                        
                csv_writer.writerow([formatted_date, CATEGORY_NAME, title, art_url])
                csv_file.flush()
                scraped_urls.add(art_url)
                scraped_count += 1
                
                if max_articles is not None and scraped_count >= max_articles:
                    print(f"\nReached article limit of {max_articles}. Stopping.")
                    break
                    
            if hit_cutoff or (max_articles is not None and scraped_count >= max_articles):
                break
                
            if (max_pages is not None and page >= max_pages) or (max_pages is None and start_date is None):
                break
                
            page += 1
            
    finally:
        csv_file.close()
        driver.quit()
        print(f"\nPrachachat World Scraper finished successfully. Total articles scraped: {scraped_count}")

if __name__ == "__main__":
    main()
