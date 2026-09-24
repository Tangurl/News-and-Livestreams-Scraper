import html
import json
import os
import random
import re
import ssl
import threading
import time
import urllib.request
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from urllib.parse import urljoin, urlparse, parse_qs, unquote
from zoneinfo import ZoneInfo

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from modules.utilities import (
    FACEBOOK_PROFILE_DIR,
    THAI_MONTH_REGEX,
    create_stealth_chrome_driver,
    gregorian_year_to_be_short,
    is_facebook_blocked_this_round,
    is_facebook_logged_out,
    normalize_title_text,
    parse_thai_date_match,
    reset_facebook_blocked_status,
    reset_facebook_logged_out_status,
    set_facebook_blocked_this_round,
    set_facebook_logged_out,
)

COMMON_STOPWORDS = {
    "ไทยพีบีเอส", "thaipbs", "live", "สด", "น", "recap", "hd", "ช่อง", "หมายเลข3",
    "nation", "เนชั่น", "nationtv", "ch3", "ch7", "one31", "gmm25", "tnn", "tnn16", 
    "true4u", "pptv", "amarin", "thairath", "ช่อง3", "ช่อง7", "ช่อง8", "ช่อง9", "ช่อง11"
}


# ชื่อไฟล์ Config สำหรับกำหนดช่องหรือรายการที่ต้องใช้ Facebook Login
FACEBOOK_LOGIN_TARGETS_FILE = "facebook_login_targets.json"

_CACHED_LOGIN_TARGETS: Optional[Dict] = None
_CACHED_LOGIN_TARGETS_MTIME: float = 0.0
_GLOBAL_DISABLE_FACEBOOK_LOGIN: bool = False


def disable_all_facebook_login(disabled: bool = True):
    """
    ตั้งค่าปิด/เปิด การใช้งานบัญชีล็อกอิน Facebook ทั้งหมดทั่วทั้งระบบ (Global CLI/Runtime Override)
    เมื่อตั้งค่าเป็น True จะบังคับให้การดึงข้อมูล Facebook ทุกช่อง/เพจ ใช้ Clean Session (Guest) ทั้งหมด
    """
    global _GLOBAL_DISABLE_FACEBOOK_LOGIN
    _GLOBAL_DISABLE_FACEBOOK_LOGIN = disabled


def is_all_facebook_login_disabled() -> bool:
    """
    ตรวจสอบว่ามีการสั่งปิดการใช้งาน Facebook Login ทั้งหมดหรือไม่
    (ผ่านคำสั่ง CLI flag, ตัวแปรสภาพแวดล้อม SKIP_FACEBOOK_LOGIN, หรือตั้งค่า enabled: false ใน json)
    """
    if _GLOBAL_DISABLE_FACEBOOK_LOGIN:
        return True
    if os.getenv("SKIP_FACEBOOK_LOGIN", "false").strip().lower() in ("true", "1", "yes"):
        return True
    cfg = load_facebook_login_targets()
    if cfg.get("enabled") is False or cfg.get("use_login") is False:
        return True
    return False


def load_facebook_login_targets(reload: bool = False) -> Dict:
    """
    โหลดการตั้งค่าช่อง/รายการที่ต้องใช้ Facebook Login จาก facebook_login_targets.json
    มีระบบตรวจจับการแก้ไขไฟล์อัตโนมัติ (mtime) ทำให้การแก้ไขไฟล์มีผลทันที
    หากไม่พบไฟล์ จะใช้ค่า Default: Thai PBS, Thairath TV, ONE และรายการ โหนกระแส
    """
    global _CACHED_LOGIN_TARGETS, _CACHED_LOGIN_TARGETS_MTIME

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        os.path.join(base_dir, FACEBOOK_LOGIN_TARGETS_FILE),
        os.path.join(base_dir, "ViewStatsScraper", FACEBOOK_LOGIN_TARGETS_FILE),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), FACEBOOK_LOGIN_TARGETS_FILE)
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                mtime = os.path.getmtime(p)
                if not reload and _CACHED_LOGIN_TARGETS is not None and mtime == _CACHED_LOGIN_TARGETS_MTIME:
                    return _CACHED_LOGIN_TARGETS
                with open(p, "r", encoding="utf-8") as f:
                    _CACHED_LOGIN_TARGETS = json.load(f)
                    _CACHED_LOGIN_TARGETS_MTIME = mtime
                    return _CACHED_LOGIN_TARGETS
            except Exception:
                pass

    if _CACHED_LOGIN_TARGETS is not None and not reload:
        return _CACHED_LOGIN_TARGETS

    _CACHED_LOGIN_TARGETS = {
        "enabled": False,
        "channels": ["Thai PBS", "Thairath TV", "ONE"],
        "broadcasts": ["โหนกระแส"]
    }
    return _CACHED_LOGIN_TARGETS


def should_use_facebook_login(
    channel_name: Optional[str] = None,
    program_titles: Optional[List[str]] = None,
    page_url: Optional[str] = None
) -> Tuple[bool, str]:
    """
    ตรวจสอบว่าช่อง รายการ หรือ URL เพจนี้ ต้องใช้บัญชี Facebook ที่ล็อกอินไว้หรือไม่
    ตามเงื่อนไขใน facebook_login_targets.json (Default: ThaiPBS, Thairath TV, ONE, โหนกระแส)
    คืนค่า (is_required, reason)
    """
    # 0. ตรวจสอบเงื่อนไขปิดการล็อกอินทั้งหมด (Global Disable)
    if _GLOBAL_DISABLE_FACEBOOK_LOGIN:
        return False, "ปิดการใช้งานบัญชี Login ทั้งหมดผ่านคำสั่ง (--no-facebook-login)"

    if os.getenv("SKIP_FACEBOOK_LOGIN", "false").strip().lower() in ("true", "1", "yes"):
        return False, "ปิดการใช้งานบัญชี Login ทั้งหมดผ่านสภาพแวดล้อม (SKIP_FACEBOOK_LOGIN=true)"

    cfg = load_facebook_login_targets()
    if cfg.get("enabled") is False or cfg.get("use_login") is False:
        return False, "ปิดการใช้งานบัญชี Login ทั้งหมดใน facebook_login_targets.json (enabled: false)"

    target_channels = [re.sub(r"[\s_\-]", "", str(c or "").lower()) for c in cfg.get("channels", []) if c]
    target_broadcasts = [str(b).strip() for b in cfg.get("broadcasts", []) if b]

    # 1. ตรวจสอบชื่อช่อง (Channel Name)
    if channel_name:
        ch_norm = re.sub(r"[\s_\-]", "", str(channel_name).lower())
        for tc in target_channels:
            if tc in ch_norm or ch_norm in tc:
                return True, f"ช่อง '{channel_name}' อยู่ในรายการที่ต้องใช้บัญชี Login"

    # 2. ตรวจสอบชื่อรายการ (Broadcast Titles) เช่น 'โหนกระแส'
    if program_titles:
        for t in program_titles:
            t_str = str(t)
            for tb in target_broadcasts:
                if tb in t_str:
                    return True, f"รายการ '{tb}' อยู่ในรายการที่ต้องใช้บัญชี Login"

    # 3. ตรวจสอบจาก URL ของเพจ (Fallback หากไม่ระบุ channel_name)
    if page_url:
        u_norm = re.sub(r"[\s_\-]", "", str(page_url).lower())
        for tc in target_channels:
            if tc in u_norm:
                return True, f"เพจ '{tc}' อยู่ในรายการที่ต้องใช้บัญชี Login"

    return False, "ไม่อยู่ในเงื่อนไขที่ต้องล็อกอิน (ใช้ Clean Session)"


def create_driver(headless: bool = True, force_clean: bool = False) -> webdriver.Chrome:
    """
    สร้างและตั้งค่า Selenium Chrome WebDriver พร้อม Stealth Arguments (สำหรับ Facebook)
    - หาก force_clean=True หรือตรวจพบว่าบัญชี Facebook ติด Action Block หรือหลุด Login หรือสั่งปิด Facebook Login ทั้งหมด จะเปิดเป็น Clean Session ทันที
    - นอกเหนือจากนั้น จะใช้ Profile ที่ล็อกอินไว้ตามปกติ
    """
    if force_clean or is_facebook_blocked_this_round() or is_all_facebook_login_disabled() or is_facebook_logged_out():
        return create_stealth_chrome_driver(headless=headless, skip_facebook_profile=True)
    return create_stealth_chrome_driver(headless=headless)


def dismiss_login_popup(driver: webdriver.Chrome, debug_screenshot_path: Optional[str] = None):
    """
    ปิด Popup Login Modal และ Dialog บังหน้าจอ
    หากระบุ debug_screenshot_path จะถ่ายภาพหน้าจอหลังพยายามปิด popup ไว้ให้ตรวจสอบว่า
    ปิดสำเร็จจริงหรือไม่ (สำหรับ debug กรณีที่ crawler ดึงวิดีโอไม่เจอ)
    """
    try:
        # หมายเหตุ: บาง popup login ของ Facebook ไม่ได้อยู่ใน div[role='dialog']
        # (เช่น floating close button เดี่ยวๆ ที่มี aria-label='ปิด'/'Close' และ role='button')
        # จึงต้องค้นหา close button โดยตรงเสมอ ไม่ผูกเงื่อนไขไว้กับการเจอ div[role='dialog'] ก่อน
        xpaths = [
            "//div[@role='button' and @aria-label='ปิด']",
            "//div[@role='button' and @aria-label='Close']",
            "//div[@role='dialog']//div[@aria-label='Close']",
            "//div[@role='dialog']//div[@aria-label='ปิด']",
            "//div[@aria-label='Close']",
            "//div[@aria-label='ปิด']",
            "//div[@role='dialog']//span[text()='ไม่ใช่ตอนนี้']",
            "//div[@role='dialog']//span[text()='Not Now']",
            "//div[@role='dialog']//span[text()='Not now']",
            "//div[@role='dialog']//span[text()='ยกเลิก']",
            "//div[@role='dialog']//span[text()='Cancel']",
            "//div[@role='dialog']//*[@role='button']",
            "//div[@role='banner']//*[@role='button']",
            "//div[@role='dialog']//i"
        ]
        for xpath in xpaths:
            try:
                close_buttons = driver.find_elements(By.XPATH, xpath)
                for close_btn in close_buttons:
                    if close_btn.is_displayed():
                        driver.execute_script("arguments[0].click();", close_btn)
                        time.sleep(0.2)
                        break
            except Exception:
                pass

        try:
            driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        except Exception:
            pass

        # Cleanup Dialog & Overlays
        js_cleanup = """
        let dialogs = document.querySelectorAll("div[role='dialog']");
        dialogs.forEach(d => d.remove());
        let overlays = document.querySelectorAll("div[data-nosnippet]");
        overlays.forEach(o => o.remove());
        document.body.style.overflow = 'auto';
        document.documentElement.style.overflow = 'auto';
        """
        driver.execute_script(js_cleanup)
    except Exception:
        pass

    if debug_screenshot_path:
        try:
            driver.save_screenshot(debug_screenshot_path)
            print(f"[Facebook Crawler] บันทึกภาพหน้าจอ Debug หลังปิด Popup ไว้ที่: {debug_screenshot_path}")
        except Exception as e:
            print(f"[Warning] ไม่สามารถบันทึกภาพหน้าจอ Debug ได้: {e}")


