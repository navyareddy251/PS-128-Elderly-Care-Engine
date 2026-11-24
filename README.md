# Elderly Care Home Resident Care-Level Billing and Staffing Ratio Engine

**Project ID:** PS-128  
**Team ID:** T025  
**Programming Language:** Python 3.10+ (Verified on Python 3.14)  
**Deadline:** 26 November 2026  

---

## 1. Project Overview

The **Elderly Care Home Billing and Staffing Ratio Engine** is an event-driven system designed to manage resident care classifications, monthly billing calculations, nurse and caregiver staffing requirements, 15-day roster assignments, shortfall cost assessments, and regulatory compliance reporting for elderly care homes.

The system processes demographic, clinical assessment, staffing, and facility data, executes an operational stream of clinical and administrative events over a simulation quarter (August – October 2026), and outputs deterministic financial, staffing, and regulatory audit files conforming to strict regulatory evaluation schemas.

---

## 2. Project Directory Structure

```text
T025-PS-128/
│
├── data/                               # Local copies of all 10 sample data files
│   ├── addon_rates.csv                 # Add-on service rates & free allowances
│   ├── assessments.csv                 # ADL & cognitive assessment records (242 rows)
│   ├── commands.txt                    # Simulation event stream (527 commands)
│   ├── fee_schedule.csv                # Monthly base rates by care level & room type
│   ├── README.md                       # Original dataset specification
│   ├── residents.csv                   # Resident demographics & admissions (70 rows)
│   ├── staff.csv                       # Staff profiles & certifications (40 rows)
│   ├── staffing_ratios.csv             # Day/night caregiver & nurse ratios
│   ├── staff_leave.csv                 # Approved staff leave windows (8 rows)
│   └── wings.csv                       # Facility wing definitions (3 wings)
│
├── src/                                # Application source code
│   ├── __init__.py                     # Package initialization
│   ├── data_loader.py                  # Phase 2: Data loading & validation engine
│   ├── care_levels.py                  # Phase 3: Clinical care-level determination
│   ├── billing.py                      # Phase 4: Monthly billing & invoicing engine
│   ├── staffing.py                     # Phase 5: Staffing requirements & rostering
│   ├── compliance.py                   # Phase 6: Regulatory compliance & audit module
│   └── main.py                         # Master CLI orchestrator & pipeline runner
│
├── tests/                              # Automated unit & integration test suite
│   ├── __init__.py
│   ├── test_data_loader.py             # Unit tests for data loading & integrity (10 tests)
│   ├── test_care_levels.py             # Unit tests for care levels & escalation (13 tests)
│   ├── test_billing.py                 # Unit tests for billing & adjustments (10 tests)
│   ├── test_staffing.py                # Unit tests for staffing ratios & roster (11 tests)
│   └── test_compliance.py              # Unit tests for compliance audit & CLI (10 tests)
│
├── outputs/                            # Generated evaluation CSV outputs
│   ├── care_levels.csv                 # Phase 3 output (87 records)
│   ├── bills.csv                       # Phase 4 output (341 records)
│   ├── staffing_requirements.csv       # Phase 5 output (90 records)
│   ├── rosters.csv                     # Phase 5 output (355 records)
│   └── compliance.csv                  # Phase 6 output (73 records)
│
├── docs/                               # Architectural designs & specifications
├── class_diagram.md                    # Complete class diagram & relationships (Mermaid)
├── state_diagram.md                    # Resident lifecycle & acuity state machines (Mermaid)
├── design_document.md                  # Comprehensive system design document
├── decision_log.md                     # Verified business rules & ambiguity decisions
└── requirements.txt                    # Python dependency requirements
```

---

## 3. Environment Setup

The application requires Python 3.10 or higher. Install dependencies using:

```bash
pip install -r requirements.txt
```

---

## 4. Core Modules & Functionality

The application consists of 6 modular components located in `src/`:

1. **`src/data_loader.py`**:
   - Ingests all 10 CSV datasets and `commands.txt`.
   - Validates primary/foreign keys, date formats, and numerical bounds (ADL 0–6, Cognitive 0–30).
   - Records non-fatal warnings for data-entry clerical errors (e.g. RES-050/RES-070 future admission dates).

2. **`src/care_levels.py`**:
   - Evaluates ADL (0–6) and cognitive (0–30) scores into dependency tiers (`LEVEL_1`–`LEVEL_4`).
   - Resolves scoring conflicts in favor of higher resident safety (EC-01: RES-025).
   - Applies fall-risk elevations (+1 level, capped at `LEVEL_4`, EC-02: RES-070).
   - Applies immediate increases on assessment dates (EC-03: RES-015) and defers decreases to the 1st of the following month (RES-050).
   - Triggers acute escalation (+1 level with `basis = FALL_ESCALATION`) when a resident has 2 falls within $\le 30$ days (EC-07: RES-014).
   - Tracks 90-day (LEVEL_1/2) and 30-day (LEVEL_3/4) reassessment cadences.

