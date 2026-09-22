import os
import re
import time
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from urllib.parse import urlparse, parse_qs

from selenium import webdriver
from selenium.webdriver.common.by import By

from modules.utilities import (
    THAI_MONTH_REGEX,
    create_stealth_chrome_driver,
    gregorian_year_to_be_short,
    parse_thai_date_match,
)

COMMON_STOPWORDS = {
    "thaipbs", "ไทยพีบีเอส", "live", "สด", "ถ่ายทอดสด",
    "recap", "daily", "ตอนที่", "ep", "hd", "ช่อง",
    "nation", "เนชั่น", "nationtv", "ch3", "ch7", "one31", "gmm25", "tnn", "tnn16", 
    "true4u", "pptv", "amarin", "thairath", "ช่อง3", "ช่อง7", "ช่อง8", "ช่อง9", "ช่อง11", "ch8"
}


def create_driver(headless: bool = True) -> webdriver.Chrome:
    """
    สร้างและตั้งค่า Selenium WebDriver (Chrome) สำหรับ YouTube
    ใช้ page_load_strategy='eager' เพื่อไม่ต้องรอ background subresources/ads/video prefetch โหลดจบ
    และลดปัญหา 'timeout: Timed out receiving message from renderer'
    """
    driver = create_stealth_chrome_driver(headless=headless, page_load_strategy="eager")
    driver.set_page_load_timeout(30)
    return driver


def clean_youtube_url(url: str) -> str:
    """
    จัดรูปแบบ URL วิดีโอ YouTube ให้สะอาดและเป็นมาตรฐาน
    เช่น:
    - https://www.youtube.com/watch?v=R2jQ48i9l40
    - https://youtu.be/R2jQ48i9l40 -> https://www.youtube.com/watch?v=R2jQ48i9l40
    """
    if not url:
        return ""
        
    if "youtu.be/" in url:
        vid_id = url.split("youtu.be/")[1].split("?")[0].split("&")[0]
        return f"https://www.youtube.com/watch?v={vid_id}"
        
    if "youtube.com/watch" in url:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        if "v" in qs:
            return f"https://www.youtube.com/watch?v={qs['v'][0]}"
            
    match = re.search(r"youtube\.com/live/([a-zA-Z0-9_\-]+)", url)
    if match:
        return f"https://www.youtube.com/watch?v={match.group(1)}"
        
    return url.split("&")[0]


def extract_thai_date_from_youtube_title(title: str) -> Optional[Tuple[int, int, Optional[int]]]:
    """
    ดึงวันที่ไทยจาก Title ของ YouTube Live
    โดย YouTube มักมีวันที่อยู่หลังเครื่องหมาย '|' เช่น:
    - '🔴 [Live] ทุกทิศทั่วไทย | 7 ส.ค. 69' -> (7, 8, 69)
    - '🔴 [Live] สถานีประชาชน | 7 ส.ค. 2569' -> (7, 8, 69)
    """
    if not title:
        return None
        
    # หากมีเครื่องหมาย | ให้เน้นดูข้อความหลัง |
    target_text = title
    if "|" in title:
        parts = title.split("|")
        target_text = parts[-1].strip()

    pattern = rf"(\d{{1,2}})\s*({THAI_MONTH_REGEX})(?:\s*(\d{{2,4}}))?"

    match = re.search(pattern, target_text)
    if not match and target_text != title:
        match = re.search(pattern, title)

    return parse_thai_date_match(match, normalize_short_year=True)