def expand_see_more_buttons(driver: webdriver.Chrome) -> int:
    """
    คลิกปุ่ม 'ดูเพิ่มเติม' / 'See more' ทั้งหมดบนหน้า Facebook เพื่อขยายชื่อรายการ (Title)
    และคำอธิบาย (Description/Hashtags) ที่ถูก Facebook ซ่อนหรือย่อไว้
    """
    try:
        clicked = driver.execute_script("""
            let candidates = document.querySelectorAll('div[role="button"], span[role="button"], a[role="button"], div, span');
            let count = 0;
            for (let el of candidates) {
                let t = (el.textContent || el.innerText || '').trim();
                if (t === 'ดูเพิ่มเติม' || t === 'See more' || t === 'See More' || t === 'ดูเพิ่มเติม...') {
                    // ป้องกันการคลิก element แม่ที่มี child ตรงเงื่อนไขอยู่แล้ว เพื่อไม่ให้คลิกผิดชั้น
                    if (el.children.length > 0 && Array.from(el.children).some(c => (c.textContent || '').trim() === t)) {
                        continue;
                    }
                    try {
                        el.click();
                        count++;
                    } catch(e) {}
                }
            }
            return count;
        """)
        if clicked and clicked > 0:
            time.sleep(0.3)
        return clicked or 0
    except Exception:
        return 0


def clean_facebook_url(url: str) -> str:
    """
    จัดรูปแบบ URL วิดีโอ Facebook ให้สะอาดและเป็นมาตรฐาน
    """
    if not url:
        return ""
    
    if "/watch" in url:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        if "v" in qs:
            return f"https://www.facebook.com/watch/?v={qs['v'][0]}"
            
    vid_match = re.search(r"/videos/(?:[^/]+/)?(\d{10,20})", url)
    if vid_match:
        vid_id = vid_match.group(1)
        page_match = re.search(r"facebook\.com/([^/]+)/videos", url)
        page_name = page_match.group(1) if page_match and page_match.group(1) not in ("watch", "videos") else ""
        if page_name and not page_name.isdigit():
            return f"https://www.facebook.com/{page_name}/videos/{vid_id}/"
        return f"https://www.facebook.com/watch/?v={vid_id}"
        
    return url.split("?")[0].rstrip("/") + "/"


def fetch_facebook_og_metadata(url: str, timeout: int = 4) -> Dict[str, str]:
    """
    ดึง OpenGraph Title, Description และ Canonical Slug จาก Facebook โดยตรง
    ด้วย facebookexternalhit User-Agent รวดเร็วภายใน 0.5-1.5 วินาที
    มีประโยชน์มากเมื่อ Facebook แสดงผลเฉพาะ Avatar/Header ที่มีข้อความสั้นๆ เช่น '<Page> is on Live'
    """
    vid_m = re.search(r"/videos/(\d+)", url) or re.search(r"[?&]v=(\d+)", url)
    if not vid_m:
        return {}
    video_id = vid_m.group(1)
    target_url = f"https://www.facebook.com/watch/?v={video_id}"
    
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(
        target_url,
        headers={"User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)"}
    )
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
            page = resp.read().decode("utf-8", errors="ignore")
            og_desc = re.search(r'<meta\s+property=\"og:description\"\s+content=\"([^\"]+)\"', page)
            og_url = re.search(r'<meta\s+property=\"og:url\"\s+content=\"([^\"]+)\"', page)
            og_title = re.search(r'<meta\s+property=\"og:title\"\s+content=\"([^\"]+)\"', page)
            
            desc = html.unescape(og_desc.group(1)).strip() if og_desc else ""
            slug = unquote(og_url.group(1)).strip() if og_url else ""
            title = html.unescape(og_title.group(1)).strip() if og_title else ""
            
            return {
                "title": title,
                "description": desc,
                "slug": slug
            }
    except Exception:
        return {}



def extract_thai_date_from_title(title: str) -> Optional[Tuple[int, int, Optional[int]]]:
    """
    ดึงวันที่ไทยจาก Title เช่น:
    - '(7 ส.ค. 69)' -> (7, 8, 69)
    - '(7 ส.ค.69)'  -> (7, 8, 69)
    - '(7 ส.ค.)'    -> (7, 8, None)
    - '6 ส.ค. 69'   -> (6, 8, 69)
    """
    if not title:
        return None

    # ค้นหา patterns วันที่ เช่น (7 ส.ค. 69), (7 ส.ค.69), 7 ส.ค. 69, 7 ส.ค.
    pattern = rf"\(?\s*(\d{{1,2}})\s*({THAI_MONTH_REGEX})(?:\s*(\d{{2,4}}))?\s*\)?"
    match = re.search(pattern, title)
    return parse_thai_date_match(match)


def parse_duration_to_seconds(dur_str: str) -> int:
    """แปลงข้อความความยาวคลิป เช่น '2:06', '25:03', '1:27:35' เป็นจำนวนวินาที"""
    if not dur_str:
        return 0
    parts = str(dur_str).strip().split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except Exception:
        pass
    return 0


def normalize_facebook_page_url(url: str) -> str:
    """
    จัดรูปแบบ URL เพจ Facebook ให้เป็นหน้า Watch Grid (https://www.facebook.com/watch/<PageName>/)
    ซึ่งเป็นหน้าแสดงวิดีโอหลักของเพจ และแสดง Live Stream กำลังออนแอร์ไว้ที่ด้านบนสุด
    รองรับทุกรูปแบบ เช่น:
      - 'https://www.facebook.com/watch/ThaiPBS/' -> 'https://www.facebook.com/watch/ThaiPBS/'
      - 'https://www.facebook.com/ThaiPBS' -> 'https://www.facebook.com/watch/ThaiPBS/'
      - 'https://www.facebook.com/watch/HKS2017/?mibextid=...' -> 'https://www.facebook.com/watch/HKS2017/'
      - 'https://www.facebook.com/profile.php?id=100064848382718' -> 'https://www.facebook.com/watch/100064848382718/'
    หากเป็น URL วิดีโอโดยตรง (มี /videos/<id> หรือ ?v=) หรือผู้ใช้ระบุ /live_videos/ มาโดยตรง จะคงเดิมไว้
    """
    if not url:
        return ""
    u = str(url).strip()

    # ลิงก์วิดีโอโดยตรง หรือลิงก์ที่ระบุ /live_videos/ เจาะจง ไม่ต้องดัดแปลง
    if re.search(r"/videos/\d+", u) or "v=" in u or "/watch/?v=" in u or "/live_videos" in u:
        return u

    parsed = urlparse(u)
    path = parsed.path.strip("/")

    # กรณี profile.php?id=...
    qs = parse_qs(parsed.query)
    if "profile.php" in path and "id" in qs:
        page_id = qs["id"][0]
        return f"https://www.facebook.com/watch/{page_id}/"

    parts = [p for p in path.split("/") if p]
    if not parts:
        return u

    # ถ้าขึ้นต้นด้วย watch เช่น /watch/ThaiPBS/
    if parts[0].lower() == "watch":
        if len(parts) > 1 and parts[1].lower() not in ("topic", "shows", "live"):
            page_name = parts[1]
            return f"https://www.facebook.com/watch/{page_name}/"
        return u

    # กรณีชื่อเพจทั่วไป เช่น ThaiPBS
    page_name = parts[0]
    reserved_words = {"watch", "home", "groups", "stories", "share", "login", "pages"}
    if page_name.lower() in reserved_words:
        return u

    return f"https://www.facebook.com/watch/{page_name}/"


def get_alternative_page_url(url: str) -> Optional[str]:
    """
    สร้าง URL สำรองของเพจเพื่อใช้ Fallback กรณีหน้าแรกไม่พบ Live:
    - หากหน้าแรกเป็น /watch/<Page>/ จะคืนค่า https://www.facebook.com/<Page>/live_videos/
    - หากหน้าแรกเป็น /<Page>/live_videos/ จะคืนค่า https://www.facebook.com/watch/<Page>/
    - หากเป็นรูปแบบอื่น จะพยายามสกัดชื่อเพจมาสร้างหน้า live_videos
    """
    if not url:
        return None
    u = str(url).strip()
    parsed = urlparse(u)
    path = parsed.path.strip("/")
    parts = [p for p in path.split("/") if p]
    if not parts:
        return None

    # กรณี profile.php?id=...
    qs = parse_qs(parsed.query)
    if "profile.php" in path and "id" in qs:
        pid = qs["id"][0]
        return f"https://www.facebook.com/{pid}/live_videos/"

    if parts[0].lower() == "watch":
        if len(parts) > 1 and parts[1].lower() not in ("topic", "shows", "live"):
            page_name = parts[1]
            return f"https://www.facebook.com/{page_name}/live_videos/"
        return None

    page_name = parts[0]
    reserved_words = {"watch", "home", "groups", "stories", "share", "login", "pages"}
    if page_name.lower() in reserved_words:
        return None

    if len(parts) > 1 and parts[1].lower() == "live_videos":
        return f"https://www.facebook.com/watch/{page_name}/"

    return f"https://www.facebook.com/{page_name}/live_videos/"


def parse_relative_time_to_minutes(time_text: str) -> Optional[int]:
    """
    แปลงข้อความเวลาสัมพัทธ์บน Facebook เช่น '36 นาที', '58m', '1 ชม.', '1h', 'เมื่อสักครู่', 'เมื่อวาน', 'yesterday'
    ให้เป็นจำนวนนาที (int) ที่ผ่านไปนับจากที่เริ่มโพสต์/สตรีม
    """
    if not time_text:
        return None
    t = time_text.strip().lower()
    if t in ("เมื่อสักครู่", "just now"):
        return 0
    if "เมื่อวาน" in t or "yesterday" in t:
        return 1440  # อย่างน้อย 1 วัน (24 ชั่วโมง)

    m_sec = re.search(r'(\d+)\s*(?:วินาที|วิ|s|sec|secs|second|seconds)\b', t)
    if m_sec:
        return 0

    m_min = re.search(r'(\d+)\s*(?:นาที|m|min|mins|minute|minutes)\b', t)
    if m_min:
        return int(m_min.group(1))

    m_hr = re.search(r'(\d+)\s*(?:ชม\.?|ชั่วโมง|h|hr|hrs|hour|hours)\b', t)
    if m_hr:
        return int(m_hr.group(1)) * 60

    m_day = re.search(r'(\d+)\s*(?:วัน|d|day|days)\b', t)
    if m_day:
        return int(m_day.group(1)) * 1440

    m_wk = re.search(r'(\d+)\s*(?:สัปดาห์|w|wk|wks|week|weeks)\b', t)
    if m_wk:
        return int(m_wk.group(1)) * 10080

    m_mo = re.search(r'(\d+)\s*(?:เดือน|mo|month|months)\b', t)
    if m_mo:
        return int(m_mo.group(1)) * 43200

    m_yr = re.search(r'(\d+)\s*(?:ปี|y|yr|yrs|year|years)\b', t)
    if m_yr:
        return int(m_yr.group(1)) * 525600

    return None


