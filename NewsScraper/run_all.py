import os
import re
import csv
import sys
import time
import argparse
import subprocess
import threading
import concurrent.futures
from datetime import datetime, timedelta

print_lock = threading.Lock()

def safe_print(*args, **kwargs):
    """Thread-safe print function."""
    with print_lock:
        print(*args, **kwargs)
        sys.stdout.flush()

# Configuration
WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(WORKSPACE_DIR)
MASTER_CSV = os.path.join(WORKSPACE_DIR, "master_scraped_data.csv")

ROOT_ENV = os.path.join(ROOT_DIR, ".env")
if not os.path.isfile(ROOT_ENV):
    safe_print(f"❌ [Config Error] Root .env file not found at: {ROOT_ENV}")
    safe_print("A .env file at the project root is strictly required. Halting execution.")
    sys.exit(1)

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT_ENV, override=True)
except ImportError:
    pass

with open(ROOT_ENV, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                v = v[1:-1]
            os.environ.setdefault(k, v)

GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "").strip()
GOOGLE_SHEET_URL = f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}/edit?usp=sharing"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

SCRAPER_DIRS = [
    "amarintv-scrapers",
    "bangkokbiznews-scrapers",
    "bangkokpost-scrapers",
    "banmuang-scrapers",
    "ch7-scrapers",
    "chiangmainews-scrapers",
    "dailynews-scrapers",
    "ejan-scrapers",
    "honekrasae-scrapers",
    "kaohoon-scrapers",
    "khaosod-scrapers",
    "khaosodenglish-scrapers",
    "komchadluek-scrapers",
    "koratdaily-scrapers",
    "matichon-scrapers",
    "mcot-scrapers",
    "mgronline-scrapers",
    "naewna-scrapers",
    "nationthailand-scrapers",
    "nationtv-scrapers",
    "nbt-scrapers",
    "nextnewsth-scrapers",
    "posttoday-scrapers",
    "pptv-scrapers",
    "prachachat-scrapers",
    "siamrath-scrapers",
    "springnews-scrapers",
    "thainews-scrapers",
    "thaipbs-scrapers",
    "thaipbsworld-scrapers",
    "thaipost-scrapers",
    "thairath-scrapers",
    "thansettakij-scrapers",
    "thestandard-scrapers",
    "tnews-scrapers",
    "tnnthailand-scrapers",
    "workpointtoday-scrapers"
]

def find_scrapers():
    """Finds all python scraper scripts inside the configured directories."""
    scrapers = []
    for s_dir in SCRAPER_DIRS:
        dir_path = os.path.join(WORKSPACE_DIR, s_dir)
        if os.path.isdir(dir_path):
            for f in sorted(os.listdir(dir_path)):
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

