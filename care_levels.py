"""
PS-128 Elderly Care Home Billing and Staffing Ratio Engine
Module: care_levels.py
Team: T025

This module manages resident care levels based on:
1. ADL and cognitive assessment scoring bands.
2. Clinical band resolution (higher level taken when scores imply different bands).
3. Fall-risk elevation (+1 level, capped at LEVEL_4).
4. Effective dates:
   - Care-level increases take effect IMMEDIATELY on assessment_date / event_date.
   - Care-level decreases take effect on the 1st day of the FOLLOWING month.
5. Fall escalation:
   - A second fall within 30 days (<= 30 days inclusive) of a previous fall
     triggers an immediate one-level escalation (basis: FALL_ESCALATION).
6. Periodic reassessment cadence:
   - LEVEL_1 and LEVEL_2: 90 days (quarterly).
   - LEVEL_3 and LEVEL_4: 30 days (monthly).
   - Tracking overdue assessments and latency.
7. Preserving full history for generating care_levels.csv.
"""

from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple, Union
import pandas as pd


class CareLevel(str, Enum):
    LEVEL_1 = "LEVEL_1"
    LEVEL_2 = "LEVEL_2"
    LEVEL_3 = "LEVEL_3"
    LEVEL_4 = "LEVEL_4"

    @property
    def rank(self) -> int:
        """Returns integer severity rank (1..4)."""
        return int(self.value.split("_")[1])

    def __lt__(self, other: "CareLevel") -> bool:
        return self.rank < other.rank

    def __le__(self, other: "CareLevel") -> bool:
        return self.rank <= other.rank

    def __gt__(self, other: "CareLevel") -> bool:
        return self.rank > other.rank

    def __ge__(self, other: "CareLevel") -> bool:
        return self.rank >= other.rank

    def elevate(self, steps: int = 1) -> "CareLevel":
        """Elevates level by steps, capped at LEVEL_4."""
        new_rank = min(4, self.rank + steps)
        return CareLevel(f"LEVEL_{new_rank}")


class Basis(str, Enum):
    ASSESSMENT = "ASSESSMENT"
    FALL_RISK = "FALL_RISK"
    FALL_ESCALATION = "FALL_ESCALATION"


CADENCE_DAYS = {
    CareLevel.LEVEL_1: 90,
    CareLevel.LEVEL_2: 90,
    CareLevel.LEVEL_3: 30,
    CareLevel.LEVEL_4: 30,
}


def score_adl(adl: int) -> CareLevel:
    """
    Maps ADL score (0-6) to CareLevel:
    - 0-1: LEVEL_1
    - 2-3: LEVEL_2
    - 4-5: LEVEL_3
    - 6:   LEVEL_4
    """
    if adl <= 1:
        return CareLevel.LEVEL_1
    elif adl <= 3:
        return CareLevel.LEVEL_2
    elif adl <= 5:
        return CareLevel.LEVEL_3
    else:
        return CareLevel.LEVEL_4


def score_cognitive(cog: int) -> CareLevel:
    """
    Maps Cognitive score (0-30) to CareLevel:
    - 24-30: LEVEL_1
    - 18-23: LEVEL_2
    - 10-17: LEVEL_3
    - 0-9:   LEVEL_4
    """
    if cog >= 24:
        return CareLevel.LEVEL_1
    elif cog >= 18:
        return CareLevel.LEVEL_2
    elif cog >= 10:
        return CareLevel.LEVEL_3
    else:
        return CareLevel.LEVEL_4


