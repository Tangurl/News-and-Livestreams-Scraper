import os
import re
import csv
import time
import json
import argparse
from datetime import datetime, timezone, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException

# Configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_URL = "https://www.tnnthailand.com"
CATEGORY_URL = "https://www.tnnthailand.com/newslist"
CSV_FILE = os.path.join(SCRIPT_DIR, "tnnthailand_latest.csv")

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
    driver.set_page_load_timeout(20)
    
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

def normalize_tnn_date(raw_date_str):
    """Parses Thai date string or ISO timestamp from TNN to standard BE date format and datetime object."""
    if not raw_date_str or raw_date_str == "N/A":
        return "N/A", None
        
    tz_ict = timezone(timedelta(hours=7))
    thai_months = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
    
    clean = raw_date_str.strip()
    
    # 1. Try ISO format (e.g. '2026-08-31T11:10:50.852+07:00')
    if "T" in clean:
        try:
            dt = datetime.fromisoformat(clean)
            dt_ict = dt.astimezone(tz_ict)
            day = dt_ict.day
            month_idx = dt_ict.month
            be_year = dt_ict.year if dt_ict.year >= 2400 else dt_ict.year + 543
            formatted = f"{day} {thai_months[month_idx - 1]} {be_year} {dt_ict.strftime('%H:%M')} น."
            return formatted, dt_ict
        except Exception:
            pass
            
    # 2. Try Thai string format
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

def get_page_articles(driver, page_num=1):
    """Finds all article links on current newslist page across top hero, highlights, and the complete lower stream."""
    # Scroll to load the entire lower section
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 2);")
    time.sleep(1)
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(1.5)
    
    articles = driver.execute_script(r"""
    var isPage2Plus = arguments[0] > 1;
    var links = [];
    var seen = new Set();
    
    function addLink(a) {
        if (!a || !a.href) return;
        var href = a.href.replace(/\/$/, '');
        if (seen.has(href)) return;
        if (!/tnnthailand\.com\/(?:[^\/]+\/)?(?:\d+|[^\/]+\/\d+)\/?$/.test(href)) return;
        seen.add(href);
        links.push(href);
    }
    
    // 1. On page 2+, start with hero element: div.item-news-bg a
    if (isPage2Plus) {
        var hero = document.querySelector('div.item-news-bg a, .item-news-bg a');
        if (hero) addLink(hero);
    }
    
    // 2. Top section: div.space-y-5 a, div.!gap-0 a
    var topSectionA = Array.from(document.querySelectorAll('div.space-y-5 a, div.\\!gap-0 a, div.gap-0 a'));
    for (var a of topSectionA) {
        addLink(a);
    }
    
    // 3. Lower section: div.blog-item a, div.border-[#CCCCCC] a, div.border-b a
    var lowerA = Array.from(document.querySelectorAll('div.blog-item a, div[class*="border-[#CCCCCC]"] a, div.border-b a'));
    for (var a of lowerA) {
        addLink(a);
    }
    
    // 4. Any remaining news stream links in container
    var allMainA = Array.from(document.querySelectorAll('main a, #__next a, .container a')).filter(a => {
        if (!a.href) return false;
        if (a.closest('header, footer, nav')) return false;
        return /tnnthailand\.com\/(?:[^\/]+\/)?(?:\d+|[^\/]+\/\d+)\/?$/.test(a.href);
    });
    for (var a of allMainA) {
        addLink(a);
    }
    
    return links;
    """, page_num)
    return articles

def get_article_detail(driver, url, max_retries=2):
    """Opens detail page in a separate tab to extract title, category, and date-time."""
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
            for _ in range(12):
                res = driver.execute_script(r"""
                    var titleEl = document.querySelector('.content-title, h1');
                    var catEl = document.querySelector('.category-link');
                    
                    var dateSpans = Array.from(document.querySelectorAll('.content-meta, span.inline-flex, time, .content-date, .publish-date')).map(el => el.innerText.trim()).filter(t => /\d{1,2}\s+[ก-์\.]+\s+\d{4}/.test(t));
                    var rawDate = dateSpans.length > 0 ? dateSpans[0] : null;
                    
                    // Fallback to JSON-LD schema
                    if (!rawDate) {
                        var scripts = Array.from(document.querySelectorAll('script[type="application/ld+json"]'));
                        for (var s of scripts) {
                            try {
                                var data = JSON.parse(s.innerText);
                                if (data.datePublished && data.datePublished !== "null") {
                                    rawDate = data.datePublished;
                                    break;
                                } else if (data.dateModified && data.dateModified !== "null") {
                                    rawDate = data.dateModified;
                                }
                            } catch(e) {}
                        }
                    }
                    
                    var title = titleEl ? titleEl.innerText.trim() : null;
                    var cat = catEl ? catEl.innerText.trim() : null;
                    
                    if (title && title.length > 3) {
                        return {
                            title: title,
                            category: cat || 'ข่าวทั่วไป',
                            rawDate: rawDate
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
                
            if res and res.get('title'):
                formatted_date, dt_obj = normalize_tnn_date(res.get('rawDate'))
                return res.get('title'), res.get('category'), formatted_date, dt_obj
        except Exception:
            try:
                if len(driver.window_handles) > 1:
                    driver.close()
                driver.switch_to.window(main_window)
            except Exception:
                pass
    return None, None, "N/A", None

def main():
    parser = argparse.ArgumentParser(description="Scrape TNN Thailand latest newslist.")
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
            
    print("Starting TNN Thailand news scraper...")
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
                
            page_url = f"{CATEGORY_URL}/?page={page}" if page > 1 else CATEGORY_URL
            print(f"\n--- [Page {page}] Loading: {page_url} ---")
            try:
                driver.get(page_url)
            except TimeoutException:
                driver.execute_script("window.stop();")
            time.sleep(3)
            
            article_urls = []
            for _ in range(15):
                article_urls = get_page_articles(driver, page)
                if article_urls:
                    break
                time.sleep(0.5)
                
            if not article_urls:
                print("No articles found on page.")
                break
                
            new_urls = [u for u in article_urls if u not in scraped_urls]
            print(f"Found {len(article_urls)} total articles on page (newly discovered: {len(new_urls)}).")
            
            for idx, art_url in enumerate(new_urls):
                print(f"  [{idx+1}/{len(new_urls)}] Scraping: {art_url}")
                
                title, category, formatted_date, date_obj = get_article_detail(driver, art_url)
                if not title:
                    print("    Article failed to load or has no content. Skipping.")
                    continue
                    
                print(f"    Date: {formatted_date} | Cat: {category} | Title: {title}")
                
                if start_date is not None and date_obj is not None:
                    if date_obj < start_date:
                        print(f"    Article date ({date_obj}) is older than start date ({start_date}). Stopping.")
                        hit_cutoff = True
                        break
                        
                if end_date is not None and date_obj is not None:
                    if date_obj >= end_date:
                        print(f"    Skipping article from today ({date_obj}) since target range is before {end_date}.")
                        continue
                        
                csv_writer.writerow([formatted_date, category, title, art_url])
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
        print(f"\nTNN Thailand Scraper finished successfully. Total articles scraped: {scraped_count}")

if __name__ == "__main__":
    main()