def run_single_scraper_worker(scraper_info, days=None, total_count=0, progress_tracker=None, verbose=False, timeout_seconds=300):
    """Runs a single scraper script in a subprocess with cwd set to its directory.
    Thread-safe and supports concurrent worker execution."""
    s = scraper_info["path"]
    channel_name = scraper_info["channel"]
    category_name = scraper_info["category"]
    script_name = os.path.basename(s)
    script_dir = os.path.dirname(s)
    csv_path = get_csv_path(s)
    
    initial_rows = count_csv_rows(csv_path)
    
    with print_lock:
        if progress_tracker is not None:
            progress_tracker["started"] += 1
            start_idx = progress_tracker["started"]
        else:
            start_idx = 1
            
    safe_print(f"[{start_idx}/{total_count}] 🚀 STARTING: {channel_name} - {category_name} ({script_name})")
    
    cmd = [sys.executable, "-u", script_name]
    if days is not None:
        cmd.extend(["-d", str(days)])
        
    output_lines = []
    try:
        process = subprocess.Popen(
            cmd,
            cwd=script_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        for line in process.stdout:
            if verbose:
                safe_print(f"[{channel_name} | {category_name}] {line.rstrip()}")
            output_lines.append(line)
            
        try:
            if timeout_seconds and timeout_seconds > 0:
                process.wait(timeout=timeout_seconds)
            else:
                process.wait()
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            output_lines.append(f"\n[Process Timed Out after {timeout_seconds} seconds]")
            
        return_code = process.returncode
        full_output = "".join(output_lines)
        
        # Check for fatal error patterns in logs
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
        
        if "[Process Timed Out" in full_output:
            failed = True
            error_msg = "Timed out (180s)"
        elif return_code != 0:
            failed = True
            error_msg = f"Exit code {return_code}"
        else:
            for pattern in fatal_patterns:
                if pattern in full_output:
                    # Ignore normal timeout warnings in ThaiPBS when no articles are posted
                    if pattern == "TimeoutException" and ("TimeoutException waiting for articles" in full_output or "timeout" in full_output.lower()):
                        continue
                    failed = True
                    error_msg = f"Fatal log: {pattern}"
                    break
                    
        final_rows = count_csv_rows(csv_path)
        new_scraped = max(0, final_rows - initial_rows)
        
        with print_lock:
            if progress_tracker is not None:
                progress_tracker["finished"] += 1
                fin_idx = progress_tracker["finished"]
            else:
                fin_idx = 1
                
        if failed:
            safe_print(f"[{fin_idx}/{total_count}] ❌ FAILED: {channel_name} - {category_name} ({error_msg})")
            status_str = f"FAILED ({error_msg})"
            success = False
        else:
            safe_print(f"[{fin_idx}/{total_count}] ✅ DONE: {channel_name} - {category_name} (+{new_scraped} new, {final_rows} total)")
            status_str = "SUCCESS"
            success = True
            
        return {
            "channel": channel_name,
            "category": category_name,
            "success": success,
            "status_str": status_str,
            "new_count": new_scraped,
            "total_count": final_rows,
            "log": full_output
        }
    except Exception as e:
        with print_lock:
            if progress_tracker is not None:
                progress_tracker["finished"] += 1
                fin_idx = progress_tracker["finished"]
            else:
                fin_idx = 1
        safe_print(f"[{fin_idx}/{total_count}] ❌ ERROR: {channel_name} - {category_name} ({e})")
        return {
            "channel": channel_name,
            "category": category_name,
            "success": False,
            "status_str": f"ERROR ({e})",
            "new_count": 0,
            "total_count": count_csv_rows(csv_path),
            "log": str(e)
        }

# Option A: Strict Standard Category Normalization (6 Core Categories + อื่นๆ)
CATEGORY_NORMALIZATION = {
    # 1. การเมือง (Politics)
    "การเมือง": "การเมือง",
    "การเมืองไทย": "การเมือง",
    "politics": "การเมือง",
    "politic": "การเมือง",
    "policy": "การเมือง",
    "วิเคราะห์ การเมือง": "การเมือง",

    # 2. เศรษฐกิจ (Economy & Business)
    "เศรษฐกิจ": "เศรษฐกิจ",
    "เศรษฐกิจไทย": "เศรษฐกิจ",
    "economy": "เศรษฐกิจ",
    "economic": "เศรษฐกิจ",
    "economics": "เศรษฐกิจ",
    "business": "เศรษฐกิจ",
    "finance": "เศรษฐกิจ",
    "banking-finance": "เศรษฐกิจ",
    "trading-investment": "เศรษฐกิจ",
    "property": "เศรษฐกิจ",
    "real-estate": "เศรษฐกิจ",
    "corporate": "เศรษฐกิจ",
    "tech": "เศรษฐกิจ",
    "trade": "เศรษฐกิจ",
    "Smart SME": "เศรษฐกิจ",
    "ธุรกิจ": "เศรษฐกิจ",
    "สังคมธุรกิจ": "เศรษฐกิจ",
    "การเงิน": "เศรษฐกิจ",
    "Wealth": "เศรษฐกิจ",
    "Digital-business": "เศรษฐกิจ",
    "เกษตร": "เศรษฐกิจ",

    # 3. สังคม (Society & Domestic)
    "สังคม": "สังคม",
    "ข่าวสังคม": "สังคม",
    "social": "สังคม",
    "general": "สังคม",
    "in-country": "สังคม",
    "ในประเทศ": "สังคม",
    "ทั่วไทย": "สังคม",
    "around-thailand": "สังคม",
    "สาธารณภัย": "สังคม",
    "สกู๊ปสังคม": "สังคม",
    "Bangkok": "สังคม",
    "ทั่วไป": "สังคม",
    "ข่าวทั่วไป": "สังคม",
    "Health": "สังคม",
    "สุขภาพ": "สังคม",
    "เกาะติด COVID-19": "สังคม",
    "พยากรณ์อากาศ": "สังคม",
    "Earth": "สังคม",
    "Smart City": "สังคม",

    # 4. อาชญากรรม (Crime & Justice)
    "อาชญากรรม": "อาชญากรรม",
    "crime": "อาชญากรรม",
    "criminality": "อาชญากรรม",
    "investigative": "อาชญากรรม",
    "สืบสวนเชิงลึก": "อาชญากรรม",
    "ลักวิ่งชิงปล้น": "อาชญากรรม",

    # 5. กีฬา (Sports)
    "กีฬา": "กีฬา",
    "sport": "กีฬา",
    "sports": "กีฬา",
    "วอลเลย์บอล": "กีฬา",

    # 6. ต่างประเทศ (International / World)
    "ต่างประเทศ": "ต่างประเทศ",
    "foreign": "ต่างประเทศ",
    "abroad": "ต่างประเทศ",
    "world": "ต่างประเทศ",
    "international": "ต่างประเทศ",
    "asean": "ต่างประเทศ",
    "เศรษฐกิจต่างประเทศ": "ต่างประเทศ",
    "World": "ต่างประเทศ",
}

def normalize_category(cat):
    """Maps arbitrary / channel-specific category names to strict Option A categories."""
    if not cat or cat.strip() in ["-", "N/A", ""]:
        return "อื่นๆ"
    clean = cat.strip()
    return CATEGORY_NORMALIZATION.get(clean, "อื่นๆ")

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
                if year > 2400:
                    year -= 543
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
        if year > 2400:
            year -= 543     # Convert Buddhist Era to Gregorian (2569 -> 2026)
        
        time_parts = time_str.split(":") if ":" in time_str else time_str.split(".")
        hour = int(time_parts[0]) if len(time_parts) >= 1 else 0
        minute = int(time_parts[1]) if len(time_parts) >= 2 else 0
        return datetime(year, month, day, hour, minute)
    except Exception:
        return datetime.min

def sync_to_google_sheet(csv_path, sheet_id=None):
    """Syncs the master CSV content to Google Spreadsheet."""
    target_sheet_id = (sheet_id or GOOGLE_SHEET_ID or os.environ.get("GOOGLE_SHEET_ID") or os.environ.get("NEWS_GOOGLE_SHEET_ID") or os.environ.get("SHEET_ID") or "").strip()
    if not target_sheet_id:
        print("\n[Google Sheet] Warning: GOOGLE_SHEET_ID is not configured in .env. Skipping Google Sheet sync.")
        return False

    token_path = os.path.join(WORKSPACE_DIR, "thaipbs-scrapers", "token.json")
    if not os.path.exists(token_path):
        token_path = os.path.join(WORKSPACE_DIR, "token.json")
    if not os.path.exists(token_path):
        token_path = os.path.join(ROOT_DIR, "token.json")
        
    if not os.path.exists(token_path):
        print(f"\n[Google Sheet] Warning: token.json not found. Skipping Google Sheet sync.")
        return False
        
    try:
        import gspread
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_path, "w") as f:
                f.write(creds.to_json())
                
        client = gspread.authorize(creds)
        sheet = client.open_by_key(target_sheet_id)
        ws = sheet.sheet1
        
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
            
        if not rows:
            print("\n[Google Sheet] No rows found to sync.")
            return False
            
        target_sheet_url = GOOGLE_SHEET_URL or f"https://docs.google.com/spreadsheets/d/{target_sheet_id}/edit?usp=sharing"
        print(f"\n[Google Sheet] Syncing {len(rows)-1} articles to '{sheet.title}' ({target_sheet_url})...")
        
        # Ensure sheet dimensions
        current_rows = ws.row_count
        current_cols = ws.col_count
        needed_rows = max(len(rows), 100)
        needed_cols = max(len(rows[0]), 5)
        
        if current_rows < needed_rows or current_cols < needed_cols:
            ws.resize(rows=needed_rows, cols=needed_cols)
            
        ws.clear()
        
        # Batch update in chunks
        chunk_size = 5000
        for i in range(0, len(rows), chunk_size):
            chunk = rows[i:i+chunk_size]
            start_row = i + 1
            end_row = i + len(chunk)
            range_label = f"A{start_row}:E{end_row}"
            ws.update(range_name=range_label, values=chunk)
            
        print(f"[Google Sheet] Successfully synced {len(rows)-1} articles to Google Sheets!")
        return True
    except Exception as e:
        print(f"[Google Sheet] Error syncing to Google Sheet: {e}")
        return False

