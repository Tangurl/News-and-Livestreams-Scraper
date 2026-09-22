#!/usr/bin/env python3
"""
ThaiPBS View Stats Scraper (Multi-Channel Live Monitoring)
=========================================================
Pulls active broadcast links from channel schedule tabs (e.g. "Thai PBS", "Online Data"),
determines the active on-air broadcast for the current capture time, concurrently scrapes
live view counts across Facebook, YouTube, TikTok, and X (Twitter), and appends snapshots
to the "View Stats" sheet in Google Sheets.

Column Schema in 'View Stats':
  - Column A: Date
  - Column B: Time when capturing
  - Column C: Channel's name (extracted from source sheet tab name)
  - Column D: Broadcast's name
  - Column E: Facebook's live link
  - Column F: Youtube's live link
  - Column G: TikTok's live link
  - Column H: X's live link
  - Column I: Facebook's live view count
  - Column J: Youtube's live view count
  - Column K: TikTok's live view count
  - Column L: X's live view count

Usage:
  python3 view_stats_scraper.py                    # Single snapshot run
  python3 view_stats_scraper.py --dry-run          # Print only, do not write to Google Sheets
  python3 view_stats_scraper.py --concurrency 10   # Custom concurrency per platform
  python3 view_stats_scraper.py --loop --interval 300  # Run every 5 minutes
"""

import argparse
import json
import os
import re
import ssl
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

def load_env_fallback():
    env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_file):
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip()
                    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                        v = v[1:-1]
                    os.environ.setdefault(k, v)

load_env_fallback()

from modules.sheets_writer import (
    append_view_stats_rows,
    ensure_sheet_capacity,
    fetch_all_channel_schedules,
    fetch_link_config,
)
from modules.cache_manager import (
    get_crawled_url,
    save_schedules_cache,
    load_schedules_cache,
    load_all_crawled_urls,
)
from modules.link_resolver import resolve_target_urls_for_program
from modules.utilities import is_thaipbs_channel

DEFAULT_CONCURRENCY = 10
NOT_APPLICABLE = "-"

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

CHANNELS_CONFIG = load_channels_config()

def get_channel_config(channel_name: str) -> Optional[Dict]:
    if not channel_name or not CHANNELS_CONFIG:
        return None
    if channel_name in CHANNELS_CONFIG:
        return CHANNELS_CONFIG[channel_name]
    target_clean = channel_name.strip().lower().replace(" ", "").replace("-", "").replace("_", "")
    for k, v in CHANNELS_CONFIG.items():
        k_clean = k.strip().lower().replace(" ", "").replace("-", "").replace("_", "")
        if target_clean == k_clean or target_clean in k_clean or k_clean in target_clean:
            return v
        for alias in v.get("aliases", []):
            a_clean = alias.strip().lower().replace(" ", "").replace("-", "").replace("_", "")
            if target_clean == a_clean or target_clean in a_clean or a_clean in target_clean:
                return v
    return None

# Default channel TikTok handles/profiles fallback
DEFAULT_TIKTOK_MAP = {
    "Thai PBS": "https://www.tiktok.com/@thaipbs/live",
    "Online Data": "https://www.tiktok.com/@thaipbs/live",
}

# ============================================================================
# Genre Classification Logic
# ============================================================================
_genre_predictor = None

def get_genre_classifier():
    """Lazily loads and caches the scikit-learn LinearSVC genre classifier."""
    global _genre_predictor
    if _genre_predictor is not None:
        return _genre_predictor
    try:
        import warnings
        warnings.filterwarnings("ignore")
        here = os.path.dirname(os.path.abspath(__file__))
        cand_paths = [
            os.path.join(here, "genre_classify", "genre_predict_test"),
            os.path.join(here, "ViewStatsScraper", "genre_classify", "genre_predict_test"),
            os.path.join(os.path.dirname(here), "ViewStatsScraper", "genre_classify", "genre_predict_test"),
        ]
        for p in cand_paths:
            if os.path.isdir(p) and p not in sys.path:
                sys.path.insert(0, p)
        from genre_predict import genre_predict
        _genre_predictor = genre_predict
        return _genre_predictor
    except Exception as e:
        print(f"⚠️ [Genre Predict] Failed to initialize classifier: {e}")
        return None


def classify_genre(title: str) -> str:
    """Classifies broadcast title into one of the 19 standard genres."""
    if not title or not title.strip():
        return "-"
    fn = get_genre_classifier()
    if not fn:
        return "-"
    try:
        return str(fn(title.strip())).strip()
    except Exception as e:
        print(f"⚠️ [Genre Predict] Classification failed for '{title}': {e}")
        return "-"


# ============================================================================
# 1. Schedule Time & Active Broadcast Selection Logic
# ============================================================================

