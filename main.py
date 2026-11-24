"""
main.py - Main CLI Orchestrator and Pipeline Engine
PS-128 / Team T025: Elderly Care Home Resident Care-level Billing and Staffing Ratio Engine

Orchestrates the entire care home management pipeline:
1. Loads and validates all input data packs.
2. Initializes Care Level, Billing, Staffing, and Compliance modules.
3. Streams and executes commands.txt events chronologically.
4. Handles human-readable print requests (PRINT_ROSTER, PRINT_BILL, PRINT_COMPLIANCE, PRINT_CARE_PLAN).
5. Generates and exports all 5 evaluation CSV outputs:
   - outputs/care_levels.csv
   - outputs/bills.csv
   - outputs/staffing_requirements.csv
   - outputs/rosters.csv
   - outputs/compliance.csv
"""

import sys
import argparse
from pathlib import Path
from typing import Dict, Any, Optional
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_loader import DataLoader, load_dataset
from src.care_levels import CareLevelManager, build_care_levels
from src.billing import BillingEngine
from src.staffing import StaffingEngine
from src.compliance import ComplianceEngine


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Elderly Care Home Billing and Staffing Ratio Engine (PS-128 / Team T025)"
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default=str(PROJECT_ROOT / "data"),
        help="Path to folder containing sample CSV files and commands.txt"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(PROJECT_ROOT / "outputs"),
        help="Path to directory where output CSV files will be saved"
    )
    parser.add_argument(
        "--commands-file",
        type=str,
        default=None,
        help="Path to commands.txt file (defaults to <data-dir>/commands.txt)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output of commands and formatted prints"
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress print outputs during command stream processing"
    )
    return parser.parse_args()


