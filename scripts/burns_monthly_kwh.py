import pandas as pd
from pathlib import Path

# File paths (relative to project root)
project_root = Path(__file__).resolve().parent.parent
input_dir = project_root / "data" / "burns_monthly"
input_files = [
    f for f in input_dir.iterdir()
    if f.is_file() and f.suffix.lower() in (".pdf", ".xlsx", ".xls")
]
if len(input_files) != 1:
    raise FileNotFoundError(
        f"Expected exactly one PDF or Excel file in {input_dir}, found {len(input_files)}: {input_files}"
    )
input_file = input_files[0]
output_dir = project_root / "outputs"
output_dir.mkdir(exist_ok=True)
dates_csv_path = project_root / "extracts" / "dates_monthly_kwh.csv"

meter_name = "burns_pv"  # matches dates_monthly_kwh.csv
fiscal_year = 2026  # Fiscal Year 2026 = October 2025 through September 2026

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


print("=" * 80)
print("CLEANING BURNS HALL MONTHLY kWh DATA")
print("=" * 80)


# --- Read every table in the file as a list of rows (each row a list of cell strings) ---
def read_pdf_rows(path):
    import pdfplumber

    rows = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for row in table:
                    # pdfplumber pads merged cells with None — drop them so columns line up
                    rows.append([str(c).strip() for c in row if c is not None])
    return rows


def read_excel_rows(path):
    rows = []
    sheets = pd.read_excel(path, sheet_name=None, header=None)
    for sheet in sheets.values():
        for row in sheet.itertuples(index=False):
            rows.append(["" if pd.isna(c) else str(c).strip() for c in row])
    return rows


if input_file.suffix.lower() == ".pdf":
    rows = read_pdf_rows(input_file)
else:
    rows = read_excel_rows(input_file)
print(f"\n✓ Loaded {input_file.name}: {len(rows)} table rows")


# --- Find the "Fiscal Year NNNN" table and pull the PV kWh column ---
def parse_fiscal_year_table(rows, fiscal_year):
    target = f"fiscal year {fiscal_year}"
    in_table = False
    kwh_col = None
    records = []

    for row in rows:
        cells_lower = [c.lower() for c in row]
        first = cells_lower[0] if cells_lower else ""

        if not in_table:
            if any(target in c for c in cells_lower):
                in_table = True
            continue

        # Stop at the next fiscal year table or the Total row
        if any(c.startswith("fiscal year") for c in cells_lower) or "total" in cells_lower:
            break

        if kwh_col is None:
            if "pv kwh" in cells_lower:
                kwh_col = cells_lower.index("pv kwh")
            continue

        if first not in MONTHS:
            continue

        month_num = MONTHS[first]
        year = fiscal_year - 1 if month_num >= 10 else fiscal_year
        raw_kwh = row[kwh_col].replace(",", "") if kwh_col < len(row) else ""
        kwh = pd.to_numeric(raw_kwh, errors="coerce")
        if pd.isna(kwh):
            print(f"  {row[0]} {year}: no PV kWh value — skipped")
            continue

        records.append({
            "month": pd.Timestamp(year=year, month=month_num, day=1),
            "meter_name": meter_name,
            "kwh": kwh,
        })

    if not in_table:
        raise ValueError(f"Could not find a 'Fiscal Year {fiscal_year}' table in {input_file.name}")
    if kwh_col is None:
        raise ValueError(f"Could not find a 'PV kWh' column in the Fiscal Year {fiscal_year} table")

    return pd.DataFrame(records, columns=["month", "meter_name", "kwh"])


print(f"\nParsing 'Fiscal Year {fiscal_year}' table...")
df_cleaned = parse_fiscal_year_table(rows, fiscal_year)
print(f"  Found {len(df_cleaned)} month(s) with PV kWh values")


# --- Look up the last loaded month and trim ---
def get_cutoff_month(dates_csv, meter):
    try:
        dates_df = pd.read_csv(dates_csv, encoding="utf-8-sig")
        dates_df.columns = [c.strip().strip('"') for c in dates_df.columns]
        for col in dates_df.columns:
            dates_df[col] = dates_df[col].astype(str).str.strip().str.strip('"')

        row = dates_df[dates_df['meter_name'] == meter]
        if row.empty:
            print(f"⚠ meter_name '{meter}' not found in dates CSV — no trimming applied.")
            return None

        val = row.iloc[0]['end_monthly_kwh']
        if pd.isna(val) or str(val).strip().lower() in ("", "nan", "none"):
            print(f"  'end_monthly_kwh' is empty for '{meter}' — no trimming applied.")
            return None

        cutoff = pd.to_datetime(val, errors="coerce")
        if pd.isna(cutoff):
            print(f"  Could not parse 'end_monthly_kwh' value '{val}' — no trimming applied.")
            return None

        return cutoff

    except Exception as e:
        print(f"⚠ Could not read dates CSV: {e}")
        return None


print(f"\nLooking up last loaded month for meter '{meter_name}'...")
cutoff = get_cutoff_month(dates_csv_path, meter_name)

if cutoff is not None:
    before_trim = len(df_cleaned)
    df_cleaned = df_cleaned[df_cleaned['month'] > cutoff].reset_index(drop=True)
    after_trim = len(df_cleaned)
    print(f"  Cutoff: {cutoff.date()}  →  Kept months after cutoff: {after_trim} (trimmed {before_trim - after_trim})")
else:
    print("  No trimming applied.")

if df_cleaned.empty:
    print("\n⚠ No new months to output.")
    raise SystemExit(0)

start_date = df_cleaned['month'].min().strftime('%Y-%m-%d')
end_date = df_cleaned['month'].max().strftime('%Y-%m-%d')
output_csv = output_dir / f"burns_pv_monthly_kwh_{start_date}_{end_date}.csv"

# --- Format month for output ---
df_cleaned['month'] = df_cleaned['month'].dt.strftime('%Y-%m-%d')

print(f"\n✓ Cleaned data: {df_cleaned.shape[0]} rows × {df_cleaned.shape[1]} columns")
print("\n  Cleaned data:")
print(df_cleaned.to_string(index=False))

df_cleaned.to_csv(output_csv, index=False)

print(f"\n✅ Cleaned data saved to: {output_csv}")
print("\n" + "=" * 80)
print("✨ CLEANING COMPLETE!")
print("=" * 80)
