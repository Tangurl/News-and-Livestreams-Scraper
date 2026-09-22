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
BASE_URL = "https://www.komchadluek.net"
CSV_FILE = os.path.join(SCRIPT_DIR, "komchadluek_foreign.csv")
CATEGORY = "ต่างประเทศ"

def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    # Set window size to load desktop layout
    chrome_options.add_argument("--window-size=1920,1080")
    # Speed optimization: block images and set eager page load strategy
    chrome_options.page_load_strategy = 'eager'
    chrome_prefs = {
        "profile.default_content_setting_values.images": 2
    }
    chrome_options.add_experimental_option("prefs", chrome_prefs)
    # Add common headers to avoid detection
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    driver = webdriver.Chrome(options=chrome_options)
    driver.set_page_load_timeout(30)

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

def parse_komchadluek_date(date_text):
    """Parses Komchadluek's JSON-LD date string (e.g. '2026-06-09T14:03:00+07:00')
    or fallback visible text (e.g. '09 มิ.ย. 2569').
    Returns (formatted_str, date_obj)."""
    date_text = date_text.strip()
    
    # 1. Check if it's ISO format
    if "T" in date_text:
        try:
            iso_str = date_text
            if iso_str.endswith("Z"):
                iso_str = iso_str[:-1] + "+00:00"
            date_obj = datetime.fromisoformat(iso_str)
            
            # Format to D MMM YYYY HH:MM น. in ICT (UTC+7)
            thai_months = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
            if date_obj.tzinfo:
                dt_ict = date_obj.astimezone(timezone(timedelta(hours=7)))
            else:
                dt_ict = date_obj.replace(tzinfo=timezone(timedelta(hours=7)))
                
            day = dt_ict.day
            month = thai_months[dt_ict.month - 1]
            year = dt_ict.year + 543
            hour_min = dt_ict.strftime("%H:%M")
            formatted_str = f"{day} {month} {year} {hour_min} น."
            return formatted_str, dt_ict
        except Exception as e:
            print(f"Error parsing ISO date '{date_text}': {e}")
            
    # 2. Fallback: Parse visible date text e.g. "09 มิ.ย. 2569"
    match = re.search(r"(\d{1,2})\s+([ก-์\.]+)\s+(\d{4})", date_text)
    if match:
        day_str = match.group(1)
        month_raw = match.group(2)
        year_str = match.group(3)
        
        long_months = ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน", "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]
        thai_months = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
        
        month_idx = 1
        month_short = month_raw
        for idx, (lm, sm) in enumerate(zip(long_months, thai_months)):
            if lm in month_raw or sm in month_raw or sm.replace(".", "") in month_raw:
                month_short = sm
                month_idx = idx + 1
                break
                
        # Look for time
        time_match = re.search(r"(\d{2}):(\d{2})", date_text)
        hour_min = "00:00"
        if time_match:
            hour_min = f"{time_match.group(1)}:{time_match.group(2)}"
            
        formatted_str = f"{int(day_str)} {month_short} {year_str} {hour_min} น."
        
        try:
            gregorian_year = int(year_str) - 543
            h, m = map(int, hour_min.split(":"))
            date_obj = datetime(gregorian_year, month_idx, int(day_str), h, m, tzinfo=timezone(timedelta(hours=7)))
            return formatted_str, date_obj
        except Exception:
            return formatted_str, None
            
    return date_text, None

def get_article_date(driver, url, max_retries=3):
    """Navigates to the article page and scrapes its publication date.
    Returns (date_text, date_obj)."""
    for attempt in range(max_retries):
        try:
            driver.get(url)
            # Give it a moment to load (0.5s is plenty for eager strategy)
            time.sleep(0.5)
            
            # 1. Try to find JSON-LD datePublished
            try:
                html = driver.page_source
                match_pub = re.search(r'"datePublished"\s*:\s*"([^"]+)"', html)
                if match_pub:
                    formatted, date_obj = parse_komchadluek_date(match_pub.group(1))
                    if date_obj:
                        return formatted, date_obj
            except Exception:
                pass
                
            # 2. Try visible element text: class "published-date"
            try:
                date_el = driver.find_element(By.CSS_SELECTOR, ".published-date")
                raw_date_text = date_el.text.strip()
                if raw_date_text:
                    formatted, date_obj = parse_komchadluek_date(raw_date_text)
                    return formatted, date_obj
            except Exception:
                pass
                
        except Exception as e:
            print(f"  [Attempt {attempt+1}/{max_retries}] Error loading article {url}: {e}")
            time.sleep(2)
            
    return "N/A", None

def get_card_details(card):
    """Extracts article title and href from card element."""
    anchors = card.find_elements(By.TAG_NAME, "a")
    href = None
    title = None
    for a in anchors:
        curr_href = a.get_attribute("href")
        curr_text = a.text.strip()
        if curr_href and "/news/foreign/" in curr_href:
            # Match only news/foreign/\d+ style
            match = re.search(r"news/foreign/(\d+)", curr_href)
            if match:
                href = curr_href
                if curr_text:
                    title = curr_text
    return title, href