def scrape_youtube_streams(
    channel_streams_url: str = "https://www.youtube.com/@ThaiPBS/streams", 
    max_scrolls: int = 15, 
    load_wait_seconds: int = 5
) -> List[Dict[str, str]]:
    """
    Crawl ข้อมูลวิดีโอจากหน้า YouTube Streams (@ThaiPBS/streams)
    ดึง Title และ URL ของ Live Streams ทั้งหมด
    """
    driver = create_driver(headless=True)
    video_dict: Dict[str, Dict[str, str]] = {}
    
    try:
        print(f"[YouTube Crawler] กำลังเปิดหน้าเว็บ: {channel_streams_url}")
        try:
            driver.get(channel_streams_url)
        except Exception as e:
            if "timeout" in str(e).lower() or "renderer" in str(e).lower():
                print(f"[YouTube Crawler Warning] หน้าเว็บโหลดนานเกินกำหนด (Renderer Timeout) จะพยายามดึงข้อมูลจากเนื้อหาที่โหลดมาแล้ว...")
                try:
                    driver.execute_script("window.stop();")
                except Exception:
                    pass
            else:
                raise
        
        print(f"[YouTube Crawler] รอให้หน้าเว็บโหลดเนื้อหา ({load_wait_seconds} วินาที)...")
        time.sleep(load_wait_seconds)
        
        # เลื่อนหน้าจอลงเพื่อโหลดวิดีโอ Streams เพิ่มเติม
        for i in range(max_scrolls):
            driver.execute_script("window.scrollBy(0, 1500);")
            time.sleep(0.8)
            
        extracted_data = driver.execute_script("""
            let results = [];
            let items = document.querySelectorAll('ytd-rich-item-renderer');
            for (let it of items) {
                let links = it.querySelectorAll('a[href*="/watch"]');
                let bestTitle = "";
                let bestHref = "";
                for (let a of links) {
                    let t = (a.innerText || a.textContent || "").trim();
                    // กรอง badge ตัวเลขเวลา / LIVE / สด / Upcoming ออก
                    if (t && !t.match(/^(\\d+:)?\\d+:\\d+$/) && t !== "LIVE" && t !== "สด" && t !== "Upcoming") {
                        if (t.length > bestTitle.length) {
                            bestTitle = t;
                            bestHref = a.href;
                        }
                    }
                }
                let badgeEl = it.querySelector('ytd-thumbnail-overlay-time-status-renderer, [overlay-style], badge-shape, .badge-style-type-live-now, .yt-badge-shape-wiz--thumbnail-live, .yt-badge-shape-wiz--thumbnail-upcoming, .ytd-badge-supported-renderer');
                let badgeText = badgeEl ? (badgeEl.innerText || badgeEl.textContent || "").trim() : "";
                let overlayStyle = (badgeEl ? badgeEl.getAttribute('overlay-style') : '') || '';

                let isUpcoming = (overlayStyle === "UPCOMING") 
                    || badgeText === "Upcoming" 
                    || badgeText.includes("กำลังจะมาถึง") 
                    || badgeText.includes("รอการถ่ายทอดสด")
                    || badgeText.includes("Waiting");

                let isLive = !isUpcoming && (
                    overlayStyle === "LIVE"
                    || !!it.querySelector('[overlay-style="LIVE"], .badge-style-type-live-now, .yt-badge-shape-wiz--thumbnail-live')
                    || badgeText === "LIVE"
                    || badgeText === "สด"
                );

                if (bestTitle && bestHref) {
                    results.push({
                        title: bestTitle,
                        href: bestHref,
                        is_ongoing_live: isLive,
                        is_upcoming: isUpcoming
                    });
                }
            }
            return results;
        """)
        
        for item in extracted_data:
            title = item.get("title", "").strip()
            href = item.get("href", "").strip()
            is_ongoing_live = bool(item.get("is_ongoing_live", False))
            is_upcoming = bool(item.get("is_upcoming", False))
            if not title or not href:
                continue
                
            clean_url = clean_youtube_url(href)
            if not clean_url or "watch?v=" not in clean_url:
                continue
                
            parsed = urlparse(clean_url)
            qs = parse_qs(parsed.query)
            vid_id = qs.get("v", [""])[0] or clean_url
            
            if vid_id not in video_dict:
                video_dict[vid_id] = {
                    "title": title,
                    "url": clean_url,
                    "raw_title": title,
                    "is_ongoing_live": is_ongoing_live,
                    "is_upcoming": is_upcoming
                }
            else:
                video_dict[vid_id]["is_ongoing_live"] = video_dict[vid_id].get("is_ongoing_live", False) or is_ongoing_live
                video_dict[vid_id]["is_upcoming"] = video_dict[vid_id].get("is_upcoming", False) or is_upcoming
                
        videos = list(video_dict.values())
        return videos
        
    finally:
        driver.quit()


