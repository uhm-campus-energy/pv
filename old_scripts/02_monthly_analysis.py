import math
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd

# Database connection and paths
db_name = "uhm2023"
project_root = Path(__file__).resolve().parent.parent
extracts_dir = project_root / "extracts"
remote_extracts_dir = "/home/campusenergy/shared/pv/extracts"
analysis_dir = project_root / "analysis"
analysis_dir.mkdir(exist_ok=True)

# Source tables by resolution
TABLES = {
    "15min": "pv.pv_power",
    "1hr": "pv.pv_power_hr",
}
STEP = {"15min": pd.Timedelta(minutes=15), "1hr": pd.Timedelta(hours=1)}

# Meters whose monthly kWh comes from a monthly report rather than pv_power data
MONTHLY_REPORT_METERS = {"burns_pv"}

# Honolulu, for sunrise/sunset (HST is UTC-10 with no daylight saving time)
LATITUDE = 21.2969
LONGITUDE = -157.8171
UTC_OFFSET_HOURS = -10

# Longest gaps listed per meter in the printed report (all gaps go to the CSV)
MAX_GAPS_SHOWN = 15

# Pass --no-refresh to re-run the analysis on the last downloaded extracts
refresh = "--no-refresh" not in sys.argv


def run_psql(copy_command, label):
    result = subprocess.run(
        ["psql", db_name, "-c", copy_command],
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError(f"psql export of {label} failed with exit code {result.returncode}")


def read_dates_csv(path):
    df = pd.read_csv(path, encoding="utf-8-sig")
    df.columns = [c.strip().strip('"') for c in df.columns]
    for col in df.columns:
        df[col] = df[col].astype(str).str.strip().str.strip('"')
    return df


def sun_times(day):
    """Sunrise and sunset (local time) for a date, using the NOAA solar equations."""
    n = day.timetuple().tm_yday
    g = 2 * math.pi / 365 * (n - 1)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                       - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g)
            - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
            - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    lat = math.radians(LATITUDE)
    ha = math.degrees(math.acos(
        math.cos(math.radians(90.833)) / (math.cos(lat) * math.cos(decl))
        - math.tan(lat) * math.tan(decl)
    ))
    sunrise_min = 720 - 4 * (LONGITUDE + ha) - eqtime + UTC_OFFSET_HOURS * 60
    sunset_min = 720 - 4 * (LONGITUDE - ha) - eqtime + UTC_OFFSET_HOURS * 60
    midnight = pd.Timestamp(day)
    return midnight + timedelta(minutes=sunrise_min), midnight + timedelta(minutes=sunset_min)


def expected_slots(month_start, freq):
    """All slots in the month; daylight flag marks slots that fall fully between sunrise and sunset."""
    month_end = month_start + pd.offsets.MonthBegin(1)
    slots = pd.date_range(month_start, month_end, freq=STEP[freq], inclusive="left")
    daylight = []
    for day in pd.date_range(month_start, month_end, freq="D", inclusive="left"):
        sunrise, sunset = sun_times(day.date())
        day_slots = slots[(slots >= day) & (slots < day + pd.Timedelta(days=1))]
        daylight.extend((day_slots >= sunrise) & (day_slots + STEP[freq] <= sunset))
    return pd.DataFrame({"slot": slots, "daylight": daylight})


def find_gaps(expected, present, meter, freq):
    """Group consecutive missing expected slots into gap ranges."""
    expected = expected.copy()
    expected["missing"] = ~expected["slot"].isin(present)
    run_id = (expected["missing"] != expected["missing"].shift()).cumsum()
    gaps = []
    for _, run in expected[expected["missing"]].groupby(run_id[expected["missing"]]):
        gaps.append({
            "meter_name": meter,
            "resolution": freq,
            "gap_start": run["slot"].iloc[0],
            "gap_end": run["slot"].iloc[-1] + STEP[freq],
            "missing_readings": len(run),
            "missing_hours": len(run) * STEP[freq] / pd.Timedelta(hours=1),
        })
    return gaps


print("=" * 80)
print("MONTHLY DATA COMPLETENESS ANALYSIS")
print("=" * 80)

# --- Step 1: Refresh the dates extracts ---
if refresh:
    refresh_script = Path(__file__).resolve().parent / "00_refresh_dates.py"
    print("\nRunning 00_refresh_dates.py to refresh the dates extracts...")
    subprocess.run([sys.executable, str(refresh_script)], check=True)

# --- Step 2: Work out which months to check for each meter ---
monthly_df = read_dates_csv(extracts_dir / "dates_monthly_kwh.csv")
power_df = read_dates_csv(extracts_dir / "dates_pv_power.csv")

# Only complete months: stop before the current month
period_end = pd.Timestamp.today().normalize().replace(day=1)

meter_starts = {}
print(f"\nMonths to check (through {(period_end - pd.Timedelta(days=1)):%Y-%m}):")
for _, row in monthly_df.iterrows():
    meter = row["meter_name"]
    if meter in MONTHLY_REPORT_METERS:
        print(f"  {meter:<20} skipped — monthly kWh comes from a monthly report")
        continue
    last_month = pd.to_datetime(row["end_monthly_kwh"], errors="coerce")
    if pd.isna(last_month):
        print(f"  {meter:<20} skipped — no end_monthly_kwh value")
        continue
    start = last_month + pd.offsets.MonthBegin(1)
    if start >= period_end:
        print(f"  {meter:<20} up to date (last month {last_month:%Y-%m})")
        continue
    meter_starts[meter] = start
    print(f"  {meter:<20} {start:%Y-%m} → {(period_end - pd.Timedelta(days=1)):%Y-%m}")

