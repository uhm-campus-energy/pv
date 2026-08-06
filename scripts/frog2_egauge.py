import pandas as pd

# File paths
input_csv = r"C:\Users\EileenPeppard\Desktop\2026-03-24_PV_data\frog2\data.csv"
output_csv = r"C:\Users\EileenPeppard\Desktop\2026-03-24_PV_data\cleaned\frog2_pv_cleaned.csv"
dates_csv_path = r"C:\Users\EileenPeppard\Desktop\2026-03-24_PV_data\dates_pv_power.csv"
## when done upload to table from command line using folder on server, eg. \copy pv.pv_power2(sensor_id,meter_name,datetime,power_avg_kw) from '/home/eileen/uploads_uhm/frog2_pv_cleaned.csv' CSV HEADER;

meter_name = "frog2_pv"

print("=" * 80)
print("CLEANING FROG2 SUBMETER DATA")
print("=" * 80)

# Load the data
df = pd.read_csv(input_csv)
print(f"\n✓ Loaded data: {df.shape[0]} rows × {df.shape[1]} columns")
print(f"  Original columns: {list(df.columns)}")

# Keep only the columns we need and rename them
df_cleaned = df[['Date & Time', 'PV [kW]']].copy()
df_cleaned = df_cleaned.rename(columns={
    'Date & Time': 'datetime',
    'PV [kW]': 'power_avg_kw'
})

# Add new columns with specified values
df_cleaned['sensor_id'] = 4
df_cleaned['meter_name'] = meter_name

# Multiply power_avg_kw by -1 to change the sign
df_cleaned['power_avg_kw'] = df_cleaned['power_avg_kw'] * -1

# Convert datetime column to pandas datetime for sorting/trimming
df_cleaned['datetime'] = pd.to_datetime(df_cleaned['datetime'])

# Reorder columns: sensor_id, meter_name, datetime, power_avg_kw
df_cleaned = df_cleaned[['sensor_id', 'meter_name', 'datetime', 'power_avg_kw']]

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
    return "15min" if minutes <= 20 else "1h"

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

# --- Format datetime for output and build output path ---
df_cleaned['datetime'] = df_cleaned['datetime'].dt.strftime('%m/%d/%Y %H:%M:%S')

# Append _hr to filename if data is hourly
if freq == "1h":
    final_output_csv = output_csv.replace(".csv", "_hr.csv")
else:
    final_output_csv = output_csv

print(f"\n✓ Multiplied power_avg_kw by -1 to change sign")
print(f"✓ Converted datetime to MM/DD/YYYY HH:MM:SS format")
print(f"\n✓ Cleaned data: {df_cleaned.shape[0]} rows × {df_cleaned.shape[1]} columns")
print(f"  New columns: {list(df_cleaned.columns)}")

# Show sample of cleaned data
print("\n  Sample of cleaned data:")
print(df_cleaned.head(10).to_string(index=False))

# Save cleaned data
df_cleaned.to_csv(final_output_csv, index=False)

print(f"\n✅ Cleaned data saved to: {final_output_csv}")
print("\n" + "=" * 80)
print("✨ CLEANING COMPLETE!")
print("=" * 80)