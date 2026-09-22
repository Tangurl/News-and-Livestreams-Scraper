import json
import ssl
import time
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

try:
    import requests
    _session = requests.Session()
    _session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "Accept": "application/json, text/plain, */*"
    })
    HAS_REQUESTS = True
except ImportError:
    _session = None
    HAS_REQUESTS = False

# ค่าที่แสดงแทน "ไม่พบลิงก์" เมื่อเขียนลง Google Sheet / CSV (ตามที่ผู้ใช้กำหนด)
NOT_FOUND_DISPLAY = "-"


class AppsScriptRedirectHandler(urllib.request.HTTPRedirectHandler):
    """
    Handles 302/303 redirects from Google Apps Script Web Apps.
    Google redirects POST requests to an echo endpoint on script.googleusercontent.com,
    which must be requested via GET without the POST payload.
    """
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return urllib.request.Request(
            newurl,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
                "Accept": "application/json, text/plain, */*"
            }
        )


def _get_opener():
    ctx = ssl._create_unverified_context()
    https_handler = urllib.request.HTTPSHandler(context=ctx)
    return urllib.request.build_opener(AppsScriptRedirectHandler, https_handler)


def _http_get_json(url: str, params: Optional[Dict] = None, timeout: int = 30) -> Dict:
    if HAS_REQUESTS and _session:
        try:
            # Clear cookies to prevent Google account/session pollution
            _session.cookies.clear()
            resp = _session.get(url, params=params, timeout=timeout, allow_redirects=True)
            if resp.status_code == 200:
                return resp.json()
            else:
                resp.raise_for_status()
                return resp.json()
        except Exception:
            # Fall back to urllib
            pass

    full_url = url
    if params:
        query_str = urllib.parse.urlencode(params)
        full_url += ("&" if "?" in full_url else "?") + query_str

    req = urllib.request.Request(
        full_url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "Accept": "application/json, text/plain, */*"
        }
    )
    opener = _get_opener()
    with opener.open(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8")
        return json.loads(text)


def _http_post_json(url: str, payload: Dict, timeout: int = 30) -> Dict:
    if HAS_REQUESTS and _session:
        try:
            # Clear cookies to prevent Google account/session pollution
            _session.cookies.clear()
            resp = _session.post(url, json=payload, timeout=timeout, allow_redirects=True)
            if resp.status_code == 200:
                return resp.json()
            else:
                resp.raise_for_status()
                return resp.json()
        except Exception:
            # Fall back to urllib
            pass

    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data_bytes,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
        }
    )
    opener = _get_opener()
    with opener.open(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8")
        return json.loads(text)


def fetch_schedule_rows(
    api_url: str,
    sheet: Optional[str] = None,
    token: Optional[str] = None,
    timeout: int = 30
) -> List[Dict]:
    """
    ดึงข้อมูลตารางเวลา (A: วันที่, B: เวลา, C: ชื่อรายการ) พร้อมผลลัพธ์ที่เขียนกลับไปแล้ว
    (D: Facebook, E: YouTube, F: X, G: TikTok) จาก Google Apps Script Web App
    """
    params = {}
    if sheet:
        params["sheet"] = sheet
    if token:
        params["token"] = token

    payload = None
    try:
        payload = _http_get_json(api_url, params=params, timeout=timeout)
    except Exception:
        pass

    if not payload or (payload.get("status") != "ok" and not payload.get("ok")):
        # Fallback to POST
        try:
            post_payload = {"action": "get", "sheet": sheet or "Thai PBS", "range": "A2:G"}
            if token:
                post_payload["token"] = token
            payload = _http_post_json(api_url, post_payload, timeout=timeout)
            if payload.get("result") and "values" in payload["result"]:
                rows = []
                for idx, r in enumerate(payload["result"]["values"]):
                    if len(r) >= 3 and r[2]:
                        rows.append({
                            "row": 2 + idx,
                            "date": r[0] if len(r) > 0 else "",
                            "time": r[1] if len(r) > 1 else "",
                            "title": r[2] if len(r) > 2 else "",
                            "facebook_url": r[3] if len(r) > 3 else "-",
                            "youtube_url": r[4] if len(r) > 4 else "-",
                            "x_url": r[5] if len(r) > 5 else "-",
                            "tiktok_url": r[6] if len(r) > 6 else "-",
                        })
                return rows
        except Exception:
            pass

    if not payload:
        return []

    data = payload.get("data", [])
    if isinstance(data, list):
        return data
    elif isinstance(data, dict):
        first_key = list(data.keys())[0] if data else None
        return data[first_key] if first_key else []
    return []


def write_batch_row_results(
    api_url: str,
    sheet: str,
    updates: List[Dict],
    token: Optional[str] = None,
    timeout: int = 45,
    max_retries: int = 3,
) -> bool:
    """
    เขียนผลลัพธ์ลิงก์แบบ Batch (หลายแถวพร้อมกันใน 1 Request) กลับลง Google Sheet
    ผ่าน action: 'update_urls' ของ Apps Script Web App
    ช่วยลดความถี่ของ HTTP Request ป้องกันปัญหา Script Lock ชนกัน และป้องกัน Rate Limit
    พร้อมระบบ Retry แบบ Exponential Backoff (2s, 4s, ...) หากเกิดข้อผิดพลาดชั่วคราว
    """
    if not updates or not sheet:
        return True

    clean_updates = []
    for u in updates:
        fb_val = u.get("facebook_url")
        yt_val = u.get("youtube_url")
        x_val = u.get("x_url")
        tt_val = u.get("tiktok_url")
        clean_updates.append({
            "row": u.get("row"),
            "date": u.get("date", ""),
            "time": u.get("time", ""),
            "title": u.get("title", ""),
            "facebook_url": fb_val if fb_val and fb_val != "NOT FOUND" else NOT_FOUND_DISPLAY,
            "youtube_url": yt_val if yt_val and yt_val != "NOT FOUND" else NOT_FOUND_DISPLAY,
            "x_url": x_val if x_val and x_val != "NOT FOUND" else NOT_FOUND_DISPLAY,
            "tiktok_url": tt_val if tt_val and tt_val != "NOT FOUND" else NOT_FOUND_DISPLAY,
        })

    payload = {
        "action": "update_urls",
        "sheet": sheet,
        "updates": clean_updates,
    }
    if token:
        payload["token"] = token

    for attempt in range(1, max_retries + 1):
        try:
            result = _http_post_json(api_url, payload, timeout=timeout)
            if result.get("ok") or result.get("status") == "ok":
                res_data = result.get("result") if isinstance(result.get("result"), dict) else result
                res_updates = res_data.get("updated", []) if isinstance(res_data, dict) else []
                updated_count = len([x for x in res_updates if x.get("status") == "updated"]) if res_updates else len(clean_updates)
                skipped_count = len([x for x in res_updates if x.get("status") == "skipped"]) if res_updates else 0
                skip_info = f" (ข้าม {skipped_count} รายการที่ชื่อไม่ตรง)" if skipped_count > 0 else ""
                print(f"[Sheet Writer] บันทึกแบบ Batch สำเร็จ: {updated_count} รายการ ในชีท '{sheet}'{skip_info}")
                return True
            else:
                err = result.get("message") or result.get("error")
                print(f"[Sheet Writer Warning] Apps Script ส่ง error สำหรับชีท '{sheet}' (ครั้งที่ {attempt}/{max_retries}): {err}")
        except Exception as e:
            if attempt < max_retries:
                wait_sec = 2 * attempt
                print(f"[Sheet Writer Warning] บันทึกชีท '{sheet}' ล้มเหลว ({e}), กำลังลองใหม่ใน {wait_sec}s ({attempt}/{max_retries})...")
                time.sleep(wait_sec)
                continue
            print(f"[Sheet Writer Warning] บันทึกชีท '{sheet}' ล้มเหลวหลังลองครบ {max_retries} ครั้ง: {e}")

    return False


def write_row_result(
    api_url: str,
    row: int,
    date: str,
    time: str,
    title: str,
    facebook_url: str,
    youtube_url: str,
    x_url: str,
    tiktok_url: Optional[str] = None,
    sheet: Optional[str] = None,
    token: Optional[str] = None,
    timeout: int = 30,
    max_retries: int = 3,
) -> bool:
    """
    เขียนผลลัพธ์ลิงก์ของแถวหนึ่งๆ กลับลง Google Sheet ผ่าน Apps Script Web App
    (Col 4: FB, Col 5: YT, Col 6: X, Col 7: TikTok) พร้อม Retry mechanism
    """
    u = {
        "row": row,
        "date": date,
        "time": time,
        "title": title,
        "facebook_url": facebook_url,
        "youtube_url": youtube_url,
        "x_url": x_url,
        "tiktok_url": tiktok_url,
    }
    return write_batch_row_results(
        api_url=api_url,
        sheet=sheet or "Default",
        updates=[u],
        token=token,
        timeout=timeout,
        max_retries=max_retries
    )


def fetch_all_channel_schedules(api_url: str, token: Optional[str] = None, timeout: int = 60) -> Dict[str, List[Dict]]:
    """
    ดึงตารางเวลาของทุกช่องจาก Google Apps Script Web App
    คืนค่าเป็น Dict: { "Channel Name": [ { row, date, time, title, facebook_url, ... }, ... ] }
    """
    params = {}
    if token:
        params["token"] = token

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            payload = _http_get_json(api_url, params=params, timeout=timeout)
            if payload.get("status") == "ok" or payload.get("ok"):
                data = payload.get("data", {})
                if isinstance(data, dict):
                    return data
                elif isinstance(data, list):
                    sheet_name = payload.get("sheet_name") or "Default"
                    return {sheet_name: data}
        except Exception as e:
            if attempt < max_retries:
                wait_sec = 2 * attempt
                print(f"[Warning] GET request timed out or failed ({e}), retrying in {wait_sec}s ({attempt}/{max_retries})...")
                time.sleep(wait_sec)
                continue
            print(f"[Warning] GET failed after {max_retries} attempts ({e}), trying POST fallback...")

    # Fallback to POST if GET is disabled or failed
    try:
        payload = _http_post_json(api_url, {"action": "get_all"}, timeout=timeout)
        if payload.get("status") == "ok" or payload.get("ok"):
            data = payload.get("data", {})
            if isinstance(data, dict):
                return data
    except Exception as post_err:
        print(f"[Warning] POST fallback also failed: {post_err}")

    return {}


def ensure_sheet_capacity(
    api_url: str,
    sheet_name: str = "View Stats",
    min_free_rows: int = 100,
    add_rows: int = 1000,
    token: Optional[str] = None,
    timeout: int = 30
) -> Dict:
    """
    ตรวจสอบว่าชีท (ดีฟอลต์ 'View Stats') มีแถวว่างเหลือเพียงพอหรือไม่
    หากเหลือแถวว่างน้อยกว่า min_free_rows จะสั่งให้ Apps Script เพิ่มแถวใหม่อัตโนมัติ (ดีฟอลต์ 1,000 แถว)
    ป้องกันข้อผิดพลาดแผ่นงานเต็ม (Coordinates or dimensions out of bounds)
    """
    payload = {
        "action": "ensure_capacity",
        "sheet": sheet_name,
        "min_free_rows": min_free_rows,
        "add_rows": add_rows
    }
    if token:
        payload["token"] = token

    try:
        res = _http_post_json(api_url, payload, timeout=timeout)
        if res.get("ok"):
            result_data = res.get("result", {})
            if result_data.get("expanded"):
                print(f"📈 [Sheet Capacity] ชีท '{sheet_name}' ใกล้เต็ม (แถวว่างเหลือ {result_data.get('free_rows', 0)} แถว < {min_free_rows}): ระบบได้เพิ่ม {result_data.get('added', add_rows)} แถวใหม่เรียบร้อย (รวม {result_data.get('new_max')} แถว)")
            return result_data
    except Exception as e:
        # ไม่ขัดจังหวะการทำงานหลัก หาก Apps Script เวอร์ชั่นเก่ายังไม่มี action นี้
        pass
    return {}


def append_view_stats_rows(
    api_url: str,
    rows: List[Dict],
    token: Optional[str] = None,
    timeout: int = 60
) -> bool:
    """
    บันทึกยอดวิวแบบ Peak View (One row per broadcast per day) ลงชีท 'View Stats' ผ่าน Apps Script Web App
    จะทำการอัปเดตเฉพาะเมื่อยอดวิวมากกว่ายอดวิวเดิมในชีทเท่านั้น โดยแยกยอดพีคและเวลาพีคของแต่ละแพลตฟอร์มอิสระต่อกัน
    พร้อมระบบตรวจสอบและเพิ่มแถวใหม่อัตโนมัติ (1,000 แถว) ก่อนบันทึกเมื่อชีทใกล้เต็ม
    """
    if not rows:
        return True

    # ตรวจสอบพื้นที่ว่างของชีท 'View Stats' ก่อนบันทึกข้อมูล (เพิ่ม 1000 แถวล่วงหน้าถ้าเหลือน้อยกว่า 100 แถว)
    try:
        ensure_sheet_capacity(api_url=api_url, sheet_name="View Stats", min_free_rows=100, add_rows=1000, token=token)
    except Exception:
        pass

    payload = {
        "action": "append_view_stats",
        "rows": rows
    }
    if token:
        payload["token"] = token

    try:
        result = _http_post_json(api_url, payload, timeout=timeout)

        if not result.get("ok") and result.get("status") != "ok":
            err_msg = str(result.get("message") or result.get("error") or "")
            # กรณีเจอข้อผิดพลาดแถวเต็ม (Coordinates or dimensions out of bounds)
            # ให้สั่งขยายชีททันที 1,000 แถว แล้วลองส่งข้อมูลซ้ำอีก 1 ครั้งอัตโนมัติ
            if "coordinates or dimensions" in err_msg.lower() or "out of bounds" in err_msg.lower():
                print(f"[View Stats Writer] ตรวจพบชีทเต็ม ({err_msg}) กำลังสั่งเพิ่ม 1,000 แถวและลองบันทึกใหม่อีกครั้ง...")
                ensure_sheet_capacity(api_url=api_url, sheet_name="View Stats", min_free_rows=0, add_rows=1000, token=token)
                result = _http_post_json(api_url, payload, timeout=timeout)

            if not result.get("ok") and result.get("status") != "ok":
                print(f"[View Stats Writer] Apps Script ส่ง error กลับมา: {result.get('message') or result.get('error')}")
                return False

        res = result.get("result")
        if isinstance(res, dict):
            updated = res.get("updated", 0)
            inserted = res.get("inserted", 0)
            preserved = res.get("preserved", 0)
            total = res.get("total_rows", len(rows))
            free_info = f", แถวว่างเหลือ {res.get('free_rows')}" if res.get("free_rows") is not None else ""
            print(f"[View Stats Writer] บันทึกยอดวิวแบบ Peak View สำเร็จ: เพิ่มใหม่ {inserted} รายการ, อัปเดตยอดพีค {updated} รายการ, คงเดิม {preserved} รายการ (รวม {total} รายการ{free_info})")
        else:
            appended_count = result.get("appended", len(rows))
            print(f"[View Stats Writer] บันทึก {appended_count} รายการลงชีท 'View Stats' สำเร็จ")
        return True
    except Exception as e:
        print(f"[Warning] ไม่สามารถบันทึกข้อมูลลงชีท 'View Stats' ผ่าน Apps Script API ได้: {e}")
        return False


def fetch_link_config(api_url: str, token: Optional[str] = None, timeout: int = 30) -> Dict:
    """
    ดึงการตั้งค่า Channel_Links และ Broadcast_Overrides จาก Google Apps Script Web App
    คืนค่าเป็น Dict: { "channel_links": {...}, "broadcast_overrides": [...] }
    """
    params = {"action": "get_link_config"}
    if token:
        params["token"] = token
    try:
        payload = _http_get_json(api_url, params=params, timeout=timeout)
        if payload.get("ok"):
            return payload
    except Exception:
        pass

    # Fallback to POST
    try:
        body = {"action": "get_link_config"}
        if token:
            body["token"] = token
        payload = _http_post_json(api_url, body, timeout=timeout)
        if payload.get("ok"):
            return payload
    except Exception as e:
        print(f"[Warning] ไม่สามารถโหลดการตั้งค่าลิงก์จาก Apps Script: {e}")

    return {"ok": False, "channel_links": {}, "broadcast_overrides": []}
