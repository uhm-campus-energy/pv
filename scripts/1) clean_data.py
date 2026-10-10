import subprocess
import sys
from pathlib import Path

import pandas as pd

# Cleans raw exports in input_data/<folder>/ and writes the cleaned files to outputs/.
# eGauge and AlsoEnergy sites (one raw CSV each) are cleaned here; WRC, Life Science,
# Law Clinic and Burns are handed to their own scripts.
#
# Usage:
#   python "1) clean.py" bachman           one site
#   python "1) clean.py" bachman wrc       several sites
#   python "1) clean.py" all               every site that has a new file

# File paths (relative to project root)
scripts_dir = Path(__file__).resolve().parent
project_root = scripts_dir.parent
input_dir = project_root / "input_data"
output_dir = project_root / "outputs"
dates_csv_path = project_root / "extracts" / "dates_pv_power.csv"

# Raw file types that count as "new data waiting" (Burns is a PDF or Excel file)
INPUT_SUFFIXES = (".csv", ".pdf", ".xlsx", ".xls")

# Column names in each portal's export
EGAUGE_TIME = "Date & Time"
ALSOENERGY_TIME = "Site Time"

# One entry per site. To add a site, add a line here.
#   folder:       subfolder of input_data/
#   script:       (special sites only) the site's own cleaning script in scripts/
#   meter_name:   must match meter_name in dates_pv_power.csv
#   time_column:  timestamp column in the raw export
#   power_column: PV power column (kW) in the raw export
#   flip_sign:    True if the export reports generation as negative
#   output_name:  prefix of the cleaned file in outputs/
SITES = {
    "bachman": dict(folder="bachman_egauge", meter_name="bachman_pv", sensor_id=14,
                    time_column=EGAUGE_TIME, power_column="Generation [kW]",
                    flip_sign=False, output_name="bachman_pv"),
    "gym": dict(folder="gym1,2_egauge", meter_name="gyms1,2_pv", sensor_id=13,
                time_column=EGAUGE_TIME, power_column="Generation [kW]",
                flip_sign=False, output_name="gyms_1_2_pv"),
    "parkingphase1": dict(folder="parkingphase1_egauge", meter_name="parking_phase1_pv", sensor_id=12,
                          time_column=EGAUGE_TIME, power_column="Generation [kW]",
                          flip_sign=False, output_name="parkingphase1_pv"),
    "frog1": dict(folder="frog1_egauge", meter_name="frog1_pv", sensor_id=3,
                  time_column=EGAUGE_TIME, power_column="pv [kW]",
                  flip_sign=True, output_name="frog1_pv"),
    "frog2": dict(folder="frog2_egauge", meter_name="frog2_pv", sensor_id=4,
                  time_column=EGAUGE_TIME, power_column="PV [kW]",
                  flip_sign=True, output_name="frog2_pv"),

    # the power column changed name from Production meter active power Kilowatts to Production meter active power (kW)
    "dancestudio": dict(folder="dancestudio_alsoenergy", meter_name="dance_pv", sensor_id=1,
                        time_column=ALSOENERGY_TIME, power_column="Production meter active power (kW)",
                        flip_sign=False, output_name="dance_pv"),
    "parkingphase2": dict(folder="parkingphase2_alsoenergy", meter_name="parking_phase2_pv", sensor_id=7,
                          time_column=ALSOENERGY_TIME, power_column="PV Inverter active power (kW)",
                          flip_sign=False, output_name="parkingphase2_pv"),
    "gartley": dict(folder="gartley_alsoenergy", meter_name="gartley_pv", sensor_id=5,
                    time_column=ALSOENERGY_TIME, power_column="PV Inverter active power (kW)",
                    flip_sign=False, output_name="gartley_pv"),
    "pbrc": dict(folder="pbrc_alsoenergy", meter_name="pbrc_pv", sensor_id=8,
                 time_column=ALSOENERGY_TIME, power_column="PV Inverter active power (kW)",
                 flip_sign=False, output_name="pbrc_pv"),

    # for these sites, the cleaning is done by a separate script (not this one) since the format is significantly different
    "wrc":         dict(folder="wrc_sunnyportal",       script="wrc_sunnyportal.py"),
    "lifescience": dict(folder="lifescience_solaredge", script="lifescience_solaredge.py"),
    "lawclinic":   dict(folder="lawclinic_solaredge",   script="lawclinic_solaredge.py"),
    "burns":       dict(folder="burns_monthly",         script="burns_monthly_kwh.py"),
}

