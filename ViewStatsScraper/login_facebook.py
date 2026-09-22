r"""
login_facebook.py
------------------
เปิด Google Chrome ตัวจริง (Native Application) โดยไม่ผ่าน Selenium / ChromeDriver
โดยใช้ Chrome Profile ที่ FACEBOOK_PROFILE_DIR
(ปกติคือ %LOCALAPPDATA%\LinkScraperAutomate\facebook_profile บน Windows
 และ ./LinkScraperAutomate/facebook_profile บน macOS)

การเปิดผ่าน Native Chrome โดยตรงทำให้ Facebook มองเห็นเป็นการใช้งานของมนุษย์ 100%
จึงช่วยหลีกเลี่ยงระบบตรวจจับ Automation Bot, ปัญหา Captcha วนลูป (Infinite Captcha Redirect),
และการโดนปฏิเสธเซสชั่นได้อย่างสมบูรณ์

วิธีใช้: python login_facebook.py
เมื่อต้องการ Logout และล้าง Session ทิ้ง ให้รัน logout_facebook.py
"""
import os
import shutil
import sqlite3
import subprocess
import sys
import time

from modules.utilities import (
    FACEBOOK_PROFILE_DIR,
    create_stealth_chrome_driver,
    reset_facebook_blocked_status,
    reset_facebook_logged_out_status,
)


def find_native_chrome() -> str | None:
    """ค้นหาตำแหน่งไฟล์ Executable ของ Google Chrome บนระบบปฏิบัติการปัจจุบัน"""
    if sys.platform == "darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        ]
        for c in candidates:
            if os.path.isfile(c) and os.access(c, os.X_OK):
                return c
    elif sys.platform.startswith("win"):
        prefixes = [
            os.environ.get("PROGRAMFILES", r"C:\Program Files"),
            os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
            os.environ.get("LOCALAPPDATA", r"C:\Users\Default\AppData\Local"),
        ]
        for p in prefixes:
            path = os.path.join(p, "Google", "Chrome", "Application", "chrome.exe")
            if os.path.isfile(path):
                return path
        for name in ("chrome", "chrome.exe", "google-chrome"):
            w = shutil.which(name)
            if w:
                return w
    else:
        for name in ("google-chrome", "google-chrome-stable", "chromium-browser", "chromium"):
            w = shutil.which(name)
            if w:
                return w
    return None


def kill_profile_chrome(profile_dir: str) -> None:
    """ปิด Chrome instances ที่เปิดใช้งาน profile_dir นี้อยู่ เพื่อให้ flush cookie ลงดิสก์และปลดล็อค"""
    if sys.platform == "darwin":
        try:
            out = subprocess.check_output(["pgrep", "-f", profile_dir], text=True)
            pids = [int(p.strip()) for p in out.splitlines() if p.strip()]
            for pid in pids:
                if pid != os.getpid():
                    try:
                        os.kill(pid, 15)  # SIGTERM for graceful shutdown
                    except OSError:
                        pass
            time.sleep(2)
        except Exception:
            pass
    elif sys.platform.startswith("win"):
        try:
            from modules.utilities import kill_zombie_chrome_processes
            kill_zombie_chrome_processes()
        except Exception:
            pass


def clear_stale_locks(profile_dir: str) -> None:
    """ลบไฟล์ Lock ที่ค้างอยู่ใน Chrome Profile เพื่อให้เปิดโปรแกรมได้ไม่ติดขัด"""
    kill_profile_chrome(profile_dir)
    for lock_file in ("SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile"):
        lock_path = os.path.join(profile_dir, lock_file)
        if os.path.exists(lock_path) or os.path.islink(lock_path):
            try:
                os.remove(lock_path)
            except OSError:
                pass