def main():
    parser = argparse.ArgumentParser(description="Scrape Komchadluek foreign section.")
    parser.add_argument(
        "-p", "--pages",
        type=int,
        default=None,
        help="Max number of pages to scrape (default: scrape all pages until the end)"
    )
    parser.add_argument(
        "-d", "--days",
        type=int,
        default=None,
        help="Max number of days to scrape (e.g. 1 for today only, 2 for today and yesterday)"
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

    print("Starting Komchadluek scraper...")
    try:
        list_url = f"{BASE_URL}/category/news/foreign"
        print(f"Loading first page: {list_url}")
        try:
            driver.get(list_url)
            time.sleep(4)
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
            
            # Find the card items
            cards = driver.find_elements(By.CSS_SELECTOR, "div.grid-lists div.grid-item")
            articles_to_scrape = []
            
            for card in cards:
                try:
                    title, href = get_card_details(card)
                    if title and href:
                        articles_to_scrape.append((title, href))
                except Exception:
                    pass
            
            # Deduplicate articles on this page
            unique_articles = []
            seen = set()
            for title, url in articles_to_scrape:
                if url not in seen:
                    seen.add(url)
                    unique_articles.append((title, url))
            
            new_articles = [art for art in unique_articles if art[1] not in scraped_urls and art[1] not in scraped_on_page]
            print(f"Found {len(unique_articles)} total articles on page/batch {page} (newly discovered: {len(new_articles)}).")
            
            if not unique_articles:
                print("No articles found. Stopping.")
                break
                
            # Scrape each new article
            for idx, (title, art_url) in enumerate(new_articles):
                print(f"  [{idx+1}/{len(new_articles)}] Scraping: {title}")
                
                # Open in a new tab to preserve list page state
                try:
                    driver.execute_script("window.open(arguments[0], '_blank');", art_url)
                    driver.switch_to.window(driver.window_handles[-1])
                    
                    date_posted, date_obj = get_article_date(driver, art_url)
                    print(f"    Date: {date_posted}")
                    
                    # Close the tab and switch back to main
                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])
                except Exception as e:
                    print(f"    Error scraping in tab: {e}")
                    try:
                        if len(driver.window_handles) > 1:
                            driver.close()
                    except:
                        pass
                    driver.switch_to.window(driver.window_handles[0])
                    date_posted, date_obj = "N/A", None

                # Check cutoff date
                if cutoff_date is not None and date_obj is not None:
                    if date_obj < cutoff_date:
                        # Check lookahead to verify if this is a pinned highlight article
                        is_pinned = False
                        next_idx = idx + 1
                        while next_idx < len(new_articles):
                            next_title, next_url = new_articles[next_idx]
                            try:
                                driver.execute_script("window.open(arguments[0], '_blank');", next_url)
                                driver.switch_to.window(driver.window_handles[-1])
                                _, next_date_obj = get_article_date(driver, next_url)
                                driver.close()
                                driver.switch_to.window(driver.window_handles[0])
                                
                                if next_date_obj is not None:
                                    if next_date_obj >= cutoff_date:
                                        is_pinned = True
                                    break
                            except Exception:
                                try:
                                    if len(driver.window_handles) > 1:
                                        driver.close()
                                except:
                                    pass
                                driver.switch_to.window(driver.window_handles[0])
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
                
                # Sleep between articles to be polite
                time.sleep(0.5)
                
            if hit_cutoff:
                break
                
            # Prepare to go to next page by clicking "ดูเพิ่มเติม"
            try:
                load_more_btn = driver.find_element(By.XPATH, "//span[contains(text(), 'ดูเพิ่มเติม')]")
            except Exception:
                load_more_btn = None
                
            if not load_more_btn:
                print("\nReached the last page. No 'ดูเพิ่มเติม' button found.")
                break
                
            print("\nClicking 'ดูเพิ่มเติม' to load more articles...")
            try:
                # Scroll to the button to ensure visibility
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", load_more_btn)
                time.sleep(0.5)
                # Click it
                driver.execute_script("arguments[0].click();", load_more_btn)
                
                # Wait for new cards to appear
                initial_count = len(cards)
                ajax_loaded = False
                for _ in range(30):  # wait up to 3 seconds
                    time.sleep(0.1)
                    new_cards = driver.find_elements(By.CSS_SELECTOR, "div.grid-lists div.grid-item")
                    if len(new_cards) > initial_count:
                        ajax_loaded = True
                        break
                if not ajax_loaded:
                    print("Load more wait timed out. Stopping.")
                    break
            except Exception as e:
                print(f"Error clicking 'ดูเพิ่มเติม': {e}")
                break
                
            page += 1
            
    finally:
        csv_file.close()
        driver.quit()
        print("\nKomchadluek Scraper finished successfully.")

if __name__ == "__main__":
    main()