def _extract_videos_from_current_page(
    driver: webdriver.Chrome,
    video_dict: Dict[str, Dict[str, object]],
    max_scrolls: int = 15,
    scroll_delay: float = 1.0,
    dismiss_popups: bool = True
) -> None:
    """
    เลื่อนหน้าจอและดึงรายการวิดีโอทั้งหมดจากหน้าปัจจุบันเข้าสู่ video_dict
    """
    for idx in range(max_scrolls):
        driver.execute_script("""
            document.querySelectorAll('div[role="dialog"]').forEach(el => el.remove());
            document.querySelectorAll('div[data-nosnippet="true"]').forEach(el => el.remove());
            
            document.documentElement.style.setProperty('overflow', 'auto', 'important');
            document.documentElement.style.setProperty('overflow-y', 'auto', 'important');
            document.body.style.setProperty('overflow', 'auto', 'important');
            document.body.style.setProperty('overflow-y', 'auto', 'important');
        """)
        
        driver.execute_script("""
            window.scrollBy(0, 1500);
            window.dispatchEvent(new Event('scroll'));
        """)
        time.sleep(scroll_delay)
        if dismiss_popups:
            dismiss_login_popup(driver)
        if idx % 2 == 0:
            expand_see_more_buttons(driver)

    # คลิก 'ดูเพิ่มเติม' / 'See more' รอบสุดท้ายก่อนดึงข้อมูล
    expand_see_more_buttons(driver)

    extracted_data = driver.execute_script("""
        let isLiveTab = window.location.pathname.includes('/live_videos');
        let results = [];
        let mainEl = document.querySelector('div[role="main"]') || document.body;
        
        // ขยายปุ่มดูเพิ่มเติมที่อาจหลงเหลืออยู่ใน DOM
        let seeMoreBtns = document.querySelectorAll('div[role="button"], span[role="button"], a[role="button"]');
        for (let el of seeMoreBtns) {
            let t = (el.textContent || el.innerText || '').trim();
            if (t === 'ดูเพิ่มเติม' || t === 'See more' || t === 'See More' || t === 'ดูเพิ่มเติม...') {
                try { el.click(); } catch(e) {}
            }
        }

        let gridLinks = Array.from(document.querySelectorAll('a[href*="/videos/"], a[href*="/watch/"], a[href*="v="], a[href*="/live/"], a[href*="/live?"]'));
        for (let a of gridLinks) {
            let href = a.href;
            if (!href || href.includes('comment_id')) continue;

            let card = a;
            let cardText = '';
            for (let i = 0; i < 7; i++) {
                if (card.parentElement && card.parentElement !== mainEl && card.parentElement.tagName !== 'BODY') {
                    card = card.parentElement;
                    let txt = (card.innerText || '').replace(/\\n+/g, ' ').replace(/ดูเพิ่มเติม\\.\\.\\.|ดูเพิ่มเติม|See more|See More/g, ' ').trim();
                    if (txt.length >= 10 && txt.length <= 4000 && (isLiveTab || txt.includes('Live') || txt.includes('สด') || txt.includes('น.') || txt.includes('#') || txt.includes(':') || txt.includes('views') || txt.includes('รับชม'))) {
                        cardText = txt;
                        break;
                    }
                }
            }

            if (!cardText) {
                let aria = a.getAttribute('aria-label') || '';
                let aText = a.innerText.replace(/\\n+/g, ' ').replace(/ดูเพิ่มเติม\\.\\.\\.|ดูเพิ่มเติม|See more|See More/g, ' ').trim();
                cardText = (aria + ' ' + aText).trim();
            }

            // Extract post caption / description text from the enclosing post container
            let postContainer = a.closest('div[role="article"], div[data-pagelet*="FeedUnit"], div[data-nosnippet="false"], .x1yztbdb') || card || a.parentElement;
            let descText = '';
            if (postContainer) {
                let localSeeMore = Array.from(postContainer.querySelectorAll('div[role="button"], span[role="button"]')).find(el => {
                    let txt = (el.textContent || el.innerText || '').trim();
                    return txt === 'ดูเพิ่มเติม' || txt === 'See more' || txt === 'See More';
                });
                if (localSeeMore) {
                    try { localSeeMore.click(); } catch(e) {}
                }

                let msgEl = postContainer.querySelector('div[data-ad-preview="message"], div[dir="auto"].xdj266r, div[dir="auto"]');
                if (msgEl) {
                    let mTxt = (msgEl.innerText || '').replace(/\\n+/g, ' ').replace(/ดูเพิ่มเติม\\.\\.\\.|ดูเพิ่มเติม|See more|See More/g, ' ').trim();
                    if (mTxt && mTxt !== cardText) {
                        descText = mTxt;
                    }
                }
                if (!descText) {
                    let autoEls = Array.from(postContainer.querySelectorAll('div[dir="auto"], span[dir="auto"]'));
                    for (let el of autoEls) {
                        let t = (el.innerText || '').replace(/\\n+/g, ' ').replace(/ดูเพิ่มเติม\\.\\.\\.|ดูเพิ่มเติม|See more|See More/g, ' ').trim();
                        if (t.length > 20 && t !== cardText && !t.includes('views') && !t.includes('รับชม')) {
                            descText = t;
                            break;
                        }
                    }
                }
            }

            let container = card || a.parentElement;
            let spans = Array.from(container.querySelectorAll('span, div')).map(s => (s.innerText || '').trim()).filter(Boolean);

            let hasLiveBadge = spans.some(t => t === 'LIVE' || t === 'สด');

            let durationBadge = '';
            for (let t of spans) {
                if (/^[0-9]{1,2}:[0-9]{2}(:[0-9]{2})?$/.test(t)) {
                    durationBadge = t;
                    break;
                }
            }

            let timeText = '';
            let searchScope = postContainer || container;
            let timeLinks = Array.from(searchScope.querySelectorAll('a[role="link"], a[href*="/videos/"], a[href*="/posts/"], a[href*="permalink"], a[href*="story.php"], span.html-span a, .x17zd0t2 a, abbr, time'));
            for (let tl of timeLinks) {
                let t = (tl.innerText || tl.getAttribute('aria-label') || '').trim();
                if (/^(\d+\s*(?:นาที|ชม|ชม\.|ชั่วโมง|วัน|m|h|d|min|mins|hr|hrs|s|sec|secs|w|wk|wks|mo|yr)(?:\s*(?:ที่แล้ว|ago))?|เมื่อสักครู่|just now|เมื่อวาน|เมื่อวานนี้|yesterday)$/i.test(t)) {
                    timeText = t;
                    break;
                }
                if (/^(?:yesterday|เมื่อวาน|เมื่อวานนี้|\d+\s*(?:d|day|days|วัน|สัปดาห์|week|weeks|mo|month|months|yr|year|years)(?:\s*(?:ที่แล้ว|ago))?)/i.test(t)) {
                    timeText = t;
                    break;
                }
                let aria = (tl.getAttribute('aria-label') || '').trim();
                if (aria && (aria.includes('เมื่อวาน') || aria.toLowerCase().includes('yesterday') || aria.includes('วัน') || aria.includes('นาที') || aria.includes('ชม') || aria.includes('เวลา'))) {
                    timeText = aria;
                    break;
                }
            }

            let isOngoingLive = hasLiveBadge && !durationBadge;
            let isClip = !hasLiveBadge && !!durationBadge && !isLiveTab;
            let combinedAllText = (cardText + ' ' + descText).trim();
            let wasLive = isOngoingLive || isLiveTab || combinedAllText.includes('ถ่ายทอดสด') || combinedAllText.toLowerCase().includes('was live') || combinedAllText.includes('[Live]');

            results.push({
                href: href,
                title: cardText,
                description: descText,
                text: combinedAllText || cardText,
                time_text: timeText,
                is_ongoing_live: isOngoingLive,
                has_live_badge: hasLiveBadge,
                duration: durationBadge,
                is_clip: isClip,
                was_live: wasLive,
                from_live_tab: isLiveTab
            });
        }
        
        return results;
    """)

    for item in extracted_data:
        try:
            href = item.get("href", "")
            if not href or "comment_id" in href:
                continue
                
            clean_url = clean_facebook_url(urljoin("https://www.facebook.com", href))
            if clean_url in ("https://www.facebook.com/watch/", "https://www.facebook.com/watch/live/", "https://www.facebook.com/watch/shows/", "https://www.facebook.com/watch/topic/"):
                continue
            if not clean_url or ("/videos/" not in clean_url and "v=" not in clean_url and "/watch/?v=" not in clean_url and "/live" not in clean_url):
                continue
            
            card_title = str(item.get("title") or item.get("text") or "").strip()
            card_title = re.sub(r"\s+", " ", card_title)
            desc_text = str(item.get("description") or "").strip()
            desc_text = re.sub(r"\s+", " ", desc_text)
            raw_text = str(item.get("text") or f"{card_title} {desc_text}").strip()
            raw_text = re.sub(r"\s+", " ", raw_text)

            is_ongoing_live = bool(item.get("is_ongoing_live", False))
            has_live_badge = bool(item.get("has_live_badge", False))
            duration = str(item.get("duration", "")).strip()
            dur_seconds = parse_duration_to_seconds(duration)
            is_clip = bool(item.get("is_clip", False))
            was_live = bool(item.get("was_live", False))
            from_live_tab = bool(item.get("from_live_tab", False))

            if is_ongoing_live or dur_seconds >= 1200 or from_live_tab:
                is_clip = False
            elif dur_seconds > 0 and dur_seconds < 1200 and not is_ongoing_live:
                is_clip = True

            # หากวิดีโอนี้กำลัง Live หรือมีข้อความหัวการ์ดสั้น/เป็นข้อความ Generic ของ Avatar (เช่น 'ช่อง8 is on Live')
            # ให้ดึง OpenGraph Title และ Description ของวิดีโอนั้นจาก Facebook เพื่อให้ได้ชื่อรายการที่แท้จริง
            is_generic_title = any(g in card_title.lower() for g in ("is on live", "is live", "กำลังถ่ายทอดสด", "facebook live")) or len(card_title) < 15
            has_bad_desc = not desc_text or any(f in desc_text.lower() for f in ("followers", "following", "ผู้ติดตาม"))
            if is_ongoing_live or (is_generic_title and has_bad_desc):
                og_meta = fetch_facebook_og_metadata(clean_url)
                if og_meta.get("description"):
                    og_d = og_meta["description"].strip()
                    first_line = og_d.split("\n")[0].strip()
                    if is_generic_title and first_line:
                        card_title = first_line
                    if has_bad_desc or len(og_d) > len(desc_text):
                        desc_text = og_d
                    raw_text = f"{card_title} {desc_text}".strip()

            vid_match = re.search(r"/videos/(\d+)", clean_url) or re.search(r"[?&]v=(\d+)", clean_url)
            canonical_key = vid_match.group(1) if vid_match else clean_url

            if canonical_key in video_dict:
                current_title = str(video_dict[canonical_key].get("title", ""))
                current_desc = str(video_dict[canonical_key].get("description", ""))
                if len(card_title) > len(current_title) or (("Live" in card_title or "น." in card_title or "ส.ค." in card_title) and "Live" not in current_title):
                    video_dict[canonical_key]["title"] = card_title
                    video_dict[canonical_key]["raw_text"] = raw_text
                    video_dict[canonical_key]["url"] = clean_url
                if len(desc_text) > len(current_desc):
                    video_dict[canonical_key]["description"] = desc_text
                if item.get("time_text"):
                    video_dict[canonical_key]["time_text"] = str(item.get("time_text", "")).strip()
                video_dict[canonical_key]["is_live"] = video_dict[canonical_key].get("is_live", False) or is_ongoing_live
                video_dict[canonical_key]["is_ongoing_live"] = video_dict[canonical_key].get("is_ongoing_live", False) or is_ongoing_live
                video_dict[canonical_key]["has_live_badge"] = video_dict[canonical_key].get("has_live_badge", False) or has_live_badge
                if not is_clip:
                    video_dict[canonical_key]["is_clip"] = False
                video_dict[canonical_key]["was_live"] = video_dict[canonical_key].get("was_live", False) or was_live
                video_dict[canonical_key]["from_live_tab"] = video_dict[canonical_key].get("from_live_tab", False) or from_live_tab
            else:
                video_dict[canonical_key] = {
                    "title": card_title,
                    "description": desc_text,
                    "url": clean_url,
                    "raw_text": raw_text,
                    "time_text": str(item.get("time_text", "")).strip(),
                    "is_live": is_ongoing_live,
                    "is_ongoing_live": is_ongoing_live,
                    "has_live_badge": has_live_badge,
                    "duration": duration,
                    "duration_seconds": dur_seconds,
                    "is_clip": is_clip,
                    "was_live": was_live,
                    "from_live_tab": from_live_tab
                }
        except Exception:
            continue


