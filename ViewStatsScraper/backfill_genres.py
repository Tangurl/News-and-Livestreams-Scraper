#!/usr/bin/env python3
"""
One-Time Genre Backfill Script for Google Sheet 'View Stats'.
============================================================
1. Fetches all existing rows in the 'View Stats' sheet.
2. Identifies rows with empty or missing 'หมวดหมู่' (Column D).
3. Classifies each program title using scikit-learn model in genre_classify.
4. Updates Column D (หมวดหมู่) on Google Sheets using 'set_range' (or batch upsert).
"""

import os
import sys
import warnings
from typing import Dict, List, Tuple
from dotenv import load_dotenv

# Filter scikit-learn pickle version warnings
warnings.filterwarnings("ignore")

# Load environment
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(env_path)

# Import classifier
here = os.path.dirname(os.path.abspath(__file__))
genre_test_dir = os.path.join(here, "genre_classify", "genre_predict_test")
if genre_test_dir not in sys.path:
    sys.path.insert(0, genre_test_dir)

try:
    from genre_predict import genre_predict
except ImportError as e:
    print(f"❌ Error importing genre_predict: {e}")
    sys.exit(1)

from modules.sheets_writer import _http_post_json


def fetch_all_view_stats_rows(api_url: str) -> List[List]:
    """Reads all rows from 'View Stats' sheet (range A1:Q500)."""
    res = _http_post_json(api_url, {"action": "get", "sheet": "View Stats", "range": "A1:Q500"})
    if not res.get("ok"):
        raise RuntimeError(f"Apps Script error: {res.get('error') or res}")
    values = res.get("result", {}).get("values", [])
    return values


def main():
    api_url = os.getenv("POST_SCRIPT_API")
    if not api_url:
        print("❌ Error: POST_SCRIPT_API not set in .env")
        sys.exit(1)

    print("=" * 80)
    print("🏷️  VIEW STATS - GENRE BACKFILL CLASSIFIER")
    print("=" * 80)
    print(f"📡 Connecting to Google Sheet via: {api_url[:60]}...")

    raw_rows = fetch_all_view_stats_rows(api_url)
    print(f"📋 Fetched {len(raw_rows)} total rows from 'View Stats'.")

    # Filter data rows (Row 1 is header, Row 2 is sub-header, data starts at row 3 = index 2)
    # Col A (0): Date, Col B (1): Channel, Col C (2): Title, Col D (3): Genre
    classified_items = []
    all_d_values = [] # For batch write to D3:D{last}

    last_data_idx = -1
    for i in range(2, len(raw_rows)):
        row = raw_rows[i]
        row_num = i + 1
        date_val = str(row[0]).strip() if len(row) > 0 else ""
        ch_val = str(row[1]).strip() if len(row) > 1 else ""
        title_val = str(row[2]).strip() if len(row) > 2 else ""
        genre_val = str(row[3]).strip() if len(row) > 3 else ""

        if not title_val or not date_val:
            continue

        last_data_idx = i

    if last_data_idx < 2:
        print("ℹ️ No data rows found in 'View Stats'. Nothing to backfill.")
        return

    data_rows_count = last_data_idx - 1  # Rows from index 2 to last_data_idx
    print(f"🔍 Found {data_rows_count} active broadcast rows (Row 3 to Row {last_data_idx + 1}).\n")

    backfill_count = 0
    already_filled = 0

    for i in range(2, last_data_idx + 1):
        row = raw_rows[i]
        row_num = i + 1
        title_val = str(row[2]).strip() if len(row) > 2 else ""
        ch_val = str(row[1]).strip() if len(row) > 1 else ""
        genre_val = str(row[3]).strip() if len(row) > 3 else ""

        if not genre_val or genre_val == "-":
            pred = str(genre_predict(title_val)).strip()
            classified_items.append((row_num, ch_val, title_val, pred))
            all_d_values.append([pred])
            backfill_count += 1
        else:
            all_d_values.append([genre_val])
            already_filled += 1

    print(f"📊 Summary of Genre Status:")
    print(f"   • Rows already categorized : {already_filled}")
    print(f"   • Rows to be backfilled    : {backfill_count}\n")

    if backfill_count == 0:
        print("✅ All rows in 'View Stats' already have a genre assigned. No backfill needed!")
        return

    print("🔍 Sample classified rows:")
    for row_num, ch, title, genre in classified_items[:10]:
        print(f"   Row {row_num:<4} [{ch:<12}] '{title:<28}' -> {genre}")
    if len(classified_items) > 10:
        print(f"   ... and {len(classified_items) - 10} more rows.")

    target_range = f"D3:D{2 + len(all_d_values)}"
    print(f"\n📝 Writing {len(all_d_values)} genre values back to 'View Stats'!{target_range}...")

    # Attempt set_range
    payload = {
        "action": "set_range",
        "sheet": "View Stats",
        "range": target_range,
        "values": all_d_values
    }

    res = _http_post_json(api_url, payload)
    if res.get("ok"):
        print(f"\n🎉 Successfully updated all {backfill_count} empty genre rows in Google Sheets!")
    else:
        err = res.get("error", "")
        if "unknown action" in err.lower():
            print("\n⚠️ Note: Apps Script returned 'unknown action: set_range'.")
            print("👉 Please deploy the updated App.gs to Google Apps Script first:")
            print("   1. Open Google Sheet -> Extensions -> Apps Script")
            print("   2. Paste the updated code from 'apps_script/App.gs'")
            print("   3. Click Deploy -> Manage deployments -> Edit -> Version: New version -> Deploy")
            print("   4. Re-run this script: python3 backfill_genres.py")
        else:
            print(f"❌ Failed to write genres: {res}")


if __name__ == "__main__":
    main()
