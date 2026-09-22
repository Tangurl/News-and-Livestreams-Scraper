import os
import re
import csv
import sys
import argparse
import subprocess
from datetime import datetime, timedelta

# Configuration
WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
MASTER_CSV = os.path.join(WORKSPACE_DIR, "master_scraped_data.csv")

SCRAPER_DIRS = [
    "pptv-scrapers",
    "thaipost-scrapers",
    "naewna-scrapers",
    "thairath-scrapers",
    "komchadluek-scrapers",
    "thansettakij-scrapers",
    "bangkokpost-scrapers",
    "thaipbs-scrapers",
    "amarintv-scrapers",
    "dailynews-scrapers",
    "thestandard-scrapers",
    "matichon-scrapers",
    "khaosod-scrapers"
]

def find_scrapers():
    """Finds all python scraper scripts inside the configured directories."""
    scrapers = []
    for s_dir in SCRAPER_DIRS:
        dir_path = os.path.join(WORKSPACE_DIR, s_dir)
        if os.path.isdir(dir_path):
            for f in os.listdir(dir_path):
                if f.endswith(".py") and "scraper" in f.lower():
                    # Exclude run_all itself (though it is at root, check just in case)
                    scrapers.append(os.path.join(dir_path, f))
    return scrapers

def get_csv_path(scraper_path):
    """Finds the CSV file output path by reading the scraper script content."""
    try:
        with open(scraper_path, "r", encoding="utf-8") as f:
            content = f.read()
        matches = re.findall(r'["\']([^"\']+\.csv)["\']', content)
        if matches:
            scraper_dir = os.path.dirname(scraper_path)
            return os.path.abspath(os.path.join(scraper_dir, matches[0]))
    except Exception:
        pass
    return None

def count_csv_rows(csv_path):
    """Counts the number of rows in the CSV (excluding header)."""
    if not csv_path or not os.path.exists(csv_path):
        return 0
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
            if len(rows) > 0:
                return len(rows) - 1
            return 0
    except Exception:
        return 0

