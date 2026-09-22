import os
import re
import csv
import time
import argparse
from datetime import datetime, timezone, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

# Configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_URL = "https://www.tnews.co.th"
CATEGORY_URL = "https://www.tnews.co.th/category/latest-news"
CSV_FILE = os.path.join(SCRIPT_DIR, "tnews_latest.csv")

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

def normalize_tnews_date(raw_date_str):
    """Parses Thai date from T-News (e.g. '28 ส.ค. 2569') to standard BE date and datetime."""
    if not raw_date_str or raw_date_str == "N/A":
        return "N/A", None
        
    tz_ict = timezone(timedelta(hours=7))
    thai_months = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
    
    clean = raw_date_str.strip()
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
    """Finds all news articles on current T-News listing page."""
    articles = driver.execute_script("""
    var links = Array.from(document.querySelectorAll('a')).filter(a => {
        return a.href && (
            /tnews\\.co\\.th\\/[a-z0-9-]+\\/[a-z0-9-]+\\/\\d+/i.test(a.href) ||
            /tnews\\.co\\.th\\/[a-z0-9-]+\\/\\d+/i.test(a.href)
        ) && !a.href.includes('/category/') && !a.href.includes('/tag/');
    });
    
    var out = [];
    var seen = new Set();
    
    for (var a of links) {
        if (seen.has(a.href)) continue;
        
        var h3 = a.querySelector('h3, h2, h1, .mask-content-lg h3') || 
                 (a.parentElement ? a.parentElement.querySelector('h3, h2, h1') : null);
        var title = h3 ? h3.innerText.trim() : a.innerText.trim();
        if (!title || title.length < 5) continue;
        
        seen.add(a.href);
        out.push({
            url: a.href,
            title: title
        });
    }
    return out;
    """)
    return articles

def get_article_detail_info(driver, url, max_retries=2):
    """Visits the T-News article detail page and extracts exact category, headline, and date."""
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
                res = driver.execute_script("""
                    var h1 = document.querySelector('h1');
                    var dateEl = document.querySelector('.dateUpdate > li:nth-child(1), .dateUpdate li, .dateUpdate');
                    var dateTxt = dateEl ? dateEl.innerText.trim() : null;
                    
                    var catBadge = document.querySelector('.breadcrumb-title .badge, .breadcrumb-area .badge');
                    var catUl = document.querySelector('.breadcrumb-title > ul, .breadcrumb > ul, ul[class*="breadcrumb"]');
                    var cat = '-';
                    
                    if (catBadge && catBadge.innerText.trim()) {
                        cat = catBadge.innerText.trim();
                    } else if (catUl) {
                        var lis = Array.from(catUl.querySelectorAll('li a, li')).map(x => x.innerText.trim()).filter(Boolean);
                        if (lis.length >= 2) {
                            cat = lis[1];
                        } else if (lis.length > 0) {
                            cat = lis[0];
                        }
                    }
                    
                    if (h1) {
                        return {
                            title: h1.innerText.trim(),
                            category: cat,
                            raw_date: dateTxt
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
                raw_date = res.get('raw_date')
                formatted_date, dt_obj = normalize_tnews_date(raw_date)
                title = res.get('title')
                category = res.get('category') or '-'
                return title, category, formatted_date, dt_obj
        except Exception:
            try:
                if len(driver.window_handles) > 1:
                    driver.close()
                driver.switch_to.window(main_window)
            except Exception:
                pass
    return None, "-", "N/A", None

def main():
    parser = argparse.ArgumentParser(description="Scrape T-News latest news.")
    parser.add_argument(
        "-p", "--pages",
        type=int,
        default=None,
        help="Max scroll iterations for infinite scroll"
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
            
    print("Starting T-News latest news scraper...")
    driver = setup_driver()
    hit_cutoff = False
    scraped_count = 0
    
    try:
        print(f"Loading URL: {CATEGORY_URL}")
        driver.get(CATEGORY_URL)
        time.sleep(5)
        
        # Paginate via infinite scroll if needed
        scroll_count = 0
        max_scrolls = (max_pages - 1) if (max_pages is not None and max_pages > 1) else (10 if max_pages is None and start_date is not None else 0)
        
        while scroll_count < max_scrolls:
            initial_count = len(get_page_articles(driver))
            print(f"Scrolling down ({scroll_count + 1}/{max_scrolls})...")
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(3)
            current_count = len(get_page_articles(driver))
            if current_count <= initial_count:
                print("No more new articles loaded on scroll.")
                break
            scroll_count += 1
            
        articles = get_page_articles(driver)
        new_articles = [art for art in articles if art["url"] not in scraped_urls]
        print(f"\nFound {len(articles)} total articles on page (newly discovered: {len(new_articles)}).")
        
        for idx, art in enumerate(new_articles):
            art_url = art["url"]
            list_title = art["title"]
            
            print(f"  [{idx+1}/{len(new_articles)}] Scraping: {list_title}")
            
            # Fetch detail page category and published date
            detail_title, category, date_posted, date_obj = get_article_detail_info(driver, art_url)
            title = detail_title or list_title
            print(f"    Date: {date_posted} | Cat: {category} | Title: {title}")
            
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
            csv_writer.writerow([date_posted, category, title, art_url])
            csv_file.flush()
            scraped_urls.add(art_url)
            scraped_count += 1
            
            if max_articles is not None and scraped_count >= max_articles:
                print(f"\nReached article limit of {max_articles}. Stopping.")
                break
                
    finally:
        csv_file.close()
        driver.quit()
        print(f"\nT-News Scraper finished successfully. Total articles scraped: {scraped_count}")

if __name__ == "__main__":
    main()
