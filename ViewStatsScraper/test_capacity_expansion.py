#!/usr/bin/env python3
"""
Unit test for View Stats Sheet Capacity Detection and Auto-Expansion Logic.
Tests both Python client behavior (ensure_sheet_capacity & retry) and Apps Script simulation.
"""

import unittest
from unittest.mock import patch, MagicMock
from modules.sheets_writer import ensure_sheet_capacity, append_view_stats_rows


class TestSheetCapacityExpansion(unittest.TestCase):

    @patch("modules.sheets_writer._http_post_json")
    def test_ensure_sheet_capacity_healthy(self, mock_post):
        # When sheet has plenty of space (free_rows >= 100)
        mock_post.return_value = {
            "ok": True,
            "result": {
                "ok": True,
                "sheet": "View Stats",
                "expanded": False,
                "added": 0,
                "max_rows": 2000,
                "last_row": 950,
                "free_rows": 1050
            }
        }
        res = ensure_sheet_capacity("https://script.google.com/mock", sheet_name="View Stats", min_free_rows=100)
        self.assertFalse(res.get("expanded"))
        self.assertEqual(res.get("free_rows"), 1050)
        self.assertEqual(res.get("max_rows"), 2000)

    @patch("modules.sheets_writer._http_post_json")
    def test_ensure_sheet_capacity_triggers_expansion(self, mock_post):
        # When sheet is getting full (free_rows < 100)
        mock_post.return_value = {
            "ok": True,
            "result": {
                "ok": True,
                "sheet": "View Stats",
                "expanded": True,
                "added": 1000,
                "previous_max": 1000,
                "new_max": 2000,
                "last_row": 980,
                "free_rows": 1020
            }
        }
        res = ensure_sheet_capacity("https://script.google.com/mock", sheet_name="View Stats", min_free_rows=100, add_rows=1000)
        self.assertTrue(res.get("expanded"))
        self.assertEqual(res.get("added"), 1000)
        self.assertEqual(res.get("new_max"), 2000)

    @patch("modules.sheets_writer.ensure_sheet_capacity")
    @patch("modules.sheets_writer._http_post_json")
    def test_append_view_stats_out_of_bounds_auto_retry(self, mock_post, mock_ensure):
        # First call fails with coordinates or dimensions invalid (sheet full)
        # Second call succeeds
        mock_post.side_effect = [
            {"ok": False, "error": "Exception: The coordinates or dimensions of the range are invalid."},
            {"ok": True, "result": {"updated": 1, "inserted": 1, "preserved": 0, "total_rows": 1002, "max_rows": 2000, "free_rows": 998}}
        ]
        mock_ensure.return_value = {"ok": True, "expanded": True, "added": 1000}

        sample_rows = [
            {
                "date": "2026-09-14",
                "time": "14:00",
                "channel_name": "Thai PBS",
                "broadcast_name": "สถานีประชาชน",
                "facebook_views": 1500
            }
        ]

        success = append_view_stats_rows("https://script.google.com/mock", rows=sample_rows)
        self.assertTrue(success)
        self.assertEqual(mock_post.call_count, 2)


class TestAppsScriptSimulation(unittest.TestCase):
    """
    Simulates Google Apps Script ensureSheetCapacity_ and upsertViewStats_ logic.
    """

    class MockSheet:
        def __init__(self, max_rows=1000, last_row=995):
            self._max_rows = max_rows
            self._last_row = last_row
            self.data = [["Header"] * 17] + [["Row"] * 17] * (last_row - 1)

        def getMaxRows(self):
            return self._max_rows

        def getLastRow(self):
            return self._last_row

        def insertRowsAfter(self, after_pos, count):
            self._max_rows += count

        def getRange(self, start_row, start_col, num_rows, num_cols):
            end_row = start_row + num_rows - 1
            if end_row > self._max_rows:
                raise ValueError(f"The coordinates or dimensions of the range are invalid (end_row={end_row} > max_rows={self._max_rows})")
            return self

        def setValues(self, values):
            self._last_row = max(self._last_row, len(values) + 1)
            return self

        def setNumberFormat(self, fmt):
            return self

    def test_ensure_sheet_capacity_script_logic(self):
        def ensure_sheet_capacity(sh, min_free_rows=100, rows_to_add=1000):
            max_rows = sh.getMaxRows()
            last_row = sh.getLastRow()
            free_rows = max_rows - last_row
            if free_rows < min_free_rows:
                to_add = max(rows_to_add, min_free_rows - free_rows)
                sh.insertRowsAfter(max_rows, to_add)
                return {
                    "expanded": True,
                    "added": to_add,
                    "previous_max": max_rows,
                    "new_max": sh.getMaxRows(),
                    "last_row": last_row,
                    "free_rows": sh.getMaxRows() - last_row
                }
            return {
                "expanded": False,
                "added": 0,
                "max_rows": max_rows,
                "last_row": last_row,
                "free_rows": free_rows
            }

        sh = self.MockSheet(max_rows=1000, last_row=950)
        res = ensure_sheet_capacity(sh, min_free_rows=100, rows_to_add=1000)
        self.assertTrue(res["expanded"])
        self.assertEqual(res["new_max"], 2000)
        self.assertEqual(sh.getMaxRows(), 2000)

        # Running again with 2000 max rows and 950 last row
        res2 = ensure_sheet_capacity(sh, min_free_rows=100, rows_to_add=1000)
        self.assertFalse(res2["expanded"])

    def test_upsert_auto_expansion_prevents_crash(self):
        # Sheet has 1000 max rows, 1000 occupied rows (so sheet is 100% full)
        sh = self.MockSheet(max_rows=1000, last_row=1000)

        # Logic from updated upsertViewStats_ in App.gs:
        # 1. ensureSheetCapacity_ at start
        max_rows = sh.getMaxRows()
        last_row = sh.getLastRow()
        if max_rows - last_row < 100:
            sh.insertRowsAfter(max_rows, 1000)

        self.assertEqual(sh.getMaxRows(), 2000)

        # 2. Add new row to existingRows (total 1000 data rows -> needs 1001 rows total)
        existing_count = 1000
        needed_rows = existing_count + 1
        if sh.getMaxRows() < needed_rows + 50:
            sh.insertRowsAfter(sh.getMaxRows(), max(1000, needed_rows + 1000 - sh.getMaxRows()))

        # 3. getRange setValues does NOT throw
        sh.getRange(2, 1, existing_count, 17).setValues([["Data"] * 17] * existing_count)
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
