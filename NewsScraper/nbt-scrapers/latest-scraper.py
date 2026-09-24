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
BASE_URL = "https://thainews.prd.go.th"
CATEGORY_URL = "https://thainews.prd.go.th/thainews/news/list/ล่าสุด"
CSV_FILE = os.path.join(SCRIPT_DIR, "nbt_latest.csv")

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
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-software-rasterizer")
    # Resolve Thai Government PRD domain directly to avoid local DNS/VPN SERVFAIL issues
    chrome_options.add_argument("--host-resolver-rules=MAP thainews.prd.go.th 122.155.92.9")
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

def normalize_nbt_date(raw_date_str):
    """Parses Thai date from NBT (e.g. '28 ส.ค. 69 14:54') to standard BE date and datetime."""
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
    """Finds all news articles on current NBT ThaiNews listing page."""
    articles = driver.execute_script("""
    var links = Array.from(document.querySelectorAll('a.text-decoration-none, a[href*="/news/view/"], a[href*="/news/"]'));
    var out = [];
    var seen = new Set();
    
    for (var a of links) {
        if (!a.href || (!a.href.includes('/news/view/') && !a.href.includes('/news/'))) continue;
        if (a.href.endsWith('/news/list/') || a.href.includes('/news/list/')) continue;
        if (seen.has(a.href)) continue;
        
        var titleEl = a.querySelector('div > div:nth-child(2) > div:nth-child(1)');
        var dateEl = a.querySelector('div > div:nth-child(2) > div:nth-child(2) > div:nth-child(1)');
        var catEl = a.querySelector('label') || a.querySelector('div > div:nth-child(2) > div:nth-child(2) > div:nth-child(2)');
        
        var title = titleEl ? titleEl.innerText.trim() : '';
        if (!title) {
            var headings = a.querySelectorAll('h1, h2, h3, h4, h5, h6, [class*="title"], p');
            for (var h of headings) {
                if (h.innerText.trim().length > 3) {
                    title = h.innerText.trim();
                    break;
                }
            }
            if (!title && a.innerText.trim()) {
                var lines = a.innerText.trim().split('\\n').map(function(s){return s.trim();}).filter(Boolean);
                if (lines.length > 0) title = lines[0];
            }
        }
        if (!title) continue;
        
        var rawDate = dateEl ? dateEl.innerText.trim() : '';
        if (!rawDate) {
            var dateCandidates = a.querySelectorAll('[class*="date"], small, time, span');
            for (var d of dateCandidates) {
                var txt = d.innerText.trim();
                if (/\\d+/.test(txt) && (txt.includes('ก.พ.') || txt.includes('มี.ค.') || txt.includes('เม.ย.') || txt.includes('พ.ค.') || txt.includes('มิ.ย.') || txt.includes('ก.ค.') || txt.includes('ส.ค.') || txt.includes('ก.ย.') || txt.includes('ต.ค.') || txt.includes('พ.ย.') || txt.includes('ธ.ค.') || txt.includes('ม.ค.'))) {
                    rawDate = txt;
                    break;
                }
            }
        }
        
        seen.add(a.href);
        out.push({
            url: a.href,
            title: title,
            raw_date: rawDate,
            raw_cat: catEl ? catEl.innerText.trim() : '-'
        });
    }
    return out;
    """)
    return articles

def click_next_page(driver, target_page):
    """Navigates to the next page using carousel button or page number button."""
    success = driver.execute_script("""
    var target = arguments[0];
    
    // Try user specified selectors or matching page button
    var selectors = [
        "li.react-multi-carousel-item--active:nth-child(" + target + ") > li:nth-child(1) > button:nth-child(1)",
        ".swiper-show-arrows > ul:nth-child(1) > li:nth-child(" + (target + 2) + ") > li:nth-child(1) > button:nth-child(1)",
        "li.active + li button",
        ".news-list-page.active + .news-list-page button"
    ];
    
    for (var s of selectors) {
        var el = document.querySelector(s);
        if (el) {
            el.scrollIntoView({behavior: 'smooth', block: 'center'});
            el.click();
            return true;
        }
    }
    
    // Fallback: search all page buttons
    var btns = Array.from(document.querySelectorAll('button.page-link, [id*="page-item"] button, .react-multi-carousel-item button'));
    for (var b of btns) {
        if (b.innerText.trim() === String(target)) {
            b.scrollIntoView({behavior: 'smooth', block: 'center'});
            b.click();
            return true;
        }
    }
    
    // Arrow next fallback
    var nextArrow = document.querySelector('button.news-list-arrow-next, .splide__arrow--next');
    if (nextArrow) {
        nextArrow.scrollIntoView({behavior: 'smooth', block: 'center'});
        nextArrow.click();
        return true;
    }
    
    return false;
    """, target_page)
    return success

