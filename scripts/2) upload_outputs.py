import csv
import subprocess
import sys
from pathlib import Path

# archive_naming.py lives in scripts/move_old_archived_data/
sys.path.insert(0, str(Path(__file__).resolve().parent / "move_old_archived_data"))
from archive_naming import archive_destination, site_name

print(f"Running {Path(__file__).resolve()}")

# Database connection and remote path configuration
db_name = "uhm2023"
project_root = Path(__file__).resolve().parent.parent
data_dir = project_root / "input_data"
archive_dir = project_root / "data_archive"
outputs_dir = project_root / "outputs"
remote_outputs_dir = "/home/campusenergy/shared/pv/outputs"

# Destination table by detected resolution
TABLE_BY_FREQ = {
    "15min": "pv.pv_power",
    "1hr": "pv.pv_power_hr",
}

# Staging table each destination table is loaded through (created automatically if missing).
# Each file is copied into the staging table first, checked, then inserted into the real table
# with ON CONFLICT (datetime, meter_name) DO NOTHING, so re-uploading rows that already exist is harmless.
STAGING_TABLE = {
    "pv.pv_power": "pv.pv_power_staging",
    "pv.pv_power_hr": "pv.pv_power_hr_staging",
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

POWER_COLUMNS = "datetime, power_avg_kw, meter_name"

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


def stage_and_insert(csv_path, table, staging, columns):
    """Load a cleaned CSV into the staging table, then insert new rows into `table`.

    Everything runs in one psql session inside one transaction, so if any step fails
    nothing is changed and the staging table is left as it was.
    """
    remote_path = f"{remote_outputs_dir}/{csv_path.name}"
    sql = f"""
BEGIN;
CREATE TABLE IF NOT EXISTS {staging} (
    datetime timestamp without time zone,
    power_avg_kw double precision,
    meter_name varchar
);
TRUNCATE {staging};
\\copy {staging}({columns}) FROM '{remote_path}' CSV HEADER
DO $$
DECLARE bad_meters text;
BEGIN
    SELECT string_agg(DISTINCT s.meter_name, ', ') INTO bad_meters
    FROM {staging} s
    LEFT JOIN pv.pv_info i ON i.meter_name = s.meter_name
    WHERE i.meter_name IS NULL;
    IF bad_meters IS NOT NULL THEN
        RAISE EXCEPTION 'meter_name not found in pv.pv_info: %', bad_meters;
    END IF;
END $$;
WITH ins AS (
    INSERT INTO {table} ({columns})
    SELECT {columns} FROM {staging}
    ON CONFLICT (datetime, meter_name) DO NOTHING
    RETURNING 1
)
SELECT (SELECT count(*) FROM {staging}) AS rows_in_file,
       (SELECT count(*) FROM {staging} s JOIN {table} t
            ON t.datetime = s.datetime AND t.meter_name = s.meter_name) AS already_in_table,
       (SELECT count(*) FROM ins) AS inserted;
COMMIT;
"""

    result = subprocess.run(
        ["psql", "-X", "-q", "-t", "-A", "-F", "|", "-v", "ON_ERROR_STOP=1", "-d", db_name, "-f", "-"],
        input=sql,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(result.stderr)
        print(f"❌ Upload failed for {csv_path.name} (exit code {result.returncode}) — nothing was changed")
        return False

    try:
        last_line = [line for line in result.stdout.splitlines() if line.strip()][-1]
        rows_in_file, already_in_table, inserted = (int(x) for x in last_line.split("|"))
    except (IndexError, ValueError):
        print(result.stdout)
        print(f"⚠ Uploaded {csv_path.name} to {table}, but could not read the row counts above")
        return True

    print(f"✅ Uploaded {csv_path.name} to {table} via {staging}: "
          f"{rows_in_file} rows in file, {already_in_table} already in table, {inserted} inserted")
    if already_in_table:
        print(f"  ⚠ {already_in_table} rows were already in {table} and were skipped")
    if inserted + already_in_table != rows_in_file:
        print(f"  ⚠ {rows_in_file - inserted - already_in_table} rows were duplicated within the file and skipped")
    return True


def get_meter_name(csv_path):
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        row = next(csv.DictReader(f))
        return row["meter_name"]


def archive_input_files(folder_name):
    # input_data/<folder>/<file> -> data_archive/<site>/<site>_<start>_<end>_<freq>.csv
    folder = data_dir / folder_name
    if not folder.is_dir():
        print(f"  ⚠ input_data/{folder_name}/ not found — nothing archived.")
        return
    archived = 0
    for input_file in sorted(folder.iterdir()):
        if not input_file.is_file() or input_file.suffix.lower() not in INPUT_SUFFIXES:
            continue
        # Never overwrites an earlier archived file with the same name
        destination = archive_destination(archive_dir, folder_name, input_file.name)
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            input_file.rename(destination)
        except OSError as e:  # e.g. file open in Excel or locked by OneDrive
            # The data is already uploaded, so carry on — just move this file by hand later
            print(f"  ⚠ Could not archive {folder_name}/{input_file.name}: {e}")
            print(f"    Move it to data_archive/{destination.parent.name}/ yourself before cleaning this site again.")
            continue
        archived += 1
        print(f"  ↳ Archived {folder_name}/{input_file.name} → data_archive/{destination.parent.name}/{destination.name}")
    if archived == 0:
        print(f"  ⚠ No raw files found in input_data/{folder_name}/ — nothing to archive.")


def upload_and_archive(csv_path, table, columns, staging=None):
    # With a staging table the file is loaded through it; without one it is copied straight in
    if staging:
        uploaded = stage_and_insert(csv_path, table, staging, columns)
    else:
        uploaded = upload_file(csv_path, table, columns)
    if not uploaded:
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
        if upload_and_archive(csv_path, table, POWER_COLUMNS, staging=STAGING_TABLE[table]):
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
    get_dates_script = Path(__file__).resolve().parent / "0) refresh_dates.py"
    print("\nRe-running 0) refresh_dates.py to refresh the dates extracts...")
    subprocess.run([sys.executable, str(get_dates_script)], check=True)