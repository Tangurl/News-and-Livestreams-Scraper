#!/usr/bin/env python3
"""
Unit test for Peak View tracking logic across platforms (Facebook, YouTube, TikTok, X).
Validates:
  1. View count parsing rules (handles '-', integers, formatted strings with commas, '0').
  2. 17-column schema order and column mapping (including Col D: หมวดหมู่ and Col E: เวลาเริ่มในผัง).
  3. Independent platform peaks: FB peak increases -> FB time & view update, TT decreases -> TT time & view remain untouched.
"""

def parse_view_count(val):
    if val is None:
        return -1
    if isinstance(val, (int, float)):
        return int(val)
    s = str(val).replace(",", "").strip()
    if s == "" or s == "-" or s.upper() == "N/A" or s == "NOT FOUND":
        return -1
    try:
        return int(s)
    except ValueError:
        return -1


def simulate_upsert_view_stats(existing_rows, incoming_snapshots):
    """
    Python simulation of Apps Script upsertViewStats_ logic to verify behavior.
    Columns:
      0: วันที่ (Date)
      1: ช่อง (Channel)
      2: ชื่อรายการ (Broadcast Title)
      3: หมวดหมู่ (Genre)
      4: เวลาเริ่มในผัง (Scheduled Time)
      5: Facebook (Link)
      6: YouTube (Link)
      7: TikTok (Link)
      8: X (Twitter) (Link)
      9: Facebook Peak Time
      10: Facebook Peak View
      11: YouTube Peak Time
      12: YouTube Peak View
      13: TikTok Peak Time
      14: TikTok Peak View
      15: X Peak Time
      16: X Peak View
    """
    rows = [list(r) for r in existing_rows]
    index_map = {}
    for idx, r in enumerate(rows):
        key = f"{str(r[0]).strip()}___{str(r[1]).strip().lower()}___{str(r[2]).strip().lower()}"
        if key not in index_map:
            index_map[key] = idx

    for item in incoming_snapshots:
        r_date = str(item.get("date", "")).strip()
        r_ch = str(item.get("channel_name", "")).strip()
        r_title = str(item.get("broadcast_name", "")).strip()
        r_genre = str(item.get("genre", "")).strip()
        r_sched = str(item.get("scheduled_time", "")).strip()
        r_time = str(item.get("capture_time", "")).strip()

        fb_link = item.get("facebook_url", "-")
        yt_link = item.get("youtube_url", "-")
        tt_link = item.get("tiktok_url", "-")
        x_link = item.get("x_url", "-")

        fb_views = parse_view_count(item.get("facebook_views"))
        yt_views = parse_view_count(item.get("youtube_views"))
        tt_views = parse_view_count(item.get("tiktok_views"))
        x_views = parse_view_count(item.get("x_views"))

        key = f"{r_date}___{r_ch.lower()}___{r_title.lower()}"

        if key in index_map:
            target = rows[index_map[key]]

            # Update genre if empty
            if r_genre and (not target[3] or target[3] == "-"):
                target[3] = r_genre

            # Update scheduled time if empty
            if r_sched and (not target[4] or target[4] == "-"):
                target[4] = r_sched

            # Update links if newly found
            if fb_link and fb_link != "-" and target[5] == "-":
                target[5] = fb_link
            if yt_link and yt_link != "-" and target[6] == "-":
                target[6] = yt_link
            if tt_link and tt_link != "-" and target[7] == "-":
                target[7] = tt_link
            if x_link and x_link != "-" and target[8] == "-":
                target[8] = x_link

            # FB Peak
            cur_fb_peak = parse_view_count(target[10])
            if fb_views >= 0 and (cur_fb_peak < 0 or fb_views > cur_fb_peak):
                target[9] = r_time
                target[10] = fb_views

            # YT Peak
            cur_yt_peak = parse_view_count(target[12])
            if yt_views >= 0 and (cur_yt_peak < 0 or yt_views > cur_yt_peak):
                target[11] = r_time
                target[12] = yt_views

            # TikTok Peak
            cur_tt_peak = parse_view_count(target[14])
            if tt_views >= 0 and (cur_tt_peak < 0 or tt_views > cur_tt_peak):
                target[13] = r_time
                target[14] = tt_views

            # X Peak
            cur_x_peak = parse_view_count(target[16])
            if x_views >= 0 and (cur_x_peak < 0 or x_views > cur_x_peak):
                target[15] = r_time
                target[16] = x_views
        else:
            new_row = [
                r_date,
                r_ch,
                r_title,
                r_genre or "-",
                r_sched or "-",
                fb_link or "-",
                yt_link or "-",
                tt_link or "-",
                x_link or "-",
                r_time if fb_views >= 0 else "-",
                fb_views if fb_views >= 0 else "-",
                r_time if yt_views >= 0 else "-",
                yt_views if yt_views >= 0 else "-",
                r_time if tt_views >= 0 else "-",
                tt_views if tt_views >= 0 else "-",
                r_time if x_views >= 0 else "-",
                x_views if x_views >= 0 else "-",
            ]
            rows.append(new_row)
            index_map[key] = len(rows) - 1

    return rows