def main():
    parser = argparse.ArgumentParser(description="Scrape NBT ThaiNews latest news.")
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
            
    print("Starting NBT ThaiNews latest news scraper...")
    driver = setup_driver()
    page = 1
    hit_cutoff = False
    scraped_count = 0
    
    try:
        print(f"Loading URL: {CATEGORY_URL}")
        for attempt in range(3):
            try:
                driver.get(CATEGORY_URL)
                break
            except Exception as e:
                if attempt < 2:
                    print(f"Warning: Failed to load {CATEGORY_URL} ({e}). Retrying in 3 seconds...")
                    time.sleep(3)
                else:
                    raise
        time.sleep(6)
        
        while True:
            if hit_cutoff:
                break
                
            if max_pages is not None and page > max_pages:
                print(f"\nReached max pages limit of {max_pages}. Stopping.")
                break
                
            if max_articles is not None and scraped_count >= max_articles:
                break
                
            print(f"\n--- Scraping Page {page} ---")
            articles = []
            max_wait = 25 if page == 1 else 10
            for w in range(max_wait):
                articles = get_page_articles(driver)
                if articles:
                    break
                time.sleep(1)
                
            if not articles:
                # Try triggering Next.js router transition in case dynamic route did not decode
                driver.execute_script("""
                try {
                    if (window.next && window.next.router) {
                        window.next.router.push({
                            pathname: '/thainews/news/list/[id]',
                            query: { id: 'ล่าสุด' }
                        });
                    }
                } catch(e) {}
                """)
                for _ in range(10):
                    articles = get_page_articles(driver)
                    if articles:
                        break
                    time.sleep(1)

            if not articles:
                print("No articles found on page after waiting.")
                try:
                    debug_url = driver.current_url
                    debug_title = driver.title
                    debug_body = driver.execute_script("return document.body ? document.body.innerText.slice(0, 200).replace(/\\n+/g, ' ') : ''")
                    debug_next = driver.execute_script("return window.next ? (window.next.router ? JSON.stringify(window.next.router.query) : 'no router') : 'no next'")
                    print(f"  [Debug] Current URL: {debug_url}")
                    print(f"  [Debug] Title: {debug_title}")
                    print(f"  [Debug] Next.js Router Query: {debug_next}")
                    print(f"  [Debug] Page text snippet: {debug_body}")
                except Exception as dbg_err:
                    print(f"  [Debug error]: {dbg_err}")
                break
                
            new_articles = [art for art in articles if art["url"] not in scraped_urls]
            print(f"Found {len(articles)} total articles on page (newly discovered: {len(new_articles)}).")
            
            for idx, art in enumerate(new_articles):
                art_url = art["url"]
                title = art["title"]
                raw_date = art["raw_date"]
                category = art["raw_cat"]
                
                formatted_date, date_obj = normalize_nbt_date(raw_date)
                print(f"  [{idx+1}/{len(new_articles)}] Scraping: {title}")
                print(f"    Date: {formatted_date} | Cat: {category} | Link: {art_url}")
                
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
                
            # Navigate to next page
            target_next = page + 1
            print(f"Navigating to page {target_next}...")
            first_url_before = articles[0]["url"] if articles else None
            clicked = click_next_page(driver, target_next)
            if not clicked:
                print("Could not click next page button. Stopping.")
                break
                
            # Wait for articles list to update
            for _ in range(30):
                time.sleep(0.3)
                curr_arts = get_page_articles(driver)
                if curr_arts and (curr_arts[0]["url"] != first_url_before or len(curr_arts) != len(articles)):
                    break
            page += 1
            
    finally:
        csv_file.close()
        driver.quit()
        print(f"\nNBT ThaiNews Scraper finished successfully. Total articles scraped: {scraped_count}")

if __name__ == "__main__":
    main()
