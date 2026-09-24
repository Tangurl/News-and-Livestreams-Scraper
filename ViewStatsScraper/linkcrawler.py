import os
import sys
import time
import json
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Union
from concurrent.futures import ThreadPoolExecutor, as_completed
from zoneinfo import ZoneInfo

# รองรับการแสดงผลภาษาไทยบน Windows Terminal
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# นำเข้าฟังก์ชันจาก modules/facebook.py, modules/youtube.py, modules/x.py และ modules/sheets_writer.py
try:
    from modules.facebook import (
        scrape_live_videos,
        find_matching_video,
        disable_all_facebook_login,
        is_all_facebook_login_disabled
    )
    from modules.youtube import scrape_youtube_streams, find_matching_youtube_video
    from modules.x import scrape_x_live_videos, find_matching_x_video
except ImportError:
    scrape_live_videos = None
    find_matching_video = None
    disable_all_facebook_login = None
    is_all_facebook_login_disabled = None
    scrape_youtube_streams = None
    find_matching_youtube_video = None
    scrape_x_live_videos = None
    find_matching_x_video = None
from modules.sheets_writer import (
    NOT_FOUND_DISPLAY,
    fetch_schedule_rows,
    fetch_all_channel_schedules,
    fetch_link_config,
    write_row_result,
    write_batch_row_results,
)
from modules.cache_manager import (
    save_crawled_url,
    get_crawled_url,
    save_schedules_cache,
    load_schedules_cache,
)
from modules.link_resolver import resolve_target_urls_for_program
from modules.utilities import is_thaipbs_channel, reset_facebook_blocked_status

_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ROOT_ENV = os.path.join(_ROOT_DIR, ".env")

