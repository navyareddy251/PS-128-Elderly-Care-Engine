# PS-128 – Elderly Care Home Resident Care-level Billing and Staffing Ratio Engine — Sample Data Pack

Prepared by 10 SECONDS for Team T025.

## Files

| File | What it holds | Row count |
|---|---|---|
| `wings.csv` | 3 wings (one memory wing) | 3 data rows |
| `fee_schedule.csv` | Monthly fee by care level and room type | 7 data rows |
| `addon_rates.csv` | Add-on services and consumable handling | 5 data rows |
| `staffing_ratios.csv` | Caregiver and nurse ratios per shift | 5 data rows |
| `residents.csv` | 70 residents (22 / 28 / 20 by wing) with room, admission, deposit and payment mode | 70 data rows |
| `assessments.csv` | ADL / cognitive assessments: latest before August plus every scheduled and incident reassessment | 242 data rows |
| `staff.csv` | 40 staff (30 caregivers, 10 nurses) | 40 data rows |
| `staff_leave.csv` | Staff leave in the roster window | 8 data rows |
| `commands.txt` | ~150 incident / hospitalisation / add-on / consumable / payment events, bill runs, roster build and prints | 527 command lines (excluding comments) |

Row numbers quoted below are 1-based data-row numbers (the header is row 0). Line numbers for `commands.txt` are physical line numbers including comment lines.

## Column reference

Conventions: dates `YYYY-MM-DD`; timestamps `YYYY-MM-DD HH:MM:SS` (24h, IST, no timezone suffix); money in Rs as plain decimals with 2 places (no commas, no symbol); percentages as plain numbers (12.5 means 12.5%); booleans `true`/`false`; IDs uppercase with a fixed prefix. An empty cell means "not applicable" and is only allowed where the notes say so.

### `wings.csv`

| Column | Type | Units / format | Allowed values | Notes |
|---|---|---|---|---|
| wing_id | string | WING-x | — | — |
| wing_name | string | — | — | — |
| memory_wing | bool | — | — | LEVEL_4 only; caregivers must be DEMENTIA_TRAINED |

### `fee_schedule.csv`

| Column | Type | Units / format | Allowed values | Notes |
|---|---|---|---|---|
| care_level | enum | — | LEVEL_1..LEVEL_4 | — |
| room_type | enum | — | SHARED, PRIVATE | LEVEL_4 private only |
| monthly_fee | decimal | Rs | — | — |

### `addon_rates.csv`

| Column | Type | Units / format | Allowed values | Notes |
|---|---|---|---|---|
| addon_code | string | — | — | — |
| description | string | — | — | — |
| rate | decimal | Rs (pct for handling) | — | — |
| unit | string | — | — | — |
| free_allowance | string | — | — | may be empty |

### `staffing_ratios.csv`

| Column | Type | Units / format | Allowed values | Notes |
|---|---|---|---|---|
| role | enum | — | CAREGIVER, NURSE | — |
| care_level | string | — | — | empty for NURSE (per resident) |
| day_ratio | int | residents per staff | — | 07:00-19:00 |
| night_ratio | int | residents per staff | — | 19:00-07:00 |
| notes | string | — | — | — |

### `residents.csv`

| Column | Type | Units / format | Allowed values | Notes |
|---|---|---|---|---|
| resident_id | string | RES-nnn | — | — |
| resident_name | string | — | — | — |
| gender | enum | — | M, F | — |
| dob | date | — | — | — |
| wing_id | string | — | wings.csv | — |
| room_type | enum | — | SHARED, PRIVATE | — |
| admission_date | date | — | — | — |
| family_contact_name | string | — | — | — |
| family_mobile | string | 10 digits | — | — |
| payment_mode | enum | — | AUTO_DEBIT, MANUAL | AUTO_DEBIT pays in full on the due date (no event) |
| late_payments_last_6m | int | — | — | before August |
| deposit_paid | decimal | Rs | — | 2 months' fee at admission level |

### `assessments.csv`

| Column | Type | Units / format | Allowed values | Notes |
|---|---|---|---|---|
| assessment_id | string | ASM-nnnn | — | — |
| resident_id | string | — | residents.csv | — |
| assessment_date | date | — | — | effective date |
| reason | enum | — | ADMISSION, PERIODIC, FALL, INCIDENT | — |
| adl_score | int | — | 0-6 | number of dependent activities |
| cognitive_score | int | — | 0-30 | — |
| fall_risk | bool | — | — | raises level by one (max 4) |
| mobility | enum | — | INDEPENDENT, WALKER, WHEELCHAIR, BEDBOUND | — |
| assessed_by | string | — | — | — |