def determine_care_level(adl: int, cog: int, fall_risk: bool = False) -> Tuple[CareLevel, Basis, bool]:
    """
    Determines care level based on ADL and Cognitive scores and fall risk.
    - Two different levels implied: resolves to the higher (more severe) level (EC-01).
    - If fall_risk=True, elevates by 1 level, capped at LEVEL_4 (EC-02).
    Returns (final_level, basis, elevated_by_fall_risk).
    """
    adl_lvl = score_adl(adl)
    cog_lvl = score_cognitive(cog)
    base_level = max(adl_lvl, cog_lvl)

    if fall_risk:
        if base_level < CareLevel.LEVEL_4:
            final_level = base_level.elevate(1)
            return final_level, Basis.FALL_RISK, True
        else:
            # Already LEVEL_4, capped at LEVEL_4 (EC-02)
            return CareLevel.LEVEL_4, Basis.ASSESSMENT, False
    else:
        return base_level, Basis.ASSESSMENT, False


def get_first_day_of_next_month(date_str: str) -> str:
    """Returns the 1st day of the following calendar month (YYYY-MM-01)."""
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    if d.month == 12:
        return date(d.year + 1, 1, 1).strftime("%Y-%m-%d")
    else:
        return date(d.year, d.month + 1, 1).strftime("%Y-%m-%d")


def add_days_to_date(date_str: str, days: int) -> str:
    """Adds N days to a YYYY-MM-DD date string."""
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    return (d + timedelta(days=days)).strftime("%Y-%m-%d")


@dataclass
class CareLevelRecord:
    """A single care level state transition."""
    resident_id: str
    effective_date: str
    care_level: str
    basis: str
    fall_risk_until: str = ""
    assessment_id: Optional[str] = None

    def to_dict(self) -> Dict[str, str]:
        return {
            "resident_id": self.resident_id,
            "effective_date": self.effective_date,
            "care_level": self.care_level,
            "basis": self.basis,
            "fall_risk_until": self.fall_risk_until,
        }


@dataclass
class ReassessmentStatus:
    """Reassessment schedule and overdue tracking."""
    resident_id: str
    current_level: CareLevel
    last_assessment_date: str
    cadence_days: int
    due_date: str
    is_overdue: bool
    days_overdue: int


