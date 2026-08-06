import subprocess

# Database connection and export target
db_name = "uhm2023"
export_path = "/home/campusenergy/shared/pv/extracts/dates_pv_power.csv"
copy_command = (
    f"\\copy (SELECT * FROM pv.dates_pv_power) TO '{export_path}' CSV HEADER;"
)

print("=" * 80)
print("EXTRACTING pv.dates_pv_power FROM DATABASE")
print("=" * 80)

result = subprocess.run(
    ["psql", db_name, "-c", copy_command],
    capture_output=True,
    text=True,
)

if result.stdout.strip():
    print(result.stdout)

if result.returncode != 0:
    print(result.stderr)
    raise RuntimeError(f"psql export failed with exit code {result.returncode}")

print(f"\n✅ Extracted pv.dates_pv_power to: {export_path}")
print("\n" + "=" * 80)
print("✨ EXTRACTION COMPLETE!")
print("=" * 80)