def normalize_youtube_title(text: str) -> str:
    """
    ปรับรูปแบบข้อความชื่อรายการ YouTube ให้อยู่ในรูปมาตรฐานสำหรับจับคู่
    """
    if not text:
        return ""
    t = text.strip()
    t = re.sub(r"🔴|🟠|\[.*?\]|\(.*?\)", "", t)
    t = t.replace("็", "๊")
    t = re.sub(r"[\s\.\-:_’'\"!|#]", "", t)
    return t.lower()


def find_matching_youtube_video(
    videos: List[Dict[str, str]], 
    program_title: str, 
    broadcast_time: Optional[str] = None, 
    broadcast_date: Optional[str] = None,
    scheduled_dt: Optional[datetime] = None,
    alternative_titles: Optional[List[str]] = None
) -> Optional[Dict[str, str]]:
    """
    ค้นหาวิดีโอ YouTube Live Streams ที่ตรงกับชื่อรายการ (Column C) หรือชื่อสำรอง (alternative_titles)
    กฎเกณฑ์การจับคู่:
    1. ตรวจสอบ 'วันที่' (อยู่หลังเครื่องหมาย '|' เช่น '| 7 ส.ค. 69') ต้องตรงกับ scheduled_dt
    2. ตรวจสอบชื่อรายการ (Title Matching): คำสำคัญหรือ Substring ของชื่อรายการหลักหรือชื่อสำรองต้องตรงกับส่วนใน Title
    """
    if not program_title or not videos:
        return None
        
    search_candidates = []
    def make_candidate(t_str: str, is_alt: bool):
        raw = t_str.strip()
        clean = normalize_youtube_title(raw)
        if not clean:
            return None
        clean_prog = re.sub(r'(?:ช่อง|ch|channel)\s*\d+.*$', '', raw, flags=re.IGNORECASE).strip()
        words = [w for w in re.split(r"[\s\(\)\-_]+", clean_prog or raw) if w]
        sig = [w for w in words if len(w) > 1 and normalize_youtube_title(w) not in COMMON_STOPWORDS]
        return {
            "raw": raw,
            "clean": clean,
            "sig_words": sig or words,
            "is_alt": is_alt
        }

    c0 = make_candidate(program_title, False)
    if c0:
        search_candidates.append(c0)

    if alternative_titles:
        for alt_raw in alternative_titles:
            if not alt_raw or not str(alt_raw).strip():
                continue
            ca = make_candidate(str(alt_raw), True)
            if ca and not any(c["clean"] == ca["clean"] for c in search_candidates):
                search_candidates.append(ca)

    if not search_candidates:
        return None

    raw_primary = program_title.strip()
    best_match = None
    highest_score = 0

    for video in videos:
        # ปฏิเสธวิดีโอที่ยังอยู่ในสถานะ Waiting / Upcoming (ยังไม่เริ่มถ่ายทอดสดจริง)
        if video.get("is_upcoming", False):
            continue

        yt_title = video.get("title", "")
        
        # 1. ตรวจสอบวันที่ (Strict Date Verification)
        if scheduled_dt:
            target_day = scheduled_dt.day
            target_month = scheduled_dt.month
            target_ce_short = scheduled_dt.year % 100
            target_be_short = gregorian_year_to_be_short(scheduled_dt.year)
            
            yt_date = extract_thai_date_from_youtube_title(yt_title)
            if yt_date:
                day, month, year = yt_date
                # วันและเดือนต้องตรงกัน
                if day != target_day or month != target_month:
                    continue
                # หากมีปีระบุ ปีต้องตรงกันทั้งแบบ ค.ศ. หรือ พ.ศ.
                if year is not None:
                    valid_years = {target_ce_short, target_be_short, scheduled_dt.year, scheduled_dt.year + 543}
                    if year not in valid_years and (year % 100) not in valid_years:
                        continue
            else:
                # หากไม่พบวันที่ในชื่อ วิดีโอนี้ต้องเป็น Ongoing Live ที่กำลังถ่ายทอดสดอยู่จริง ณ ขณะนี้เท่านั้น
                # ห้ามยอมรับวิดีโอที่จบไปแล้วโดยไม่มีวันที่ เพราะจะทำให้จับคู่วิดีโอของเมื่อวานหรือวันก่อนหน้า
                if not video.get("is_ongoing_live", False):
                    continue

        # หากเป็นรายการ 'โหนกระแส' ต้องมีคำว่า "LIVE" ในชื่อวิดีโอเท่านั้น เพื่อป้องกันการจับคู่คลิป/ไฮไลท์ย้อนหลัง
        if "โหนกระแส" in raw_primary:
            if not re.search(r'(?:^|[^a-z0-9])live(?:[^a-z0-9]|$)', yt_title, re.IGNORECASE):
                continue

        # 2. ตรวจสอบชื่อรายการ (Title Matching)
        # แบ่งส่วนประกอบของ YouTube Title ตาม |
        parts = yt_title.split("|")
        norm_parts = [normalize_youtube_title(p) for p in parts]
        norm_full_title = normalize_youtube_title(yt_title)
        
        matched_candidate = None
        best_cand_score = 0
        best_cand_reason = ""

        for cand in search_candidates:
            c_score = 0
            c_matched = False
            clean_search_title = cand["clean"]
            sig_words = cand["sig_words"]

            if clean_search_title in norm_parts or clean_search_title == norm_full_title:
                c_score += 100
                c_matched = True
            elif any(clean_search_title in np for np in norm_parts if np and len(clean_search_title) >= 3):
                c_score += 85
                c_matched = True
            elif len(clean_search_title) >= 4 and clean_search_title in norm_full_title:
                c_score += 80
                c_matched = True
            else:
                # ตรวจสอบการตรงกันของ Sig words
                matched_words = 0
                for w in sig_words:
                    norm_w = normalize_youtube_title(w)
                    if norm_w and (norm_w in norm_full_title or any(norm_w in np for np in norm_parts)):
                        matched_words += 1
                if len(sig_words) == 1 and matched_words == 1:
                    c_score += 60
                    c_matched = True
                elif len(sig_words) == 2 and matched_words == 2:
                    c_score += 70
                    c_matched = True
                elif len(sig_words) >= 3:
                    if matched_words >= len(sig_words):
                        c_score += 70
                        c_matched = True
                    elif matched_words >= len(sig_words) - 1:
                        c_score += 40 * (matched_words / len(sig_words))
                        c_matched = True

            if c_matched:
                adj_score = c_score if not cand["is_alt"] else (c_score - 1)
                if adj_score > best_cand_score:
                    best_cand_score = adj_score
                    matched_candidate = cand
                    best_cand_reason = f"alt:{cand['raw']}" if cand["is_alt"] else "primary"

        # หากชื่อรายการไม่ตรงเลย (ไม่มีคำสำคัญตรงตามเกณฑ์) ปฏิเสธวิดีโอนี้ทันที ไม่จับคู่มั่ว
        if not matched_candidate:
            continue

        score = best_cand_score

        # ให้คะแนนพิเศษแก่วิดีโอที่กำลัง LIVE อยู่จริง ณ ขณะนี้ (+50)
        if video.get("is_ongoing_live", False):
            score += 50

        if score > highest_score and score >= 50:
            highest_score = score
            best_match = dict(video)
            best_match["match_reason"] = best_cand_reason

    return best_match
