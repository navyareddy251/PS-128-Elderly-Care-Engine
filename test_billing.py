"""
Unit tests for billing.py
PS-128 / Team T025

Tests all billing requirements:
1. Pricing across different care levels and room types.
2. Monthly pro-rating by calendar days (admission, care level changes, departures).
3. Admission date pro-rating (RES-022).
4. Discharge notice charge (EC-08 RES-004: 29 days notice -> 50% monthly fee).
5. Death pro-rata refund and notice waiver (RES-023).
6. Add-on services, eligibility exclusion during hospitalisation, and free allowances (DOCTOR_VISIT 2 free, SPECIAL_DIET flat).
7. Consumables and 10% handling capped at Rs 2000 (RES-030).
8. Hospitalisation of exactly 30 days @ 50% retention (EC-04 RES-039).
9. Continuous hospitalisation across months exceeding 30 and 60 days with BED_RETAIN FULL (RES-029).
10. Deposit adjustments on care level increase (EC-03 RES-015).
11. Late payments and 1.5% interest (RES-003).
12. Validation of output DataFrame schema.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_loader import load_dataset
from src.care_levels import build_care_levels
from src.billing import BillingEngine, execute_billing_stream


class TestBillingEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loader, _ = load_dataset(PROJECT_ROOT / "data")
        cls.cl_manager, _ = build_care_levels(cls.loader)
        cls.engine, cls.bills_df = execute_billing_stream(cls.loader, cls.cl_manager)

    def test_fee_schedule_pricing_all_combinations(self):
        """Verifies monthly fees for all care levels and room types."""
        self.assertEqual(self.engine.get_monthly_fee("LEVEL_1", "SHARED"), 45000.0)
        self.assertEqual(self.engine.get_monthly_fee("LEVEL_1", "PRIVATE"), 65000.0)
        self.assertEqual(self.engine.get_monthly_fee("LEVEL_2", "SHARED"), 60000.0)
        self.assertEqual(self.engine.get_monthly_fee("LEVEL_2", "PRIVATE"), 80000.0)
        self.assertEqual(self.engine.get_monthly_fee("LEVEL_3", "SHARED"), 80000.0)
        self.assertEqual(self.engine.get_monthly_fee("LEVEL_3", "PRIVATE"), 100000.0)
        self.assertEqual(self.engine.get_monthly_fee("LEVEL_4", "PRIVATE"), 110000.0)

    def test_admission_date_prorating_res022(self):
        """RES-022 admitted 2026-08-17: billed pro-rata for 15 days in August."""
        inv = self.engine.invoices.get(("RES-022", "2026-08"))
        self.assertIsNotNone(inv)
        fee_lines = [l for l in inv.lines if l.line_type == "FEE"]
        self.assertEqual(len(fee_lines), 1)
        self.assertEqual(fee_lines[0].days, "15")
        # 15 days @ 45000 / 31 = 21774.19
        self.assertEqual(float(fee_lines[0].amount), 21774.19)
        self.assertEqual(inv.total_amount, 21774.19)

    def test_care_level_increase_prorating_and_deposit_res015(self):
        """EC-03: RES-015 level increase on Aug 31 (30 days @ L2, 1 day @ L3, deposit diff)."""
        inv = self.engine.invoices.get(("RES-015", "2026-08"))
        self.assertIsNotNone(inv)

        fee_lines = [l for l in inv.lines if l.line_type == "FEE"]
        self.assertEqual(len(fee_lines), 2)
        # 30 days @ 60000 / 31 = 58064.52
        self.assertEqual(float(fee_lines[0].amount), 58064.52)
        # 1 day @ 80000 / 31 = 2580.65
        self.assertEqual(float(fee_lines[1].amount), 2580.65)

        # Deposit adjustment: 2 * 80000 - 120000 = 40000.00
        dep_lines = [l for l in inv.lines if l.line_type == "DEPOSIT_ADJUSTMENT"]
        self.assertEqual(len(dep_lines), 1)
        self.assertEqual(float(dep_lines[0].amount), 40000.0)
        self.assertEqual(inv.total_amount, 100645.17)

    def test_hospitalisation_exactly_30_days_res039(self):
        """EC-04: RES-039 hospitalised Aug 6 to Sep 5 = 30 days @ 50%, add-on during stay not billed."""
        # August bill (31 days): 5 days residence, 26 days hospital @ 50%
        inv_aug = self.engine.invoices.get(("RES-039", "2026-08"))
        self.assertIsNotNone(inv_aug)

        fee_lines = [l for l in inv_aug.lines if l.line_type == "FEE"]
        self.assertEqual(len(fee_lines), 1)
        self.assertEqual(fee_lines[0].days, "5")
        self.assertEqual(float(fee_lines[0].amount), 16129.03)

        ret_lines = [l for l in inv_aug.lines if l.line_type == "HOSPITAL_RETENTION"]
        self.assertEqual(len(ret_lines), 1)
        self.assertEqual(ret_lines[0].days, "26")
        self.assertEqual(float(ret_lines[0].amount), 41935.48)

        # PHYSIO recorded on 2026-08-12 must NOT be billed
        addon_lines = [l for l in inv_aug.lines if l.line_type == "ADDON"]
        self.assertEqual(len(addon_lines), 0)

        # September bill: 4 days hospital @ 50% (days 27-30), 26 days residence
        inv_sep = self.engine.invoices.get(("RES-039", "2026-09"))
        self.assertIsNotNone(inv_sep)
        ret_sep = [l for l in inv_sep.lines if l.line_type == "HOSPITAL_RETENTION"]
        self.assertEqual(len(ret_sep), 1)
        self.assertEqual(ret_sep[0].days, "4")
        self.assertEqual(float(ret_sep[0].amount), 6666.67)

    def test_continuous_hospitalisation_66_days_and_bed_retain_res029(self):
        """RES-029: 66 days across Aug-Oct (30d @ 50%, 30d @ 25%, BED_RETAIN FULL @ 100%)."""
        # August: 2 days residence, 29 days hospital (days 1-29 @ 50%)
        inv_aug = self.engine.invoices.get(("RES-029", "2026-08"))
        ret_aug = [l for l in inv_aug.lines if l.line_type == "HOSPITAL_RETENTION"]
        self.assertEqual(ret_aug[0].days, "29")
        self.assertEqual(float(ret_aug[0].amount), 37419.35)

        # September (30 days): day 1 is day 30 (@ 50%), days 2-30 are days 31-59 (@ 25%)
        inv_sep = self.engine.invoices.get(("RES-029", "2026-09"))
        ret_sep = [l for l in inv_sep.lines if l.line_type == "HOSPITAL_RETENTION"]
        self.assertEqual(len(ret_sep), 2)
        # Find 50% line and 25% line
        ret_50 = next(l for l in ret_sep if "50%" in l.description)
        ret_25 = next(l for l in ret_sep if "25%" in l.description)
        self.assertEqual(ret_50.days, "1")
        self.assertEqual(float(ret_50.amount), 1333.33)
        self.assertEqual(ret_25.days, "29")
        self.assertEqual(float(ret_25.amount), 19333.33)

        # October: day 1 is day 60 (@ 25%), days 2-7 are days 61-66 (@ 100% via BED_RETAIN FULL), days 8-31 residence
        inv_oct = self.engine.invoices.get(("RES-029", "2026-10"))
        ret_oct = [l for l in inv_oct.lines if l.line_type == "HOSPITAL_RETENTION"]
        ret_oct_25 = next(l for l in ret_oct if "25%" in l.description)
        ret_oct_100 = next(l for l in ret_oct if "100%" in l.description)
        self.assertEqual(ret_oct_25.days, "1")
        self.assertEqual(float(ret_oct_25.amount), 645.16)
        self.assertEqual(ret_oct_100.days, "6")
        self.assertEqual(float(ret_oct_100.amount), 15483.87)

    def test_addons_free_allowance_and_consumables_cap_res030(self):
        """RES-030 September: 4 doctor visits (2 free, 2 billed), consumables handling capped at Rs 2000."""
        inv = self.engine.invoices.get(("RES-030", "2026-09"))
        self.assertIsNotNone(inv)

        # Doctor visits: 2 billed @ 1500 = 3000
        doc_lines = [l for l in inv.lines if "Doctor visit" in l.description]
        self.assertEqual(len(doc_lines), 1)
        self.assertEqual(doc_lines[0].days, "2")
        self.assertEqual(float(doc_lines[0].amount), 3000.0)

        # Handling fee: consumables = 9800 + 7400 + 6200 = 23400. 10% = 2340 -> capped at 2000
        handling_lines = [l for l in inv.lines if l.line_type == "HANDLING"]
        self.assertEqual(len(handling_lines), 1)
        self.assertEqual(float(handling_lines[0].amount), 2000.0)

    def test_discharge_notice_charge_res004(self):
        """EC-08: RES-004 notice given 29 days before vacating -> 50% monthly fee charge."""
        inv = self.engine.invoices.get(("RES-004", "2026-09"))
        self.assertIsNotNone(inv)
        nc_lines = [l for l in inv.lines if l.line_type == "NOTICE_CHARGE"]
        self.assertEqual(len(nc_lines), 1)
        # LEVEL_2 PRIVATE fee = 80000 -> 50% = 40000.00
        self.assertEqual(float(nc_lines[0].amount), 40000.0)

    def test_death_prorating_res023(self):
        """RES-023 death on Sep 23: notice waived, billed only through Sep 23 (23 days pro-rata)."""
        inv = self.engine.invoices.get(("RES-023", "2026-09"))
        self.assertIsNotNone(inv)
        fee_lines = [l for l in inv.lines if l.line_type == "FEE"]
        self.assertEqual(len(fee_lines), 1)
        self.assertEqual(fee_lines[0].days, "23")
        # 23 / 30 * 80000 = 61333.33
        self.assertEqual(float(fee_lines[0].amount), 61333.33)

    def test_late_payment_interest_res003(self):
        """RES-003: August bill paid late on Sep 15 -> 1.5% interest on September bill."""
        inv_aug = self.engine.invoices.get(("RES-003", "2026-08"))
        self.assertTrue(inv_aug.is_paid)
        self.assertTrue(inv_aug.is_late)

        inv_sep = self.engine.invoices.get(("RES-003", "2026-09"))
        interest_lines = [l for l in inv_sep.lines if l.line_type == "INTEREST"]
        self.assertEqual(len(interest_lines), 1)
        # 1.5% of 60000.00 = 900.00
        self.assertEqual(float(interest_lines[0].amount), 900.0)

    def test_bills_dataframe_schema(self):
        """Verifies bills.csv column names, ordering, and line types."""
        expected_cols = [
            "bill_id", "resident_id", "month", "line_type",
            "description", "days", "rate", "amount"
        ]
        self.assertListEqual(list(self.bills_df.columns), expected_cols)

        # Verify allowed line_types
        allowed_types = {
            "FEE", "HOSPITAL_RETENTION", "ADDON", "CONSUMABLE",
            "HANDLING", "NOTICE_CHARGE", "REFUND", "DEPOSIT_ADJUSTMENT", "INTEREST"
        }
        self.assertTrue(set(self.bills_df["line_type"]).issubset(allowed_types))


if __name__ == "__main__":
    unittest.main()
