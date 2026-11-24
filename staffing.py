"""
PS-128 Elderly Care Home Billing and Staffing Ratio Engine
Module: staffing.py
Team: T025

This module implements the complete staffing calculation, scheduling, and compliance engine:
1. Staff availability management and staff leave tracking.
2. Care-level based staffing ratio calculations for caregivers and nurses:
   - Day & Night ratios calculated separately per wing.
   - Night shift ratios reflect half demand for LEVEL_1 and LEVEL_2.
   - Nurses: minimum 1 per wing per shift.
   - Medication error tightening: nurse ratio becomes 1:15 for 14 days (EC-05).
3. Shift scheduling and allocation constraints:
   - Shifts are 12 hours (Day: 07:00-19:00, Night: 19:00-07:00).
   - Contract hours: 48 hours per week (Monday to Sunday).
   - Staff at 48 hours cannot take another shift in that week (EC-06).
   - At most 1 shift per calendar day per staff member.
   - Memory wing (WING-M): caregivers must be dementia_trained (Rule BR-ST-05).
   - Tie-break: lowest staff_id first (Rule BR-ST-10), with home-wing preference.
4. Staffing shortfall detection & agency cost calculation:
   - agency_cost = shortfall * Rs 2,500 per shift.
5. Exact output generation for staffing_requirements.csv and rosters.csv.
"""

import sys
import math
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Union
import pandas as pd

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.care_levels import CareLevelManager


@dataclass
class StaffProfile:
    """Represents a staff member."""
    staff_id: str
    staff_name: str
    gender: str
    role: str  # 'CAREGIVER' or 'NURSE'
    dementia_trained: bool
    contract_hours_week: int
    home_wing: str


@dataclass
class ShiftRequirement:
    """Staffing requirements and assignment result for one wing in one shift."""
    date: str
    shift: str  # 'DAY' or 'NIGHT'
    wing_id: str
    caregivers_required: int
    nurses_required: int
    caregivers_assigned: int = 0
    nurses_assigned: int = 0
    shortfall: int = 0
    agency_cost: float = 0.0
    assigned_staff_ids: List[str] = field(default_factory=list)

    def finalize(self):
        cg_shortfall = max(0, self.caregivers_required - self.caregivers_assigned)
        nurse_shortfall = max(0, self.nurses_required - self.nurses_assigned)
        self.shortfall = cg_shortfall + nurse_shortfall
        self.agency_cost = round(self.shortfall * 2500.0, 2)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date,
            "shift": self.shift,
            "wing_id": self.wing_id,
            "caregivers_required": self.caregivers_required,
            "nurses_required": self.nurses_required,
            "caregivers_assigned": self.caregivers_assigned,
            "nurses_assigned": self.nurses_assigned,
            "shortfall": self.shortfall,
            "agency_cost": f"{self.agency_cost:.2f}"
        }


@dataclass
class RosterAssignment:
    """A single staff assignment row for rosters.csv."""
    date: str
    shift: str
    wing_id: str
    staff_id: str
    role: str
    hours: int = 12
    week_hours_after: int = 12

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date,
            "shift": self.shift,
            "wing_id": self.wing_id,
            "staff_id": self.staff_id,
            "role": self.role,
            "hours": self.hours,
            "week_hours_after": self.week_hours_after
        }


