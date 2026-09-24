"""
Cache Manager for LinkCrawler & ViewStatsScraper.

Provides local-first shared caching for:
  1. Crawled stream URLs (Facebook, YouTube, X, TikTok) per channel/program.
  2. Channel schedule tables (to avoid repeated 12,000+ row fetches from Google Sheets).

Includes automatic purging of records older than 3 days to keep local disk usage minimal.
Uses atomic file writes (write-to-temp + rename) for cross-platform process safety.
"""

import json
import os
import re
import tempfile
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

# Default TTL in days for purging old records
DEFAULT_CACHE_TTL_DAYS = 3

# File names
CRAWLED_URLS_FILE = "crawled_urls.json"
SCHEDULES_CACHE_FILE = "schedules_cache.json"


def get_cache_dir() -> str:
    """
    Returns the absolute path to the cache directory.
    Creates it if it does not already exist.
    Ensures both workspace root (MonitoringLIVE/) and subfolder (ViewStatsScraper/)
    consistently share the same cache directory.
    """
    env_cache = os.environ.get("CACHE_DIR")
    if env_cache:
        os.makedirs(env_cache, exist_ok=True)
        return env_cache

    curr_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # If called from workspace root containing ViewStatsScraper, prefer ViewStatsScraper/cache
    if os.path.isdir(os.path.join(curr_dir, "ViewStatsScraper", "cache")):
        cache_dir = os.path.join(curr_dir, "ViewStatsScraper", "cache")
    else:
        cache_dir = os.path.join(curr_dir, "cache")

    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir



def _atomic_write_json(filepath: str, data: Any) -> None:
    """
    Writes data as formatted JSON using an atomic replace to prevent
    corrupted reads if another process reads concurrently.
    """
    dir_name = os.path.dirname(filepath)
    os.makedirs(dir_name, exist_ok=True)
    temp_fd, temp_path = tempfile.mkstemp(dir=dir_name, prefix="cache_", suffix=".tmp")
    try:
        with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, filepath)
    except Exception:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        raise


def _read_json_safe(filepath: str) -> Optional[Any]:
    """Reads JSON data safely, returning None if file doesn't exist or is corrupt."""
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def parse_record_date(date_str: str) -> Optional[datetime.date]:
    """
    Parses various date formats used in schedule and crawl records
    (YYYY-MM-DD, DD-MM-YYYY, DD/MM/YYYY, DD-MM-YY, etc.).
    """
    if not date_str:
        return None
    s = str(date_str).strip().replace("/", "-")
    parts = s.split("-")
    if len(parts) != 3:
        return None
    try:
        p0, p1, p2 = int(parts[0]), int(parts[1]), int(parts[2])
        if p0 > 2400:  # Buddhist Era 2569-MM-DD
            return datetime(p0 - 543, p1, p2).date()
        elif p2 > 2400:  # DD-MM-2569
            return datetime(p2 - 543, p1, p0).date()
        elif p0 > 1900:  # 2026-MM-DD
            return datetime(p0, p1, p2).date()
        elif p2 > 1900:  # DD-MM-2026
            return datetime(p2, p1, p0).date()
        else:
            # 2-digit year (e.g. 17-09-26 or 17-09-69)
            day, month = p0, p1
            year = (2500 + p2) - 543 if p2 >= 50 else 2000 + p2
            return datetime(year, month, day).date()
    except Exception:
        return None


def make_program_key(date_str: str, time_str: str, title: str) -> str:
    """Normalizes a program key for indexing: YYYY-MM-DD|HH:MM|title"""
    d_obj = parse_record_date(date_str)
    d_norm = d_obj.strftime("%Y-%m-%d") if d_obj else str(date_str).strip()
    
    t_clean = str(time_str or "").strip().replace("น.", "").replace("น", "").replace(".", ":")
    if "-" in t_clean:
        t_clean = t_clean.split("-")[0].strip()
    t_parts = t_clean.split(":")
    if len(t_parts) >= 2:
        try:
            t_norm = f"{int(t_parts[0]):02d}:{int(t_parts[1]):02d}"
        except ValueError:
            t_norm = t_clean
    else:
        t_norm = t_clean

    title_norm = re.sub(r"\s+", " ", str(title or "").strip().lower())
    return f"{d_norm}|{t_norm}|{title_norm}"


