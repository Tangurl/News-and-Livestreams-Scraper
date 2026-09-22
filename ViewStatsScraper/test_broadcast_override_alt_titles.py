#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for Broadcast Overrides with alternative titles and multiple URLs.
"""
from datetime import datetime
import sys
import os

# Ensure ViewStatsScraper is in sys.path
sys.path.insert(0, os.path.dirname(__file__))

from modules.link_resolver import resolve_target_urls_for_program
from modules.facebook import find_matching_video
from modules.youtube import find_matching_youtube_video
from modules.x import find_matching_x_video


def test_link_resolver_multiline_title_and_urls():
    link_config = {
        "channel_links": {},
        "broadcast_overrides": [
            {
                "channel": "Thai PBS",
                "title": "สถานีประชาชน",
                "raw_title": "สถานีประชาชน\nสารพันลั่นทุ่งบางเขน\nทุกข์ปัญหามีทางออก",
                "facebook": "https://www.facebook.com/watch/ThaiPBS/\nhttps://www.facebook.com/watch/stationpeoples/",
                "youtube": [
                    "https://www.youtube.com/@ThaiPBS/streams",
                    "https://www.youtube.com/@ThaiPBSSpecials/streams"
                ],
                "tiktok": "https://www.tiktok.com/@thaipbs/live",
                "x": "https://x.com/ThaiPBS"
            }
        ]
    }

    # Case 1: Match with primary title
    res1 = resolve_target_urls_for_program(
        channel_name="Thai PBS",
        program_title="สถานีประชาชน",
        channels_config={},
        link_config=link_config
    )
    assert res1["is_override"] is True, "Should be recognized as override"
    assert len(res1["facebook"]) == 2, f"Expected 2 FB URLs, got {len(res1['facebook'])}"
    assert res1["facebook"][0] == "https://www.facebook.com/watch/ThaiPBS/"
    assert res1["facebook"][1] == "https://www.facebook.com/watch/stationpeoples/"
    assert len(res1["youtube"]) == 2, f"Expected 2 YT URLs, got {len(res1['youtube'])}"
    assert "สารพันลั่นทุ่งบางเขน" in res1["alternative_titles"]
    assert "ทุกข์ปัญหามีทางออก" in res1["alternative_titles"]
    print("✅ Case 1: Match primary title passed")

    # Case 2: Match with alternative title from schedule
    res2 = resolve_target_urls_for_program(
        channel_name="Thai PBS",
        program_title="สารพันลั่นทุ่งบางเขน",
        channels_config={},
        link_config=link_config
    )
    assert res2["is_override"] is True, "Alternative title should match override"
    assert len(res2["facebook"]) == 2
    assert "สถานีประชาชน" in res2["alternative_titles"]
    print("✅ Case 2: Match alternative title from schedule passed")


def test_link_resolver_separate_alt_titles_column():
    link_config = {
        "channel_links": {},
        "broadcast_overrides": [
            {
                "channel": "Thai PBS",
                "title": "สถานีประชาชน",
                "alternative_titles": ["สารพันลั่นทุ่งบางเขน", "ทุกข์ปัญหามีทางออก"],
                "facebook": [
                    "https://www.facebook.com/watch/ThaiPBS/",
                    "https://www.facebook.com/watch/stationpeoples/"
                ]
            }
        ]
    }

    res = resolve_target_urls_for_program(
        channel_name="Thai PBS",
        program_title="สถานีประชาชน",
        channels_config={},
        link_config=link_config
    )
    assert res["is_override"] is True
    assert "สารพันลั่นทุ่งบางเขน" in res["alternative_titles"]
    assert "ทุกข์ปัญหามีทางออก" in res["alternative_titles"]
    assert len(res["facebook"]) == 2

    # Match when schedule has the alternative title
    res_alt = resolve_target_urls_for_program(
        channel_name="Thai PBS",
        program_title="ทุกข์ปัญหามีทางออก",
        channels_config={},
        link_config=link_config
    )
    assert res_alt["is_override"] is True
    assert "สถานีประชาชน" in res_alt["alternative_titles"]
    assert len(res_alt["facebook"]) == 2
    print("✅ Case 2b: Separate alternative_titles column passed")


def test_facebook_matching_with_alternative_titles():
    sched_dt = datetime(2026, 9, 14, 14, 5)

    # Videos on Facebook:
    # Video 1: Actual live post has title "🔴 [Live-Rerun] สารพันลั่นทุ่งบางเขน (14 ก.ย. 69)"
    # but the scheduled title is "สถานีประชาชน"
    videos = [
        {
            "url": "https://www.facebook.com/watch/live/?v=111111",
            "title": "🔴 [Live-Rerun] 13.00 น. #สารพันลั่นทุ่งบางเขน : บลูเบอร์รี่ (14 ก.ย. 69)",
            "description": "รายการเพลงลูกทุ่งยอดนิยม",
            "is_ongoing_live": True,
            "is_live": True,
            "is_clip": False
        },
        {
            "url": "https://www.facebook.com/watch/live/?v=222222",
            "title": "ข่าวค่ำ มิติใหม่ทั่วไทย (14 ก.ย. 69)",
            "description": "",
            "is_ongoing_live": True,
            "is_live": True,
            "is_clip": False
        }
    ]

    # Without alternative_titles, "สถานีประชาชน" should NOT match Video 1
    match_without = find_matching_video(
        videos=videos,
        program_title="สถานีประชาชน",
        scheduled_dt=sched_dt
    )
    assert match_without is None, "Should not match without alternative titles"

    # With alternative_titles=["สารพันลั่นทุ่งบางเขน"], it SHOULD match Video 1
    match_with = find_matching_video(
        videos=videos,
        program_title="สถานีประชาชน",
        scheduled_dt=sched_dt,
        alternative_titles=["สารพันลั่นทุ่งบางเขน"]
    )
    assert match_with is not None, "Should match video with alternative title"
    assert match_with["url"] == "https://www.facebook.com/watch/live/?v=111111"
    assert "alt:สารพันลั่นทุ่งบางเขน" in match_with.get("match_reason", "")
    print("✅ Case 3: Facebook match with alternative title passed")


def test_youtube_matching_with_alternative_titles():
    sched_dt = datetime(2026, 9, 14, 14, 5)
    videos = [
        {
            "url": "https://www.youtube.com/watch?v=yt12345",
            "title": "🔴 LIVE | สารพันลั่นทุ่งบางเขน | 14 ก.ย. 69",
            "is_ongoing_live": True,
            "is_upcoming": False
        }
    ]

    match_with_alt = find_matching_youtube_video(
        videos=videos,
        program_title="สถานีประชาชน",
        scheduled_dt=sched_dt,
        alternative_titles=["สารพันลั่นทุ่งบางเขน"]
    )
    assert match_with_alt is not None, "YouTube should match alternative title"
    assert match_with_alt["url"] == "https://www.youtube.com/watch?v=yt12345"
    assert "alt:สารพันลั่นทุ่งบางเขน" in match_with_alt.get("match_reason", "")
    print("✅ Case 4: YouTube match with alternative title passed")


def test_x_matching_with_alternative_titles():
    sched_dt = datetime(2026, 9, 14, 14, 5)
    videos = [
        {
            "url": "https://x.com/i/broadcasts/xbroadcast123",
            "title": "ถ่ายทอดสด สารพันลั่นทุ่งบางเขน 14 ก.ย. 69 รับชมได้แล้วตอนนี้"
        }
    ]

    match_with_alt = find_matching_x_video(
        videos=videos,
        program_title="สถานีประชาชน",
        scheduled_dt=sched_dt,
        alternative_titles=["สารพันลั่นทุ่งบางเขน"]
    )
    assert match_with_alt is not None, "X should match alternative title"
    assert match_with_alt["url"] == "https://x.com/i/broadcasts/xbroadcast123"
    assert "alt:สารพันลั่นทุ่งบางเขน" in match_with_alt.get("match_reason", "")
    print("✅ Case 5: X match with alternative title passed")


if __name__ == "__main__":
    test_link_resolver_multiline_title_and_urls()
    test_link_resolver_separate_alt_titles_column()
    test_facebook_matching_with_alternative_titles()
    test_youtube_matching_with_alternative_titles()
    test_x_matching_with_alternative_titles()
    print("\n🎉 ALL 6 UNIT TESTS PASSED!")