3. **`src/billing.py`**:
   - Generates monthly itemized invoices in arrears on the 1st of the next month (due on the 10th).
   - Applies calendar-day pro-rating for mid-month admissions, discharges, and rate changes.
   - Computes continuous hospital retention discounts across month boundaries (Days 1–30 @ 50%, Days 31–60 @ 25%, >60 Days @ 100% under `BED_RETAIN FULL`).
   - Suppresses add-on charges during hospital stays (EC-04: RES-039).
   - Applies doctor visit allowances (2 free visits/month, excess @ Rs 1,500) and consumable handling caps (10% capped at Rs 2,000/month, RES-030).
   - Handles short-notice discharge penalties (50% fee charge for notice $< 30$ days, EC-08: RES-004) and death notice waivers (RES-023).
   - Assesses 1.5% late payment interest on unpaid bills (RES-003).

4. **`src/staffing.py`**:
   - Computes caregiver staffing demand from resident acuity, halving night demand for LEVEL_1 and LEVEL_2.
   - Enforces nurse minimums (1 per wing per shift, 1:20 day, 1:40 night).
   - Applies 14-day 1:15 nurse ratio tightening after a reported medication error (EC-05: WING-M).
   - Enforces memory wing dementia training constraints (`dementia_trained = true` for WING-M).
   - Enforces statutory 48-hour maximum work weeks (Monday to Sunday) and 1-shift-per-day limits.
   - Allocates agency staff with shortfall costs (Rs 2,500/shift) when available hours are exhausted (EC-06).

5. **`src/compliance.py`**:
   - Audits operational logs and generates regulatory findings in `compliance.csv`:
     - `OVERDUE_REASSESSMENT`: Periodic assessments conducted after cadence due dates (RES-033 in Aug; RES-007, RES-015, RES-027 in Oct).
     - `RATIO_BREACH`: Shifts with staffing shortfalls ($\text{shortfall} > 0$).
     - `LATE_PAYMENT`: Bills paid after the 10th of the issue month (RES-003 in Sep; RES-035, RES-038, RES-060 in Oct).
   - Formats monthly compliance audit reports for `PRINT_COMPLIANCE|YYYY-MM`.

6. **`src/main.py`**:
   - Master CLI orchestrator streaming all 527 simulation commands in chronological order.
   - Exports all 5 mandatory evaluation CSV files to `outputs/`.

---

## 5. Execution Instructions

### A. Run Complete Simulation Pipeline (Main Orchestrator)

Execute the end-to-end pipeline to process all commands and generate all 5 evaluation CSV files:

```bash
python src/main.py
```

#### Command-Line Options:
```bash
python src/main.py --help
python src/main.py --verbose     # Display formatted bills, rosters, compliance & care plans
python src/main.py --quiet       # Suppress terminal outputs during execution
python src/main.py --data-dir <path> --output-dir <path>
```

### B. Run Individual Modules Standalone

Each module can also be executed independently for focused debugging and reporting:

```bash
# Run data loader & print validation report
python src/data_loader.py

# Run care level engine & view care-level changes
python src/care_levels.py

# Run billing engine & generate invoices
python src/billing.py

# Run staffing engine & build 15-day roster
python src/staffing.py

# Run compliance engine & inspect audit findings
python src/compliance.py
```

---

## 6. Evaluation CSV Outputs

When executed, the system writes 5 standardized CSV files into `outputs/`:

| Output File | Records | Exact Schema (in order) |
|---|---|---|
| **`outputs/care_levels.csv`** | **87** | `resident_id,effective_date,care_level,basis,fall_risk_until` |
| **`outputs/bills.csv`** | **341** | `bill_id,resident_id,month,line_type,description,days,rate,amount` |
| **`outputs/staffing_requirements.csv`** | **90** | `date,shift,wing_id,caregivers_required,nurses_required,caregivers_assigned,nurses_assigned,shortfall,agency_cost` |
| **`outputs/rosters.csv`** | **355** | `date,shift,wing_id,staff_id,role,hours,week_hours_after` |
| **`outputs/compliance.csv`** | **73** | `month,finding_type,ref_id,detail` |

---

## 7. Running Unit Tests

Execute the automated test suite comprising **54 tests** across 5 test modules using Python's built-in `unittest` runner:

```bash
python -m unittest discover -s tests -v
```

### Test Suite Summary:
- `tests/test_data_loader.py` (10 tests): Validates file loading, schemas, constraints, PK/FK referentials, and admission warnings.
- `tests/test_care_levels.py` (13 tests): Validates scoring bands, conflict resolution (EC-01), fall risk (EC-02), immediate increase (EC-03), deferred decrease (RES-050), and fall escalation (EC-07).
- `tests/test_billing.py` (10 tests): Validates pricing, admission pro-rating, hospital tiers (EC-04, RES-029), add-on limits (RES-030), short-notice charges (EC-08), death waivers (RES-023), and late interest (RES-003).
- `tests/test_staffing.py` (11 tests): Validates caregiver ratios, night halving, nurse minimums, medication error tightening (EC-05), dementia training, 48h weekly limits (EC-06), 1 shift/day, and shortfall costs.
- `tests/test_compliance.py` (10 tests): Validates overdue reassessment findings (RES-033), ratio breaches, late payments (RES-003), schema sorting, programmatic pipeline execution, and CLI end-to-end execution.

**Test Pass Rate:** **100% (54/54 tests passing)**.