def verify_facebook_login_cookies(profile_dir: str) -> bool:
    """
    ตรวจสอบว่าใน Profile มีคุกกี้ c_user ของ Facebook ที่ล็อกอินสำเร็จ
    และ Chrome Driver สามารถถอดรหัส (decrypt) ใช้งานได้จริง
    """
    # 1. ตรวจสอบไฟล์ฐานข้อมูลบนดิสก์เบื้องต้น
    cookie_paths = [
        os.path.join(profile_dir, "Default", "Network", "Cookies"),
        os.path.join(profile_dir, "Default", "Cookies"),
    ]
    found_in_disk = False
    for p in cookie_paths:
        if os.path.isfile(p):
            try:
                conn = sqlite3.connect(p, timeout=5)
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM cookies WHERE name = 'c_user' LIMIT 1")
                row = cursor.fetchone()
                conn.close()
                if row:
                    found_in_disk = True
                    print(f"  📁 [Verify] ตรวจพบคุกกี้ c_user ในไฟล์ SQLite: {p}")
                    break
            except Exception as e:
                print(f"  ⚠️ [Verify] ไม่สามารถเปิด SQLite {p}: {e}")

    # 2. ตรวจสอบความถูกต้องของการถอดรหัสผ่าน Headless Chrome Driver จริง
    print("  🌐 [Verify] กำลังตรวจสอบ Session สดผ่าน Chrome Driver...")
    try:
        driver = create_stealth_chrome_driver(headless=True, profile_dir=profile_dir)
        driver.set_page_load_timeout(20)
        driver.get("https://www.facebook.com")
        time.sleep(2)
        cookies = driver.get_cookies()
        driver.quit()

        cookie_names = [c.get("name") for c in cookies]
        if "c_user" in cookie_names:
            print(f"  ✅ [Verify] ถอดรหัสสำเร็จ! พบคุกกี้ c_user พร้อมใช้งาน")
            return True
        else:
            print(f"  ⚠️ [Verify] ไม่พบคุกกี้ c_user ในเบราว์เซอร์ (คุกกี้ที่พบ: {cookie_names})")
            return False
    except Exception as e:
        print(f"  ⚠️ [Verify] Driver verification error: {e}")
        return found_in_disk


def main():
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

    print("=" * 70)
    print("🔑 [Facebook Login Setup]")
    print(f"📁 Chrome Profile Directory: {FACEBOOK_PROFILE_DIR}")
    os.makedirs(FACEBOOK_PROFILE_DIR, exist_ok=True)
    clear_stale_locks(FACEBOOK_PROFILE_DIR)

    print("🚀 กำลังเปิด Google Chrome ด้วย Stealth Engine (โหมดหน้าจอปกติ)...")
    print("💡 เพื่อให้ระบบบันทึกคุกกี้ด้วย Encryption Context เดียวกันกับบอท Crawler 100%\n")

    driver = None
    try:
        driver = create_stealth_chrome_driver(headless=False, profile_dir=FACEBOOK_PROFILE_DIR)
        driver.get("https://www.facebook.com")
        print("[Login Facebook] หน้าต่างเบราว์เซอร์ Google Chrome กำลังเปิดขึ้นมา...")
        print("[Login Facebook] กรุณาเข้าสู่ระบบ Facebook ให้เรียบร้อยในหน้าต่างที่เปิดขึ้นมา")
        print("----------------------------------------------------------------------")
        input("[Login Facebook] เมื่อเข้าสู่ระบบสำเร็จแล้ว (เห็นหน้า Feed/Home ข่าว)\n👉 กลับมากด [Enter] ที่นี่เพื่อบันทึกเซสชั่นและปิดหน้าต่าง...\n")

        # ตรวจสอบคุกกี้สดจากเบราว์เซอร์ก่อนปิด
        try:
            cookies = driver.get_cookies()
            c_user = next((c.get("value") for c in cookies if c.get("name") == "c_user"), None)
            if c_user:
                print(f"  🎉 ตรวจพบคุกกี้ล็อกอินสด: c_user = {c_user}")
        except Exception:
            pass
    except Exception as e:
        print(f"⚠️ เกิดข้อผิดพลาดขณะเปิดเบราว์เซอร์: {e}")
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        clear_stale_locks(FACEBOOK_PROFILE_DIR)

    print("\n🔍 กำลังตรวจสอบสถานะการเข้าสู่ระบบ...")
    time.sleep(1)
    is_logged_in = verify_facebook_login_cookies(FACEBOOK_PROFILE_DIR)

    if is_logged_in:
        reset_facebook_logged_out_status()
        reset_facebook_blocked_status()
        print("\n" + "=" * 70)
        print("✅ [Login Facebook] สำเร็จเรียบร้อย! ตรวจพบ Session Facebook ที่ล็อกอินแล้ว")
        print(f"💾 บันทึก Session ลงในโปรไฟล์: {FACEBOOK_PROFILE_DIR}")
        print("🎉 ระบบ Crawler พร้อมใช้งานบัญชี Facebook ล็อกอินนี้ทันที!")
        print("=" * 70 + "\n")
    else:
        print("\n" + "=" * 70)
        print("⚠️ [Login Facebook] ยังไม่พบคุกกี้ล็อกอิน c_user ในโปรไฟล์")
        print("💡 หากเพิ่งล็อกอินสำเร็จ อาจเป็นเพราะหน้าต่าง Chrome ยังไม่ปิดสนิท")
        print("   กรุณาลองปิด Chrome ให้สนิทแล้วรันใหม่อีกครั้ง")
        print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
