"""
PS-128 Elderly Care Home Billing and Staffing Ratio Engine
Module: data_loader.py
Team: T025

This module loads, parses, and validates all input data files for the care-home engine.
It uses Pandas for data manipulation and provides comprehensive data validation checks:
- Required column presence
- Unexpected missing values (respecting columns where empty values are permitted)
- Primary key uniqueness / duplicate checking
- Date format validation (YYYY-MM-DD)
- Data type and value-range constraints
- Foreign key referential integrity
- Anomaly detection (e.g., documented future admission dates for RES-050 / RES-070)
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import re
import pandas as pd


@dataclass
class ValidationIssue:
    """Represents a validation error or warning."""
    severity: str  # 'ERROR' or 'WARNING'
    file_name: str
    row_index: Optional[int]
    column: Optional[str]
    message: str


@dataclass
class ValidationReport:
    """Holds complete validation results across all loaded files."""
    file_summaries: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    errors: List[ValidationIssue] = field(default_factory=list)
    warnings: List[ValidationIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """Returns True if there are zero errors."""
        return len(self.errors) == 0

    def add_error(self, file_name: str, message: str, row_index: Optional[int] = None, column: Optional[str] = None):
        self.errors.append(ValidationIssue('ERROR', file_name, row_index, column, message))

    def add_warning(self, file_name: str, message: str, row_index: Optional[int] = None, column: Optional[str] = None):
        self.warnings.append(ValidationIssue('WARNING', file_name, row_index, column, message))

    def print_summary(self):
        """Prints a well-formatted summary of the validation report."""
        print("=" * 80)
        print("                    DATA LOADING & VALIDATION REPORT")
        print("=" * 80)
        print(f"{'File Name':<25} | {'Rows':<8} | {'Columns':<8} | {'Status':<10}")
        print("-" * 80)
        for fname, info in self.file_summaries.items():
            status = "FAILED" if info.get("errors", 0) > 0 else "OK"
            print(f"{fname:<25} | {info.get('rows', 0):<8} | {info.get('cols', 0):<8} | {status:<10}")
        print("-" * 80)
        print(f"Total Errors:   {len(self.errors)}")
        print(f"Total Warnings: {len(self.warnings)}")
        print("=" * 80)

        if self.errors:
            print("\n❌ VALIDATION ERRORS:")
            for err in self.errors:
                row_str = f"Row {err.row_index}: " if err.row_index is not None else ""
                col_str = f"Col '{err.column}': " if err.column else ""
                print(f"  [{err.file_name}] {row_str}{col_str}{err.message}")

        if self.warnings:
            print("\n⚠️ VALIDATION WARNINGS & NOTABLE OBSERVATIONS:")
            for warn in self.warnings:
                row_str = f"Row {warn.row_index}: " if warn.row_index is not None else ""
                col_str = f"Col '{warn.column}': " if warn.column else ""
                print(f"  [{warn.file_name}] {row_str}{col_str}{warn.message}")
        print("=" * 80)


class DataLoader:
    """
    Authoritative data loader and validator for the PS-128 engine.
    Loads all static and event CSV files into Pandas DataFrames and parses commands.txt.
    """

    EXPECTED_COLUMNS = {
        "wings.csv": ["wing_id", "wing_name", "memory_wing"],
        "fee_schedule.csv": ["care_level", "room_type", "monthly_fee"],
        "addon_rates.csv": ["addon_code", "description", "rate", "unit", "free_allowance"],
        "staffing_ratios.csv": ["role", "care_level", "day_ratio", "night_ratio", "notes"],
        "residents.csv": [
            "resident_id", "resident_name", "gender", "dob", "wing_id",
            "room_type", "admission_date", "family_contact_name",
            "family_mobile", "payment_mode", "late_payments_last_6m", "deposit_paid"
        ],
        "assessments.csv": [
            "assessment_id", "resident_id", "assessment_date", "reason",
            "adl_score", "cognitive_score", "fall_risk", "mobility", "assessed_by"
        ],
        "staff.csv": [
            "staff_id", "staff_name", "gender", "role",
            "dementia_trained", "contract_hours_week", "home_wing"
        ],
        "staff_leave.csv": ["staff_id", "leave_from", "leave_to", "leave_type"],
    }

    PRIMARY_KEYS = {
        "wings.csv": "wing_id",
        "residents.csv": "resident_id",
        "assessments.csv": "assessment_id",
        "staff.csv": "staff_id",
        "addon_rates.csv": "addon_code",
    }

    def __init__(self, data_dir: Union[str, Path]):
        self.data_dir = Path(data_dir)
        if not self.data_dir.exists():
            raise FileNotFoundError(f"Data directory does not exist: {self.data_dir}")

        self.report = ValidationReport()
        self.wings: Optional[pd.DataFrame] = None
        self.fee_schedule: Optional[pd.DataFrame] = None
        self.addon_rates: Optional[pd.DataFrame] = None
        self.staffing_ratios: Optional[pd.DataFrame] = None
        self.residents: Optional[pd.DataFrame] = None
        self.assessments: Optional[pd.DataFrame] = None
        self.staff: Optional[pd.DataFrame] = None
        self.staff_leave: Optional[pd.DataFrame] = None
        self.commands: List[Tuple[str, List[str], int, str]] = []  # (command_name, args, line_no, raw_line)

    def load_all(self) -> "DataLoader":
        """Loads all CSV files and commands.txt, executing full validation."""
        self.wings = self._load_csv("wings.csv")
        self.fee_schedule = self._load_csv("fee_schedule.csv")
        self.addon_rates = self._load_csv("addon_rates.csv", allow_empty_cols=["free_allowance"])
        self.staffing_ratios = self._load_csv("staffing_ratios.csv", allow_empty_cols=["care_level", "notes"])
        self.residents = self._load_csv("residents.csv")
        self.assessments = self._load_csv("assessments.csv")
        self.staff = self._load_csv("staff.csv")
        self.staff_leave = self._load_csv("staff_leave.csv")
        self.commands = self._load_commands("commands.txt")

        # Run cross-file integrity and domain-specific validation
        self._validate_domain_constraints()
        return self

    def _load_csv(self, file_name: str, allow_empty_cols: Optional[List[str]] = None) -> pd.DataFrame:
        """Loads a single CSV file with structural and syntax validation."""
        allow_empty_cols = allow_empty_cols or []
        file_path = self.data_dir / file_name

        if not file_path.exists():
            self.report.add_error(file_name, f"File not found: {file_path}")
            self.report.file_summaries[file_name] = {"rows": 0, "cols": 0, "errors": 1}
            return pd.DataFrame()

        try:
            # Load with string types initially to avoid silent cast corruptions
            df = pd.read_csv(file_path, dtype=str, keep_default_na=False)
        except Exception as e:
            self.report.add_error(file_name, f"Failed to parse CSV: {e}")
            self.report.file_summaries[file_name] = {"rows": 0, "cols": 0, "errors": 1}
            return pd.DataFrame()

        # Check required columns
        expected_cols = self.EXPECTED_COLUMNS.get(file_name, [])
        actual_cols = list(df.columns)
        missing_cols = set(expected_cols) - set(actual_cols)
        if missing_cols:
            self.report.add_error(file_name, f"Missing required columns: {sorted(missing_cols)}")

        # Check unexpected empty cells
        for col in actual_cols:
            if col not in allow_empty_cols:
                empty_mask = df[col].str.strip() == ""
                if empty_mask.any():
                    empty_rows = df[empty_mask].index.tolist()
                    self.report.add_error(
                        file_name,
                        f"Disallowed empty/whitespace values found in column '{col}' at rows: {empty_rows[:5]}",
                        column=col
                    )

        # Check duplicate primary keys
        pk_col = self.PRIMARY_KEYS.get(file_name)
        if pk_col and pk_col in df.columns:
            duplicates = df[df.duplicated(subset=[pk_col], keep=False)]
            if not duplicates.empty:
                dup_ids = duplicates[pk_col].unique().tolist()
                self.report.add_error(file_name, f"Duplicate primary key values in '{pk_col}': {dup_ids}", column=pk_col)

        # Check composite keys for fee_schedule and staffing_ratios
        if file_name == "fee_schedule.csv" and set(["care_level", "room_type"]).issubset(df.columns):
            duplicates = df[df.duplicated(subset=["care_level", "room_type"], keep=False)]
            if not duplicates.empty:
                self.report.add_error(file_name, "Duplicate (care_level, room_type) combinations found")

        self.report.file_summaries[file_name] = {
            "rows": len(df),
            "cols": len(df.columns),
            "errors": sum(1 for e in self.report.errors if e.file_name == file_name)
        }
        return df

    def _load_commands(self, file_name: str) -> List[Tuple[str, List[str], int, str]]:
        """Parses commands.txt preserving physical line numbers and strict order."""
        file_path = self.data_dir / file_name
        commands = []

        if not file_path.exists():
            self.report.add_error(file_name, f"Commands file not found: {file_path}")
            self.report.file_summaries[file_name] = {"rows": 0, "cols": 0, "errors": 1}
            return commands

        valid_command_verbs = {
            "FALL", "MED_ERROR", "HOSPITAL_ADMIT", "HOSPITAL_RETURN", "BED_RETAIN",
            "ADDON", "CONSUMABLE", "DISCHARGE_NOTICE", "VACATE", "DEATH",
            "GENERATE_BILLS", "PAYMENT", "BUILD_ROSTER", "PRINT_ROSTER",
            "PRINT_BILL", "PRINT_COMPLIANCE", "PRINT_CARE_PLAN"
        }

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line_no, raw_line in enumerate(f, start=1):
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("|")
                    verb = parts[0]
                    args = parts[1:]
                    if verb not in valid_command_verbs:
                        self.report.add_error(
                            file_name,
                            f"Unknown command verb '{verb}' on line {line_no}: {line}",
                            row_index=line_no
                        )
                    commands.append((verb, args, line_no, line))
        except Exception as e:
            self.report.add_error(file_name, f"Failed to read commands file: {e}")

        self.report.file_summaries[file_name] = {
            "rows": len(commands),
            "cols": 2,
            "errors": sum(1 for e in self.report.errors if e.file_name == file_name)
        }
        return commands

    def _validate_date_string(self, file_name: str, date_str: str, row_idx: int, col_name: str) -> bool:
        """Validates that a string strictly adheres to YYYY-MM-DD."""
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str.strip()):
            self.report.add_error(file_name, f"Invalid date format '{date_str}', expected YYYY-MM-DD", row_idx, col_name)
            return False
        try:
            datetime.strptime(date_str.strip(), "%Y-%m-%d")
            return True
        except ValueError as e:
            self.report.add_error(file_name, f"Invalid calendar date '{date_str}': {e}", row_idx, col_name)
            return False

    def _validate_domain_constraints(self):
        """Cross-table and semantic validation of domain rules."""
        # 1. Wings
        valid_wings = set()
        if self.wings is not None and not self.wings.empty:
            for idx, row in self.wings.iterrows():
                wid = row["wing_id"]
                if not re.match(r"^WING-[A-Za-z0-9]+$", wid):
                    self.report.add_error("wings.csv", f"Invalid wing_id format: {wid}", idx, "wing_id")
                valid_wings.add(wid)
                if row["memory_wing"].lower() not in ["true", "false"]:
                    self.report.add_error("wings.csv", f"memory_wing must be boolean true/false, got: {row['memory_wing']}", idx, "memory_wing")

        # 2. Fee Schedule
        if self.fee_schedule is not None and not self.fee_schedule.empty:
            for idx, row in self.fee_schedule.iterrows():
                if row["care_level"] not in ["LEVEL_1", "LEVEL_2", "LEVEL_3", "LEVEL_4"]:
                    self.report.add_error("fee_schedule.csv", f"Invalid care_level: {row['care_level']}", idx, "care_level")
                if row["room_type"] not in ["SHARED", "PRIVATE"]:
                    self.report.add_error("fee_schedule.csv", f"Invalid room_type: {row['room_type']}", idx, "room_type")
                if row["care_level"] == "LEVEL_4" and row["room_type"] != "PRIVATE":
                    self.report.add_error("fee_schedule.csv", "LEVEL_4 can only be PRIVATE room type", idx, "room_type")
                try:
                    fee = float(row["monthly_fee"])
                    if fee <= 0:
                        self.report.add_error("fee_schedule.csv", f"monthly_fee must be positive: {fee}", idx, "monthly_fee")
                except ValueError:
                    self.report.add_error("fee_schedule.csv", f"Invalid monthly_fee decimal: {row['monthly_fee']}", idx, "monthly_fee")

        # 3. Addon Rates
        if self.addon_rates is not None and not self.addon_rates.empty:
            for idx, row in self.addon_rates.iterrows():
                try:
                    rate = float(row["rate"])
                    if rate < 0:
                        self.report.add_error("addon_rates.csv", f"rate must be non-negative: {rate}", idx, "rate")
                except ValueError:
                    self.report.add_error("addon_rates.csv", f"Invalid rate decimal: {row['rate']}", idx, "rate")

        # 4. Residents
        valid_residents = set()
        if self.residents is not None and not self.residents.empty:
            for idx, row in self.residents.iterrows():
                rid = row["resident_id"]
                if not re.match(r"^RES-\d{3}$", rid):
                    self.report.add_error("residents.csv", f"Invalid resident_id format: {rid}", idx, "resident_id")
                valid_residents.add(rid)

                if row["gender"] not in ["M", "F"]:
                    self.report.add_error("residents.csv", f"Invalid gender: {row['gender']}", idx, "gender")

                self._validate_date_string("residents.csv", row["dob"], idx, "dob")
                self._validate_date_string("residents.csv", row["admission_date"], idx, "admission_date")

                if row["wing_id"] not in valid_wings:
                    self.report.add_error("residents.csv", f"Foreign key error: wing_id '{row['wing_id']}' not in wings.csv", idx, "wing_id")

                if row["room_type"] not in ["SHARED", "PRIVATE"]:
                    self.report.add_error("residents.csv", f"Invalid room_type: {row['room_type']}", idx, "room_type")

                if not re.match(r"^\d{10}$", row["family_mobile"].strip()):
                    self.report.add_error("residents.csv", f"family_mobile must be 10 digits: {row['family_mobile']}", idx, "family_mobile")

                if row["payment_mode"] not in ["AUTO_DEBIT", "MANUAL"]:
                    self.report.add_error("residents.csv", f"Invalid payment_mode: {row['payment_mode']}", idx, "payment_mode")

                try:
                    late_count = int(row["late_payments_last_6m"])
                    if late_count < 0:
                        self.report.add_error("residents.csv", f"late_payments_last_6m cannot be negative: {late_count}", idx, "late_payments_last_6m")
                except ValueError:
                    self.report.add_error("residents.csv", f"Invalid late_payments_last_6m int: {row['late_payments_last_6m']}", idx, "late_payments_last_6m")

                try:
                    deposit = float(row["deposit_paid"])
                    if deposit < 0:
                        self.report.add_error("residents.csv", f"deposit_paid cannot be negative: {deposit}", idx, "deposit_paid")
                except ValueError:
                    self.report.add_error("residents.csv", f"Invalid deposit_paid decimal: {row['deposit_paid']}", idx, "deposit_paid")

                # Documented anomalies: future admission dates
                if row["admission_date"] > "2026-10-31":
                    self.report.add_warning(
                        "residents.csv",
                        f"Resident {rid} ({row['resident_name']}) has admission_date in future ({row['admission_date']}). "
                        f"Handled per decision_log.md Ambiguity 1 (active resident with earlier assessments).",
                        idx,
                        "admission_date"
                    )

        # 5. Assessments
        if self.assessments is not None and not self.assessments.empty:
            for idx, row in self.assessments.iterrows():
                aid = row["assessment_id"]
                if not re.match(r"^ASM-\d{4}$", aid):
                    self.report.add_error("assessments.csv", f"Invalid assessment_id format: {aid}", idx, "assessment_id")

                rid = row["resident_id"]
                if rid not in valid_residents:
                    self.report.add_error("assessments.csv", f"Foreign key error: resident_id '{rid}' not in residents.csv", idx, "resident_id")

                self._validate_date_string("assessments.csv", row["assessment_date"], idx, "assessment_date")

                if row["reason"] not in ["ADMISSION", "PERIODIC", "FALL", "INCIDENT"]:
                    self.report.add_error("assessments.csv", f"Invalid assessment reason: {row['reason']}", idx, "reason")

                try:
                    adl = int(row["adl_score"])
                    if not (0 <= adl <= 6):
                        self.report.add_error("assessments.csv", f"adl_score must be between 0 and 6: {adl}", idx, "adl_score")
                except ValueError:
                    self.report.add_error("assessments.csv", f"Invalid adl_score int: {row['adl_score']}", idx, "adl_score")

                try:
                    cog = int(row["cognitive_score"])
                    if not (0 <= cog <= 30):
                        self.report.add_error("assessments.csv", f"cognitive_score must be between 0 and 30: {cog}", idx, "cognitive_score")
                except ValueError:
                    self.report.add_error("assessments.csv", f"Invalid cognitive_score int: {row['cognitive_score']}", idx, "cognitive_score")

                if row["fall_risk"].lower() not in ["true", "false"]:
                    self.report.add_error("assessments.csv", f"fall_risk must be boolean: {row['fall_risk']}", idx, "fall_risk")

                if row["mobility"] not in ["INDEPENDENT", "WALKER", "WHEELCHAIR", "BEDBOUND"]:
                    self.report.add_error("assessments.csv", f"Invalid mobility: {row['mobility']}", idx, "mobility")

        # 6. Staff
        valid_staff = set()
        if self.staff is not None and not self.staff.empty:
            for idx, row in self.staff.iterrows():
                sid = row["staff_id"]
                if not re.match(r"^STF-\d{2}$", sid):
                    self.report.add_error("staff.csv", f"Invalid staff_id format: {sid}", idx, "staff_id")
                valid_staff.add(sid)

                if row["gender"] not in ["M", "F"]:
                    self.report.add_error("staff.csv", f"Invalid gender: {row['gender']}", idx, "gender")

                if row["role"] not in ["CAREGIVER", "NURSE"]:
                    self.report.add_error("staff.csv", f"Invalid role: {row['role']}", idx, "role")

                if row["dementia_trained"].lower() not in ["true", "false"]:
                    self.report.add_error("staff.csv", f"dementia_trained must be boolean: {row['dementia_trained']}", idx, "dementia_trained")

                try:
                    hours = int(row["contract_hours_week"])
                    if hours != 48:
                        self.report.add_warning("staff.csv", f"Unexpected contract_hours_week: {hours} (expected 48)", idx, "contract_hours_week")
                except ValueError:
                    self.report.add_error("staff.csv", f"Invalid contract_hours_week int: {row['contract_hours_week']}", idx, "contract_hours_week")

                if row["home_wing"] not in valid_wings:
                    self.report.add_error("staff.csv", f"Foreign key error: home_wing '{row['home_wing']}' not in wings.csv", idx, "home_wing")

        # 7. Staff Leave
        if self.staff_leave is not None and not self.staff_leave.empty:
            for idx, row in self.staff_leave.iterrows():
                sid = row["staff_id"]
                if sid not in valid_staff:
                    self.report.add_error("staff_leave.csv", f"Foreign key error: staff_id '{sid}' not in staff.csv", idx, "staff_id")

                v_from = self._validate_date_string("staff_leave.csv", row["leave_from"], idx, "leave_from")
                v_to = self._validate_date_string("staff_leave.csv", row["leave_to"], idx, "leave_to")

                if v_from and v_to:
                    d_from = datetime.strptime(row["leave_from"].strip(), "%Y-%m-%d")
                    d_to = datetime.strptime(row["leave_to"].strip(), "%Y-%m-%d")
                    if d_from > d_to:
                        self.report.add_error("staff_leave.csv", f"leave_from ({row['leave_from']}) cannot be after leave_to ({row['leave_to']})", idx, "leave_from")

                if row["leave_type"] not in ["CASUAL", "SICK", "EARNED"]:
                    self.report.add_error("staff_leave.csv", f"Invalid leave_type: {row['leave_type']}", idx, "leave_type")


def load_dataset(data_dir: Union[str, Path]) -> Tuple[DataLoader, ValidationReport]:
    """Convenience factory function to load and validate all files."""
    loader = DataLoader(data_dir)
    loader.load_all()
    return loader, loader.report


if __name__ == "__main__":
    # Test script directly when run as main
    project_root = Path(__file__).resolve().parent.parent
    data_path = project_root / "data"
    print(f"Loading data from: {data_path.resolve()}\n")

    loader, report = load_dataset(data_path)
    report.print_summary()
