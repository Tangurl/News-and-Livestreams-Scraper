"""
Unit tests for Facebook Description Matching logic in ViewStatsScraper.
Tests edge cases where video title is mistyped, copy-pasted, or generic,
verifying that the crawler can recover and match using the post description.
"""

from datetime import datetime
import sys
import os

# Add parent directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules.facebook import (
    _score_title_match,
    find_matching_video,
    extract_thai_date_from_title
)


def test_score_title_match_description():
    sig_words = ["วันใหม่ไทยพีบีเอส"]
    clean_title = "วันใหม่ไทยพีบีเอส"

    # Case 1: Title is wrong, description has hashtag #วันใหม่ไทยพีบีเอส
    card_title = "🔴 [Live] เกาะติดสถานการณ์น้ำท่วมภาคเหนือ (14 ก.ย. 69)"
    desc = "ร่วมเกาะติดสถานการณ์ข่าวเช้าในรายการ #วันใหม่ไทยพีบีเอส เวลา 06.00 น. ทาง #ThaiPBS"

    matched, score, reason = _score_title_match(card_title, clean_title, sig_words, desc_text=desc)
    assert matched is True, "Should match via description hashtag"
    assert reason == "desc_hashtag", f"Expected 'desc_hashtag', got '{reason}'"
    assert score == 32, f"Expected score 32, got {score}"
    print("✅ test_score_title_match_description (desc_hashtag): PASS")

    # Case 2: Title is generic, description has exact substring
    card_title = "🔴 LIVE ถ่ายทอดสด"
    desc = "ติดตามชมรายการ ตอบโจทย์ คืนนี้ ทางไทยพีบีเอส"
    matched, score, reason = _score_title_match(card_title, "ตอบโจทย์", ["ตอบโจทย์"], desc_text=desc)
    assert matched is True, "Should match via description exact text"
    assert reason == "desc_exact", f"Expected 'desc_exact', got '{reason}'"
    assert score == 28, f"Expected score 28, got {score}"
    print("✅ test_score_title_match_description (desc_exact): PASS")

    # Case 3: Title match outranks description match
    card_title = "🔴 [Live] #ตอบโจทย์ (14 ก.ย. 69)"
    desc = "รายละเอียดรายการ #ตอบโจทย์"
    matched, score, reason = _score_title_match(card_title, "ตอบโจทย์", ["ตอบโจทย์"], desc_text=desc)
    assert matched is True
    assert reason == "title_hashtag", f"Expected 'title_hashtag', got '{reason}'"
    assert score == 35, f"Expected title hashtag score 35, got {score}"
    print("✅ test_score_title_match_description (title priority over desc): PASS")


def test_find_matching_video_wrong_title_but_valid_description():
    scheduled_dt = datetime(2026, 9, 14, 6, 0)

    videos = [
        {
            "url": "https://www.facebook.com/ThaiPBS/videos/11111",
            "title": "🔴 [Live] ข่าวด่วนประเด็นร้อน (14 ก.ย. 69)",
            "description": "ติดตามสถานการณ์ข่าวเช้า #วันใหม่ไทยพีบีเอส อัปเดตทุกมุมมอง",
            "is_live": True,
            "is_ongoing_live": True,
        },
        {
            "url": "https://www.facebook.com/ThaiPBS/videos/22222",
            "title": "🔴 [Live] จับตาสถานการณ์โลก (14 ก.ย. 69)",
            "description": "สรุปข่าวต่างประเทศประจำวัน",
            "is_live": True,
            "is_ongoing_live": True,
        }
    ]

    matched = find_matching_video(
        videos=videos,
        program_title="วันใหม่ไทยพีบีเอส",
        broadcast_time="06:00",
        broadcast_date="14-09-26",
        scheduled_dt=scheduled_dt
    )

    assert matched is not None, "Should find matching video via description"
    assert matched["url"] == "https://www.facebook.com/ThaiPBS/videos/11111"
    assert "desc" in matched["match_reason"]
    print("✅ test_find_matching_video_wrong_title_but_valid_description: PASS")


def test_date_in_description_only():
    scheduled_dt = datetime(2026, 9, 14, 20, 30)

    # Video A has date in description matching today (14 ก.ย. 69)
    # Video B has date in description from yesterday (13 ก.ย. 69)
    videos = [
        {
            "url": "https://www.facebook.com/ThaiPBS/videos/yesterday",
            "title": "🔴 [Live] รายการตอบโจทย์",
            "description": "ออกอากาศสดเมื่อ (13 ก.ย. 69) เกาะติดประเด็นร้อน",
            "is_live": False,
            "was_live": True,
        },
        {
            "url": "https://www.facebook.com/ThaiPBS/videos/today",
            "title": "🔴 [Live] รายการตอบโจทย์",
            "description": "ออกอากาศสดประจำวัน (14 ก.ย. 69) วิเคราะห์สถานการณ์",
            "is_live": False,
            "was_live": True,
        }
    ]

    matched = find_matching_video(
        videos=videos,
        program_title="ตอบโจทย์",
        broadcast_time="20:30",
        broadcast_date="14-09-26",
        scheduled_dt=scheduled_dt
    )

    assert matched is not None
    assert matched["url"] == "https://www.facebook.com/ThaiPBS/videos/today", "Should pick today's video, rejecting yesterday's date"
    print("✅ test_date_in_description_only: PASS")


def test_hone_krasae_live_in_description():
    # Hone Krasae rule: must have LIVE in title or description or be ongoing live
    scheduled_dt = datetime(2026, 9, 14, 12, 0)

    videos = [
        {
            "url": "https://www.facebook.com/Ch3ThailandNews/videos/clip1",
            "title": "เปิดใจผู้เสียหาย ปมธุรกิจขายตรง",
            "description": "ไฮไลท์จากรายการโหนกระแส",
            "is_clip": True,
            "is_ongoing_live": False,
        },
        {
            "url": "https://www.facebook.com/Ch3ThailandNews/videos/live1",
            "title": "เปิดใจผู้เสียหาย ปมธุรกิจขายตรง",
            "description": "ถ่ายทอดสด #โหนกระแส วันนี้ 14 ก.ย. 69 #LIVE สด",
            "is_clip": False,
            "was_live": True,
        }
    ]

    matched = find_matching_video(
        videos=videos,
        program_title="โหนกระแส",
        broadcast_time="12:00",
        broadcast_date="14-09-26",
        scheduled_dt=scheduled_dt
    )

    assert matched is not None
    assert matched["url"] == "https://www.facebook.com/Ch3ThailandNews/videos/live1"
    print("✅ test_hone_krasae_live_in_description: PASS")


if __name__ == "__main__":
    print("Running Facebook Description Matching Tests...\n")
    test_score_title_match_description()
    test_find_matching_video_wrong_title_but_valid_description()
    test_date_in_description_only()
    test_hone_krasae_live_in_description()
    print("\n🎉 ALL FACEBOOK DESCRIPTION MATCHING TESTS PASSED!")