def extract_facebook_page_name(url: str) -> Optional[str]:
    """
    ดึงชื่อเพจหรือ Page ID จาก URL ของ Facebook เช่น:
    - https://www.facebook.com/watch/ThaiPBS/ -> ThaiPBS
    - https://www.facebook.com/ThaiPBS/live_videos/ -> ThaiPBS
    - https://www.facebook.com/ThaiPBS/ -> ThaiPBS
    """
    if not url:
        return None
    parsed = urlparse(str(url).strip())
    path = parsed.path.strip("/")
    parts = [p for p in path.split("/") if p]
    if not parts:
        return None
    qs = parse_qs(parsed.query)
    if "profile.php" in path and "id" in qs:
        return qs["id"][0]
    if parts[0].lower() == "watch":
        if len(parts) > 1 and parts[1].lower() not in ("topic", "shows", "live"):
            return parts[1]
        return None
    reserved = {"watch", "home", "groups", "stories", "share", "login", "pages"}
    if parts[0].lower() not in reserved:
        return parts[0]
    return None


_AUTO_LOGIN_LOCK = threading.Lock()
_LAST_AUTO_LOGIN_ATTEMPT: float = 0.0
_LATEST_AUTH_COOKIES: List[Dict] = []


def is_facebook_auto_login_configured() -> bool:
    """
    ตรวจสอบว่ามีการตั้งค่าข้อมูลประจำตัวสำหรับ Facebook Auto Re-Login ใน .env หรือไม่
    (ต้องการอย่างน้อย FB_PASSWORD โดย FB_EMAIL เป็น optional หากโปรไฟล์มีบัญชีค้างอยู่แล้ว)
    """
    auto_enabled = os.getenv("FB_AUTO_LOGIN", "").strip().lower()
    if auto_enabled in ("false", "0", "no"):
        return False
    password = os.getenv("FB_PASSWORD", "").strip()
    return bool(password)


def _human_type(element, text: str, min_delay: float = 0.03, max_delay: float = 0.10) -> None:
    """พิมพ์ข้อความลงใน Input element ทีละตัวอักษรพร้อมหน่วงเวลาสุ่มเพื่อจำลองมนุษย์"""
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(min_delay, max_delay))


def attempt_facebook_auto_relogin(force: bool = False) -> bool:
    """
    พยายามเข้าสู่ระบบ Facebook อัตโนมัติด้วยข้อมูลประจำตัวจาก .env
    ดำเนินการผ่าน Master Chrome Profile (FACEBOOK_PROFILE_DIR) เพื่อบันทึก Session ไว้ถาวร
    รองรับทั้งกรณีฟอร์มเต็ม (Email + Password) และกรณี Continue/Recent Logins (ต้องการเฉพาะ Password)
    """
    global _LAST_AUTO_LOGIN_ATTEMPT, _LATEST_AUTH_COOKIES

    email = os.getenv("FB_EMAIL", "").strip()
    password = os.getenv("FB_PASSWORD", "").strip()
    if not password:
        return False

    cooldown_min = 30
    try:
        cooldown_min = int(os.getenv("FB_LOGIN_COOLDOWN_MINUTES", "30"))
    except Exception:
        cooldown_min = 30

    cooldown_seconds = max(60, cooldown_min * 60)
    now = time.time()

    with _AUTO_LOGIN_LOCK:
        if not force and (now - _LAST_AUTO_LOGIN_ATTEMPT) < cooldown_seconds:
            remaining = int((cooldown_seconds - (now - _LAST_AUTO_LOGIN_ATTEMPT)) / 60)
            print(f"  ⏳ [Facebook Auto-Login] อยู่ในช่วง Cooldown (เหลือ {remaining} นาที) ข้ามการพยายามล็อกอินซ้ำ")
            return False

        _LAST_AUTO_LOGIN_ATTEMPT = now
        headless_login = os.getenv("FB_AUTO_LOGIN_HEADLESS", "true").strip().lower() in ("true", "1", "yes")

        masked_id = f"{email[:3]}***" if email else "Saved Profile"
        print("\n  ==================================================================")
        print(f"  🔐 [Facebook Auto-Login] กำลังเริ่มต้นการล็อกอินอัตโนมัติ ({masked_id})")
        print("  ==================================================================")

        driver = None
        try:
            driver = create_stealth_chrome_driver(
                headless=headless_login,
                profile_dir=FACEBOOK_PROFILE_DIR,
                skip_facebook_profile=False
            )
            driver.set_page_load_timeout(35)

            # 0. ตรวจสอบว่า Profile มีเซสชั่นที่ใช้งานได้อยู่แล้วหรือไม่
            cookies = driver.get_cookies()
            has_c_user = any(c.get("name") == "c_user" for c in cookies)
            has_xs = any(c.get("name") == "xs" for c in cookies)
            if has_c_user and has_xs:
                driver.get("https://www.facebook.com/")
                time.sleep(3)
                curr_url = driver.current_url.lower()
                if not any(k in curr_url for k in ("/login", "/checkpoint", "/recover")):
                    print("  ✨ [Facebook Auto-Login] ตรวจพบว่าบัญชีมีเซสชั่นที่ใช้งานได้อยู่แล้ว 100%!")
                    _LATEST_AUTH_COOKIES = driver.get_cookies()
                    reset_facebook_logged_out_status()
                    reset_facebook_blocked_status()
                    return True

            login_url = "https://www.facebook.com/login"
            driver.get(login_url)
            time.sleep(4)

            # 1. ลองคลิกปุ่ม "Continue" / "Continue as..." / "ดำเนินการต่อในชื่อ..." หรือการ์ดโปรไฟล์
            continue_clicked = False
            try:
                from selenium.webdriver.common.action_chains import ActionChains
                # ค้นหาปุ่ม Continue ที่เป็น interactive element (tabindex=0 หรือ aria-label มีคำว่า Continue)
                continue_btn = None
                for sel in (
                    "div[role='button'][tabindex='0'][aria-label*='Continue']",
                    "div[role='button'][aria-label*='Continue']",
                    "div[role='button'][tabindex='0'][aria-label*='ดำเนินการต่อ']",
                    "div[role='button'][aria-label*='ดำเนินการต่อ']",
                    "[aria-label*='Continue Maruki']",
                    "div[data-testid='recent_login_profile']",
                ):
                    try:
                        c_els = driver.find_elements(By.CSS_SELECTOR, sel)
                        if c_els and c_els[0].is_displayed():
                            continue_btn = c_els[0]
                            break
                    except Exception:
                        pass

                if continue_btn:
                    ActionChains(driver).move_to_element(continue_btn).click().perform()
                    continue_clicked = True
                else:
                    # Fallback JS click
                    continue_clicked = driver.execute_script("""
                        let buttons = Array.from(document.querySelectorAll('button, div[role="button"], a[role="button"], span[role="button"]'));
                        let target = buttons.find(b => {
                            let t = (b.innerText || b.textContent || '').trim().toLowerCase();
                            let a = (b.getAttribute('aria-label') || '').toLowerCase();
                            return t === 'continue' || t.startsWith('continue as') || t.startsWith('ดำเนินการต่อ') || a.includes('continue') || a.includes('ดำเนินการต่อ');
                        });
                        if (target) {
                            target.click();
                            return true;
                        }
                        return false;
                    """)
            except Exception as e:
                pass

            if continue_clicked:
                print("  👉 [Facebook Auto-Login] ตรวจพบปุ่ม 'Continue' หรือการ์ดโปรไฟล์ กำลังคลิกเลือก...")
                time.sleep(3)

            # 2. ตรวจสอบว่าหลังจากคลิกแล้ว เข้าสู่ระบบได้เลยหรือไม่ (1-Click Restore)
            cookies = driver.get_cookies()
            has_c_user = any(c.get("name") == "c_user" for c in cookies)
            has_xs = any(c.get("name") == "xs" for c in cookies)

            # 3. ถ้ายังไม่สำเร็จ ให้ตรวจสอบฟอร์มกรอกรหัสผ่าน (ทั้งแบบ Modal ใส่เฉพาะ Password หรือ Full Form Email + Password)
            curr_url = driver.current_url.lower()

            if not has_c_user or not has_xs or "/login" in curr_url or "checkpoint" in curr_url:
                email_input = None
                pass_input = None

                for sel in ("input[name='email']", "input[id='email']", "input[type='text']"):
                    try:
                        els = driver.find_elements(By.CSS_SELECTOR, sel)
                        if els and els[0].is_displayed():
                            email_input = els[0]
                            break
                    except Exception:
                        pass

                for sel in (
                    "div[role='dialog'] input[type='password']",
                    "input[name='pass']",
                    "input[id='pass']",
                    "input[type='password']"
                ):
                    try:
                        els = driver.find_elements(By.CSS_SELECTOR, sel)
                        if els and els[0].is_displayed():
                            pass_input = els[0]
                            break
                    except Exception:
                        pass

                if pass_input:
                    if email_input and email:
                        print("  ✍️ [Facebook Auto-Login] กำลังกรอก Email และ Password ด้วย Human-like Keystrokes...")
                        email_input.clear()
                        _human_type(email_input, email)
                        time.sleep(random.uniform(0.3, 0.7))
                    else:
                        print("  ✍️ [Facebook Auto-Login] ตรวจพบหน้าต่างยืนยันตัวตน (ใส่เฉพาะ Password) กำลังกรอกรหัสผ่าน...")

                    pass_input.clear()
                    _human_type(pass_input, password)
                    time.sleep(random.uniform(0.4, 0.8))

                    # ค้นหาปุ่ม Login (ให้ความสำคัญกับปุ่มใน Modal ก่อน)
                    modal_login_clicked = driver.execute_script("""
                        let modal = document.querySelector("div[role='dialog']");
                        if (modal) {
                            let buttons = Array.from(modal.querySelectorAll("div[role='button'], button, [type='submit']"));
                            let target = buttons.find(b => {
                                let t = (b.innerText || b.textContent || '').trim().toLowerCase();
                                let a = (b.getAttribute('aria-label') || '').toLowerCase();
                                return t === 'log in' || t === 'เข้าสู่ระบบ' || a === 'log in' || a === 'เข้าสู่ระบบ';
                            });
                            if (target) {
                                target.click();
                                return true;
                            }
                        }
                        return false;
                    """)

                    if modal_login_clicked:
                        print("  🚀 [Facebook Auto-Login] กำลังส่งคำขอเข้าสู่ระบบ (กดปุ่ม Log In ใน Modal)...")
                    else:
                        login_btn = None
                        for sel in (
                            "div[role='button'][aria-label*='Log in']",
                            "div[role='button'][aria-label*='เข้าสู่ระบบ']",
                            "button[name='login']",
                            "#loginbutton",
                            "button[data-testid='royal_login_button']",
                            "input[type='submit']",
                            "button[type='submit']"
                        ):
                            try:
                                btns = driver.find_elements(By.CSS_SELECTOR, sel)
                                if btns and btns[0].is_displayed():
                                    login_btn = btns[0]
                                    break
                            except Exception:
                                pass

                        if login_btn:
                            print("  🚀 [Facebook Auto-Login] กำลังส่งคำขอเข้าสู่ระบบ (กดปุ่ม Log In)...")
                            driver.execute_script("arguments[0].click();", login_btn)
                        else:
                            pass_input.send_keys(Keys.RETURN)

                    # รอให้ Facebook ประมวลผลและเปลี่ยนหน้า
                    time.sleep(8)

            # 3. ตรวจสอบผลลัพธ์หลังพยายามล็อกอิน
            after_url = driver.current_url.lower()
            visible_body_text = ""
            try:
                visible_body_text = (driver.find_element(By.TAG_NAME, "body").text or "").lower()
            except Exception:
                pass

            # 3.1 ตรวจจับ Captcha / 2FA / Checkpoint (ตรวจจาก visible text และ URL ไม่ตรวจ page_source เพื่อเลี่ยง false positive จาก minified JS)
            if any(k in after_url for k in ("/checkpoint", "/recover", "two_factor", "approvals_code")):
                print(f"\n  ⚠️ [Facebook Auto-Login Failed] Facebook ต้องการการยืนยันตัวตนเพิ่มเติม (Checkpoint / 2FA / OTP)")
                print(f"  👉 กรุณารันคำสั่ง: python login_facebook.py เพื่อกดยืนยันตัวตนด้วยตนเองในหน้าต่างเบราว์เซอร์\n")
                return False

            if any(k in visible_body_text for k in ("security check", "ยืนยันความปลอดภัย", "enter code", "ป้อนรหัส", "captcha")):
                print(f"\n  ⚠️ [Facebook Auto-Login Failed] Facebook แสดงหน้าต่าง Captcha หรือ Security Check")
                print(f"  👉 กรุณารันคำสั่ง: python login_facebook.py เพื่อผ่านการทดสอบ\n")
                return False

            # 3.2 ตรวจสอบความสำเร็จ (มี c_user และ xs หรือมี Profile Avatar)
            final_cookies = driver.get_cookies()
            final_c_user = any(c.get("name") == "c_user" for c in final_cookies)
            final_xs = any(c.get("name") == "xs" for c in final_cookies)

            has_profile = driver.execute_script("""
                return document.querySelectorAll(
                    "div[aria-label='Your profile'], div[aria-label='โปรไฟล์ของคุณ'], " +
                    "svg[aria-label='Your profile'], svg[aria-label='โปรไฟล์ของคุณ'], " +
                    "a[href*='/me/']"
                ).length > 0;
            """)

            if (final_c_user and final_xs) or has_profile:
                print("  ==================================================================")
                print("  ✅ [Facebook Auto-Login Success] เข้าสู่ระบบ Facebook สำเร็จเรียบร้อย!")
                print("  💾 บันทึก Session ลงใน Chrome Master Profile กลางเรียบร้อยแล้ว")
                print("  ==================================================================\n")
                _LATEST_AUTH_COOKIES = final_cookies
                reset_facebook_logged_out_status()
                reset_facebook_blocked_status()
                return True
            else:
                print("  ❌ [Facebook Auto-Login Failed] ไม่สามารถเข้าสู่ระบบได้ (อาจเกิดจากรหัสผ่านไม่ถูกต้อง หรือโครงสร้างหน้าเปลี่ยน)")
                return False

        except Exception as e:
            print(f"  ⚠️ [Facebook Auto-Login Error] เกิดข้อผิดพลาดขณะพยายามล็อกอิน: {e}")
            return False
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass


