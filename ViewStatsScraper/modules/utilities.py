import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from typing import Optional, Tuple

try:
    from selenium import webdriver
    from selenium.common.exceptions import WebDriverException
    from selenium.webdriver.chrome.options import Options
except ImportError:
    webdriver = None
    WebDriverException = Exception
    Options = None

# รองรับการแสดงผลภาษาไทยบน Windows Terminal ที่ default console codepage ไม่ใช่ UTF-8 (เช่น
# cp1252/cp874 บางเครื่อง) หากไม่ทำ ทุก print() ที่มีข้อความไทยปนอยู่ในไฟล์นี้และไฟล์ที่ import
# โมดูลนี้ (facebook.py, youtube.py, x.py, login_facebook.py, logout_facebook.py) จะพังด้วย
# UnicodeEncodeError ทันทีที่ error จริงเกิดขึ้น กลบข้อความ error ตัวจริงจนไม่เหลือร่องรอยให้ดู
# (linkcrawler.py มี guard เดียวกันนี้อยู่แล้ว แต่ทำซ้ำที่นี่เพื่อให้ครอบคลุมทุก Entry Point)
for _stream in (sys.stdout, sys.stderr):
    if getattr(_stream, "encoding", None) != "utf-8":
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

# ไดเรกทอรีเก็บ Chrome User Profile ที่ล็อกอิน Facebook ค้างไว้ (สร้าง/ล้างข้อมูลผ่าน
# login_facebook.py / logout_facebook.py) ใช้ร่วมกันทุกโมดูลที่เรียก
# create_stealth_chrome_driver() (facebook.py, x.py, youtube.py) เพื่อให้เห็นวิดีโอ Live ที่
# ต้องล็อกอินบัญชี Facebook ก่อนถึงจะดูได้
#
# ตั้งใจเก็บไว้นอกโฟลเดอร์โปรเจกต์ (เช่น %LOCALAPPDATA%\LinkScraperAutomate บน Windows) แทนที่จะ
# เก็บไว้ใต้ตัวโปรเจกต์เอง เพราะโปรเจกต์นี้มักถูก clone ไว้ใต้ Desktop\...\WB-07-LinkScraperAutomate
# ซึ่ง path ยาวอยู่แล้ว โดยเฉพาะเครื่องที่ Desktop ถูก OneDrive sync ไว้ (เติม
# "OneDrive - ชื่อบริษัท\Desktop\" นำหน้า) ทำให้ path เต็มของไฟล์ลึกๆที่ Chrome สร้างขึ้นเอง เช่น
# Default\Service Worker\CacheStorage\<hash>\... ทะลุขีดจำกัด Windows MAX_PATH (260 ตัวอักษร)
# แล้วเปิด Chrome ไม่ขึ้นด้วย error "session not created: from unknown error: failed to write
# prefs file" (พังเฉพาะบางเครื่องที่ path ยาวเกิน แม้โค้ดจะเหมือนกันทุกเครื่องก็ตาม)
# Always resolve PROJECT_ROOT to the repository root directory
_file_dir = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(os.path.dirname(_file_dir)) == "ViewStatsScraper":
    PROJECT_ROOT = os.path.dirname(os.path.dirname(_file_dir))
else:
    PROJECT_ROOT = os.path.dirname(_file_dir)

CHROME_DATA_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or PROJECT_ROOT,
    "LinkScraperAutomate",
)
FACEBOOK_PROFILE_DIR = os.path.join(CHROME_DATA_DIR, "facebook_profile")

# ไฟล์ Lock ที่ Chrome สร้างไว้ระหว่างใช้ Profile นี้อยู่ (กลไกนี้เป็นของ Linux/Mac เท่านั้น
# Windows ไม่สร้างไฟล์เหล่านี้ แต่ยังคงลบทิ้งไว้เผื่อรันข้าม OS) หาก Chrome ปิดไม่สนิท (ปิดหน้าต่าง
# เอง แทนกด Enter ให้ driver.quit() ทำงาน, เครื่องแฮงค์/ไฟดับ) ไฟล์เหล่านี้จะค้างอยู่ และทำให้เปิด
# Chrome ครั้งถัดไปด้วย user-data-dir เดียวกันไม่ขึ้น (session not created: user data directory
# is already in use) จึงต้องล้างทิ้งก่อนเปิด driver ทุกครั้ง
PROFILE_LOCK_FILES = ("SingletonLock", "SingletonCookie", "SingletonSocket")

