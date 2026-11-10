import io
import subprocess
import sys
from pathlib import Path

import pandas as pd

# Database connection and paths
db_name = "uhm2023"
project_root = Path(__file__).resolve().parent.parent
analysis_dir = project_root / "analysis"

TARGET_TABLE = "pv.monthly_kwh"
COLUMNS = ["month", "meter_name", "kwh", "note", "campus"]

# Usage:
#   python "5) upload_monthly_kwh.py"                 -> newest monthly_kwh_aggregated_*.csv in analysis/
#   python "5) upload_monthly_kwh.py" path/to/file.csv -> a specific file
#   add --yes to skip the confirmation prompt
args = [a for a in sys.argv[1:] if not a.startswith("--")]
skip_confirm = "--yes" in sys.argv


def run_psql(extra_args, label, input_text=None):
    result = subprocess.run(
        ["psql", db_name, "-v", "ON_ERROR_STOP=1", *extra_args],
        input=input_text,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError(f"psql {label} failed with exit code {result.returncode}")
    return result.stdout


def fetch_existing(df):
    """Return the set of (month, meter_name) from df that are already in the table."""
    meters = ", ".join("'" + m.replace("'", "''") + "'" for m in sorted(df["meter_name"].unique()))
    first_month = df["month"].min()
    query = (
        f"COPY (SELECT month::date AS month, meter_name FROM {TARGET_TABLE} "
        f"WHERE meter_name IN ({meters}) AND month >= '{first_month}') TO STDOUT CSV HEADER"
    )
    stdout = run_psql(["-c", query], "existing-rows check")
    existing = pd.read_csv(io.StringIO(stdout), dtype=str)
    return set(zip(existing["month"], existing["meter_name"]))


print("=" * 80)
print(f"UPLOADING MONTHLY KWH TO {TARGET_TABLE}")
print("=" * 80)

# --- Step 1: Find and load the CSV ---
if args:
    csv_path = Path(args[0])
else:
    candidates = sorted(analysis_dir.glob("monthly_kwh_aggregated_*.csv"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        print(f"\n⚠ No monthly_kwh_aggregated_*.csv found in {analysis_dir}")
        print("  Run 4) monthly_upload.py first.")
        raise SystemExit(1)
    csv_path = candidates[-1]

print(f"\n[1/4] Loading {csv_path.name}...")
df = pd.read_csv(csv_path, dtype={"meter_name": str, "note": str, "campus": str})

missing_cols = [c for c in COLUMNS if c not in df.columns]
if missing_cols:
    raise ValueError(f"CSV is missing column(s): {missing_cols}")
df = df[COLUMNS].copy()
df["month"] = pd.to_datetime(df["month"]).dt.strftime("%Y-%m-%d")
df["note"] = df["note"].fillna("")
print(f"✓ Loaded {len(df)} row(s) for {df['meter_name'].nunique()} meter(s)")

# --- Step 2: Sanity checks ---
print("\n[2/4] Checking the data...")
bad = df[["month", "meter_name", "kwh", "campus"]].isna().any(axis=1)
if bad.any():
    print(f"⚠ {int(bad.sum())} row(s) have blank month/meter_name/kwh/campus — fix these first:")
    print(df[bad].to_string(index=False))
    raise SystemExit(1)

dupes = df.duplicated(["month", "meter_name"], keep=False)
if dupes.any():
    print(f"⚠ Duplicate month/meter_name pairs in the file — fix these first:")
    print(df[dupes].to_string(index=False))
    raise SystemExit(1)
print("✓ No blanks or duplicates")

# --- Step 3: Skip anything already in the table ---
print(f"\n[3/4] Checking {TARGET_TABLE} for rows that already exist...")
existing = fetch_existing(df)
already = df.apply(lambda r: (r["month"], r["meter_name"]) in existing, axis=1)
if already.any():
    print(f"⏭ Skipping {int(already.sum())} row(s) already in the table:")
    for _, r in df[already].iterrows():
        print(f"    {r['meter_name']}  {r['month'][:7]}")
new_rows = df[~already].reset_index(drop=True)

if new_rows.empty:
    print("\nNothing to upload — every row is already in the table.")
    raise SystemExit(0)

print(f"\nRows to upload ({len(new_rows)}):")
print(new_rows.to_string(index=False))

if not skip_confirm:
    answer = input(f"\nUpload {len(new_rows)} row(s) to {TARGET_TABLE}? [y/N]: ").strip().lower()
    if answer != "y":
        print("Cancelled — nothing was uploaded.")
        raise SystemExit(0)

# --- Step 4: Upload in a single transaction ---
print(f"\n[4/4] Uploading to {TARGET_TABLE}...")
csv_text = new_rows.to_csv(index=False)
sql_script = (
    "BEGIN;\n"
    "CREATE TEMP TABLE stage_monthly_kwh "
    "(month date, meter_name text, kwh numeric, note text, campus text) ON COMMIT DROP;\n"
    "\\copy stage_monthly_kwh FROM STDIN WITH (FORMAT csv, HEADER true)\n"
    f"{csv_text}"
    "\\.\n"
    f"INSERT INTO {TARGET_TABLE} (month, meter_name, kwh, note, campus)\n"
    "SELECT s.month, s.meter_name, s.kwh, s.note, s.campus FROM stage_monthly_kwh s\n"
    f"WHERE NOT EXISTS (SELECT 1 FROM {TARGET_TABLE} m "
    "WHERE m.month = s.month AND m.meter_name = s.meter_name);\n"
    "COMMIT;\n"
)
stdout = run_psql(["-f", "-"], "upload", input_text=sql_script)
if stdout.strip():
    print(stdout.strip())

# --- Verify ---
now_existing = fetch_existing(new_rows)
found = sum((r["month"], r["meter_name"]) in now_existing for _, r in new_rows.iterrows())
print(f"\n✓ Verified {found} of {len(new_rows)} uploaded row(s) are now in {TARGET_TABLE}")
if found != len(new_rows):
    print("⚠ Some rows are missing — check the table before re-running.")

print("\n" + "=" * 80)
print("✨ UPLOAD COMPLETE!")
print("=" * 80)