class StaffingEngine:
    """
    Stateful staffing and roster engine. Calculates daily shift requirements,
    allocates staff respecting leave, hours limits, and qualifications, and detects shortfalls.
    """

    def __init__(self, data_loader, care_level_manager: CareLevelManager):
        self.loader = data_loader
        self.cl_manager = care_level_manager

        # Staff records
        self.staff: Dict[str, StaffProfile] = {}
        self.caregivers: List[StaffProfile] = []
        self.nurses: List[StaffProfile] = []
        self._load_staff()

        # Wings: wing_id -> memory_wing (bool)
        self.wings: Dict[str, bool] = {}
        self._load_wings()

        # Staff leave: staff_id -> list of (leave_from, leave_to)
        self.leave_records: Dict[str, List[Tuple[str, str]]] = {}
        self._load_leave()

        # Medication error tightening windows: wing_id -> list of (start_date, end_date)
        self.med_error_windows: Dict[str, List[Tuple[str, str]]] = {}
        self._load_med_errors()

        # State tracking over simulation
        # staff_id -> hours worked in current week (Monday-Sunday)
        self.weekly_hours: Dict[str, int] = {sid: 0 for sid in self.staff}
        self.current_week_start: Optional[date] = None

        # Storage for results
        # (date, shift, wing_id) -> ShiftRequirement
        self.shift_requirements: Dict[Tuple[str, str, str], ShiftRequirement] = {}
        # List of all RosterAssignment
        self.roster_assignments: List[RosterAssignment] = []

    def _load_staff(self):
        for _, row in self.loader.staff.iterrows():
            sid = row["staff_id"].strip()
            profile = StaffProfile(
                staff_id=sid,
                staff_name=row["staff_name"].strip(),
                gender=row["gender"].strip(),
                role=row["role"].strip(),
                dementia_trained=str(row["dementia_trained"]).lower() == "true",
                contract_hours_week=int(row["contract_hours_week"]),
                home_wing=row["home_wing"].strip()
            )
            self.staff[sid] = profile
            if profile.role == "CAREGIVER":
                self.caregivers.append(profile)
            else:
                self.nurses.append(profile)

        # Sort staff lists by staff_id ascending for tie-break (STF-01, STF-02, ...)
        self.caregivers.sort(key=lambda s: s.staff_id)
        self.nurses.sort(key=lambda s: s.staff_id)

    def _load_wings(self):
        for _, row in self.loader.wings.iterrows():
            wid = row["wing_id"].strip()
            is_mem = str(row["memory_wing"]).lower() == "true"
            self.wings[wid] = is_mem

    def _load_leave(self):
        for _, row in self.loader.staff_leave.iterrows():
            sid = row["staff_id"].strip()
            l_from = row["leave_from"].strip()
            l_to = row["leave_to"].strip()
            if sid not in self.leave_records:
                self.leave_records[sid] = []
            self.leave_records[sid].append((l_from, l_to))

    def _load_med_errors(self):
        for verb, args, line_no, raw in self.loader.commands:
            if verb == "MED_ERROR":
                # args: wing_id, timestamp, description
                wid = args[0]
                d_str = args[1].split(" ")[0]
                # 14 days tightening inclusive
                d_start = datetime.strptime(d_str, "%Y-%m-%d").date()
                d_end = d_start + timedelta(days=13)
                if wid not in self.med_error_windows:
                    self.med_error_windows[wid] = []
                self.med_error_windows[wid].append((d_str, d_end.strftime("%Y-%m-%d")))

    def is_on_leave(self, staff_id: str, date_str: str) -> bool:
        """Returns True if the staff member is on leave on date_str."""
        for l_from, l_to in self.leave_records.get(staff_id, []):
            if l_from <= date_str <= l_to:
                return True
        return False

    def is_nurse_ratio_tightened(self, wing_id: str, date_str: str) -> bool:
        """Returns True if medication error 1:15 tightening is active on date_str."""
        for start_d, end_d in self.med_error_windows.get(wing_id, []):
            if start_d <= date_str <= end_d:
                return True
        return False

    def calculate_shift_requirements(self, wing_id: str, date_str: str, shift: str) -> Tuple[int, int]:
        """
        Calculates (caregivers_required, nurses_required) for a given wing, date, and shift.
        - Caregiver ratios:
          LEVEL_1: 8 (Day) / 16 (Night)
          LEVEL_2: 5 (Day) / 10 (Night)
          LEVEL_3: 3 (Day) / 3 (Night)
          LEVEL_4: 2 (Day) / 2 (Night)
        - Nurse ratios:
          20 (Day) / 40 (Night), or 15 if tightened after MED_ERROR. Minimum 1 per wing per shift.
        """
        # Get active residents in wing on date_str
        active_residents = [
            r["resident_id"] for _, r in self.loader.residents.iterrows()
            if r["wing_id"] == wing_id
        ]

        counts_by_level: Dict[str, int] = {}
        for rid in active_residents:
            cl_rec = self.cl_manager.get_effective_care_level(rid, date_str)
            lvl = cl_rec.care_level if cl_rec else "LEVEL_1"
            counts_by_level[lvl] = counts_by_level.get(lvl, 0) + 1

        # Caregivers required per acuity category
        cg_required = 0
        for lvl, count in counts_by_level.items():
            if lvl == "LEVEL_1":
                ratio = 8 if shift == "DAY" else 16
            elif lvl == "LEVEL_2":
                ratio = 5 if shift == "DAY" else 10
            elif lvl == "LEVEL_3":
                ratio = 3
            else:  # LEVEL_4
                ratio = 2
            cg_required += math.ceil(count / ratio)

        # Nurses required
        total_residents = len(active_residents)
        if self.is_nurse_ratio_tightened(wing_id, date_str):
            nurse_ratio = 15
        else:
            nurse_ratio = 20 if shift == "DAY" else 40

        nurse_required = max(1, math.ceil(total_residents / nurse_ratio))
        return cg_required, nurse_required

    def build_roster(self, from_date: str, to_date: str):
        """
        Builds the 15-day roster from from_date to to_date (2026-10-05 to 2026-10-19).
        Manages weekly 48-hour resets on Mondays and enforces all staffing rules.
        """
        d_curr = datetime.strptime(from_date, "%Y-%m-%d").date()
        d_end = datetime.strptime(to_date, "%Y-%m-%d").date()

        while d_curr <= d_end:
            d_str = d_curr.strftime("%Y-%m-%d")

            # Reset weekly hours on Monday (weekday == 0)
            if d_curr.weekday() == 0:
                self.weekly_hours = {sid: 0 for sid in self.staff}
                self.current_week_start = d_curr

            # Track who has worked on this calendar day (max 1 shift per day)
            worked_today: Set[str] = set()

            for shift in ["DAY", "NIGHT"]:
                self._schedule_shift(d_str, shift, worked_today)

            d_curr += timedelta(days=1)

    def _schedule_shift(self, date_str: str, shift: str, worked_today: Set[str]):
        """
        Schedules a single shift (DAY or NIGHT) across all wings.
        Prioritizes WING-M for dementia trained staff, then home wings, then tie-breaks.
        """
        # 1. Compute requirements for each wing
        wing_reqs: Dict[str, ShiftRequirement] = {}
        for wid in ["WING-A", "WING-B", "WING-M"]:
            cg_req, n_req = self.calculate_shift_requirements(wid, date_str, shift)
            req = ShiftRequirement(
                date=date_str,
                shift=shift,
                wing_id=wid,
                caregivers_required=cg_req,
                nurses_required=n_req
            )
            wing_reqs[wid] = req

        # 2. Caregiver Allocation:
        # Schedule WING-M first (strictly requires dementia_trained)
        self._allocate_caregivers_for_wing(wing_reqs["WING-M"], date_str, shift, worked_today, memory_wing_only=True)
        # Then schedule WING-B and WING-A
        self._allocate_caregivers_for_wing(wing_reqs["WING-B"], date_str, shift, worked_today, memory_wing_only=False)
        self._allocate_caregivers_for_wing(wing_reqs["WING-A"], date_str, shift, worked_today, memory_wing_only=False)

        # 3. Nurse Allocation:
        for wid in ["WING-M", "WING-B", "WING-A"]:
            self._allocate_nurses_for_wing(wing_reqs[wid], date_str, shift, worked_today)

        # 4. Finalize and store requirements
        for wid in ["WING-A", "WING-B", "WING-M"]:
            req = wing_reqs[wid]
            req.finalize()
            self.shift_requirements[(date_str, shift, wid)] = req

    def _allocate_caregivers_for_wing(self, req: ShiftRequirement, date_str: str, shift: str,
                                      worked_today: Set[str], memory_wing_only: bool):
        """Allocates caregivers to a wing respecting hours, leave, qualifications, and tie-breaks."""
        needed = req.caregivers_required - req.caregivers_assigned
        if needed <= 0:
            return

        # Eligible candidates filter
        eligible: List[StaffProfile] = []
        for s in self.caregivers:
            sid = s.staff_id
            if sid in worked_today:
                continue
            if self.is_on_leave(sid, date_str):
                continue
            if self.weekly_hours[sid] + 12 > 48:
                continue
            if memory_wing_only and not s.dementia_trained:
                continue
            eligible.append(s)

        # Sorting preference:
        # For memory wing (WING-M): home_wing == 'WING-M' first, then lowest staff_id
        # For non-memory wings: home_wing first, non-dementia-trained first (to save trained staff for WING-M), then staff_id
        def caregiver_sort_key(s: StaffProfile):
            is_home = (s.home_wing == req.wing_id)
            if memory_wing_only:
                return (0 if is_home else 1, s.staff_id)
            else:
                # Prefer home wing, then prefer non-dementia-trained to protect WING-M pool
                trained_penalty = 1 if s.dementia_trained else 0
                return (0 if is_home else 1, trained_penalty, s.staff_id)

        eligible.sort(key=caregiver_sort_key)

        # Assign up to needed
        assigned_now = eligible[:needed]
        for s in assigned_now:
            sid = s.staff_id
            self.weekly_hours[sid] += 12
            worked_today.add(sid)
            req.caregivers_assigned += 1
            req.assigned_staff_ids.append(sid)

            self.roster_assignments.append(RosterAssignment(
                date=date_str,
                shift=shift,
                wing_id=req.wing_id,
                staff_id=sid,
                role="CAREGIVER",
                hours=12,
                week_hours_after=self.weekly_hours[sid]
            ))

    def _allocate_nurses_for_wing(self, req: ShiftRequirement, date_str: str, shift: str, worked_today: Set[str]):
        """Allocates nurses to a wing respecting hours, leave, and home-wing preference."""
        needed = req.nurses_required - req.nurses_assigned
        if needed <= 0:
            return

        eligible: List[StaffProfile] = []
        for s in self.nurses:
            sid = s.staff_id
            if sid in worked_today:
                continue
            if self.is_on_leave(sid, date_str):
                continue
            if self.weekly_hours[sid] + 12 > 48:
                continue
            eligible.append(s)

        # Preference: home_wing first, then lowest staff_id
        eligible.sort(key=lambda s: (0 if s.home_wing == req.wing_id else 1, s.staff_id))

        assigned_now = eligible[:needed]
        for s in assigned_now:
            sid = s.staff_id
            self.weekly_hours[sid] += 12
            worked_today.add(sid)
            req.nurses_assigned += 1
            req.assigned_staff_ids.append(sid)

            self.roster_assignments.append(RosterAssignment(
                date=date_str,
                shift=shift,
                wing_id=req.wing_id,
                staff_id=sid,
                role="NURSE",
                hours=12,
                week_hours_after=self.weekly_hours[sid]
            ))

    def print_roster(self, wing_id: str, date_str: str, shift: str) -> str:
        """Formats the shift roster statement for PRINT_ROSTER commands."""
        key = (date_str, shift, wing_id)
        req = self.shift_requirements.get(key)
        if not req:
            return f"No roster built for {wing_id} on {date_str} {shift}."

        shift_hours = "07:00-19:00" if shift == "DAY" else "19:00-07:00"
        wing_name = "Tulsi Wing" if wing_id == "WING-A" else ("Champa Wing" if wing_id == "WING-B" else "Smriti Wing (Memory)")

        lines = []
        lines.append("=" * 80)
        lines.append(f"                         SHIFT ROSTER STATEMENT")
        lines.append("=" * 80)
        lines.append(f"Date:       {req.date:<20} Shift:      {req.shift} ({shift_hours})")
        lines.append(f"Wing:       {wing_name} ({req.wing_id})")
        lines.append("-" * 80)
        lines.append(f"CAREGIVERS: Required = {req.caregivers_required:<4} Assigned = {req.caregivers_assigned}")
        cg_ids = [sid for sid in req.assigned_staff_ids if self.staff[sid].role == "CAREGIVER"]
        if cg_ids:
            cg_str = ", ".join(f"{sid} ({self.staff[sid].staff_name})" for sid in cg_ids)
            lines.append(f"  Assigned: {cg_str}")
        else:
            lines.append("  Assigned: None")

        lines.append(f"\nNURSES:     Required = {req.nurses_required:<4} Assigned = {req.nurses_assigned}")
        n_ids = [sid for sid in req.assigned_staff_ids if self.staff[sid].role == "NURSE"]
        if n_ids:
            n_str = ", ".join(f"{sid} ({self.staff[sid].staff_name})" for sid in n_ids)
            lines.append(f"  Assigned: {n_str}")
        else:
            lines.append("  Assigned: None")

        lines.append("-" * 80)
        if req.shortfall > 0:
            lines.append(f"STATUS:     ⚠️ SHORTFALL DETECTED: {req.shortfall} staff missing | Agency Cost: Rs {req.agency_cost:,.2f}")
        else:
            lines.append("STATUS:     ✅ FULLY STAFFED | Agency Cost: Rs 0.00")
        lines.append("=" * 80)
        return "\n".join(lines)

    def to_staffing_requirements_dataframe(self) -> pd.DataFrame:
        """Generates staffing_requirements.csv DataFrame strictly matching specification."""
        records = []
        # Sorted by date, shift, wing_id
        for key in sorted(self.shift_requirements.keys()):
            req = self.shift_requirements[key]
            records.append(req.to_dict())

        df = pd.DataFrame(records, columns=[
            "date", "shift", "wing_id", "caregivers_required", "nurses_required",
            "caregivers_assigned", "nurses_assigned", "shortfall", "agency_cost"
        ])
        return df

    def to_rosters_dataframe(self) -> pd.DataFrame:
        """Generates rosters.csv DataFrame strictly matching specification."""
        records = [r.to_dict() for r in self.roster_assignments]
        df = pd.DataFrame(records, columns=[
            "date", "shift", "wing_id", "staff_id", "role", "hours", "week_hours_after"
        ])
        return df