# สถานะตรวจจับ Action Block ของบัญชี Facebook ในรอบปัจจุบัน
# เมื่อมี worker ใดตรวจพบว่าติดบล็อก จะตั้งเป็น True เพื่อให้ worker/channel อื่นๆ ในรอบเดียวกัน
# สลับไปใช้ Clean Session (เหมือน Incognito) ทันที เพื่อพักบัญชีและเพิ่มความเร็ว
_FACEBOOK_BLOCKED_THIS_ROUND = False
_FACEBOOK_LOGGED_OUT_STATUS = False


def is_facebook_blocked_this_round() -> bool:
    """ตรวจสอบว่ารอบปัจจุบันตรวจพบว่าบัญชี Facebook ติด Action Block หรือไม่"""
    global _FACEBOOK_BLOCKED_THIS_ROUND
    return _FACEBOOK_BLOCKED_THIS_ROUND


def set_facebook_blocked_this_round(blocked: bool = True) -> None:
    """ตั้งค่าสถานะ Action Block สำหรับรอบปัจจุบัน"""
    global _FACEBOOK_BLOCKED_THIS_ROUND
    _FACEBOOK_BLOCKED_THIS_ROUND = blocked


def reset_facebook_blocked_status() -> None:
    """รีเซ็ตสถานะ Action Block เมื่อเริ่มรอบตรวจสอบใหม่ (เพื่อให้ลองใช้บัญชีอีกครั้งในรอบถัดไป)"""
    global _FACEBOOK_BLOCKED_THIS_ROUND
    _FACEBOOK_BLOCKED_THIS_ROUND = False


def is_facebook_logged_out() -> bool:
    """ตรวจสอบว่าตรวจพบบัญชี Facebook หลุดการล็อกอิน (Session Expired / Need Re-login) หรือไม่"""
    global _FACEBOOK_LOGGED_OUT_STATUS
    return _FACEBOOK_LOGGED_OUT_STATUS


def set_facebook_logged_out(logged_out: bool = True) -> None:
    """ตั้งค่าสถานะว่าบัญชี Facebook หลุดการล็อกอิน"""
    global _FACEBOOK_LOGGED_OUT_STATUS
    _FACEBOOK_LOGGED_OUT_STATUS = logged_out


def reset_facebook_logged_out_status() -> None:
    """รีเซ็ตสถานะการหลุดล็อกอิน (เช่น เมื่อผู้ใช้ล็อกอินใหม่แล้ว)"""
    global _FACEBOOK_LOGGED_OUT_STATUS
    _FACEBOOK_LOGGED_OUT_STATUS = False

# ตารางแปลงชื่อเดือนภาษาไทย (แบบย่อและเต็ม) เป็นตัวเลข (1-12)
# ใช้ร่วมกันระหว่าง facebook.py, youtube.py และ x.py
THAI_MONTH_TO_INT = {
    "ม.ค.": 1, "ม.ค": 1, "มกราคม": 1,
    "ก.พ.": 2, "ก.พ": 2, "กุมภาพันธ์": 2,
    "มี.ค.": 3, "มี.ค": 3, "มีนาคม": 3,
    "เม.ย.": 4, "เม.ย": 4, "เมษายน": 4,
    "พ.ค.": 5, "พ.ค": 5, "พฤษภาคม": 5,
    "มิ.ย.": 6, "มิ.ย": 6, "มิถุนายน": 6,
    "ก.ค.": 7, "ก.ค": 7, "กรกฎาคม": 7,
    "ส.ค.": 8, "ส.ค": 8, "สิงหาคม": 8,
    "ก.ย.": 9, "ก.ย": 9, "กันยายน": 9,
    "ต.ค.": 10, "ต.ค": 10, "ตุลาคม": 10,
    "พ.ย.": 11, "พ.ย": 11, "พฤศจิกายน": 11,
    "ธ.ค.": 12, "ธ.ค": 12, "ธันวาคม": 12,
}