def parse_schedule_datetime(date_str: str, time_str: str) -> Optional[datetime]:
    """
    Parses date and time strings from Google Sheets into a datetime object.
    Supports formats:
      - Date: 2026-09-03, 03/09/2026, 3/9/2569 (BE)
      - Time: 05:00, 05.00, 12.00-12.30 (uses start time)
    """
    try:
        date_clean = str(date_str or "").strip().replace("/", "-")
        time_clean = str(time_str or "").strip()
        if not date_clean or not time_clean:
            return None

        # Clean Thai time suffix & extract start time if range given
        time_clean = time_clean.replace("น.", "").replace("น", "").strip()
        if "-" in time_clean:
            time_clean = time_clean.split("-")[0].strip()
        time_clean = time_clean.replace(".", ":")

        time_parts = time_clean.split(":")
        if len(time_parts) < 2:
            return None

        hour = int(time_parts[0])
        minute = int(time_parts[1])

        date_parts = date_clean.split("-")
        if len(date_parts) == 3:
            p0, p1, p2 = int(date_parts[0]), int(date_parts[1]), int(date_parts[2])
            if p0 > 2400:  # 2569-09-03 (Buddhist Era)
                year, month, day = p0 - 543, p1, p2
            elif p2 > 2400:  # 03-09-2569
                year, month, day = p2 - 543, p1, p0
            elif p0 > 1900:  # 2026-09-03
                year, month, day = p0, p1, p2
            elif p2 > 1900:  # 03-09-2026
                year, month, day = p2, p1, p0
            else:
                # DD-MM-YY (e.g. 03-09-26 or 03-09-69)
                day, month = p0, p1
                if p2 >= 50:  # Buddhist Era e.g. 69 -> 2569 - 543 = 2026
                    year = (2500 + p2) - 543
                else:  # Christian Era e.g. 26 -> 2026
                    year = 2000 + p2

            return datetime(year, month, day, hour, minute)
    except Exception:
        return None


def parse_explicit_end_time(date_str: str, time_str: str) -> Optional[datetime]:
    """
    Extracts the end time if the time string contains a range (e.g. '12.00-12.30').
    """
    try:
        time_clean = str(time_str or "").strip().replace("น.", "").replace("น", "").strip()
        if "-" not in time_clean:
            return None

        parts = time_clean.split("-")
        if len(parts) < 2:
            return None

        end_part = parts[1].strip().replace(".", ":")
        end_parts = end_part.split(":")
        if len(end_parts) < 2:
            return None

        end_hour = int(end_parts[0])
        end_minute = int(end_parts[1])

        start_dt = parse_schedule_datetime(date_str, parts[0])
        if not start_dt:
            return None

        end_dt = datetime(start_dt.year, start_dt.month, start_dt.day, end_hour, end_minute)
        if end_dt < start_dt:  # Crosses midnight
            end_dt += timedelta(days=1)
        return end_dt
    except Exception:
        return None


def find_active_program_for_channel(
    rows: List[Dict],
    target_dt: Optional[datetime] = None,
    channel_name: str = ""
) -> Optional[Dict]:
    """
    Identifies the currently active broadcast for a channel at target_dt (default now).

    Rules:
      1. Parse all row dates & times into datetime objects.
      2. Filter rows for target_dt's date (or fallback to latest available date).
      3. Sort chronologically by start time.
      4. For each program i:
         - Program is active if start_dt <= target_dt < next_program.start_dt.
      5. Handles explicit durations (e.g. 12:00-12:30).
      6. If target_dt is 10:00 and program A was at 08:00 and program B at 09:00:
         Program A ended at 09:00, so program B is selected.
    """
    if not rows:
        return None

    if target_dt is None:
        target_dt = datetime.now()

    # Parse and validate datetimes for each row
    parsed_items = []
    for r in rows:
        d_val = r.get("date")
        t_val = r.get("time")
        title = r.get("title")
        if not title or not d_val or not t_val:
            continue

        s_dt = parse_schedule_datetime(str(d_val), str(t_val))
        if s_dt:
            parsed_items.append({
                **r,
                "dt": s_dt,
                "explicit_end": parse_explicit_end_time(str(d_val), str(t_val))
            })

    if not parsed_items:
        return None

    target_date = target_dt.date()

    # Filter for target date
    day_items = [p for p in parsed_items if p["dt"].date() == target_date]

    # If no items match target date, fallback to closest available date
    if not day_items:
        available_dates = sorted(list(set(p["dt"].date() for p in parsed_items)))
        # Pick the latest date before or on target_dt, or the latest available
        past_dates = [d for d in available_dates if d <= target_date]
        chosen_date = past_dates[-1] if past_dates else available_dates[-1]
        print(f"[{channel_name}] No schedule rows found for {target_date}; falling back to {chosen_date}")
        day_items = [p for p in parsed_items if p["dt"].date() == chosen_date]

    # Sort day's programs chronologically
    day_items.sort(key=lambda x: x["dt"])

    # Determine active slot
    active_program = None
    for i, prog in enumerate(day_items):
        start_time = prog["dt"]

        # Determine end time: explicit end time, or start time of next program, or default 2h
        if prog.get("explicit_end"):
            end_time = prog["explicit_end"]
        elif i + 1 < len(day_items):
            end_time = day_items[i + 1]["dt"]
        else:
            end_time = start_time + timedelta(hours=2)

        if start_time <= target_dt < end_time:
            active_program = prog
            break

    # If current time is past all scheduled programs for today, pick the last program
    if not active_program and day_items:
        if target_dt >= day_items[-1]["dt"]:
            active_program = day_items[-1]
        elif target_dt < day_items[0]["dt"]:
            # Early morning before first broadcast
            active_program = day_items[0]

    return active_program


# ============================================================================
# 2. Multi-Platform View Count Scrapers (Lightweight HTTP / No Chrome Driver)
# ============================================================================

def is_valid_url(url: Optional[str]) -> bool:
    """Checks if a string is a real web URL (not '-', 'W', 'C', or empty)."""
    if not url:
        return False
    u = str(url).strip().lower()
    return u.startswith("http://") or u.startswith("https://")