def execute_staffing_engine(data_loader, cl_manager: CareLevelManager) -> Tuple[StaffingEngine, pd.DataFrame, pd.DataFrame]:
    """Builds the complete 15-day roster and returns the engine and both DataFrames."""
    engine = StaffingEngine(data_loader, cl_manager)
    engine.build_roster("2026-10-05", "2026-10-19")
    req_df = engine.to_staffing_requirements_dataframe()
    rost_df = engine.to_rosters_dataframe()
    return engine, req_df, rost_df


if __name__ == "__main__":
    from src.data_loader import load_dataset
    from src.care_levels import build_care_levels

    project_root = Path(__file__).resolve().parent.parent
    loader, _ = load_dataset(project_root / "data")
    manager, _ = build_care_levels(loader)
    engine, req_df, rost_df = execute_staffing_engine(loader, manager)

    print("=" * 80)
    print("                    STAFFING ENGINE SUMMARY")
    print("=" * 80)
    print(f"Total Shift Slots Evaluated:     {len(req_df)}")
    print(f"Total Roster Assignments Made:   {len(rost_df)}")
    total_shortfall = req_df["shortfall"].sum()
    total_agency_cost = req_df["agency_cost"].astype(float).sum()
    print(f"Total Shortfall Count:           {total_shortfall}")
    print(f"Total Agency Cost:               Rs {total_agency_cost:,.2f}")
    print("-" * 80)

    # Print sample shift statement
    print(engine.print_roster("WING-A", "2026-10-05", "DAY"))
    print("\n" + engine.print_roster("WING-M", "2026-10-12", "DAY"))
    print("\n" + engine.print_roster("WING-M", "2026-10-11", "NIGHT"))
    print("=" * 80)