# Regex สำหรับจับชื่อเดือนภาษาไทยทั้งแบบเต็มและแบบย่อ (เช่น 'กันยายน', 'สิงหาคม', 'ส.ค.', 'ก.ย.')
THAI_FULL_MONTHS_REGEX = (
    r"มกราคม|กุมภาพันธ์|มีนาคม|เมษายน|พฤษภาคม|มิถุนายน|"
    r"กรกฎาคม|สิงหาคม|กันยายน|ตุลาคม|พฤศจิกายน|ธันวาคม"
)
THAI_SHORT_MONTHS_REGEX = (
    r"ม\.ค\.?|ก\.พ\.?|มี\.ค\.?|เม\.ย\.?|พ\.ค\.?|มิ\.ย\.?|"
    r"ก\.ค\.?|ส\.ค\.?|ก\.ย\.?|ต\.ค\.?|พ\.ย\.?|ธ\.ค\.?"
)
THAI_MONTH_REGEX = rf"(?:{THAI_FULL_MONTHS_REGEX}|{THAI_SHORT_MONTHS_REGEX})"


def parse_thai_date_match(match: Optional[re.Match], normalize_short_year: bool = False) -> Optional[Tuple[int, int, Optional[int]]]:
    """
    แปลงผลลัพธ์จาก re.search (ที่ match ด้วย pattern รูปแบบ 'วัน เดือน ปี') ให้เป็น (day, month, year)
    - normalize_short_year: หากปีที่ดึงได้เป็น พ.ศ. เต็ม (เช่น 2569) ให้ตัดเหลือ 2 หลักท้าย (69)
    คืนค่า None หากไม่มี match หรือเดือน/วันไม่ถูกต้อง
    """
    if not match:
        return None

    day = int(match.group(1))
    month_str = match.group(2).strip()
    year_str = match.group(3)

    month = THAI_MONTH_TO_INT.get(month_str, 0)
    year = None
    if year_str:
        year = int(year_str)
        if normalize_short_year and year > 2500:
            year = year % 100

    if month > 0 and 1 <= day <= 31:
        return (day, month, year)

    return None


def gregorian_year_to_be_short(year: int) -> int:
    """
    แปลงปี ค.ศ. (Gregorian) เป็นปี พ.ศ. แบบ 2 หลักท้าย เช่น 2026 -> 69
    ใช้เทียบกับปีที่ดึงได้จาก Title บนหน้าเว็บ (ซึ่งมักแสดงเป็น พ.ศ. แบบย่อ)
    """
    return (year + 543) % 100


def normalize_title_text(text: str) -> str:
    """
    ปรับรูปแบบข้อความให้อยู่ในรูปมาตรฐานสำหรับจับคู่ (ตัด space, hashtag, วงเล็บ)
    เช่น:
    - 'วันใหม่  ไทยพีบีเอส' -> 'วันใหม่ไทยพีบีเอส'
    - '#วันใหม่ไทยพีบีเอส'  -> 'วันใหม่ไทยพีบีเอส'
    """
    if not text:
        return ""
    t = text.strip()
    t = re.sub(r"\(.*?\)", "", t)
    t = t.replace("็", "๊")
    t = re.sub(r"[#\s\.\-:_’'\"!]", "", t)
    return t.lower()


def is_thaipbs_channel(name: Optional[str]) -> bool:
    """
    ตรวจสอบว่าชื่อช่อง หรือชื่อรายการเป็นของ Thai PBS หรือไม่
    """
    if not name:
        return False
    norm = str(name).strip().lower().replace(" ", "").replace("-", "").replace("_", "")
    return (
        norm in ("thaipbs", "ไทยพีบีเอส", "ช่องหมายเลข3", "ช่อง3ไทยพีบีเอส")
        or "thaipbs" in norm
        or "ไทยพีบีเอส" in norm
    )


