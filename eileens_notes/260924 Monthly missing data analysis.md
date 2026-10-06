# PV project: monthly missing-data analysis

*Written 2026-09-24.*

---

## Done today

Ran `02_monthly_analysis.py` and synced its outputs to this folder:

- `extracts/monthly_analysis_pv_power.csv` and `monthly_analysis_pv_power_hr.csv`: the readings downloaded for the check
- `analysis/monthly_completeness.csv`: expected vs. present readings for each meter and month
- `analysis/monthly_missing_gaps.csv`: every gap, with its start, end and length

The script checks each meter from the month after its `end_monthly_kwh` through the last complete month, so **Jul 2025 – Aug 2026** this time. `burns_pv` is skipped because its kWh comes from the monthly report. For 15-min meters, only daylight slots count as expected; hourly meters are expected to have all 24 hours.

## What's missing

**Jul 2025 – Jul 2026:** every meter is 100% complete, except for two real gaps:

| Meter | Gap | Missing |
|---|---|---|
| `bachman_pv` (15min) | 2025-08-13 06:15 → 2025-08-14 19:00 | 25.5 daylight h (Aug 2025 is 93.5% complete) |
| `warrior_pv` (1hr) | 2026-01-01 00:00 → 2026-01-06 01:00 | 121 h, 49 of them daylight (Jan 2026 is 83.7% complete) |

**Aug 2026:** every meter is only 13–20% complete. The data stops around Aug 5–7, which matches the last portal downloads (Aug 6). This is most likely **data that hasn't been downloaded or uploaded yet**, not a real outage. Download through the end of August and re-run the analysis before treating it as missing.

## Not decided yet

I haven't decided what to do about the missing data. Open questions:

1. **Bachman, Aug 13–14 2025, and WRC, Jan 1–6 2026**: can the missing data be re-downloaded from the portal (eGauge / SunnyPortal)? If not, should these months be filled in (for example, interpolated or estimated from nearby days or other meters), flagged as incomplete, or left out of the monthly kWh?
2. **What counts as complete enough?** Is there a threshold (for example, 95%) above which a month's kWh can be computed as is?
3. **August 2026**: once the rest of August is downloaded and uploaded, re-run `02_monthly_analysis.py` to confirm the month is complete.