def is_direct_facebook_video_url(url: Optional[str]) -> bool:
    """
    Checks if a Facebook URL is an actual video/livestream link,
    rejecting channel/page URLs (e.g., /watch/ThaiPBS/ or /ThaiPBS/).
    """
    if not is_valid_url(url):
        return False
    u = str(url).strip()
    if re.search(r"^https?://(?:www\.|m\.)?fb\.watch/[A-Za-z0-9_-]+", u, re.IGNORECASE):
        return True
    if re.search(r"[?&]v=\d+", u):
        return True
    if re.search(r"/videos/(?:[^/?#]+/)?\d+", u):
        return True
    if re.search(r"/live/(?:videos/)?\d+", u):
        return True
    if "video.php" in u and re.search(r"[?&]v=\d+", u):
        return True
    return False


def is_direct_youtube_video_url(url: Optional[str]) -> bool:
    """
    Checks if a YouTube URL is an actual video/livestream link,
    rejecting channel/streams tab URLs (e.g., /@channel/streams).
    """
    if not is_valid_url(url):
        return False
    u = str(url).strip()
    if "watch?v=" in u:
        return True
    if re.search(r"^https?://youtu\.be/[A-Za-z0-9_-]+", u, re.IGNORECASE):
        return True
    if re.search(r"youtube\.com/(?:live|embed|v)/[A-Za-z0-9_-]+", u, re.IGNORECASE):
        return True
    return False


def scrape_facebook_views(url: str, timeout: int = 6) -> Tuple[Optional[int], str]:
    """
    Scrapes Facebook Live viewer count via Facebook's public embed plugin.
    Returns: (viewer_count, status_message)
    """
    if not is_direct_facebook_video_url(url):
        return None, NOT_APPLICABLE

    try:
        # Extract video ID
        m = re.search(r"/videos/(\d+)", url) or re.search(r"v=(\d+)", url)
        vid = m.group(1) if m else url.strip().split("/")[-1].split("?")[0]

        plugin_url = f"https://www.facebook.com/plugins/video.php?href=https%3A%2F%2Fwww.facebook.com%2Fwatch%2F%3Fv%3D{vid}&show_text=0"
        req = urllib.request.Request(
            plugin_url,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        )
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        counts = re.findall(r"viewerCount(?:&quot;|\"):(\d+)", html)
        if counts:
            return int(counts[0]), "LIVE"

        is_live = bool(re.search(r"class=\"[^\"]*_u_h\"[^\>]*>(สด|LIVE)", html, re.IGNORECASE))
        if is_live:
            return 0, "LIVE (0 views)"

        return None, "OFFLINE"
    except Exception as e:
        return None, f"ERR: {e}"


def scrape_youtube_views(url: str, timeout: int = 6) -> Tuple[Optional[int], str]:
    """
    Scrapes YouTube Live viewer count using YouTube's internal player API.
    Returns: (viewer_count, status_message)
    """
    if not is_direct_youtube_video_url(url):
        return None, NOT_APPLICABLE

    try:
        video_id = url
        if "v=" in url:
            video_id = url.split("v=")[1].split("&")[0]
        elif "youtu.be/" in url:
            video_id = url.split("youtu.be/")[1].split("?")[0]
        elif "/live/" in url:
            video_id = url.split("/live/")[1].split("?")[0]

        api_url = "https://www.youtube.com/youtubei/v1/next"
        payload = json.dumps({
            "context": {
                "client": {
                    "clientName": "WEB",
                    "clientVersion": "2.20240101.00.00",
                    "hl": "th",
                    "gl": "TH"
                }
            },
            "videoId": video_id
        }).encode("utf-8")

        req = urllib.request.Request(
            api_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            }
        )
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        contents = data.get("contents", {}).get("twoColumnWatchNextResults", {}).get("results", {}).get("results", {}).get("contents", [])
        for c in contents:
            pri = c.get("videoPrimaryInfoRenderer", {})
            if pri:
                vc_renderer = pri.get("viewCount", {}).get("videoViewCountRenderer", {})
                is_live = bool(vc_renderer.get("isLive"))
                live_count = vc_renderer.get("originalViewCount")
                if not live_count:
                    runs = vc_renderer.get("viewCount", {}).get("runs", [])
                    for r in runs:
                        t = r.get("text", "").replace(",", "").strip()
                        if t.isdigit():
                            live_count = t
                            break

                if not live_count:
                    simple_txt = vc_renderer.get("viewCount", {}).get("simpleText", "")
                    digits = re.findall(r"[\d,]+", simple_txt)
                    if digits:
                        live_count = digits[0].replace(",", "")

                if live_count:
                    clean_count = int(str(live_count).replace(",", "").strip())
                    return clean_count, "LIVE" if is_live else "RECORDED"

        return None, "NO_DATA"
    except Exception as e:
        return None, f"ERR: {e}"


