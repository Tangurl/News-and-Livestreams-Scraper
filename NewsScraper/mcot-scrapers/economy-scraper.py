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
BASE_URL = "https://tna.mcot.net"
CATEGORY_URL = "https://tna.mcot.net/tna/th/news/list?categoryId=53"
CATEGORY_NAME = "เศรษฐกิจ"
CSV_FILE = os.path.join(SCRIPT_DIR, "mcot_economy.csv")

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

def normalize_mcot_date(date_str, time_str):
    """Parses Thai date and time from MCOT detail page to standard BE date and datetime."""
    if not date_str or date_str == "N/A":
        return "N/A", None
        
    tz_ict = timezone(timedelta(hours=7))
    thai_months = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
    
    clean_date = date_str.strip()
    clean_time = time_str.strip().replace(" น.", "").strip() if time_str else ""
    
    m_date = re.search(r"(\d+)\s+([ก-์\.]+)\s+(\d+)", clean_date)
    if m_date:
        day = int(m_date.group(1))
        month_str = m_date.group(2)
        year_str = m_date.group(3)
        
        month_idx = 1
        for idx, m in enumerate(thai_months):
            if m in month_str or m.replace(".", "") in month_str:
                month_idx = idx + 1
                break
                
        year = int(year_str)
        if year < 100:
            year += 2500
            
        gregorian_year = year - 543
        
        h = 0
        m = 0
        if clean_time:
            m_time = re.search(r"(\d{1,2})[:\.](\d{2})", clean_time)
            if m_time:
                h = int(m_time.group(1))
                m = int(m_time.group(2))
                
        dt_obj = datetime(gregorian_year, month_idx, day, h, m, tzinfo=tz_ict)
        time_part = f"{h:02d}:{m:02d} น." if clean_time else "00:00 น."
        formatted = f"{day} {thai_months[month_idx - 1]} {year} {time_part}"
        return formatted, dt_obj
        
    return clean_date, None

def get_page_articles(driver):
    """Finds all news articles on current MCOT listing page by extracting article IDs from images and titles."""
    articles = driver.execute_script("""
    var out = [];
    var seen = new Set();
    
    // Find all images matching api-service.mcot.net/data/news/<id>/
    var imgs = document.querySelectorAll('img[src*="api-service.mcot.net/data/news/"]');
    for (var img of imgs) {
        var src = img.src;
        var idx = src.indexOf('/data/news/');
        if (idx === -1) continue;
        var rest = src.substring(idx + 11);
        var slashIdx = rest.indexOf('/');
        if (slashIdx === -1) continue;
        var id = rest.substring(0, slashIdx);
        if (!/^\\d+$/.test(id)) continue;
        if (seen.has(id)) continue;
        seen.add(id);
        
        // Find title from alt or parent elements
        var alt = img.getAttribute('alt') || '';
        var parent = img.closest('.cursor-pointer') || img.parentElement.parentElement;
        
        var title = '';
        if (parent) {
            var h2 = parent.querySelector('h2.font-semibold, h2, h3');
            if (h2 && h2.innerText.trim()) {
                title = h2.innerText.trim();
            } else {
                var p = parent.querySelector('.grid-cols-1 > div > div > div:nth-child(2) > div:nth-child(2) > p:nth-child(1)') || parent.querySelector('p:last-of-type');
                if (p && p.innerText.trim()) {
                    title = p.innerText.trim();
                }
            }
        }
        if (!title && alt) {
            title = alt.trim();
        }
        
        var detailUrl = 'https://tna.mcot.net/tna/th/news/list/' + id;
        out.push({id: id, title: title, url: detailUrl});
    }
    return out;
    """)
    return articles

def get_article_detail_info(url, max_retries=3):
    """Visits the MCOT article detail page and extracts exact title, published date and time."""
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
                    var dateEl = document.querySelector('div.gap-1:nth-child(1) > p:nth-child(2)') || document.querySelector('div[class*="gap-1"] p:nth-of-type(2)');
                    
                    var dateStr = dateEl ? dateEl.innerText.trim() : null;
                    var timeStr = null;
                    
                    var allP = document.querySelectorAll('p');
                    for (var p of allP) {
                        var txt = p.innerText.trim();
                        if (!timeStr && /^\\d{1,2}:\\d{2}$/.test(txt)) {
                            timeStr = txt;
                        }
                        if (!dateStr && /\\d{1,2}\\s+[ก-์\\.]+\\s+\\d{2,4}/.test(txt)) {
                            dateStr = txt;
                        }
                    }
                    
                    if (h1 && (dateStr || timeStr)) {
                        return {
                            title: h1.innerText.trim(),
                            date_str: dateStr,
                            time_str: timeStr
                        };
                    }
                    return null;
                """)
                if res:
                    break
                time.sleep(0.3)
                
            if res:
                formatted_date, dt_obj = normalize_mcot_date(res.get('date_str'), res.get('time_str'))
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
    parser = argparse.ArgumentParser(description="Scrape MCOT economy news.")
    parser.add_argument(
        "-p", "--pages",
        type=int,
        default=None,
        help="Max pages to scrape (via pagination Next button)"
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
            
    print("Starting MCOT economy news scraper...")
    driver = setup_driver()
    page = 1
    hit_cutoff = False
    scraped_count = 0
    
    try:
        print(f"Loading URL: {CATEGORY_URL}")
        driver.get(CATEGORY_URL)
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
            articles = get_page_articles(driver)
            new_articles = [art for art in articles if art["url"] not in scraped_urls]
            print(f"Found {len(articles)} total articles on page (newly discovered: {len(new_articles)}).")
            
            for idx, art in enumerate(new_articles):
                art_id = art["id"]
                art_url = art["url"]
                list_title = art["title"]
                
                print(f"  [{idx+1}/{len(new_articles)}] Scraping ID {art_id}: {list_title}")
                
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
                    
            if hit_cutoff or (max_articles is not None and scraped_count >= max_articles):
                break
                
            # Click Next button for pagination (button.gap-2:nth-child(3))
            page += 1
            if max_pages is not None and page > max_pages:
                break
                
            next_btn = driver.execute_script("""
            var btn = document.querySelector('button.gap-2:nth-child(3)');
            if (btn && !btn.disabled) return btn;
            
            var btns = document.querySelectorAll('button');
            for (var b of btns) {
                if (b.innerText.trim() === 'Next' && !b.disabled) return b;
            }
            return null;
            """)
            
            if not next_btn:
                print("No active Next button found. Stopping.")
                break
                
            print(f"Clicking Next button (button.gap-2:nth-child(3)) for page {page}...")
            first_id_before = articles[0]['id'] if articles else None
            driver.execute_script("arguments[0].scrollIntoView(true); arguments[0].click();", next_btn)
            
            # Wait for articles list to change
            for _ in range(30):
                time.sleep(0.3)
                current_arts = get_page_articles(driver)
                if current_arts and current_arts[0]['id'] != first_id_before:
                    break
                    
    finally:
        csv_file.close()
        driver.quit()
        print(f"\nMCOT Scraper finished successfully. Total articles scraped: {scraped_count}")

if __name__ == "__main__":
    main()
