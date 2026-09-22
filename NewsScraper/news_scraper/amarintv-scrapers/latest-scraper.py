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
BASE_URL = "https://www.amarintv.com"
CSV_FILE = os.path.join(SCRIPT_DIR, "amarintv_latest.csv")

# English to Thai category mapping
CATEGORY_MAPPING = {
    "social": "สังคม",
    "politic": "การเมือง",
    "crime": "อาชญากรรม",
    "sport": "กีฬา",
    "entertain": "บันเทิง",
    "quality-of-life": "คุณภาพชีวิต",
    "agriculture": "เกษตรกรรม",
    "general": "ทั่วไป"
}

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

def normalize_amarintv_date(date_text):
    """Parses Thai dates from Amarin TV cards or detail page to standard BE date and datetime."""
    date_text = date_text.strip()
    if not date_text or date_text == "N/A":
        return "N/A", None
        
    tz_ict = timezone(timedelta(hours=7))
    now = datetime.now(tz_ict)
    thai_months = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
    
    # Check for minutes relative
    match_min = re.search(r"(\d+)\s*นาที", date_text)
    if match_min:
        mins = int(match_min.group(1))
        target_dt = now - timedelta(minutes=mins)
        formatted = f"{target_dt.day} {thai_months[target_dt.month - 1]} {target_dt.year + 543} {target_dt.strftime('%H:%M')} น."
        return formatted, target_dt
        
    # Check for hours relative
    match_hr = re.search(r"(\d+)\s*ชั่วโมง", date_text)
    if match_hr:
        hrs = int(match_hr.group(1))
        target_dt = now - timedelta(hours=hrs)
        formatted = f"{target_dt.day} {thai_months[target_dt.month - 1]} {target_dt.year + 543} {target_dt.strftime('%H:%M')} น."
        return formatted, target_dt
        
    # Normalize newlines and whitespace
    clean_text = re.sub(r"\s+", " ", date_text).replace(" น.", "").strip()
    
    # Check for standard date '28 ส.ค. 69 10:10' or '28 ส.ค. 2569 10:10' or '28 ส.ค. 69'
    match_date = re.search(r"(\d+)\s+([ก-์\.]+)\s+(\d+)(?:\s+(\d{1,2})[:\.](\d{2}))?", clean_text)
    if match_date:
        day = int(match_date.group(1))
        month_str = match_date.group(2)
        year_str = match_date.group(3)
        h_str = match_date.group(4)
        m_str = match_date.group(5)
        
        month_idx = 1
        for idx, m in enumerate(thai_months):
            if m in month_str or m.replace(".", "") in month_str:
                month_idx = idx + 1
                break
                
        year = int(year_str)
        if year < 100:
            year += 2500
            
        gregorian_year = year - 543
        h = int(h_str) if h_str is not None else 0
        m = int(m_str) if m_str is not None else 0
        dt_obj = datetime(gregorian_year, month_idx, day, h, m, tzinfo=tz_ict)
        time_part = f"{h:02d}:{m:02d} น." if h_str is not None else "00:00 น."
        formatted = f"{day} {thai_months[month_idx - 1]} {year} {time_part}"
        return formatted, dt_obj
        
    return date_text, None

def get_article_detail_time(url, max_retries=3):
    """Visits the article page with a fresh session and extracts exact date & time from .text-[#696969] > div:nth-child(1)."""
    for attempt in range(max_retries):
        driver = None
        try:
            driver = setup_driver()
            driver.get(url)
            
            # Wait for article page DOM and date element to be ready
            date_time_text = None
            for _ in range(20):
                if "Just a moment" not in driver.title:
                    date_time_text = driver.execute_script("""
                        var el = document.querySelector('.text-\\\\[\\\\#696969\\\\] > div:nth-child(1)');
                        if (el && el.innerText.trim()) return el.innerText.trim();
                        var parent = document.querySelector('.text-\\\\[\\\\#696969\\\\]');
                        if (parent && parent.innerText.trim()) return parent.innerText.trim();
                        var divs = document.querySelectorAll('div');
                        for (var d of divs) {
                            if (d.className && typeof d.className === 'string' && d.className.includes('696969')) {
                                if (d.innerText && (d.innerText.includes('น.') || d.innerText.includes(':'))) {
                                    return d.innerText.trim();
                                }
                            }
                        }
                        return null;
                    """)
                    if date_time_text:
                        break
                time.sleep(0.3)
            
            if date_time_text:
                formatted, dt_obj = normalize_amarintv_date(date_time_text)
                if dt_obj is not None:
                    return formatted, dt_obj
                    
            # Fallback to publishedTime in page HTML / meta tags
            html = driver.page_source
            m = re.search(r'publishedTime["\\]*:\s*["\\]*([^"\\,]+)', html)
            if not m:
                m = re.search(r'article:published_time["\']\s+content=["\']([^"\']+)["\']', html)
            if not m:
                m = re.search(r'content=["\']([^"\']+)["\']\s+property=["\']article:published_time["\']', html)
            if m:
                iso_str = m.group(1).replace("Z", "+00:00")
                iso_dt = datetime.fromisoformat(iso_str)
                ict_dt = iso_dt.astimezone(timezone(timedelta(hours=7)))
                thai_months = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
                formatted = f"{ict_dt.day} {thai_months[ict_dt.month - 1]} {ict_dt.year + 543} {ict_dt.strftime('%H:%M')} น."
                return formatted, ict_dt
        except Exception:
            pass
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
    return None, None