def scrape_tiktok_views(url_or_handle: str, timeout: int = 6) -> Tuple[Optional[int], str]:
    """
    Scrapes TikTok Live viewer count via Webcast room info and api-live endpoints.
    Returns: (viewer_count, status_message)
    """
    if not url_or_handle or url_or_handle.strip() == NOT_APPLICABLE:
        return None, NOT_APPLICABLE

    # Extract username
    username = str(url_or_handle).strip()
    if "@" in username:
        username = username.split("@")[1].split("/")[0].split("?")[0]
    elif "tiktok.com/" in username:
        username = username.split("tiktok.com/")[1].split("/")[0].split("?")[0]

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/17.0 Mobile/15E148 Safari/604.1"
        ),
        "Referer": "https://www.tiktok.com/",
    }
    ctx = ssl._create_unverified_context()

    # Method 1: Webcast API
    try:
        webcast_url = f"https://webcast.tiktok.com/webcast/room/info_by_user/?aid=1988&app_name=tiktok_web&live_id=12&unique_id={username}"
        req = urllib.request.Request(webcast_url, headers=headers)
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8")).get("data", {})
            if data.get("status") == 2:
                vc = data.get("user_count")
                if vc is not None:
                    return int(vc), "LIVE"
    except Exception:
        pass

    # Method 2: API-Live room endpoint
    try:
        api_live_url = f"https://www.tiktok.com/api-live/user/room/?aid=1988&uniqueId={username}&sourceType=54"
        req = urllib.request.Request(api_live_url, headers=headers)
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8")).get("data", {})
            live_room = data.get("liveRoom", {})
            if live_room.get("status") == 2:
                stats = live_room.get("liveRoomStats", {})
                vc = stats.get("userCount") or live_room.get("userCount")
                if vc is not None:
                    return int(vc), "LIVE"
    except Exception:
        pass

    return None, "OFFLINE"


def scrape_x_views(url: str, timeout: int = 6, return_broadcast_url: bool = False):
    """
    Scrapes X (Twitter) broadcast live view count.
    Supports:
      1. Direct broadcast URL: https://x.com/i/broadcasts/<id>
      2. Tweet status URL: https://x.com/<user>/status/<tweet_id>
      3. Channel profile URL: https://x.com/<screen_name> (discovers currently active live broadcast)
      4. Raw broadcast ID: e.g. '1pKdRDPQMgRJW'
    Returns: (viewer_count, status_message) or (viewer_count, status_message, resolved_url)
    """
    if not is_valid_url(url) and not (isinstance(url, str) and len(url.strip()) >= 10 and "/" not in url.strip()):
        if return_broadcast_url:
            return None, NOT_APPLICABLE, None
        return None, NOT_APPLICABLE

    clean_url = url.strip()
    broadcast_id = None
    resolved_url = None
    ctx = ssl._create_unverified_context()

    try:
        # Case 1: Direct broadcast URL
        if "broadcasts/" in clean_url:
            broadcast_id = clean_url.split("broadcasts/")[1].split("?")[0].split("/")[0]
            resolved_url = f"https://x.com/i/broadcasts/{broadcast_id}"

        # Case 2: Tweet status URL
        elif "status/" in clean_url:
            tweet_match = re.search(r"status/(\d+)", clean_url)
            if tweet_match:
                tweet_id = tweet_match.group(1)
                syn_url = f"https://cdn.syndication.twimg.com/tweet-result?id={tweet_id}&token=4"
                syn_req = urllib.request.Request(syn_url, headers={"User-Agent": "Mozilla/5.0"})
                try:
                    with urllib.request.urlopen(syn_req, context=ctx, timeout=timeout) as syn_resp:
                        t_data = json.loads(syn_resp.read().decode("utf-8"))
                        text = t_data.get("text", "")
                        tco_match = re.search(r"https://t\.co/\w+", text)
                        if tco_match:
                            tco_req = urllib.request.Request(tco_match.group(0), headers={"User-Agent": "Mozilla/5.0"})
                            with urllib.request.urlopen(tco_req, context=ctx, timeout=timeout) as tco_resp:
                                final_url = tco_resp.geturl()
                                if "broadcasts/" in final_url:
                                    broadcast_id = final_url.split("broadcasts/")[1].split("?")[0].split("/")[0]
                                    resolved_url = f"https://x.com/i/broadcasts/{broadcast_id}"
                except Exception:
                    pass

        # Case 3: Profile URL (e.g. https://x.com/ThaiPBS)
        elif ("x.com/" in clean_url or "twitter.com/" in clean_url):
            screen_name = clean_url.rstrip("/").split("/")[-1].replace("@", "")
            if screen_name and screen_name.lower() not in ("home", "explore", "search", "notifications", "messages"):
                prof_url = f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{screen_name}"
                prof_req = urllib.request.Request(prof_url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
                try:
                    with urllib.request.urlopen(prof_req, context=ctx, timeout=timeout) as prof_resp:
                        html = prof_resp.read().decode("utf-8")
                        found_ids = set(re.findall(r"/i/broadcasts/([a-zA-Z0-9]{10,15})", html))
                        for b_id in found_ids:
                            chk_url = f"https://api.periscope.tv/api/v2/getBroadcastPublic?broadcast_id={b_id}"
                            chk_req = urllib.request.Request(chk_url, headers={"User-Agent": "Mozilla/5.0"})
                            try:
                                with urllib.request.urlopen(chk_req, context=ctx, timeout=3) as chk_resp:
                                    chk_data = json.loads(chk_resp.read().decode("utf-8"))
                                    if chk_data.get("broadcast", {}).get("state") == "RUNNING":
                                        broadcast_id = b_id
                                        resolved_url = f"https://x.com/i/broadcasts/{broadcast_id}"
                                        break
                            except Exception:
                                pass
                except Exception:
                    pass

        # Case 4: Raw broadcast ID
        elif len(clean_url) >= 10 and "/" not in clean_url:
            broadcast_id = clean_url
            resolved_url = f"https://x.com/i/broadcasts/{broadcast_id}"

        if not broadcast_id:
            if return_broadcast_url:
                return None, "OFFLINE", None
            return None, "OFFLINE"

        # Query Periscope public broadcast endpoint for live viewer count
        api_url = f"https://api.periscope.tv/api/v2/getBroadcastPublic?broadcast_id={broadcast_id}"
        req = urllib.request.Request(
            api_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Referer": f"https://x.com/i/broadcasts/{broadcast_id}",
            }
        )
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            bc = data.get("broadcast", {})
            state = bc.get("state", "UNKNOWN")
            n_watching = data.get("n_watching")
            n_watched = data.get("n_watched")

            if state in ("RUNNING", "LIVE"):
                count = n_watching if (n_watching is not None and n_watching > 0) else n_watched
                views = int(count) if count is not None else 0
                status = "LIVE"
            elif state in ("ENDED", "TIMED_OUT"):
                count = n_watched if n_watched is not None else n_watching
                views = int(count) if count is not None else None
                status = "ENDED"
            else:
                count = n_watching if n_watching is not None else n_watched
                views = int(count) if count is not None else None
                status = state

            if return_broadcast_url:
                return views, status, resolved_url
            return views, status

    except Exception as e:
        if return_broadcast_url:
            return None, f"ERR: {e}", resolved_url
        return None, f"ERR: {e}"


