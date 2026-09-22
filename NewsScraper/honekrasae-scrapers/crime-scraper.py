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
BASE_URL = "https://www.honekrasae.com"
CATEGORY_URL = "https://www.honekrasae.com/category?c=%E0%B8%AD%E0%B8%B2%E0%B8%8A%E0%B8%8D%E0%B8%B2%E0%B8%81%E0%B8%A3%E0%B8%A3%E0%B8%A1"
CATEGORY_NAME = "อาชญากรรม"
CSV_FILE = os.path.join(SCRIPT_DIR, "honekrasae_crime.csv")

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

def normalize_honekrasae_date(raw_date_str):
    """Parses Thai date from HoneKrasae (e.g. '24 สิงหาคม 2569') to standard BE date and datetime."""
    if not raw_date_str or raw_date_str == "N/A":
        return "N/A", None
        
    tz_ict = timezone(timedelta(hours=7))
    thai_full_months = [
        "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
        "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"
    ]
    thai_short_months = [
        "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
        "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."
    ]
    
    clean = raw_date_str.strip()
    m = re.search(r"(\d+)\s+([ก-์\.]+)\s+(\d+)", clean)
    if m:
        day = int(m.group(1))
        month_str = m.group(2)
        year_str = m.group(3)
        
        month_idx = 1
        for idx, full_m in enumerate(thai_full_months):
            if full_m in month_str:
                month_idx = idx + 1
                break
        else:
            for idx, short_m in enumerate(thai_short_months):
                if short_m in month_str or short_m.replace(".", "") in month_str:
                    month_idx = idx + 1
                    break
                    
        year = int(year_str)
        if year < 100:
            year += 2500
            
        gregorian_year = year - 543
        dt_obj = datetime(gregorian_year, month_idx, day, 0, 0, tzinfo=tz_ict)
        formatted = f"{day} {thai_short_months[month_idx - 1]} {year} 00:00 น."
        return formatted, dt_obj
        
    return clean, None

def get_page_articles(driver):
    """Finds all news articles on current HoneKrasae category page."""
    articles = driver.execute_script("""
    var out = [];
    var cards = document.querySelectorAll('div[class*="content_item_wrapper"]');

    for (var c of cards) {
        var h2 = c.querySelector('h2');
        var title = h2 ? h2.innerText.trim() : '';
        if (!title) continue;
        
        // Find date string from span: '24 สิงหาคม 2569'
        var spans = Array.from(c.querySelectorAll('span')).map(s => s.innerText.trim());
        var dateText = '';
        for (var s of spans) {
            if (/\\d{1,2}\\s+[ก-์]+\\s+\\d{4}/.test(s)) {
                dateText = s;
                break;
            }
        }
        
        // Find ID from React fiber
        var id = null;
        var fiberKey = Object.keys(c).find(k => k.startsWith('__reactFiber'));
        if (fiberKey) {
            var fiber = c[fiberKey];
            var curr = fiber;
            while (curr && !id) {
                if (curr.memoizedProps) {
                    if (curr.memoizedProps.id) id = curr.memoizedProps.id;
                    else if (curr.memoizedProps.content && curr.memoizedProps.content.id) id = curr.memoizedProps.content.id;
                    else if (curr.memoizedProps.data && curr.memoizedProps.data.id) id = curr.memoizedProps.data.id;
                    else if (curr.memoizedProps.item && curr.memoizedProps.item.id) id = curr.memoizedProps.item.id;
                }
                curr = curr.return;
            }
        }
        
        var url = id ? 'https://www.honekrasae.com/content/' + id : '';
        out.push({
            title: title,
            raw_date: dateText,
            id: id,
            url: url
        });
    }
    return out;
    """)
    return articles

def main():
    parser = argparse.ArgumentParser(description="Scrape HoneKrasae crime news.")
    parser.add_argument(
        "-p", "--pages",
        type=int,
        default=None,
        help="Max pages to scrape (via &p= parameter)"
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
            
    print("Starting HoneKrasae crime news scraper...")
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
                
            page_url = f"{CATEGORY_URL}&p={page}" if page > 1 else CATEGORY_URL
            print(f"\n--- Loading Page {page}: {page_url} ---")
            driver.get(page_url)
            time.sleep(5)
            
            articles = get_page_articles(driver)
            if not articles:
                print("No articles found on this page. Stopping.")
                break
                
            new_articles = [art for art in articles if art["url"] and art["url"] not in scraped_urls]
            print(f"Found {len(articles)} total articles on page (newly discovered: {len(new_articles)}).")
            
            if not new_articles and len(articles) > 0 and max_pages is None and start_date is None:
                # All articles on page 1 already scraped and no pagination requested
                break
                
            for idx, art in enumerate(new_articles):
                title = art["title"]
                raw_date = art["raw_date"]
                art_url = art["url"]
                
                formatted_date, date_obj = normalize_honekrasae_date(raw_date)
                print(f"  [{idx+1}/{len(new_articles)}] Scraping: {title}")
                print(f"    Date: {formatted_date} | Link: {art_url}")
                
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
                csv_writer.writerow([formatted_date, CATEGORY_NAME, title, art_url])
                csv_file.flush()
                scraped_urls.add(art_url)
                scraped_count += 1
                
                if max_articles is not None and scraped_count >= max_articles:
                    print(f"\nReached article limit of {max_articles}. Stopping.")
                    break
                    
            if hit_cutoff or (max_articles is not None and scraped_count >= max_articles):
                break
                
            page += 1
            if max_pages is None and start_date is None:
                # Default single page run unless max_pages or date filter specified
                break
                
    finally:
        csv_file.close()
        driver.quit()
        print(f"\nHoneKrasae Scraper finished successfully. Total articles scraped: {scraped_count}")

if __name__ == "__main__":
    main()