def execute_pipeline(
    data_dir: Path,
    output_dir: Path,
    commands_file: Optional[Path] = None,
    verbose: bool = False,
    quiet: bool = False
) -> Dict[str, Any]:
    """
    Executes the complete end-to-end pipeline and exports all outputs.
    Returns a dictionary of all engines and DataFrames.
    """
    data_dir = Path(data_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if commands_file is None:
        commands_file = data_dir / "commands.txt"
    else:
        commands_file = Path(commands_file)

    if not quiet:
        print("=" * 80)
        print("    ELDERLY CARE HOME BILLING AND STAFFING RATIO ENGINE (PS-128 / T025)")
        print("=" * 80)
        print(f"Data Directory:    {data_dir}")
        print(f"Output Directory:  {output_dir}")
        print(f"Commands Stream:   {commands_file}")
        print("-" * 80)

    # ---------------------------------------------------------
    # STEP 1: Load and Validate All Datasets
    # ---------------------------------------------------------
    if not quiet:
        print("[1/5] Ingesting and validating input datasets...")
    loader, val_report = load_dataset(data_dir)
    if not quiet:
        print(f"      Loaded {len(loader.residents)} residents, {len(loader.assessments)} assessments, "
              f"{len(loader.staff)} staff, {len(loader.wings)} wings, {len(loader.commands)} commands.")

    # ---------------------------------------------------------
    # STEP 2: Initialize Care Level Module
    # ---------------------------------------------------------
    if not quiet:
        print("[2/5] Initializing Care Level Management Module...")
    care_manager, cl_df = build_care_levels(loader)
    if not quiet:
        print(f"      Evaluated {len(cl_df)} care-level change records across {len(loader.residents)} residents.")

    # ---------------------------------------------------------
    # STEP 3: Initialize Billing & Staffing Engines
    # ---------------------------------------------------------
    if not quiet:
        print("[3/5] Initializing Billing and Staffing Engines...")
    billing = BillingEngine(loader, care_manager)
    staffing = StaffingEngine(loader, care_manager)
    compliance = ComplianceEngine(care_manager, billing, staffing)

    # Prepare resident lookup info for care plan prints
    resident_info_lookup = {}
    for _, r in loader.residents.iterrows():
        resident_info_lookup[r["resident_id"]] = {
            "resident_name": r["resident_name"],
            "wing_id": r["wing_id"],
            "room_type": r["room_type"],
            "admission_date": r["admission_date"],
            "payment_mode": r["payment_mode"]
        }

    # ---------------------------------------------------------
    # STEP 4: Stream and Execute Simulation Commands
    # ---------------------------------------------------------
    if not quiet:
        print("[4/5] Executing simulation commands in chronological stream...")

    printed_roster_count = 0
    printed_bill_count = 0
    printed_compliance_count = 0
    printed_care_plan_count = 0

    with open(commands_file, encoding="utf-8") as f:
        for line_no, raw_line in enumerate(f, 1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            parts = line.split("|")
            verb = parts[0]
            args = parts[1:]

            # Dispatch based on verb
            if verb in [
                "HOSPITAL_ADMIT", "HOSPITAL_RETURN", "BED_RETAIN", "ADDON",
                "CONSUMABLE", "DISCHARGE_NOTICE", "VACATE", "DEATH",
                "PAYMENT", "GENERATE_BILLS"
            ]:
                billing.process_command(verb, args, line_no)

            elif verb == "FALL":
                # Already captured and interleaved during CareLevelManager initialization
                pass

            elif verb == "MED_ERROR":
                # Already captured by StaffingEngine windows
                pass

            elif verb == "BUILD_ROSTER":
                # BUILD_ROSTER|from_date|to_date
                from_date, to_date = args[0], args[1]
                staffing.build_roster(from_date, to_date)

            elif verb == "PRINT_ROSTER":
                # PRINT_ROSTER|wing_id|date|shift
                printed_roster_count += 1
                if verbose and not quiet:
                    wing_id, date_str, shift = args[0], args[1], args[2]
                    print(staffing.print_roster(wing_id, date_str, shift))

            elif verb == "PRINT_BILL":
                # PRINT_BILL|resident_id|YYYY-MM
                printed_bill_count += 1
                if verbose and not quiet:
                    resident_id, month_str = args[0], args[1]
                    print(billing.print_invoice(resident_id, month_str))

            elif verb == "PRINT_COMPLIANCE":
                # PRINT_COMPLIANCE|YYYY-MM
                printed_compliance_count += 1
                month_str = args[0]
                # Recompile findings up to this point
                compliance.compile_all_findings()
                if verbose and not quiet:
                    print(compliance.print_compliance(month_str))

            elif verb == "PRINT_CARE_PLAN":
                # PRINT_CARE_PLAN|resident_id
                printed_care_plan_count += 1
                if verbose and not quiet:
                    resident_id = args[0]
                    res_info = resident_info_lookup.get(resident_id)
                    print(care_manager.print_care_plan(resident_id, res_info))

    if not quiet:
        print(f"      Processed all commands. Formatted prints encountered: "
              f"{printed_roster_count} rosters, {printed_bill_count} bills, "
              f"{printed_compliance_count} compliance, {printed_care_plan_count} care plans.")

    # ---------------------------------------------------------
    # STEP 5: Compile Findings and Export Output CSV Files
    # ---------------------------------------------------------
    if not quiet:
        print("[5/5] Compiling final records and exporting all 5 output CSV files...")

    # 1. care_levels.csv
    cl_df = care_manager.to_dataframe()
    cl_path = output_dir / "care_levels.csv"
    cl_df.to_csv(cl_path, index=False)

    # 2. bills.csv
    bills_df = billing.to_dataframe()
    bills_path = output_dir / "bills.csv"
    bills_df.to_csv(bills_path, index=False)

    # 3. staffing_requirements.csv
    req_df = staffing.to_staffing_requirements_dataframe()
    req_path = output_dir / "staffing_requirements.csv"
    req_df.to_csv(req_path, index=False)

    # 4. rosters.csv
    rost_df = staffing.to_rosters_dataframe()
    rost_path = output_dir / "rosters.csv"
    rost_df.to_csv(rost_path, index=False)

    # 5. compliance.csv
    comp_df = compliance.to_dataframe()
    comp_path = output_dir / "compliance.csv"
    comp_df.to_csv(comp_path, index=False)

    if not quiet:
        print("=" * 80)
        print("                     PIPELINE EXECUTION COMPLETE")
        print("=" * 80)
        print(f"  1. Care Levels:            {cl_path} ({len(cl_df)} rows)")
        print(f"  2. Bills:                  {bills_path} ({len(bills_df)} rows)")
        print(f"  3. Staffing Requirements:  {req_path} ({len(req_df)} rows)")
        print(f"  4. Rosters:                {rost_path} ({len(rost_df)} rows)")
        print(f"  5. Compliance Findings:    {comp_path} ({len(comp_df)} rows)")
        print("=" * 80)

    return {
        "loader": loader,
        "care_manager": care_manager,
        "billing": billing,
        "staffing": staffing,
        "compliance": compliance,
        "care_levels_df": cl_df,
        "bills_df": bills_df,
        "staffing_requirements_df": req_df,
        "rosters_df": rost_df,
        "compliance_df": comp_df,
    }


def main():
    args = parse_arguments()
    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    commands_file = Path(args.commands_file) if args.commands_file else None

    try:
        execute_pipeline(
            data_dir=data_dir,
            output_dir=output_dir,
            commands_file=commands_file,
            verbose=args.verbose,
            quiet=args.quiet
        )
    except Exception as exc:
        print(f"FATAL ERROR during pipeline execution: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