# ============================================================================
# 3. Concurrent Multi-Channel Orchestration
# ============================================================================

class ControlledScraper:
    """
    Coordinates multi-channel scraping with independent per-platform concurrency limiters.
    Ensures that at most N concurrent requests hit any single platform.
    """

    def __init__(self, max_concurrency: int = DEFAULT_CONCURRENCY, skip_x: bool = False, skip_x_except_thaipbs: bool = False):
        self.max_concurrency = max_concurrency
        self.skip_x = skip_x
        self.skip_x_except_thaipbs = skip_x_except_thaipbs
        self.fb_sem = threading.Semaphore(max_concurrency)
        self.yt_sem = threading.Semaphore(max_concurrency)
        self.tt_sem = threading.Semaphore(max_concurrency)
        self.x_sem = threading.Semaphore(max_concurrency)

    def scrape_fb(self, url: str) -> Tuple[Optional[int], str]:
        with self.fb_sem:
            return scrape_facebook_views(url)

    def scrape_yt(self, url: str) -> Tuple[Optional[int], str]:
        with self.yt_sem:
            return scrape_youtube_views(url)

    def scrape_tt(self, url_or_handle: str) -> Tuple[Optional[int], str]:
        with self.tt_sem:
            return scrape_tiktok_views(url_or_handle)

    def scrape_x(self, url: str):
        with self.x_sem:
            return scrape_x_views(url, return_broadcast_url=True)

    def scrape_channel_snapshot(
        self,
        channel_name: str,
        program: Dict,
        capture_dt: datetime,
        link_config: Optional[Dict] = None
    ) -> Dict:
        """
        Scrapes all 4 platforms for a single active broadcast on a channel.
        """
        prog_title = str(program.get("title") or "").strip()

        # Check local cache for fresh URLs discovered by LinkCrawler
        try:
            cached_urls = get_crawled_url(
                channel=channel_name,
                date=str(program.get("date", "")),
                time=str(program.get("time", "")),
                title=prog_title
            )
            if cached_urls:
                for field in ("facebook_url", "youtube_url", "x_url", "tiktok_url"):
                    c_link = cached_urls.get(field)
                    if c_link and c_link not in ("-", "NOT FOUND", "N/A"):
                        program[field] = c_link
        except Exception:
            pass

        targets = resolve_target_urls_for_program(
            channel_name=channel_name,
            program_title=prog_title,
            channels_config=CHANNELS_CONFIG,
            link_config=link_config
        )

        # FB: Use schedule sheet URL if valid direct video link, otherwise check override direct video link
        fb_raw = str(program.get("facebook_url") or "").strip()
        if is_direct_facebook_video_url(fb_raw):
            fb_url = fb_raw
        elif targets["facebook"]:
            direct_fb = next((u for u in targets["facebook"] if is_direct_facebook_video_url(u)), None)
            fb_url = direct_fb if direct_fb else NOT_APPLICABLE
        else:
            fb_url = NOT_APPLICABLE

        # YouTube: Use schedule sheet URL if valid direct video link, otherwise check override direct video link
        yt_raw = str(program.get("youtube_url") or "").strip()
        if is_direct_youtube_video_url(yt_raw):
            yt_url = yt_raw
        elif targets["youtube"]:
            direct_yt = next((u for u in targets["youtube"] if is_direct_youtube_video_url(u)), None)
            yt_url = direct_yt if direct_yt else NOT_APPLICABLE
        else:
            yt_url = NOT_APPLICABLE

        # X: Dump from sheet if valid, otherwise check resolved targets or channel default from channels.json
        should_skip_x = self.skip_x or (self.skip_x_except_thaipbs and not is_thaipbs_channel(channel_name))
        if should_skip_x:
            x_url = NOT_APPLICABLE
        else:
            x_raw = str(program.get("x_url") or "").strip()
            if is_valid_url(x_raw) and x_raw != NOT_APPLICABLE:
                x_url = x_raw
            elif targets["x"]:
                x_url = targets["x"][0]
            else:
                ch_cfg = get_channel_config(channel_name) or {}
                x_url = ch_cfg.get("x_url") or NOT_APPLICABLE

        # TikTok: Dump from sheet if valid, otherwise check resolved targets or channel default from channels.json
        tt_raw = str(program.get("tiktok_url") or "").strip()
        if is_valid_url(tt_raw):
            tt_url = tt_raw
        elif targets["tiktok"]:
            tt_url = targets["tiktok"][0]
        else:
            ch_cfg = get_channel_config(channel_name) or {}
            tt_url = ch_cfg.get("tiktok_url") or DEFAULT_TIKTOK_MAP.get(channel_name, NOT_APPLICABLE)

        # Concurrently execute platform view count scrapes (only for platforms with valid URLs)
        with ThreadPoolExecutor(max_workers=4) as executor:
            fut_fb = executor.submit(self.scrape_fb, fb_url) if fb_url != NOT_APPLICABLE else None
            fut_yt = executor.submit(self.scrape_yt, yt_url) if yt_url != NOT_APPLICABLE else None
            fut_tt = executor.submit(self.scrape_tt, tt_url) if tt_url != NOT_APPLICABLE else None
            fut_x = executor.submit(self.scrape_x, x_url) if x_url != NOT_APPLICABLE else None

            fb_views, fb_status = fut_fb.result() if fut_fb else (NOT_APPLICABLE, "N/A")
            yt_views, yt_status = fut_yt.result() if fut_yt else (NOT_APPLICABLE, "N/A")
            tt_views, tt_status = fut_tt.result() if fut_tt else (NOT_APPLICABLE, "N/A")
            
            x_res = fut_x.result() if fut_x else (NOT_APPLICABLE, "N/A", None)
            x_views, x_status = x_res[0], x_res[1]
            resolved_x_url = x_res[2] if len(x_res) > 2 else None
            if resolved_x_url and is_valid_url(resolved_x_url):
                x_url = resolved_x_url
            elif x_views is None or x_views == NOT_APPLICABLE:
                x_url = NOT_APPLICABLE

        title = program.get("title", "")
        genre = classify_genre(title)
        time_str = capture_dt.strftime("%H:%M:%S")

        return {
            "date": capture_dt.strftime("%Y-%m-%d"),
            "time": time_str,
            "capture_time": time_str,
            "channel_name": channel_name,
            "broadcast_name": title,
            "genre": genre,
            "scheduled_time": str(program.get("time") or "").strip(),
            "facebook_url": fb_url,
            "youtube_url": yt_url,
            "tiktok_url": tt_url,
            "x_url": x_url,
            "facebook_live_link": fb_url,
            "youtube_live_link": yt_url,
            "tiktok_live_link": tt_url,
            "x_live_link": x_url,
            "facebook_views": fb_views if fb_views is not None else NOT_APPLICABLE,
            "youtube_views": yt_views if yt_views is not None else NOT_APPLICABLE,
            "tiktok_views": tt_views if tt_views is not None else NOT_APPLICABLE,
            "x_views": x_views if x_views is not None else NOT_APPLICABLE,
            "_statuses": {
                "fb": fb_status,
                "yt": yt_status,
                "tt": tt_status,
                "x": x_status,
            }
        }