def load_env_root():
    if not os.path.isfile(_ROOT_ENV):
        sys.exit(f"❌ [Config Error] Root .env file not found at: {_ROOT_ENV}\nA .env file at the project root is strictly required. Halting execution.")
    try:
        from dotenv import load_dotenv
        load_dotenv(_ROOT_ENV, override=True)
    except ImportError:
        pass
    with open(_ROOT_ENV, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip()
                if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                    v = v[1:-1]
                os.environ.setdefault(k, v)

load_env_root()
load_env_fallback = load_env_root


def parse_schedule_datetime(date_str: str, time_str: str) -> Optional[datetime]:
    """
    แปลงวันที่ (A) และเวลา (B) จาก Google Sheet ให้เป็น datetime object
    รองรับหลายรูปแบบ เช่น:
    - DD-MM-YY: 03-09-26, 03/09/26, 03-09-69 (พ.ศ.)
    - DD-MM-YYYY / YYYY-MM-DD: 03-09-2026, 2026-09-03
    - Time: 05:00, 05.00, 10.30, 12.00-12.30 (ดึงเวลาเริ่มต้น)
    """
    try:
        date_clean = date_str.strip()
        time_clean = time_str.strip()

        # ปรับเวลา เช่น '05.00 น.', '12.00-12.30 น.'
        time_clean = time_clean.replace("น.", "").replace("น", "").strip()
        if "-" in time_clean:
            time_clean = time_clean.split("-")[0].strip()
        time_clean = time_clean.replace(".", ":")

        time_parts = time_clean.split(":")
        if len(time_parts) >= 2:
            hour = int(time_parts[0])
            minute = int(time_parts[1])
        else:
            return None

        # จัดการรูปแบบวันที่
        parsed_date = None
        date_clean = date_clean.replace("/", "-")
        date_parts = date_clean.split("-")

        if len(date_parts) == 3:
            p0, p1, p2 = int(date_parts[0]), int(date_parts[1]), int(date_parts[2])
            if p0 > 2400:  # 2569-08-07
                year, month, day = p0 - 543, p1, p2
            elif p2 > 2400:  # 07-08-2569
                year, month, day = p2 - 543, p1, p0
            elif p0 > 1900:  # 2026-08-07
                year, month, day = p0, p1, p2
            elif p2 > 1900:  # 07-08-2026
                year, month, day = p2, p1, p0
            else:
                # DD-MM-YY 2 หลัก เช่น 03-09-26 หรือ 03-09-69
                day, month = p0, p1
                if p2 >= 50:  # พ.ศ. เช่น 69 -> 2569 - 543 = 2026
                    year = (2500 + p2) - 543
                else:  # ค.ศ. เช่น 26 -> 2026
                    year = 2000 + p2

            parsed_date = datetime(year, month, day, hour, minute, tzinfo=ZoneInfo("Asia/Bangkok"))

        return parsed_date
    except Exception as e:
        print(f"[Warning] ไม่สามารถแปลงวันเวลา '{date_str} {time_str}': {e}")
        return None


def fetch_sheet_schedule(api_url: str, sheet: Optional[str] = None, token: Optional[str] = None) -> List[Dict]:
    """
    ดึงข้อมูลตารางเวลาและรายการ (A: วันที่, B: เวลา, C: ชื่อรายการ) พร้อมผลลัพธ์ที่เขียนกลับ
    ไปแล้ว (D: Facebook, E: YouTube, F: X, G: TikTok) ผ่าน Google Apps Script Web App
    """
    target_sh_text = f" (Sheet: {sheet})" if sheet else ""
    print(f"[Apps Script API] กำลังดึงข้อมูลตารางจาก: {api_url}{target_sh_text}")

    rows = fetch_schedule_rows(api_url=api_url, sheet=sheet, token=token)

    schedule_list = []
    for row in rows:
        date_val = str(row.get("date", "")).strip()
        time_val = str(row.get("time", "")).strip()
        title_val = str(row.get("title", "")).strip()

        # ข้ามแถวที่ไม่มีชื่อรายการ (Column C)
        if not title_val:
            continue

        sched_dt = parse_schedule_datetime(date_val, time_val)

        schedule_list.append({
            "row": row.get("row"),
            "date": date_val,
            "time": time_val,
            "title": title_val,
            "datetime": sched_dt,
            "facebook_url": str(row.get("facebook_url", "")).strip(),
            "youtube_url": str(row.get("youtube_url", "")).strip(),
            "x_url": str(row.get("x_url", "")).strip(),
            "tiktok_url": str(row.get("tiktok_url", "")).strip()
        })

    print(f"[Apps Script API] ดึงข้อมูลสำเร็จ: ทั้งหมด {len(schedule_list)} รายการ\n")
    return schedule_list


def seed_master_results_from_schedule(
    schedules: List[Dict],
    channel_name: Optional[str] = None,
    return_unsynced: bool = False
) -> Union[Dict[str, Dict], Tuple[Dict[str, Dict], List[Dict]]]:
    """
    Seed master_results จาก Google Sheet และ Local Cache (crawled_urls.json)
    เพื่อป้องกันไม่ให้โปรแกรม crawl ซ้ำเมื่อปิดและเปิดโปรแกรมใหม่ (reboot/restart):
    1. หากมีลิงก์ที่เคยค้นพบใน Local Cache จะนำมา seed ทันที
    2. หากใน Google Sheet มีลิงก์ (หรือผลลัพธ์ครบทุกแพลตฟอร์ม) และเวลาออกอากาศผ่านไปแล้ว จะนำมา seed
    3. ตรวจสอบรายการที่ Local Cache มีลิงก์จริง แต่ Google Sheet ยังว่าง (กรณีโปรแกรมถูกปิดก่อน Batch Sync) เพื่อนำไป Sync ทันที
    """
    master_results: Dict[str, Dict] = {}
    unsynced_items: List[Dict] = []
    system_now = datetime.now(ZoneInfo("Asia/Bangkok"))

    def _is_real_url(val: Optional[str]) -> bool:
        v = str(val or "").strip()
        return bool(v and v not in ("-", "NOT FOUND", NOT_FOUND_DISPLAY, ""))

    seeded_from_cache = 0
    seeded_from_sheet = 0

    for s in schedules:
        sched_dt = s.get("datetime")
        title = s.get("title", "")
        date_val = s.get("date", "")
        time_val = s.get("time", "")
        if not title:
            continue

        key = f"{date_val} {time_val}_{title}"

        # 1. ตรวจสอบข้อมูลจาก Local Cache (crawled_urls.json)
        cached = get_crawled_url(channel_name, date_val, time_val, title) if channel_name else None

        cached_fb = cached.get("facebook_url", "") if cached else ""
        cached_yt = cached.get("youtube_url", "") if cached else ""
        cached_x = cached.get("x_url", "") if cached else ""
        cached_tt = cached.get("tiktok_url", "") if cached else ""

        sheet_fb = str(s.get("facebook_url", "")).strip()
        sheet_yt = str(s.get("youtube_url", "")).strip()
        sheet_x = str(s.get("x_url", "")).strip()
        sheet_tt = str(s.get("tiktok_url", "")).strip()

        # เลือก URL จริงที่ดีที่สุด (Cache หรือ Sheet)
        final_fb = cached_fb if _is_real_url(cached_fb) else (sheet_fb if _is_real_url(sheet_fb) else "")
        final_yt = cached_yt if _is_real_url(cached_yt) else (sheet_yt if _is_real_url(sheet_yt) else "")
        final_x = cached_x if _is_real_url(cached_x) else (sheet_x if _is_real_url(sheet_x) else "")
        final_tt = cached_tt if _is_real_url(cached_tt) else (sheet_tt if _is_real_url(sheet_tt) else "-")

        # ตรวจสอบว่ามีลิงก์จริงที่เคยบันทึกไว้ใน Local Cache หรือไม่
        has_cached_link = bool(_is_real_url(final_fb) or _is_real_url(final_yt) or _is_real_url(final_x))

        # ตรวจสอบว่าใน Google Sheet เป็นรายการในอดีตที่ประมวลผลเสร็จสิ้นไปแล้ว (มีค่าครบ) หรือไม่
        is_sheet_completed = bool(
            sched_dt and sched_dt < system_now and sheet_fb and sheet_yt and sheet_x
        )

        # ตรวจสอบว่ามีลิงก์ที่ Local Cache มี แต่ Google Sheet ยังไม่มีหรือไม่ (ตกค้างจากการปิดโปรแกรมกลางคัน)
        sheet_missing_links = (
            (_is_real_url(final_fb) and not _is_real_url(sheet_fb)) or
            (_is_real_url(final_yt) and not _is_real_url(sheet_yt)) or
            (_is_real_url(final_x) and not _is_real_url(sheet_x))
        )
        if sheet_missing_links and s.get("row"):
            unsynced_items.append({
                "row": s.get("row"),
                "date": date_val,
                "time": time_val,
                "title": title,
                "facebook_url": final_fb if _is_real_url(final_fb) else (sheet_fb or NOT_FOUND_DISPLAY),
                "youtube_url": final_yt if _is_real_url(final_yt) else (sheet_yt or NOT_FOUND_DISPLAY),
                "x_url": final_x if _is_real_url(final_x) else (sheet_x or NOT_FOUND_DISPLAY),
                "tiktok_url": final_tt or "-",
                "last_checked": system_now.strftime('%Y-%m-%d %H:%M:%S')
            })

        if has_cached_link or is_sheet_completed:
            master_results[key] = {
                "row": s.get("row"),
                "date": date_val,
                "time": time_val,
                "search_string": title,
                "title": title,
                "facebook_url": final_fb if _is_real_url(final_fb) else "NOT FOUND",
                "youtube_url": final_yt if _is_real_url(final_yt) else "NOT FOUND",
                "x_url": final_x if _is_real_url(final_x) else "NOT FOUND",
                "tiktok_url": final_tt or "-",
                "fb_attempts": 0,
                "yt_attempts": 0,
                "x_attempts": 0
            }
            # อัปเดตใน schedule dict เพื่อให้ค่าในหน่วยความจำสอดคล้องกัน
            if _is_real_url(final_fb):
                s["facebook_url"] = final_fb
            if _is_real_url(final_yt):
                s["youtube_url"] = final_yt
            if _is_real_url(final_x):
                s["x_url"] = final_x
            if _is_real_url(final_tt):
                s["tiktok_url"] = final_tt

            if has_cached_link:
                seeded_from_cache += 1
            else:
                seeded_from_sheet += 1

    log_parts = []
    if seeded_from_cache > 0:
        log_parts.append(f"Local Cache: {seeded_from_cache} รายการ")
    if seeded_from_sheet > 0:
        log_parts.append(f"Google Sheet: {seeded_from_sheet} รายการ")
    if unsynced_items:
        log_parts.append(f"รอ Sync ขึ้น Sheet: {len(unsynced_items)} รายการ")
    ch_label = f" [{channel_name}]" if channel_name else ""
    if log_parts:
        print(f"📦 [Seed{ch_label}] โหลดรายการที่เคยค้นพบแล้ว: รวม {len(master_results)} รายการ ({', '.join(log_parts)})")
    else:
        print(f"📦 [Seed{ch_label}] ไม่มีรายการที่เคยประมวลผลไว้ล่วงหน้า")

    if return_unsynced:
        return master_results, unsynced_items
    return master_results


def process_due_schedules(
    schedules: List[Dict],
    facebook_url: str,
    youtube_url: str,
    x_url: str,
    page_wait_seconds_fb: int,
    page_wait_seconds_yt: int,
    page_wait_seconds_x: int,
    master_results: Dict[str, Dict],
    delay_minutes: int,
    script_api_url: str,
    channel_name: Optional[str] = None,
    tiktok_url: Optional[str] = None,
    current_only: bool = False,
    max_attempts: int = 1,
    script_api_token: Optional[str] = None,
    link_config: Optional[Dict] = None,
    channels_config: Optional[Dict] = None,
    skip_x: bool = False,
    skip_x_except_thaipbs: bool = False
) -> Tuple[List[Dict], List[Dict]]:
    """
    ตรวจสอบเงื่อนไขเวลาในลักษณะ Sliding Queue:
    - แบ่งรายการตามเวลาออกอากาศ + Delay 4 นาที
    - หาก current_only=True: ประมวลผลเฉพาะรายการล่าสุดที่กำลังออกอากาศอยู่ (past_items[-1]) ข้ามรายการในอดีตที่จบไปแล้ว
    - รายการในอนาคต (ไปหน้า 1 รายการ): รอเวลาและแสดงเวลานับถอยหลัง
    - หาก skip_x=True หรือ (skip_x_except_thaipbs=True และไม่ใช่ช่อง Thai PBS): จะข้ามการ Crawl X (Twitter) โดยอัตโนมัติ

    คืนค่า (updated_items, upcoming_items)
    """
    MAX_ATTEMPTS_PER_PLATFORM = max_attempts
    system_now = datetime.now(ZoneInfo("Asia/Bangkok"))
    should_skip_x = skip_x or (skip_x_except_thaipbs and not is_thaipbs_channel(channel_name))

    # กรองเฉพาะรายการที่มี datetime ถูกต้อง และเรียงตามลำดับเวลา
    valid_schedules = [s for s in schedules if s.get("datetime")]
    valid_schedules.sort(key=lambda x: x["datetime"])

    # คำนวณเวลาสิ้นสุดรายการ (end_time) ของแต่ละรายการในผัง
    # หากมีรายการถัดไป ให้ใช้เวลาเริ่มต้นของรายการถัดไปเป็นเวลาสิ้นสุด (ไม่เกิน 4 ชม.)
    # หากไม่มีรายการถัดไป ให้กำหนดความยาวรายการไว้ที่ 3 ชม.
    for idx, item in enumerate(valid_schedules):
        sched_dt = item["datetime"]
        if idx + 1 < len(valid_schedules) and valid_schedules[idx + 1].get("datetime"):
            next_dt = valid_schedules[idx + 1]["datetime"]
            diff_secs = (next_dt - sched_dt).total_seconds()
            if 0 < diff_secs <= 4 * 3600:
                end_dt = next_dt
            else:
                end_dt = sched_dt + timedelta(hours=3)
        else:
            end_dt = sched_dt + timedelta(hours=3)
        item["end_time"] = end_dt

    past_items = []
    upcoming_items = []

    for item in valid_schedules:
        sched_dt = item["datetime"]
        trigger_time = sched_dt + timedelta(minutes=delay_minutes)
        item_copy = {**item, "trigger_time": trigger_time, "end_time": item["end_time"]}

        if system_now >= trigger_time:
            past_items.append(item_copy)
        else:
            wait_seconds = max(0, int((trigger_time - system_now).total_seconds()))
            item_copy["wait_seconds"] = wait_seconds
            upcoming_items.append(item_copy)

    due_items_to_search = []
    active_current_item = None

    # ตรวจสอบรายการที่ถึงเวลาแล้ว
    if past_items:
        if current_only:
            # เลือกเฉพาะรายการที่กำลังออกอากาศอยู่จริง ณ ขณะนี้ (trigger_time <= system_now < end_time)
            active_items = [
                it for it in past_items
                if system_now < it.get("end_time", it["datetime"] + timedelta(hours=3))
            ]
            if active_items:
                active_current_item = active_items[-1]
                candidates_to_eval = [active_current_item]
            else:
                candidates_to_eval = []
        else:
            candidates_to_eval = past_items

        for cand in candidates_to_eval:
            key = f"{cand['date']} {cand['time']}_{cand['title']}"
            existing_res = master_results.get(key)
            if not existing_res:
                existing_res = {
                    "facebook_url": "NOT FOUND",
                    "youtube_url": "NOT FOUND",
                    "x_url": "NOT FOUND",
                    "fb_attempts": 0,
                    "yt_attempts": 0,
                    "x_attempts": 0
                }
                master_results[key] = existing_res

            # ตรวจสอบ Local Cache อีกครั้ง เผื่อมีลิงก์ที่เคยค้นพบในรอบก่อนหน้า/หลังจากรีสตาร์ทโปรแกรม
            if channel_name:
                cached = get_crawled_url(channel_name, cand["date"], cand["time"], cand["title"])
                if cached:
                    c_fb = cached.get("facebook_url")
                    c_yt = cached.get("youtube_url")
                    c_x = cached.get("x_url")
                    c_tt = cached.get("tiktok_url")
                    if c_fb and c_fb not in ("-", "NOT FOUND", NOT_FOUND_DISPLAY, "") and existing_res.get("facebook_url") in ("NOT FOUND", "", None):
                        existing_res["facebook_url"] = c_fb
                    if c_yt and c_yt not in ("-", "NOT FOUND", NOT_FOUND_DISPLAY, "") and existing_res.get("youtube_url") in ("NOT FOUND", "", None):
                        existing_res["youtube_url"] = c_yt
                    if c_x and c_x not in ("-", "NOT FOUND", NOT_FOUND_DISPLAY, "") and existing_res.get("x_url") in ("NOT FOUND", "", None):
                        existing_res["x_url"] = c_x
                    if c_tt and c_tt not in ("-", "NOT FOUND", NOT_FOUND_DISPLAY, "") and existing_res.get("tiktok_url") in ("NOT FOUND", "", None, "-"):
                        existing_res["tiktok_url"] = c_tt

            fb_url = existing_res.get("facebook_url", "NOT FOUND")
            yt_url = existing_res.get("youtube_url", "NOT FOUND")
            x_link_existing = existing_res.get("x_url", "NOT FOUND")

            has_fb = (fb_url and fb_url != "NOT FOUND")
            has_yt = (yt_url and yt_url != "NOT FOUND")
            has_x = should_skip_x or (x_link_existing and x_link_existing != "NOT FOUND")

            # 1. หากพบครบทุกแพลตฟอร์มแล้ว (FB, YT และ X หรือข้าม X) -> ข้ามการค้นหาได้เลย
            if has_fb and has_yt and has_x:
                continue

            # 2. หากรายการจบการออกอากาศแล้ว (system_now >= end_time) -> ข้ามได้เลย ไม่ต้องค้นหาต่อ
            is_ended = (system_now >= cand.get("end_time", cand["datetime"] + timedelta(hours=3)))
            if is_ended:
                continue

            # 3. หากรายการยังออกอากาศอยู่ และยังมี platform ที่ยังไม่พบ -> ให้ค้นหาต่อในรอบนี้
            due_items_to_search.append(cand)

    # แสดงสถานะคิวรอบเวลาปัจจุบัน
    ch_pfx = f"[{channel_name}] " if channel_name else ""
    print(f"\n" + "-"*70)
    if current_only:
        if active_current_item:
            k = f"{active_current_item['date']} {active_current_item['time']}_{active_current_item['title']}"
            res = master_results.get(k, {})
            fb = res.get("facebook_url", "NOT FOUND")
            yt = res.get("youtube_url", "NOT FOUND")
            x_link = res.get("x_url", "NOT FOUND")

            has_fb = (fb and fb != "NOT FOUND")
            has_yt = (yt and yt != "NOT FOUND")
            has_x = (x_link and x_link != "NOT FOUND")
            is_ended = (system_now >= active_current_item.get("end_time", active_current_item["datetime"] + timedelta(hours=3)))

            if has_fb and has_yt and (has_x or should_skip_x):
                status_str = "✅ มีลิงก์ครบแล้ว" + (" (FB & YT, ข้าม X)" if should_skip_x else " (FB, YT & X)") + " -> ข้ามไปรายการถัดไป"
            elif is_ended:
                status_str = "⏹️ รายการจบการออกอากาศแล้ว (บางแพลตฟอร์มไม่พบ) -> ข้ามไปรายการถัดไป"
            else:
                status_str = "🔄 กำลังค้นหาลิงก์สด (กำลังออกอากาศ)..."

            print(f"📺 {ch_pfx}รายการที่กำลังออกอากาศ: '{active_current_item['title']}' ({active_current_item['date']} {active_current_item['time']} น. แถว {active_current_item['row']}) -> {status_str}")

            def _platform_line(name: str, found: bool, url: str) -> str:
                if name.strip() == "X" and should_skip_x:
                    reason = "ยกเว้นเฉพาะ Thai PBS" if skip_x_except_thaipbs else "--skip-x"
                    return f"   • {name} : ข้ามการค้นหา ({reason})"
                if found:
                    return f"   • {name} : {url}"
                elif is_ended:
                    return f"   • {name} : NOT FOUND (รายการจบแล้ว)"
                else:
                    return f"   • {name} : ยังไม่พบ (จะตรวจสอบใหม่อีกครั้งในรอบถัดไปหากยังออกอากาศ)"

            print(_platform_line("Facebook", has_fb, fb))
            print(_platform_line("YouTube ", has_yt, yt))
            print(_platform_line("X       ", has_x, x_link))
        elif past_items:
            latest_past = past_items[-1]
            end_t_str = latest_past.get("end_time", latest_past["datetime"] + timedelta(hours=3)).strftime('%H:%M') + ' น.'
            print(f"📺 {ch_pfx}ขณะนี้ไม่มีรายการที่กำลังออกอากาศ (รายการล่าสุด '{latest_past['title']}' เวลา {latest_past['date']} {latest_past['time']} น. จบไปแล้วเมื่อ {end_t_str})")
        else:
            print(f"📋 {ch_pfx}ไม่มีรายการที่เริ่มออกอากาศแล้วในขณะนี้")
    elif past_items:
        latest_item = past_items[-1]
        k = f"{latest_item['date']} {latest_item['time']}_{latest_item['title']}"
        res = master_results.get(k, {})
        fb = res.get("facebook_url", "NOT FOUND")
        yt = res.get("youtube_url", "NOT FOUND")
        x_link = res.get("x_url", "NOT FOUND")

        has_fb = (fb and fb != "NOT FOUND")
        has_yt = (yt and yt != "NOT FOUND")
        has_x = (x_link and x_link != "NOT FOUND")
        is_ended = (system_now >= latest_item.get("end_time", latest_item["datetime"] + timedelta(hours=3)))

        if has_fb and has_yt and (has_x or should_skip_x):
            status_str = "✅ มีลิงก์ครบแล้ว" + (" (FB & YT, ข้าม X)" if should_skip_x else " (FB, YT & X)") + " -> ข้ามไปรายการถัดไป"
        elif is_ended:
            status_str = "⏹️ รายการจบการออกอากาศแล้ว (บางแพลตฟอร์มไม่พบ) -> ข้ามไปรายการถัดไป"
        else:
            status_str = "🔄 กำลังค้นหาลิงก์สด..."

        pending_count = len(due_items_to_search)
        print(f"📋 {ch_pfx}[Queue] รายการในผังที่ถึงเวลาแล้ว: {len(past_items)} รายการ | รอค้นหา: {pending_count} รายการ")
        print(f"📍 {ch_pfx}[ล่าสุด] แถว {latest_item['row']}: '{latest_item['title']}' ({latest_item['date']} {latest_item['time']}) -> {status_str}")

        def _platform_line(name: str, found: bool, url: str) -> str:
            if name.strip() == "X" and should_skip_x:
                reason = "ยกเว้นเฉพาะ Thai PBS" if skip_x_except_thaipbs else "--skip-x"
                return f"   • {name} : ข้ามการค้นหา ({reason})"
            if found:
                return f"   • {name} : {url}"
            elif is_ended:
                return f"   • {name} : NOT FOUND (รายการจบแล้ว)"
            else:
                return f"   • {name} : ยังไม่พบ (จะตรวจสอบใหม่อีกครั้งในรอบถัดไปหากยังออกอากาศ)"

        print(_platform_line("Facebook", has_fb, fb))
        print(_platform_line("YouTube ", has_yt, yt))
        print(_platform_line("X       ", has_x, x_link))
    else:
        print(f"📋 {ch_pfx}ไม่มีรายการที่เริ่มออกอากาศแล้วในขณะนี้")

    if upcoming_items:
        next_item = upcoming_items[0]
        w_sec = int(next_item["wait_seconds"])
        w_min = w_sec // 60
        w_rem_sec = w_sec % 60
        print(f"⏳ {ch_pfx}[รายการถัดไป] แถว {next_item['row']}: '{next_item['title']}' ({next_item['date']} {next_item['time']}) -> เริ่มค้นหา {next_item['trigger_time'].strftime('%H:%M:%S')} (อีก {w_min:02d} นาที {w_rem_sec:02d} วินาที)")
    print("-"*70)

    if not due_items_to_search:
        return [], upcoming_items

    print(f"\n" + "="*70)
    print(f"🔥 [Live Due] พบ {len(due_items_to_search)} รายการใน Queue ที่ถึงเวลาค้นหา (เวลาออกอากาศ + Delay {delay_minutes} นาที)")
    print(f"⏰ [System Time] {system_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)
    for it in due_items_to_search:
        print(f"  - แถว {it['row']}: '{it['title']}' (เวลา {it['date']} {it['time']})")

    # เตรียมสถานะการค้นหาของแต่ละรายการที่ถึงเวลา
    item_states = []
    for item in due_items_to_search:
        title = item["title"]
        time_str = item["time"]
        date_str = item["date"]
        sched_dt = item.get("datetime")
        row_num = item["row"]
        key = f"{date_str} {time_str}_{title}"

        # แก้ไข/ระบุเป้าหมาย URL สำหรับรายการนี้ (ตรวจสอบ Broadcast Override -> Channel Links -> Defaults)
        if channel_name and (link_config or channels_config):
            resolved = resolve_target_urls_for_program(
                channel_name=channel_name,
                program_title=title,
                channels_config=channels_config,
                link_config=link_config
            )
            item_fb_urls = resolved["facebook"] or ([facebook_url] if facebook_url else [])
            item_yt_urls = resolved["youtube"] or ([youtube_url] if youtube_url else [])
            item_x_urls = resolved["x"] or ([x_url] if x_url else [])
            item_tt_urls = resolved["tiktok"] or ([tiktok_url] if tiktok_url else [])
            is_ov = resolved["is_override"]
            ov_name = resolved.get("matched_override_title")
            alt_titles = resolved.get("alternative_titles", [])
            all_titles = resolved.get("all_titles", [title])
        else:
            item_fb_urls = [facebook_url] if facebook_url else []
            item_yt_urls = [youtube_url] if youtube_url else []
            item_x_urls = [x_url] if x_url else []
            item_tt_urls = [tiktok_url] if tiktok_url else []
            is_ov = False
            ov_name = None
            alt_titles = []
            all_titles = [title]

        curr_res = master_results.get(key, {
            "facebook_url": "NOT FOUND",
            "youtube_url": "NOT FOUND",
            "x_url": "NOT FOUND",
            "fb_attempts": 0,
            "yt_attempts": 0,
            "x_attempts": 0
        })
        state = {
            "row_num": row_num,
            "key": key,
            "title": title,
            "time_str": time_str,
            "date_str": date_str,
            "sched_dt": sched_dt,
            "target_fb_urls": item_fb_urls,
            "target_yt_urls": item_yt_urls,
            "target_x_urls": [] if should_skip_x else item_x_urls,
            "target_tt_urls": item_tt_urls,
            "is_override": is_ov,
            "override_name": ov_name,
            "alternative_titles": alt_titles,
            "all_titles": all_titles,
            "fb_link": curr_res.get("facebook_url", "NOT FOUND"),
            "yt_link": curr_res.get("youtube_url", "NOT FOUND"),
            "x_link": NOT_FOUND_DISPLAY if should_skip_x else curr_res.get("x_url", "NOT FOUND"),
            "fb_attempts": 0,
            "yt_attempts": 0,
            "x_attempts": 0,
        }
        item_states.append(state)

    # รวบรวมรายการ URL ที่ต้อง Crawl ทั้งหมดในรอบนี้ (ตัด URL ซ้ำออกเพื่อไม่โหลดหน้าเดิมซ้ำ)
    needed_fb_urls = list({u for s in item_states if s["fb_link"] == "NOT FOUND" for u in s["target_fb_urls"] if u})
    needed_yt_urls = list({u for s in item_states if s["yt_link"] == "NOT FOUND" for u in s["target_yt_urls"] if u})
    needed_x_urls = [] if should_skip_x else list({u for s in item_states if s["x_link"] == "NOT FOUND" for u in s["target_x_urls"] if u})

    # รอบที่ 1: Scrape วิดีโอจาก Facebook, YouTube และ X (เช็คครั้งแรกของรายการที่ถึงเวลา)
    print("\n--- เริ่มต้น Scrape ข้อมูลจาก Facebook, YouTube และ X (ครั้งที่ 1) ---")
    fb_videos_by_url = {}
    yt_videos_by_url = {}
    x_videos_by_url = {}

    for u in needed_fb_urls:
        try:
            print(f"  🌐 [FB Crawl] กำลังตรวจสอบ: {u}")
            titles_for_u = [s["title"] for s in item_states if u in s["target_fb_urls"]]
            fb_videos_by_url[u] = scrape_live_videos(
                page_url=u,
                max_scrolls=25,
                load_wait_seconds=page_wait_seconds_fb,
                channel_name=channel_name,
                program_titles=titles_for_u
            )
        except Exception as e:
            print(f"[Warning] เกิดข้อผิดพลาดขณะ Crawl Facebook ({u}): {e}")

    for u in needed_yt_urls:
        try:
            print(f"  🌐 [YT Crawl] กำลังตรวจสอบ: {u}")
            yt_videos_by_url[u] = scrape_youtube_streams(channel_streams_url=u, max_scrolls=15, load_wait_seconds=page_wait_seconds_yt)
        except Exception as e:
            print(f"[Warning] เกิดข้อผิดพลาดขณะ Crawl YouTube ({u}): {e}")

    for u in needed_x_urls:
        try:
            print(f"  🌐 [X Crawl] กำลังตรวจสอบ: {u}")
            x_videos_by_url[u] = scrape_x_live_videos(page_url=u, max_scrolls=3, load_wait_seconds=page_wait_seconds_x)
        except Exception as e:
            print(f"[Warning] เกิดข้อผิดพลาดขณะ Crawl X ({u}): {e}")

    # ทำการ Match รายการครั้งที่ 1
    for state in item_states:
        title = state["title"]
        time_str = state["time_str"]
        date_str = state["date_str"]
        sched_dt = state["sched_dt"]
        cand_fb_videos = [v for u in state["target_fb_urls"] for v in fb_videos_by_url.get(u, [])]
        cand_yt_videos = [v for u in state["target_yt_urls"] for v in yt_videos_by_url.get(u, [])]
        cand_x_videos = [v for u in state["target_x_urls"] for v in x_videos_by_url.get(u, [])]

        # ข้อกำหนดเฉพาะสำหรับ 'โหนกระแส': ต้องเป็น ongoing live หรือมีคำว่า LIVE/สด ในชื่อ/คำอธิบาย เพื่อป้องกันการจับคู่คลิป/ไฮไลท์ย้อนหลัง
        if "โหนกระแส" in title:
            live_pattern = re.compile(r'(?:^|[^a-z0-9\u0E00-\u0E7F])(?:live|สด)(?:[^a-z0-9\u0E00-\u0E7F]|$)', re.IGNORECASE)
            cand_fb_videos = [v for v in cand_fb_videos if v.get("is_ongoing_live") or live_pattern.search(f"{v.get('title', '')} {v.get('description', '')}")]
            cand_yt_videos = [v for v in cand_yt_videos if v.get("is_ongoing_live") or live_pattern.search(v.get("title", ""))]
            cand_x_videos = [v for v in cand_x_videos if v.get("is_ongoing_live") or live_pattern.search(v.get("title", ""))]

        alt_msg = f" (ชื่อสำรอง: {', '.join(state['alternative_titles'])})" if state.get("alternative_titles") else ""
        if state["is_override"]:
            print(f"\n[Search] กำลังค้นหารายการ: '{title}' ({date_str} {time_str}) ⚙️ [มีลิงก์เฉพาะรายการ: {state['override_name']}]{alt_msg} (ครั้งที่ 1)")
        else:
            print(f"\n[Search] กำลังค้นหารายการ: '{title}' ({date_str} {time_str}){alt_msg} (ครั้งที่ 1)")

        if state["fb_link"] == "NOT FOUND":
            state["fb_attempts"] += 1
            matched_fb = find_matching_video(
                videos=cand_fb_videos,
                program_title=title,
                broadcast_time=time_str,
                broadcast_date=date_str,
                scheduled_dt=sched_dt,
                alternative_titles=state.get("alternative_titles")
            )
            if matched_fb:
                state["fb_link"] = matched_fb["url"]
                reason_note = f" ({matched_fb['match_reason']})" if matched_fb.get("match_reason") else ""
                print(f"  ✅ [FB MATCHED] เจอ Facebook (ครั้งที่ {state['fb_attempts']}){reason_note}: {state['fb_link']}")
            else:
                print(f"  ❌ [FB NOT FOUND] ไม่พบวิดีโอบน Facebook (ครั้งที่ {state['fb_attempts']}/{MAX_ATTEMPTS_PER_PLATFORM})")
        else:
            print(f"  ℹ️ [FB ALREADY FOUND] มีลิงก์ Facebook อยู่แล้ว: {state['fb_link']}")

        if state["yt_link"] == "NOT FOUND":
            state["yt_attempts"] += 1
            matched_yt = find_matching_youtube_video(
                videos=cand_yt_videos,
                program_title=title,
                broadcast_time=time_str,
                broadcast_date=date_str,
                scheduled_dt=sched_dt,
                alternative_titles=state.get("alternative_titles")
            )
            if matched_yt:
                state["yt_link"] = matched_yt["url"]
                reason_note = f" ({matched_yt['match_reason']})" if matched_yt.get("match_reason") else ""
                print(f"  ✅ [YT MATCHED] เจอ YouTube (ครั้งที่ {state['yt_attempts']}){reason_note}: {state['yt_link']}")
            else:
                print(f"  ❌ [YT NOT FOUND] ไม่พบวิดีโอบน YouTube (ครั้งที่ {state['yt_attempts']}/{MAX_ATTEMPTS_PER_PLATFORM})")
        else:
            print(f"  ℹ️ [YT ALREADY FOUND] มีลิงก์ YouTube อยู่แล้ว: {state['yt_link']}")

        if should_skip_x:
            reason = "ยกเว้นเฉพาะ Thai PBS" if skip_x_except_thaipbs else "--skip-x"
            print(f"  ⏭️ [X SKIPPED] ข้ามการค้นหา X ({reason})")
        elif state["x_link"] == "NOT FOUND":
            state["x_attempts"] += 1
            matched_x = find_matching_x_video(
                videos=cand_x_videos,
                program_title=title,
                broadcast_time=time_str,
                broadcast_date=date_str,
                scheduled_dt=sched_dt,
                alternative_titles=state.get("alternative_titles")
            )
            if matched_x:
                state["x_link"] = matched_x["url"]
                reason_note = f" ({matched_x['match_reason']})" if matched_x.get("match_reason") else ""
                print(f"  ✅ [X MATCHED] เจอ X (ครั้งที่ {state['x_attempts']}){reason_note}: {state['x_link']}")
            else:
                print(f"  ❌ [X NOT FOUND] ไม่พบวิดีโอบน X (ครั้งที่ {state['x_attempts']}/{MAX_ATTEMPTS_PER_PLATFORM})")
        else:
            print(f"  ℹ️ [X ALREADY FOUND] มีลิงก์ X อยู่แล้ว: {state['x_link']}")

    # รอบที่ 2 (รอบสุดท้าย): Refetch หน้าเว็บใหม่ เฉพาะ platform ที่ยัง NOT FOUND เท่านั้น แล้วค้นหาซ้ำอีก "ครั้งเดียว"
    need_fb_retry = any(s["fb_link"] == "NOT FOUND" and s["fb_attempts"] < MAX_ATTEMPTS_PER_PLATFORM for s in item_states)
    need_yt_retry = any(s["yt_link"] == "NOT FOUND" and s["yt_attempts"] < MAX_ATTEMPTS_PER_PLATFORM for s in item_states)
    need_x_retry = (not should_skip_x) and any(s["x_link"] == "NOT FOUND" and s["x_attempts"] < MAX_ATTEMPTS_PER_PLATFORM for s in item_states)

    if need_fb_retry or need_yt_retry or need_x_retry:
        retry_platforms = [name for name, need in (("Facebook", need_fb_retry), ("YouTube", need_yt_retry), ("X", need_x_retry)) if need]
        print(f"\n--- Refetch เฉพาะ platform ที่ยังไม่พบ (ครั้งที่ 2 / ครั้งสุดท้าย): {', '.join(retry_platforms)} ---")

        retry_fb_urls = list({u for s in item_states if need_fb_retry and s["fb_link"] == "NOT FOUND" for u in s["target_fb_urls"] if u})
        retry_yt_urls = list({u for s in item_states if need_yt_retry and s["yt_link"] == "NOT FOUND" for u in s["target_yt_urls"] if u})
        retry_x_urls = list({u for s in item_states if need_x_retry and s["x_link"] == "NOT FOUND" for u in s["target_x_urls"] if u})

        fb_videos_retry_by_url = {}
        yt_videos_retry_by_url = {}
        x_videos_retry_by_url = {}

        for u in retry_fb_urls:
            try:
                print(f"  🌐 [FB Refetch] {u}")
                titles_for_u = [s["title"] for s in item_states if u in s["target_fb_urls"]]
                fb_videos_retry_by_url[u] = scrape_live_videos(
                    page_url=u,
                    max_scrolls=25,
                    load_wait_seconds=page_wait_seconds_fb,
                    channel_name=channel_name,
                    program_titles=titles_for_u
                )
            except Exception as e:
                print(f"[Warning] เกิดข้อผิดพลาดขณะ Refetch Facebook ({u}): {e}")

        for u in retry_yt_urls:
            try:
                print(f"  🌐 [YT Refetch] {u}")
                yt_videos_retry_by_url[u] = scrape_youtube_streams(channel_streams_url=u, max_scrolls=15, load_wait_seconds=page_wait_seconds_yt)
            except Exception as e:
                print(f"[Warning] เกิดข้อผิดพลาดขณะ Refetch YouTube ({u}): {e}")

        for u in retry_x_urls:
            try:
                print(f"  🌐 [X Refetch] {u}")
                x_videos_retry_by_url[u] = scrape_x_live_videos(page_url=u, max_scrolls=3, load_wait_seconds=page_wait_seconds_x)
            except Exception as e:
                print(f"[Warning] เกิดข้อผิดพลาดขณะ Refetch X ({u}): {e}")

        for state in item_states:
            title = state["title"]
            time_str = state["time_str"]
            date_str = state["date_str"]
            sched_dt = state["sched_dt"]
            retry_cand_fb = [v for u in state["target_fb_urls"] for v in fb_videos_retry_by_url.get(u, [])]
            retry_cand_yt = [v for u in state["target_yt_urls"] for v in yt_videos_retry_by_url.get(u, [])]
            retry_cand_x = [v for u in state["target_x_urls"] for v in x_videos_retry_by_url.get(u, [])]

            # ข้อกำหนดเฉพาะสำหรับ 'โหนกระแส': ต้องเป็น ongoing live หรือมีคำว่า LIVE/สด ในชื่อ/คำอธิบาย
            if "โหนกระแส" in title:
                live_pattern = re.compile(r'(?:^|[^a-z0-9\u0E00-\u0E7F])(?:live|สด)(?:[^a-z0-9\u0E00-\u0E7F]|$)', re.IGNORECASE)
                retry_cand_fb = [v for v in retry_cand_fb if v.get("is_ongoing_live") or live_pattern.search(f"{v.get('title', '')} {v.get('description', '')}")]
                retry_cand_yt = [v for v in retry_cand_yt if v.get("is_ongoing_live") or live_pattern.search(v.get("title", ""))]
                retry_cand_x = [v for v in retry_cand_x if v.get("is_ongoing_live") or live_pattern.search(v.get("title", ""))]

            if need_fb_retry and state["fb_link"] == "NOT FOUND" and state["fb_attempts"] < MAX_ATTEMPTS_PER_PLATFORM:
                state["fb_attempts"] += 1
                matched_fb = find_matching_video(
                    videos=retry_cand_fb,
                    program_title=title,
                    broadcast_time=time_str,
                    broadcast_date=date_str,
                    scheduled_dt=sched_dt,
                    alternative_titles=state.get("alternative_titles")
                )
                if matched_fb:
                    state["fb_link"] = matched_fb["url"]
                    reason_note = f" ({matched_fb['match_reason']})" if matched_fb.get("match_reason") else ""
                    print(f"  ✅ [FB MATCHED] เจอ Facebook (ครั้งที่ {state['fb_attempts']}){reason_note}: {state['fb_link']} (รายการ '{title}')")
                else:
                    print(f"  🚫 [FB NOT FOUND] ค้นหาครบ {state['fb_attempts']}/{MAX_ATTEMPTS_PER_PLATFORM} ครั้งในรอบนี้ ไม่พบ Facebook สำหรับรายการ '{title}'")

            if need_yt_retry and state["yt_link"] == "NOT FOUND" and state["yt_attempts"] < MAX_ATTEMPTS_PER_PLATFORM:
                state["yt_attempts"] += 1
                matched_yt = find_matching_youtube_video(
                    videos=retry_cand_yt,
                    program_title=title,
                    broadcast_time=time_str,
                    broadcast_date=date_str,
                    scheduled_dt=sched_dt,
                    alternative_titles=state.get("alternative_titles")
                )
                if matched_yt:
                    state["yt_link"] = matched_yt["url"]
                    reason_note = f" ({matched_yt['match_reason']})" if matched_yt.get("match_reason") else ""
                    print(f"  ✅ [YT MATCHED] เจอ YouTube (ครั้งที่ {state['yt_attempts']}){reason_note}: {state['yt_link']} (รายการ '{title}')")
                else:
                    print(f"  🚫 [YT NOT FOUND] ค้นหาครบ {state['yt_attempts']}/{MAX_ATTEMPTS_PER_PLATFORM} ครั้งในรอบนี้ ไม่พบ YouTube สำหรับรายการ '{title}'")

            if need_x_retry and state["x_link"] == "NOT FOUND" and state["x_attempts"] < MAX_ATTEMPTS_PER_PLATFORM:
                state["x_attempts"] += 1
                matched_x = find_matching_x_video(
                    videos=retry_cand_x,
                    program_title=title,
                    broadcast_time=time_str,
                    broadcast_date=date_str,
                    scheduled_dt=sched_dt,
                    alternative_titles=state.get("alternative_titles")
                )
                if matched_x:
                    state["x_link"] = matched_x["url"]
                    reason_note = f" ({matched_x['match_reason']})" if matched_x.get("match_reason") else ""
                    print(f"  ✅ [X MATCHED] เจอ X (ครั้งที่ {state['x_attempts']}){reason_note}: {state['x_link']} (รายการ '{title}')")
                else:
                    print(f"  🚫 [X NOT FOUND] ค้นหาครบ {state['x_attempts']}/{MAX_ATTEMPTS_PER_PLATFORM} ครั้งในรอบนี้ ไม่พบ X สำหรับรายการ '{title}'")

    # อัปเดต master_results และเขียนผลลัพธ์กลับลง Google Sheet (รายการถือว่าจบแล้วหลังรอบนี้)
    updated_items = []
    for state in item_states:
        key = state["key"]
        row_num = state["row_num"]
        date_str = state["date_str"]
        time_str = state["time_str"]
        title = state["title"]
        fb_link = state["fb_link"]
        yt_link = state["yt_link"]
        x_link = state["x_link"]

        master_results[key] = {
            "row": row_num,
            "date": date_str,
            "time": time_str,
            "search_string": title,
            "title": title,
            "facebook_url": fb_link,
            "youtube_url": yt_link,
            "x_url": x_link,
            "fb_attempts": state["fb_attempts"],
            "yt_attempts": state["yt_attempts"],
            "x_attempts": state["x_attempts"],
            "last_checked": system_now.strftime('%Y-%m-%d %H:%M:%S')
        }
        updated_items.append(master_results[key])

        # ดึง TikTok URL: ให้ความสำคัญกับ Broadcast Override / Channel Link (target_tt_urls) ก่อนเสมอ
        custom_tt = state.get("target_tt_urls", [None])[0] if state.get("target_tt_urls") else None
        tt_to_write = custom_tt or state.get("tiktok_url") or tiktok_url
        if not tt_to_write or tt_to_write.strip() in ("-", "NOT FOUND", ""):
            if channel_name:
                cfg_src = channels_config or CHANNELS_CONFIG
                ch_cfg = resolve_channel_config(channel_name, cfg_src) if cfg_src else None
                if ch_cfg and ch_cfg.get("tiktok_url"):
                    tt_to_write = ch_cfg["tiktok_url"]
            if not tt_to_write or tt_to_write.strip() in ("-", "NOT FOUND", ""):
                tt_to_write = os.getenv("PAGE_URL_TT", "https://www.tiktok.com/@thaipbs/live")

        master_results[key]["tiktok_url"] = tt_to_write

        # บันทึกลิงก์สดลง Local Cache ทันที เพื่อให้ ViewStatsScraper นำไปใช้ได้แบบ Real-time โดยไม่ต้องรอโหลด Google Sheets
        try:
            save_crawled_url(
                channel=channel_name,
                date=date_str,
                time=time_str,
                title=title,
                facebook_url=fb_link,
                youtube_url=yt_link,
                x_url=x_link,
                tiktok_url=tt_to_write
            )
        except Exception:
            pass

    return updated_items, upcoming_items


def start_live_scheduler(
    script_api_url: str,
    facebook_url: str,
    youtube_url: str,
    x_url: str,
    page_wait_seconds_fb: int,
    page_wait_seconds_yt: int,
    page_wait_seconds_x: int,
    check_interval_seconds: int,
    delay_minutes: int,
    channel_name: Optional[str] = None,
    tiktok_url: Optional[str] = None,
    current_only: bool = False,
    run_once: bool = False,
    max_attempts: int = 1,
    script_api_token: Optional[str] = None,
    skip_x: bool = False,
    skip_x_except_thaipbs: bool = False
):
    """
    Loop ตรวจสอบสถานะอัตโนมัติ รันทิ้งไว้ต่อเนื่องจนกว่าผู้ใช้จะกด Ctrl + C (หรือรันรอบเดียวจบหาก run_once=True)
    """
    ch_label = f" (Channel: {channel_name})" if channel_name else ""
    print("=" * 80)
    mode_desc = "Single-Pass Mode" if run_once else "Continuous Scheduler Mode"
    scope_desc = "Current Broadcast Only" if current_only else "All Past Schedules"
    attempts_desc = f"Max Attempts: {max_attempts}"
    print(f"🚀 เริ่มต้นระบบ Live Scraper Automate ({mode_desc} | {scope_desc} | {attempts_desc}){ch_label}")
    print("=" * 80)
    print(f"• Apps Script API : {script_api_url}")
    if channel_name:
        print(f"• Channel Name    : {channel_name}")
    print(f"• Facebook Target : {facebook_url}")
    print(f"• YouTube Target  : {youtube_url}")
    if skip_x:
        print("• X Target        : ข้ามการค้นหาทั้งหมด (--skip-x)")
    elif skip_x_except_thaipbs:
        is_tpbs = is_thaipbs_channel(channel_name)
        print(f"• X Target        : {x_url} (ค้นหาปกติ - ช่อง Thai PBS)" if is_tpbs else "• X Target        : ข้ามการค้นหา (ยกเว้นเฉพาะ Thai PBS)")
    else:
        print(f"• X Target        : {x_url}")
    if tiktok_url:
        print(f"• TikTok Default  : {tiktok_url}")
    print(f"• Check Interval  : ทุกๆ {check_interval_seconds} วินาที")
    print(f"• Stream Delay    : {delay_minutes} นาที (เผื่อเวลาให้ทีม Live ขึ้นสตรีมสด)")
    print(f"• Max Attempts    : {max_attempts} ครั้ง/platform")
    if run_once:
        print("• โหมดการทำงาน    : --once (รัน 1 รอบค้นหารายการปัจจุบันแล้วสิ้นสุดทันที)\n")
    else:
        print("• กด Ctrl + C ได้ทุกเมื่อเพื่อหยุดการทำงานอย่างปลอดภัย\n")

    # ดึงตารางจาก Google Apps Script API
    try:
        schedules: List[Dict] = fetch_sheet_schedule(api_url=script_api_url, sheet=channel_name, token=script_api_token)
        if current_only and schedules:
            now_dt = datetime.now(ZoneInfo("Asia/Bangkok"))
            today_d = now_dt.date()
            yesterday_d = today_d - timedelta(days=1)
            dates = [s["datetime"].date() for s in schedules if s.get("datetime")]
            if dates:
                allowed_dates = set()
                # กรณีข้ามวันช่วงดึก (00:00 - 04:59 น.): ให้รวมผังเมื่อวานด้วยเสมอ เพื่อไม่ให้พลาดรายการที่เริ่ม 23:xx
                if now_dt.hour < 5 and yesterday_d in dates:
                    allowed_dates.add(yesterday_d)
                if today_d in dates:
                    allowed_dates.add(today_d)

                if not allowed_dates:
                    latest_d_str = max(dates).strftime('%d-%m-%y') if dates else "ไม่มี"
                    print(f"⚠️ [{channel_name}] ยังไม่มีผังรายการของวันนี้ ({today_d.strftime('%d-%m-%y')}) ใน Google Sheet (ผังล่าสุด: {latest_d_str}) -> ข้ามการค้นหา")
                    schedules = []
                else:
                    schedules = [s for s in schedules if s.get("datetime") and s["datetime"].date() in allowed_dates]
    except Exception as e:
        print(f"[Error] ไม่สามารถดึงข้อมูลจาก Google Apps Script API ได้: {e}")
        return

    # Seed รายการที่ประมวลผลจบไปแล้ว และโหลดลิงก์ที่เคยค้นพบจาก Local Cache
    master_results, unsynced = seed_master_results_from_schedule(schedules, channel_name=channel_name, return_unsynced=True)
    if unsynced:
        print(f"🔄 [Sync Recovery] ตรวจพบ {len(unsynced)} รายการใน Local Cache ที่ยังไม่ได้บันทึกลง Google Sheet (จากการปิดโปรแกรมก่อนหน้า)")
        print(f"📝 กำลังซิงค์รายการตกค้างขึ้น Google Sheet ทันที...")
        write_batch_row_results(
            api_url=script_api_url,
            sheet=channel_name,
            updates=unsynced,
            token=script_api_token,
            max_retries=3
        )

    print("📡 [Google Sheets] กำลังโหลดการตั้งค่าลิงก์ช่อง & รายการเฉพาะ (Channel Multi-Links & Broadcast Overrides)...")
    link_config = fetch_link_config(api_url=script_api_url, token=script_api_token)
    if link_config.get("ok"):
        ch_cfg_count = len(link_config.get("channel_links", {}))
        bo_cfg_count = len(link_config.get("broadcast_overrides", []))
        print(f"✅ โหลดการตั้งค่าลิงก์สำเร็จ: {ch_cfg_count} ช่องปรับแต่ง, {bo_cfg_count} รายการเฉพาะ\n")

    iteration = 0

    try:
        while True:
            iteration += 1
            reset_facebook_blocked_status()
            system_now = datetime.now(ZoneInfo("Asia/Bangkok"))
            print(f"\n{'='*30} รอบตรวจสอบที่ #{iteration} ({system_now.strftime('%Y-%m-%d %H:%M:%S')}) {'='*30}")

            # ประมวลผลรายการที่ถึงเวลา
            updated_items, upcoming_items = process_due_schedules(
                schedules=schedules,
                facebook_url=facebook_url,
                youtube_url=youtube_url,
                x_url=x_url,
                page_wait_seconds_fb=page_wait_seconds_fb,
                page_wait_seconds_yt=page_wait_seconds_yt,
                page_wait_seconds_x=page_wait_seconds_x,
                master_results=master_results,
                delay_minutes=delay_minutes,
                script_api_url=script_api_url,
                channel_name=channel_name,
                tiktok_url=tiktok_url,
                current_only=current_only,
                max_attempts=max_attempts,
                script_api_token=script_api_token,
                link_config=link_config,
                channels_config=CHANNELS_CONFIG,
                skip_x=skip_x,
                skip_x_except_thaipbs=skip_x_except_thaipbs
            )

            # บันทึกผลลัพธ์ที่อัปเดตทั้งหมดขึ้น Google Sheet แบบ Batch (รวมส่งใน 1 Request เดียว พร้อม Retry)
            if updated_items:
                write_batch_row_results(
                    api_url=script_api_url,
                    sheet=channel_name,
                    updates=updated_items,
                    token=script_api_token,
                    max_retries=3
                )

            # สรุปสถานะภาพรวม
            total_items = len(schedules)
            completed_count = 0
            partial_count = 0
            not_found_count = 0

            for s in schedules:
                k = f"{s['date']} {s['time']}_{s['title']}"
                res = master_results.get(k, {})
                fb = res.get("facebook_url", "NOT FOUND")
                yt = res.get("youtube_url", "NOT FOUND")
                x_link = res.get("x_url", "NOT FOUND")
                if fb != "NOT FOUND" and yt != "NOT FOUND" and x_link != "NOT FOUND":
                    completed_count += 1
                elif fb != "NOT FOUND" or yt != "NOT FOUND" or x_link != "NOT FOUND":
                    partial_count += 1
                else:
                    not_found_count += 1

            print(f"\n📊 [Status Summary] รายการทั้งหมด: {total_items} | เจอครบ (FB+YT+X): {completed_count} | เจอบางส่วน: {partial_count} | ยังไม่พบ/รอเวลา: {not_found_count}")

            # แสดงข้อมูลรายการถัดไปที่กำลังรอเวลาออกอากาศ + delay
            if upcoming_items:
                # เรียงลำดับรายการตามเวลาที่ใกล้จะถึงที่สุด
                upcoming_items.sort(key=lambda x: x.get("trigger_time", datetime.max.replace(tzinfo=ZoneInfo("Asia/Bangkok"))))
                next_item = upcoming_items[0]
                wait_sec = int(next_item["wait_seconds"])
                wait_min = wait_sec // 60
                wait_rem_sec = wait_sec % 60

                print(f"\n⏳ [Next Program] รายการถัดไปในตาราง:")
                print(f"   • ชื่อรายการ : '{next_item['title']}'")
                print(f"   • เวลาในผัง  : {next_item['date']} เวลา {next_item['time']} น.")
                print(f"   • เวลาเริ่มค้นหา (ผัง + {delay_minutes} นาที) : {next_item['trigger_time'].strftime('%H:%M:%S')} น.")
                print(f"   • นับถอยหลัง : อีก {wait_min:02d} นาที {wait_rem_sec:02d} วินาที (System Time: {system_now.strftime('%H:%M:%S')})")
            else:
                print("\n✅ [Info] ประมวลผลครบทุกรายการในผังปัจจุบันแล้ว (หรือไม่มีรายการที่รอเวลาข้างหน้า)")

            if run_once:
                print(f"\n🏁 [Done] ประมวลผลรอบปัจจุบันของช่อง '{channel_name}' เรียบร้อยแล้ว (--once เสร็จสิ้น)")
                break

            print(f"\n💤 [Scheduler] สแตนด์บายรอตรวจรอบถัดไปในอีก {check_interval_seconds} วินาที... (กด Ctrl+C เพื่อหยุด)")
            time.sleep(check_interval_seconds)

    except KeyboardInterrupt:
        print("\n\n" + "="*80)
        print("🛑 ได้รับคำสั่ง Ctrl + C: จบการทำงานของระบบเรียบร้อยแล้ว")
        print("💾 ผลลัพธ์ทั้งหมดถูกเขียนกลับลง Google Sheet แบบ Real-time ไว้แล้ว")
        print("="*80 + "\n")


def start_multi_channel_scheduler(
    script_api_url: str,
    page_wait_seconds_fb: int,
    page_wait_seconds_yt: int,
    page_wait_seconds_x: int,
    check_interval_seconds: int,
    delay_minutes: int,
    channels_config: Dict,
    current_only: bool = False,
    run_once: bool = False,
    workers: int = 5,
    max_attempts: int = 1,
    script_api_token: Optional[str] = None,
    skip_x: bool = False,
    skip_x_except_thaipbs: bool = False
):
    """
    Multi-Channel Scheduler Loop:
    - ดึงตารางเวลาของทุกช่องจาก Google Sheet
    - ตรวจสอบเวลาทุกๆ check_interval_seconds
    - เมื่อรายการของช่องใดถึงเวลา (เวลาออกอากาศ + delay) ระบบจะดึง crawler ของช่องนั้นมาค้นหาทันที
    - หาก current_only=True: จะค้นหาเฉพาะรายการปัจจุบันที่กำลังออกอากาศ ข้ามรายการเก่าในอดีตทั้งหมด
    - หาก run_once=True: ค้นหารายการปัจจุบันครบทุกช่อง 1 รอบแล้วสิ้นสุดการทำงานทันที
    - หาก skip_x=True หรือ skip_x_except_thaipbs=True: ข้ามการค้นหา X ตามเงื่อนไขที่กำหนด
    - ทำงานพร้อมกัน (Concurrent) สูงสุด workers ช่อง (default: 5)
    - ค้นหาครั้งเดียวจบ ไม่ refetch ซ้ำ (max_attempts=1)
    - เขียนลิงก์ FB, YT, X กลับลงในแท็บชีทของช่องนั้นๆ แบบ Real-time
    - แสดงเวลานับถอยหลังของรายการถัดไปที่ใกล้จะถึงที่สุดในบรรดาทุกช่อง
    """
    print("=" * 80)
    mode_desc = "Single-Pass Mode" if run_once else "Continuous Scheduler Mode"
    scope_desc = "Current Broadcast Only" if current_only else "All Past Schedules"
    attempts_desc = f"Max Attempts: {max_attempts}"
    workers_desc = f"Concurrency: {workers} Channels"
    print(f"🚀 เริ่มต้นระบบ Multi-Channel Live Crawler Scheduler ({mode_desc} | {scope_desc} | {attempts_desc} | {workers_desc})")
    print("=" * 80)
    print(f"• Apps Script API : {script_api_url}")
    print(f"• Target Channels : ทุกช่องใน Google Sheet ({len(channels_config)} ช่องในฐานข้อมูล)")
    print(f"• Concurrency     : พร้อมกันสูงสุด {workers} ช่อง")
    print(f"• Max Attempts    : {max_attempts} ครั้ง/platform")
    print(f"• Check Interval  : ทุกๆ {check_interval_seconds} วินาที")
    print(f"• Stream Delay    : {delay_minutes} นาที (เผื่อเวลาให้ทีม Live ขึ้นสตรีมสด)")
    if skip_x:
        print("• X Search        : ข้ามการค้นหาทุกช่อง (--skip-x)")
    elif skip_x_except_thaipbs:
        print("• X Search        : ข้ามการค้นหาทุกช่อง ยกเว้นช่อง Thai PBS (--skip-x-except-thaipbs)")
    else:
        print("• X Search        : ค้นหาทุกช่องตามปกติ")
    if run_once:
        print("• โหมดการทำงาน    : --once (รัน 1 รอบค้นหารายการปัจจุบันแล้วสิ้นสุดทันที)\n")
    else:
        print("• กด Ctrl + C ได้ทุกเมื่อเพื่อหยุดการทำงานอย่างปลอดภัย\n")

    print("📡 [Google Sheets] กำลังโหลดตารางเวลาของทุกช่อง...")
    all_schedules_raw = fetch_all_channel_schedules(api_url=script_api_url, token=script_api_token)
    if all_schedules_raw:
        try:
            save_schedules_cache(all_schedules_raw)
        except Exception:
            pass
    else:
        print("[Warning] ไม่พบข้อมูลตารางเวลา หรือไม่สามารถเข้าถึง Apps Script ได้ กำลังลองโหลดจาก Local Cache...")
        all_schedules_raw = load_schedules_cache(max_age_seconds=0) or {}
        if all_schedules_raw:
            print(f"📦 [Local Cache] โหลดตารางเวลาจาก Local Cache สำเร็จ ({len(all_schedules_raw)} ช่อง)")
        else:
            print("[Warning] ไม่พบข้อมูลตารางเวลาใน Local Cache เช่นกัน")

    # Map channel -> parsed schedule items และ master_results per channel
    channel_schedules = {}
    master_results_by_channel = {}
    pending_sync_by_channel = {}

    for ch_name, rows in all_schedules_raw.items():
        sched_list = []
        for r in rows:
            date_val = str(r.get("date", "")).strip()
            time_val = str(r.get("time", "")).strip()
            title_val = str(r.get("title", "")).strip()
            if not title_val:
                continue
            sched_dt = parse_schedule_datetime(date_val, time_val)
            sched_list.append({
                "row": r.get("row"),
                "date": date_val,
                "time": time_val,
                "title": title_val,
                "datetime": sched_dt,
                "facebook_url": str(r.get("facebook_url", "")).strip(),
                "youtube_url": str(r.get("youtube_url", "")).strip(),
                "x_url": str(r.get("x_url", "")).strip(),
                "tiktok_url": str(r.get("tiktok_url", "")).strip()
            })
        if current_only and sched_list:
            now_dt = datetime.now(ZoneInfo("Asia/Bangkok"))
            today_d = now_dt.date()
            yesterday_d = today_d - timedelta(days=1)
            dates = [s["datetime"].date() for s in sched_list if s.get("datetime")]
            if dates:
                allowed_dates = set()
                # กรณีข้ามวันช่วงดึก (00:00 - 04:59 น.): ให้รวมผังเมื่อวานด้วยเสมอ เพื่อไม่ให้พลาดรายการที่เริ่ม 23:xx
                if now_dt.hour < 5 and yesterday_d in dates:
                    allowed_dates.add(yesterday_d)
                if today_d in dates:
                    allowed_dates.add(today_d)

                if not allowed_dates:
                    latest_d_str = max(dates).strftime('%d-%m-%y') if dates else "ไม่มี"
                    print(f"⚠️ [{ch_name}] ยังไม่มีผังรายการของวันนี้ ({today_d.strftime('%d-%m-%y')}) ใน Google Sheet (ผังล่าสุด: {latest_d_str}) -> ข้ามช่องนี้")
                    sched_list = []
                else:
                    sched_list = [s for s in sched_list if s.get("datetime") and s["datetime"].date() in allowed_dates]
        channel_schedules[ch_name] = sched_list
        res_master, unsynced = seed_master_results_from_schedule(sched_list, channel_name=ch_name, return_unsynced=True)
        master_results_by_channel[ch_name] = res_master
        if unsynced:
            pending_sync_by_channel[ch_name] = unsynced

    total_programs = sum(len(v) for v in channel_schedules.values())
    print(f"✅ โหลดผังรายการสำเร็จ: ทั้งหมด {len(channel_schedules)} ช่อง ({total_programs} รายการ)\n")

    # Sync Recovery: บันทึกรายการตกค้างจาก Local Cache ที่ยังไม่ได้เขียนลง Google Sheets ทันที
    if pending_sync_by_channel:
        total_unsynced = sum(len(v) for v in pending_sync_by_channel.values())
        print(f"🔄 [Sync Recovery] ตรวจพบ {total_unsynced} รายการใน Local Cache จาก {len(pending_sync_by_channel)} ช่อง ที่ยังไม่ได้บันทึกลง Google Sheet (จากการปิดโปรแกรมก่อนหน้า)")
        print(f"📝 กำลังซิงค์รายการตกค้างขึ้น Google Sheet ทันที...")
        for ch_key, rows_to_write in pending_sync_by_channel.items():
            write_batch_row_results(
                api_url=script_api_url,
                sheet=ch_key,
                updates=rows_to_write,
                token=script_api_token,
                max_retries=3
            )
        print("✅ [Sync Recovery] ซิงค์รายการตกค้างขึ้น Google Sheet เรียบร้อยแล้ว\n")


    print("📡 [Google Sheets] กำลังโหลดการตั้งค่าลิงก์ช่อง & รายการเฉพาะ (Channel Multi-Links & Broadcast Overrides)...")
    link_config = fetch_link_config(api_url=script_api_url, token=script_api_token)
    if link_config.get("ok"):
        ch_cfg_count = len(link_config.get("channel_links", {}))
        bo_cfg_count = len(link_config.get("broadcast_overrides", []))
        print(f"✅ โหลดการตั้งค่าลิงก์สำเร็จ: {ch_cfg_count} ช่องปรับแต่ง, {bo_cfg_count} รายการเฉพาะ\n")

    def _crawl_single_channel(ch_name_task, sched_task):
        ch_cfg = resolve_channel_config(ch_name_task, channels_config) or {}
        fb_target = ch_cfg.get("facebook_url") or os.getenv("PAGE_URL_FB", "https://www.facebook.com/ThaiPBS/live_videos/")
        yt_target = ch_cfg.get("youtube_url") or os.getenv("PAGE_URL_YT", "https://www.youtube.com/@ThaiPBS/streams")
        x_target = ch_cfg.get("x_url") or os.getenv("PAGE_URL_X", "https://x.com/ThaiPBS")
        tt_target = ch_cfg.get("tiktok_url") or os.getenv("PAGE_URL_TT", "https://www.tiktok.com/@thaipbs/live")

        upd, upc = process_due_schedules(
            schedules=sched_task,
            facebook_url=fb_target,
            youtube_url=yt_target,
            x_url=x_target,
            page_wait_seconds_fb=page_wait_seconds_fb,
            page_wait_seconds_yt=page_wait_seconds_yt,
            page_wait_seconds_x=page_wait_seconds_x,
            master_results=master_results_by_channel[ch_name_task],
            delay_minutes=delay_minutes,
            script_api_url=script_api_url,
            channel_name=ch_name_task,
            tiktok_url=tt_target,
            current_only=current_only,
            max_attempts=max_attempts,
            script_api_token=script_api_token,
            link_config=link_config,
            channels_config=channels_config,
            skip_x=skip_x,
            skip_x_except_thaipbs=skip_x_except_thaipbs
        )
        res_upc = []
        for item in upc:
            item_copy = dict(item)
            item_copy["channel"] = ch_name_task
            res_upc.append(item_copy)
        return ch_name_task, upd, res_upc

    iteration = 0
    try:
        while True:
            iteration += 1
            reset_facebook_blocked_status()
            system_now = datetime.now(ZoneInfo("Asia/Bangkok"))
            print(f"\n{'='*30} รอบตรวจสอบที่ #{iteration} ({system_now.strftime('%Y-%m-%d %H:%M:%S')}) {'='*30}")

            all_upcoming = []
            active_tasks = [(k, v) for k, v in channel_schedules.items() if v]
            num_workers = max(1, min(workers, len(active_tasks))) if active_tasks else 1
            print(f"⚡ [Concurrency] เริ่มประมวลผลพร้อมกัน {num_workers} ช่อง...")

            channel_batch_updates = {}
            with ThreadPoolExecutor(max_workers=num_workers) as executor:
                future_map = {
                    executor.submit(_crawl_single_channel, k, v): k
                    for k, v in active_tasks
                }
                for fut in as_completed(future_map):
                    ch_key = future_map[fut]
                    try:
                        _, upd, upc = fut.result()
                        all_upcoming.extend(upc)
                        if upd:
                            channel_batch_updates[ch_key] = upd
                    except Exception as e:
                        print(f"[Error] ช่อง {ch_key} เกิดข้อผิดพลาดขณะ Crawl: {e}")

            # บันทึกผลลัพธ์ทั้งหมดขึ้น Google Sheet แบบ Batch แยกรายช่อง (ส่งแบบ Sequential ป้องกัน Lock ชนกัน)
            if channel_batch_updates:
                total_to_write = sum(len(v) for v in channel_batch_updates.values())
                print(f"\n📝 [Google Sheets Batch Sync] กำลังบันทึกผลลัพธ์รวม {total_to_write} รายการ จาก {len(channel_batch_updates)} ช่อง...")
                for ch_key, rows_to_write in channel_batch_updates.items():
                    write_batch_row_results(
                        api_url=script_api_url,
                        sheet=ch_key,
                        updates=rows_to_write,
                        token=script_api_token,
                        max_retries=3
                    )

            if all_upcoming:
                all_upcoming.sort(key=lambda x: x.get("trigger_time", datetime.max.replace(tzinfo=ZoneInfo("Asia/Bangkok"))))
                next_item = all_upcoming[0]
                wait_sec = max(0, int(next_item["wait_seconds"]))
                wait_min = wait_sec // 60
                wait_rem_sec = wait_sec % 60
                print(f"\n⏳ [Next Program Across All Channels] รายการถัดไปในผัง:")
                print(f"   • ช่อง       : {next_item['channel']}")
                print(f"   • ชื่อรายการ : '{next_item['title']}'")
                print(f"   • เวลาในผัง  : {next_item['date']} เวลา {next_item['time']} น.")
                print(f"   • เวลาเริ่มค้นหา (ผัง + {delay_minutes} นาที) : {next_item['trigger_time'].strftime('%H:%M:%S')} น.")
                print(f"   • นับถอยหลัง : อีก {wait_min:02d} นาที {wait_rem_sec:02d} วินาที (System Time: {system_now.strftime('%H:%M:%S')})")
            else:
                print("\n✅ [Info] ประมวลผลครบทุกรายการในทุกช่องแล้ว (หรือไม่มีรายการที่รอเวลาข้างหน้า)")

            if run_once:
                print("\n🏁 [Done] ประมวลผลรอบปัจจุบันครบทุกช่องเรียบร้อยแล้ว (--once เสร็จสิ้น)")
                break

            print(f"\n💤 [Scheduler] สแตนด์บายรอตรวจรอบถัดไปในอีก {check_interval_seconds} วินาที... (กด Ctrl+C เพื่อหยุด)")
            time.sleep(check_interval_seconds)

    except KeyboardInterrupt:
        print("\n\n" + "="*80)
        print("🛑 ได้รับคำสั่ง Ctrl + C: จบการทำงานของระบบเรียบร้อยแล้ว")
        print("💾 ผลลัพธ์ทั้งหมดถูกเขียนกลับลง Google Sheet แบบ Real-time ไว้แล้ว")
        print("="*80 + "\n")


def load_channels_config() -> Dict:
    cfg_file = os.getenv("CHANNELS_CONFIG_FILE", "channels.json")
    if not os.path.isabs(cfg_file):
        cfg_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), cfg_file)
    if os.path.exists(cfg_file):
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def resolve_channel_config(channel_name: str, channels_data: Dict) -> Optional[Dict]:
    if not channel_name or not channels_data:
        return None
    if channel_name in channels_data:
        return channels_data[channel_name]
    target_clean = channel_name.strip().lower().replace(" ", "").replace("-", "").replace("_", "")
    for k, v in channels_data.items():
        k_clean = k.strip().lower().replace(" ", "").replace("-", "").replace("_", "")
        if target_clean == k_clean or target_clean in k_clean or k_clean in target_clean:
            return v
        for alias in v.get("aliases", []):
            a_clean = alias.strip().lower().replace(" ", "").replace("-", "").replace("_", "")
            if target_clean == a_clean or target_clean in a_clean or a_clean in target_clean:
                return v
    return None