# ==============================================================================
# Crawled URLs Cache
# ==============================================================================

def purge_old_crawled_urls(data: Dict, ttl_days: int = DEFAULT_CACHE_TTL_DAYS) -> Tuple[Dict, int]:
    """
    Purges crawled URL records older than ttl_days.
    Returns (cleaned_data, purged_count).
    """
    cutoff_date = datetime.now(ZoneInfo("Asia/Bangkok")).date() - timedelta(days=ttl_days)
    purged_count = 0
    channels_dict = data.get("channels", {})
    cleaned_channels = {}

    for ch_name, prog_dict in channels_dict.items():
        surviving_progs = {}
        for p_key, info in prog_dict.items():
            item_date = parse_record_date(info.get("date"))
            # If date couldn't be parsed, check updated_at timestamp
            if not item_date and info.get("updated_at"):
                try:
                    item_date = datetime.fromisoformat(info["updated_at"]).date()
                except Exception:
                    pass

            if item_date and item_date < cutoff_date:
                purged_count += 1
                continue
            surviving_progs[p_key] = info

        if surviving_progs:
            cleaned_channels[ch_name] = surviving_progs

    data["channels"] = cleaned_channels
    return data, purged_count


def save_crawled_url(
    channel: str,
    date: str,
    time: str,
    title: str,
    facebook_url: str = "",
    youtube_url: str = "",
    x_url: str = "",
    tiktok_url: str = "",
    ttl_days: int = DEFAULT_CACHE_TTL_DAYS
) -> None:
    """
    Saves or updates crawled streaming URLs for a specific program in the local cache.
    Automatically purges records older than ttl_days (default 3 days).
    """
    if not channel or not title:
        return

    cache_path = os.path.join(get_cache_dir(), CRAWLED_URLS_FILE)
    data = _read_json_safe(cache_path) or {"channels": {}, "version": 1}

    channels_dict = data.setdefault("channels", {})
    ch_dict = channels_dict.setdefault(channel, {})

    prog_key = make_program_key(date, time, title)
    existing = ch_dict.get(prog_key, {})

    # Update with new non-empty links, retaining existing valid links
    def _pick(new_val, old_val):
        clean_new = str(new_val or "").strip()
        if clean_new and clean_new not in ("-", "NOT FOUND", "N/A"):
            return clean_new
        return old_val or clean_new

    ch_dict[prog_key] = {
        "channel": channel,
        "date": date,
        "time": time,
        "title": title,
        "facebook_url": _pick(facebook_url, existing.get("facebook_url")),
        "youtube_url": _pick(youtube_url, existing.get("youtube_url")),
        "x_url": _pick(x_url, existing.get("x_url")),
        "tiktok_url": _pick(tiktok_url, existing.get("tiktok_url")),
        "updated_at": datetime.now(ZoneInfo("Asia/Bangkok")).isoformat()
    }

    # Auto-purge records older than 3 days
    data, purged = purge_old_crawled_urls(data, ttl_days=ttl_days)
    data["last_updated"] = datetime.now(ZoneInfo("Asia/Bangkok")).isoformat()

    try:
        _atomic_write_json(cache_path, data)
    except Exception as e:
        print(f"[CacheManager Warning] Could not write crawled URLs cache: {e}")


def get_crawled_url(
    channel: str,
    date: str,
    time: str,
    title: str
) -> Optional[Dict]:
    """
    Retrieves cached crawled URLs for a program slot.
    Returns Dict with facebook_url, youtube_url, x_url, tiktok_url, or None if not found.
    """
    cache_path = os.path.join(get_cache_dir(), CRAWLED_URLS_FILE)
    data = _read_json_safe(cache_path)
    if not data or "channels" not in data:
        return None

    ch_dict = data["channels"].get(channel)
    if not ch_dict:
        # Check case-insensitive channel match
        target_ch = channel.strip().lower()
        for c_name, c_dict in data["channels"].items():
            if c_name.strip().lower() == target_ch:
                ch_dict = c_dict
                break

    if not ch_dict:
        return None

    # Exact key match
    prog_key = make_program_key(date, time, title)
    if prog_key in ch_dict:
        return ch_dict[prog_key]

    # Fuzzy match on title + date if time format slightly varied
    d_obj = parse_record_date(date)
    d_norm = d_obj.strftime("%Y-%m-%d") if d_obj else str(date).strip()
    clean_title = re.sub(r"\s+", " ", str(title or "").strip().lower())

    for k, item in ch_dict.items():
        k_item_date = parse_record_date(item.get("date"))
        k_date_norm = k_item_date.strftime("%Y-%m-%d") if k_item_date else str(item.get("date", "")).strip()
        k_title_norm = re.sub(r"\s+", " ", str(item.get("title", "")).strip().lower())

        if k_date_norm == d_norm and (clean_title == k_title_norm or clean_title in k_title_norm or k_title_norm in clean_title):
            return item

    return None