# ============================================================================
# 4. Main Runner & Reporter
# ============================================================================

def format_count_display(val) -> str:
    """Formats numbers with commas or displays '-'."""
    if val is None or val == NOT_APPLICABLE:
        return "-"
    if isinstance(val, (int, float)):
        return f"{int(val):,}"
    if str(val).isdigit():
        return f"{int(val):,}"
    return str(val)


def print_summary_table(snapshots: List[Dict]):
    """Pretty prints the snapshot results table to the console."""
    print("\n" + "=" * 125)
    print(f"📊 LIVE VIEW STATS SNAPSHOT | Captured at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 125)

    header = f"{'Channel':<13} | {'Genre':<11} | {'Sched':<6} | {'Broadcast Title':<22} | {'FB Views':<9} | {'YT Views':<9} | {'TikTok':<9} | {'X Views':<9}"
    print(header)
    print("-" * 125)

    for s in snapshots:
        title = s['broadcast_name']
        if len(title) > 20:
            title = title[:18] + ".."
        ch = s['channel_name']
        if len(ch) > 12:
            ch = ch[:11] + "."
        genre = s.get('genre') or '-'
        if len(genre) > 10:
            genre = genre[:9] + "."
        sched = s.get('scheduled_time') or '-'

        fb_str = format_count_display(s['facebook_views'])
        yt_str = format_count_display(s['youtube_views'])
        tt_str = format_count_display(s['tiktok_views'])
        x_str = format_count_display(s['x_views'])

        print(f"{ch:<13} | {genre:<11} | {sched:<6} | {title:<22} | {fb_str:<9} | {yt_str:<9} | {tt_str:<9} | {x_str:<9}")

    print("=" * 125)


def run_scrape_cycle(
    api_url: str,
    token: Optional[str] = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    dry_run: bool = False,
    override_time: Optional[datetime] = None,
    channel_filter: Optional[List[str]] = None,
    skip_x: bool = False,
    skip_x_except_thaipbs: bool = False,
    refresh_schedules: bool = False
) -> List[Dict]:
    """
    Executes one complete view stats collection cycle across all channels:
      1. Pulls channel schedules from Google Sheets.
      2. Finds currently active broadcast for each channel.
      3. Scrapes view counts concurrently (max N per platform).
      4. Appends result rows to Google Sheet tab "View Stats".
    """
    capture_dt = override_time if override_time else datetime.now()
    print(f"\n🚀 [View Stats] Starting capture cycle for time: {capture_dt.strftime('%Y-%m-%d %H:%M:%S')}")
    if skip_x:
        print("  • X Platform: ข้ามการดึงยอดวิวทุกช่อง (--skip-x)")
    elif skip_x_except_thaipbs:
        print("  • X Platform: ข้ามการดึงยอดวิวทุกช่อง ยกเว้นช่อง Thai PBS (--skip-x-except-thaipbs)")

    # 1. Fetch channel schedules (with smart local cache check & fallback)
    schedules_by_channel = None if refresh_schedules else load_schedules_cache(max_age_seconds=3600)
    if schedules_by_channel:
        print(f"📦 [Local Cache] Loaded channel schedules from local cache ({len(schedules_by_channel)} channels).")
    else:
        fetch_msg = "Force fetching fresh channel schedules (--refresh-schedules)..." if refresh_schedules else "Fetching channel schedules from Apps Script Web App..."
        print(f"📡 [Google Sheets] {fetch_msg}")
        schedules_by_channel = fetch_all_channel_schedules(api_url=api_url, token=token)
        if schedules_by_channel:
            try:
                save_schedules_cache(schedules_by_channel)
            except Exception:
                pass
        else:
            # Fallback to older cache if network failed (e.g. 404 / timeout / offline)
            schedules_by_channel = load_schedules_cache(max_age_seconds=0)
            if schedules_by_channel:
                print(f"📦 [Local Cache Fallback] Network request failed. Using existing local schedules cache ({len(schedules_by_channel)} channels).")

    # Check local crawled stream URLs cache
    try:
        crawled_cache = load_all_crawled_urls()
        total_cached_progs = sum(len(p) for p in crawled_cache.values())
        if total_cached_progs > 0:
            print(f"📦 [Local Cache] Crawled stream URLs available for {len(crawled_cache)} channel(s) ({total_cached_progs} program links).")
    except Exception:
        pass

    if not schedules_by_channel:
        print("⚠️ No channel schedules returned from Google Sheets or local cache. Check POST_SCRIPT_API URL.")
        return []

    # Fetch link configuration (Channel Multi-Links & Broadcast Overrides)
    print(f"⚙️ [Link Config] Loading channel links and broadcast overrides from Google Sheets...")
    link_config = fetch_link_config(api_url=api_url, token=token)
    if link_config.get("ok"):
        ch_cfg_count = len(link_config.get("channel_links", {}))
        bo_cfg_count = len(link_config.get("broadcast_overrides", []))
        print(f"  • Link config active: {ch_cfg_count} custom channel link(s), {bo_cfg_count} broadcast override(s)")

    # Filter channels if specified, and omit destination tab 'View Stats' (and any archived View Stats)
    channel_names = [
        ch for ch in schedules_by_channel.keys()
        if not ch.strip().lower().startswith("view stats")
    ]
    if channel_filter:
        channel_names = [ch for ch in channel_names if ch in channel_filter]

    print(f"📺 Discovered {len(channel_names)} active channel tabs: {', '.join(channel_names)}")

    # 2. Identify active program for each channel
    active_targets = []
    for ch_name in channel_names:
        rows = schedules_by_channel[ch_name]
        prog = find_active_program_for_channel(rows, target_dt=capture_dt, channel_name=ch_name)
        if prog:
            active_targets.append((ch_name, prog))
            print(f"  • [{ch_name}] Active slot: '{prog.get('title')}' (Scheduled: {prog.get('date')} {prog.get('time')})")
        else:
            print(f"  • [{ch_name}] No active broadcast found for {capture_dt.strftime('%Y-%m-%d %H:%M')}")

    if not active_targets:
        print("ℹ️ No active programs found across channels. Exiting cycle.")
        return []

    # 3. Concurrently scrape view counts across channels
    scraper = ControlledScraper(
        max_concurrency=concurrency,
        skip_x=skip_x,
        skip_x_except_thaipbs=skip_x_except_thaipbs
    )
    snapshots: List[Dict] = []

    # Run channel evaluations concurrently
    max_workers = min(len(active_targets), 16)
    print(f"\n⚡ Scraping view counts across {len(active_targets)} channels (concurrency limit: {concurrency}/platform)...")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(scraper.scrape_channel_snapshot, ch_name, prog, capture_dt, link_config): ch_name
            for ch_name, prog in active_targets
        }
        for fut in as_completed(futures):
            ch_name = futures[fut]
            try:
                result = fut.result()
                snapshots.append(result)
            except Exception as e:
                print(f"⚠️ [{ch_name}] Scraping failed: {e}")

    # Sort snapshots to maintain stable channel order
    snapshots.sort(key=lambda x: x["channel_name"])

    # 4. Print Summary
    print_summary_table(snapshots)

    # 5. Write to Google Sheet ("View Stats" tab in Peak View mode)
    if dry_run:
        print("💡 [Dry Run Mode] Google Sheets write skipped (--dry-run specified).")
    else:
        # Check sheet row capacity before adding new data
        print("🔍 Checking 'View Stats' row capacity...")
        cap_info = ensure_sheet_capacity(api_url=api_url, sheet_name="View Stats", min_free_rows=100, add_rows=1000, token=token)
        if cap_info.get("expanded"):
            print(f"📈 [Capacity Expanded] 'View Stats' was nearly full (< 100 free rows). Automatically added {cap_info.get('added', 1000)} rows! (Total rows: {cap_info.get('new_max')})")
        elif cap_info.get("ok"):
            print(f"📊 [Capacity OK] 'View Stats' has {cap_info.get('free_rows', 0)} free rows remaining (Total: {cap_info.get('max_rows', 0)}).")

        print(f"📝 Saving peak view counts for {len(snapshots)} channel(s) to 'View Stats' sheet...")
        success = append_view_stats_rows(api_url=api_url, rows=snapshots, token=token)
        if success:
            print("✅ Successfully updated peak stats in 'View Stats' sheet!")
        else:
            print("❌ Failed to update 'View Stats'. Please ensure App.gs has been updated in your Google Sheet.")

    return snapshots