not_in_monthly = sorted(set(power_df["meter_name"]) - set(monthly_df["meter_name"]))
if not_in_monthly:
    print(f"\n  ⚠ In dates_pv_power but not dates_monthly_kwh (not checked): {', '.join(not_in_monthly)}")

if not meter_starts:
    print("\nNothing to check — all meters are up to date.")
    raise SystemExit(0)

# --- Step 3: Download pv_power and pv_power_hr rows for those months ---
where = " OR ".join(
    f"(meter_name = '{meter}' AND datetime >= '{start:%Y-%m-%d}' AND datetime < '{period_end:%Y-%m-%d}')"
    for meter, start in meter_starts.items()
)
for freq, table in TABLES.items():
    extract_name = f"monthly_analysis_{table.split('.')[1]}.csv"
    if refresh:
        print(f"\nDownloading {table}...")
        copy_command = (
            f"\\copy (SELECT meter_name, datetime, power_avg_kw FROM {table} WHERE {where} "
            f"ORDER BY meter_name, datetime) TO '{remote_extracts_dir}/{extract_name}' CSV HEADER;"
        )
        run_psql(copy_command, table)
        print(f"✅ Downloaded {table} to: {remote_extracts_dir}/{extract_name}")

readings = {}
for freq, table in TABLES.items():
    df = pd.read_csv(extracts_dir / f"monthly_analysis_{table.split('.')[1]}.csv", parse_dates=["datetime"])
    # Some loggers stamp readings a few minutes off the interval (e.g. 11:17) — snap to the slot
    df["slot"] = df["datetime"].dt.floor(STEP[freq])
    readings[freq] = df
    print(f"\n✓ Loaded {len(df)} {freq} reading(s) from {table}")

# Fallback resolution for meters with no data at all in the period
resolution_by_meter = {
    row["meter_name"]: ("1hr" if row["resolution_per_hr"] == "1" else "15min")
    for _, row in power_df.iterrows()
}

# --- Step 4: Check completeness for every meter and month ---
summary_rows = []
all_gaps = []

for meter, start in meter_starts.items():
    # Check whichever table(s) this meter has data in for the period
    freqs = [f for f in TABLES if (readings[f]["meter_name"] == meter).any()]
    if not freqs:
        freqs = [resolution_by_meter.get(meter, "15min")]

    for freq in freqs:
        meter_slots = set(readings[freq].loc[readings[freq]["meter_name"] == meter, "slot"])

        months = pd.date_range(start, period_end, freq="MS", inclusive="left")
        expected = pd.concat([expected_slots(m, freq) for m in months], ignore_index=True)
        if freq == "15min":
            # PV doesn't produce at night — only daylight slots are expected
            expected = expected[expected["daylight"]].reset_index(drop=True)
        expected["month"] = expected["slot"].dt.to_period("M").dt.to_timestamp()
        expected["present"] = expected["slot"].isin(meter_slots)

        # Gaps are found across the whole period so a gap spanning months is reported once
        all_gaps.extend(find_gaps(expected, meter_slots, meter, freq))

        for month_start, month in expected.groupby("month"):
            missing = month[~month["present"]]
            summary_rows.append({
                "meter_name": meter,
                "month": month_start.strftime("%Y-%m-%d"),
                "resolution": freq,
                "expected": len(month),
                "present": int(month["present"].sum()),
                "missing": len(missing),
                "missing_daylight": int(missing["daylight"].sum()),
                "pct_complete": round(100 * month["present"].mean(), 1),
            })

summary = pd.DataFrame(summary_rows)
gaps_df = pd.DataFrame(all_gaps, columns=[
    "meter_name", "resolution", "gap_start", "gap_end", "missing_readings", "missing_hours",
])

# --- Step 5: Report ---
print("\n" + "=" * 80)
print("COMPLETENESS BY METER AND MONTH")
print("  15min: expected = 4 readings/hour, daylight only (sunrise to sunset)")
print("  1hr:   expected = 24 readings/day (missing_daylight = how many of the missing were daytime)")
print("=" * 80)
print(summary.to_string(index=False))

incomplete = summary[summary["missing"] > 0]
print("\n" + "=" * 80)
print("WHAT IS MISSING")
print("=" * 80)
if incomplete.empty:
    print("✅ Every meter has a complete record for every month checked.")
else:
    for meter, meter_gaps in gaps_df.groupby("meter_name", sort=False):
        print(f"\n{meter}: {len(meter_gaps)} gap(s), {meter_gaps['missing_hours'].sum():g} h missing")
        # Show the longest gaps in date order; the full list is in the gaps CSV
        shown = meter_gaps.nlargest(MAX_GAPS_SHOWN, "missing_hours").sort_values("gap_start")
        for _, g in shown.iterrows():
            print(f"  {g['resolution']:<5}  {g['gap_start']:%Y-%m-%d %H:%M} → {g['gap_end']:%Y-%m-%d %H:%M}"
                  f"  ({g['missing_readings']} reading(s), {g['missing_hours']:g} h)")
        if len(meter_gaps) > MAX_GAPS_SHOWN:
            print(f"  … {len(meter_gaps) - MAX_GAPS_SHOWN} shorter gap(s) not shown — see the gaps CSV")

summary_csv = analysis_dir / "monthly_completeness.csv"
gaps_csv = analysis_dir / "monthly_missing_gaps.csv"
summary.to_csv(summary_csv, index=False)
gaps_df.to_csv(gaps_csv, index=False, date_format="%Y-%m-%d %H:%M:%S")

print(f"\n✅ Summary saved to: {summary_csv}")
print(f"✅ Gaps saved to: {gaps_csv}")
print("\n" + "=" * 80)
print("✨ ANALYSIS COMPLETE!")
print("=" * 80)
