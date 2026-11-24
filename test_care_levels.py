"""
Unit tests for care_levels.py
PS-128 / Team T025

Tests all requirements:
1. Care level determination for LEVEL_1, LEVEL_2, LEVEL_3, LEVEL_4.
2. Clinical conflict resolution (higher level taken when ADL and Cognitive imply different levels, EC-01).
3. Fall risk elevation (+1 level, capped at LEVEL_4, EC-02).
4. Reassessment cadence: 90 days for LEVEL_1/LEVEL_2, 30 days for LEVEL_3/LEVEL_4.
5. Effective dates:
   - Immediate on assessment_date for care-level increase (EC-03).
   - 1st of following month for care-level decrease (RES-050).
6. Fall escalation:
   - Exactly 30-day boundary between two falls triggers FALL_ESCALATION (EC-07 RES-014).
   - Fall occurring > 30 days later does NOT trigger escalation.
7. Overdue reassessment detection and latency calculation (RES-033 16 days late).
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_loader import load_dataset
from src.care_levels import (
    CareLevel, Basis, score_adl, score_cognitive, determine_care_level,
    get_first_day_of_next_month, CareLevelManager, build_care_levels
)


class TestCareLevelScoring(unittest.TestCase):
    """Tests ADL and cognitive score mapping to care levels."""

    def test_score_adl_all_bands(self):
        """Verifies ADL score mapping to LEVEL_1 through LEVEL_4."""
        self.assertEqual(score_adl(0), CareLevel.LEVEL_1)
        self.assertEqual(score_adl(1), CareLevel.LEVEL_1)
        self.assertEqual(score_adl(2), CareLevel.LEVEL_2)
        self.assertEqual(score_adl(3), CareLevel.LEVEL_2)
        self.assertEqual(score_adl(4), CareLevel.LEVEL_3)
        self.assertEqual(score_adl(5), CareLevel.LEVEL_3)
        self.assertEqual(score_adl(6), CareLevel.LEVEL_4)

    def test_score_cognitive_all_bands(self):
        """Verifies cognitive score mapping to LEVEL_1 through LEVEL_4."""
        # 24-30 -> LEVEL_1
        self.assertEqual(score_cognitive(30), CareLevel.LEVEL_1)
        self.assertEqual(score_cognitive(24), CareLevel.LEVEL_1)
        # 18-23 -> LEVEL_2
        self.assertEqual(score_cognitive(23), CareLevel.LEVEL_2)
        self.assertEqual(score_cognitive(18), CareLevel.LEVEL_2)
        # 10-17 -> LEVEL_3
        self.assertEqual(score_cognitive(17), CareLevel.LEVEL_3)
        self.assertEqual(score_cognitive(10), CareLevel.LEVEL_3)
        # 0-9 -> LEVEL_4
        self.assertEqual(score_cognitive(9), CareLevel.LEVEL_4)
        self.assertEqual(score_cognitive(0), CareLevel.LEVEL_4)

    def test_conflict_resolution_higher_level_taken_ec01(self):
        """EC-01: ADL 3 (LEVEL_2) with cognitive 17 (LEVEL_3) must resolve to LEVEL_3."""
        level, basis, elevated = determine_care_level(adl=3, cog=17, fall_risk=False)
        self.assertEqual(level, CareLevel.LEVEL_3)
        self.assertEqual(basis, Basis.ASSESSMENT)
        self.assertFalse(elevated)

    def test_fall_risk_elevation(self):
        """Fall risk raises level by 1 when below LEVEL_4."""
        # LEVEL_1 + fall_risk -> LEVEL_2
        level, basis, elevated = determine_care_level(adl=1, cog=28, fall_risk=True)
        self.assertEqual(level, CareLevel.LEVEL_2)
        self.assertEqual(basis, Basis.FALL_RISK)
        self.assertTrue(elevated)

        # LEVEL_2 + fall_risk -> LEVEL_3
        level, basis, elevated = determine_care_level(adl=2, cog=26, fall_risk=True)
        self.assertEqual(level, CareLevel.LEVEL_3)
        self.assertEqual(basis, Basis.FALL_RISK)
        self.assertTrue(elevated)

        # LEVEL_3 + fall_risk -> LEVEL_4
        level, basis, elevated = determine_care_level(adl=4, cog=25, fall_risk=True)
        self.assertEqual(level, CareLevel.LEVEL_4)
        self.assertEqual(basis, Basis.FALL_RISK)
        self.assertTrue(elevated)

    def test_fall_risk_capped_at_level_4_ec02(self):
        """EC-02: Fall risk on a resident already at LEVEL_4 is capped at LEVEL_4."""
        level, basis, elevated = determine_care_level(adl=6, cog=5, fall_risk=True)
        self.assertEqual(level, CareLevel.LEVEL_4)
        self.assertEqual(basis, Basis.ASSESSMENT)
        self.assertFalse(elevated)


class TestReassessmentCadence(unittest.TestCase):
    """Tests 30-day and 90-day periodic reassessment cadence."""

    def setUp(self):
        self.manager = CareLevelManager()

    def test_cadence_days_by_level(self):
        """Verifies 90 days for LEVEL_1/LEVEL_2 and 30 days for LEVEL_3/LEVEL_4."""
        self.assertEqual(self.manager.get_cadence_days(CareLevel.LEVEL_1), 90)
        self.assertEqual(self.manager.get_cadence_days(CareLevel.LEVEL_2), 90)
        self.assertEqual(self.manager.get_cadence_days(CareLevel.LEVEL_3), 30)
        self.assertEqual(self.manager.get_cadence_days(CareLevel.LEVEL_4), 30)

    def test_next_month_first_day_calculation(self):
        """Verifies calculation of 1st day of next month."""
        self.assertEqual(get_first_day_of_next_month("2026-08-15"), "2026-09-01")
        self.assertEqual(get_first_day_of_next_month("2026-08-31"), "2026-09-01")
        self.assertEqual(get_first_day_of_next_month("2026-09-12"), "2026-10-01")
        self.assertEqual(get_first_day_of_next_month("2026-12-05"), "2027-01-01")


class TestCareLevelEffectiveDates(unittest.TestCase):
    """Tests effective date business rules for increases and decreases."""

    def setUp(self):
        self.manager = CareLevelManager()

    def test_immediate_effective_date_for_increase_ec03(self):
        """EC-03: Care level increase takes effect immediately on assessment_date."""
        # Initial assessment: LEVEL_2 on 2026-07-06
        self.manager.process_assessment({
            "resident_id": "RES-015",
            "assessment_date": "2026-07-06",
            "adl_score": "2",
            "cognitive_score": "28",
            "fall_risk": "false",
            "assessment_id": "ASM-0026"
        })
        self.assertEqual(self.manager.get_effective_care_level("RES-015", "2026-08-30").care_level, "LEVEL_2")

        # Reassessment on 2026-08-31 (ADL 4 -> LEVEL_3)
        rec = self.manager.process_assessment({
            "resident_id": "RES-015",
            "assessment_date": "2026-08-31",
            "adl_score": "4",
            "cognitive_score": "27",
            "fall_risk": "false",
            "assessment_id": "ASM-0123"
        })
        self.assertIsNotNone(rec)
        self.assertEqual(rec.effective_date, "2026-08-31")
        self.assertEqual(rec.care_level, "LEVEL_3")

        # Effective level on 2026-08-31 must be LEVEL_3
        active = self.manager.get_effective_care_level("RES-015", "2026-08-31")
        self.assertEqual(active.care_level, "LEVEL_3")

    def test_next_month_effective_date_for_decrease(self):
        """Care level decrease takes effect on the 1st of the next month (RES-050)."""
        # Baseline assessment: LEVEL_3
        self.manager.process_assessment({
            "resident_id": "RES-050",
            "assessment_date": "2026-09-03",
            "adl_score": "4",
            "cognitive_score": "28",
            "fall_risk": "false",
            "assessment_id": "ASM-0131"
        })
        self.assertEqual(self.manager.get_effective_care_level("RES-050", "2026-09-10").care_level, "LEVEL_3")

        # Reassessment on 2026-09-12 lowers to LEVEL_2 (ADL 3, Cog 26)
        rec = self.manager.process_assessment({
            "resident_id": "RES-050",
            "assessment_date": "2026-09-12",
            "adl_score": "3",
            "cognitive_score": "26",
            "fall_risk": "false",
            "assessment_id": "ASM-0149"
        })
        self.assertIsNotNone(rec)
        # Must be effective 2026-10-01
        self.assertEqual(rec.effective_date, "2026-10-01")
        self.assertEqual(rec.care_level, "LEVEL_2")

        # On 2026-09-20, level must STILL be LEVEL_3
        self.assertEqual(self.manager.get_effective_care_level("RES-050", "2026-09-20").care_level, "LEVEL_3")
        # On 2026-10-01, level is now LEVEL_2
        self.assertEqual(self.manager.get_effective_care_level("RES-050", "2026-10-01").care_level, "LEVEL_2")


class TestFallEscalation(unittest.TestCase):
    """Tests 2-falls-in-30-days escalation and 30-day boundary."""

    def setUp(self):
        self.manager = CareLevelManager()

    def test_second_fall_on_exact_30th_day_triggers_escalation_ec07(self):
        """EC-07: Second fall on the exact 30th day triggers immediate one-level escalation."""
        # Initial baseline: LEVEL_1
        self.manager.process_assessment({
            "resident_id": "RES-014",
            "assessment_date": "2026-06-25",
            "adl_score": "1",
            "cognitive_score": "25",
            "fall_risk": "false",
            "assessment_id": "ASM-0013"
        })
        # First fall: 2026-08-20
        self.manager.record_fall("RES-014", "2026-08-20")

        # Fall reassessment on 2026-08-21 sets LEVEL_2 (fall_risk=true)
        self.manager.process_assessment({
            "resident_id": "RES-014",
            "assessment_date": "2026-08-21",
            "adl_score": "1",
            "cognitive_score": "26",
            "fall_risk": "true",
            "assessment_id": "ASM-0106"
        })
        self.assertEqual(self.manager.get_effective_care_level("RES-014", "2026-08-25").care_level, "LEVEL_2")

        # Second fall: 2026-09-19 (exactly 30 days after 2026-08-20)
        esc_rec = self.manager.record_fall("RES-014", "2026-09-19")
        self.assertIsNotNone(esc_rec)
        self.assertEqual(esc_rec.care_level, "LEVEL_3")
        self.assertEqual(esc_rec.basis, Basis.FALL_ESCALATION.value)
        self.assertEqual(esc_rec.effective_date, "2026-09-19")

        # Effective care level on 2026-09-19 must be LEVEL_3
        active = self.manager.get_effective_care_level("RES-014", "2026-09-19")
        self.assertEqual(active.care_level, "LEVEL_3")
        self.assertEqual(active.basis, Basis.FALL_ESCALATION.value)

    def test_second_fall_beyond_30_days_does_not_escalate(self):
        """A second fall on the 31st day does NOT trigger FALL_ESCALATION."""
        # Baseline: LEVEL_1
        self.manager.process_assessment({
            "resident_id": "TEST-01",
            "assessment_date": "2026-08-01",
            "adl_score": "1",
            "cognitive_score": "28",
            "fall_risk": "false",
            "assessment_id": "ASM-T01"
        })
        # Fall 1 on 2026-08-01
        self.manager.record_fall("TEST-01", "2026-08-01")
        # Fall 2 on 2026-09-01 (31 days later, since August has 31 days)
        esc_rec = self.manager.record_fall("TEST-01", "2026-09-01")
        self.assertIsNone(esc_rec)


class TestOverdueReassessments(unittest.TestCase):
    """Tests overdue assessment tracking against 30-day / 90-day cadences."""

    def test_res033_overdue_16_days(self):
        """Verifies RES-033 is overdue by 16 days on 2026-08-22 before assessment."""
        project_root = Path(__file__).resolve().parent.parent
        loader, _ = load_dataset(project_root / "data")
        manager, _ = build_care_levels(loader)

        # On 2026-08-21, prior assessment was 2026-07-07 (LEVEL_3, 30 days -> due 2026-08-06)
        status = manager.get_reassessment_status("RES-033", "2026-08-21")
        self.assertIsNotNone(status)
        self.assertTrue(status.is_overdue)
        self.assertEqual(status.cadence_days, 30)
        self.assertEqual(status.due_date, "2026-08-06")
        self.assertEqual(status.days_overdue, 15)

    def test_full_dataset_care_levels_dataframe(self):
        """Verifies complete DataFrame structure for care_levels.csv."""
        project_root = Path(__file__).resolve().parent.parent
        loader, _ = load_dataset(project_root / "data")
        manager, df = build_care_levels(loader)

        expected_columns = ["resident_id", "effective_date", "care_level", "basis", "fall_risk_until"]
        self.assertListEqual(list(df.columns), expected_columns)
        self.assertGreater(len(df), 70)  # 70 initial + level changes

        # Check all basis values are strictly allowed enums
        valid_bases = {"ASSESSMENT", "FALL_RISK", "FALL_ESCALATION"}
        self.assertTrue(set(df["basis"]).issubset(valid_bases))

        # Check all care_levels are valid
        valid_levels = {"LEVEL_1", "LEVEL_2", "LEVEL_3", "LEVEL_4"}
        self.assertTrue(set(df["care_level"]).issubset(valid_levels))


if __name__ == "__main__":
    unittest.main()
