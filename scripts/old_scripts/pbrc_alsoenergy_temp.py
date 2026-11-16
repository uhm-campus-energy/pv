import pandas as pd
from pathlib import Path

# TEMPORARY: backfills one fixed window of pbrc_pv data. The window is older than
# pv_power_end in dates_pv_power.csv, so the cutoff trim in pbrc_alsoenergy.py would
# drop it all — this script uses the window below instead and doesn't rename inputs.

# File paths (relative to project root)
project_root = Path(__file__).resolve().parent.parent
input_dir = project_root / "data" / "pbrc_alsoenergy"
input_csvs = sorted(input_dir.glob("*.csv"))
if not input_csvs:
    raise FileNotFoundError(f"No CSVs found in {input_dir}")
output_dir = project_root / "outputs"
output_dir.mkdir(exist_ok=True)
meter_name = "pbrc_pv"

# Window to keep (both ends inclusive)
window_start = pd.Timestamp("2026-03-17 10:00:00")
window_end = pd.Timestamp("2026-03-24 23:45:00")
## when done upload to table from command line using folder on server, eg. \copy pv.pv_power (sensor_id,meter_name,datetime,power_avg_kw) from '/home/eileen/uploads_uhm/pbrc_pv_cleaned.csv' CSV HEADER;

# The AlsoEnergy export has used both of these headers for the power column
POWER_COLUMNS = ["PV Inverter active power (kW)", "PV Inverter active power Kilowatts"]


print("=" * 80)
print("CLEANING PBRC PV DATA (TEMPORARY WINDOW)")
print("=" * 80)

# Load and combine every CSV in the folder
frames = []
for csv in input_csvs:
    df = pd.read_csv(csv)
    power_col = next((c for c in POWER_COLUMNS if c in df.columns), None)
    if power_col is None:
        raise KeyError(f"{csv.name}: no power column found in {list(df.columns)}")
    df = df[['Site Time', power_col]].rename(columns={'Site Time': 'datetime', power_col: 'power_avg_kw'})
    frames.append(df)
    print(f"\n✓ Loaded {csv.name}: {len(df)} rows")

df_cleaned = pd.concat(frames, ignore_index=True)
df_cleaned['datetime'] = pd.to_datetime(df_cleaned['datetime'], format='%m-%d-%Y %H:%M:%S')

# Files can overlap — keep one row per timestamp
before_dedupe = len(df_cleaned)
df_cleaned = df_cleaned.drop_duplicates('datetime', keep='first')
if len(df_cleaned) < before_dedupe:
    print(f"\n✓ Dropped {before_dedupe - len(df_cleaned)} duplicate timestamp(s)")

# --- Sort and trim to the window ---
df_cleaned = df_cleaned.sort_values('datetime').reset_index(drop=True)
df_cleaned = df_cleaned[df_cleaned['datetime'].between(window_start, window_end)].reset_index(drop=True)
print(f"\n✓ Kept {len(df_cleaned)} rows from {window_start} to {window_end} (inclusive)")

# Check the window is complete at 15-min resolution
expected = pd.date_range(window_start, window_end, freq="15min")
missing = expected.difference(df_cleaned['datetime'])
if len(missing):
    print(f"⚠ {len(missing)} of {len(expected)} expected 15-min timestamps are missing, e.g. {list(missing[:5])}")
else:
    print(f"  All {len(expected)} expected 15-min timestamps present")

# Add new columns with specified values
df_cleaned['sensor_id'] = 8
df_cleaned['meter_name'] = meter_name

start_date = window_start.strftime('%Y-%m-%d')
end_date = window_end.strftime('%Y-%m-%d')
output_csv = output_dir / f"pbrc_pv_cleaned_{start_date}_{end_date}_15min.csv"

# --- Format datetime for output ---
df_cleaned['datetime'] = df_cleaned['datetime'].dt.strftime('%Y-%m-%d %H:%M:%S')

# Reorder columns: datetime, sensor_id, power_avg_kw, meter_name
df_cleaned = df_cleaned[['datetime', 'sensor_id', 'power_avg_kw', 'meter_name']]

print(f"\n✓ Cleaned data: {df_cleaned.shape[0]} rows × {df_cleaned.shape[1]} columns")
print("\n  First and last rows:")
print(pd.concat([df_cleaned.head(3), df_cleaned.tail(3)]).to_string(index=False))

# Save cleaned data
df_cleaned.to_csv(output_csv, index=False)

print(f"\n✅ Cleaned data saved to: {output_csv}")
print("\n" + "=" * 80)
print("✨ CLEANING COMPLETE!")
print("=" * 80)
