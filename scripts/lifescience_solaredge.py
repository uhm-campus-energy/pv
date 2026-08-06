import os
import glob
import shutil
import pandas as pd
from pathlib import Path

# === Settings ===
folder_path = r"C:\Users\EileenPeppard\Desktop\2026-03-24_PV_data\life_science"
sensor_id_value = 6
meter_name = "life_science_pv"
output_filename = "life_science_pv_cleaned.csv"  # output file for life science pv array, sums the five inverters, converts to kW
output_dir = Path(r"C:\Users\EileenPeppard\Desktop\2026-03-24_PV_data\cleaned")
output_filepath = output_dir / output_filename

dates_csv_path = r"C:\Users\EileenPeppard\Desktop\2026-03-24_PV_data\dates_pv_power.csv"

# === Script === # This also divides the W by 1,000 to get kW
def read_one_csv(path):
    # Read with headers; files have 'DateTime' plus five inverter columns
    df = pd.read_csv(
        path,
        encoding="utf-8-sig",
        on_bad_lines="skip",
    )

    # Identify datetime column (supports 'DateTime' or 'Date & Time')
    dt_col = None
    for c in df.columns:
        if str(c).strip().lower() in ("datetime", "date & time"):
            dt_col = c
            break
    if dt_col is None:
        # Fallback to first column
        dt_col = df.columns[0]

    # Inverter power columns are all non-datetime columns
    inverter_cols = [c for c in df.columns if c != dt_col]

    # Clean and convert types
    df[dt_col] = df[dt_col].astype(str).str.strip()
    df[dt_col] = pd.to_datetime(df[dt_col], errors="coerce")

    # Convert inverter columns to numeric, filling NaNs with 0
    df[inverter_cols] = df[inverter_cols].apply(pd.to_numeric, errors="coerce").fillna(0)

    # Drop rows with invalid datetime
    df = df.dropna(subset=[dt_col])

    # Convert W → kW by summing inverter columns
    df["power_avg_kw"] = df[inverter_cols].sum(axis=1) / 1000.0

    # Standardize column names and add metadata
    df = df.rename(columns={dt_col: "datetime"})
    df["sensor_id"] = sensor_id_value
    df["meter_name"] = meter_name

    # Keep only needed columns
    df = df[["sensor_id", "meter_name", "datetime", "power_avg_kw"]]

    return df


def detect_frequency(combined_df):
    """
    Infer the dominant timestamp interval from the combined dataframe.
    Returns '15min' or '1h'.
    """
    sorted_dt = combined_df["datetime"].drop_duplicates().sort_values()
    if len(sorted_dt) < 2:
        return "unknown"

    diffs = sorted_dt.diff().dropna()
    median_diff = diffs.median()

    minutes = median_diff.total_seconds() / 60
    print(f"  Median timestamp interval: {minutes:.1f} minutes")

    if minutes <= 20:
        return "15min"
    else:
        return "1h"


def get_cutoff_timestamp(dates_csv, meter, freq):
    """
    Look up the appropriate cutoff timestamp from dates_pv_power.csv.
    Returns a pandas Timestamp or None if not found.
    """
    try:
        dates_df = pd.read_csv(dates_csv, encoding="utf-8-sig")
        # Strip whitespace from column names and string columns
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


def move_duplicate_files(csv_paths, folder):
    """
    Check for files with identical content (byte-for-byte duplicates).
    Move duplicates to a 'duplicates' subfolder, keeping the first occurrence.
    Returns the list of unique file paths.
    """
    import hashlib

    duplicates_dir = Path(folder) / "duplicates"
    seen_hashes = {}
    unique_paths = []

    for path in csv_paths:
        with open(path, "rb") as f:
            file_hash = hashlib.md5(f.read()).hexdigest()

        if file_hash in seen_hashes:
            # This file is a duplicate — move it
            duplicates_dir.mkdir(parents=True, exist_ok=True)
            dest = duplicates_dir / Path(path).name
            # Avoid overwrite collision in duplicates folder
            if dest.exists():
                stem = Path(path).stem
                suffix = Path(path).suffix
                dest = duplicates_dir / f"{stem}_dup{suffix}"
            shutil.move(path, dest)
            print(f"  ⚠ Duplicate of '{seen_hashes[file_hash]}' → moved to duplicates/: {Path(path).name}")
        else:
            seen_hashes[file_hash] = Path(path).name
            unique_paths.append(path)

    return unique_paths


def main():
    csv_paths = sorted(glob.glob(os.path.join(folder_path, "*.csv")))
    if not csv_paths:
        print(f"No CSV files found in:\n  {folder_path}")
        return

    # --- Step 1: Detect and move duplicate files ---
    print(f"Found {len(csv_paths)} CSV file(s). Checking for duplicates...")
    csv_paths = move_duplicate_files(csv_paths, folder_path)
    print(f"  {len(csv_paths)} unique file(s) remaining after duplicate check.\n")

    # --- Step 2: Read and combine ---
    parts = []
    for p in csv_paths:
        try:
            df = read_one_csv(p)
            parts.append(df)
            print(f"✔ Processed: {os.path.basename(p)} → {len(df)} rows")
        except Exception as e:
            print(f"⚠ Skipped {os.path.basename(p)}: {e}")

    if not parts:
        print("No valid rows found across files.")
        return

    combined = pd.concat(parts, ignore_index=True)

    # --- Step 3: Sort by timestamp ---
    combined = combined.sort_values("datetime").reset_index(drop=True)
    print(f"\nCombined rows (pre-dedup): {len(combined)}")

    # --- Step 4: Remove duplicate rows ---
    before = len(combined)
    combined = combined.drop_duplicates()
    after = len(combined)
    print(f"Rows after row-level dedup: {after} (removed {before - after})")

    # --- Step 5: Detect timestamp frequency ---
    print("\nDetecting timestamp frequency...")
    freq = detect_frequency(combined)
    print(f"  Detected frequency: {freq}")

    # --- Step 6: Look up cutoff and trim ---
    print(f"\nLooking up cutoff timestamp for meter '{meter_name}' (freq={freq})...")
    cutoff = get_cutoff_timestamp(dates_csv_path, meter_name, freq)

    if cutoff is not None:
        before_trim = len(combined)
        combined = combined[combined["datetime"] > cutoff].reset_index(drop=True)
        after_trim = len(combined)
        print(f"  Cutoff: {cutoff}  →  Kept rows after cutoff: {after_trim} (trimmed {before_trim - after_trim})")
    else:
        print("  No trimming applied.")

    if combined.empty:
        print("\n⚠ No data remains after trimming. Output file not written.")
        return

    # --- Step 7: Save output ---
    # Append _hr to filename if data is hourly
    if freq == "1h":
        final_filepath = output_dir / output_filename.replace(".csv", "_hr.csv")
    else:
        final_filepath = output_filepath

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = str(final_filepath)
    combined.to_csv(out_path, index=False, header=["sensor_id", "meter_name", "datetime", "power_avg_kw"])

    print("\n=== Done ===")
    print(f" Files processed  : {len(csv_paths)}")
    print(f" Rows before dedup: {before}")
    print(f" Rows after dedup : {after}")
    print(f" Frequency        : {freq}")
    print(f" Cutoff applied   : {cutoff}")
    print(f" Final rows       : {len(combined)}")
    print(f" Output written   : {out_path}")

if __name__ == "__main__":
    main()