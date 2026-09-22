#!/usr/bin/env python3
"""
Quick connection tester for Google Apps Script Web App.
"""

import os
import sys
from view_stats_scraper import load_env_fallback
from modules.sheets_writer import _http_get_json, _http_post_json

load_env_fallback()

def main():
    url = os.getenv("POST_SCRIPT_API")
    print("=" * 70)
    print("🔍 Testing Google Apps Script Connection...")
    print(f"URL: {url}")
    print("=" * 70)

    if not url:
        print("❌ Error: POST_SCRIPT_API is not set in .env")
        sys.exit(1)

    # Test 1: GET (Channel discovery)
    print("\n1️⃣  Testing HTTP GET (doGet)...")
    try:
        res = _http_get_json(url)
        sheets = res.get("sheets", [])
        total = res.get("total_count", 0)
        print("✅ HTTP GET Successful!")
        print(f"   • Total Channels/Sheets detected : {len(sheets)}")
        print(f"   • Total Program Rows detected    : {total}")
        print(f"   • Channel Tabs: {sheets[:8]} ...")
    except Exception as e:
        print(f"❌ HTTP GET failed: {e}")
        if "403" in str(e):
            print("\n💡 [403 Forbidden]: ใน Apps Script ตอน Deploy ต้องตั้ง 'Who has access' (ใครมีสิทธิ์เข้าถึง) เป็น 'Anyone' (ทุกคน)")
        return

    # Test 2: POST (get_all action)
    print("\n2️⃣  Testing HTTP POST (doPost with action: 'get_all')...")
    try:
        res = _http_post_json(url, {"action": "get_all"})
        if res.get("ok"):
            print("✅ HTTP POST Successful!")
            print(f"   • Response: {res.get('action')} ok (Total: {res.get('total_count', 0)} programs)")
        else:
            print(f"⚠️ HTTP POST returned status error: {res}")
    except Exception as e:
        print(f"❌ HTTP POST failed: {e}")
        return

    print("\n🎉 Google Apps Script is fully operational and ready!")

if __name__ == "__main__":
    main()