def parse_args():
    parser = argparse.ArgumentParser(
        description="Scrapes live view counts across platforms for currently broadcasting programs and writes to 'View Stats'."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Perform scraping and print table without writing to Google Sheets."
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help=f"Maximum concurrent scrapes per platform (default: {DEFAULT_CONCURRENCY})"
    )
    parser.add_argument(
        "--time",
        type=str,
        default=None,
        help="Simulate a specific capture time (e.g. '10:00' or '2026-09-03 10:00:00') to test schedule matching."
    )
    parser.add_argument(
        "--channel",
        nargs="+",
        help="Filter for specific channel sheet tab names (e.g. --channel 'Thai PBS')"
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        default=os.getenv("VIEW_STATS_LOOP", "false").strip().lower() in ("true", "1", "yes"),
        help="Run continuously at fixed intervals (can also set VIEW_STATS_LOOP=true in .env)"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.getenv("VIEW_STATS_INTERVAL", "300")),
        help="Interval in seconds between runs when --loop is active (default: 300 = 5 minutes, can set VIEW_STATS_INTERVAL in .env)"
    )
    parser.add_argument(
        "--skip-x",
        action="store_true",
        default=os.getenv("SKIP_X", "false").strip().lower() in ("true", "1", "yes"),
        help="Skip scraping X (Twitter) for all broadcasts"
    )
    parser.add_argument(
        "--skip-x-except-thaipbs",
        "--skip-x-non-thaipbs",
        action="store_true",
        default=os.getenv("SKIP_X_EXCEPT_THAIPBS", os.getenv("SKIP_X_NON_THAIPBS", "false")).strip().lower() in ("true", "1", "yes"),
        help="Skip scraping X (Twitter) for all channels except Thai PBS"
    )
    parser.add_argument(
        "--no-facebook-login",
        "--skip-facebook-login",
        action="store_true",
        default=os.getenv("SKIP_FACEBOOK_LOGIN", "false").strip().lower() in ("true", "1", "yes"),
        help="Accepted for consistency across scripts (ViewStatsScraper uses HTTP requests without profile)."
    )
    parser.add_argument(
        "--refresh-schedules",
        "--no-cache",
        action="store_true",
        help="Force fetch fresh channel schedules directly from Google Sheets instead of using local cache"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    api_url = os.environ.get("POST_SCRIPT_API", "").strip()
    token = os.environ.get("API_TOKEN", "").strip() or None

    if not api_url:
        print("❌ Error: POST_SCRIPT_API is not set in environment or .env file.")
        sys.exit(1)

    override_dt = None
    if args.time:
        try:
            if " " in args.time:
                override_dt = datetime.strptime(args.time, "%Y-%m-%d %H:%M:%S")
            elif ":" in args.time:
                today = datetime.now()
                parts = args.time.split(":")
                override_dt = datetime(today.year, today.month, today.day, int(parts[0]), int(parts[1]))
        except Exception as e:
            print(f"❌ Invalid --time argument '{args.time}': {e}")
            sys.exit(1)

    if args.loop:
        print(f"🔄 Loop mode activated. Scraper will execute every {args.interval} seconds. Press Ctrl+C to stop.\n")
        first_cycle = True
        try:
            while True:
                try:
                    run_scrape_cycle(
                        api_url=api_url,
                        token=token,
                        concurrency=args.concurrency,
                        dry_run=args.dry_run,
                        override_time=override_dt,
                        channel_filter=args.channel,
                        skip_x=args.skip_x,
                        skip_x_except_thaipbs=args.skip_x_except_thaipbs,
                        refresh_schedules=(args.refresh_schedules and first_cycle)
                    )
                except Exception as cycle_err:
                    print(f"\n⚠️ [Loop Warning] Cycle error: {cycle_err}. Scraper will retry in {args.interval}s.")
                first_cycle = False
                print(f"\n💤 Sleeping for {args.interval}s until next capture...")
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n🛑 Scraper loop terminated by user.")
    else:
        run_scrape_cycle(
            api_url=api_url,
            token=token,
            concurrency=args.concurrency,
            dry_run=args.dry_run,
            override_time=override_dt,
            channel_filter=args.channel,
            skip_x=args.skip_x,
            skip_x_except_thaipbs=args.skip_x_except_thaipbs,
            refresh_schedules=args.refresh_schedules
        )


if __name__ == "__main__":
    main()