def _kill_orphaned_chrome_processes_windows() -> None:
    """
    Windows ไม่ใช้ไฟล์ Lock แบบ Linux/Mac (SingletonLock ฯลฯ) แต่ล็อก Profile ด้วย process ที่ยัง
    เปิดค้างอยู่จริงแทน (เช่น Chrome จากรอบก่อนที่ driver.quit() ไม่ทันทำงาน, Python ถูกปิดกลางคัน)
    จึงต้องค้นหา chrome.exe/chromedriver.exe ที่ Command Line อ้างอิงถึง FACEBOOK_PROFILE_DIR
    นี้โดยเฉพาะ (ไม่แตะ Chrome browser ปกติของผู้ใช้ที่เปิดอยู่) แล้วปิดทิ้งก่อนเปิด driver ใหม่
    เป็น Best Effort ล้วนๆ หากค้นหา/ปิดไม่สำเร็จ (เช่น powershell ใช้งานไม่ได้) จะข้ามไปเงียบๆ
    """
    ps_script = (
        "$ErrorActionPreference = 'SilentlyContinue'; "
        "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe' OR Name='chromedriver.exe'\" | "
        f"Where-Object {{ $_.CommandLine -like '*{FACEBOOK_PROFILE_DIR}*' }} | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            timeout=15,
        )
    except Exception:
        pass


def _clear_stale_profile_locks() -> None:
    """
    ล้างสถานะ Chrome Profile ที่อาจค้างจากการปิด Chrome ไม่สนิทในรอบก่อนหน้า ป้องกัน error
    'user data directory is already in use' ตอนเปิด Chrome ครั้งถัดไปด้วย Profile เดียวกัน
    """
    for filename in PROFILE_LOCK_FILES:
        lock_path = os.path.join(FACEBOOK_PROFILE_DIR, filename)
        try:
            if os.path.exists(lock_path):
                os.remove(lock_path)
        except OSError:
            pass

    if os.name == "nt":
        _kill_orphaned_chrome_processes_windows()


def _clone_profile_for_worker(source_profile: str, target_profile: str) -> None:
    """
    คัดลอกไฟล์ session/cookies จาก source_profile ไปยัง target_profile สำหรับ worker แต่ละตัว
    โดยข้าม cache โฟลเดอร์ขนาดใหญ่ เพื่อให้เสร็จสิ้นภายในเสี้ยววินาที (~50-80ms)
    ทำให้ทุก worker thread ใน linkcrawler.py ใช้งาน session Facebook ที่ล็อกอินไว้ได้พร้อมกัน
    โดยไม่ชน SingletonLock ของ Chrome
    """
    if not os.path.isdir(source_profile):
        return

    ignored_dirs = {
        "Cache",
        "Code Cache",
        "DawnGraphiteCache",
        "DawnWebGPUCache",
        "GPUCache",
        "component_crx_cache",
        "extensions_crx_cache",
        "optimization_guide_model_store",
    }

    def _ignore(path, names):
        return {
            n for n in names
            if n in ignored_dirs or n.startswith("Singleton") or n == "RunningChromeVersion"
        }

    try:
        shutil.copytree(
            source_profile,
            target_profile,
            ignore=_ignore,
            dirs_exist_ok=True,
            ignore_dangling_symlinks=True,
        )
    except Exception as e:
        print(f"[Chrome Driver] ไม่สามารถคัดลอก session จาก Profile หลักได้ (จะเริ่มด้วย profile ว่างแทน): {e}")


def _build_chrome_options(
    headless: bool,
    user_data_dir: Optional[str] = None,
    page_load_strategy: str = "normal"
) -> Options:
    chrome_options = Options()
    if headless:
        chrome_options.add_argument("--headless=new")

    if page_load_strategy:
        chrome_options.page_load_strategy = page_load_strategy

    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--disable-popup-blocking")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--lang=th-TH,th")
    chrome_options.add_argument("--mute-audio")
    chrome_options.add_argument("--disable-renderer-backgrounding")
    chrome_options.add_argument("--disable-backgrounding-occluded-windows")
    chrome_options.add_argument("--disable-features=Translate,OptimizationHints,MediaRouter")

    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

    if user_data_dir:
        chrome_options.add_argument(f"--user-data-dir={user_data_dir}")

    if sys.platform == "darwin":
        user_agent = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/153.0.0.0 Safari/537.36"
        )
    else:
        user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/153.0.0.0 Safari/537.36"
        )
    chrome_options.add_argument(f"user-agent={user_agent}")
    return chrome_options


