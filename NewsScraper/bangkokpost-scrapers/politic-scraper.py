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
BASE_URL = "https://www.bangkokpost.com"
CSV_FILE = os.path.join(SCRIPT_DIR, "bangkokpost_politic.csv")
CATEGORY = "การเมือง"

def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.page_load_strategy = 'none' # Async page loading for speed
    
    # Anti-detection settings
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(options=chrome_options)
    
    # Hide webdriver property
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

def parse_bangkokpost_date(date_text):
    """Parses date from Bangkok Post (either ISO-8601 or English text 'D MMM YYYY').
    Returns (formatted_str, date_obj) where:
      formatted_str is in 'D MMM YYYY HH:MM น.' format (Thai months, Buddhist year)
      date_obj is a timezone-aware datetime object (ICT, UTC+7).
    """
    date_text = date_text.strip()
    
    # 1. ISO format check (e.g., "2026-06-09T05:37:00+07:00")
    if "T" in date_text:
        try:
            iso_str = date_text
            if iso_str.endswith("Z"):
                iso_str = iso_str[:-1] + "+00:00"
            date_obj = datetime.fromisoformat(iso_str)
            
            # Convert to ICT (UTC+7) timezone
            tz_ict = timezone(timedelta(hours=7))
            if date_obj.tzinfo:
                dt_ict = date_obj.astimezone(tz_ict)
            else:
                dt_ict = date_obj.replace(tzinfo=tz_ict)
                
            thai_months = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
            day = dt_ict.day
            month = thai_months[dt_ict.month - 1]
            year = dt_ict.year + 543
            hour_min = dt_ict.strftime("%H:%M")
            formatted_str = f"{day} {month} {year} {hour_min} น."
            return formatted_str, dt_ict
        except Exception as e:
            print(f"Error parsing ISO date '{date_text}': {e}")

    # 2. English text format check (e.g., "9 Jun 2026" or "12 May 2026")
    match = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", date_text)
    if match:
        day_str = match.group(1)
        month_raw = match.group(2)[:3].title()
        year_str = match.group(3)
        
        eng_months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        thai_months = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
        
        month_idx = 1
        month_short = "ม.ค."
        for idx, eng in enumerate(eng_months):
            if eng in month_raw:
                month_short = thai_months[idx]
                month_idx = idx + 1
                break
                
        greg_year = int(year_str)
        buddhist_year = greg_year + 543
        
        formatted_str = f"{int(day_str)} {month_short} {buddhist_year} 00:00 น."
        try:
            tz_ict = timezone(timedelta(hours=7))
            date_obj = datetime(greg_year, month_idx, int(day_str), 0, 0, tzinfo=tz_ict)
            return formatted_str, date_obj
        except Exception:
            return formatted_str, None
            
    return date_text, None

def load_page_with_none_strategy(driver, url, timeout=30):
    """Loads category page with none strategy, polling for div.news--list availability."""
    driver.get(url)
    start_time = time.time()
    while time.time() - start_time < timeout:
        time.sleep(0.5)
        try:
            cards = driver.find_elements(By.CSS_SELECTOR, "div.news--list")
            if len(cards) >= 3:
                return True
        except:
            pass
    return False

def load_detail_page_with_none_strategy(driver, url, timeout=15):
    """Loads article details page with none strategy, polling for publish date metadata."""
    driver.get(url)
    start_time = time.time()
    while time.time() - start_time < timeout:
        time.sleep(0.5)
        try:
            html = driver.page_source
            if '"datePublished"' in html or 'lead:published_at' in html:
                return True
        except:
            pass
    return False

def get_article_date_from_detail(driver):
    """Retrieves article date from JSON-LD or meta tags in the detail page."""
    try:
        html = driver.page_source
        match_pub = re.search(r'"datePublished"\s*:\s*"([^"]+)"', html)
        if match_pub:
            formatted, date_obj = parse_bangkokpost_date(match_pub.group(1))
            if date_obj:
                return formatted, date_obj
    except Exception:
        pass
        
    try:
        meta_el = driver.find_element(By.CSS_SELECTOR, "meta[name='lead:published_at']")
        content = meta_el.get_attribute("content")
        if content:
            formatted, date_obj = parse_bangkokpost_date(content)
            if date_obj:
                return formatted, date_obj
    except Exception:
        pass
        
    return None, None