def load_all_crawled_urls() -> Dict[str, Dict[str, Dict]]:
    """
    Loads all crawled URLs grouped by channel.
    Automatically purges expired records.
    """
    cache_path = os.path.join(get_cache_dir(), CRAWLED_URLS_FILE)
    data = _read_json_safe(cache_path)
    if not data:
        return {}

    data, purged = purge_old_crawled_urls(data, ttl_days=DEFAULT_CACHE_TTL_DAYS)
    if purged > 0:
        try:
            _atomic_write_json(cache_path, data)
        except Exception:
            pass
    return data.get("channels", {})


# ==============================================================================
# Schedules Cache
# ==============================================================================

def purge_old_schedules(schedules: Dict[str, List[Dict]], ttl_days: int = DEFAULT_CACHE_TTL_DAYS) -> Tuple[Dict[str, List[Dict]], int]:
    """
    Purges schedule rows with dates older than ttl_days.
    Returns (cleaned_schedules, purged_rows_count).
    """
    cutoff_date = datetime.now(ZoneInfo("Asia/Bangkok")).date() - timedelta(days=ttl_days)
    purged_count = 0
    cleaned = {}

    for ch_name, rows in schedules.items():
        surviving = []
        for r in rows:
            r_date = parse_record_date(r.get("date"))
            if r_date and r_date < cutoff_date:
                purged_count += 1
                continue
            surviving.append(r)
        if surviving:
            cleaned[ch_name] = surviving

    return cleaned, purged_count


def save_schedules_cache(
    schedules: Dict[str, List[Dict]],
    ttl_days: int = DEFAULT_CACHE_TTL_DAYS
) -> None:
    """
    Saves channel schedules to local cache with auto-purge of rows older than ttl_days.
    """
    if not schedules:
        return

    cleaned_schedules, _ = purge_old_schedules(schedules, ttl_days=ttl_days)
    payload = {
        "saved_at": datetime.now(ZoneInfo("Asia/Bangkok")).isoformat(),
        "total_channels": len(cleaned_schedules),
        "total_rows": sum(len(v) for v in cleaned_schedules.values()),
        "schedules": cleaned_schedules
    }
    cache_path = os.path.join(get_cache_dir(), SCHEDULES_CACHE_FILE)
    try:
        _atomic_write_json(cache_path, payload)
    except Exception as e:
        print(f"[CacheManager Warning] Could not save schedules cache: {e}")


def load_schedules_cache(max_age_seconds: int = 14400) -> Optional[Dict[str, List[Dict]]]:
    """
    Loads channel schedules from local cache.
    If max_age_seconds is specified (> 0), returns None if cache is older than max_age_seconds.
    If max_age_seconds <= 0, ignores age check (useful for offline/error fallback).
    """
    cache_path = os.path.join(get_cache_dir(), SCHEDULES_CACHE_FILE)
    data = _read_json_safe(cache_path)
    if not data or "schedules" not in data:
        return None

    if max_age_seconds > 0 and data.get("saved_at"):
        try:
            saved_time = datetime.fromisoformat(data["saved_at"])
            if saved_time.tzinfo is None:
                saved_time = saved_time.replace(tzinfo=ZoneInfo("Asia/Bangkok"))
            age_sec = (datetime.now(ZoneInfo("Asia/Bangkok")) - saved_time).total_seconds()
            if age_sec > max_age_seconds:
                return None
        except Exception:
            pass

    return data.get("schedules")
