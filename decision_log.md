# Decision Log — PS-128 (Team T025)

## Elderly Care Home Resident Care-Level Billing and Staffing Ratio Engine

---

## 1. Document Overview

This decision log tracks confirmed business rules, forensic analysis of assignment ambiguities, sample data cross-references, and authoritative interpretations supported by the original project specification (`README.md`, `commands.txt`, and data CSV files). Every decision documented herein is verified against the codebase and sample datasets without ungrounded assumptions.

---

## 2. Verification of Key Ambiguities

### Ambiguity 1: RES-050 Future Admission Date vs. Earlier Assessments

- **Business Rule / Scenario ID:** Extra Trap (Line 160) & EC-02 Analog (Line 144)
- **Original Specification Quote:**
  - `README.md` Line 14: `"assessments.csv | ADL / cognitive assessments: latest before August plus every scheduled and incident reassessment"`
  - `README.md` Line 160: `"- RES-050: reassessment on 2026-09-12 lowers LEVEL_3 -> LEVEL_2 — a decrease takes effect only from 1 October — assessments.csv row 149"`
- **Exact Line Numbers:**
  - `README.md` Lines 13, 14, 160
  - `residents.csv` Row 51 (Line 51): `RES-050,Deepak Chowdhury,M,1934-09-08,WING-B,SHARED,2026-12-24,Priya Chowdhury,7984162294,MANUAL,0,160000.00`
  - `assessments.csv` Rows 24, 77, 132, 150, 192 (ASM-0023, ASM-0076, ASM-0131, ASM-0149, ASM-0191)
  - `commands.txt` Lines 66, 157, 295, 365, 435, 508