_WARNED_LOGGED_OUT_THIS_RUN = False


def check_and_handle_logged_out(driver: webdriver.Chrome, target_url: str, auto_relogin: bool = True) -> bool:
    """
    ตรวจสอบว่าบัญชี Facebook หลุดการล็อกอิน (Session Expired, Checkpoint, หรือขึ้นหน้า 'Continue as...') หรือไม่
    หากหลุด จะแจ้งเตือนผู้ใช้ให้รัน login_facebook.py และสลับเป็น Clean Session ในรอบนี้อัตโนมัติ
    """
    global _WARNED_LOGGED_OUT_THIS_RUN, _LATEST_AUTH_COOKIES
    try:
        current_url = driver.current_url.lower()
        title_lower = driver.title.lower() if driver.title else ""

        # ตรวจสอบสถานะ DOM เชิงลึกผ่าน JavaScript
        dom_status = driver.execute_script("""
            let res = {
                has_profile_avatar: false,
                has_login_form: false,
                has_continue_prompt: false,
                has_session_expired: false,
                has_recent_logins: false,
                has_guest_login_button: false,
                continue_button_text: ""
            };

            // 1. ตรวจสอบ Profile Avatar (แสดงเฉพาะตอนล็อกอินอยู่จริง)
            let profileEls = document.querySelectorAll(
                "div[aria-label='Your profile'], div[aria-label='โปรไฟล์ของคุณ'], " +
                "svg[aria-label='Your profile'], svg[aria-label='โปรไฟล์ของคุณ'], " +
                "a[href*='/me/'], [aria-label*='Account controls and settings'], " +
                "[aria-label*='การควบคุมและการตั้งค่าบัญชี']"
            );
            res.has_profile_avatar = (profileEls.length > 0);

            // 2. ตรวจสอบฟอร์ม Login / Password input
            let emailInputs = document.querySelectorAll("input[name='email'], input[id='email']");
            let passInputs = document.querySelectorAll("input[name='pass'], input[id='pass'], input[type='password']");
            let loginButtons = document.querySelectorAll("#loginbutton, button[name='login'], button[data-testid='royal_login_button']");
            res.has_login_form = (emailInputs.length > 0 && passInputs.length > 0) || (loginButtons.length > 0);

            // 3. ตรวจสอบปุ่มหรือข้อความ Continue / ดำเนินการต่อในชื่อ...
            let buttons = Array.from(document.querySelectorAll('button, div[role="button"], a[role="button"], span[role="button"]'));
            for (let b of buttons) {
                let t = (b.innerText || b.textContent || '').trim().toLowerCase();
                if (t.startsWith('continue as') || t.startsWith('ดำเนินการต่อในชื่อ') || t.startsWith('ดำเนินการต่อในฐานะ') || t.startsWith('log in as') || t.startsWith('เข้าสู่ระบบในชื่อ') || t === 'continue' || t === 'ดำเนินการต่อ') {
                    res.has_continue_prompt = true;
                    res.continue_button_text = t;
                    break;
                }
            }

            // 4. ตรวจสอบข้อความบนหน้าเว็บ (Body Text)
            let bodyText = (document.body ? (document.body.innerText || document.body.textContent || "") : "").toLowerCase();
            if (bodyText.includes("continue as") || bodyText.includes("ดำเนินการต่อในชื่อ") || bodyText.includes("ดำเนินการต่อในฐานะ") || bodyText.includes("log in as")) {
                res.has_continue_prompt = true;
            }
            if (bodyText.includes("recent logins") || bodyText.includes("การเข้าสู่ระบบล่าสุด") || bodyText.includes("คลิกรูปภาพของคุณ") || bodyText.includes("click your picture") || bodyText.includes("ไม่ใช่คุณใช่ไหม") || bodyText.includes("not you?")) {
                res.has_recent_logins = true;
            }
            if (bodyText.includes("session expired") || bodyText.includes("เซสชั่นหมดอายุ") || bodyText.includes("please log in again") || bodyText.includes("โปรดเข้าสู่ระบบอีกครั้ง")) {
                res.has_session_expired = true;
            }

            // 5. ตรวจสอบปุ่ม Log In ของโหมด Guest ที่มุมขวาบน/แถบนำทาง (เมื่อไม่มี profile avatar)
            let guestLoginLinks = document.querySelectorAll("a[href*='/login/'], a[href*='login.php'], [aria-label='Log In'], [aria-label='เข้าสู่ระบบ'], [aria-label='Log in']");
            res.has_guest_login_button = (guestLoginLinks.length > 0);

            return res;
        """) or {}

        is_logged_out = False
        reason = ""

        # ลองกดปุ่ม "Continue as..." อัตโนมัติ (เผื่อเซสชั่นกู้คืนได้ด้วย 1-Click Confirmation)
        if dom_status.get("has_continue_prompt"):
            try:
                clicked = driver.execute_script("""
                    let buttons = Array.from(document.querySelectorAll('button, div[role="button"], a[role="button"], span[role="button"]'));
                    let target = buttons.find(b => {
                        let t = (b.innerText || b.textContent || '').trim().toLowerCase();
                        return t.startsWith('continue as') || t.startsWith('ดำเนินการต่อในชื่อ') || t.startsWith('ดำเนินการต่อในฐานะ');
                    });
                    if (target) {
                        target.click();
                        return true;
                    }
                    return false;
                """)
                if clicked:
                    time.sleep(3)
                    has_prof_after = driver.execute_script("""
                        return document.querySelectorAll("div[aria-label='Your profile'], div[aria-label='โปรไฟล์ของคุณ'], a[href*='/me/']").length > 0;
                    """)
                    if has_prof_after:
                        print("  ✨ [Facebook Session] กู้คืนเซสชั่นสำเร็จอัตโนมัติจากการคลิกปุ่ม 'Continue as...'")
                        return False
            except Exception:
                pass

        # 1. URL ถูก Redirect ไปหน้า Login / Checkpoint / Recover
        if any(k in current_url for k in ("/login", "/checkpoint", "/recover", "login_attempt", "two_factor")):
            is_logged_out = True
            reason = f"ถูก Redirect ไปยังหน้า Login/Checkpoint ({driver.current_url})"

        # 2. ตรวจพบหน้าต่าง / ข้อความ 'Continue as [Name]' / 'ดำเนินการต่อในชื่อ...'
        elif dom_status.get("has_continue_prompt"):
            is_logged_out = True
            btn_txt = dom_status.get("continue_button_text") or "Continue as..."
            reason = f"ตรวจพบหน้าต่างยืนยันตัวตน '{btn_txt}' (เซสชั่นหมดอายุ ต้องกดยืนยันตัวตน)"

        # 3. ตรวจพบหน้า 'Recent Logins' / 'การเข้าสู่ระบบล่าสุด'
        elif dom_status.get("has_recent_logins"):
            is_logged_out = True
            reason = "ตรวจพบหน้าต่าง 'Recent Logins / การเข้าสู่ระบบล่าสุด' (เซสชั่นหลุด บัญชีถูกตัดออกจากระบบ)"

        # 4. ตรวจพบข้อความ 'Session Expired' / 'เซสชั่นหมดอายุ'
        elif dom_status.get("has_session_expired"):
            is_logged_out = True
            reason = "ตรวจพบข้อความ 'Session Expired / เซสชั่นหมดอายุ'"

        # 5. หน้าเว็บแสดงฟอร์ม Login ชัดเจน (มีช่องใส่ Email/Pass หรือปุ่มเข้าสู่ระบบ) และไม่มี Profile Avatar
        elif dom_status.get("has_login_form") and not dom_status.get("has_profile_avatar"):
            is_logged_out = True
            reason = "หน้าเว็บแสดงฟอร์มเข้าสู่ระบบ (Email/Password) แทนที่จะเป็นโปรไฟล์ที่ล็อกอินไว้"

        # 6. Title ของหน้าเว็บเป็น 'เข้าสู่ระบบ Facebook' หรือ 'Log in to Facebook'
        elif any(k in title_lower for k in ("log in to facebook", "เข้าสู่ระบบ facebook", "facebook – log in", "facebook - เข้าสู่ระบบ")) and not dom_status.get("has_profile_avatar"):
            is_logged_out = True
            reason = f"Title ของหน้าเว็บระบุว่าต้องเข้าสู่ระบบ ({driver.title})"

        # 7. ตรวจสอบคุกกี้เซสชั่น
        else:
            cookies = driver.get_cookies()
            has_c_user = any(c.get("name") == "c_user" for c in cookies)
            has_xs = any(c.get("name") == "xs" for c in cookies)
            if not has_c_user or not has_xs:
                if dom_status.get("has_guest_login_button") and not dom_status.get("has_profile_avatar"):
                    is_logged_out = True
                    reason = f"ไม่พบคุกกี้เซสชั่นที่สมบูรณ์ (c_user={has_c_user}, xs={has_xs}) และหน้าเว็บแสดงสถานะ Guest"

        if is_logged_out:
            # ตรวจสอบว่าเปิดใช้งานระบบ Auto Re-Login ไว้หรือไม่
            if auto_relogin and is_facebook_auto_login_configured():
                print("  🔄 [Facebook Session] ตรวจพบเซสชั่นหลุด กำลังเริ่มกระบวนการ Auto Re-Login อัตโนมัติ...")
                if attempt_facebook_auto_relogin():
                    print(f"  ✨ [Facebook Session] กู้คืนเซสชั่นสำเร็จ! กำลังเชื่อมต่อหน้าเป้าหมายด้วยบัญชีล็อกอิน: {target_url}")
                    try:
                        driver.delete_all_cookies()
                        driver.get("https://www.facebook.com")
                        time.sleep(1)
                        for ck in _LATEST_AUTH_COOKIES:
                            try:
                                driver.add_cookie(ck)
                            except Exception:
                                pass
                        driver.get(target_url)
                        time.sleep(3)
                        return False  # Not logged out anymore! Continue crawling
                    except Exception as cookie_err:
                        print(f"  ⚠️ [Facebook Session] เกิดข้อผิดพลาดขณะโหลดคุกกี้ใหม่ลง Worker: {cookie_err}")

            if not _WARNED_LOGGED_OUT_THIS_RUN or not is_facebook_logged_out():
                print("\n  ==================================================================")
                print(f"  ⚠️ [Facebook Session Logged Out] บัญชี Facebook ของคุณหลุดการล็อกอิน!")
                print(f"  🔍 สาเหตุ: {reason}")
                print(f"  👉 กรุณารันคำสั่ง: python login_facebook.py เพื่อเข้าสู่ระบบ Facebook ใหม่อีกครั้ง")
                print(f"  💡 สลับเป็นโหมด Clean Session (เหมือน Incognito) ให้อัตโนมัติ เพื่อให้ crawler ยังทำงานต่อไปได้")
                print("  ==================================================================\n")
                _WARNED_LOGGED_OUT_THIS_RUN = True
                set_facebook_logged_out(True)
                set_facebook_blocked_this_round(True)

            driver.delete_all_cookies()
            driver.get(target_url)
            time.sleep(3)
            dismiss_login_popup(driver)
            return True

    except Exception:
        pass
    return False


