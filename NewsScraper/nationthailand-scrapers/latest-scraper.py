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
BASE_URL = "https://www.nationthailand.com"
CATEGORY_URLS = [
    ("News", "https://www.nationthailand.com/category/news"),
    ("Business", "https://www.nationthailand.com/category/business")
]
CSV_FILE = os.path.join(SCRIPT_DIR, "nationthailand_latest.csv")

# English URL slug to Thai category mapping
CATEGORY_MAPPING = {
    "politics": "การเมือง",
    "policy": "การเมือง",
    "general": "สังคม",
    "social": "สังคม",
    "society": "สังคม",
    "world": "ต่างประเทศ",
    "asean": "ต่างประเทศ",
    "international": "ต่างประเทศ",
    "sport": "กีฬา",
    "sports": "กีฬา",
    "economy": "เศรษฐกิจ",
    "economic": "เศรษฐกิจ",
    "business": "เศรษฐกิจ",
    "trading-investment": "เศรษฐกิจ",
    "corporate": "เศรษฐกิจ",
    "banking-finance": "เศรษฐกิจ",
    "property": "เศรษฐกิจ",
    "tech": "เศรษฐกิจ",
    "macro-economy": "เศรษฐกิจ",
    "tourism": "ท่องเที่ยว",
    "travel": "ท่องเที่ยว",
    "entertainment": "บันเทิง",
    "crime": "อาชญากรรม"
}

def extract_category_from_url(url):
    """Extracts and maps Thai category from Nation Thailand URL path."""
    m = re.search(r'/(?:news|business)/([^/]+)/\d+', url)
    if m:
        slug = m.group(1).lower()
        if slug in CATEGORY_MAPPING:
            return CATEGORY_MAPPING[slug]
        return "สังคม" if slug == "general" else slug
        
    if "/business" in url:
        return "เศรษฐกิจ"
    if "/news" in url:
        return "สังคม"
    return "ทั่วไป"

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

def normalize_nation_date(date_text):
    """Parses English dates from Nation Thailand to standard BE date and datetime."""
    date_text = date_text.strip()
    if not date_text or date_text == "N/A":
        return "N/A", None
        
    tz_ict = timezone(timedelta(hours=7))
    now = datetime.now(tz_ict)
    thai_months = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
    eng_months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    
    # Check relative minutes/hours
    match_min = re.search(r"(\d+)\s*(?:min|minute)", date_text, re.IGNORECASE)
    if match_min:
        mins = int(match_min.group(1))
        dt = now - timedelta(minutes=mins)
        formatted = f"{dt.day} {thai_months[dt.month - 1]} {dt.year + 543} {dt.strftime('%H:%M')} น."
        return formatted, dt
        
    match_hr = re.search(r"(\d+)\s*(?:hour|hr)", date_text, re.IGNORECASE)
    if match_hr:
        hrs = int(match_hr.group(1))
        dt = now - timedelta(hours=hrs)
        formatted = f"{dt.day} {thai_months[dt.month - 1]} {dt.year + 543} {dt.strftime('%H:%M')} น."
        return formatted, dt
        
    # Match 'THURSDAY, AUGUST 27, 2026' or 'August 26, 2026'
    m1 = re.search(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})(?:\s+(\d{1,2})[:\.](\d{2}))?", date_text)
    if m1 and m1.group(1).lower()[:3] in eng_months:
        month_raw = m1.group(1).lower()[:3]
        day = int(m1.group(2))
        year = int(m1.group(3))
        h_str = m1.group(4)
        m_str = m1.group(5)
        
        month_idx = eng_months.index(month_raw) + 1
        h = int(h_str) if h_str is not None else 0
        m = int(m_str) if m_str is not None else 0
        dt_obj = datetime(year, month_idx, day, h, m, tzinfo=tz_ict)
        time_part = f"{h:02d}:{m:02d} น." if h_str is not None else "00:00 น."
        formatted = f"{day} {thai_months[month_idx - 1]} {year + 543} {time_part}"
        return formatted, dt_obj
        
    # Match '27 August 2026'
    m2 = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})(?:\s+(\d{1,2})[:\.](\d{2}))?", date_text)
    if m2 and m2.group(2).lower()[:3] in eng_months:
        day = int(m2.group(1))
        month_raw = m2.group(2).lower()[:3]
        year = int(m2.group(3))
        h_str = m2.group(4)
        m_str = m2.group(5)
        
        month_idx = eng_months.index(month_raw) + 1
        h = int(h_str) if h_str is not None else 0
        m = int(m_str) if m_str is not None else 0
        dt_obj = datetime(year, month_idx, day, h, m, tzinfo=tz_ict)
        time_part = f"{h:02d}:{m:02d} น." if h_str is not None else "00:00 น."
        formatted = f"{day} {thai_months[month_idx - 1]} {year + 543} {time_part}"
        return formatted, dt_obj
        
    return date_text, None