- **Sample Data Cross-Check:**
  - `residents.csv` lists `admission_date` as `2026-12-24`.
  - Deposit paid is `160000.00` (which equals exactly 2 months' deposit for LEVEL_3 SHARED @ Rs 80,000/month).
  - `assessments.csv` contains assessments on `2026-07-05`, `2026-08-04`, `2026-09-03`, `2026-09-12`, and `2026-10-03`.
  - `commands.txt` explicitly commands:
    - `PAYMENT|RES-050|2026-09-10|FULL|CHEQUE` (paying August bill)
    - `PAYMENT|RES-050|2026-10-09|FULL|UPI` (paying September bill)
    - `PRINT_BILL|RES-050|2026-08`, `PRINT_BILL|RES-050|2026-09`, `PRINT_BILL|RES-050|2026-10`
    - `PRINT_CARE_PLAN|RES-050`
  - A similar clerical pattern exists for RES-070 (`admission_date: 2026-11-11`), which is explicitly featured in EC-02 (`README.md` line 143-144) as an active resident with assessments in July, August, September, October.
- **Possible Interpretations:**
  - *Interpretation A:* Treat RES-050 as not admitted until 2026-12-24, ignoring assessments and generating zero/empty bills for Aug–Oct.
  - *Interpretation B:* Treat the `2026-12-24` admission year as an obvious data-entry clerical error in `residents.csv` (intended to be `2024-12-24` or prior admission), while recognizing that per `README.md` lines 14 & 160, RES-050 is an active resident present during the entire simulation window whose assessments determine care level and billing.
- **Recommended Decision:** **Interpretation B**. All assessments for RES-050 must be processed on their `assessment_date`. RES-050 is an active resident in WING-B for August, September, and October 2026. This is directly mandated by `README.md` line 160 and corroborated by payment and bill print commands.

---

### Ambiguity 2: Reassessment Cadence (30 Days vs. Another Interval)

- **Business Rule / Scenario ID:** BR-CO-01 / Extra Trap (Line 161)
- **Original Specification Quote:**
  - `README.md` Line 161: `"- RES-033 (LEVEL_3, 30-day cadence): reassessment due 2026-08-06 is done only on 2026-08-22 (16 days late) — a fall on 2026-08-15 cannot raise the bill until the reassessment is completed — commands.txt line 18"`
  - `README.md` Line 200: `"compliance.csv: One row per finding per month (overdue reassessments, ratio breaches, late payments)."`
- **Exact Line Numbers:**
  - `README.md` Lines 161, 200
  - `assessments.csv` ASM-0028 (2026-07-07) and ASM-0112 (2026-08-22)
- **Sample Data Cross-Check:**
  - Quantitative audit of all 242 rows in `assessments.csv`:
    - LEVEL_3 and LEVEL_4 residents: 132 periodic intervals are **exactly 30 days** apart.
    - LEVEL_1 and LEVEL_2 residents: 21 periodic intervals are **exactly 90 days** apart (quarterly).
    - For RES-033: Initial assessment `2026-07-07` (LEVEL_3). Cadence is 30 days. Due date = `2026-07-07` + 30 days = `2026-08-06`. Conducted on `2026-08-22`. Latency = 16 days overdue.
- **Possible Interpretations:**
  - *Interpretation A:* Every resident regardless of care level requires reassessment every 30 days.
  - *Interpretation B:* Reassessment cadence depends on care-level tier:
    - **LEVEL_1 and LEVEL_2:** 90-day cadence (quarterly).
    - **LEVEL_3 and LEVEL_4:** 30-day cadence (monthly), explicitly stated in `README.md` line 161 `"(LEVEL_3, 30-day cadence)"`.
- **Recommended Decision:** **Interpretation B**. High-acuity residents (LEVEL_3 and LEVEL_4) follow a **30-day cadence**, while low-acuity residents (LEVEL_1 and LEVEL_2) follow a **90-day cadence**. An overdue reassessment finding in `compliance.csv` is triggered when `actual_assessment_date - prior_assessment_date > cadence_days` (or when `cadence_days` have elapsed without reassessment).

---

### Ambiguity 3: Second Fall on Exactly the 30th Day (EC-07 Escalation Boundary)

- **Business Rule / Scenario ID:** EC-07 (Planted Scenario 7)
- **Original Specification Quote:**
  - `README.md` Line 153-154: `"- EC-07 Second fall on the 30th day after the first"`
  - `README.md` Line 154: `"  - RES-014: falls on 2026-08-20 and on 2026-09-19 = the 30th day after the first — whether that is '2 falls in 30 days' decides an immediate one-level escalation — commands.txt lines 21, 91"`
  - `README.md` Line 204: `"basis ASSESSMENT, FALL_RISK, FALL_ESCALATION."`
- **Exact Line Numbers:**
  - `README.md` Lines 153–154, 204
  - `commands.txt` Line 21: `FALL|RES-014|2026-08-20 06:10:00|Bathroom`
  - `commands.txt` Line 91: `FALL|RES-014|2026-09-19 22:40:00|Bedside`
  - `assessments.csv` ASM-0106 (2026-08-21) and ASM-0168 (2026-09-21)
- **Sample Data Cross-Check:**
  - Fall 1 date: `2026-08-20`.
  - Fall 2 date: `2026-09-19`.
  - August has 31 days: $31 - 20 = 11$ days in August. Plus 19 days in September = exactly 30 days elapsed ($\Delta = 30$).
  - `README.md` line 204 specifically defines an enum value `FALL_ESCALATION` for the `basis` column in `care_levels.csv`.
- **Possible Interpretations:**
  - *Interpretation A (Strictly Less Than):* "Within 30 days" means $< 30$ days. Day 30 is outside the window; no escalation occurs.
  - *Interpretation B (Inclusive Boundary - Less Than or Equal To):* "Within 30 days" means $\le 30$ calendar days ($\Delta \le 30$). A fall on the 30th day falls inside the 30-day window, triggering immediate one-level escalation with basis `FALL_ESCALATION`.
- **Recommended Decision:** **Interpretation B**. In healthcare and clinical risk management, "within N days" is inclusive of day N ($\Delta \le 30$). The presence of `EC-07` and the specific enum `FALL_ESCALATION` in `README.md` line 204 exists specifically to test that boundary condition: RES-014 escalates immediately on `2026-09-19` with basis `FALL_ESCALATION`.

---

### Ambiguity 4: Hospitalisation Reductions Crossing Billing-Month Boundaries

- **Business Rule / Scenario ID:** EC-04, Extra Trap (Line 159), BR-BL-06, BR-BL-07, BR-BL-08
- **Original Specification Quote:**
  - `README.md` Line 147-148: `"- EC-04 Hospitalisation of exactly 30 days"`
  - `README.md` Line 148: `"  - RES-039: HOSPITAL_ADMIT 2026-08-06, HOSPITAL_RETURN 2026-09-05 = exactly 30 days — all 30 days at 50% of the fee (none at 25%); the PHYSIO add-on recorded on 2026-08-12 falls during hospitalisation and is not billed — commands.txt lines 9, 16, 50"`
  - `README.md` Line 159: `"- RES-029: hospitalised 2026-08-03 to 2026-10-08 (66 days): 30 days at 50%, 30 days at 25%, then the bed would be released — the family's BED_RETAIN FULL keeps it at 100% — commands.txt lines 6, 109, 149"`
  - `README.md` Line 204: `"Binding choices: bills are issued in arrears on the 1st of the next month and fall due on the 10th; pro-rating uses calendar days of the month; a week runs Monday to Sunday; shifts are 12 h. bill_id format BILL-<resident_id>-<YYYY-MM>; line_type FEE, HOSPITAL_RETENTION, ADDON, CONSUMABLE, HANDLING, NOTICE_CHARGE, REFUND, DEPOSIT_ADJUSTMENT, INTEREST;"`
- **Exact Line Numbers:**
  - `README.md` Lines 147–148, 159, 184, 204
  - `commands.txt` Lines 6, 9, 16, 50, 109, 149
- **Sample Data Cross-Check:**
  - **RES-039:** Admitted `2026-08-06`, returned `2026-09-05`.
    - Total hospital duration: 26 days in August (Aug 6–31) + 4 days in September (Sep 1–4) = 30 days. Return day Sep 5 is back in residence.
    - August bill (`2026-08`):
      - In-residence: Aug 1–5 (5 days) @ full daily fee.
      - Hospital retention: Aug 6–31 (26 days) @ 50% daily fee (`line_type: HOSPITAL_RETENTION`).
    - September bill (`2026-09`):
      - Hospital retention: Sep 1–4 (4 days) @ 50% daily fee (`line_type: HOSPITAL_RETENTION`). (These are cumulative hospital days 27, 28, 29, 30 of the stay).
      - In-residence: Sep 5–30 (26 days) @ full daily fee (`line_type: FEE`).
  - **RES-029:** Admitted `2026-08-03`, returned `2026-10-08` (66 days).
    - Cumulative days 1–30 @ 50% fee (Aug 3–31 = 29 days; Sep 1 = 1 day).
    - Cumulative days 31–60 @ 25% fee (Sep 2–30 = 29 days; Oct 1 = 1 day).
    - Cumulative days 61–66 @ 100% fee via `BED_RETAIN FULL` (Oct 2–7 = 6 days). Return Oct 8.
- **Possible Interpretations:**
  - *Interpretation A:* Reset the hospital day counter at each calendar month boundary (so every new calendar month starts back at day 1 with 50% discount).
  - *Interpretation B:* The hospitalisation tier (Days 1–30 @ 50%, Days 31–60 @ 25%, >60 Days @ Bed Release / Bed Retain) is tracked **cumulatively across the continuous hospital episode**, but billed monthly in arrears for the exact days falling within each calendar month pro-rata.
- **Recommended Decision:** **Interpretation B**. Proven by RES-029 where line 159 notes: `"30 days at 50%, 30 days at 25%, then the bed would be released — the family's BED_RETAIN FULL keeps it at 100%"`. The 66-day hospital stay spans August, September, and October, proving continuous cumulative tracking across month boundaries.

---

## 3. Register of Confirmed Technical Rules & Edge-Case Decisions

### Decision 5: Doctor Visit Free Allowance and Consumables Handling Fee Cap (RES-030)
- **Source**: `README.md` Line 162; `addon_rates.csv`
- **Rule**:
  - `DOCTOR_VISIT`: First 2 visits per resident per billing month are FREE (`free_allowance = 2 per month free`). Subsequent visits are billed at Rs 1,500.00 each.
  - `CONSUMABLE_HANDLING`: Assessed at 10% of total consumable purchases in the month, strictly **capped at Rs 2,000.00** per month.
- **Verification Case**: RES-030 in September had 4 doctor visits (2 free, 2 billed @ Rs 1,500 = Rs 3,000) and consumables of Rs 23,400.00 (10% = Rs 2,340.00, capped at Rs 2,000.00).

### Decision 6: Short-Notice Departure Penalty (EC-08: RES-004)
- **Source**: `README.md` Line 155; `commands.txt` lines 36, 113
- **Rule**:
  - A resident must provide at least 30 calendar days' advance notice before vacating (`vacate_date - notice_date >= 30`).
  - If notice is $< 30$ days, a short-notice charge equal to **50% of one month's base fee** is billed (`line_type = NOTICE_CHARGE`).
  - Pro-rata refund of fee applies from the day after vacating.
- **Verification Case**: RES-004 notice on 2026-09-02 to vacate 2026-10-01 (29 days). Billed 50% of monthly fee (Rs 30,000) as notice charge on September bill.

### Decision 7: Death Notice Waiver and Pro-Rata Fee Refund (RES-023)
- **Source**: `README.md` Line 158; `commands.txt` line 97
- **Rule**:
  - Upon a resident's death (`DEATH|resident_id|date`), all notice periods are **fully waived**.
  - Monthly fee is refunded pro-rata from the day after death through the end of the billing month (`line_type = REFUND`).
- **Verification Case**: RES-023 passed away on 2026-09-23. Billed for 23 days; remaining 7 days of September refunded pro-rata.

### Decision 8: Memory Care Wing (`WING-M`) Dementia Training Constraint
- **Source**: `README.md` lines 27, 33; `wings.csv`
- **Rule**:
  - `WING-M` houses exclusively `LEVEL_4` maximum dependency residents.
  - Every caregiver assigned to `WING-M` must have `dementia_trained = true`.
  - Non-dementia trained caregivers can never be allocated to `WING-M`.

### Decision 9: Medication Error 14-Day Nurse Ratio Tightening (EC-05: WING-M)
- **Source**: `README.md` lines 149–150; `staffing_ratios.csv`
- **Rule**:
  - Following a `MED_ERROR` command in a wing, the nurse ratio for that wing tightens from 1:20 to **1:15** for **14 calendar days** (incident date plus 13 days).
- **Verification Case**: WING-M medication error on 2026-10-12 (20 residents). Normal nurse requirement is $20 / 20 = 1$. Under 1:15 tightening, $\lceil 20 / 15 \rceil = 2$ nurses required per day shift through 2026-10-25.

### Decision 10: 48-Hour Weekly Work Limit and Shortfall Costs (EC-06)
- **Source**: `README.md` lines 100, 151–152, 204; `staff.csv`
- **Rule**:
  - A week runs from **Monday 00:00 to Sunday 23:59**.
  - Staff members work 12-hour shifts (`DAY` or `NIGHT`) and cannot exceed 48 contract hours per week (maximum 4 shifts).
  - Maximum 1 shift per staff member per calendar day.
  - When all available eligible staff have reached 48 hours, unfilled shifts become `shortfall` with an agency replacement cost of **Rs 2,500.00** per staff shift.
- **Verification Case**: Sunday 2026-10-11 end-of-week shifts generate shortfalls due to exhausted staff hours (EC-06).

### Decision 11: Late Payment Interest Assessment (RES-003)
- **Source**: `README.md` line 163; `commands.txt` line 83
- **Rule**:
  - Bills are issued on the 1st of the next month and fall due on the 10th.
  - Any payment received after the 10th incurs interest at **1.5% per month** on the unpaid amount, charged on the next month's bill (`line_type = INTEREST`).
  - A 3rd late payment in a 6-month period forces the resident into mandatory advance billing mode.
- **Verification Case**: RES-003 paid August bill (due 2026-09-10) on 2026-09-15. September bill included 1.5% interest charge (Rs 900.00).

### Decision 12: Compliance Finding Categorization and Month Attribution
- **Source**: `README.md` lines 198–202; `commands.txt` lines 456–458
- **Rule**:
  - Finding types are strictly: `OVERDUE_REASSESSMENT`, `RATIO_BREACH`, `LATE_PAYMENT`.
  - Findings are attributed to the calendar month in which the violation/event occurred:
    - Overdue reassessment: attributed to the month the delayed assessment occurred (or became overdue).
    - Ratio breach: attributed to the month of the short-staffed shift (`YYYY-MM`).
    - Late payment: attributed to the month when the late payment was received (`payment_date[:7]`).
  - Output rows in `compliance.csv` are sorted deterministically by `(month, finding_type, ref_id)`.