### `staff.csv`

| Column | Type | Units / format | Allowed values | Notes |
|---|---|---|---|---|
| staff_id | string | STF-nn | — | tie-break: lowest id |
| staff_name | string | — | — | — |
| gender | enum | — | M, F | — |
| role | enum | — | CAREGIVER, NURSE | — |
| dementia_trained | bool | — | — | — |
| contract_hours_week | int | h | 48 | — |
| home_wing | string | — | wings.csv | informational |

### `staff_leave.csv`

| Column | Type | Units / format | Allowed values | Notes |
|---|---|---|---|---|
| staff_id | string | — | staff.csv | — |
| leave_from | date | — | — | inclusive |
| leave_to | date | — | — | inclusive |
| leave_type | enum | — | CASUAL, SICK, EARNED | — |

## Command file format

`commands.txt` holds one command per line in the form `COMMAND_NAME|arg1|arg2|...`. Commands must be processed strictly in file order. Lines starting with `#` are comments and blank lines are ignored. An argument written as `-` means "not applicable". Every command used in this pack:

| Command | Arguments (in order) | Meaning |
|---|---|---|
| `FALL` | `resident_id|ts|location` | Fall incident |
| `MED_ERROR` | `wing_id|ts|description` | Medication error in a wing |
| `HOSPITAL_ADMIT` | `resident_id|date|hospital` | — |
| `HOSPITAL_RETURN` | `resident_id|date` | — |
| `BED_RETAIN` | `resident_id|date|FULL` | Family pays 100% to keep the bed beyond 60 days |
| `ADDON` | `resident_id|date|addon_code|quantity` | — |
| `CONSUMABLE` | `resident_id|date|item|amount` | Actual cost |
| `DISCHARGE_NOTICE` | `resident_id|notice_date|vacate_date` | — |
| `VACATE` | `resident_id|date` | — |
| `DEATH` | `resident_id|date` | — |
| `GENERATE_BILLS` | `YYYY-MM|issue_date` | Bill the month in arrears; due on the 10th of the issue month |
| `PAYMENT` | `resident_id|date|FULL|mode` | Manual payment of the open bill |
| `BUILD_ROSTER` | `from_date|to_date` | Allocate staff to every wing/shift in the window |
| `PRINT_ROSTER` | `wing_id|date|shift` | shift DAY or NIGHT |
| `PRINT_BILL` | `resident_id|YYYY-MM` | — |
| `PRINT_COMPLIANCE` | `YYYY-MM` | — |
| `PRINT_CARE_PLAN` | `resident_id` | — |

## Planted scenarios

Every edge case in the brief, mapped to the exact record where it occurs, followed by extra traps.

- **EC-01 ADL 3 with cognitive 17 (two different levels implied)**
  - RES-025: every assessment has ADL 3 (-> LEVEL_2 band) with cognitive 17 (-> LEVEL_3 band) — two levels implied; the care level must resolve to one of them consistently — `assessments.csv row 29 (first of its rows)`
- **EC-02 Fall-risk flag on a LEVEL_4 resident**
  - RES-070 (memory wing, ADL 6, cognitive 5 = LEVEL_4) carries fall_risk = true — raising by one is capped at LEVEL_4 — `assessments.csv row 35`
- **EC-03 Level increase on the last day of the month**
  - RES-015 (LEVEL_2, shared room): reassessment on 2026-08-31 (ADL 4) -> LEVEL_3 — an increase takes effect immediately, so 31 August alone is billed at the LEVEL_3 rate (1/31 of the month) and the deposit difference is billed — `assessments.csv row 123`
- **EC-04 Hospitalisation of exactly 30 days**
  - RES-039: HOSPITAL_ADMIT 2026-08-06, HOSPITAL_RETURN 2026-09-05 = exactly 30 days — all 30 days at 50% of the fee (none at 25%); the PHYSIO add-on recorded on 2026-08-12 falls during hospitalisation and is not billed — `commands.txt lines 9, 16, 50`
- **EC-05 Wing with 20 residents (nurse count boundary)**
  - WING-M (memory wing) has exactly 20 residents — day-shift nurses = 20 / 20 = exactly 1; from the 2026-10-12 medication error the 1:15 tightening makes it 2 for 14 days — `commands.txt line 182; residents.csv rows with wing_id WING-M`
- **EC-06 Caregiver reaching 48 h with one shift left**
  - Roster week Mon 2026-10-05 to Sun 2026-10-11: with 30 caregivers against ~40 caregiver-shifts a day, caregivers reach 48 h (4 x 12 h) before the week ends — at the last shifts of the week a caregiver at 48 h cannot take one more shift; those slots become SHORTFALL at Rs 2500 each — `commands.txt lines 172, 173, 174, 176, 177, 178`