def get_page_articles(driver):
    """Finds all articles from card-h, card-body and dynamically appended news links on Nation Thailand."""
    articles = driver.execute_script("""
    var list = [];
    var seen = new Set();
    var allAnchors = document.querySelectorAll('a[href*="/news/"], a[href*="/business/"]');
    for (var a of allAnchors) {
        var href = a.href;
        if (!href || !/\\/(news|business)\\/[^/]+\\/\\d+/.test(href)) continue;
        if (seen.has(href)) continue;
        seen.add(href);
        
        var container = a.closest('.card-h, .card-body') || a.parentElement;
        var small = (container ? container.querySelector('small') : null) || a.querySelector('small');
        var dateText = small ? small.innerText.trim() : 'N/A';
        
        var title = a.getAttribute('title') || '';
        if (!title) {
            var hEl = container ? container.querySelector('h2, h3, h4, .text-category-header') : a.querySelector('h2, h3, h4');
            title = hEl ? hEl.innerText.trim() : a.innerText.split('\\n')[0].trim();
        }
        
        if (title && href) {
            list.push({title: title, url: href, raw_date: dateText});
        }
    }
    return list;
    """)
    return articles

def scrape_category(driver, cat_title, cat_url, max_pages, max_articles, start_date, end_date, scraped_urls, csv_writer, current_scraped_count):
    """Scrapes a single category page with pagination."""
    print(f"\n==========================================")
    print(f"Loading Nation Thailand [{cat_title}]: {cat_url}")
    print(f"==========================================")
    
    driver.get(cat_url)
    time.sleep(5)
    
    # Pagination via button.font-poppins ('LOAD MORE')
    page = 1
    should_paginate = (max_pages is not None and max_pages > 1) or (max_pages is None and start_date is not None)
    while should_paginate:
        if max_pages is not None and page >= max_pages:
            break
            
        # Scroll down to bottom to trigger button rendering
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1.5)
        
        try:
            btn = driver.find_element(By.CSS_SELECTOR, "button.font-poppins, button[class*='font-poppins']")
        except Exception:
            try:
                btn = driver.find_element(By.XPATH, "//button[contains(., 'LOAD MORE') or contains(., 'Load More')]")
            except Exception:
                btn = None
                
        if not btn:
            break
            
        initial_count = len(get_page_articles(driver))
        print(f"Clicking 'LOAD MORE' (button.font-poppins) - page {page + 1}/{max_pages or 'auto'}...")
        try:
            driver.execute_script("arguments[0].scrollIntoView(true); arguments[0].click();", btn)
            for _ in range(40):
                time.sleep(0.3)
                if len(get_page_articles(driver)) > initial_count:
                    break
        except Exception as e:
            print(f"Error clicking LOAD MORE button: {e}")
            break
        page += 1
        
        # If date cutoff is already reached on current articles, stop early
        if start_date is not None:
            current_arts = get_page_articles(driver)
            if current_arts:
                _, last_dt = normalize_nation_date(current_arts[-1]["raw_date"])
                if last_dt is not None and last_dt < start_date:
                    print(f"Oldest article loaded ({last_dt}) is older than start date ({start_date}). Stopping pagination.")
                    break
                    
    articles = get_page_articles(driver)
    new_articles = [art for art in articles if art["url"] not in scraped_urls]
    print(f"Found {len(articles)} total articles in [{cat_title}] (newly discovered: {len(new_articles)}).")
    
    hit_cutoff = False
    count = current_scraped_count
    
    for idx, art in enumerate(new_articles):
        title = art["title"]
        art_url = art["url"]
        raw_date = art["raw_date"]
        category = extract_category_from_url(art_url)
        
        print(f"  [{idx+1}/{len(new_articles)}] Scraping: {title}")
        
        date_posted, date_obj = normalize_nation_date(raw_date)
        print(f"    Date: {date_posted} (raw: '{raw_date}') | Category: {category}")
        
        # Check start date cutoff
        if start_date is not None and date_obj is not None:
            if date_obj < start_date:
                print(f"    Article date ({date_obj}) is older than start date ({start_date}). Stopping category.")
                hit_cutoff = True
                break
                
        # Check end date cutoff
        if end_date is not None and date_obj is not None:
            if date_obj >= end_date:
                print(f"    Skipping article from today ({date_obj}) since target range is before {end_date}.")
                continue
                
        # Write to CSV
        csv_writer.writerow([date_posted, category, title, art_url])
        scraped_urls.add(art_url)
        count += 1
        
        if max_articles is not None and count >= max_articles:
            print(f"\nReached article limit of {max_articles}. Stopping.")
            break
            
    return count

def main():
    parser = argparse.ArgumentParser(description="Scrape Nation Thailand news & business.")
    parser.add_argument(
        "-p", "--pages",
        type=int,
        default=None,
        help="Max pages/clicks on 'LOAD MORE' button per section"
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
            
    print("Starting Nation Thailand latest news scraper...")
    driver = setup_driver()
    total_scraped = 0
    
    try:
        for cat_title, cat_url in CATEGORY_URLS:
            if max_articles is not None and total_scraped >= max_articles:
                break
            total_scraped = scrape_category(
                driver,
                cat_title,
                cat_url,
                max_pages,
                max_articles,
                start_date,
                end_date,
                scraped_urls,
                csv_writer,
                total_scraped
            )
            csv_file.flush()
            
    finally:
        csv_file.close()
        driver.quit()
        print(f"\nNation Thailand Scraper finished successfully. Total new articles scraped: {total_scraped}")

if __name__ == "__main__":
    main()
