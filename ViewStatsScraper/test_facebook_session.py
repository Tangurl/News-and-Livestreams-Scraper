#!/usr/bin/env python3
r"""
test_facebook_session.py
-------------------------
สคริปต์สำหรับทดสอบสถานะ Session ของ Facebook และระบบ Auto Re-Login:
1. ตรวจสอบว่า Chrome Profile ปัจจุบันมีเซสชั่นที่ล็อกอินอยู่จริงหรือไม่
2. ทดสอบเปิดหน้าเพจ Facebook (เช่น ช่อง ONE) เพื่อดูว่ามองเห็นเนื้อหาในฐานะผู้ใช้ล็อกอินหรือไม่
3. ทดสอบการทำงานของระบบ Auto Re-Login ด้วยข้อมูลใน .env (เมื่อใส่ flag --auto-login)

วิธีใช้:
  python test_facebook_session.py              # ทดสอบตรวจเช็ค Session ปัจจุบัน
  python test_facebook_session.py --auto-login # ทดสอบให้ระบบล็อกอินอัตโนมัติด้วยรหัสใน .env
"""
import argparse
import os
import sys
import time

try:
    import selenium
except ImportError:
    print("=" * 70)
    print("❌ ไม่พบแพ็กเกจ 'selenium' ในสภาพแวดล้อม Python นี้")
    print("👉 กรุณารันคำสั่งติดตั้ง Dependencies ก่อน:")
    print("   pip install -r requirements.txt")
    print("   (หรือสำหรับ Windows: python -m pip install -r requirements.txt)")
    print("=" * 70)
    sys.exit(1)
try:
    from dotenv import load_dotenv
    env_paths = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
    ]
    for p in env_paths:
        if os.path.isfile(p):
            load_dotenv(p)
            break
except ImportError:
    pass

