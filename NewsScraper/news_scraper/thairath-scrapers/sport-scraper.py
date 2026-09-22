import os
import re
import csv
import time
import argparse
from datetime import datetime, timezone, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_URL = "https://www.thairath.co.th"
CSV_FILE = os.path.join(SCRIPT_DIR, "thairath_sport.csv")
CATEGORY = "กีฬา"

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

def extract_sport_info(href):
    """Extracts subcategory and article ID from Thairath sport URL href."""
    if not href:
        return None, None
    match = re.search(r"sport/worldsport/([^/]+)/(\d+)", href)
    if match:
        return match.group(1), match.group(2)
    return None, None

def get_article_date(driver, url, max_retries=3):
    """Navigates to the article page and scrapes its publication date.
    Returns (date_text, date_obj)."""
    for attempt in range(max_retries):
        try:
            driver.get(url)
            # Give it a moment to load (0.5s is plenty for eager strategy)
            time.sleep(0.5)
            
            date_text = None
            iso_str = None
            
            # 1. Try scraping using regex on the entire page source first (very fast & handles Next.js JSON formats)
            try:
                html = driver.page_source
                match_th = re.search(r'publishTimeTh\\*"\s*:\s*\\*"([^"\\]+)\\*"', html)
                if match_th:
                    date_text = match_th.group(1)
                
                match_pub = re.search(r'datePublished\\*"\s*:\s*\\*"([^"\\]+)\\*"', html)
                if match_pub:
                    iso_str = match_pub.group(1)
            except Exception:
                pass
            
            # 2. Try finding the visible date div if date_text parsing failed
            if not date_text:
                try:
                    date_el = driver.find_element(By.CSS_SELECTOR, "div[class*='__item_article-date']")
                    date_text = date_el.text.strip()
                except Exception:
                    pass
                
            # 3. Try scraping the ISO string from meta tags if iso_str parsing failed
            if not iso_str:
                try:
                    meta_el = driver.find_element(By.XPATH, "//meta[@property='og:article:published_time' or @property='article:published_time']")
                    iso_str = meta_el.get_attribute("content")
                except Exception:
                    pass
            
            # Parse ISO string to datetime object
            date_obj = None
            if iso_str:
                try:
                    date_obj = datetime.fromisoformat(iso_str)
                except Exception:
                    pass
            
            # If we still don't have date_text, fallback to iso_str or N/A
            if not date_text:
                date_text = iso_str if iso_str else "N/A"
            else:
                # Clean up prefix if visible element was used
                if date_text.startswith("ไทยรัฐออนไลน์"):
                    date_text = date_text.replace("ไทยรัฐออนไลน์", "").strip()
                
            return date_text, date_obj
                
        except Exception as e:
            print(f"  [Attempt {attempt+1}/{max_retries}] Error loading article {url}: {e}")
            time.sleep(2)
            
    return "N/A", None

def main():
    parser = argparse.ArgumentParser(description="Scrape Thairath worldsport section.")
    parser.add_argument(
        "-p", "--pages",
        type=int,
        default=None,
        help="Max clicks on 'ดูเพิ่ม' button (default: click until the end of articles)"
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

    print("Starting scraper...")
    try:
        list_url = f"{BASE_URL}/sport/worldsport"
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
            # 1. Resolve the "ดูเพิ่ม" button first to help locate the article container and handle pagination
            btn = None
            try:
                btn = driver.find_element(By.CSS_SELECTOR, "body > div.css-1vmz8qx.ef6nub519 > div.css-qcxt5r.e1sh2apk4 > main > div:nth-child(5) > div > div > div.css-xya191.e1sh2apk17 > a")
            except Exception:
                try:
                    btn = driver.find_element(By.XPATH, "//a[contains(text(), 'ดูเพิ่ม')]")
                except Exception:
                    pass

            # Resolve the article container
            container = None
            if btn:
                try:
                    container = btn.find_element(By.XPATH, "./../..")
                except Exception:
                    pass

            if not container:
                try:
                    container = driver.find_element(By.CSS_SELECTOR, "body > div.css-1vmz8qx.ef6nub519 > div.css-qcxt5r.e1sh2apk4 > main > div:nth-child(5) > div > div")
                except Exception:
                    pass

            # Find all h3 tags to extract links from within the container
            if container:
                h3_elements = container.find_elements(By.TAG_NAME, "h3")
            else:
                h3_elements = driver.find_elements(By.TAG_NAME, "h3")

            articles_to_scrape = []
            for h3 in h3_elements:
                try:
                    a_elements = h3.find_elements(By.TAG_NAME, "a")
                    for a in a_elements:
                        href = a.get_attribute("href")
                        title = a.get_attribute("textContent").strip() or a.get_attribute("title") or a.text.strip()
                        
                        subcategory, art_id = extract_sport_info(href)
                        if subcategory and art_id and title:
                            art_url = f"{BASE_URL}/sport/worldsport/{subcategory}/{art_id}"
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
                
            # Check click limit
            if max_pages is not None and clicks >= max_pages - 1:
                print(f"\nReached max pages/clicks limit of {max_pages}. Stopping.")
                break
                
            if not btn:
                print("\nNo 'ดูเพิ่ม' button found. Reached the end of articles!")
                break
                
            print(f"\nClicking 'ดูเพิ่ม' (Click count: {clicks+1})...")
            
            # Record number of articles before click
            if container:
                prev_article_count = len(container.find_elements(By.XPATH, ".//h3/a[contains(@href, '/sport/worldsport/')]"))
            else:
                prev_article_count = len(driver.find_elements(By.XPATH, "//h3/a[contains(@href, '/sport/worldsport/')]"))
            
            # Scroll to and click the button directly in the current DOM
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
            time.sleep(1)
            driver.execute_script("arguments[0].click();", btn)
            
            # Wait dynamically for new articles to load
            start_time = time.time()
            loaded = False
            while time.time() - start_time < 5:
                if container:
                    try:
                        curr_article_count = len(container.find_elements(By.XPATH, ".//h3/a[contains(@href, '/sport/worldsport/')]"))
                    except Exception:
                        # Re-resolve the container if it became stale due to dynamic DOM updates
                        try:
                            container = driver.find_element(By.CSS_SELECTOR, "body > div.css-1vmz8qx.ef6nub519 > div.css-qcxt5r.e1sh2apk4 > main > div:nth-child(5) > div > div")
                            curr_article_count = len(container.find_elements(By.XPATH, ".//h3/a[contains(@href, '/sport/worldsport/')]"))
                        except Exception:
                            curr_article_count = prev_article_count
                else:
                    curr_article_count = len(driver.find_elements(By.XPATH, "//h3/a[contains(@href, '/sport/worldsport/')]"))
                
                if curr_article_count > prev_article_count:
                    loaded = True
                    break
                time.sleep(0.5)
                
            if not loaded:
                print("Timed out waiting for new articles to load after clicking. Stopping.")
                break
                
            clicks += 1
            
    finally:
        csv_file.close()
        driver.quit()
        print("\nSport-Scraper finished successfully.")

if __name__ == "__main__":
    main()