class CareLevelManager:
    """
    Manages resident assessment history, care level transitions,
    fall incidents, escalation logic, and overdue assessment detection.
    """

    def __init__(self):
        # resident_id -> list of CareLevelRecord in chronological effective order
        self.history: Dict[str, List[CareLevelRecord]] = {}
        # resident_id -> list of raw assessment dicts sorted by date
        self.assessments_by_resident: Dict[str, List[Dict]] = {}
        # resident_id -> list of fall incident dates (YYYY-MM-DD)
        self.falls_by_resident: Dict[str, List[str]] = {}
        # Pending decreases: resident_id -> (effective_date, CareLevelRecord)
        self.pending_decreases: Dict[str, List[CareLevelRecord]] = {}

    def get_cadence_days(self, level: Union[CareLevel, str]) -> int:
        """Returns the reassessment cadence in days for a given care level."""
        if isinstance(level, str):
            level = CareLevel(level)
        return CADENCE_DAYS.get(level, 30)

    def process_all_data(self, assessments_df: pd.DataFrame, commands: List[Tuple[str, List[str], int, str]]):
        """
        Coordinates full processing of assessments and fall commands chronologically.
        Events are interleaved by date to ensure proper state progression.
        """
        # Step 1: Collect all raw assessments
        all_events = []
        for _, row in assessments_df.iterrows():
            all_events.append({
                "type": "ASSESSMENT",
                "date": row["assessment_date"],
                "data": row.to_dict()
            })

        # Step 2: Collect all FALL commands
        for verb, args, line_no, raw in commands:
            if verb == "FALL":
                # args: resident_id, timestamp (YYYY-MM-DD HH:MM:SS), location
                res_id = args[0]
                ts_str = args[1]
                fall_date = ts_str.split(" ")[0]
                all_events.append({
                    "type": "FALL",
                    "date": fall_date,
                    "resident_id": res_id,
                    "timestamp": ts_str,
                    "location": args[2] if len(args) > 2 else ""
                })

        # Sort all events chronologically. For same-day events, process FALL then ASSESSMENT.
        all_events.sort(key=lambda x: (x["date"], 0 if x["type"] == "FALL" else 1))

        # Process each event in timeline
        for ev in all_events:
            if ev["type"] == "FALL":
                self.record_fall(ev["resident_id"], ev["date"])
            elif ev["type"] == "ASSESSMENT":
                self.process_assessment(ev["data"])

    def record_fall(self, resident_id: str, fall_date: str) -> Optional[CareLevelRecord]:
        """
        Records a fall incident and evaluates the 2-falls-in-30-days escalation rule (EC-07).
        If second fall occurs <= 30 days from previous fall, triggers immediate one-level escalation.
        """
        if resident_id not in self.falls_by_resident:
            self.falls_by_resident[resident_id] = []

        prior_falls = list(self.falls_by_resident[resident_id])
        self.falls_by_resident[resident_id].append(fall_date)

        if not prior_falls:
            return None

        # Check if the immediately preceding fall occurred within 30 days
        last_fall_date = prior_falls[-1]
        d_last = datetime.strptime(last_fall_date, "%Y-%m-%d").date()
        d_curr = datetime.strptime(fall_date, "%Y-%m-%d").date()
        delta_days = (d_curr - d_last).days

        # Rule EC-07: exactly 30 days (<= 30) qualifies as within 30 days
        if 0 < delta_days <= 30:
            current_rec = self.get_effective_care_level(resident_id, fall_date)
            if current_rec:
                curr_level = CareLevel(current_rec.care_level)
                if curr_level < CareLevel.LEVEL_4:
                    escalated_level = curr_level.elevate(1)
                    fall_until = add_days_to_date(fall_date, 30)
                    new_rec = CareLevelRecord(
                        resident_id=resident_id,
                        effective_date=fall_date,
                        care_level=escalated_level.value,
                        basis=Basis.FALL_ESCALATION.value,
                        fall_risk_until=fall_until
                    )
                    self._add_record(new_rec)
                    return new_rec
        return None

    def process_assessment(self, row: Dict) -> Optional[CareLevelRecord]:
        """
        Processes an assessment record:
        - Establishes initial care level for new residents.
        - Immediate effective date for care-level increases.
        - Next-month 1st day effective date for care-level decreases.
        - Records fall_risk_until where fall_risk=True.
        """
        res_id = row["resident_id"]
        asm_date = row["assessment_date"]
        adl = int(row["adl_score"])
        cog = int(row["cognitive_score"])
        fall_risk = str(row.get("fall_risk", "false")).lower() == "true"
        asm_id = row.get("assessment_id")

        if res_id not in self.assessments_by_resident:
            self.assessments_by_resident[res_id] = []
        self.assessments_by_resident[res_id].append(row)

        determined_level, basis, elevated = determine_care_level(adl, cog, fall_risk)
        fall_until = add_days_to_date(asm_date, 30) if fall_risk else ""

        # Case 1: Initial assessment for this resident
        if res_id not in self.history or len(self.history[res_id]) == 0:
            rec = CareLevelRecord(
                resident_id=res_id,
                effective_date=asm_date,
                care_level=determined_level.value,
                basis=basis.value,
                fall_risk_until=fall_until,
                assessment_id=asm_id
            )
            self._add_record(rec)
            return rec

        # Case 2: Subsequent assessment — compare against current effective level
        current_rec = self.get_effective_care_level(res_id, asm_date)
        current_level = CareLevel(current_rec.care_level)

        if determined_level > current_level:
            # CARE-LEVEL INCREASE: takes effect IMMEDIATELY
            rec = CareLevelRecord(
                resident_id=res_id,
                effective_date=asm_date,
                care_level=determined_level.value,
                basis=basis.value,
                fall_risk_until=fall_until,
                assessment_id=asm_id
            )
            self._add_record(rec)
            return rec

        elif determined_level < current_level:
            # CARE-LEVEL DECREASE: takes effect 1st of NEXT month (README line 160)
            effective_next_month = get_first_day_of_next_month(asm_date)
            rec = CareLevelRecord(
                resident_id=res_id,
                effective_date=effective_next_month,
                care_level=determined_level.value,
                basis=Basis.ASSESSMENT.value,
                fall_risk_until=fall_until,
                assessment_id=asm_id
            )
            self._add_record(rec)
            return rec

        else:
            # Level remains unchanged. If fall_risk was introduced on same level, update fall_risk_until
            if fall_risk and not current_rec.fall_risk_until:
                rec = CareLevelRecord(
                    resident_id=res_id,
                    effective_date=asm_date,
                    care_level=determined_level.value,
                    basis=Basis.FALL_RISK.value if elevated else current_rec.basis,
                    fall_risk_until=fall_until,
                    assessment_id=asm_id
                )
                self._add_record(rec)
                return rec
            return None

    def _add_record(self, record: CareLevelRecord):
        """Adds a care level record ensuring ordering and avoiding redundant duplicates."""
        res_id = record.resident_id
        if res_id not in self.history:
            self.history[res_id] = []

        history_list = self.history[res_id]
        if history_list:
            last_rec = history_list[-1]
            # If same effective date, replace or keep higher
            if last_rec.effective_date == record.effective_date:
                if CareLevel(record.care_level) >= CareLevel(last_rec.care_level):
                    history_list[-1] = record
                return
            # If care level is identical and basis/fall_risk is identical, skip redundant row
            if (last_rec.care_level == record.care_level and
                last_rec.basis == record.basis and
                last_rec.fall_risk_until == record.fall_risk_until):
                return

        history_list.append(record)
        # Ensure chronological order by effective_date
        history_list.sort(key=lambda r: r.effective_date)

    def get_effective_care_level(self, resident_id: str, as_of_date: str) -> Optional[CareLevelRecord]:
        """
        Returns the active CareLevelRecord for resident_id on as_of_date.
        If before the first recorded effective date, returns the initial record.
        """
        history_list = self.history.get(resident_id, [])
        if not history_list:
            return None

        # Binary or linear scan for the latest record with effective_date <= as_of_date
        active_rec = history_list[0]
        for rec in history_list:
            if rec.effective_date <= as_of_date:
                active_rec = rec
            else:
                break
        return active_rec

    def get_reassessment_status(self, resident_id: str, as_of_date: str) -> Optional[ReassessmentStatus]:
        """
        Evaluates whether a resident's periodic reassessment is overdue on as_of_date.
        Cadence is 90 days for LEVEL_1/2 and 30 days for LEVEL_3/4.
        """
        assessments = self.assessments_by_resident.get(resident_id, [])
        if not assessments:
            return None

        # Filter assessments up to as_of_date
        prior_assessments = [a for a in assessments if a["assessment_date"] <= as_of_date]
        if not prior_assessments:
            return None

        last_asm = prior_assessments[-1]
        last_date = last_asm["assessment_date"]
        current_rec = self.get_effective_care_level(resident_id, as_of_date)
        curr_lvl = CareLevel(current_rec.care_level) if current_rec else CareLevel.LEVEL_1

        cadence = self.get_cadence_days(curr_lvl)
        due_date = add_days_to_date(last_date, cadence)

        d_as_of = datetime.strptime(as_of_date, "%Y-%m-%d").date()
        d_due = datetime.strptime(due_date, "%Y-%m-%d").date()

        days_overdue = (d_as_of - d_due).days
        is_overdue = days_overdue > 0

        return ReassessmentStatus(
            resident_id=resident_id,
            current_level=curr_lvl,
            last_assessment_date=last_date,
            cadence_days=cadence,
            due_date=due_date,
            is_overdue=is_overdue,
            days_overdue=max(0, days_overdue)
        )

    def get_overdue_assessments(self, as_of_date: str) -> List[ReassessmentStatus]:
        """Returns all residents who have overdue reassessments on as_of_date."""
        overdue_list = []
        for res_id in self.assessments_by_resident.keys():
            status = self.get_reassessment_status(res_id, as_of_date)
            if status and status.is_overdue:
                overdue_list.append(status)
        return overdue_list

    def to_dataframe(self) -> pd.DataFrame:
        """
        Generates the exact care_levels.csv output DataFrame.
        Columns: resident_id, effective_date, care_level, basis, fall_risk_until
        Sorted by resident_id and effective_date.
        """
        rows = []
        for res_id in sorted(self.history.keys()):
            for rec in self.history[res_id]:
                rows.append(rec.to_dict())

        df = pd.DataFrame(rows, columns=[
            "resident_id", "effective_date", "care_level", "basis", "fall_risk_until"
        ])
        return df

    def print_care_plan(self, resident_id: str, resident_info: Optional[Dict] = None) -> str:
        """Generates a human-readable statement for PRINT_CARE_PLAN command."""
        history = self.history.get(resident_id, [])
        if not history:
            return f"No care plan found for resident {resident_id}."

        latest_rec = history[-1]
        name = resident_info.get("resident_name", resident_id) if resident_info else resident_id
        wing = resident_info.get("wing_id", "Unknown") if resident_info else "Unknown"
        room = resident_info.get("room_type", "Unknown") if resident_info else "Unknown"

        lines = []
        lines.append("=" * 80)
        lines.append(f"                           RESIDENT CARE PLAN")
        lines.append("=" * 80)
        lines.append(f"Resident:       {name} ({resident_id})")
        lines.append(f"Wing / Room:    {wing} / {room}")
        lines.append(f"Current Level:  {latest_rec.care_level} (Effective: {latest_rec.effective_date})")
        lines.append(f"Basis:          {latest_rec.basis}")
        fr_str = f"YES (Until {latest_rec.fall_risk_until})" if latest_rec.fall_risk_until else "NO"
        lines.append(f"Fall Risk:      {fr_str}")
        lines.append("-" * 80)
        lines.append(f"{'Effective Date':<15} | {'Care Level':<12} | {'Basis':<18} | {'Fall Risk Until':<15}")
        lines.append("-" * 80)
        for h in history:
            fr = h.fall_risk_until or "None"
            lines.append(f"{h.effective_date:<15} | {h.care_level:<12} | {h.basis:<18} | {fr:<15}")
        lines.append("=" * 80)
        return "\n".join(lines)