def check_and_handle_temporarily_blocked(driver: webdriver.Chrome, target_url: str) -> bool:
    """
    ตรวจสอบว่าบัญชี Facebook ที่ Login ไว้ติด Action Block ('You’re Temporarily Blocked') หรือโดนจำกัดสิทธิ์บน watch/ หรือไม่
    หากติดบล็อก จะแจ้งเตือน ล้าง cookies เปิดหน้าเว็บแบบ Unauthenticated (เหมือน Incognito)
    และตั้งค่าให้ crawler ช่องอื่นๆ ในรอบนี้สลับใช้ Clean Session ทันทีโดยอัตโนมัติ
    """
    try:
        source_lower = driver.page_source.lower()
        is_blocked = False
        reason = ""

        # คำหรือข้อความบ่งชี้การโดนบล็อก / Rate Limit / จำกัดการเข้าถึง (รองรับทั้งภาษาไทยและอังกฤษ ทุกรูปแบบ)
        if any(k in source_lower for k in (
            "temporarily blocked",
            "คุณถูกบล็อกชั่วคราว",
            "ถูกบล็อกชั่วคราว",
            "you're temporarily blocked",
            "you’re temporarily blocked",
            "you’ve been temporarily blocked",
            "action blocked",
            "ถูกบล็อกการกระทำ",
            "we limit how often",
            "เราจำกัดความถี่",
            "try again later",
            "โปรดลองอีกครั้งในภายหลัง"
        )):
            is_blocked = True
            reason = "ตรวจพบข้อความ 'You’re Temporarily Blocked' หรือข้อความจำกัดความถี่จาก Facebook"
        elif "this content isn't available right now" in source_lower or "เนื้อหานี้ไม่พร้อมใช้งานในขณะนี้" in source_lower:
            is_blocked = True
            reason = "ตรวจพบข้อความ 'This content isn\'t available right now / เนื้อหานี้ไม่พร้อมใช้งานในขณะนี้'"

        if is_blocked:
            if not is_facebook_blocked_this_round():
                print("\n  ==================================================================")
                print(f"  ⚠️ [Facebook Action Block] บัญชี Facebook ที่ Login ไว้ติด Action Block / ถูกจำกัดการเข้าถึง!")
                print(f"  🔍 สาเหตุ: {reason}")
                print(f"  💡 สลับเป็นโหมด Clean Session (เหมือน Incognito) ให้กับทุกช่องในรอบนี้ เพื่อพักบัญชีและเพิ่มความเร็ว...")
                print("  ==================================================================\n")
                set_facebook_blocked_this_round(True)
            driver.delete_all_cookies()
            driver.get(target_url)
            time.sleep(3)
            dismiss_login_popup(driver)
            return True
    except Exception:
        pass
    return False


def scrape_live_videos(
    page_url: str = "https://www.facebook.com/watch/ThaiPBS/",
    max_scrolls: int = 20,
    load_wait_seconds: int = 5,
    debug: bool = False,
    check_fallback: bool = True,
    channel_name: Optional[str] = None,
    program_titles: Optional[List[str]] = None
) -> List[Dict[str, str]]:
    """
    Crawl ข้อมูลวิดีโอจาก Facebook:
    1. ตรวจสอบความจำเป็นในการใช้ Session ล็อกอินจาก facebook_login_targets.json
    2. ตรวจสอบหน้า Timeline ของเพจ (https://www.facebook.com/<PageName>/)
    3. ตรวจสอบหน้า Watch Grid / Videos
    4. Fallback ไปยัง live_videos เมื่อจำเป็น
    """
    need_login, login_reason = should_use_facebook_login(
        channel_name=channel_name,
        program_titles=program_titles,
        page_url=page_url
    )
    if need_login:
        if is_facebook_logged_out():
            print(f"  ⚠️ [Facebook Session] บัญชี Facebook หลุดการล็อกอิน -> สลับใช้ Clean Session Guest แทน (รัน 'python login_facebook.py' เพื่อเข้าสู่ระบบ)")
        elif is_facebook_blocked_this_round():
            print(f"  ⚠️ [Facebook Session] บัญชี Facebook ติด Action Block ในรอบนี้ -> สลับใช้ Clean Session Guest แทน")
        else:
            print(f"  🔑 [Facebook Session] ใช้บัญชี Facebook ที่ล็อกอินไว้ ({login_reason})")
    else:
        print(f"  👤 [Facebook Session] ใช้ Clean Session Guest ({login_reason})")

    driver = create_driver(headless=True, force_clean=(not need_login))
    video_dict: Dict[str, Dict[str, object]] = {}

    try:
        primary_url = normalize_facebook_page_url(page_url)
        page_name = extract_facebook_page_name(primary_url)

        # 1. ตรวจสอบหน้า Timeline ของเพจ (https://www.facebook.com/<PageName>/)
        # บน Facebook ปัจจุบัน โพสต์บน Timeline จะระบุชื่อรายการและคำอธิบาย (Description) สดใหม่ที่สุด
        # รวมถึงเมื่อสตรีมยาวต่อเนื่องแล้วเปลี่ยนช่วงรายการ (เช่น สารพันลั่นทุ่ง -> สถานีประชาชน)
        if page_name:
            timeline_url = f"https://www.facebook.com/{page_name}/" if not page_name.isdigit() else f"https://www.facebook.com/profile.php?id={page_name}"
            if timeline_url.rstrip("/") != primary_url.rstrip("/"):
                print(f"[Facebook Crawler] กำลังตรวจสอบหน้า Timeline ของเพจ: {timeline_url}")
                try:
                    driver.get(timeline_url)
                    time.sleep(load_wait_seconds)
                    if need_login:
                        if not check_and_handle_logged_out(driver, timeline_url):
                            check_and_handle_temporarily_blocked(driver, timeline_url)
                            dismiss_login_popup(driver)
                    else:
                        dismiss_login_popup(driver)
                    _extract_videos_from_current_page(driver, video_dict, max_scrolls=min(max_scrolls, 5), scroll_delay=0.8)
                except Exception as e:
                    print(f"[Facebook Crawler] ตรวจสอบหน้า Timeline ไม่สำเร็จ: {e}")

        # 2. ตรวจสอบหน้าหลัก (Watch Grid / Videos)
        print(f"[Facebook Crawler] กำลังเปิดหน้าเว็บหลัก: {primary_url}")
        driver.get(primary_url)
        print(f"[Facebook Crawler] รอให้หน้าเว็บโหลดเนื้อหา ({load_wait_seconds} วินาที)...")
        time.sleep(max(3, load_wait_seconds - 1))
        debug_shot_path = os.path.join(os.getcwd(), "debug_facebook_after_close.png") if debug else None
        if need_login:
            if not check_and_handle_logged_out(driver, primary_url):
                check_and_handle_temporarily_blocked(driver, primary_url)
                dismiss_login_popup(driver, debug_screenshot_path=debug_shot_path)
        else:
            dismiss_login_popup(driver, debug_screenshot_path=debug_shot_path)

        _extract_videos_from_current_page(driver, video_dict, max_scrolls=max_scrolls)

        # 3. Fallback: หากยังไม่พบ Ongoing Live ให้ลองเปิดหน้า /live_videos/
        has_ongoing = any(v.get("is_ongoing_live") for v in video_dict.values())
        if not has_ongoing and check_fallback:
            alt_url = get_alternative_page_url(primary_url)
            if alt_url and alt_url.rstrip("/") != primary_url.rstrip("/"):
                print(f"[Facebook Crawler] ไม่พบ Ongoing Live ลองตรวจสอบหน้าสำรอง: {alt_url}")
                try:
                    driver.get(alt_url)
                    time.sleep(max(3, load_wait_seconds - 1))
                    if need_login:
                        if not check_and_handle_logged_out(driver, alt_url):
                            check_and_handle_temporarily_blocked(driver, alt_url)
                            dismiss_login_popup(driver)
                    else:
                        dismiss_login_popup(driver)
                    _extract_videos_from_current_page(driver, video_dict, max_scrolls=min(max_scrolls, 8), scroll_delay=0.8)
                except Exception as e:
                    print(f"[Facebook Crawler] ตรวจสอบหน้าสำรองไม่สำเร็จ: {e}")

        return list(video_dict.values())
    finally:
        driver.quit()


