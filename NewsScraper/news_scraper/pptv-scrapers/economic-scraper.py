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
BASE_URL = "https://www.pptvhd36.com"
CSV_FILE = os.path.join(SCRIPT_DIR, "pptv_economic.csv")
CATEGORY = "เศรษฐกิจ"

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

def extract_pptv_id(href):
    """Extracts article ID from PPTV URL href."""
    if not href:
        return None
    # Matches wealth/economic/article_id
    match = re.search(r"economic/(\d+)", href)
    if match:
        return match.group(1)
    return None

def get_article_date(driver, url, max_retries=3):
    """Navigates to the article page and scrapes its publication date.
    Returns (date_text, date_obj)."""
    for attempt in range(max_retries):
        try:
            driver.get(url)
            # Give it a moment to load (0.5s is plenty for eager strategy)
            time.sleep(0.5)
            
            date_text = None
            date_obj = None
            
            # 1. Try finding <time> element with datetime attribute
            try:
                time_els = driver.find_elements(By.TAG_NAME, "time")
                for el in time_els:
                    dt_attr = el.get_attribute("datetime")
                    if dt_attr:
                        dt_attr = dt_attr.strip()
                        try:
                            # Try YYYY-MM-DD HH:MM:SS format
                            date_obj = datetime.strptime(dt_attr, "%Y-%m-%d %H:%M:%S")
                            date_obj = date_obj.replace(tzinfo=timezone(timedelta(hours=7)))
                            break
                        except Exception:
                            try:
                                # Try ISO format
                                date_obj = datetime.fromisoformat(dt_attr)
                                break
                            except Exception:
                                pass
            except Exception:
                pass
                
            # 2. Try scraping the ISO string from page HTML JSON-LD schema
            if not date_obj:
                try:
                    html = driver.page_source
                    match_pub = re.search(r'"datePublished"\s*:\s*"([^"]+)"', html)
                    if match_pub:
                        date_obj = datetime.fromisoformat(match_pub.group(1))
                except Exception:
                    pass
            
            # 3. If we got date_obj, format it to Thai style
            if date_obj:
                thai_months = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
                if date_obj.tzinfo:
                    dt_ict = date_obj.astimezone(timezone(timedelta(hours=7)))
                else:
                    dt_ict = date_obj.replace(tzinfo=timezone(timedelta(hours=7)))
                
                day = dt_ict.day
                month = thai_months[dt_ict.month - 1]
                year = dt_ict.year + 543
                hour_min = dt_ict.strftime("%H:%M")
                date_text = f"{day} {month} {year} {hour_min} น."
            else:
                # Fallback to visible text from time tag
                try:
                    time_el = driver.find_element(By.TAG_NAME, "time")
                    date_text = time_el.text.strip()
                except Exception:
                    date_text = "N/A"
                    
                if date_text and date_text != "N/A":
                    date_text = date_text.replace(",", " ")
                    date_text = re.sub(r"\s+", " ", date_text)
                    date_text = re.sub(r"(\d{2}:\d{2})น\.", r"\1 น.", date_text)
                    date_text = date_text.strip()
                    
            return date_text, date_obj
                
        except Exception as e:
            print(f"  [Attempt {attempt+1}/{max_retries}] Error loading article {url}: {e}")
            time.sleep(2)
            
    return "N/A", None

def main():
    parser = argparse.ArgumentParser(description="Scrape PPTV wealth economic section.")
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

    print("Starting PPTV scraper...")
    try:
        list_url = f"{BASE_URL}/wealth/economic"
        print(f"Loading {list_url}...")
        try:
            driver.get(list_url)
            time.sleep(3)
        except Exception as e:
            print(f"Error loading main page: {e}")
            return

        clicks = 0
        hit_cutoff = False
        
        while True:
            if hit_cutoff:
                break
                
            # Resolve the "แสดงเพิ่มเติม" button first
            btn = None
            try:
                btn = driver.find_element(By.CSS_SELECTOR, "button.btn-more")
                if not btn.is_displayed():
                    btn = None
            except Exception:
                pass
                
            # Find all title links currently on the page
            title_elements = driver.find_elements(By.CSS_SELECTOR, "a.title")
            articles_to_scrape = []
            
            for el in title_elements:
                try:
                    href = el.get_attribute("href")
                    title = el.get_attribute("textContent").strip() or el.text.strip()
                    
                    art_id = extract_pptv_id(href)
                    if art_id and title:
                        art_url = f"{BASE_URL}/wealth/economic/{art_id}"
                        articles_to_scrape.append((title, art_url))
                except Exception:
                    pass
            
            # Deduplicate articles
            unique_articles = []
            seen = set()
            for title, url in articles_to_scrape:
                if url not in seen:
                    seen.add(url)
                    unique_articles.append((title, url))
            
            new_articles = [art for art in unique_articles if art[1] not in scraped_urls]
            print(f"Found {len(unique_articles)} total articles on page (newly discovered: {len(new_articles)}).")
            
            if not unique_articles:
                print("No articles found on this page. Stopping.")
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
                        print(f"    Article date ({date_obj}) is older than cutoff ({cutoff_date}). Stopping.")
                        hit_cutoff = True
                        break

                # Write to CSV
                csv_writer.writerow([date_posted, CATEGORY, title, art_url])
                csv_file.flush()
                scraped_urls.add(art_url)
                
                # Sleep between articles to be polite
                time.sleep(0.5)
                
            if hit_cutoff:
                break
                
            # Check clicks limit
            if max_pages is not None and clicks >= max_pages - 1:
                print(f"\nReached max pages/clicks limit of {max_pages}. Stopping.")
                break
                
            if not btn:
                print("\nNo 'แสดงเพิ่มเติม' button found. Reached the end of articles!")
                break
                
            print(f"\nClicking 'แสดงเพิ่มเติม' (Click count: {clicks+1})...")
            
            # Record number of articles before click
            prev_article_count = len(driver.find_elements(By.CSS_SELECTOR, "a.title"))
            
            # Scroll to and click the button
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
            time.sleep(1)
            driver.execute_script("arguments[0].click();", btn)
            
            # Wait dynamically for new articles to load
            start_time = time.time()
            loaded = False
            while time.time() - start_time < 5:
                try:
                    curr_article_count = len(driver.find_elements(By.CSS_SELECTOR, "a.title"))
                except Exception:
                    curr_article_count = prev_article_count
                
                if curr_article_count > prev_article_count:
                    loaded = True
                    break
                time.sleep(0.5)
                
            clicks += 1
            
    finally:
        csv_file.close()
        driver.quit()
        print("\nPPTV Scraper finished successfully.")

if __name__ == "__main__":
    main()