- **EC-07 Second fall on the 30th day after the first**
  - RES-014: falls on 2026-08-20 and on 2026-09-19 = the 30th day after the first — whether that is '2 falls in 30 days' decides an immediate one-level escalation — `commands.txt lines 21, 91`
- **EC-08 Discharge notice given 29 days before vacating**
  - RES-004: DISCHARGE_NOTICE on 2026-09-02 to vacate 2026-10-01 = 29 days — short of 30, so 50% of one month's fee is charged; pro-rata refund from the day after vacating; deposit refunded within 30 days minus dues — `commands.txt lines 36, 113`
- **Extra traps (not in the brief, but realistic):**
  - RES-023: DEATH on 2026-09-23 — notice period waived, pro-rata refund of September from 2026-09-24 — `commands.txt line 97`
  - RES-029: hospitalised 2026-08-03 to 2026-10-08 (66 days): 30 days at 50%, 30 days at 25%, then the bed would be released — the family's BED_RETAIN FULL keeps it at 100% — `commands.txt lines 6, 109, 149`
  - RES-050: reassessment on 2026-09-12 lowers LEVEL_3 -> LEVEL_2 — a decrease takes effect only from 1 October — `assessments.csv row 149`
  - RES-033 (LEVEL_3, 30-day cadence): reassessment due 2026-08-06 is done only on 2026-08-22 (16 days late) — a fall on 2026-08-15 cannot raise the bill until the reassessment is completed — `commands.txt line 18`
  - RES-030: September consumables Rs 23400.00 -> 10% handling = Rs 2340.00, capped at Rs 2000.00; 4 doctor visits -> 2 free, 2 billed at Rs 1500.00 — `commands.txt lines 41, 43, 71, 79, 88, 103, 105`
  - RES-003: already 2 late payments in the last 6 months; the August bill (due 2026-09-10) is paid on 2026-09-15 — interest at 1.5% per month and, as the 3rd late payment, advance payment is required from then on — `commands.txt line 83`
  - RES-022: admitted 2026-08-17 (deposit 2 months' LEVEL_1 shared fee); August billed pro-rata from the 17th; pays exactly on the due date 2026-09-10 — not late — `commands.txt line 68; residents.csv row 22`

## What is NOT in this pack

Expected outputs are not provided for this set. Validate your engine with your own test suite against the rules in your brief (BR-01 … BR-nn). A separate hidden input set with the same schema will be used at final evaluation; outputs are compared field-for-field, so follow the column formats above exactly in your own output.

## Output format expected at evaluation

Produce these CSV files (header row, same conventions as above, rows sorted as stated). Where the brief is silent on a format detail the choice below is binding for evaluation.

### `care_levels.csv`

One row per level change (incl. the initial level), per resident in date order.

Columns, in order: `resident_id`, `effective_date`, `care_level`, `basis`, `fall_risk_until`

### `bills.csv`

One row per bill line; lines ordered as fee, add-ons, consumables, adjustments, deposit, interest.

Columns, in order: `bill_id`, `resident_id`, `month`, `line_type`, `description`, `days`, `rate`, `amount`

### `staffing_requirements.csv`

One row per wing per shift per date.

Columns, in order: `date`, `shift`, `wing_id`, `caregivers_required`, `nurses_required`, `caregivers_assigned`, `nurses_assigned`, `shortfall`, `agency_cost`

### `rosters.csv`

One row per staff assignment.

Columns, in order: `date`, `shift`, `wing_id`, `staff_id`, `role`, `hours`, `week_hours_after`

### `compliance.csv`

One row per finding per month (overdue reassessments, ratio breaches, late payments).

Columns, in order: `month`, `finding_type`, `ref_id`, `detail`

Binding choices: bills are issued in arrears on the 1st of the next month and fall due on the 10th; pro-rating uses calendar days of the month; a week runs Monday to Sunday; shifts are 12 h. bill_id format BILL-<resident_id>-<YYYY-MM>; `line_type` FEE, HOSPITAL_RETENTION, ADDON, CONSUMABLE, HANDLING, NOTICE_CHARGE, REFUND, DEPOSIT_ADJUSTMENT, INTEREST; `basis` ASSESSMENT, FALL_RISK, FALL_ESCALATION.

## Project Demonstration Video

Watch the demonstration of the PS-128 Elderly Care Home Billing and Staffing Ratio Engine.

[Watch Project Demonstration Video](./PS128_Project_Demonstration_under_25MB.mp4)