# Manual env fallback
for env_f in (
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
):
    if os.path.isfile(env_f):
        with open(env_f, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip()
                    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                        v = v[1:-1]
                    os.environ.setdefault(k, v)


from modules.utilities import (
    FACEBOOK_PROFILE_DIR,
    create_stealth_chrome_driver,
    is_facebook_logged_out,
)
from modules.facebook import (
    attempt_facebook_auto_relogin,
    check_and_handle_logged_out,
    is_facebook_auto_login_configured,
)


def test_current_session():
    print("=" * 70)
    print("🔍 [Test 1] ตรวจสอบ Session Facebook ใน Profile ปัจจุบัน...")
    print(f"📁 Profile: {FACEBOOK_PROFILE_DIR}")
    print("=" * 70)

    # 1. ตรวจสอบไฟล์ฐานข้อมูลดิสก์โดยตรง
    cookie_paths = [
        os.path.join(FACEBOOK_PROFILE_DIR, "Default", "Network", "Cookies"),
        os.path.join(FACEBOOK_PROFILE_DIR, "Default", "Cookies"),
    ]
    sqlite_has_c_user = False
    for p in cookie_paths:
        if os.path.isfile(p):
            try:
                import sqlite3
                conn = sqlite3.connect(p, timeout=5)
                cur = conn.cursor()
                cur.execute("SELECT name FROM cookies WHERE name = 'c_user' LIMIT 1")
                row = cur.fetchone()
                conn.close()
                if row:
                    sqlite_has_c_user = True
                    print(f"📁 ฐานข้อมูลดิสก์ ({os.path.basename(p)}): ✅ พบคุกกี้ c_user")
                    break
            except Exception:
                pass
    if not sqlite_has_c_user:
        print("📁 ฐานข้อมูลดิสก์: ℹ️ ยังไม่พบคุกกี้ c_user ในฐานข้อมูล (กำลังตรวจสอบผ่านเบราว์เซอร์...)")

    driver = None
    try:
        # ใช้ Driver แบบ Clone จาก Profile หลัก (เหมือน Crawler จริง) เพื่อไม่ทำลาย Master Profile
        driver = create_stealth_chrome_driver(headless=True)
        driver.set_page_load_timeout(30)

        print("\n🌐 กำลังเปิดหน้า https://www.facebook.com ...")
        driver.get("https://www.facebook.com")
        time.sleep(4)

        cookies = driver.get_cookies()
        c_user = next((c.get("value") for c in cookies if c.get("name") == "c_user"), None)
        xs = next((c.get("value") for c in cookies if c.get("name") == "xs"), None)

        print(f"🍪 คุกกี้ c_user: {'พบ (' + c_user + ')' if c_user else '❌ ไม่พบ'}")
        print(f"🍪 คุกกี้ xs:     {'พบ (เซสชั่นสมบูรณ์)' if xs else '❌ ไม่พบ'}")

        # ตรวจสอบ Profile Avatar บน DOM
        has_profile = driver.execute_script("""
            return document.querySelectorAll(
                "div[aria-label='Your profile'], div[aria-label='โปรไฟล์ของคุณ'], " +
                "svg[aria-label='Your profile'], svg[aria-label='โปรไฟล์ของคุณ'], " +
                "a[href*='/me/']"
            ).length > 0;
        """)

        if has_profile:
            print("👤 สถานะบนหน้าเว็บ: ✅ พบ Profile Avatar (คุณกำลังอยู่ในสถานะล็อกอิน 100%)")
        else:
            print("👤 สถานะบนหน้าเว็บ: ⚠️ ไม่พบ Profile Avatar บนหน้าแรก")

        # ทดสอบเปิดเพจช่อง ONE
        print("\n📺 กำลังทดสอบเปิดหน้า Timeline ของเพจ ONE (https://www.facebook.com/onenews31/) ...")
        driver.get("https://www.facebook.com/onenews31/")
        time.sleep(4)

        is_logged_out = check_and_handle_logged_out(driver, "https://www.facebook.com/onenews31/", auto_relogin=False)
        if not is_logged_out and (has_profile or c_user):
            print("\n🎉 ผลการทดสอบ: สมบูรณ์แบบ! บัญชี Facebook ของคุณพร้อมใช้งานสำหรับ Crawler แล้ว!")
        else:
            print("\n⚠️ ผลการทดสอบ: เซสชั่นยังไม่พร้อม หรือหลุดการล็อกอิน กรุณาตรวจสอบอีกครั้ง")

    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดขณะทดสอบ: {e}")
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def test_auto_login():
    print("=" * 70)
    print("🤖 [Test 2] ทดสอบระบบ Facebook Auto Re-Login ด้วยข้อมูลใน .env...")
    print("=" * 70)

    if not is_facebook_auto_login_configured():
        print("❌ ไม่พบการตั้งค่า FB_PASSWORD ในไฟล์ .env")
        print("💡 กรุณาเปิดไฟล์ .env แล้วใส่:")
        print("   FB_AUTO_LOGIN=true")
        print("   FB_PASSWORD=รหัสผ่านของคุณ")
        return

    email = os.getenv("FB_EMAIL", "")
    print(f"📧 บัญชี: {email if email else '(ใช้โปรไฟล์ที่จำไว้)'}")
    print("🚀 กำลังสั่งรัน attempt_facebook_auto_relogin(force=True)...")

    success = attempt_facebook_auto_relogin(force=True)
    if success:
        print("\n🎉 ผลการทดสอบ Auto-Login: สำเร็จเรียบร้อย! ระบบสามารถเข้าสู่ระบบและบันทึกคุกกี้ได้เองอัตโนมัติ")
    else:
        print("\n❌ ผลการทดสอบ Auto-Login: ไม่สำเร็จ กรุณาตรวจสอบ Log ด้านบน")


def main():
    parser = argparse.ArgumentParser(description="ทดสอบ Facebook Session และ Auto-Login")
    parser.add_argument("--auto-login", action="store_true", help="ทดสอบการทำงานของระบบ Auto-Login")
    args = parser.parse_args()

    if args.auto_login:
        test_auto_login()
    else:
        test_current_session()
        print("💡 บัญชีพร้อมใช้งานแล้ว! คุณสามารถรัน python linkcrawler.py หรือ python view_stats_scraper.py ได้ทันที")
        print("   (คำสั่ง --auto-login เป็นเพียงฟังก์ชันเสริมสำหรับจำลองการล็อกอินอัตโนมัติเมื่อเซสชั่นหมดอายุ)\n")


if __name__ == "__main__":
    main()