# Facebook title มักมีรูปแบบไม่คงที่ เช่น '🔴[Live] 10:00 #ชื่อรายการ (7 ส.ค. 69)' หรือไม่มี
# เวลานำหน้าเลยก็ได้ '🔴[Live] #ชื่อรายการ (7 ส.ค. 69)' ใช้ดึงเฉพาะชื่อรายการหลักหลัง '#'
# จนกว่าจะเจอ space หรือวงเล็บเปิด '(' เพื่อตัดปัญหา prefix/suffix ที่แปรผัน (เวลา, [Live], อีโมจิ)
FB_HASHTAG_TITLE_REGEX = re.compile(r"#([^(\s]+)")


def _score_title_match(
    card_text: str, 
    clean_search_title: str, 
    sig_words: List[str], 
    desc_text: str = ""
) -> Tuple[bool, int, str]:
    """
    ตรวจสอบว่าชื่อรายการ/keyword ปรากฏอยู่ใน card_text (Title) หรือ desc_text (Description) หรือไม่
    พร้อมให้คะแนนความมั่นใจ
    ใช้ร่วมกันทั้งการจับคู่แบบปกติ (เช็ควันที่) และแบบ fallback (เช็ค LIVE badge)
    คืนค่า (is_matched, score, match_reason)
    """
    def _evaluate_text(text: str, is_desc: bool = False) -> Tuple[bool, int, str]:
        if not text:
            return False, 0, "none"
        norm_text = normalize_title_text(text)
        prefix = "desc" if is_desc else "title"

        # 1. ลองดึงชื่อรายการหลักจาก hashtag ก่อน (เช่น #ชื่อรายการ)
        hashtag_match = FB_HASHTAG_TITLE_REGEX.search(text)
        if hashtag_match:
            norm_hashtag_title = normalize_title_text(hashtag_match.group(1))
            if norm_hashtag_title and (
                norm_hashtag_title == clean_search_title
                or clean_search_title in norm_hashtag_title
                or norm_hashtag_title in clean_search_title
            ):
                score = 32 if is_desc else 35
                return True, score, f"{prefix}_hashtag"

        # 2. Substring matching แบบตรงไปตรงมา
        if clean_search_title in norm_text:
            score = 28 if is_desc else 30
            return True, score, f"{prefix}_exact"

        # 3. ตรวจสอบ Significant words
        matched_sig = [w for w in sig_words if normalize_title_text(w) in norm_text]
        kw_score = 20 if is_desc else 25
        low_score = 12 if is_desc else 15

        if len(sig_words) == 1 and matched_sig:
            return True, kw_score, f"{prefix}_keywords"
        if len(sig_words) == 2:
            # หากชื่อรายการมีคำสำคัญ 2 คำ (เช่น NATION FOCUS) ต้องตรงครบทั้ง 2 คำ 100% เท่านั้น
            if len(matched_sig) == 2:
                return True, kw_score, f"{prefix}_keywords"
            return False, 0, "none"
        if len(sig_words) >= 3:
            if len(matched_sig) >= len(sig_words):
                return True, kw_score, f"{prefix}_keywords"
            if len(matched_sig) >= len(sig_words) - 1:
                return True, low_score, f"{prefix}_keywords"

        return False, 0, "none"

    best_matched = False
    best_score = 0
    best_reason = "none"

    # ประเมินจาก Title ก่อน
    m_t, s_t, r_t = _evaluate_text(card_text, is_desc=False)
    if m_t:
        best_matched = True
        best_score = s_t
        best_reason = r_t

    # ประเมินจาก Description
    if desc_text:
        m_d, s_d, r_d = _evaluate_text(desc_text, is_desc=True)
        if m_d and s_d > best_score:
            best_matched = True
            best_score = s_d
            best_reason = r_d

    return best_matched, best_score, best_reason


