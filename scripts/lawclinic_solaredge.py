import hashlib
import shutil
import pandas as pd
from pathlib import Path

# File paths (relative to project root)
project_root = Path(__file__).resolve().parent.parent
input_dir = project_root / "data" / "lawclinic_solaredge"
archive_dir = input_dir / "archive"
input_csvs = sorted(input_dir.glob("*.csv"))
if not input_csvs:
    raise FileNotFoundError(f"No CSVs found in {input_dir}")
output_dir = project_root / "outputs"
output_dir.mkdir(exist_ok=True)
dates_csv_path = project_root / "extracts" / "dates_pv_power.csv"
sensor_id_value = 9
meter_name = "law_clinic_pv"
output_basename = "law_pv_cleaned"
## when done upload to table from command line using folder on server, eg. \copy pv.pv_power (sensor_id,meter_name,datetime,power_avg_kw) from '/home/eileen/uploads_uhm/law_pv_cleaned.csv' CSV HEADER;


print("=" * 80)
print("CLEANING LAW CLINIC PV DATA")
print("=" * 80)


def read_one_csv(path):
    """Read a SolarEdge per-inverter export and sum inverter power (W) into kW."""
    df = pd.read_csv(path, encoding="utf-8-sig", on_bad_lines="skip")

    # Identify datetime column (supports 'DateTime' or 'Date & Time')
    dt_col = None
    for c in df.columns:
        if str(c).strip().lower() in ("datetime", "date & time"):
            dt_col = c
            break
    if dt_col is None:
        dt_col = df.columns[0]

    inverter_cols = [c for c in df.columns if c != dt_col]

    df[dt_col] = pd.to_datetime(df[dt_col].astype(str).str.strip(), errors="coerce")
    df[inverter_cols] = df[inverter_cols].apply(pd.to_numeric, errors="coerce").fillna(0)
    df = df.dropna(subset=[dt_col])

    df["power_avg_kw"] = df[inverter_cols].sum(axis=1) / 1000.0
    df = df.rename(columns={dt_col: "datetime"})

    return df[["datetime", "power_avg_kw"]]


def move_duplicate_files(csv_paths, folder):
    """Move byte-identical duplicate exports to a 'duplicates' subfolder."""
    duplicates_dir = Path(folder) / "duplicates"
    seen_hashes = {}
    unique_paths = []

    for path in csv_paths:
        file_hash = hashlib.md5(path.read_bytes()).hexdigest()
        if file_hash in seen_hashes:
            duplicates_dir.mkdir(parents=True, exist_ok=True)
            dest = duplicates_dir / path.name
            if dest.exists():
                dest = duplicates_dir / f"{path.stem}_dup{path.suffix}"
            shutil.move(str(path), dest)
            print(f"  ⚠ Duplicate of '{seen_hashes[file_hash]}' → moved to duplicates/: {path.name}")
        else:
            seen_hashes[file_hash] = path.name
            unique_paths.append(path)

    return unique_paths


# --- Check for byte-identical duplicate exports ---
print(f"\nFound {len(input_csvs)} CSV file(s). Checking for duplicates...")
input_csvs = move_duplicate_files(input_csvs, input_dir)
print(f"  {len(input_csvs)} unique file(s) remaining after duplicate check.")

# --- Load and combine all inverter export files ---
parts = [read_one_csv(p) for p in input_csvs]
before_dedup = sum(len(p) for p in parts)
combined_raw = pd.concat(parts, ignore_index=True)
combined_raw = combined_raw.sort_values("datetime").drop_duplicates().reset_index(drop=True)
print(f"\n✓ Combined {len(input_csvs)} file(s) into {len(combined_raw)} row(s) "
      f"(removed {before_dedup - len(combined_raw)} duplicate row(s))")

# Add new columns with specified values
df_cleaned = combined_raw.copy()
df_cleaned["sensor_id"] = sensor_id_value
df_cleaned["meter_name"] = meter_name

# --- Timestamp frequency (data is known to be 1hr resolution) ---
freq = "1hr"
print(f"\nFrequency: {freq}")


# --- Look up cutoff timestamp and trim ---
def get_cutoff_timestamp(dates_csv, meter, freq):
    try:
        dates_df = pd.read_csv(dates_csv, encoding="utf-8-sig")
        dates_df.columns = [c.strip().strip('"') for c in dates_df.columns]
        for col in dates_df.select_dtypes(include="object").columns:
            dates_df[col] = dates_df[col].astype(str).str.strip().str.strip('"')

        row = dates_df[dates_df["meter_name"] == meter]
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
    df_cleaned = df_cleaned[df_cleaned["datetime"] > cutoff].reset_index(drop=True)
    after_trim = len(df_cleaned)
    print(f"  Cutoff: {cutoff}  →  Kept rows after cutoff: {after_trim} (trimmed {before_trim - after_trim})")
else:
    print("  No trimming applied.")

if df_cleaned.empty:
    raise ValueError("No data remains after trimming.")

# Date range used for both the archived raw file and the output file
start_date = df_cleaned["datetime"].min().strftime("%Y-%m-%d")
end_date = df_cleaned["datetime"].max().strftime("%Y-%m-%d")

# --- Combine raw source files into one archived file, then remove the originals ---
archive_dir.mkdir(parents=True, exist_ok=True)
archive_csv = archive_dir / f"{meter_name}_{start_date}_{end_date}_{freq}.csv"
combined_raw.to_csv(archive_csv, index=False)
for path in input_csvs:
    path.unlink()
print(f"\n✓ Archived combined raw data to: {archive_csv.name}")
print(f"✓ Removed {len(input_csvs)} processed source file(s) from {input_dir.name}/")

# Output file follows the same naming convention as the archived data file
output_csv = output_dir / f"{output_basename}_{start_date}_{end_date}_{freq}.csv"

# --- Format datetime for output ---
df_cleaned["datetime"] = df_cleaned["datetime"].dt.strftime("%Y-%m-%d %H:%M:%S")

print(f"✓ Converted datetime to YYYY-MM-DD HH:MM:SS format")

# Reorder columns: datetime, sensor_id, power_avg_kw, meter_name
df_cleaned = df_cleaned[["datetime", "sensor_id", "power_avg_kw", "meter_name"]]

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
