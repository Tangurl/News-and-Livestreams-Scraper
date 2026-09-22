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
BASE_URL = "https://www.thansettakij.com"
CSV_FILE = os.path.join(SCRIPT_DIR, "thansettakij_economy.csv")
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

def parse_thansettakij_date(date_text):
    """Parses date from Thansettakij (either ISO-8601 or visible Thai text 'DD MMM YYYY | HH:MM น.').
    Returns (formatted_str, date_obj) where:
      formatted_str is in 'D MMM YYYY HH:MM น.' format (Thai months, Buddhist year)
      date_obj is a timezone-aware datetime object (ICT, UTC+7).
    """
    date_text = date_text.strip()
    
    # 1. ISO format check (e.g., "2026-06-09T14:54:00+07:00")
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

    # 2. Thai text format check (e.g., "09 มิ.ย. 2569 | 14:54 น." or "9 มิ.ย. 2569 | 14:54 น.")
    # Match: day, month, year, hours, minutes
    match = re.search(r"(\d{1,2})\s+([ก-์\.]+)\s+(\d{4})\s*\|\s*(\d{2})[:\.](\d{2})\s*น\.", date_text)
    if match:
        day_str = match.group(1)
        month_raw = match.group(2)
        year_str = match.group(3)
        hour_str = match.group(4)
        minute_str = match.group(5)
        
        long_months = ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน", "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]
        thai_months = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
        
        month_idx = 1
        month_short = month_raw
        for idx, (lm, sm) in enumerate(zip(long_months, thai_months)):
            if lm in month_raw or sm in month_raw or sm.replace(".", "") in month_raw:
                month_short = sm
                month_idx = idx + 1
                break
                
        formatted_str = f"{int(day_str)} {month_short} {year_str} {hour_str}:{minute_str} น."
        
        try:
            gregorian_year = int(year_str) - 543
            h, m = int(hour_str), int(minute_str)
            tz_ict = timezone(timedelta(hours=7))
            date_obj = datetime(gregorian_year, month_idx, int(day_str), h, m, tzinfo=tz_ict)
            return formatted_str, date_obj
        except Exception as e:
            print(f"Error creating datetime object from '{date_text}': {e}")
            return formatted_str, None
            
    return date_text, None

def get_article_date_from_detail(driver):
    """Retrieves article date from JSON-LD or meta tags in the detail page."""
    try:
        # Try to find JSON-LD datePublished
        html = driver.page_source
        match_pub = re.search(r'"datePublished"\s*:\s*"([^"]+)"', html)
        if match_pub:
            formatted, date_obj = parse_thansettakij_date(match_pub.group(1))
            if date_obj:
                return formatted, date_obj
    except Exception:
        pass
        
    try:
        # Try meta tag article:published_time
        meta_el = driver.find_element(By.CSS_SELECTOR, "meta[property='article:published_time']")
        content = meta_el.get_attribute("content")
        if content:
            formatted, date_obj = parse_thansettakij_date(content)
            if date_obj:
                return formatted, date_obj
    except Exception:
        pass
        
    return None, None

