"""Tests qs_s3_gap_vaso (sin S3/BQ reales)."""

from __future__ import annotations

import os
import unittest
from datetime import date
from unittest.mock import patch

from gap_utils import GAP_SYNC_MODE, is_legacy_miss, resolve_gap_target_date


class ResolveGapTargetDateTests(unittest.TestCase):
    def test_from_env(self) -> None:
        with patch.dict(os.environ, {"GAP_TARGET_DATE": "2026-09-07"}, clear=False):
            self.assertEqual(resolve_gap_target_date({}), date(2026, 9, 7))

    def test_missing_raises(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                resolve_gap_target_date({})


class LegacyMissTests(unittest.TestCase):
    def test_audio_ext(self) -> None:
        self.assertTrue(
            is_legacy_miss({"ext": "audio", "prefix": "UTP423"})
        )

    def test_prefix_5(self) -> None:
        self.assertTrue(is_legacy_miss({"ext": "mp3", "prefix": "65AG6"}))

    def test_prefix_7(self) -> None:
        self.assertTrue(is_legacy_miss({"ext": "webm", "prefix": "105AG41"}))

    def test_prefix_6_ok_for_legacy(self) -> None:
        self.assertFalse(is_legacy_miss({"ext": "mp3", "prefix": "105AG4"}))

    def test_sync_mode(self) -> None:
        self.assertEqual(GAP_SYNC_MODE, "gap_fill")


if __name__ == "__main__":
    unittest.main()