def merge_csv_outputs(days=None, skip_gsheet=False, sheet_id=None):
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
        "amarintv-scrapers": "Amarin TV",
        "bangkokbiznews-scrapers": "Bangkok Biz News",
        "bangkokpost-scrapers": "Bangkok Post",
        "banmuang-scrapers": "Banmuang",
        "ch7-scrapers": "CH7",
        "chiangmainews-scrapers": "Chiang Mai News",
        "dailynews-scrapers": "Daily News",
        "ejan-scrapers": "EJan",
        "honekrasae-scrapers": "Hone Krasae",
        "kaohoon-scrapers": "Kaohoon",
        "khaosod-scrapers": "Khaosod",
        "khaosodenglish-scrapers": "Khaosod English",
        "komchadluek-scrapers": "Komchadluek",
        "koratdaily-scrapers": "Korat Daily",
        "matichon-scrapers": "Matichon",
        "mcot-scrapers": "MCOT",
        "mgronline-scrapers": "MGR Online",
        "naewna-scrapers": "Naewna",
        "nationthailand-scrapers": "Nation Thailand",
        "nationtv-scrapers": "Nation TV",
        "nbt-scrapers": "NBT",
        "nextnewsth-scrapers": "Next News TH",
        "posttoday-scrapers": "Post Today",
        "pptv-scrapers": "PPTV",
        "prachachat-scrapers": "Prachachat",
        "siamrath-scrapers": "Siamrath",
        "springnews-scrapers": "Spring News",
        "thainews-scrapers": "Thai News",
        "thaipbs-scrapers": "ThaiPBS",
        "thaipbsworld-scrapers": "Thai PBS World",
        "thaipost-scrapers": "ThaiPost",
        "thairath-scrapers": "Thairath",
        "thansettakij-scrapers": "Thansettakij",
        "thestandard-scrapers": "The Standard",
        "tnews-scrapers": "TNews",
        "tnnthailand-scrapers": "TNN Thailand",
        "workpointtoday-scrapers": "Workpoint Today"
    }
    
    # Scan scraper directories for CSV files
    for s_dir in SCRAPER_DIRS:
        dir_path = os.path.join(WORKSPACE_DIR, s_dir)
        if not os.path.isdir(dir_path):
            continue
            
        channel_name = channel_mapping.get(s_dir, "Unknown")
            
        for f in sorted(os.listdir(dir_path)):
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
        
        # Sync to Google Sheets
        if not skip_gsheet:
            sync_to_google_sheet(MASTER_CSV, sheet_id=sheet_id)
            
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

