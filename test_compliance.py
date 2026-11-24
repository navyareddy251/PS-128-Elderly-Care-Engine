"""
Unit tests for compliance.py
PS-128 / Team T025: Elderly Care Home Resident Care-level Billing and Staffing Ratio Engine

Tests all compliance monitoring features:
1. Detection of overdue periodic reassessments (30-day and 90-day cadences, RES-033 16 days late).
2. Detection of ratio breaches (staffing shortfalls during shift schedules).
3. Detection of late payments (payments received after 10th of issue month, RES-003).
4. Compliance CSV schema verification (month, finding_type, ref_id, detail).
5. Human-readable PRINT_COMPLIANCE statement formatting.
6. Deterministic sorting of findings.
"""

import sys
import unittest
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_loader import load_dataset
from src.care_levels import build_care_levels
from src.billing import BillingEngine
from src.staffing import execute_staffing_engine
from src.compliance import ComplianceEngine, execute_compliance_engine


class TestComplianceEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loader, _ = load_dataset(PROJECT_ROOT / "data")
        cls.cl_manager, _ = build_care_levels(cls.loader)

        # Build billing engine with commands
        cls.billing = BillingEngine(cls.loader, cls.cl_manager)
        with open(PROJECT_ROOT / "data" / "commands.txt", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("|")
                cls.billing.process_command(parts[0], parts[1:], line_no)

        # Build staffing engine with 15-day roster
        cls.staffing, cls.req_df, cls.rost_df = execute_staffing_engine(cls.loader, cls.cl_manager)

        # Build compliance engine
        cls.compliance, cls.comp_df = execute_compliance_engine(cls.cl_manager, cls.billing, cls.staffing)

    def test_compliance_dataframe_schema(self):
        """Verifies compliance.csv schema columns and order."""
        expected_cols = ["month", "finding_type", "ref_id", "detail"]
        self.assertEqual(list(self.comp_df.columns), expected_cols)
        self.assertGreater(len(self.comp_df), 0)

    def test_overdue_reassessment_res033_august(self):
        """
        README Line 161: RES-033 reassessment due 2026-08-06 is done on 2026-08-22 (16 days late).
        Verifies that RES-033 is flagged as OVERDUE_REASSESSMENT in 2026-08.
        """
        aug_findings = self.compliance.get_findings_for_month("2026-08")
        overdue_aug = [f for f in aug_findings if f.finding_type == "OVERDUE_REASSESSMENT" and f.ref_id == "RES-033"]
        self.assertEqual(len(overdue_aug), 1)
        finding = overdue_aug[0]
        self.assertIn("16 days", finding.detail)
        self.assertIn("2026-08-06", finding.detail)
        self.assertIn("2026-08-22", finding.detail)

    def test_overdue_reassessments_october(self):
        """Verifies late periodic reassessments in October (RES-007, RES-015, RES-027)."""
        oct_findings = self.compliance.get_findings_for_month("2026-10")
        overdue_oct = [f for f in oct_findings if f.finding_type == "OVERDUE_REASSESSMENT"]
        res_ids = {f.ref_id for f in overdue_oct}
        self.assertIn("RES-007", res_ids)
        self.assertIn("RES-015", res_ids)
        self.assertIn("RES-027", res_ids)

    def test_late_payment_res003_september(self):
        """
        README Line 163: RES-003 August bill (due 2026-09-10) paid on 2026-09-15 (5 days late).
        Verifies that RES-003 is flagged as LATE_PAYMENT in 2026-09.
        """
        sep_findings = self.compliance.get_findings_for_month("2026-09")
        late_sep = [f for f in sep_findings if f.finding_type == "LATE_PAYMENT" and "RES-003" in f.ref_id]
        self.assertEqual(len(late_sep), 1)
        finding = late_sep[0]
        self.assertIn("5 days late", finding.detail)
        self.assertIn("2026-09-15", finding.detail)
        self.assertIn("2026-09-10", finding.detail)

    def test_late_payments_october(self):
        """Verifies late payments in October (September bills paid after Oct 10)."""
        oct_findings = self.compliance.get_findings_for_month("2026-10")
        late_oct = [f for f in oct_findings if f.finding_type == "LATE_PAYMENT"]
        ref_ids = [f.ref_id for f in late_oct]
        # RES-060 paid 2026-10-13, RES-035 paid 2026-10-21, RES-038 paid 2026-10-21
        self.assertTrue(any("RES-060" in r for r in ref_ids))
        self.assertTrue(any("RES-035" in r for r in ref_ids))
        self.assertTrue(any("RES-038" in r for r in ref_ids))

    def test_ratio_breach_findings_october(self):
        """Verifies that staffing shortfalls during October shifts generate RATIO_BREACH findings."""
        oct_findings = self.compliance.get_findings_for_month("2026-10")
        breaches = [f for f in oct_findings if f.finding_type == "RATIO_BREACH"]
        self.assertGreater(len(breaches), 0)
        # Check first breach format: date|shift|wing_id
        for b in breaches:
            parts = b.ref_id.split("|")
            self.assertEqual(len(parts), 3)
            self.assertIn(parts[1], ["DAY", "NIGHT"])
            self.assertIn(parts[2], ["WING-A", "WING-B", "WING-M"])
            self.assertIn("shortfall", b.detail.lower())

    def test_print_compliance_formatting(self):
        """Verifies the human-readable report generated for PRINT_COMPLIANCE."""
        report_aug = self.compliance.print_compliance("2026-08")
        self.assertIn("REGULATORY COMPLIANCE REPORT - 2026-08", report_aug)
        self.assertIn("OVERDUE_REASSESSMENT", report_aug)
        self.assertIn("RES-033", report_aug)

        report_empty = self.compliance.print_compliance("2026-07")
        self.assertIn("No compliance findings", report_empty)
        self.assertIn("FULLY COMPLIANT", report_empty)

    def test_deterministic_sorting(self):
        """Verifies findings in to_dataframe() are sorted deterministically."""
        df = self.compliance.to_dataframe()
        tuples = list(zip(df["month"], df["finding_type"], df["ref_id"]))
        self.assertEqual(tuples, sorted(tuples))

    def test_main_cli_execution(self):
        """Verifies that src/main.py executes end-to-end via CLI and generates all 5 output CSV files."""
        import subprocess
        main_script = PROJECT_ROOT / "src" / "main.py"
        result = subprocess.run(
            [sys.executable, str(main_script), "--quiet"],
            capture_output=True,
            text=True
        )
        self.assertEqual(result.returncode, 0, f"main.py failed: {result.stderr}")

        out_dir = PROJECT_ROOT / "outputs"
        expected_files = [
            "care_levels.csv",
            "bills.csv",
            "staffing_requirements.csv",
            "rosters.csv",
            "compliance.csv"
        ]
        for fname in expected_files:
            file_path = out_dir / fname
            self.assertTrue(file_path.exists(), f"Missing output file: {fname}")
            df = pd.read_csv(file_path)
            self.assertGreater(len(df), 0, f"Output file is empty: {fname}")

    def test_execute_pipeline_programmatic(self):
        """Verifies execute_pipeline programmatic API return values and DataFrames."""
        from src.main import execute_pipeline
        results = execute_pipeline(
            data_dir=PROJECT_ROOT / "data",
            output_dir=PROJECT_ROOT / "outputs",
            quiet=True
        )
        self.assertIn("care_levels_df", results)
        self.assertIn("bills_df", results)
        self.assertIn("staffing_requirements_df", results)
        self.assertIn("rosters_df", results)
        self.assertIn("compliance_df", results)
        self.assertEqual(len(results["care_levels_df"]), 87)
        self.assertEqual(len(results["bills_df"]), 341)
        self.assertEqual(len(results["staffing_requirements_df"]), 90)
        self.assertEqual(len(results["rosters_df"]), 355)
        self.assertEqual(len(results["compliance_df"]), 73)


if __name__ == "__main__":
    unittest.main()