def detect_frequency(df):
    sorted_dt = df['datetime'].drop_duplicates().sort_values()
    if len(sorted_dt) < 2:
        return "unknown"
    diffs = sorted_dt.diff().dropna()
    median_diff = diffs.median()
    minutes = median_diff.total_seconds() / 60
    print(f"  Median timestamp interval: {minutes:.1f} minutes")
    return "15min" if minutes <= 20 else "1hr"


def get_cutoff_timestamp(dates_csv, meter, freq):
    try:
        dates_df = pd.read_csv(dates_csv, encoding="utf-8-sig")
        dates_df.columns = [c.strip().strip('"') for c in dates_df.columns]
        for col in dates_df.columns:
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


def run_site_script(site):
    """Run a site's own cleaning script (WRC, Life Science, Law Clinic, Burns)."""
    script = scripts_dir / site["script"]
    print("\n" + "=" * 80)
    print(f"RUNNING {site['script']} ({site['folder']})")
    print("=" * 80)
    result = subprocess.run([sys.executable, str(script)])
    if result.returncode != 0:
        raise RuntimeError(f"{site['script']} exited with code {result.returncode}")


def has_waiting_files(site):
    folder = input_dir / site["folder"]
    return folder.is_dir() and any(
        f.is_file() and f.suffix.lower() in INPUT_SUFFIXES for f in folder.iterdir()
    )


