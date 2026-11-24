"""
Unit tests for data_loader.py
PS-128 / Team T025
"""

import sys
import unittest
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
from src.data_loader import DataLoader, load_dataset


class TestDataLoader(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project_root = Path(__file__).resolve().parent.parent
        cls.data_dir = cls.project_root / "data"
        cls.loader, cls.report = load_dataset(cls.data_dir)

    def test_all_files_loaded_successfully(self):
        """Verifies that all 9 files are loaded without fatal errors."""
        self.assertTrue(self.report.is_valid, f"Validation errors occurred: {self.report.errors}")
        self.assertEqual(len(self.report.errors), 0)

    def test_record_counts_match_specification(self):
        """Verifies record counts match README.md table specification."""
        self.assertEqual(len(self.loader.wings), 3)
        self.assertEqual(len(self.loader.fee_schedule), 7)
        self.assertEqual(len(self.loader.addon_rates), 5)
        self.assertEqual(len(self.loader.staffing_ratios), 5)
        self.assertEqual(len(self.loader.residents), 70)
        self.assertEqual(len(self.loader.assessments), 242)
        self.assertEqual(len(self.loader.staff), 40)
        self.assertEqual(len(self.loader.staff_leave), 8)
        self.assertEqual(len(self.loader.commands), 527)

    def test_wings_schema_and_values(self):
        """Verifies wings structure and memory wing flag."""
        wings_df = self.loader.wings
        self.assertListEqual(list(wings_df.columns), ["wing_id", "wing_name", "memory_wing"])
        wing_ids = set(wings_df["wing_id"])
        self.assertSetEqual(wing_ids, {"WING-A", "WING-B", "WING-M"})

        memory_wings = wings_df[wings_df["memory_wing"].str.lower() == "true"]
        self.assertEqual(len(memory_wings), 1)
        self.assertEqual(memory_wings.iloc[0]["wing_id"], "WING-M")

    def test_fee_schedule_pricing(self):
        """Verifies fee schedule amounts and room type rules."""
        fees = self.loader.fee_schedule
        self.assertIn("monthly_fee", fees.columns)

        # LEVEL_4 must only be PRIVATE
        l4_fees = fees[fees["care_level"] == "LEVEL_4"]
        self.assertEqual(len(l4_fees), 1)
        self.assertEqual(l4_fees.iloc[0]["room_type"], "PRIVATE")
        self.assertEqual(float(l4_fees.iloc[0]["monthly_fee"]), 110000.0)

    def test_resident_foreign_keys_and_uniqueness(self):
        """Verifies resident uniqueness and wing referential integrity."""
        res_df = self.loader.residents
        self.assertEqual(res_df["resident_id"].nunique(), 70)

        # All wing_ids in residents must exist in wings.csv
        valid_wings = set(self.loader.wings["wing_id"])
        res_wings = set(res_df["wing_id"])
        self.assertTrue(res_wings.issubset(valid_wings))

        # Memory wing residents check: all 20 WING-M residents must be PRIVATE room_type
        m_residents = res_df[res_df["wing_id"] == "WING-M"]
        self.assertEqual(len(m_residents), 20)
        self.assertTrue((m_residents["room_type"] == "PRIVATE").all())

    def test_assessment_foreign_keys_and_score_bounds(self):
        """Verifies assessment constraints (ADL 0-6, Cognitive 0-30)."""
        asm_df = self.loader.assessments
        self.assertEqual(asm_df["assessment_id"].nunique(), 242)

        # All resident_ids must exist
        valid_res_ids = set(self.loader.residents["resident_id"])
        asm_res_ids = set(asm_df["resident_id"])
        self.assertTrue(asm_res_ids.issubset(valid_res_ids))

        # Score ranges
        adl_scores = asm_df["adl_score"].astype(int)
        self.assertTrue((adl_scores >= 0).all() and (adl_scores <= 6).all())

        cog_scores = asm_df["cognitive_score"].astype(int)
        self.assertTrue((cog_scores >= 0).all() and (cog_scores <= 30).all())

    def test_staff_roles_and_hours(self):
        """Verifies staff roles (30 caregivers, 10 nurses) and contract hours."""
        staff_df = self.loader.staff
        self.assertEqual(len(staff_df[staff_df["role"] == "CAREGIVER"]), 30)
        self.assertEqual(len(staff_df[staff_df["role"] == "NURSE"]), 10)
        self.assertTrue((staff_df["contract_hours_week"].astype(int) == 48).all())

    def test_staff_leave_validity(self):
        """Verifies staff leave dates are valid ranges and staff exists."""
        leave_df = self.loader.staff_leave
        valid_staff = set(self.loader.staff["staff_id"])
        self.assertTrue(set(leave_df["staff_id"]).issubset(valid_staff))

        for _, row in leave_df.iterrows():
            self.assertLessEqual(row["leave_from"], row["leave_to"])

    def test_commands_parsing(self):
        """Verifies commands list contains valid verbs and preservation of order."""
        commands = self.loader.commands
        self.assertEqual(len(commands), 527)
        self.assertEqual(commands[0][0], "ADDON")
        self.assertEqual(commands[-1][0], "PRINT_CARE_PLAN")

    def test_future_admission_warnings_recorded(self):
        """Verifies that RES-050 and RES-070 future admission dates are recorded as warnings."""
        warn_messages = [w.message for w in self.report.warnings if w.file_name == "residents.csv"]
        self.assertTrue(any("RES-050" in msg for msg in warn_messages))
        self.assertTrue(any("RES-070" in msg for msg in warn_messages))


if __name__ == "__main__":
    unittest.main()
