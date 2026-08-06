import pandas as pd

# File paths
input_csv = r"C:\Users\EileenPeppard\Desktop\2026-03-24_PV_data\frog1\data.csv"
output_pv_csv = r"C:\Users\EileenPeppard\Desktop\2026-03-24_PV_data\cleaned\frog1_pv_cleaned.csv"
dates_csv_path = r"C:\Users\EileenPeppard\Desktop\2026-03-24_PV_data\dates_pv_power.csv"

## upload at commandline \copy aurora_v4.kw (meter_name,datetime,mean) from '/home/eileen/uploads_uhm/frog1_main.csv' CSV HEADER;

meter_name = "frog1_pv"

print("=" * 80)
print("CLEANING FROG1 SUBMETER DATA - TWO OUTPUTS")
print("=" * 80)

# Load the data
df = pd.read_csv(input_csv)
print(f"\n✓ Loaded data: {df.shape[0]} rows × {df.shape[1]} columns")
print(f"  Original columns: {list(df.columns)}")

# ============================================================================
# OUTPUT 1: FROG1_PV_CLEANED
# ============================================================================
print("\n" + "=" * 80)
print("OUTPUT 1: FROG1_PV_CLEANED")
print("=" * 80)

# Keep only the columns we need and rename them
df_pv = df[['Date & Time', 'pv [kW]']].copy()
df_pv = df_pv.rename(columns={
    'Date & Time': 'datetime',
    'pv [kW]': 'power_avg_kw'
})

# Add new columns with specified values
df_pv['sensor_id'] = 3
df_pv['meter_name'] = meter_name

# Multiply power_avg_kw by -1 to change the sign
df_pv['power_avg_kw'] = df_pv['power_avg_kw'] * -1

# Convert datetime to proper datetime format and sort
df_pv['datetime'] = pd.to_datetime(df_pv['datetime'])
df_pv = df_pv.sort_values('datetime').reset_index(drop=True)
print(f"\n✓ Sorted rows by timestamp")

# Reorder columns: sensor_id, meter_name, datetime, power_avg_kw
df_pv = df_pv[['sensor_id', 'meter_name', 'datetime', 'power_avg_kw']]

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
freq = detect_frequency(df_pv)
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
    before_trim = len(df_pv)
    df_pv = df_pv[df_pv['datetime'] > cutoff].reset_index(drop=True)
    after_trim = len(df_pv)
    print(f"  Cutoff: {cutoff}  →  Kept rows after cutoff: {after_trim} (trimmed {before_trim - after_trim})")
else:
    print("  No trimming applied.")

# --- Format datetime for output and build output path ---
df_pv['datetime'] = df_pv['datetime'].dt.strftime('%m/%d/%Y %H:%M:%S')
print(f"\n✓ Converted datetime to MM/DD/YYYY HH:MM:SS format")

# Append _hr to filename if data is hourly
if freq == "1h":
    final_output_pv_csv = output_pv_csv.replace(".csv", "_hr.csv")
else:
    final_output_pv_csv = output_pv_csv

print(f"\n✓ Created PV data: {df_pv.shape[0]} rows × {df_pv.shape[1]} columns")
print(f"  Columns: {list(df_pv.columns)}")
print(f"\n  Sample of PV data:")
print(df_pv.head(10).to_string(index=False))

# Save PV data
df_pv.to_csv(final_output_pv_csv, index=False)
print(f"\n✅ PV data saved to: {final_output_pv_csv}")


# ============================================================================
# SUMMARY
# ============================================================================
print("\n" + "=" * 80)
print("✨ CLEANING COMPLETE! - TWO FILES CREATED")
print("=" * 80)
print(f"\n1. {final_output_pv_csv}")
print(f"   - Columns: sensor_id, meter_name, datetime, power_avg_kw")
print(f"   - Columns: meter_name, datetime, mean")