def find_matching_video(
    videos: List[Dict[str, str]], 
    program_title: str, 
    broadcast_time: Optional[str] = None, 
    broadcast_date: Optional[str] = None,
    scheduled_dt: Optional[datetime] = None,
    alternative_titles: Optional[List[str]] = None
) -> Optional[Dict[str, str]]:
    """
    ค้นหาวิดีโอ Facebook ที่ตรงกับชื่อรายการ (Column C) หรือชื่อสำรอง (alternative_titles)
    กฎเกณฑ์การจับคู่:
    1. ตรวจสอบ 'วันที่' (เช่น '(7 ส.ค. 69)' หรือ '(6 ส.ค. 69)') ต้องตรงกับวันที่ที่ต้องการค้นหา (scheduled_dt) อย่างเคร่งครัด
       หาก Title หรือ Description ของวิดีโอบน Facebook มีวันที่ระบุอยู่แล้วไม่ตรงกัน จะถูกปฏิเสธทันที (ไม่ดึงข้ามวัน)
    2. ตรวจสอบชื่อรายการ (Title / Description Matching): ชื่อรายการหลัก หรือชื่อสำรอง หรือ Keyword สำคัญต้องปรากฏในการ์ดวิดีโอหรือคำอธิบาย
    3. ตรวจสอบเวลาออกอากาศ (เช่น 10:00, 10.30 น.)
    """
    if not program_title or not videos:
        return None
        
    search_candidates = []
    raw_primary = program_title.strip()
    clean_primary = normalize_title_text(raw_primary)
    if clean_primary:
        all_words = [w for w in re.split(r"[\s#\(\)\-_]+", raw_primary) if w]
        sig = [w for w in all_words if len(w) > 1 and normalize_title_text(w) not in COMMON_STOPWORDS]
        search_candidates.append({
            "raw": raw_primary,
            "clean": clean_primary,
            "sig_words": sig or all_words,
            "is_alt": False
        })

    if alternative_titles:
        for alt_raw in alternative_titles:
            if not alt_raw or not str(alt_raw).strip():
                continue
            alt_str = str(alt_raw).strip()
            alt_clean = normalize_title_text(alt_str)
            if not alt_clean or any(c["clean"] == alt_clean for c in search_candidates):
                continue
            all_words_alt = [w for w in re.split(r"[\s#\(\)\-_]+", alt_str) if w]
            sig_alt = [w for w in all_words_alt if len(w) > 1 and normalize_title_text(w) not in COMMON_STOPWORDS]
            search_candidates.append({
                "raw": alt_str,
                "clean": alt_clean,
                "sig_words": sig_alt or all_words_alt,
                "is_alt": True
            })

    if not search_candidates:
        return None

    # เวลาที่ต้องการค้นหา
    time_regex = None
    if broadcast_time:
        t_clean = broadcast_time.strip().replace("น.", "").replace("น", "").strip()
        if "-" in t_clean:
            t_clean = t_clean.split("-")[0].strip()
        t_clean = t_clean.replace(":", ".").strip()
        parts = t_clean.split(".")
        if len(parts) >= 2:
            h = int(parts[0])
            m = parts[1]
            time_regex = re.compile(rf"(?:0?{h})[.:]{m}", re.IGNORECASE)

    best_match = None
    highest_score = 0

    for video in videos:
        card_text = str(video.get("title") or "")
        desc_text = str(video.get("description") or "")

        # Fallback enrichment: หากวิดีโอมีข้อความสั้นหรือเป็นข้อความ Header Avatar (เช่น 'ช่อง8 is on Live')
        # และยังไม่ได้ถูกเติมข้อมูล ให้ดึง OpenGraph metadata เพิ่มเติม
        if (video.get("is_ongoing_live") or "is on live" in card_text.lower() or "followers" in desc_text.lower()) and not video.get("_og_enriched"):
            og_meta = fetch_facebook_og_metadata(video.get("url", ""))
            if og_meta.get("description"):
                og_d = og_meta["description"].strip()
                first_line = og_d.split("\n")[0].strip()
                if ("is on live" in card_text.lower() or len(card_text) < 15) and first_line:
                    card_text = first_line
                    video["title"] = first_line
                if len(og_d) > len(desc_text) or "followers" in desc_text.lower():
                    desc_text = og_d
                    video["description"] = og_d
            video["_og_enriched"] = True

        combined_text = f"{card_text} {desc_text}".strip()

        # 1. ตรวจสอบวันที่ (Strict Date Verification)
        if scheduled_dt:
            sched_day = scheduled_dt.day
            sched_month = scheduled_dt.month
            sched_year_be = gregorian_year_to_be_short(scheduled_dt.year)  # เช่น 2569 -> 69

            video_date = extract_thai_date_from_title(card_text)
            if video_date is None and desc_text:
                video_date = extract_thai_date_from_title(desc_text)

            if video_date is not None:
                v_day, v_month, v_year = video_date
                # หากวัน หรือ เดือนไม่ตรงกัน -> ปฏิเสธทันที (ห้ามดึงข้ามวัน)
                if v_day != sched_day or v_month != sched_month:
                    continue

                # หากระบุปีแล้วปีไม่ตรงกัน -> ปฏิเสธ
                if v_year is not None:
                    v_year_2digit = v_year % 100
                    if v_year_2digit != sched_year_be:
                        continue

        # ปฏิเสธคลิปตัดย้อนหลังที่มีการระบุความยาวคลิปชัดเจน (เช่น 0:56, 2:06, 7:07) และไม่ได้กำลังถ่ายทอดสด
        if video.get("is_clip", False) and not video.get("is_ongoing_live", False):
            continue

        # ตรวจสอบว่าเป็น Facebook Live จริงๆ (ไม่ใช่คลิปทั่วไป)
        # ต้องเป็นวิดีโอที่กำลัง LIVE อยู่ (is_ongoing_live), มาจากแท็บ live_videos (from_live_tab),
        # เป็นการถ่ายทอดสดแล้ว (was_live), หรือมีข้อความบ่งบอกการถ่ายทอดสด ('ถ่ายทอดสด', 'LIVE')
        is_live_candidate = (
            video.get("is_ongoing_live", False)
            or video.get("is_live", False)
            or video.get("from_live_tab", False)
            or video.get("was_live", False)
            or "ถ่ายทอดสด" in combined_text
            or bool(re.search(r'(?:^|[^a-z0-9])live(?:[^a-z0-9]|$)', combined_text, re.IGNORECASE))
        )
        if not is_live_candidate:
            continue

        # หากเป็นรายการ 'โหนกระแส' ต้องมีคำว่า "LIVE" ในชื่อวิดีโอหรือคำอธิบายเท่านั้น เพื่อป้องกันการจับคู่คลิป/ไฮไลท์ย้อนหลัง
        if "โหนกระแส" in raw_primary:
            if not (re.search(r'(?:^|[^a-z0-9])live(?:[^a-z0-9]|$)', combined_text, re.IGNORECASE) or video.get("is_ongoing_live", False)):
                continue

        # 2. ตรวจสอบชื่อรายการ (Title / Description Matching): ตรวจสอบชื่อหลักก่อน ตามด้วยชื่อสำรอง
        matched_candidate = None
        cand_matched = False
        best_cand_score = 0
        best_cand_reason = ""

        for cand in search_candidates:
            t_matched, t_score, t_reason = _score_title_match(
                card_text, cand["clean"], cand["sig_words"], desc_text=desc_text
            )
            if t_matched:
                adj_score = t_score if not cand["is_alt"] else (t_score - 1)
                if adj_score > best_cand_score:
                    best_cand_score = adj_score
                    cand_matched = True
                    matched_candidate = cand
                    best_cand_reason = f"alt:{cand['raw']} -> {t_reason}" if cand["is_alt"] else t_reason

        # หากชื่อรายการไม่ตรงเลย ข้ามไป (ไม่จับคู่มั่ว)
        if not cand_matched or matched_candidate is None:
            continue

        score = best_cand_score
        match_reason = best_cand_reason

        # ให้คะแนนพิเศษสูงมากแก่วิดีโอที่กำลัง LIVE อยู่จริง ณ ขณะนี้ (+50) หรือเป็นการถ่ายทอดสด (+10)
        if video.get("is_ongoing_live", False) or video.get("is_live", False):
            score += 50
        elif video.get("from_live_tab", False) or video.get("was_live", False):
            score += 10

        # ตรวจสอบ relative time และวันที่ (Previous Day / Yesterday Rejection)
        # กฎเหล็ก: หากรายการในผังมีกำหนดการเป็น 'วันนี้' แต่วิดีโอนี้มาจากเมื่อวาน หรือวันก่อนหน้า
        # ต้องปฏิเสธทันที (ห้ามจับคู่วิดีโอของเมื่อวานให้รายการของวันนี้เด็ดขาด)
        time_text = video.get("time_text", "")
        minutes_ago = parse_relative_time_to_minutes(time_text)

        if scheduled_dt:
            is_today = (scheduled_dt.date() == datetime.now(ZoneInfo("Asia/Bangkok")).date())
            if is_today:
                # 1) ตรวจสอบจาก time_text
                if time_text:
                    t_lower = time_text.lower()
                    if any(k in t_lower for k in ("เมื่อวาน", "yesterday", "สัปดาห์", "week", "เดือน", "month", "ปี", "year")):
                        continue
                    if re.search(r'\b(?:\d+|หนึ่ง|1)\s*(?:วัน|d|day|days|สัปดาห์|week|เดือน|month|ปี|year)(?:ที่แล้ว|ago)?\b', t_lower):
                        continue

                # 2) ตรวจสอบจาก minutes_ago
                if minutes_ago is not None:
                    stream_start_dt = datetime.now(ZoneInfo("Asia/Bangkok")) - timedelta(minutes=minutes_ago)
                    # หากเวลาเริ่มสตรีมเป็นวันก่อนหน้า (ก่อน 00:00 ของวันนี้) -> ปฏิเสธทันที
                    if stream_start_dt.date() < scheduled_dt.date():
                        continue

                # 3) ตรวจสอบจาก combined_text / desc_text
                if re.search(r'\b(?:\d+\s*(?:day|week|month|year)s?|a\s*(?:day|week|month|year))\s*ago\b|(?:\d+|หนึ่ง|1)\s*(?:วัน|สัปดาห์|เดือน|ปี)ที่แล้ว|\b(?:yesterday|เมื่อวาน|เมื่อวานนี้)\b', combined_text, re.IGNORECASE):
                    if not video.get("is_ongoing_live", False):
                        continue

        # ตรวจสอบความสอดคล้องของเวลาออกอากาศ (Stream Start Time Consistency Check)
        if minutes_ago is not None and scheduled_dt:
            stream_start_dt = datetime.now(ZoneInfo("Asia/Bangkok")) - timedelta(minutes=minutes_ago)
            # gap_mins = เวลาผัง - เวลาเริ่มสตรีมจริง (บวกหมายถึงสตรีมเริ่มก่อนเวลาผัง)
            gap_mins = (scheduled_dt - stream_start_dt).total_seconds() / 60

            # กฎเหล็ก: หากวิดีโอ 'ไม่ได้กำลัง LIVE อยู่จริง ณ ขณะนี้' (เป็นวิดีโอที่จบไปแล้ว)
            # แต่วิดีโอนี้เริ่มก่อนเวลาผังออกอากาศเกิน 45 นาที (เช่น ผัง 12:25 แต่วิดีโอนี้เริ่ม 11:30 หรือก่อนหน้านั้น และจบไปแล้ว)
            # ย่อมเป็นรายการรอบก่อนหน้าที่จบไปแล้ว ไม่ใช่รายการของสล็อตนี้เด็ดขาด!
            if not video.get("is_ongoing_live", False):
                if gap_mins > 45:
                    continue  # เริ่มก่อนผังเกิน 45 นาที และจบแล้ว -> ปฏิเสธทันที
                if gap_mins < -180:
                    continue  # เริ่มหลังเวลาผังเกิน 3 ชั่วโมง -> ปฏิเสธทันที

            # หากวิดีโอนี้กำลัง LIVE อยู่จริง (Ongoing Live):
            if video.get("is_ongoing_live", False):
                if -20 <= gap_mins <= 20:
                    score += 20
                elif gap_mins > 20:
                    if not any(c["clean"] in normalize_title_text(combined_text) for c in search_candidates):
                        continue
                    else:
                        score += 5
            else:
                if -30 <= gap_mins <= 30:
                    score += 15
                else:
                    score -= 10

        # 3. ตรวจสอบเวลาออกอากาศ (+10 คะแนน)
        if time_regex and (time_regex.search(card_text) or (desc_text and time_regex.search(desc_text))):
            score += 10

        # ปรับคะแนนระหว่าง Main Stream กับ Big Sign / ภาษามือ / Vertical
        raw_title_lower = raw_primary.lower()
        has_sign_request = any(k in raw_title_lower for k in ("big sign", "bigsign", "ภาษามือ", "vertical"))
        lower_combined = combined_text.lower()
        is_sign_stream = any(k in lower_combined for k in ("big sign", "bigsign", "ภาษามือ", "vertical"))

        if has_sign_request:
            if is_sign_stream:
                score += 5
        else:
            if is_sign_stream:
                score -= 3
            else:
                score += 2

        if score > highest_score:
            highest_score = score
            best_match = dict(video)
            best_match["match_reason"] = match_reason

    if best_match is not None:
        if "desc" in best_match.get("match_reason", "") or "alt:" in best_match.get("match_reason", ""):
            print(f"[Facebook Crawler] ℹ️ พบวิดีโอ (Reason: {best_match.get('match_reason')}) สำหรับรายการ '{program_title}'")
        return best_match

    # 4. Fallback: หาก Thai date ใน title/description ตรวจสอบไม่ผ่าน/ไม่พบเลย (best_match ยังเป็น None)
    # ให้ใช้ badge "LIVE" (กำลังถ่ายทอดสดอยู่จริง ณ ขณะนี้) แทนการเช็ควันที่
    # โดยยังต้องจับคู่ชื่อรายการ/keyword กับ title หรือ description ให้ผ่านเหมือนเดิม ก่อนจะยืนยันว่าไม่พบจริงๆ
    if scheduled_dt is not None:
        fallback_match = None
        fallback_score = 0
        for video in videos:
            if video.get("is_clip", False) and not video.get("is_ongoing_live", False):
                continue
            # ต้องเป็น Ongoing Live ที่กำลังถ่ายทอดสดอยู่จริง ณ ขณะนี้เท่านั้น
            if not video.get("is_ongoing_live", False):
                continue

            card_text = str(video.get("title") or "")
            desc_text = str(video.get("description") or "")
            combined_text = f"{card_text} {desc_text}".strip()

            # หากเป็นรายการ 'โหนกระแส' ต้องมีคำว่า "LIVE" ในชื่อวิดีโอหรือคำอธิบายเท่านั้น เพื่อป้องกันการจับคู่คลิป/ไฮไลท์ย้อนหลัง
            if "โหนกระแส" in raw_primary:
                if not (re.search(r'(?:^|[^a-z0-9])live(?:[^a-z0-9]|$)', combined_text, re.IGNORECASE) or video.get("is_ongoing_live", False)):
                    continue

            matched_candidate = None
            cand_matched = False
            best_cand_score = 0
            best_cand_reason = ""

            for cand in search_candidates:
                t_matched, t_score, t_reason = _score_title_match(
                    card_text, cand["clean"], cand["sig_words"], desc_text=desc_text
                )
                if t_matched:
                    adj_score = t_score if not cand["is_alt"] else (t_score - 1)
                    if adj_score > best_cand_score:
                        best_cand_score = adj_score
                        cand_matched = True
                        matched_candidate = cand
                        best_cand_reason = f"alt:{cand['raw']} -> {t_reason}" if cand["is_alt"] else t_reason

            if not cand_matched or matched_candidate is None:
                continue

            score = best_cand_score
            match_reason = best_cand_reason

            if time_regex and (time_regex.search(card_text) or (desc_text and time_regex.search(desc_text))):
                score += 10

            raw_title_lower = raw_primary.lower()
            has_sign_request = any(k in raw_title_lower for k in ("big sign", "bigsign", "ภาษามือ", "vertical"))
            lower_combined = combined_text.lower()
            is_sign_stream = any(k in lower_combined for k in ("big sign", "bigsign", "ภาษามือ", "vertical"))

            if has_sign_request:
                if is_sign_stream:
                    score += 5
            else:
                if is_sign_stream:
                    score -= 3
                else:
                    score += 2

            if score > fallback_score:
                fallback_score = score
                fallback_match = dict(video)
                fallback_match["match_reason"] = match_reason

        if fallback_match is not None:
            if "desc" in fallback_match.get("match_reason", "") or "alt:" in fallback_match.get("match_reason", ""):
                print(f"[Facebook Crawler] ℹ️ พบวิดีโอ LIVE (Reason: {fallback_match.get('match_reason')}) สำหรับรายการ '{program_title}'")
            else:
                print(
                    "[Facebook Crawler] ตรวจสอบวันที่ไทยใน title/description ไม่พบ/ไม่ตรง "
                    "แต่พบวิดีโอที่กำลัง LIVE และชื่อรายการตรงกัน จึงใช้ผลลัพธ์นี้แทน"
                )
            return fallback_match

    return None
