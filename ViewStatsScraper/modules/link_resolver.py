import os
import re
from typing import Dict, List, Optional, Tuple, Any

def normalize_key(s: Optional[str]) -> str:
    """Normalizes string for comparison by lowercasing and removing punctuation and extra spaces."""
    if not s:
        return ""
    # Remove special punctuation, normalize spaces
    cleaned = re.sub(r"[^\w\u0E00-\u0E7F]+", "", str(s).lower())
    return cleaned.strip()


def to_url_list(val: Any) -> List[str]:
    """Converts a string, list, or comma/newline-delimited text to a clean list of URLs."""
    if not val:
        return []
    if isinstance(val, list):
        items = val
    elif isinstance(val, str):
        items = re.split(r"[\r\n,]+", val)
    else:
        items = [str(val)]
    
    out = []
    seen = set()
    for item in items:
        u = str(item).strip()
        if u and u not in ("-", "N/A", "None", "NOT APPLICABLE") and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def normalize_facebook_page_url(url: str) -> str:
    """
    จัดรูปแบบ URL เพจ Facebook ให้เป็นหน้า Watch Grid (https://www.facebook.com/watch/<PageName>/)
    ซึ่งเป็นหน้าแสดงวิดีโอหลักของเพจ และแสดง Live Stream กำลังออนแอร์ไว้ที่ด้านบนสุด
    """
    import re
    from urllib.parse import urlparse, parse_qs
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


def resolve_target_urls_for_program(
    channel_name: str,
    program_title: str,
    channels_config: Optional[Dict] = None,
    link_config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Resolves the target platform URLs to monitor/crawl for a given channel and broadcast title.
    
    Hierarchy:
      1. Broadcast-level specific override (Channel + Title match in Broadcast_Overrides)
      2. Channel-wide configured links (Channel_Links in Google Sheets - supports multiple URLs)
      3. Fallback to channels.json default configuration
    
    Returns:
      {
        "facebook": [url, ...],
        "youtube": [url, ...],
        "tiktok": [url, ...],
        "x": [url, ...],
        "is_override": bool
      }
    """
    channels_config = channels_config or {}
    link_config = link_config or {}

    ch_norm = normalize_key(channel_name)
    title_norm = normalize_key(program_title)

    res = {
        "facebook": [],
        "youtube": [],
        "tiktok": [],
        "x": [],
        "is_override": False,
        "matched_override_title": None,
        "alternative_titles": [],
        "all_titles": [program_title]
    }

    # 1. Check Broadcast Overrides
    overrides = link_config.get("broadcast_overrides", []) or []
    matched_override = None
    matched_override_titles = []

    for bo in overrides:
        bo_ch = normalize_key(bo.get("channel", ""))
        if not bo_ch:
            continue
        # Check channel match
        if not (ch_norm == bo_ch or ch_norm in bo_ch or bo_ch in ch_norm):
            continue

        # Extract all titles in this override (split by newline if string, or from all_titles)
        bo_raw = bo.get("raw_title") or bo.get("title", "")
        bo_titles = []
        if isinstance(bo.get("all_titles"), list):
            bo_titles = [str(t).strip() for t in bo["all_titles"] if str(t).strip()]
        elif isinstance(bo_raw, str):
            bo_titles = [t.strip() for t in re.split(r"[\r\n]+", bo_raw) if t.strip()]

        if not bo_titles and bo.get("title"):
            bo_titles = [str(bo.get("title")).strip()]

        # Also merge alternative_titles if present (e.g. from separate column)
        alts_in_bo = bo.get("alternative_titles")
        if isinstance(alts_in_bo, list):
            for at in alts_in_bo:
                at_s = str(at).strip()
                if at_s and at_s not in bo_titles:
                    bo_titles.append(at_s)
        elif isinstance(alts_in_bo, str) and alts_in_bo.strip():
            for at in re.split(r"[\r\n]+", alts_in_bo):
                at_s = at.strip()
                if at_s and at_s not in bo_titles:
                    bo_titles.append(at_s)

        for bt in bo_titles:
            bt_norm = normalize_key(bt)
            if not bt_norm:
                continue
            if title_norm == bt_norm or (title_norm and title_norm in bt_norm) or (bt_norm and bt_norm in title_norm):
                matched_override = bo
                matched_override_titles = bo_titles
                break

        if matched_override:
            break

    if matched_override:
        fb_ov = to_url_list(matched_override.get("facebook"))
        yt_ov = to_url_list(matched_override.get("youtube"))
        tt_ov = to_url_list(matched_override.get("tiktok"))
        x_ov = to_url_list(matched_override.get("x"))

        if fb_ov:
            res["facebook"] = fb_ov
            res["is_override"] = True
        if yt_ov:
            res["youtube"] = yt_ov
            res["is_override"] = True
        if tt_ov:
            res["tiktok"] = tt_ov
            res["is_override"] = True
        if x_ov:
            res["x"] = x_ov
            res["is_override"] = True

        alt_titles = [t for t in matched_override_titles if normalize_key(t) != title_norm]
        if alt_titles or res["is_override"]:
            res["is_override"] = True
            res["matched_override_title"] = matched_override_titles[0] if matched_override_titles else matched_override.get("title")
            res["alternative_titles"] = alt_titles
            res["all_titles"] = matched_override_titles

    # 2. For any platform not overridden, check Channel_Links from link_config
    channel_links_map = link_config.get("channel_links", {}) or {}
    ch_sheet_links = None
    if channel_name in channel_links_map:
        ch_sheet_links = channel_links_map[channel_name]
    else:
        for k, v in channel_links_map.items():
            if normalize_key(k) == ch_norm:
                ch_sheet_links = v
                break

    if ch_sheet_links:
        if not res["facebook"]:
            res["facebook"] = to_url_list(ch_sheet_links.get("facebook"))
        if not res["youtube"]:
            res["youtube"] = to_url_list(ch_sheet_links.get("youtube"))
        if not res["tiktok"]:
            res["tiktok"] = to_url_list(ch_sheet_links.get("tiktok"))
        if not res["x"]:
            res["x"] = to_url_list(ch_sheet_links.get("x"))

    # 3. Fallback to channels.json / channels_config
    # Find matching channel config in channels.json
    ch_cfg = channels_config.get(channel_name)
    if not ch_cfg:
        for k, v in channels_config.items():
            if normalize_key(k) == ch_norm:
                ch_cfg = v
                break
            for alias in v.get("aliases", []):
                if normalize_key(alias) == ch_norm:
                    ch_cfg = v
                    break
            if ch_cfg:
                break

    if ch_cfg:
        if not res["facebook"] and ch_cfg.get("facebook_url"):
            res["facebook"] = to_url_list(ch_cfg.get("facebook_url"))
        if not res["youtube"] and ch_cfg.get("youtube_url"):
            res["youtube"] = to_url_list(ch_cfg.get("youtube_url"))
        if not res["tiktok"] and ch_cfg.get("tiktok_url"):
            res["tiktok"] = to_url_list(ch_cfg.get("tiktok_url"))
        if not res["x"] and ch_cfg.get("x_url"):
            res["x"] = to_url_list(ch_cfg.get("x_url"))

    if res["facebook"]:
        res["facebook"] = [normalize_facebook_page_url(u) for u in res["facebook"] if u]

    return res