def main():
    parser = argparse.ArgumentParser(description="Scrape Bangkok Post politics section.")
    parser.add_argument(
        "-p", "--pages",
        type=int,
        default=None,
        help="Max number of pages to scrape"
    )
    parser.add_argument(
        "-d", "--days",
        type=int,
        default=None,
        help="Max number of days to scrape (1 for today, 2 for today and yesterday, etc.)"
    )
    args = parser.parse_args()
    max_pages = args.pages
    max_days = args.days

    cutoff_date = None
    if max_days is not None:
        tz_ict = timezone(timedelta(hours=7))
        now_ict = datetime.now(tz_ict)
        # Cutoff is start of today minus (max_days - 1) days
        cutoff_date = (now_ict - timedelta(days=max_days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
        print(f"Scraping articles published on or after: {cutoff_date.strftime('%Y-%m-%d %H:%M:%S %Z')}")

    driver = setup_driver()
    
    # Initialize CSV file and write header if it doesn't exist
    os.makedirs(SCRIPT_DIR, exist_ok=True)
    file_exists = os.path.exists(CSV_FILE)
    csv_file = open(CSV_FILE, "a", encoding="utf-8", newline="")
    csv_writer = csv.writer(csv_file)
    if not file_exists:
        csv_writer.writerow(["date", "category", "article title", "article link"])
        csv_file.flush()
        
    scraped_urls = set()
    
    # If file exists, read existing URLs to avoid duplicate scraping
    if file_exists:
        try:
            with open(CSV_FILE, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                next(reader, None)  # Skip header
                for row in reader:
                    if len(row) >= 4:
                        scraped_urls.add(row[3])
            print(f"Loaded {len(scraped_urls)} already scraped articles from {CSV_FILE}.")
        except Exception as e:
            print("Error reading existing CSV:", e)

    print("Starting Bangkok Post scraper...")
    try:
        list_url = f"{BASE_URL}/thailand/politics"
        print(f"Loading first page: {list_url}")
        try:
            success = load_page_with_none_strategy(driver, list_url)
            if not success:
                print("Warning: Page did not load completely within timeout, trying to proceed anyway.")
            time.sleep(2)
        except Exception as e:
            print(f"Error loading main page: {e}")
            return
            
        page = 1
        hit_cutoff = False
        scraped_on_page = set()
        
        while True:
            if hit_cutoff:
                break
                
            if max_pages is not None and page > max_pages:
                print(f"\nReached max pages limit of {max_pages}. Stopping.")
                break
                
            print(f"\n--- Scraping Page/Batch {page} ---")
            
            # Query article card elements
            cards = driver.find_elements(By.CSS_SELECTOR, "div.news--list")
            batch_articles = {}
            for card in cards:
                try:
                    h3_a = card.find_element(By.CSS_SELECTOR, "h3 a")
                    href = h3_a.get_attribute("href")
                    if not href:
                        continue
                    if href.startswith("/"):
                        href = BASE_URL + href
                        
                    title = h3_a.text.strip()
                    
                    # Fallback date
                    date_span = card.find_element(By.CSS_SELECTOR, "div.chanel-s span")
                    fallback_text = date_span.text.strip()
                    
                    batch_articles[href] = {
                        "title": title,
                        "fallback_date": fallback_text,
                        "date_text": None,
                        "date_obj": None
                    }
                except:
                    pass

            # Extract unique URLs in order of appearance
            ordered_urls = []
            seen_urls = set()
            for card in cards:
                try:
                    h3_a = card.find_element(By.CSS_SELECTOR, "h3 a")
                    href = h3_a.get_attribute("href")
                    if href:
                        if href.startswith("/"):
                            href = BASE_URL + href
                        if href not in seen_urls:
                            seen_urls.add(href)
                            ordered_urls.append(href)
                except:
                    pass
                    
            new_urls = [url for url in ordered_urls if url not in scraped_urls and url not in scraped_on_page]
            print(f"Found {len(seen_urls)} total articles on page/batch {page} (newly discovered: {len(new_urls)}).")
            
            if not seen_urls:
                print("No articles found. Stopping.")
                break
                
            for idx, art_url in enumerate(new_urls):
                art_data = batch_articles[art_url]
                title = art_data["title"]
                fallback_str = art_data["fallback_date"]
                
                # Fetch exact date/time from detail tab
                print(f"  [{idx+1}/{len(new_urls)}] Fetching metadata for: {title}")
                date_posted = None
                date_obj = None
                
                try:
                    driver.execute_script("window.open(arguments[0], '_blank');", art_url)
                    driver.switch_to.window(driver.window_handles[-1])
                    
                    # Wait for publish date details to load
                    load_detail_page_with_none_strategy(driver, art_url)
                    time.sleep(0.5)
                    
                    date_posted, date_obj = get_article_date_from_detail(driver)
                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])
                except Exception as e:
                    print(f"    Error loading detail tab: {e}")
                    try:
                        if len(driver.window_handles) > 1:
                            driver.close()
                    except:
                        pass
                    driver.switch_to.window(driver.window_handles[0])
                
                # Fallback to listing page date if detail tab failed
                if not date_obj:
                    print(f"    Warning: Detail fetch failed. Falling back to listing date: {fallback_str}")
                    date_posted, date_obj = parse_bangkokpost_date(fallback_str)
                    
                if not date_posted:
                    date_posted = "N/A"
                if not title:
                    title = "N/A"
                    
                print(f"    Date: {date_posted}")
                
                # Cutoff check
                if cutoff_date is not None and date_obj is not None:
                    if date_obj < cutoff_date:
                        # Lookahead for pinned highlight articles
                        is_pinned = False
                        next_idx = idx + 1
                        while next_idx < len(new_urls):
                            next_url = new_urls[next_idx]
                            next_data = batch_articles[next_url]
                            next_fallback = next_data["fallback_date"]
                            
                            # Try parsing next date from fallback first to avoid unnecessary detail loads
                            _, next_date_obj = parse_bangkokpost_date(next_fallback)
                            
                            # If fallback date is newer or equal, it is pinned.
                            # If fallback date is older, let's load detail page just to be sure
                            if not next_date_obj or next_date_obj < cutoff_date:
                                try:
                                    driver.execute_script("window.open(arguments[0], '_blank');", next_url)
                                    driver.switch_to.window(driver.window_handles[-1])
                                    load_detail_page_with_none_strategy(driver, next_url)
                                    time.sleep(0.5)
                                    _, next_date_obj = get_article_date_from_detail(driver)
                                    driver.close()
                                    driver.switch_to.window(driver.window_handles[0])
                                except Exception:
                                    try:
                                        if len(driver.window_handles) > 1:
                                            driver.close()
                                    except:
                                        pass
                                    driver.switch_to.window(driver.window_handles[0])
                                    
                            if next_date_obj is not None:
                                if next_date_obj >= cutoff_date:
                                    is_pinned = True
                                break
                            next_idx += 1
                            
                        if is_pinned:
                            print(f"    Article date ({date_obj}) is older than cutoff ({cutoff_date}) but detected as pinned highlight. Skipping and continuing.")
                            continue
                        else:
                            print(f"    Article date ({date_obj}) is older than cutoff ({cutoff_date}). Stopping.")
                            hit_cutoff = True
                            break
                            
                # Write to CSV
                csv_writer.writerow([date_posted, CATEGORY, title, art_url])
                csv_file.flush()
                scraped_urls.add(art_url)
                scraped_on_page.add(art_url)
                time.sleep(0.1)
                
            if hit_cutoff:
                break
                
            if max_pages is not None and page >= max_pages:
                print(f"\nReached max pages limit of {max_pages}. Stopping.")
                break
                
            # Click MORE
            try:
                more_btn = driver.find_element(By.CSS_SELECTOR, "div.divbtn-more a")
            except Exception:
                more_btn = None
                
            if not more_btn:
                print("\nNo 'MORE' button found. Reached the last page.")
                break
                
            print("\nClicking 'MORE' to load more articles...")
            try:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", more_btn)
                time.sleep(0.5)
                driver.execute_script("arguments[0].click();", more_btn)
                
                initial_count = len(cards)
                ajax_loaded = False
                for _ in range(40):
                    time.sleep(0.1)
                    current_cards = driver.find_elements(By.CSS_SELECTOR, "div.news--list")
                    if len(current_cards) > initial_count:
                        ajax_loaded = True
                        break
                if not ajax_loaded:
                    print("MORE stories wait timed out. Stopping.")
                    break
                else:
                    time.sleep(0.5)
            except Exception as e:
                print(f"Error clicking MORE: {e}")
                break
                
            page += 1
            
    finally:
        csv_file.close()
        driver.quit()
        print("\nBangkok Post Scraper finished.")

if __name__ == "__main__":
    main()