def format_elapsed_time(seconds):
    """Formats elapsed seconds into a readable string (e.g. 1h 23m 45s or 12m 34s)."""
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"

def main():
    start_time = time.time()
    
    parser = argparse.ArgumentParser(description="Master scraper runner.")
    parser.add_argument(
        "-d", "--days",
        type=int,
        default=None,
        help="Number of days to scrape (1 for today only, 2 for today and yesterday, etc., or negative: -1 for yesterday only, -2 yesterday and day before)"
    )
    parser.add_argument(
        "-c", "--concurrency", "--workers",
        type=int,
        default=10,
        help="Number of concurrent scrapers to run in parallel (default: 10, set to 1 for sequential)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Stream real-time scraper stdout logs to console"
    )
    parser.add_argument(
        "-t", "--timeout",
        type=int,
        default=None,
        help="Max time in seconds to allow each scraper before timing out (default: auto-scales with days, min 300s. Set 0 to disable)"
    )
    parser.add_argument(
        "-m", "--merge-only",
        action="store_true",
        help="Only merge the existing CSV files without running any scrapers"
    )
    parser.add_argument(
        "--no-sheet",
        action="store_true",
        help="Skip syncing the merged data to Google Sheets"
    )
    parser.add_argument(
        "--sheet-id",
        type=str,
        default=None,
        help="Target Google Sheet ID to sync to (overrides GOOGLE_SHEET_ID in root .env)"
    )
    args = parser.parse_args()
    days = args.days
    concurrency = max(1, args.concurrency)
    verbose = args.verbose
    merge_only = args.merge_only
    skip_gsheet = args.no_sheet
    sheet_id = args.sheet_id
    
    # Auto-scale timeout based on days if not explicitly specified
    if args.timeout is not None:
        timeout_seconds = args.timeout
    else:
        num_days = abs(days) if days is not None else 1
        timeout_seconds = max(300, num_days * 90)  # e.g. 7 days -> 630s (10.5 mins)
    
    if merge_only:
        merge_csv_outputs(days, skip_gsheet=skip_gsheet, sheet_id=sheet_id)
        elapsed = time.time() - start_time
        print(f"\n=====================================================================")
        print(f"⏱️  Total Run Time: {format_elapsed_time(elapsed)} ({elapsed:.2f} seconds)")
        print(f"=====================================================================")
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
        "amarintv-scrapers": "Amarin TV",
        "bangkokbiznews-scrapers": "Bangkok Biz News",
        "bangkokpost-scrapers": "Bangkok Post",
        "banmuang-scrapers": "Banmuang",
        "ch7-scrapers": "CH7",
        "chiangmainews-scrapers": "Chiang Mai News",
        "dailynews-scrapers": "Daily News",
        "ejan-scrapers": "EJan",
        "honekrasae-scrapers": "Hone Krasae",
        "kaohoon-scrapers": "Kaohoon",
        "khaosod-scrapers": "Khaosod",
        "khaosodenglish-scrapers": "Khaosod English",
        "komchadluek-scrapers": "Komchadluek",
        "koratdaily-scrapers": "Korat Daily",
        "matichon-scrapers": "Matichon",
        "mcot-scrapers": "MCOT",
        "mgronline-scrapers": "MGR Online",
        "naewna-scrapers": "Naewna",
        "nationthailand-scrapers": "Nation Thailand",
        "nationtv-scrapers": "Nation TV",
        "nbt-scrapers": "NBT",
        "nextnewsth-scrapers": "Next News TH",
        "posttoday-scrapers": "Post Today",
        "pptv-scrapers": "PPTV",
        "prachachat-scrapers": "Prachachat",
        "siamrath-scrapers": "Siamrath",
        "springnews-scrapers": "Spring News",
        "thainews-scrapers": "Thai News",
        "thaipbs-scrapers": "ThaiPBS",
        "thaipbsworld-scrapers": "Thai PBS World",
        "thaipost-scrapers": "ThaiPost",
        "thairath-scrapers": "Thairath",
        "thansettakij-scrapers": "Thansettakij",
        "thestandard-scrapers": "The Standard",
        "tnews-scrapers": "TNews",
        "tnnthailand-scrapers": "TNN Thailand",
        "workpointtoday-scrapers": "Workpoint Today"
    }
    
    category_mapping = {
        "society": "สังคม",
        "social": "สังคม",
        "region": "สังคม",
        "politic": "การเมือง",
        "politics": "การเมือง",
        "crime": "อาชญากรรม",
        "criminality": "อาชญากรรม",
        "investigative": "อาชญากรรม",
        "sport": "กีฬา",
        "sports": "กีฬา",
        "economy": "เศรษฐกิจ",
        "economic": "เศรษฐกิจ",
        "economics": "เศรษฐกิจ",
        "domestic-economy": "เศรษฐกิจในประเทศ",
        "foreign-economy": "เศรษฐกิจต่างประเทศ",
        "domestic": "ในประเทศ",
        "foreign": "ต่างประเทศ",
        "abroad": "ต่างประเทศ",
        "world": "ต่างประเทศ",
        "international": "ต่างประเทศ",
        "general": "ทั่วไป",
        "around-thailand": "ทั่วไทย",
        "latest": "ล่าสุด",
        "thaipbs": "ทั้งหมด"
    }
    
    # Prepare scraper metadata list
    scraper_tasks = []
    for s in scrapers:
        s_dir = os.path.basename(os.path.dirname(s))
        s_name = os.path.basename(s)
        
        channel_name = channel_mapping.get(s_dir, s_dir)
        cat_key = s_name.split("-")[0].lower()
        if cat_key == "thaipbs":
            category_name = "ทั้งหมด"
        else:
            category_name = category_mapping.get(cat_key, cat_key)
            
        scraper_tasks.append({
            "path": s,
            "channel": channel_name,
            "category": category_name
        })
        
    # Scale days parameter if negative to ensure the scrapers fetch yesterday's content
    scraper_days = None
    if days is not None:
        if days > 0:
            scraper_days = days
        else:
            scraper_days = abs(days) + 1  # e.g. -1 -> 2, covering today and yesterday
            
    # 2. Run scrapers (concurrent or sequential)
    print(f"\n=====================================================================")
    print(f"🚀 Launching {len(scraper_tasks)} scrapers (Concurrency = {concurrency} workers)")
    print(f"=====================================================================")
    
    results = []
    progress_tracker = {"started": 0, "finished": 0}
    total_tasks = len(scraper_tasks)
    
    if concurrency <= 1:
        # Sequential execution
        for st in scraper_tasks:
            res = run_single_scraper_worker(st, scraper_days, total_tasks, progress_tracker, verbose=verbose, timeout_seconds=timeout_seconds)
            results.append(res)
    else:
        # Concurrent execution with ThreadPoolExecutor
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [
                executor.submit(run_single_scraper_worker, st, scraper_days, total_tasks, progress_tracker, verbose=verbose, timeout_seconds=timeout_seconds)
                for st in scraper_tasks
            ]
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())
                
    # Sort results by channel and category for neat table display
    results.sort(key=lambda r: (r["channel"], r["category"]))
    
    # 3. Print Summary Table
    print_summary_table(results)
    
    # 4. Merge CSV outputs
    merge_csv_outputs(None, skip_gsheet=skip_gsheet, sheet_id=sheet_id)
    
    # 5. Print Execution Time
    elapsed = time.time() - start_time
    print(f"\n=====================================================================")
    print(f"⏱️  Total Run Time: {format_elapsed_time(elapsed)} ({elapsed:.2f} seconds)")
    print(f"=====================================================================")

if __name__ == "__main__":
    main()
