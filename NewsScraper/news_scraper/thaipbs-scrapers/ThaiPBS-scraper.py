import os
import sys
import csv
import re
import argparse
import gspread
from datetime import datetime, timedelta, timezone
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import time

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def connect_sheet(sheet_name):
    creds = None
    script_dir = os.path.dirname(os.path.abspath(__file__))
    token_path = os.path.join(script_dir, "token.json")
    credentials_path = os.path.join(script_dir, "credentials.json")

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    client = gspread.authorize(creds)
    return client.open(sheet_name).sheet1

def create_driver(headless=False):
    options = Options()
    if headless:
        options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")

    driver = webdriver.Chrome(options=options)
    driver.implicitly_wait(5)

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

def convert_relative_to_absolute(date_str):
    date_str = date_str.strip()
    
    # Thailand is UTC+7
    tz_ict = timezone(timedelta(hours=7))
    now = datetime.now(tz_ict)
    
    thai_months = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
    
    # Check for minutes: e.g. "42 นาทีที่แล้ว"
    match_min = re.match(r"(\d+)\s+นาทีที่แล้ว", date_str)
    if match_min:
        mins = int(match_min.group(1))
        target_dt = now - timedelta(minutes=mins)
        day = target_dt.day
        month = thai_months[target_dt.month - 1]
        year = target_dt.year + 543
        hour_min = target_dt.strftime("%H:%M")
        return f"{day} {month} {year} {hour_min} น."
        
    # Check for hours: e.g. "1 ชั่วโมงที่แล้ว"
    match_hr = re.match(r"(\d+)\s+ชั่วโมงที่แล้ว", date_str)
    if match_hr:
        hrs = int(match_hr.group(1))
        target_dt = now - timedelta(hours=hrs)
        day = target_dt.day
        month = thai_months[target_dt.month - 1]
        year = target_dt.year + 543
        hour_min = target_dt.strftime("%H:%M")
        return f"{day} {month} {year} {hour_min} น."
        
    if "วันนี้" in date_str:
        match_time = re.search(r"(\d{2})[:\.](\d{2})", date_str)
        h, m = (int(match_time.group(1)), int(match_time.group(2))) if match_time else (now.hour, now.minute)
        day = now.day
        month = thai_months[now.month - 1]
        year = now.year + 543
        return f"{day} {month} {year} {h:02d}:{m:02d} น."
        
    if "เมื่อวานนี้" in date_str:
        yesterday = now - timedelta(days=1)
        match_time = re.search(r"(\d{2})[:\.](\d{2})", date_str)
        h, m = (int(match_time.group(1)), int(match_time.group(2))) if match_time else (0, 0)
        day = yesterday.day
        month = thai_months[yesterday.month - 1]
        year = yesterday.year + 543
        return f"{day} {month} {year} {h:02d}:{m:02d} น."
        
    return date_str

def main():
    parser = argparse.ArgumentParser(description="Scrape ThaiPBS archive.")
    parser.add_argument(
        "-d", "--days",
        type=int,
        default=5,
        help="Number of days to scrape"
    )
    args = parser.parse_args()
    max_days = args.days

    script_dir = os.path.dirname(os.path.abspath(__file__))
    csv_file_path = os.path.join(script_dir, "thaipbs_all.csv")

    # Load existing URLs to avoid duplicates
    scraped_urls = set()
    file_exists = os.path.exists(csv_file_path)
    if file_exists:
        try:
            with open(csv_file_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                next(reader, None)
                for row in reader:
                    # Handle both 4-column and 5-column formats to stay backward compatible
                    if len(row) >= 4:
                        link = row[3] if len(row) == 4 else row[4]
                        scraped_urls.add(link)
            print(f"Loaded {len(scraped_urls)} already scraped articles from local CSV.")
        except Exception as e:
            print("Error reading existing CSV:", e)

    # Open CSV for appending
    csv_file = open(csv_file_path, "a", encoding="utf-8", newline="")
    csv_writer = csv.writer(csv_file)
    if not file_exists:
        csv_writer.writerow(["date", "category", "channel", "article title", "article link"])
        csv_file.flush()

    print(f"Connecting to Google Sheets...")
    sheet = None
    try:
        sheet = connect_sheet("Selenium Test Sheet")
    except Exception as e:
        print(f"Warning: Could not connect to Google Sheet: {e}. Scraper will continue saving locally.")

    print(f"Starting WebDriver...")
    driver = create_driver(headless=True) # Default to headless for CLI execution
    
    # Use today's date in Thailand timezone (UTC+7)
    tz_ict = timezone(timedelta(hours=7))
    date = datetime.now(tz_ict)

    try:
        for i in range(max_days):
            current_date = date - timedelta(days=i)
            url = f"https://www.thaipbs.or.th/news/archive/{current_date.strftime('%Y-%m-%d')}"
            print(f"Scraping date: {current_date.strftime('%Y-%m-%d')} - {url}")
            
            driver.get(url)
            wait = WebDriverWait(driver, 10)
            try:
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".list-container article")))
            except TimeoutException:
                print(f"No articles found or timeout waiting for articles on {current_date.strftime('%Y-%m-%d')}")
                continue
            
            articles = driver.find_elements(By.CSS_SELECTOR, ".list-container article")
            new_rows = []
            for article in articles:
                try:
                    title  = article.find_element(By.CSS_SELECTOR, "a[href] h3").text
                    link   = article.find_element(By.CSS_SELECTOR, "a[href]").get_attribute("href")
                    posted = article.find_element(By.CSS_SELECTOR, "time").text
                    kind   = article.find_element(By.CSS_SELECTOR, "time ~ a").text
                    
                    # Convert to accurate literal date format
                    literal_date = convert_relative_to_absolute(posted)
                    
                    if link not in scraped_urls:
                        print(f"  {literal_date} | {kind} | ThaiPBS | {title} | {link}")
                        csv_writer.writerow([literal_date, kind, "ThaiPBS", title, link])
                        csv_file.flush()
                        scraped_urls.add(link)
                        new_rows.append([literal_date, kind, "ThaiPBS", title, link])
                except Exception as e:
                    print(f"Error extracting article: {e}")
                    
            if new_rows and sheet is not None:
                try:
                    sheet.append_rows(new_rows)
                    print(f"Saved {len(new_rows)} new articles to Google Sheet.")
                except Exception as e:
                    print(f"Error saving to Google Sheet: {e}")
            else:
                print(f"Processed {len(articles)} articles. Saved {len(new_rows)} new articles locally.")

    except Exception as e:
        print(f"Error during scraping: {e}")
        driver.save_screenshot(os.path.join(script_dir, "error.png"))

    finally:
        csv_file.close()
        driver.quit()

if __name__ == "__main__":
    main()
