"""Behavior tests and optional full reference regression, all stdlib."""
import copy
import os
from pathlib import Path
import unittest
import zipfile

import neware_extract as ne


def record(index, step, status, qchg=0.0, qdis=0.0, echg=0.0, edis=0.0, time=0):
    return ne.Record(index, 0, step, status, time, (qchg, qdis, echg, edis),
                     "2025-01-01 00:00:00", -1, index * 94)


class LogicTests(unittest.TestCase):
    def test_decimal_half_up_at_exact_ties(self):
        self.assertEqual(ne.format_value(560.125, 2), "560.13")
        self.assertEqual(ne.format_value(648.175, 2), "648.18")
        self.assertEqual(ne.format_value(467.325, 2), "467.33")
        self.assertEqual(ne.format_value(0.0002425, 6), "0.000243")

    def test_discharge_first_and_multistage_charge(self):
        # First cycle: discharge=3; charge=1 CC + 0.5 CV. Second: 2 -> 1.8.
        records = [record(1, 1, 4), record(2, 2, 2, qdis=3, edis=4),
                   record(3, 3, 4), record(4, 4, 1, qchg=1, echg=2),
                   record(5, 5, 3, qchg=0.5, echg=1), record(6, 6, 4),
                   record(7, 2, 2, qdis=2, edis=3),
                   record(8, 4, 1, qchg=1.8, echg=2.5)]
        rows, audit = ne.aggregate_records(records, 1.0)
        self.assertEqual(audit["cycle_count"], 2)
        self.assertEqual(rows[0]["charge_specific_capacity_mAh_g"], 1500)
        self.assertEqual(rows[0]["efficiency_percent"], 50)
        self.assertEqual(rows[0]["charge_energy_Wh"], 0.003)
        self.assertAlmostEqual(rows[1]["capacity_retention_percent"], 200 / 3)

    def test_cumulative_points_are_not_summed(self):
        rows, _ = ne.aggregate_records([record(1, 1, 2, qdis=1, time=1),
                                       record(2, 1, 2, qdis=2, time=2),
                                       record(3, 2, 1, qchg=1.5)], 1.0)
        self.assertEqual(rows[0]["discharge_capacity_mAh"], 2)

    def test_cumulative_reset_fails_explicitly(self):
        with self.assertRaises(ne.ExtractionError):
            ne.aggregate_records([record(1, 1, 2, qdis=2, time=1),
                                  record(2, 1, 2, qdis=1, time=2)], 1.0)

    def test_incomplete_direction_remains_visible(self):
        rows, _ = ne.aggregate_records([record(1, 1, 1, qchg=1)], 1.0)
        self.assertFalse(rows[0]["has_both_directions"])
        self.assertIsNone(rows[0]["efficiency_percent"])
        self.assertIsNone(rows[0]["capacity_retention_percent"])

    def test_name_uses_exact_metadata_suffix(self):
        metadata = {"test_info": {"DevID": "102", "UnitID": "6", "ChlID": "3",
                                  "StartTime": "2025-11-05 22:31:17", "Barcode": ""},
                    "head_info": {}}
        for sample in ("CS55-3.18-1C", "王同学_A_B-01_1C", "很多_下划线_102_6_3"):
            got = ne.resolve_name(Path(sample + "_102_6_3_20251105223117.ndax"), metadata)
            self.assertEqual(got["value"], sample)
            self.assertEqual(got["source"], "filename_with_metadata_verified_suffix")
        mismatched = "名字_999_6_3_20251105223117"
        self.assertEqual(ne.resolve_name(Path(mismatched + ".ndax"), metadata)["value"], mismatched)
        metadata["test_info"]["Barcode"] = "内部条码样品名"
        self.assertEqual(ne.resolve_name(Path("renamed.ndax"), metadata)["value"], "内部条码样品名")

    def test_mass_unknown_profile_needs_override(self):
        metadata = {"step_config": {}, "head_info": {}}
        with self.assertRaises(ne.ExtractionError):
            ne.mass_from_metadata(metadata, None)
        self.assertEqual(ne.mass_from_metadata(metadata, 0.896)[0], 0.896)
        with self.assertRaises(ne.ExtractionError):
            ne.mass_from_metadata(metadata, 0)


@unittest.skipUnless(os.environ.get("NEWARE_TEST_FILE") and os.environ.get("NEWARE_REFERENCE"),
                     "Set NEWARE_TEST_FILE and NEWARE_REFERENCE for the full regression")
class SampleRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = Path(os.environ["NEWARE_TEST_FILE"])
        cls.reference = Path(os.environ["NEWARE_REFERENCE"])
        cls.result = ne.extract(cls.path)

    def test_all_reference_values(self):
        self.assertEqual(self.result["audit"]["record_count"], 220101)
        self.assertEqual(self.result["audit"]["cycle_count"], 1505)
        check = ne.verify_reference(self.result["cycles"], self.reference)
        self.assertTrue(check["all_match_at_reference_precision"])
        self.assertEqual(check["matched_value_count"], 9030)

    def test_reference_detects_wrong_value(self):
        rows = copy.deepcopy(self.result["cycles"])
        rows[0]["charge_specific_capacity_mAh_g"] += 0.01
        check = ne.verify_reference(rows, self.reference)
        self.assertFalse(check["all_match_at_reference_precision"])
        self.assertEqual(len(check["differences"]), 1)

    def test_name_is_honestly_identified_as_filename_source(self):
        self.assertEqual(self.result["sample_name"]["value"], "CS55-3.18-1C")
        self.assertEqual(self.result["sample_name"]["source"], "filename_with_metadata_verified_suffix")
        for encodings in self.result["sample_name_plaintext_search_offsets"].values():
            self.assertTrue(all(offset == -1 for offset in encodings.values()))

    def test_missing_record_and_unknown_range_are_rejected(self):
        with zipfile.ZipFile(self.path) as archive:
            blob = bytearray(archive.read("data.ndc"))
        # Corrupt first record index (byte offset 517 + 8).
        blob[525] = 2
        with self.assertRaises(ne.ExtractionError):
            next(ne.read_records(bytes(blob), self.result["metadata"]))
        blob[525] = 1
        blob[599:603] = (1234567).to_bytes(4, "little", signed=True)
        with self.assertRaises(ne.ExtractionError):
            next(ne.read_records(bytes(blob), self.result["metadata"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
