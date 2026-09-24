import subprocess

# Database connection and export targets
db_name = "uhm2023"
extracts_dir = "/home/campusenergy/shared/pv/extracts"
views = ["dates_pv_power", "dates_monthly_kwh"]

print("=" * 80)
print("EXTRACTING VIEWS FROM DATABASE")
print("=" * 80)

for view in views:
    export_path = f"{extracts_dir}/{view}.csv"
    copy_command = f"\\copy (SELECT * FROM pv.{view}) TO '{export_path}' CSV HEADER;"

    print(f"\nExtracting pv.{view}...")

    result = subprocess.run(
        ["psql", db_name, "-c", copy_command],
        capture_output=True,
        text=True,
    )

    if result.stdout.strip():
        print(result.stdout)

    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError(
            f"psql export of pv.{view} failed with exit code {result.returncode}"
        )

    print(f"✅ Extracted pv.{view} to: {export_path}")

print("\n" + "=" * 80)
print("✨ EXTRACTION COMPLETE!")
print("=" * 80)
