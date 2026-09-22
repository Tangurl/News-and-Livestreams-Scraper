#!/usr/bin/env python3
"""
Unit tests for DD-MM-YY date parsing, 7-column layout, and 19 channels resolution.
"""

from datetime import datetime
from view_stats_scraper import parse_schedule_datetime as vs_parse_date, get_channel_config
from linkcrawler import parse_schedule_datetime as lc_parse_date, load_channels_config, resolve_channel_config

TARGET_CHANNELS = [
    "3 HD", "7 HD", "8", "9 MCOT HD", "GMM Channel", "NBT 2 HD",
    "Nation TV", "ONE", "T Sports 7", "TNN16", "True4U", "TV5 HD",
    "PPTV", "TP Channel", "Thai PBS", "AMARIN TV HD", "Workpoint TV",
    "MONO 29", "Thairath TV"
]

def test_date_parsing():
    test_cases = [
        ("03-09-26", "18:00", datetime(2026, 9, 3, 18, 0)),
        ("03/09/26", "18:00", datetime(2026, 9, 3, 18, 0)),
        ("03-09-2026", "18:00", datetime(2026, 9, 3, 18, 0)),
        ("03-09-69", "18:00", datetime(2026, 9, 3, 18, 0)),
        ("2026-09-03", "18:00", datetime(2026, 9, 3, 18, 0)),
        ("03-09-2569", "18:00", datetime(2026, 9, 3, 18, 0)),
        ("2569-09-03", "18:00", datetime(2026, 9, 3, 18, 0)),
    ]

    for date_str, time_str, expected in test_cases:
        res_vs = vs_parse_date(date_str, time_str)
        res_lc = lc_parse_date(date_str, time_str)
        assert res_vs == expected, f"view_stats_scraper failed on ({date_str}, {time_str}): got {res_vs}, expected {expected}"
        assert res_lc == expected, f"linkcrawler failed on ({date_str}, {time_str}): got {res_lc}, expected {expected}"
        print(f"✅ Date parse ({date_str} {time_str}) -> {expected.strftime('%Y-%m-%d %H:%M')}: PASS")

    print("\n🎉 ALL DATE PARSING TESTS PASSED!\n")


def test_channel_resolution():
    channels_cfg = load_channels_config()
    assert len(channels_cfg) == 19, f"Expected 19 channels in config, got {len(channels_cfg)}"

    for ch in TARGET_CHANNELS:
        cfg = resolve_channel_config(ch, channels_cfg)
        assert cfg is not None, f"Failed to resolve channel: {ch}"
        assert "facebook_url" in cfg, f"Missing facebook_url for {ch}"
        assert "youtube_url" in cfg, f"Missing youtube_url for {ch}"
        assert "x_url" in cfg, f"Missing x_url for {ch}"
        assert "tiktok_url" in cfg, f"Missing tiktok_url for {ch}"
        print(f"✅ Channel '{ch}' -> FB: {cfg['facebook_url']} | YT: {cfg['youtube_url']} | TT: {cfg['tiktok_url']}")

    print("\n🎉 ALL 19 CHANNELS RESOLVED SUCCESSFULLY!")


if __name__ == "__main__":
    test_date_parsing()
    test_channel_resolution()