CHANNELS_CONFIG = load_channels_config()


def get_env_with_default(key: str, default: Optional[str] = None) -> str:
    val = os.getenv(key)
    if not val:
        if default is not None:
            return default
        raise SystemExit(f"[Config Error] ไม่พบค่า '{key}' ในไฟล์ .env กรุณาตรวจสอบไฟล์ .env ก่อนรันโปรแกรม")
    return val


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Multi-Channel Live Stream Link Crawler")
    parser.add_argument(
        "--channel",
        default=os.getenv("TARGET_CHANNEL", "all"),
        help="Target channel name or 'all' to continuously monitor all channels (default: all)"
    )
    parser.add_argument(
        "--fb-url",
        default=None,
        help="Target Facebook live videos URL (overrides channels.json)"
    )
    parser.add_argument(
        "--yt-url",
        default=None,
        help="Target YouTube channel streams URL (overrides channels.json)"
    )
    parser.add_argument(
        "--x-url",
        default=None,
        help="Target X (Twitter) profile URL (overrides channels.json)"
    )
    parser.add_argument(
        "--tt-url",
        default=None,
        help="Target TikTok live URL (overrides channels.json)"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.getenv("CHECK_INTERVAL_SECONDS", "30")),
        help="Scheduler check interval in seconds (default: 30)"
    )
    parser.add_argument(
        "--delay",
        type=int,
        default=int(os.getenv("DELAY_MINUTES", "4")),
        help="Stream broadcast delay in minutes (default: 4)"
    )
    parser.add_argument(
        "--current-only",
        action="store_true",
        default=os.getenv("CURRENT_ONLY", "false").strip().lower() in ("true", "1", "yes"),
        help="Only crawl the currently active broadcast on air right now, skipping older ended programs"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        default=False,
        help="Crawl once for the current broadcast and exit (do not loop continuously)"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=int(os.getenv("CRAWLER_CONCURRENCY", "5")),
        help="Number of channels to crawl concurrently (default: 5)"
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=int(os.getenv("MAX_ATTEMPTS", "1")),
        help="Max search attempts per platform (default: 1, search once and do not refetch to save time)"
    )
    parser.add_argument(
        "--skip-x",
        action="store_true",
        default=os.getenv("SKIP_X", "false").strip().lower() in ("true", "1", "yes"),
        help="Skip crawling X (Twitter) for all broadcasts"
    )
    parser.add_argument(
        "--skip-x-except-thaipbs",
        "--skip-x-non-thaipbs",
        action="store_true",
        default=os.getenv("SKIP_X_EXCEPT_THAIPBS", os.getenv("SKIP_X_NON_THAIPBS", "false")).strip().lower() in ("true", "1", "yes"),
        help="Skip crawling X (Twitter) for all channels except Thai PBS"
    )
    parser.add_argument(
        "--no-facebook-login",
        "--skip-facebook-login",
        action="store_true",
        default=os.getenv("SKIP_FACEBOOK_LOGIN", "false").strip().lower() in ("true", "1", "yes"),
        help="Do not use logged in Facebook session for any channel (run clean guest session for all)"
    )
    args = parser.parse_args()

    if args.no_facebook_login and disable_all_facebook_login:
        disable_all_facebook_login(True)
        print("🚫 [Facebook Login] ปิดการใช้งานบัญชีล็อกอิน Facebook ทั้งหมด (บังคับใช้ Clean Guest Session ตลอดการทำงาน)")
    elif is_all_facebook_login_disabled and is_all_facebook_login_disabled():
        print("🚫 [Facebook Login] ปิดการใช้งานบัญชีล็อกอิน Facebook ตามการตั้งค่าใน facebook_login_targets.json (enabled: false)")

    SCRIPT_API_URL = get_env_with_default("STREAM_STATS_API")
    SCRIPT_API_TOKEN = os.getenv("SCRIPT_API_TOKEN") or None

    PAGE_WAIT_SECONDS_FB = int(os.getenv("PAGE_WAIT_SECONDS_FB", "8"))
    PAGE_WAIT_SECONDS_YT = int(os.getenv("PAGE_WAIT_SECONDS_YT", "5"))
    PAGE_WAIT_SECONDS_X = int(os.getenv("PAGE_WAIT_SECONDS_X", "5"))

    if args.channel.strip().lower() == "all":
        start_multi_channel_scheduler(
            script_api_url=SCRIPT_API_URL,
            page_wait_seconds_fb=PAGE_WAIT_SECONDS_FB,
            page_wait_seconds_yt=PAGE_WAIT_SECONDS_YT,
            page_wait_seconds_x=PAGE_WAIT_SECONDS_X,
            check_interval_seconds=args.interval,
            delay_minutes=args.delay,
            channels_config=CHANNELS_CONFIG,
            current_only=args.current_only,
            run_once=args.once,
            workers=args.workers,
            max_attempts=args.max_attempts,
            script_api_token=SCRIPT_API_TOKEN,
            skip_x=args.skip_x,
            skip_x_except_thaipbs=args.skip_x_except_thaipbs
        )
    else:
        # Resolve target channel URLs from channels.json
        ch_cfg = resolve_channel_config(args.channel, CHANNELS_CONFIG) or {}

        fb_target = args.fb_url or ch_cfg.get("facebook_url") or os.getenv("PAGE_URL_FB", "https://www.facebook.com/ThaiPBS/live_videos/")
        yt_target = args.yt_url or ch_cfg.get("youtube_url") or os.getenv("PAGE_URL_YT", "https://www.youtube.com/@ThaiPBS/streams")
        x_target = args.x_url or ch_cfg.get("x_url") or os.getenv("PAGE_URL_X", "https://x.com/ThaiPBS")
        tt_target = args.tt_url or ch_cfg.get("tiktok_url") or os.getenv("PAGE_URL_TT", "https://www.tiktok.com/@thaipbs/live")

        start_live_scheduler(
            script_api_url=SCRIPT_API_URL,
            facebook_url=fb_target,
            youtube_url=yt_target,
            x_url=x_target,
            page_wait_seconds_fb=PAGE_WAIT_SECONDS_FB,
            page_wait_seconds_yt=PAGE_WAIT_SECONDS_YT,
            page_wait_seconds_x=PAGE_WAIT_SECONDS_X,
            check_interval_seconds=args.interval,
            delay_minutes=args.delay,
            channel_name=args.channel,
            tiktok_url=tt_target,
            current_only=args.current_only,
            run_once=args.once,
            max_attempts=args.max_attempts,
            script_api_token=SCRIPT_API_TOKEN,
            skip_x=args.skip_x,
            skip_x_except_thaipbs=args.skip_x_except_thaipbs
        )