def run_scraper(scraper_path, days=None):
    """Runs a single scraper script in a subprocess with cwd set to its directory.
    Streams output in real-time and captures output to verify successful execution."""
    script_name = os.path.basename(scraper_path)
    script_dir = os.path.dirname(scraper_path)
    
    print(f"\n==========================================")
    print(f"RUNNING SCRAPER: {script_name} (in {os.path.basename(script_dir)})")
    print(f"==========================================")
    
    cmd = [sys.executable, "-u", script_name]
    if days is not None:
        cmd.extend(["-d", str(days)])
        
    output_lines = []
    try:
        # Run with real-time streaming and stderr redirection
        process = subprocess.Popen(
            cmd,
            cwd=script_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        for line in process.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            output_lines.append(line)
            
        process.wait()
        return_code = process.returncode
        full_output = "".join(output_lines)
        
        # Check for error patterns in stdout/stderr logs
        fatal_patterns = [
            "Error loading main page",
            "ERR_CONNECTION_TIMED_OUT",
            "ERR_NAME_NOT_RESOLVED",
            "ERR_TIMED_OUT",
            "ERR_CONNECTION_CLOSED",
            "ERR_CONNECTION_RESET",
            "Max retries exceeded",
            "Traceback (most recent call last):",
            "WebDriverException",
            "TimeoutException"
        ]
        
        failed = False
        error_msg = ""
        
        if return_code != 0:
            failed = True
            error_msg = f"Exit code {return_code}"
        else:
            for pattern in fatal_patterns:
                if pattern in full_output:
                    # Ignore normal timeout warnings in ThaiPBS when no articles are posted
                    if pattern == "TimeoutException" and "TimeoutException waiting for articles" in full_output:
                        continue
                    failed = True
                    error_msg = f"Fatal log: {pattern}"
                    break
                    
        if failed:
            print(f"\nScraper {script_name} failed: {error_msg}")
            return False, error_msg
            
        print(f"\nScraper {script_name} finished successfully.")
        return True, "Success"
        
    except Exception as e:
        print(f"Unexpected error running {script_name}: {e}")
        return False, str(e)

def parse_thai_date(date_str):
    """Parses Thai Buddhist Era date strings to timezone-naive datetime objects for sorting.
    Examples:
      - '10 มิ.ย. 2569 18:22 น.'
      - '2 มิ.ย. 69'
      - '10/06/2026'
      - '42 นาทีที่แล้ว'
      - '1 ชั่วโมงที่แล้ว'
    """
    if not date_str or date_str == "N/A":
        return datetime.min
        
    date_str = date_str.replace(" น.", "").strip()
    
    # Handle relative Thai dates (e.g., '42 นาทีที่แล้ว', '1 ชั่วโมงที่แล้ว')
    now = datetime.now()
    
    match_min = re.match(r"(\d+)\s+นาทีที่แล้ว", date_str)
    if match_min:
        mins = int(match_min.group(1))
        return now - timedelta(minutes=mins)
        
    match_hr = re.match(r"(\d+)\s+ชั่วโมงที่แล้ว", date_str)
    if match_hr:
        hrs = int(match_hr.group(1))
        return now - timedelta(hours=hrs)
        
    if "วันนี้" in date_str:
        match_time = re.search(r"(\d{2})[:\.](\d{2})", date_str)
        if match_time:
            h, m = map(int, match_time.groups())
            return now.replace(hour=h, minute=m, second=0, microsecond=0)
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
        
    if "เมื่อวานนี้" in date_str:
        yesterday = now - timedelta(days=1)
        match_time = re.search(r"(\d{2})[:\.](\d{2})", date_str)
        if match_time:
            h, m = map(int, match_time.groups())
            return yesterday.replace(hour=h, minute=m, second=0, microsecond=0)
        return yesterday.replace(hour=0, minute=0, second=0, microsecond=0)

    # Check for DD/MM/YYYY format
    if "/" in date_str:
        try:
            parts = date_str.split("/")
            if len(parts) == 3:
                day, month, year = map(int, parts)
                return datetime(year, month, day)
        except:
            pass
            
    parts = date_str.split()
    if len(parts) < 3:
        return datetime.min
        
    day_str, month_str, year_str = parts[0], parts[1], parts[2]
    time_str = parts[3] if len(parts) >= 4 else "00:00"
    
    thai_months = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
    try:
        day = int(day_str)
        month = thai_months.index(month_str) + 1
        
        year = int(year_str)
        if year < 100:
            year += 2500 # Convert short year (69) to Buddhist Era (2569)
        year -= 543     # Convert Buddhist Era to Gregorian (2569 -> 2026)
        
        hour, minute = map(int, time_str.split(":"))
        return datetime(year, month, day, hour, minute)
    except Exception:
        return datetime.min

def merge_csv_outputs(days=None):
    """Reads all generated CSV files from scraper directories, merges them, sorts them by date, and writes the master CSV.
    If days is specified, filters the merged articles accordingly:
      - days > 0: includes articles from today and up to (days-1) days ago.
      - days < 0: includes articles from yesterday up to abs(days) days ago, excluding today.
    """
    print(f"\nMerging scraped CSV files...")
    
    # Calculate start and end date ranges for filtering
    now_naive = datetime.now()
    start_of_today = now_naive.replace(hour=0, minute=0, second=0, microsecond=0)
    
    start_date = None
    end_date = None
    
    if days is not None:
        if days > 0:
            start_date = start_of_today - timedelta(days=days - 1)
        elif days < 0:
            num_days = abs(days)
            start_date = start_of_today - timedelta(days=num_days)
            end_date = start_of_today
            
    if start_date:
        if end_date:
            print(f"Filtering merged articles to date range: [{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')})")
        else:
            print(f"Filtering merged articles to start on or after: {start_date.strftime('%Y-%m-%d')}")
            
    merged_rows = []
    seen_links = set()
    
    # Helper mapping for channel names
    channel_mapping = {
        "pptv-scrapers": "PPTV",
        "thaipost-scrapers": "ThaiPost",
        "naewna-scrapers": "Naewna",
        "thairath-scrapers": "Thairath",
        "komchadluek-scrapers": "Komchadluek",
        "thansettakij-scrapers": "Thansettakij",
        "bangkokpost-scrapers": "Bangkok Post",
        "thaipbs-scrapers": "ThaiPBS",
        "amarintv-scrapers": "Amarin TV",
        "dailynews-scrapers": "Daily News",
        "thestandard-scrapers": "The Standard",
        "matichon-scrapers": "Matichon",
        "khaosod-scrapers": "Khaosod"
    }
    
    # Scan scraper directories for CSV files
    for s_dir in SCRAPER_DIRS:
        dir_path = os.path.join(WORKSPACE_DIR, s_dir)
        if not os.path.isdir(dir_path):
            continue
            
        channel_name = channel_mapping.get(s_dir, "Unknown")
            
        for f in os.listdir(dir_path):
            if f.endswith(".csv"):
                csv_path = os.path.join(dir_path, f)
                print(f"Reading CSV: {f}")
                try:
                    with open(csv_path, "r", encoding="utf-8") as file:
                        reader = csv.reader(file)
                        header = next(reader, None) # Skip header
                        if not header:
                            continue
                            
                        for row in reader:
                            if len(row) == 4:
                                date_str, category, title, link = row[0], row[1], row[2], row[3]
                                ch = channel_name
                            elif len(row) >= 5:
                                date_str, category, ch, title, link = row[0], row[1], row[2], row[3], row[4]
                            else:
                                continue
                                
                            if link not in seen_links:
                                seen_links.add(link)
                                parsed_date = parse_thai_date(date_str)
                                
                                # Filter checks
                                if start_date is not None and parsed_date < start_date:
                                    continue
                                if end_date is not None and parsed_date >= end_date:
                                    continue
                                    
                                merged_rows.append({
                                    "date_obj": parsed_date,
                                    "row_data": [date_str, category, ch, title, link]
                                })
                except Exception as e:
                    print(f"  Error reading {f}: {e}")
                    
    # Sort merged rows by date_obj in descending order (newest first)
    merged_rows.sort(key=lambda x: x["date_obj"], reverse=True)
    
    # Write to master CSV
    try:
        with open(MASTER_CSV, "w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["date", "category", "channel", "article title", "article link"])
            for item in merged_rows:
                writer.writerow(item["row_data"])
        print(f"\nSuccess! Merged {len(merged_rows)} unique articles into: {MASTER_CSV}")
    except Exception as e:
        print(f"Error writing master CSV: {e}")

def print_summary_table(results):
    """Prints a formatted console table summarizing the run of all scrapers."""
    headers = ["Scraper Channel", "Category", "Status", "New", "Total"]
    widths = [len(h) for h in headers]
    for r in results:
        widths[0] = max(widths[0], len(r["channel"]))
        widths[1] = max(widths[1], len(r["category"]))
        widths[2] = max(widths[2], len(r["status_str"]))
        widths[3] = max(widths[3], len(str(r["new_count"])))
        widths[4] = max(widths[4], len(str(r["total_count"])))
        
    row_fmt = " | ".join(f"{{:<{w}}}" for w in widths)
    sep_line = "-+-".join("-" * w for w in widths)
    
    print("\n=====================================================================")
    print("                      SCRAPING EXECUTION SUMMARY                     ")
    print("=====================================================================")
    print(row_fmt.format(*headers))
    print(sep_line)
    
    total_new = 0
    total_db = 0
    successful_runs = 0
    
    for r in results:
        print(row_fmt.format(
            r["channel"],
            r["category"],
            r["status_str"],
            r["new_count"],
            r["total_count"]
        ))
        total_new += r["new_count"]
        total_db += r["total_count"]
        if r["success"]:
            successful_runs += 1
            
    print(sep_line)
    print(row_fmt.format(
        "TOTAL",
        "",
        f"{successful_runs}/{len(results)} Success",
        total_new,
        total_db
    ))
    print("=====================================================================")

def main():
    parser = argparse.ArgumentParser(description="Master scraper runner.")
    parser.add_argument(
        "-d", "--days",
        type=int,
        default=None,
        help="Number of days to scrape (1 for today only, 2 for today and yesterday, etc., or negative: -1 for yesterday only, -2 yesterday and day before)"
    )
    parser.add_argument(
        "-m", "--merge-only",
        action="store_true",
        help="Only merge the existing CSV files without running any scrapers"
    )
    args = parser.parse_args()
    days = args.days
    merge_only = args.merge_only
    
    if merge_only:
        merge_csv_outputs(days)
        return
        
    # 1. Discover scrapers
    scrapers = find_scrapers()
    print(f"Discovered {len(scrapers)} scraper scripts:")
    for s in scrapers:
        print(f"  - {os.path.relpath(s, WORKSPACE_DIR)}")
        
    if not scrapers:
        print("No scraper scripts found. Stopping.")
        return
        
    # Channel and category mappings for table
    channel_mapping = {
        "pptv-scrapers": "PPTV",
        "thaipost-scrapers": "ThaiPost",
        "naewna-scrapers": "Naewna",
        "thairath-scrapers": "Thairath",
        "komchadluek-scrapers": "Komchadluek",
        "thansettakij-scrapers": "Thansettakij",
        "bangkokpost-scrapers": "Bangkok Post",
        "thaipbs-scrapers": "ThaiPBS",
        "amarintv-scrapers": "Amarin TV",
        "dailynews-scrapers": "Daily News",
        "thestandard-scrapers": "The Standard",
        "matichon-scrapers": "Matichon",
        "khaosod-scrapers": "Khaosod"
    }
    
    category_mapping = {
        "society": "สังคม",
        "politic": "การเมือง",
        "crime": "อาชญากรรม",
        "criminality": "อาชญากรรม",
        "sport": "กีฬา",
        "sports": "กีฬา",
        "economy": "เศรษฐกิจ",
        "economic": "เศรษฐกิจ",
        "foreign": "ต่างประเทศ",
        "abroad": "ต่างประเทศ",
        "thaipbs": "ทั้งหมด"
    }
    
    # 2. Run all scrapers sequentially
    results = []
    
    # Scale days parameter if negative to ensure the scrapers fetch yesterday's content
    scraper_days = None
    if days is not None:
        if days > 0:
            scraper_days = days
        else:
            scraper_days = abs(days) + 1  # e.g. -1 -> 2, covering today and yesterday
            
    for s in scrapers:
        s_dir = os.path.basename(os.path.dirname(s))
        s_name = os.path.basename(s)
        
        channel_name = channel_mapping.get(s_dir, s_dir)
        cat_key = s_name.split("-")[0].lower()
        if cat_key == "thaipbs":
            category_name = "ทั้งหมด"
        else:
            category_name = category_mapping.get(cat_key, cat_key)
            
        csv_path = get_csv_path(s)
        initial_rows = count_csv_rows(csv_path)
        
        success, err_msg = run_scraper(s, scraper_days)
        
        final_rows = count_csv_rows(csv_path)
        new_scraped = max(0, final_rows - initial_rows)
        
        status_str = "SUCCESS" if success else f"FAILED ({err_msg})"
        
        results.append({
            "channel": channel_name,
            "category": category_name,
            "success": success,
            "status_str": status_str,
            "new_count": new_scraped,
            "total_count": final_rows
        })
            
    # 3. Print Summary Table
    print_summary_table(results)
    
    # 4. Merge CSV outputs
    merge_csv_outputs(days)

if __name__ == "__main__":
    main()
