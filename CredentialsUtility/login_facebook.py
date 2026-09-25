"""
login_facebook.py
------------------
เปิด Chrome แบบเห็นหน้าจอ (ไม่ headless) โดยใช้ Chrome Profile ที่ FACEBOOK_PROFILE_DIR
(modules/utilities.py, ปกติคือ %LOCALAPPDATA%\\LinkScraperAutomate\\facebook_profile บน Windows)
ให้ผู้ใช้ Login เข้าบัญชี Facebook ด้วยตนเอง เมื่อ Login สำเร็จแล้ว Chrome จะบันทึก Session/Cookies
ลงในโปรไฟล์นี้อัตโนมัติ ทำให้ linkcrawler.py (ผ่าน modules/facebook.py) เห็น Live Video ที่ต้อง
Login บัญชี Facebook ก่อนถึงจะดูได้

หาก Facebook เด้ง Logout ระหว่าง crawler ทำงาน ระบบจะ Login ใหม่ให้อัตโนมัติด้วย FB_EMAIL /
FB_PASSWORD ใน .env ที่ root (ดู attempt_facebook_auto_relogin() ใน modules/facebook.py)

วิธีใช้: python login_facebook.py (หรือดับเบิลคลิก Login.bat ที่ root)
เมื่อต้องการ Logout และล้าง Session ทิ้ง ให้รัน logout_facebook.py
"""
import os
import sys

# modules/ อยู่ใน ViewStatsScraper/ จึงต้องเพิ่มเข้า sys.path ก่อน import
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ViewStatsScraper"))

from modules.utilities import FACEBOOK_PROFILE_DIR, create_stealth_chrome_driver, manual_login_lock


def main():
    print("=" * 70)
    print(f"[Login Facebook] กำลังเปิด Chrome โดยใช้ Profile ที่: {FACEBOOK_PROFILE_DIR}")

    # Lock บอก crawler ว่ากำลัง Login อยู่ จะได้ไม่เปิด Auto Re-Login ด้วย Profile เดียวกันมาชน
    with manual_login_lock():
        driver = create_stealth_chrome_driver(headless=False, profile_dir=FACEBOOK_PROFILE_DIR)

        try:
            driver.get("https://www.facebook.com/login")
            print("[Login Facebook] กรุณา Login เข้าบัญชี Facebook ในหน้าต่าง Chrome ที่เปิดขึ้นมา")
            input("[Login Facebook] เมื่อ Login สำเร็จแล้ว (เห็นหน้า Feed/Home) ให้กลับมากด Enter ที่นี่...\n")

            cookies = driver.get_cookies()
            logged_in = any(c.get("name") == "c_user" for c in cookies)
            if logged_in:
                print("[Login Facebook] ✅ ตรวจพบ Session ที่ Login สำเร็จแล้ว")
            else:
                print("[Login Facebook] ⚠️ ยังไม่พบ Session ที่ Login (อาจ Login ไม่สำเร็จ) กรุณาลองรันใหม่อีกครั้ง")
        finally:
            driver.quit()
            print(f"[Login Facebook] ปิด Chrome แล้ว Session ถูกบันทึกไว้ที่: {FACEBOOK_PROFILE_DIR}")
            print("=" * 70)


if __name__ == "__main__":
    main()
