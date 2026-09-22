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
BASE_URL = "https://www.springnews.co.th"
CATEGORY_URL = "https://www.springnews.co.th/category/news/sport"
CSV_FILE = os.path.join(SCRIPT_DIR, "springnews_sport.csv")
CATEGORY_NAME = "กีฬา"

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

def normalize_springnews_date(raw_date_str):
    """Parses date string from SpringNews (e.g. '27 Aug 2026' or Thai date)
    to standard BE date format and datetime object."""
    if not raw_date_str or raw_date_str == "N/A":
        return "N/A", None
        
    tz_ict = timezone(timedelta(hours=7))
    thai_short_months = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
    eng_months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    
    clean = raw_date_str.strip()
    
    # 1. Try English format: "27 Aug 2026"
    m_eng = re.search(r"(\d{1,2})\s+([a-zA-Z]+)\s+(\d{4})", clean)
    if m_eng:
        day = int(m_eng.group(1))
        month_str = m_eng.group(2).lower()[:3]
        year_num = int(m_eng.group(3))
        
        month_idx = 1
        for idx, em in enumerate(eng_months):
            if em == month_str:
                month_idx = idx + 1
                break
                
        if year_num < 2400:
            gregorian_year = year_num
            be_year = year_num + 543
        else:
            be_year = year_num
            gregorian_year = year_num - 543
            
        dt_obj = datetime(gregorian_year, month_idx, day, 0, 0, tzinfo=tz_ict)
        formatted = f"{day} {thai_short_months[month_idx - 1]} {be_year} 00:00 น."
        return formatted, dt_obj
        
    # 2. Try Thai format: "27 ส.ค. 2569"
    m_thai = re.search(r"(\d{1,2})\s+([ก-์\.]+)\s+(?:พ\.ศ\.\s*)?(\d{2,4})", clean)
    if m_thai:
        day = int(m_thai.group(1))
        month_str = m_thai.group(2)
        year_raw = int(m_thai.group(3))
        
        if year_raw < 100:
            be_year = 2500 + year_raw
            gregorian_year = be_year - 543
        elif year_raw < 2400:
            gregorian_year = year_raw
            be_year = year_raw + 543
        else:
            be_year = year_raw
            gregorian_year = year_raw - 543
            
        month_idx = 1
        for idx, sm in enumerate(thai_short_months):
            if sm in month_str or sm.replace(".", "") in month_str:
                month_idx = idx + 1
                break
                
        dt_obj = datetime(gregorian_year, month_idx, day, 0, 0, tzinfo=tz_ict)
        formatted = f"{day} {thai_short_months[month_idx - 1]} {be_year} 00:00 น."
        return formatted, dt_obj
        
    return clean, None

def get_page_articles(driver):
    """Extracts article cards from current DOM."""
    articles = driver.execute_script(r"""
    var cards = Array.from(document.querySelectorAll('.card-v-category, [id^="1"], [id^="2"], [id^="3"], [id^="4"], [id^="5"], [id^="6"], [id^="7"], [id^="8"], [id^="9"], [id^="0"]'));
    var res = [];
    var seen = new Set();
    
    var engDateRegex = /(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})/i;
    var thaiDateRegex = /(\d{1,2})\s+([ก-์\.]+)\s+(\d{2,4})/;
    
    for (var card of cards) {
        var aList = Array.from(card.querySelectorAll('a')).filter(a => a.href && a.href.includes('/news/'));
        if (aList.length === 0) continue;
        
        var mainA = aList.find(a => a.querySelector('h3, h2, h4') || a.innerText.trim().length > 10) || aList[0];
        var href = mainA.href.split('?')[0].replace(/\/$/, '');
        if (!href || seen.has(href)) continue;
        seen.add(href);
        
        var h3 = card.querySelector('h3, h2, h4, [class*="title"]');
        var title = h3 ? h3.innerText.trim() : (mainA.getAttribute('title') || mainA.innerText.trim());
        if (!title) continue;
        
        // Find date inside card
        var allTexts = Array.from(card.querySelectorAll('p, span, div, time')).map(el => el.innerText.trim());
        var dateMatch = null;
        for (var t of allTexts) {
            var mEng = t.match(engDateRegex);
            if (mEng) {
                dateMatch = mEng[0];
                break;
            }
            var mThai = t.match(thaiDateRegex);
            if (mThai) {
                dateMatch = mThai[0];
                break;
            }
        }
        
        res.push({
            href: href,
            title: title,
            raw_date: dateMatch
        });
    }
    return res;
    """)
    return articles

def main():
    parser = argparse.ArgumentParser(description="Scrape SpringNews sport news.")
    parser.add_argument(
        "-p", "--pages",
        type=int,
        default=None,
        help="Max scroll pages to scrape"
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
            
    print("Starting SpringNews Sport news scraper...")
    driver = setup_driver()
    scroll_round = 1
    hit_cutoff = False
    scraped_count = 0
    
    try:
        print(f"\n--- Loading: {CATEGORY_URL} ---")
        try:
            driver.get(CATEGORY_URL)
        except TimeoutException:
            driver.execute_script("window.stop();")
        time.sleep(3)
        
        last_height = 0
        stagnant_count = 0
        
        while True:
            if hit_cutoff:
                break
                
            if max_pages is not None and scroll_round > max_pages:
                print(f"\nReached max scroll iterations limit of {max_pages}. Stopping.")
                break
                
            if max_articles is not None and scraped_count >= max_articles:
                break
                
            articles = []
            for _ in range(10):
                articles = get_page_articles(driver)
                if articles:
                    break
                time.sleep(0.5)
                
            if not articles:
                print(f"No articles found on scroll round {scroll_round}.")
                break
                
            new_articles = [art for art in articles if art["href"] not in scraped_urls]
            print(f"Scroll round #{scroll_round}: Found {len(articles)} total DOM articles ({len(new_articles)} newly discovered).")
            
            for idx, art in enumerate(new_articles):
                art_url = art["href"]
                title = art["title"]
                raw_date = art["raw_date"]
                
                print(f"  [{idx+1}/{len(new_articles)}] Scraping: {title}")
                formatted_date, date_obj = normalize_springnews_date(raw_date)
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
                
            if (max_pages is not None and scroll_round >= max_pages) or (max_pages is None and start_date is None and max_articles is None):
                break
                
            current_height = driver.execute_script("return document.body.scrollHeight;")
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2.5)
            new_height = driver.execute_script("return document.body.scrollHeight;")
            
            if new_height == current_height:
                stagnant_count += 1
                if stagnant_count >= 3:
                    print("Reached end of infinite scroll feed.")
                    break
            else:
                stagnant_count = 0
                
            scroll_round += 1
            
    finally:
        csv_file.close()
        driver.quit()
        print(f"\nSpringNews Sport Scraper finished successfully. Total articles scraped: {scraped_count}")

if __name__ == "__main__":
    main()
