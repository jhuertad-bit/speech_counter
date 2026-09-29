"""Tests de parseo de nombres Ticketero → manifiesto."""

from __future__ import annotations

import unittest

from datetime import date

from audio_paths import (
    LEGACY_FILENAME_REGEX,
    gcs_key_for_audio,
    gcs_key_for_original,
    parse_audio_filename,
    split_campus_type_code,
)


class SplitCampusTypeCodeTests(unittest.TestCase):
    def test_standard_six_chars(self) -> None:
        self.assertEqual(split_campus_type_code("105AG4"), ("105", "AG4"))

    def test_missing_leading_zero(self) -> None:
        self.assertEqual(split_campus_type_code("65AG6"), ("065", "AG6"))

    def test_seven_char_type(self) -> None:
        self.assertEqual(split_campus_type_code("105AG41"), ("105", "AG41"))

    def test_eight_char_prefix(self) -> None:
        self.assertEqual(split_campus_type_code("105AG411"), ("105", "AG411"))

    def test_rejects_three_chars(self) -> None:
        self.assertIsNone(split_campus_type_code("105"))


class ParseAudioFilenameTests(unittest.TestCase):
    def test_standard_webm(self) -> None:
        parsed = parse_audio_filename("105AG4-20260907-155702.webm")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["campus"], "105")
        self.assertEqual(parsed["type_code"], "AG4")
        self.assertEqual(parsed["prefix"], "105AG4")

    def test_audio_extension(self) -> None:
        parsed = parse_audio_filename("105AG4-20260907-155702.audio")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["ext"], "audio")

    def test_five_char_prefix(self) -> None:
        parsed = parse_audio_filename("65AG6-20260907-001.mp3")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["campus"], "065")
        self.assertEqual(parsed["type_code"], "AG6")

    def test_seven_char_prefix(self) -> None:
        parsed = parse_audio_filename("105AG41-20260907-123728.mp3")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["type_code"], "AG41")

    def test_utp_style_prefix(self) -> None:
        parsed = parse_audio_filename("UTP423-20240907-234255.audio")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["campus"], "UTP")
        self.assertEqual(parsed["type_code"], "423")

    def test_qs_style_prefix(self) -> None:
        parsed = parse_audio_filename("QS005-20240907-35398.audio")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["campus"], "0QS")
        self.assertEqual(parsed["type_code"], "005")

    def test_rejects_extra_dashes(self) -> None:
        self.assertIsNone(parse_audio_filename("105AG4-20260907-155702-extra.mp3"))

    def test_rejects_missing_correlative(self) -> None:
        self.assertIsNone(parse_audio_filename("105AG4-20260907.mp3"))

    def test_rejects_invalid_date(self) -> None:
        self.assertIsNone(parse_audio_filename("105AG4-20261399-1.mp3"))

    def test_rejects_invalid_extension(self) -> None:
        self.assertIsNone(parse_audio_filename("105AG4-20260907-1.xyz"))

    def test_legacy_regex_still_works(self) -> None:
        parsed = parse_audio_filename(
            "115RA1-20260907-35398.mp3",
            LEGACY_FILENAME_REGEX,
        )
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["campus"], "115")
        self.assertEqual(parsed["type_code"], "RA1")


class GcsKeyTests(unittest.TestCase):
    def test_flac_and_original_paths(self) -> None:
        d = date(2026, 9, 7)
        prefix = "queuesmart_mp3_s3/"
        flac = gcs_key_for_audio("105AG4-20260907-155702.flac", d, prefix)
        orig = gcs_key_for_original("105AG4-20260907-155702.webm", d, prefix)
        self.assertEqual(flac, "queuesmart_mp3_s3/2026-09-07/105AG4-20260907-155702.flac")
        self.assertEqual(
            orig,
            "queuesmart_mp3_s3/2026-09-07/original/105AG4-20260907-155702.webm",
        )


if __name__ == "__main__":
    unittest.main()
