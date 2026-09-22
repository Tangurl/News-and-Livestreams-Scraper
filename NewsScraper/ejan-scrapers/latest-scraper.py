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
BASE_URL = "https://www.ejan.co"
CSV_FILE = os.path.join(SCRIPT_DIR, "ejan_latest.csv")

# Category mapping (user specified: List ข่าวทั่วไป as สังคม)
CATEGORY_MAPPING = {
    "ข่าวทั่วไป": "สังคม",
    "สังคมอีจัน": "สังคม",
    "โซเชียล-เทรนด์": "สังคม",
    "ข่าวการเมือง": "การเมือง",
    "การเมือง": "การเมือง",
    "ข่าวเศรษฐกิจ": "เศรษฐกิจ",
    "เศรษฐกิจ": "เศรษฐกิจ",
    "ข่าวอาชญากรรม": "อาชญากรรม",
    "อาชญากรรม": "อาชญากรรม",
    "ข่าวบันเทิง": "บันเทิง",
    "อีจัน บันเทิง": "บันเทิง",
    "บันเทิง": "บันเทิง",
    "ต่างประเทศ": "ต่างประเทศ",
    "ข่าวต่างประเทศ": "ต่างประเทศ",
    "กีฬา": "กีฬา",
    "ข่าวกีฬา": "กีฬา",
    "ยานยนต์": "ยานยนต์",
    "ท่องเที่ยว-อาหาร": "ท่องเที่ยว",
    "ดวง พลังมู": "ดูดวง",
    "ข่าวหวย": "หวย"
}

def map_category(raw_cat):
    """Normalizes EJan category names according to repository standards."""
    if not raw_cat:
        return "สังคม"
    raw_cat = raw_cat.strip()
    if raw_cat == "ข่าวทั่วไป":
        return "สังคม"
    if raw_cat in CATEGORY_MAPPING:
        return CATEGORY_MAPPING[raw_cat]
    if raw_cat.startswith("ข่าว"):
        cleaned = raw_cat[4:].strip()
        if cleaned in CATEGORY_MAPPING:
            return CATEGORY_MAPPING[cleaned]
        return cleaned
    return raw_cat

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

def normalize_ejan_date(date_text):
    """Parses Thai dates from EJan (e.g., 'เผยแพร่เมื่อ : 28 ส.ค. 2569, 10:36') to standard BE date and datetime."""
    date_text = date_text.strip()
    if not date_text or date_text == "N/A":
        return "N/A", None
        
    tz_ict = timezone(timedelta(hours=7))
    thai_months = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
    
    # Remove 'เผยแพร่เมื่อ :' prefix and commas
    clean_text = re.sub(r"เผยแพร่เมื่อ\s*:\s*", "", date_text).replace(",", "").strip()
    clean_text = re.sub(r"\s+", " ", clean_text).replace(" น.", "").strip()
    
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
    """Visits the article page and extracts exact date & time from .entry-publish."""
    for attempt in range(max_retries):
        driver = None
        try:
            driver = setup_driver()
            driver.get(url)
            
            # Wait for article page DOM and .entry-publish element to be ready
            date_time_text = None
            for _ in range(20):
                if "Just a moment" not in driver.title:
                    date_time_text = driver.execute_script("""
                        var el = document.querySelector('.entry-publish');
                        if (el && el.innerText.trim()) return el.innerText.trim();
                        var timeEl = document.querySelector('time.entry-date') || document.querySelector('.posted-on');
                        if (timeEl && timeEl.innerText.trim()) return timeEl.innerText.trim();
                        return null;
                    """)
                    if date_time_text:
                        break
                time.sleep(0.3)
            
            if date_time_text:
                formatted, dt_obj = normalize_ejan_date(date_time_text)
                if dt_obj is not None:
                    return formatted, dt_obj
                    
            # Fallback to publishedTime in page HTML / meta tags
            html = driver.page_source
            m = re.search(r'article:published_time["\']\s+content=["\']([^"\']+)["\']', html)
            if not m:
                m = re.search(r'content=["\']([^"\']+)["\']\s+property=["\']article:published_time["\']', html)
            if not m:
                m = re.search(r'publishedTime["\\]*:\s*["\\]*([^"\\,]+)', html)
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
    """Finds all articles on the current EJan latest news page."""
    cards = driver.find_elements(By.CSS_SELECTOR, "article.s-content")
    articles = []
    
    for card in cards:
        try:
            # Hyperlink and Title: article.s-content > div:nth-child(2) > h2:nth-child(2) > a
            title_el = None
            try:
                title_el = card.find_element(By.CSS_SELECTOR, "h2 a")
            except Exception:
                try:
                    title_el = card.find_element(By.TAG_NAME, "h2").find_element(By.TAG_NAME, "a")
                except Exception:
                    pass
                    
            if not title_el:
                continue
                
            href = title_el.get_attribute("href")
            title = title_el.get_attribute("textContent").strip()
            
            if not href or not title:
                continue
                
            # Category name: #post-XXXXXX > div:nth-child(2) > div:nth-child(1) > a
            cat_text = "สังคม"
            try:
                cat_el = card.find_element(By.CSS_SELECTOR, "div:nth-child(2) > div:nth-child(1) > a")
                cat_text = cat_el.get_attribute("textContent").strip()
            except Exception:
                try:
                    cat_el = card.find_element(By.CSS_SELECTOR, "a[href*='/category/']")
                    cat_text = cat_el.get_attribute("textContent").strip()
                except Exception:
                    pass
                    
            category = map_category(cat_text)
            
            articles.append({
                "title": title,
                "url": href,
                "category": category
            })
        except Exception:
            pass
            
    unique = []
    seen = set()
    for art in articles:
        if art["url"] not in seen:
            seen.add(art["url"])
            unique.append(art)
    return unique

def main():
    parser = argparse.ArgumentParser(description="Scrape EJan latest news.")
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
            
    print("Starting EJan latest news scraper...")
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
                
            if page == 1:
                list_url = f"{BASE_URL}/latest-news"
            else:
                list_url = f"{BASE_URL}/latest-news/page/{page}"
                
            print(f"\n--- Scraping Page {page} ---")
            print(f"Loading URL: {list_url}")
            
            driver = setup_driver()
            try:
                driver.get(list_url)
                time.sleep(4)
                articles = get_page_articles(driver)
            except Exception as e:
                print(f"Error loading page {page}: {e}")
                articles = []
            finally:
                driver.quit()
                
            new_articles = [art for art in articles if art["url"] not in scraped_urls]
            print(f"Found {len(articles)} total articles on page (newly discovered: {len(new_articles)}).")
            
            if page == 1 and not articles:
                print("Error: No articles found on page 1. Target structure might have changed.")
                import sys
                sys.exit(1)
                
            if not articles:
                print("No articles found on this page. Stopping.")
                break
                
            for idx, art in enumerate(new_articles):
                title = art["title"]
                art_url = art["url"]
                category = art["category"]
                
                print(f"  [{idx+1}/{len(new_articles)}] Scraping: {title}")
                
                # Fetch exact posted timestamp from detail page (.entry-publish)
                date_posted, date_obj = get_article_detail_time(art_url)
                print(f"    Date: {date_posted} | Category: {category}")
                
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
                    
            if hit_cutoff:
                break
                
            page += 1
            
    finally:
        csv_file.close()
        print("\nEJan Scraper finished successfully.")

if __name__ == "__main__":
    main()
