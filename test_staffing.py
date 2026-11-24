"""
Unit tests for staffing.py
PS-128 / Team T025

Tests all staffing requirements:
1. Staff availability and leave management (staff on leave are excluded).
2. Staffing ratio calculations for Day and Night shifts across all care levels.
3. Night-shift ratio halving for LEVEL_1 and LEVEL_2.
4. Memory wing (WING-M) caregiver constraint (all assigned caregivers must be dementia_trained).
5. Nurse minimum requirements (min 1 per wing per shift).
6. Medication error tightening for 14 days (EC-05: 1:15 ratio).
7. Weekly contract hours constraint: maximum 48 hours per week (Monday to Sunday).
8. Shift limit: maximum 1 shift (12 hours) per staff member per calendar day.
9. Shortfall detection and agency cost calculation (shortfall * Rs 2500, EC-06).
10. Full dataset 15-day roster validation (staffing_requirements.csv and rosters.csv schemas).
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_loader import load_dataset
from src.care_levels import build_care_levels
from src.staffing import StaffingEngine, execute_staffing_engine


class TestStaffingEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loader, _ = load_dataset(PROJECT_ROOT / "data")
        cls.cl_manager, _ = build_care_levels(cls.loader)
        cls.engine, cls.req_df, cls.rost_df = execute_staffing_engine(cls.loader, cls.cl_manager)

    def test_staff_leave_periods(self):
        """Verifies staff availability excludes leave periods."""
        # STF-02 on CASUAL leave 2026-10-05 to 2026-10-06
        self.assertTrue(self.engine.is_on_leave("STF-02", "2026-10-05"))
        self.assertTrue(self.engine.is_on_leave("STF-02", "2026-10-06"))
        self.assertFalse(self.engine.is_on_leave("STF-02", "2026-10-07"))

        # STF-08 on EARNED leave 2026-10-06 to 2026-10-09
        self.assertTrue(self.engine.is_on_leave("STF-08", "2026-10-06"))
        self.assertTrue(self.engine.is_on_leave("STF-08", "2026-10-09"))
        self.assertFalse(self.engine.is_on_leave("STF-08", "2026-10-10"))

    def test_staff_not_assigned_during_leave(self):
        """Verifies that no staff member is assigned on a date they are on leave."""
        for _, row in self.rost_df.iterrows():
            sid = row["staff_id"]
            d_str = row["date"]
            self.assertFalse(
                self.engine.is_on_leave(sid, d_str),
                f"Staff {sid} was assigned on {d_str} while on leave!"
            )

    def test_day_vs_night_ratios(self):
        """Verifies that night shift ratios reflect halved demand for LEVEL_1 and LEVEL_2."""
        # WING-A has 12 L1, 8 L2, 2 L3
        cg_day, n_day = self.engine.calculate_shift_requirements("WING-A", "2026-10-05", "DAY")
        cg_night, n_night = self.engine.calculate_shift_requirements("WING-A", "2026-10-05", "NIGHT")

        # Day: ceil(12/8) + ceil(8/5) + ceil(2/3) = 2 + 2 + 1 = 5
        self.assertEqual(cg_day, 5)
        # Night: ceil(12/16) + ceil(8/10) + ceil(2/3) = 1 + 1 + 1 = 3
        self.assertEqual(cg_night, 3)

        # Nurses: day ceil(22/20) = 2, night ceil(22/40) = 1
        self.assertEqual(n_day, 2)
        self.assertEqual(n_night, 1)

    def test_memory_wing_caregiver_dementia_training_constraint(self):
        """Rule BR-ST-05: All caregivers assigned to WING-M must be dementia trained."""
        wing_m_roster = self.rost_df[(self.rost_df["wing_id"] == "WING-M") & (self.rost_df["role"] == "CAREGIVER")]
        for _, row in wing_m_roster.iterrows():
            sid = row["staff_id"]
            staff_member = self.engine.staff[sid]
            self.assertTrue(
                staff_member.dementia_trained,
                f"Caregiver {sid} assigned to WING-M is not dementia trained!"
            )

    def test_medication_error_nurse_tightening_ec05(self):
        """EC-05: 1:15 nurse ratio for 14 days after MED_ERROR on 2026-10-12 in WING-M."""
        # Before med error: 2026-10-05 -> 20 / 20 = 1 nurse
        _, n_norm = self.engine.calculate_shift_requirements("WING-M", "2026-10-05", "DAY")
        self.assertEqual(n_norm, 1)

        # On and after med error: 2026-10-12 to 2026-10-25 -> ceil(20 / 15) = 2 nurses
        _, n_tight = self.engine.calculate_shift_requirements("WING-M", "2026-10-12", "DAY")
        self.assertEqual(n_tight, 2)

        # Still tightened on 2026-10-19 (within 14 days)
        _, n_tight_19 = self.engine.calculate_shift_requirements("WING-M", "2026-10-19", "DAY")
        self.assertEqual(n_tight_19, 2)

    def test_max_weekly_hours_48_limit_ec06(self):
        """EC-06: No staff member works more than 48 hours in any Monday-to-Sunday week."""
        # Check that week_hours_after in rosters.csv never exceeds 48
        max_hours = self.rost_df["week_hours_after"].max()
        self.assertLessEqual(max_hours, 48)

    def test_max_one_shift_per_day(self):
        """Verifies no staff member is scheduled for more than one 12h shift on the same calendar day."""
        day_staff_counts = self.rost_df.groupby(["date", "staff_id"]).size()
        max_shifts_per_day = day_staff_counts.max()
        self.assertEqual(max_shifts_per_day, 1)

    def test_shortfall_and_agency_cost_calculation(self):
        """Verifies that shortfall = required - assigned and agency_cost = shortfall * Rs 2500."""
        for _, row in self.req_df.iterrows():
            cg_shortfall = max(0, row["caregivers_required"] - row["caregivers_assigned"])
            n_shortfall = max(0, row["nurses_required"] - row["nurses_assigned"])
            expected_shortfall = cg_shortfall + n_shortfall
            self.assertEqual(row["shortfall"], expected_shortfall)
            expected_cost = expected_shortfall * 2500.0
            self.assertEqual(float(row["agency_cost"]), expected_cost)

    def test_end_of_week_shortfall_occurs_ec06(self):
        """EC-06: On Sunday 2026-10-11, staffing shortfalls occur due to 48h exhausted hours."""
        sunday_reqs = self.req_df[self.req_df["date"] == "2026-10-11"]
        total_sunday_shortfall = sunday_reqs["shortfall"].sum()
        self.assertGreater(total_sunday_shortfall, 0)
        self.assertGreater(sunday_reqs["agency_cost"].astype(float).sum(), 0.0)

    def test_staffing_requirements_schema(self):
        """Verifies staffing_requirements.csv columns and order."""
        expected_cols = [
            "date", "shift", "wing_id", "caregivers_required", "nurses_required",
            "caregivers_assigned", "nurses_assigned", "shortfall", "agency_cost"
        ]
        self.assertListEqual(list(self.req_df.columns), expected_cols)
        # 15 days * 2 shifts * 3 wings = 90 rows
        self.assertEqual(len(self.req_df), 90)

    def test_rosters_schema(self):
        """Verifies rosters.csv columns and order."""
        expected_cols = [
            "date", "shift", "wing_id", "staff_id", "role", "hours", "week_hours_after"
        ]
        self.assertListEqual(list(self.rost_df.columns), expected_cols)
        self.assertTrue((self.rost_df["hours"] == 12).all())


if __name__ == "__main__":
    unittest.main()