def test_parsing_and_schema():
    assert parse_view_count(None) == -1
    assert parse_view_count("-") == -1
    assert parse_view_count("N/A") == -1
    assert parse_view_count("NOT FOUND") == -1
    assert parse_view_count(0) == 0
    assert parse_view_count("0") == 0
    assert parse_view_count(1500) == 1500
    assert parse_view_count("1,500") == 1500
    assert parse_view_count(" 25,432 ") == 25432
    print("✅ test_parsing_and_schema: PASS")


def test_single_row_per_broadcast():
    existing = []
    cycle_1 = [{
        "date": "2026-09-04",
        "capture_time": "16:00:00",
        "scheduled_time": "16:00",
        "channel_name": "Thai PBS",
        "broadcast_name": "ข่าวค่ำมิติใหม่",
        "genre": "ข่าวทั่วไป",
        "facebook_url": "https://fb.com/thaipbs/live",
        "youtube_url": "https://youtube.com/thaipbs/live",
        "tiktok_url": "https://tiktok.com/@thaipbs/live",
        "x_url": "-",
        "facebook_views": 1000,
        "youtube_views": 5000,
        "tiktok_views": 3000,
        "x_views": "-",
    }]

    rows_after_1 = simulate_upsert_view_stats(existing, cycle_1)
    assert len(rows_after_1) == 1
    assert len(rows_after_1[0]) == 17, f"Expected 17 columns, got {len(rows_after_1[0])}"
    assert rows_after_1[0][0] == "2026-09-04"
    assert rows_after_1[0][1] == "Thai PBS"
    assert rows_after_1[0][2] == "ข่าวค่ำมิติใหม่"
    assert rows_after_1[0][3] == "ข่าวทั่วไป"  # หมวดหมู่ (Col D)
    assert rows_after_1[0][4] == "16:00"        # เวลาเริ่มในผัง (Col E)
    assert rows_after_1[0][5] == "https://fb.com/thaipbs/live"
    assert rows_after_1[0][6] == "https://youtube.com/thaipbs/live"
    assert rows_after_1[0][7] == "https://tiktok.com/@thaipbs/live"
    assert rows_after_1[0][8] == "-"
    assert rows_after_1[0][9] == "16:00:00"   # FB Peak Time
    assert rows_after_1[0][10] == 1000        # FB Peak View
    assert rows_after_1[0][11] == "16:00:00"  # YT Peak Time
    assert rows_after_1[0][12] == 5000        # YT Peak View
    assert rows_after_1[0][13] == "16:00:00"  # TT Peak Time
    assert rows_after_1[0][14] == 3000        # TT Peak View
    assert rows_after_1[0][15] == "-"         # X Peak Time
    assert rows_after_1[0][16] == "-"         # X Peak View
    print("✅ test_single_row_per_broadcast initial insert: PASS")

    # Cycle 2 at 17:00: FB views peak (1000 -> 1500), but TikTok drops (3000 -> 2500)
    cycle_2 = [{
        "date": "2026-09-04",
        "capture_time": "17:00:00",
        "scheduled_time": "16:00",
        "channel_name": "Thai PBS",
        "broadcast_name": "ข่าวค่ำมิติใหม่",
        "genre": "ข่าวทั่วไป",
        "facebook_url": "https://fb.com/thaipbs/live",
        "youtube_url": "https://youtube.com/thaipbs/live",
        "tiktok_url": "https://tiktok.com/@thaipbs/live",
        "x_url": "-",
        "facebook_views": 1500,  # PEAKED!
        "youtube_views": 4800,  # Dropped
        "tiktok_views": 2500,   # Dropped
        "x_views": "-",
    }]

    rows_after_2 = simulate_upsert_view_stats(rows_after_1, cycle_2)
    assert len(rows_after_2) == 1, "Must maintain only ONE row for the same broadcast today"
    row = rows_after_2[0]
    assert len(row) == 17, f"Expected 17 columns, got {len(row)}"

    # Genre and scheduled time preserved
    assert row[3] == "ข่าวทั่วไป"
    assert row[4] == "16:00"

    # Facebook SHOULD be updated to new peak
    assert row[9] == "17:00:00", f"FB Peak Time should be 17:00:00, got {row[9]}"
    assert row[10] == 1500, f"FB Peak View should be 1500, got {row[10]}"

    # YouTube and TikTok MUST PRESERVE earlier peaks and times!
    assert row[11] == "16:00:00", f"YT Peak Time must remain 16:00:00, got {row[11]}"
    assert row[12] == 5000, f"YT Peak View must remain 5000, got {row[12]}"
    assert row[13] == "16:00:00", f"TikTok Peak Time must remain 16:00:00, got {row[13]}"
    assert row[14] == 3000, f"TikTok Peak View must remain 3000, got {row[14]}"

    print("✅ test_independent_platform_peaks: PASS")


if __name__ == "__main__":
    test_parsing_and_schema()
    test_single_row_per_broadcast()
    print("\n🎉 ALL 17-COLUMN PEAK VIEW TESTS PASSED SUCCESSFULLY!")