def build_care_levels(data_loader) -> Tuple[CareLevelManager, pd.DataFrame]:
    """Helper function to instantiate and run CareLevelManager from DataLoader."""
    manager = CareLevelManager()
    manager.process_all_data(data_loader.assessments, data_loader.commands)
    df = manager.to_dataframe()
    return manager, df


if __name__ == "__main__":
    import sys
    from pathlib import Path
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from src.data_loader import load_dataset

    loader, _ = load_dataset(project_root / "data")
    manager, df = build_care_levels(loader)

    print("=" * 80)
    print("                    CARE LEVELS GENERATION SUMMARY")
    print("=" * 80)
    print(f"Total Residents Processed: {len(manager.history)}")
    print(f"Total Care Level Records:  {len(df)}")
    print("-" * 80)
    print("\nSample records:")
    print(df.head(15).to_string(index=False))
    print("\nNotable edge-case checks:")
    print("RES-014 (EC-07 fall escalation & decrease):")
    print(df[df["resident_id"] == "RES-014"].to_string(index=False))
    print("\nRES-015 (EC-03 increase on last day of month):")
    print(df[df["resident_id"] == "RES-015"].to_string(index=False))
    print("\nRES-025 (EC-01 ADL 3 + Cog 17):")
    print(df[df["resident_id"] == "RES-025"].to_string(index=False))
    print("\nRES-050 (decrease takes effect 1st of next month):")
    print(df[df["resident_id"] == "RES-050"].to_string(index=False))
    print("\nRES-070 (EC-02 fall risk on LEVEL_4):")
    print(df[df["resident_id"] == "RES-070"].to_string(index=False))
    print("=" * 80)