def get_page_articles(driver):
    """Finds all articles matching standard Amarin TV news patterns on current page."""
    cards = driver.find_elements(By.CSS_SELECTOR, "div[class*='CardNormal_card_txt']")
    articles = []
    
    for card in cards:
        try:
            a = card.find_element(By.TAG_NAME, "a")
            href = a.get_attribute("href")
            
            if href and re.search(r'/news/[^/]+/\d+', href):
                title_el = a.find_element(By.TAG_NAME, "h2")
                title = title_el.get_attribute("textContent").strip()
                
                date_text = "N/A"
                divs = a.find_elements(By.CSS_SELECTOR, "div[class*='font-skvText']")
                for div in divs:
                    text = div.get_attribute("textContent").strip()
                    if text:
                        date_text = text
                        break
                        
                match_cat = re.search(r'/news/([^/]+)/\d+', href)
                eng_cat = match_cat.group(1) if match_cat else "general"
                category = CATEGORY_MAPPING.get(eng_cat, "ทั่วไป")
                
                if href.startswith("/"):
                    href = BASE_URL + href
                    
                articles.append({
                    "title": title,
                    "url": href,
                    "category": category,
                    "raw_date": date_text
                })
        except:
            pass
            
    unique = []
    seen = set()
    for art in articles:
        if art["url"] not in seen:
            seen.add(art["url"])
            unique.append(art)
    return unique

def main():
    parser = argparse.ArgumentParser(description="Scrape Amarin TV latest news.")
    parser.add_argument(
        "-p", "--pages",
        type=int,
        default=None,
        help="Max clicks on 'See More' pagination button"
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
                next(reader, None)
                for row in reader:
                    if len(row) >= 4:
                        scraped_urls.add(row[3])
            print(f"Loaded {len(scraped_urls)} already scraped articles from {CSV_FILE}.")
        except Exception as e:
            print("Error reading existing CSV:", e)
            
    print("Starting Amarin TV scraper...")
    try:
        list_url = f"{BASE_URL}/news/latest"
        print(f"Loading main page: {list_url}")
        try:
            driver.get(list_url)
            time.sleep(5)
        except Exception as e:
            print(f"Error loading main page: {e}")
            import sys
            sys.exit(1)
            
        page = 1
        while max_pages is not None and page < max_pages:
            try:
                btn = driver.find_element(By.CSS_SELECTOR, "button.button-seemore")
            except:
                btn = None
                
            if not btn:
                break
                
            print(f"Clicking 'ดูเพิ่มเติม' (page {page + 1}/{max_pages})...")
            initial_count = len(get_page_articles(driver))
            try:
                driver.execute_script("arguments[0].click();", btn)
                for _ in range(40):
                    time.sleep(0.1)
                    if len(get_page_articles(driver)) > initial_count:
                        break
            except Exception as e:
                print(f"Error clicking see more: {e}")
                break
            page += 1
            
        articles = get_page_articles(driver)
        driver.quit()
        driver = None
        
        new_articles = [art for art in articles if art["url"] not in scraped_urls]
        print(f"Found {len(articles)} total articles on page (newly discovered: {len(new_articles)}).")
        
        hit_cutoff = False
        scraped_count = 0
        for idx, art in enumerate(new_articles):
            title = art["title"]
            art_url = art["url"]
            category = art["category"]
            raw_date = art["raw_date"]
            
            print(f"  [{idx+1}/{len(new_articles)}] Scraping: {title}")
            
            # Fetch exact posted timestamp from detail page
            detail_date, detail_dt = get_article_detail_time(art_url)
            if detail_dt is not None:
                date_posted = detail_date
                date_obj = detail_dt
            else:
                date_posted, date_obj = normalize_amarintv_date(raw_date)
                
            print(f"    Date: {date_posted}")
            
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
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        print("\nAmarin TV Scraper finished successfully.")

if __name__ == "__main__":
    main()
