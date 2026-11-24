"""
compliance.py - Regulatory Compliance and Audit Engine
PS-128 / Team T025: Elderly Care Home Resident Care-level Billing and Staffing Ratio Engine

Business Rules & Specifications:
- README.md lines 198-202:
  compliance.csv: One row per finding per month (overdue reassessments, ratio breaches, late payments).
  Columns, in order: month, finding_type, ref_id, detail
- decision_log.md & BR-CO-01:
  Cadence: 90 days for LEVEL_1 and LEVEL_2; 30 days for LEVEL_3 and LEVEL_4.
  Overdue reassessment occurs when periodic assessment is delayed past cadence due date.
- Ratio breaches:
  Occur when staffing shortfall > 0 on any wing/shift.
- Late payments:
  Bills are due on the 10th of the issue month (issued 1st of following month in arrears).
  Payments received after the 10th are late payments.
"""

import sys
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Union
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.care_levels import CareLevelManager, CareLevel
from src.billing import BillingEngine
from src.staffing import StaffingEngine


@dataclass
class ComplianceFinding:
    month: str
    finding_type: str  # OVERDUE_REASSESSMENT, RATIO_BREACH, LATE_PAYMENT
    ref_id: str
    detail: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "month": self.month,
            "finding_type": self.finding_type,
            "ref_id": self.ref_id,
            "detail": self.detail
        }


