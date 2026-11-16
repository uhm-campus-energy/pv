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

# Tables to scan for unique (campus, meter_name) pairs
SOURCE_TABLES = [
    "pv.monthly_kwh",
    # "pv.pv_power",
    # "pv.pv_power_hr",
]

PV_INFO_TABLE = "pv.pv_info"

# Exact column order from pv_info.csv
PV_INFO_COLUMNS = [
    "sensor_id",
    "building_id",
    "customer",
    "dg_size_kw_stc",
    "invert_kw",
    "heco_id",
    "program",
    "contractor",
    "account",
    "meter",
    "date_intercon",
    "uh_person",
    "monitoring_portal",
    "ownership",
    "history",
    "comment",
    "timestamp_type",
    "resolution_per_hr",
    "building_complex_id",
    "$_per_kwh",
    "building_complex_name",
    "meter_name",
    "campus",
]

# Flags:
#   --no-refresh : reuse existing extracts instead of querying Postgres
#   --insert     : also insert the new rows directly into pv.pv_info
refresh = "--no-refresh" not in sys.argv
direct_insert = "--insert" in sys.argv


def run_psql(command, label):
    result = subprocess.run(
        ["psql", db_name, "-v", "ON_ERROR_STOP=1", "-c", command],
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.returncode != 0:
        print(result.stderr.strip())
        raise RuntimeError(f"psql command for {label} failed with exit code {result.returncode}")


def clean_str_series(s):
    return s.fillna("").astype(str).str.strip().str.strip('"')


print("=" * 80)
print("SYNCING NEW (CAMPUS, METER_NAME) PAIRS TO PV_INFO")
print("=" * 80)

# --- Step 1: Export current pv_info and distinct (campus, meter_name) pairs ---
pv_info_extract = extracts_dir / "pv_info_current.csv"
pairs_extract = extracts_dir / "distinct_campus_meters.csv"

if refresh:
    print(f"\nExporting current {PV_INFO_TABLE}...")
    run_psql(
        f"\\copy (SELECT * FROM {PV_INFO_TABLE} ORDER BY sensor_id) "
        f"TO '{remote_extracts_dir}/{pv_info_extract.name}' CSV HEADER;",
        PV_INFO_TABLE,
    )

    union_queries = " UNION ".join(
        f"SELECT DISTINCT campus, meter_name FROM {tbl} "
        f"WHERE campus IS NOT NULL AND meter_name IS NOT NULL"
        for tbl in SOURCE_TABLES
    )
    print(f"Querying distinct (campus, meter_name) pairs from {', '.join(SOURCE_TABLES)}...")
    run_psql(
        f"\\copy ({union_queries} ORDER BY campus, meter_name) "
        f"TO '{remote_extracts_dir}/{pairs_extract.name}' CSV HEADER;",
        "distinct campus/meter pairs",
    )

# Read as strings so IDs/integers (e.g., heco_id, $_per_kwh) aren't turned into floats
existing_df = pd.read_csv(pv_info_extract, dtype=str, keep_default_na=False)
pairs_df = pd.read_csv(pairs_extract, dtype=str, keep_default_na=False)

for col in ["campus", "meter_name"]:
    existing_df[col] = clean_str_series(existing_df[col])
    pairs_df[col] = clean_str_series(pairs_df[col])

pairs_df = pairs_df[(pairs_df["campus"] != "") & (pairs_df["meter_name"] != "")].drop_duplicates(
    subset=["campus", "meter_name"]
)

# --- Step 2: Identify pairs not yet in pv_info ---
existing_pairs = set(zip(existing_df["campus"], existing_df["meter_name"]))
new_pairs = pairs_df[
    ~pairs_df.apply(lambda r: (r["campus"], r["meter_name"]) in existing_pairs, axis=1)
].reset_index(drop=True)

if new_pairs.empty:
    print("\n✅ pv_info is already up to date — no new (campus, meter_name) pairs found.")
    raise SystemExit(0)

# --- Step 3: Build new pv_info rows (customer = meter_name) ---
max_sensor_id = pd.to_numeric(existing_df["sensor_id"], errors="coerce").max()
next_sensor_id = 1 if pd.isna(max_sensor_id) else int(max_sensor_id) + 1

new_rows = pd.DataFrame("", index=range(len(new_pairs)), columns=PV_INFO_COLUMNS)
new_rows["sensor_id"] = [str(next_sensor_id + i) for i in range(len(new_pairs))]
new_rows["customer"] = new_pairs["meter_name"]
new_rows["meter_name"] = new_pairs["meter_name"]
new_rows["campus"] = new_pairs["campus"]

updated_df = pd.concat([existing_df.reindex(columns=PV_INFO_COLUMNS, fill_value=""), new_rows], ignore_index=True)

print("\n" + "=" * 80)
print(f"NEW METERS TO ADD ({len(new_rows)})")
print("=" * 80)
print(new_rows[["sensor_id", "campus", "meter_name", "customer"]].to_string(index=False))

# --- Step 4: Save upload CSVs (and optionally insert into Postgres) ---
new_only_csv = analysis_dir / "pv_info_new_meters.csv"
full_updated_csv = analysis_dir / "pv_info_updated.csv"

new_rows.to_csv(new_only_csv, index=False)
updated_df.to_csv(full_updated_csv, index=False)

print(f"\n✅ Wrote {len(new_rows)} new row(s) to: {new_only_csv}")
print(f"✅ Wrote {len(updated_df)} total row(s) to: {full_updated_csv}")

if direct_insert:
    values_sql = ", ".join(
        f"({int(r['sensor_id'])}, "
        f"'{r['customer'].replace(chr(39), chr(39)*2)}', "
        f"'{r['meter_name'].replace(chr(39), chr(39)*2)}', "
        f"'{r['campus'].replace(chr(39), chr(39)*2)}')"
        for _, r in new_rows.iterrows()
    )
    insert_sql = (
        f"INSERT INTO {PV_INFO_TABLE} (sensor_id, customer, meter_name, campus) "
        f"VALUES {values_sql};"
    )
    run_psql(insert_sql, PV_INFO_TABLE)
    print(f"✅ Inserted {len(new_rows)} row(s) into {PV_INFO_TABLE}.")

print("\n" + "=" * 80)
print("✨ PV_INFO SYNC COMPLETE!")
print("=" * 80)