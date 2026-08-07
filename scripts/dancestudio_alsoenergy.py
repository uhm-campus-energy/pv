import pandas as pd
from pathlib import Path

# File paths (relative to project root)
project_root = Path(__file__).resolve().parent.parent
input_dir = project_root / "data" / "dancestudio_alsoenergy"
input_csvs = list(input_dir.glob("*.csv"))
if len(input_csvs) != 1:
    raise FileNotFoundError(
        f"Expected exactly one CSV in {input_dir}, found {len(input_csvs)}: {input_csvs}"
    )
input_csv = input_csvs[0]
output_dir = project_root / "outputs"
output_dir.mkdir(exist_ok=True)
dates_csv_path = project_root / "extracts" / "dates_pv_power.csv"
meter_name = "dance_pv"  # matches meter_name in dates_pv_power.csv
## when done upload to table from command line using folder on server, eg. \copy pv.pv_power (sensor_id,meter_name,datetime,power_avg_kw) from '/home/eileen/uploads_uhm/dancestudio_pv_cleaned.csv' CSV HEADER;


print("=" * 80)
print("CLEANING DANCESTUDIO SUBMETER DATA")
print("=" * 80)

# Load the data
df = pd.read_csv(input_csv)
print(f"\n✓ Loaded data: {df.shape[0]} rows × {df.shape[1]} columns")
print(f"  Original columns: {list(df.columns)}")

# Keep only the columns we need and rename them
df_cleaned = df[['Site Time', 'Production meter active power Kilowatts']].copy()
df_cleaned = df_cleaned.rename(columns={
    'Site Time': 'datetime',
    'Production meter active power Kilowatts': 'power_avg_kw'
})

# Add new columns with specified values
df_cleaned['sensor_id'] = 1
df_cleaned['meter_name'] = meter_name

# # Multiply power_avg_kw by -1 to change the sign
# df_cleaned['power_avg_kw'] = df_cleaned['power_avg_kw'] * -1

# Convert datetime column to pandas datetime for sorting/trimming
df_cleaned['datetime'] = pd.to_datetime(df_cleaned['datetime'])

# --- Sort by timestamp ---
df_cleaned = df_cleaned.sort_values('datetime').reset_index(drop=True)
print(f"\n✓ Sorted rows by timestamp")

# --- Detect timestamp frequency ---
def detect_frequency(df):
    sorted_dt = df['datetime'].drop_duplicates().sort_values()
    if len(sorted_dt) < 2:
        return "unknown"
    diffs = sorted_dt.diff().dropna()
    median_diff = diffs.median()
    minutes = median_diff.total_seconds() / 60
    print(f"  Median timestamp interval: {minutes:.1f} minutes")
    return "15min" if minutes <= 20 else "1hr"

print("\nDetecting timestamp frequency...")
freq = detect_frequency(df_cleaned)
print(f"  Detected frequency: {freq}")

# --- Look up cutoff timestamp and trim ---
def get_cutoff_timestamp(dates_csv, meter, freq):
    try:
        dates_df = pd.read_csv(dates_csv, encoding="utf-8-sig")
        dates_df.columns = [c.strip().strip('"') for c in dates_df.columns]
        for col in dates_df.select_dtypes(include="object").columns:
            dates_df[col] = dates_df[col].astype(str).str.strip().str.strip('"')

        row = dates_df[dates_df['meter_name'] == meter]
        if row.empty:
            print(f"⚠ meter_name '{meter}' not found in dates CSV — no trimming applied.")
            return None

        col_name = "pv_power_end" if freq == "15min" else "pv_power_hr_end"
        val = row.iloc[0][col_name]

        if pd.isna(val) or str(val).strip().lower() in ("", "nan", "none"):
            print(f"  '{col_name}' is empty for '{meter}' — no trimming applied.")
            return None

        cutoff = pd.to_datetime(val, errors="coerce")
        if pd.isna(cutoff):
            print(f"  Could not parse '{col_name}' value '{val}' — no trimming applied.")
            return None

        return cutoff

    except Exception as e:
        print(f"⚠ Could not read dates CSV: {e}")
        return None

print(f"\nLooking up cutoff timestamp for meter '{meter_name}' (freq={freq})...")
cutoff = get_cutoff_timestamp(dates_csv_path, meter_name, freq)

if cutoff is not None:
    before_trim = len(df_cleaned)
    df_cleaned = df_cleaned[df_cleaned['datetime'] > cutoff].reset_index(drop=True)
    after_trim = len(df_cleaned)
    print(f"  Cutoff: {cutoff}  →  Kept rows after cutoff: {after_trim} (trimmed {before_trim - after_trim})")
else:
    print("  No trimming applied.")

# Rename the input file to <subfolder>_<start-date>_<end-date>_<freq>.csv
start_date = df_cleaned['datetime'].min().strftime('%Y-%m-%d')
end_date = df_cleaned['datetime'].max().strftime('%Y-%m-%d')
new_input_csv = input_dir / f"{input_dir.name}_{start_date}_{end_date}_{freq}.csv"
if input_csv != new_input_csv:
    input_csv.rename(new_input_csv)
    print(f"\n✓ Renamed input file to: {new_input_csv.name}")
    input_csv = new_input_csv

# Output file follows the same naming convention as the data file
output_csv = output_dir / f"dance_pv_cleaned_{start_date}_{end_date}_{freq}.csv"

# --- Format datetime for output ---
df_cleaned['datetime'] = df_cleaned['datetime'].dt.strftime('%Y-%m-%d %H:%M:%S')

print(f"\n✓ Converted datetime to YYYY-MM-DD HH:MM:SS format")

# Reorder columns: datetime, sensor_id, power_avg_kw, meter_name
df_cleaned = df_cleaned[['datetime', 'sensor_id', 'power_avg_kw', 'meter_name']]

print(f"\n✓ Cleaned data: {df_cleaned.shape[0]} rows × {df_cleaned.shape[1]} columns")
print(f"  New columns: {list(df_cleaned.columns)}")

# Show sample of cleaned data
print("\n  Sample of cleaned data:")
print(df_cleaned.head(10).to_string(index=False))

# Save cleaned data
df_cleaned.to_csv(output_csv, index=False)

print(f"\n✅ Cleaned data saved to: {output_csv}")
print("\n" + "=" * 80)
print("✨ CLEANING COMPLETE!")
print("=" * 80)
