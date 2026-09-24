import csv
import subprocess
import sys
from pathlib import Path

# Database connection and remote path configuration
db_name = "uhm2023"
project_root = Path(__file__).resolve().parent.parent
data_dir = project_root / "data"
outputs_dir = project_root / "outputs"
remote_outputs_dir = "/home/campusenergy/shared/pv/outputs"

# Destination table by detected resolution
TABLE_BY_FREQ = {
    "15min": "pv.pv_power",
    "1hr": "pv.pv_power_hr",
}

# meter_name (as written in the cleaned CSV) -> data subfolder name
METER_TO_FOLDER = {
    "dance_pv": "dancestudio_alsoenergy",
    "frog1_pv": "frog1_egauge",
    "frog2_pv": "frog2_egauge",
    "gartley_pv": "gartley_alsoenergy",
    "life_science_pv": "lifescience_solaredge",
    "parking_phase2_pv": "parkingphase2_alsoenergy",
    "pbrc_pv": "pbrc_alsoenergy",
    "law_clinic_pv": "lawclinic_solaredge",
    "warrior_pv": "wrc_sunnyportal",
    "parking_phase1_pv": "parkingphase1_egauge",
    "gyms1,2_pv": "gym1,2_egauge",
    "bachman_pv": "bachman_egauge",
    "burns_pv": "burns_monthly",
}

POWER_COLUMNS = "datetime, sensor_id, power_avg_kw, meter_name"

# Monthly kWh outputs (e.g. burns_pv_monthly_kwh_<start>_<end>.csv)
MONTHLY_PATTERN = "*_monthly_kwh_*.csv"
MONTHLY_TABLE = "pv.monthly"
MONTHLY_COLUMNS = "month, meter_name, kwh"

# Input file types moved to the archive after a successful upload
INPUT_SUFFIXES = (".csv", ".pdf", ".xlsx", ".xls")


def upload_file(csv_path, table, columns):
    remote_path = f"{remote_outputs_dir}/{csv_path.name}"
    copy_command = (
        f"\\copy {table}({columns}) "
        f"FROM '{remote_path}' CSV HEADER;"
    )

    result = subprocess.run(
        ["psql", db_name, "-c", copy_command],
        capture_output=True,
        text=True,
    )

    if result.stdout.strip():
        print(result.stdout)

    if result.returncode != 0:
        print(result.stderr)
        print(f"❌ Upload failed for {csv_path.name} (exit code {result.returncode})")
        return False

    print(f"✅ Uploaded {csv_path.name} to {table}")
    return True


def get_meter_name(csv_path):
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        row = next(csv.DictReader(f))
        return row["meter_name"]


def archive_input_files(folder_name):
    folder = data_dir / folder_name
    archive_dir = folder / "archive"
    archive_dir.mkdir(exist_ok=True)
    for input_file in folder.iterdir():
        if not input_file.is_file() or input_file.suffix.lower() not in INPUT_SUFFIXES:
            continue
        destination = archive_dir / input_file.name
        input_file.replace(destination)
        print(f"  ↳ Archived {folder_name}/{input_file.name}")


def upload_and_archive(csv_path, table, columns):
    if not upload_file(csv_path, table, columns):
        return False

    meter_name = get_meter_name(csv_path)
    folder_name = METER_TO_FOLDER.get(meter_name)
    if folder_name:
        archive_input_files(folder_name)
    else:
        print(f"  ⚠ No data subfolder mapped for meter_name '{meter_name}' — input file not archived.")

    csv_path.unlink()
    print(f"  ↳ Deleted {csv_path.name} from outputs")
    return True


print("=" * 80)
print("UPLOADING OUTPUT FILES TO DATABASE")
print("=" * 80)

any_success = False

for freq, table in TABLE_BY_FREQ.items():
    matches = sorted(outputs_dir.glob(f"*_{freq}.csv"))
    print(f"\nFound {len(matches)} file(s) for {freq} → {table}")
    for csv_path in matches:
        if upload_and_archive(csv_path, table, POWER_COLUMNS):
            any_success = True

matches = sorted(outputs_dir.glob(MONTHLY_PATTERN))
print(f"\nFound {len(matches)} file(s) for monthly kWh → {MONTHLY_TABLE}")
for csv_path in matches:
    if upload_and_archive(csv_path, MONTHLY_TABLE, MONTHLY_COLUMNS):
        any_success = True

print("\n" + "=" * 80)
print("✨ UPLOAD COMPLETE!")
print("=" * 80)

# Refresh the dates extract so the next cleaning run has up-to-date cutoffs
if any_success:
    get_dates_script = Path(__file__).resolve().parent / "00_refresh_dates.py"
    print("\nRe-running 00_refresh_dates.py to refresh the dates extracts...")
    subprocess.run([sys.executable, str(get_dates_script)], check=True)
