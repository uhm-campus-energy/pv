import subprocess
import sys
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
# Hours each reading represents (kWh = average kW x hours)
HOURS_PER_READING = {"15min": 0.25, "1hr": 1.0}

# Meters whose monthly kWh comes from a monthly report rather than pv_power data
MONTHLY_REPORT_METERS = {"burns_pv"}

CAMPUS = 'Manoa'
KWH_DECIMALS = 2

# Pass --no-refresh to re-run on the last downloaded extracts
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


print("=" * 80)
print("AGGREGATING PV POWER DATA TO MONTHLY KWH")
print("=" * 80)

# --- Step 1: Refresh the dates extracts ---
if refresh:
    refresh_script = Path(__file__).resolve().parent / "0) refresh_dates.py"
    print("\nRunning 0) refresh_dates.py to refresh the dates extracts...")
    subprocess.run([sys.executable, str(refresh_script)], check=True)

# --- Step 2: Work out which months to aggregate for each meter ---
monthly_df = read_dates_csv(extracts_dir / "dates_monthly_kwh.csv")
power_df = read_dates_csv(extracts_dir / "dates_pv_power.csv")

# Only complete months: stop before the current month
period_end = pd.Timestamp.today().normalize().replace(day=1)
last_complete = period_end - pd.Timedelta(days=1)

last_month_by_meter = {
    row["meter_name"]: pd.to_datetime(row["end_monthly_kwh"], errors="coerce")
    for _, row in monthly_df.iterrows()
}

# meter -> first month to aggregate (None = from the start of its data)
meter_starts = {}
print(f"\nMonths to aggregate (through {last_complete:%Y-%m}):")
for meter in sorted(set(power_df["meter_name"])):
    if meter in MONTHLY_REPORT_METERS:
        print(f"  {meter:<20} skipped — monthly kWh comes from a monthly report")
        continue
    last_month = last_month_by_meter.get(meter, pd.NaT)
    if pd.isna(last_month):
        meter_starts[meter] = None
        print(f"  {meter:<20} no monthly history found — aggregating all complete months")
        continue
    start = last_month + pd.offsets.MonthBegin(1)
    if start >= period_end:
        print(f"  {meter:<20} up to date (last month {last_month:%Y-%m})")
        continue
    meter_starts[meter] = start
    print(f"  {meter:<20} {start:%Y-%m} → {last_complete:%Y-%m}")

if not meter_starts:
    print("\nNothing to aggregate — all meters are up to date.")
    raise SystemExit(0)


def meter_condition(meter, start):
    cond = f"meter_name = '{meter}' AND datetime < '{period_end:%Y-%m-%d}'"
    if start is not None:
        cond += f" AND datetime >= '{start:%Y-%m-%d}'"
    return f"({cond})"


where = " OR ".join(meter_condition(meter, start) for meter, start in meter_starts.items())

# --- Step 3: Sum power by month in the database and download the results ---
frames = []
for freq, table in TABLES.items():
    extract_name = f"monthly_kwh_{table.split('.')[1]}.csv"
    if refresh:
        print(f"\nAggregating {table} by month...")
        copy_command = (
            f"\\copy (SELECT date_trunc('month', datetime)::date AS month, meter_name, "
            f"SUM(power_avg_kw) AS kw_sum, COUNT(power_avg_kw) AS readings "
            f"FROM {table} WHERE {where} GROUP BY 1, 2 ORDER BY 2, 1) "
            f"TO '{remote_extracts_dir}/{extract_name}' CSV HEADER;"
        )
        run_psql(copy_command, table)
        print(f"✅ Downloaded monthly sums from {table} to: {remote_extracts_dir}/{extract_name}")

    df = pd.read_csv(extracts_dir / extract_name, parse_dates=["month"])
    df["kwh"] = df["kw_sum"] * HOURS_PER_READING[freq]
    df["resolution"] = freq
    frames.append(df)
    print(f"✓ Loaded {len(df)} meter-month(s) from {table}")

combined = pd.concat(frames, ignore_index=True)
if combined.empty:
    print("\n⚠ No data found for the months checked. Output file not written.")
    raise SystemExit(0)

# --- Step 4: Clean up the combined results ---
no_data = combined["kwh"].isna()
if no_data.any():
    print(f"\n⚠ Dropping {int(no_data.sum())} meter-month(s) where every power value was null:")
    for _, r in combined[no_data].iterrows():
        print(f"    {r['meter_name']}  {r['month']:%Y-%m}  ({r['resolution']})")
    combined = combined[~no_data]

# A meter-month in both tables would be double counted — keep the 15min one and warn
combined["order"] = combined["resolution"].map({"15min": 0, "1hr": 1})
combined = combined.sort_values(["meter_name", "month", "order"]).reset_index(drop=True)
dupes = combined.duplicated(["meter_name", "month"], keep="first")
if dupes.any():
    print(f"\n⚠ {int(dupes.sum())} meter-month(s) found in both pv_power and pv_power_hr — keeping the 15min value:")
    for _, r in combined[dupes].iterrows():
        print(f"    {r['meter_name']}  {r['month']:%Y-%m}  (1hr value ignored: {r['kwh']:.2f} kWh)")
    combined = combined[~dupes]

# --- Step 5: Build the upload file ---
out = combined[["month", "meter_name", "kwh"]].copy()
out["month"] = out["month"].dt.strftime("%Y-%m-%d")
out["kwh"] = out["kwh"].round(KWH_DECIMALS)
out["note"] = ""
out["campus"] = CAMPUS

print("\n" + "=" * 80)
print("MONTHLY KWH TO UPLOAD")
print("=" * 80)
preview = combined[["meter_name", "month", "resolution", "readings", "kwh"]].copy()
preview["month"] = preview["month"].dt.strftime("%Y-%m")
preview["kwh"] = preview["kwh"].round(KWH_DECIMALS)
print(preview.to_string(index=False))

first_month = combined["month"].min()
last_month = combined["month"].max()
output_csv = analysis_dir / f"monthly_kwh_aggregated_{first_month:%Y-%m}_{last_month:%Y-%m}.csv"
out.to_csv(output_csv, index=False)

print(f"\n✅ Wrote {len(out)} row(s) for {out['meter_name'].nunique()} meter(s) to: {output_csv}")
print("   Columns: month, meter_name, kwh, note, campus")
print("\n" + "=" * 80)
print("✨ AGGREGATION COMPLETE!")
print("=" * 80)