def create_stealth_chrome_driver(
    headless: bool = True,
    profile_dir: Optional[str] = None,
    page_load_strategy: str = "normal",
    skip_facebook_profile: bool = False
) -> "webdriver.Chrome":
    """
    สร้างและตั้งค่า Selenium Chrome WebDriver พร้อม Stealth Arguments
    (ป้องกัน bot detection) สำหรับหน้าเว็บที่ตรวจจับ automation เช่น Facebook, X, YouTube
    """
    if webdriver is None:
        raise RuntimeError(
            "ไม่พบแพ็กเกจ 'selenium' ในสภาพแวดล้อม Python นี้\n"
            "👉 กรุณารันคำสั่งติดตั้ง: pip install -r requirements.txt หรือ python -m pip install selenium"
        )

    """
    การจัดการ Chrome User Profile:
    1. หากระบุ profile_dir (เช่น login_facebook.py / logout_facebook.py ส่ง FACEBOOK_PROFILE_DIR):
       จะใช้งาน profile_dir นั้นโดยตรง และจะไม่ลบโฟลเดอร์ทิ้งเมื่อ driver.quit()
    2. หากไม่ระบุ profile_dir (crawler ทั่วไป / worker threads):
       จะสร้างโฟลเดอร์ profile แยกเฉพาะตัวของแต่ละ worker ใน temp directory เพื่อป้องกัน
       ปัญหา Chrome SingletonLock ชนกัน หรือ 'Chrome instance exited' ในระบบ Multithreading
       และหากพบว่า FACEBOOK_PROFILE_DIR มี session Facebook อยู่ (มี Default/)
       และไม่ได้ระบุ skip_facebook_profile=True หรือติด Action Block อยู่ จะคัดลอก
       Cookies/Session มายัง temp profile นี้ให้อัตโนมัติ (ข้ามแคชขนาดใหญ่ ใช้เวลาเพียง ~0.06 วิ)
       ทำให้ทุก worker สามารถดึง Live ที่ต้อง Login ได้ทันที
    """
    is_custom = bool(profile_dir)
    if profile_dir:
        target_profile = profile_dir
        os.makedirs(target_profile, exist_ok=True)
        _clear_stale_profile_locks()
    else:
        target_profile = os.path.join(
            tempfile.gettempdir(),
            f"chrome_crawler_{os.getpid()}_{uuid.uuid4().hex[:8]}"
        )
        should_clone = (
            not skip_facebook_profile
            and not is_facebook_blocked_this_round()
            and not is_facebook_logged_out()
        )
        if should_clone and os.path.isdir(os.path.join(FACEBOOK_PROFILE_DIR, "Default")):
            _clone_profile_for_worker(FACEBOOK_PROFILE_DIR, target_profile)

    max_attempts = 2
    last_error: Optional[WebDriverException] = None

    for attempt in range(1, max_attempts + 1):
        if attempt > 1 and is_custom:
            _clear_stale_profile_locks()
        try:
            driver = webdriver.Chrome(options=_build_chrome_options(headless, user_data_dir=target_profile, page_load_strategy=page_load_strategy))

            # Wrap quit() เพื่อลบ temp profile directory อัตโนมัติ (เฉพาะเมื่อเป็น temp profile)
            original_quit = driver.quit
            def safe_quit():
                try:
                    original_quit()
                except Exception:
                    pass
                if not is_custom and os.path.exists(target_profile):
                    try:
                        shutil.rmtree(target_profile, ignore_errors=True)
                    except Exception:
                        pass
            driver.quit = safe_quit

            return driver
        except WebDriverException as e:
            last_error = e
            print(f"[Chrome Driver] เปิด Chrome ไม่สำเร็จ (ครั้งที่ {attempt}/{max_attempts}): {e}")
            if attempt < max_attempts:
                time.sleep(1)

    print(f"[Chrome Driver] เปิด Chrome ไม่สำเร็จหลังลองครบ {max_attempts} ครั้งแล้ว ยอมแพ้")
    raise last_error