class ComplianceEngine:
    """
    Monitors, evaluates and reports all regulatory compliance findings across:
    1. Overdue periodic resident care reassessments.
    2. Staffing ratio breaches and shift shortfalls.
    3. Late billing payments.
    """

    def __init__(
        self,
        care_level_manager: CareLevelManager,
        billing_engine: BillingEngine,
        staffing_engine: StaffingEngine
    ):
        self.cl_manager = care_level_manager
        self.billing = billing_engine
        self.staffing = staffing_engine
        self.findings: List[ComplianceFinding] = []

    def check_overdue_reassessments(self, month: Optional[str] = None) -> List[ComplianceFinding]:
        """
        Identifies periodic reassessments that were conducted past their required cadence due date,
        or overdue periodic reassessments.
        Cadence:
        - LEVEL_1 & LEVEL_2: 90 days
        - LEVEL_3 & LEVEL_4: 30 days
        """
        findings: List[ComplianceFinding] = []
        for res_id, asm_list in sorted(self.cl_manager.assessments_by_resident.items()):
            asm_sorted = sorted(asm_list, key=lambda x: x["assessment_date"])
            for i in range(1, len(asm_sorted)):
                prev = asm_sorted[i - 1]
                curr = asm_sorted[i]
                d_prev = datetime.strptime(prev["assessment_date"], "%Y-%m-%d").date()
                d_curr = datetime.strptime(curr["assessment_date"], "%Y-%m-%d").date()
                diff_days = (d_curr - d_prev).days

                # Look up effective care level on prev assessment date
                eff = self.cl_manager.get_effective_care_level(res_id, prev["assessment_date"])
                curr_lvl = eff.care_level if eff else "LEVEL_1"
                cadence = self.cl_manager.get_cadence_days(curr_lvl)

                if diff_days > cadence and curr["reason"] == "PERIODIC":
                    due_date = (d_prev + timedelta(days=cadence)).strftime("%Y-%m-%d")
                    late_days = diff_days - cadence
                    f_month = curr["assessment_date"][:7]

                    if month is None or f_month == month:
                        detail = (
                            f"Periodic reassessment overdue by {late_days} days "
                            f"(due {due_date}, conducted {curr['assessment_date']})"
                        )
                        findings.append(ComplianceFinding(
                            month=f_month,
                            finding_type="OVERDUE_REASSESSMENT",
                            ref_id=res_id,
                            detail=detail
                        ))
        return findings

    def check_ratio_breaches(self, month: Optional[str] = None) -> List[ComplianceFinding]:
        """
        Identifies all shift ratio breaches where assigned staff is less than required,
        resulting in a shortfall.
        """
        findings: List[ComplianceFinding] = []
        requirements = self.staffing.shift_requirements.values() if hasattr(self.staffing, "shift_requirements") else []
        for req in requirements:
            if req.shortfall > 0:
                f_month = req.date[:7]
                if month is None or f_month == month:
                    ref_id = f"{req.date}|{req.shift}|{req.wing_id}"
                    detail = (
                        f"Staffing shortfall of {req.shortfall} staff "
                        f"(caregivers required {req.caregivers_required}, assigned {req.caregivers_assigned}; "
                        f"nurses required {req.nurses_required}, assigned {req.nurses_assigned}; "
                        f"agency cost Rs {req.agency_cost:.2f})"
                    )
                    findings.append(ComplianceFinding(
                        month=f_month,
                        finding_type="RATIO_BREACH",
                        ref_id=ref_id,
                        detail=detail
                    ))
        return findings

    def check_late_payments(self, month: Optional[str] = None) -> List[ComplianceFinding]:
        """
        Identifies all invoices that were paid after the due date (10th of the issue month).
        """
        findings: List[ComplianceFinding] = []
        for (res_id, inv_month), inv in sorted(self.billing.invoices.items()):
            if inv.is_late and inv.payment_date:
                f_month = inv.payment_date[:7]
                if month is None or f_month == month:
                    d_pay = datetime.strptime(inv.payment_date, "%Y-%m-%d").date()
                    d_due = datetime.strptime(inv.due_date, "%Y-%m-%d").date()
                    days_late = (d_pay - d_due).days
                    detail = (
                        f"Payment for bill {inv.bill_id} received on {inv.payment_date} "
                        f"(due {inv.due_date}, {days_late} days late)"
                    )
                    findings.append(ComplianceFinding(
                        month=f_month,
                        finding_type="LATE_PAYMENT",
                        ref_id=inv.bill_id,
                        detail=detail
                    ))
        return findings

    def compile_all_findings(self) -> List[ComplianceFinding]:
        """Compiles all compliance findings across all three categories in deterministic order."""
        all_findings = []
        all_findings.extend(self.check_overdue_reassessments())
        all_findings.extend(self.check_ratio_breaches())
        all_findings.extend(self.check_late_payments())

        # Deterministic sort: month ASC, finding_type ASC, ref_id ASC
        all_findings.sort(key=lambda f: (f.month, f.finding_type, f.ref_id))
        self.findings = all_findings
        return self.findings

    def get_findings_for_month(self, month: str) -> List[ComplianceFinding]:
        """Returns all compiled findings for a specific calendar month."""
        if not self.findings:
            self.compile_all_findings()
        return [f for f in self.findings if f.month == month]

    def print_compliance(self, month: str) -> str:
        """
        Formats human-readable statement for PRINT_COMPLIANCE|YYYY-MM command.
        """
        findings = self.get_findings_for_month(month)
        lines = []
        lines.append("=" * 80)
        lines.append(f"                 REGULATORY COMPLIANCE REPORT - {month}")
        lines.append("=" * 80)

        if not findings:
            lines.append("No compliance findings or violations recorded for this month.")
            lines.append("Status: FULLY COMPLIANT")
            lines.append("=" * 80)
            return "\n".join(lines)

        lines.append(f"{'Finding Type':<25} | {'Reference ID':<22} | {'Details'}")
        lines.append("-" * 80)

        for f in findings:
            lines.append(f"{f.finding_type:<25} | {f.ref_id:<22} | {f.detail}")

        lines.append("-" * 80)
        lines.append(f"TOTAL FINDINGS: {len(findings)}")
        lines.append("=" * 80)
        return "\n".join(lines)

    def to_dataframe(self) -> pd.DataFrame:
        """Returns pandas DataFrame with exact columns: month, finding_type, ref_id, detail."""
        if not self.findings:
            self.compile_all_findings()
        records = [f.to_dict() for f in self.findings]
        cols = ["month", "finding_type", "ref_id", "detail"]
        if not records:
            return pd.DataFrame(columns=cols)
        df = pd.DataFrame(records)[cols]
        return df

    def export_csv(self, filepath: Union[str, Path]) -> pd.DataFrame:
        """Exports compliance findings to evaluation CSV file."""
        df = self.to_dataframe()
        out_path = Path(filepath)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_path, index=False)
        return df


def execute_compliance_engine(
    care_level_manager: CareLevelManager,
    billing_engine: BillingEngine,
    staffing_engine: StaffingEngine
) -> Tuple[ComplianceEngine, pd.DataFrame]:
    """Factory helper to execute the compliance engine and return the engine and findings DataFrame."""
    engine = ComplianceEngine(care_level_manager, billing_engine, staffing_engine)
    df = engine.to_dataframe()
    return engine, df