def main():
    parser = argparse.ArgumentParser(description="Scrape Thansettakij economy section.")
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

    print("Starting Thansettakij scraper...")
    try:
        list_url = f"{BASE_URL}/category/economy"
        print(f"Loading first page: {list_url}")
        try:
            driver.get(list_url)
            time.sleep(4)
            
            # Accept PDPA to avoid covering elements
            try:
                accept_btn = driver.find_element(By.CSS_SELECTOR, ".pdpa-mini-accept")
                accept_btn.click()
                time.sleep(1)
            except:
                pass
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
            
            # Find anchors only inside section-1 and section-3 blocks
            anchors = []
            try:
                sec1 = driver.find_element(By.CSS_SELECTOR, "#section-1 > div.wrapper-1 > div.block-1")
                anchors.extend(sec1.find_elements(By.TAG_NAME, "a"))
            except Exception:
                pass
            try:
                sec3 = driver.find_element(By.CSS_SELECTOR, "#section-3 > div.wrapper-1 > div.block-1")
                anchors.extend(sec3.find_elements(By.TAG_NAME, "a"))
            except Exception:
                pass
            batch_articles = {}
            for a in anchors:
                try:
                    href = a.get_attribute("href")
                    if not href:
                        continue
                    if href.startswith("/"):
                        href = BASE_URL + href
                    
                    if "/economy/" in href or "/blogs/economy/" in href:
                        match = re.search(r"/(?:blogs/)?economy/(?:.*/)?(\d+)/?$", href)
                        if match:
                            text = a.text.strip()
                            lines = [line.strip() for line in text.split("\n") if line.strip()]
                            
                            if href not in batch_articles:
                                batch_articles[href] = {
                                    "title": lines[0] if lines else None,
                                    "date_text": None,
                                    "date_obj": None
                                }
                            else:
                                if lines and not batch_articles[href]["title"]:
                                    batch_articles[href]["title"] = lines[0]
                                    
                            for line in lines:
                                if re.search(r"(\d{1,2})\s+([ก-์\.]+)\s+(\d{4})\s*\|\s*(\d{2})[:\.](\d{2})\s*น\.", line):
                                    formatted_str, date_obj = parse_thansettakij_date(line)
                                    if date_obj:
                                        batch_articles[href]["date_text"] = formatted_str
                                        batch_articles[href]["date_obj"] = date_obj
                                        break
                except Exception:
                    pass

            # Extract the unique URLs in order of appearance
            ordered_urls = []
            seen_urls = set()
            for a in anchors:
                try:
                    href = a.get_attribute("href")
                    if not href:
                        continue
                    if href.startswith("/"):
                        href = BASE_URL + href
                    if "/economy/" in href or "/blogs/economy/" in href:
                        match = re.search(r"/(?:blogs/)?economy/(?:.*/)?(\d+)/?$", href)
                        if match and href not in seen_urls:
                            seen_urls.add(href)
                            ordered_urls.append(href)
                except Exception:
                    pass
                    
            new_urls = [url for url in ordered_urls if url not in scraped_urls and url not in scraped_on_page]
            print(f"Found {len(seen_urls)} total articles on page/batch {page} (newly discovered: {len(new_urls)}).")
            
            if not seen_urls:
                print("No articles found. Stopping.")
                break
                
            for idx, art_url in enumerate(new_urls):
                art_data = batch_articles[art_url]
                title = art_data["title"]
                date_posted = art_data["date_text"]
                date_obj = art_data["date_obj"]
                
                # If date or title is missing from listing page, open in tab
                if not date_posted or not title:
                    try:
                        driver.execute_script("window.open(arguments[0], '_blank');", art_url)
                        driver.switch_to.window(driver.window_handles[-1])
                        time.sleep(0.5)
                        
                        detail_date_posted, detail_date_obj = get_article_date_from_detail(driver)
                        if not title:
                            try:
                                h1_el = driver.find_element(By.TAG_NAME, "h1")
                                title = h1_el.text.strip()
                            except:
                                title = driver.title.strip()
                                
                        driver.close()
                        driver.switch_to.window(driver.window_handles[0])
                        
                        if detail_date_obj:
                            date_posted = detail_date_posted
                            date_obj = detail_date_obj
                    except Exception as e:
                        print(f"    Error scraping detail tab for {art_url}: {e}")
                        try:
                            if len(driver.window_handles) > 1:
                                driver.close()
                        except:
                            pass
                        driver.switch_to.window(driver.window_handles[0])
                
                if not date_posted:
                    date_posted = "N/A"
                if not title:
                    title = "N/A"
                    
                print(f"  [{idx+1}/{len(new_urls)}] Title: {title} | Date: {date_posted}")
                
                # Cutoff check
                if cutoff_date is not None and date_obj is not None:
                    if date_obj < cutoff_date:
                        is_pinned = False
                        next_idx = idx + 1
                        while next_idx < len(new_urls):
                            next_url = new_urls[next_idx]
                            next_data = batch_articles[next_url]
                            next_date_obj = next_data["date_obj"]
                            
                            if not next_date_obj:
                                try:
                                    driver.execute_script("window.open(arguments[0], '_blank');", next_url)
                                    driver.switch_to.window(driver.window_handles[-1])
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
                
            # Click LOAD MORE
            try:
                buttons = driver.find_elements(By.TAG_NAME, "button")
                load_more_btn = None
                for btn in buttons:
                    if "LOAD MORE" in btn.text.upper():
                        load_more_btn = btn
                        break
            except Exception:
                load_more_btn = None
                
            if not load_more_btn:
                print("\nNo 'LOAD MORE' button found. Reached the last page.")
                break
                
            print("\nClicking 'LOAD MORE' to load more articles...")
            try:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", load_more_btn)
                time.sleep(0.5)
                driver.execute_script("arguments[0].click();", load_more_btn)
                
                initial_anchors_count = len(anchors)
                ajax_loaded = False
                for _ in range(40):
                    time.sleep(0.1)
                    current_anchors = []
                    try:
                        sec1 = driver.find_element(By.CSS_SELECTOR, "#section-1 > div.wrapper-1 > div.block-1")
                        current_anchors.extend(sec1.find_elements(By.TAG_NAME, "a"))
                    except Exception:
                        pass
                    try:
                        sec3 = driver.find_element(By.CSS_SELECTOR, "#section-3 > div.wrapper-1 > div.block-1")
                        current_anchors.extend(sec3.find_elements(By.TAG_NAME, "a"))
                    except Exception:
                        pass
                    if len(current_anchors) > initial_anchors_count:
                        ajax_loaded = True
                        break
                if not ajax_loaded:
                    print("LOAD MORE wait timed out. Stopping.")
                    break
                else:
                    time.sleep(1)
            except Exception as e:
                print(f"Error clicking LOAD MORE: {e}")
                break
                
            page += 1
            
    finally:
        csv_file.close()
        driver.quit()
        print("\nThansettakij Scraper finished.")

if __name__ == "__main__":
    main()