def clean_site(site):
    site_dir = input_dir / site["folder"]
    meter_name = site["meter_name"]

    print("\n" + "=" * 80)
    print(f"CLEANING {meter_name.upper()} ({site['folder']})")
    print("=" * 80)

    input_csvs = list(site_dir.glob("*.csv"))
    if len(input_csvs) != 1:
        raise FileNotFoundError(
            f"Expected exactly one CSV in {site_dir}, found {len(input_csvs)}: {input_csvs}"
        )
    input_csv = input_csvs[0]

    # Load the data
    df = pd.read_csv(input_csv)
    print(f"\n✓ Loaded {input_csv.name}: {df.shape[0]} rows × {df.shape[1]} columns")
    print(f"  Original columns: {list(df.columns)}")

    missing = [c for c in (site["time_column"], site["power_column"]) if c not in df.columns]
    if missing:
        raise KeyError(f"Column(s) {missing} not found in {input_csv.name} — has the export format changed?")

    # Keep only the columns we need and rename them
    df_cleaned = df[[site["time_column"], site["power_column"]]].copy()
    df_cleaned = df_cleaned.rename(columns={
        site["time_column"]: 'datetime',
        site["power_column"]: 'power_avg_kw',
    })

    # Add new columns with specified values
    df_cleaned['sensor_id'] = site["sensor_id"]
    df_cleaned['meter_name'] = meter_name

    if site["flip_sign"]:
        df_cleaned['power_avg_kw'] = df_cleaned['power_avg_kw'] * -1
        print("\n✓ Multiplied power_avg_kw by -1 to change sign")

    # Convert datetime column to pandas datetime for sorting/trimming
    df_cleaned['datetime'] = pd.to_datetime(df_cleaned['datetime'])

    # --- Sort by timestamp ---
    df_cleaned = df_cleaned.sort_values('datetime').reset_index(drop=True)
    print(f"\n✓ Sorted rows by timestamp")

    # --- Detect timestamp frequency ---
    print("\nDetecting timestamp frequency...")
    freq = detect_frequency(df_cleaned)
    print(f"  Detected frequency: {freq}")

    # --- Look up cutoff timestamp and trim ---
    print(f"\nLooking up cutoff timestamp for meter '{meter_name}' (freq={freq})...")
    cutoff = get_cutoff_timestamp(dates_csv_path, meter_name, freq)

    if cutoff is not None:
        before_trim = len(df_cleaned)
        df_cleaned = df_cleaned[df_cleaned['datetime'] > cutoff].reset_index(drop=True)
        after_trim = len(df_cleaned)
        print(f"  Cutoff: {cutoff}  →  Kept rows after cutoff: {after_trim} (trimmed {before_trim - after_trim})")
    else:
        print("  No trimming applied.")

    if df_cleaned.empty:
        print(f"\n⚠ No rows after the cutoff — everything in {input_csv.name} is already in the database.")
        print("  Nothing written. Move the raw file to data_archive/ yourself if you don't need it.")
        return

    # Rename the input file to <subfolder>_<start-date>_<end-date>_<freq>.csv
    start_date = df_cleaned['datetime'].min().strftime('%Y-%m-%d')
    end_date = df_cleaned['datetime'].max().strftime('%Y-%m-%d')
    new_input_csv = site_dir / f"{site_dir.name}_{start_date}_{end_date}_{freq}.csv"
    if input_csv != new_input_csv:
        input_csv.rename(new_input_csv)
        print(f"\n✓ Renamed input file to: {new_input_csv.name}")

    # Output file follows the same naming convention as the data file
    output_dir.mkdir(exist_ok=True)
    output_csv = output_dir / f"{site['output_name']}_cleaned_{start_date}_{end_date}_{freq}.csv"

    # --- Format datetime for output ---
    df_cleaned['datetime'] = df_cleaned['datetime'].dt.strftime('%Y-%m-%d %H:%M:%S')
    print(f"\n✓ Converted datetime to YYYY-MM-DD HH:MM:SS format")

    # Reorder columns: datetime, sensor_id, power_avg_kw, meter_name
    df_cleaned = df_cleaned[['datetime', 'sensor_id', 'power_avg_kw', 'meter_name']]

    print(f"\n✓ Cleaned data: {df_cleaned.shape[0]} rows × {df_cleaned.shape[1]} columns")
    print("\n  Sample of cleaned data:")
    print(df_cleaned.head(10).to_string(index=False))

    df_cleaned.to_csv(output_csv, index=False)
    print(f"\n✅ Cleaned data saved to: {output_csv}")


# --- Pick which sites to run ---
requested = [a.lower() for a in sys.argv[1:]]
if not requested:
    print('Usage: python "1) clean.py" <site> [<site> ...]  or  all')
    print(f"Sites: {', '.join(SITES)}")
    sys.exit(1)

unknown = [s for s in requested if s != "all" and s not in SITES]
if unknown:
    print(f"Unknown site(s): {', '.join(unknown)}")
    print(f"Sites: {', '.join(SITES)}")
    sys.exit(1)

if "all" in requested:
    # Only sites with a raw file waiting; empty folders are skipped
    names = [n for n, s in SITES.items() if has_waiting_files(s)]
    skipped = [n for n in SITES if n not in names]
    if skipped:
        print(f"No new file for: {', '.join(skipped)} — skipped")
else:
    names = requested

# Keep going if one site fails, and list the failures at the end
failed = []
for name in names:
    try:
        if "script" in SITES[name]:
            run_site_script(SITES[name])
        else:
            clean_site(SITES[name])
    except Exception as e:
        print(f"\n❌ {name} failed: {e}")
        failed.append(name)

print("\n" + "=" * 80)
print(f"✨ CLEANING COMPLETE — {len(names) - len(failed)} of {len(names)} site(s) cleaned")
if failed:
    print(f"❌ Failed: {', '.join(failed)}")
print("=" * 80)
if failed:
    sys.exit(1)
