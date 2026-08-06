import os, re, csv, shutil, hashlib
from datetime import datetime
from typing import Optional, List
from pathlib import Path
import pandas as pd

# === SETTINGS ===
FOLDER = r"C:\Users\EileenPeppard\Desktop\2026-03-24_PV_data\warrior_missing"
EXPORT_FOLDER = r"C:\Users\EileenPeppard\Desktop\2026-03-24_PV_data\cleaned"
OUTPUT = os.path.join(EXPORT_FOLDER, "wrc_pv_missing_cleaned.csv")
dates_csv_path = r"C:\Users\EileenPeppard\Desktop\2026-03-24_PV_data\dates_pv_power.csv"
SENSOR_ID = 11
DAY_FIRST = True  # <-- we parse as DD/MM (e.g., 04/02 = 4 Feb)

FILE_RE = re.compile(
    r"Analysis_(\d{4})_(\d{2})_(\d{2})_(\d{4})_(\d{2})_(\d{2})\.csv$", re.IGNORECASE
)
meter_name = "warrior_pv"

def year_from_filename(fname: str) -> Optional[int]:
    m = FILE_RE.search(os.path.basename(fname))
    return int(m.group(1)) if m else None  # start year

def clean_cell(s: Optional[str]) -> str:
    if s is None:
        return ""
    s = s.replace("\u00A0", " ")  # NBSP -> space
    s = s.strip()
    if s.startswith("="):
        s = s[1:].strip()
    s = s.replace('""', '"')
    while len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1].strip()
    s = re.sub(r"\s+", " ", s)
    return s

def normalize_ddmm_slash(s: str) -> str:
    return re.sub(r"^(\d{1,2})/(\d{1,2})/\s+(?=\d)", r"\1/\2 ", s)

def parse_timestamp_ddmm(text: str, default_year: Optional[int]) -> Optional[datetime]:
    s = clean_cell(text)
    s = normalize_ddmm_slash(s)
    m = re.match(
        r"^(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\s+(\d{1,2}):(\d{2})\s*([AP]M)$",
        s, flags=re.I
    )
    if not m:
        return None
    dd, mm, yy, hr, mn, ampm = m.groups()
    dd, mm, hr, mn = map(int, [dd, mm, hr, mn])
    ampm = ampm.upper()

    if yy:
        yy = int(yy)
        if yy < 100:
            yy += 2000 if yy < 70 else 1900
    else:
        if default_year is None:
            return None
        yy = default_year

    if ampm == "AM" and hr == 12:
        hr = 0
    elif ampm == "PM" and hr != 12:
        hr += 12

    try:
        return datetime(yy, mm if not DAY_FIRST else mm, dd if not DAY_FIRST else dd, hr, mn)
    except ValueError:
        return None

def parse_kw(text: str) -> Optional[float]:
    s = clean_cell(text)
    if s == "" or s.lower() in {"na", "null", "none"}:
        return None
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1]
    s = s.replace(",", "").replace(" ", "")
    s = re.sub(r"[^0-9.+-]", "", s)
    if s in {"", "+", "-", ".", "+.", "-."}:
        return None
    try:
        val = float(s)
        return -val if neg else val
    except ValueError:
        return None

def sniff_delimiter(first_chunk: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(first_chunk, delimiters=[",", ";", "\t"])
        return dialect.delimiter
    except Exception:
        return ";" if ";" in first_chunk else ("," if "," in first_chunk else "\t")


def move_duplicate_files(folder: str) -> List[str]:
    """
    Check for files with identical content (byte-for-byte duplicates).
    Move duplicates to a 'duplicates' subfolder, keeping the first occurrence.
    Returns the list of unique file paths.
    """
    duplicates_dir = Path(folder) / "duplicates"
    seen_hashes = {}
    unique_paths = []

    csv_files = sorted([f for f in os.listdir(folder) if f.lower().endswith(".csv")])
    for fname in csv_files:
        path = os.path.join(folder, fname)
        with open(path, "rb") as f:
            file_hash = hashlib.md5(f.read()).hexdigest()

        if file_hash in seen_hashes:
            duplicates_dir.mkdir(parents=True, exist_ok=True)
            dest = duplicates_dir / fname
            if dest.exists():
                stem = Path(fname).stem
                suffix = Path(fname).suffix
                dest = duplicates_dir / f"{stem}_dup{suffix}"
            shutil.move(path, dest)
            print(f"  ⚠ Duplicate of '{seen_hashes[file_hash]}' → moved to duplicates/: {fname}")
        else:
            seen_hashes[file_hash] = fname
            unique_paths.append(path)

    return unique_paths


def detect_frequency(df: pd.DataFrame) -> str:
    """Infer the dominant timestamp interval. Returns '15min' or '1h'."""
    sorted_dt = df["datetime"].drop_duplicates().sort_values()
    if len(sorted_dt) < 2:
        return "unknown"
    diffs = sorted_dt.diff().dropna()
    median_diff = diffs.median()
    minutes = median_diff.total_seconds() / 60
    print(f"  Median timestamp interval: {minutes:.1f} minutes")
    return "15min" if minutes <= 20 else "1h"


def get_cutoff_timestamp(dates_csv: str, meter: str, freq: str) -> Optional[pd.Timestamp]:
    """Look up the appropriate cutoff timestamp from dates_pv_power.csv."""
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


# === Step 1: Detect and move duplicate files ===
print(f"Checking for duplicate files in: {FOLDER}")
unique_paths = move_duplicate_files(FOLDER)
print(f"  {len(unique_paths)} unique file(s) remaining after duplicate check.\n")

# === Step 2: Read and parse all unique files ===
rows: List[dict] = []
for path in unique_paths:
    fname = os.path.basename(path)
    default_year = year_from_filename(fname)

    with open(path, "r", encoding="utf-8-sig", errors="ignore", newline="") as fh:
        sample = fh.read(4096)
        delim = sniff_delimiter(sample)
        fh.seek(0)
        reader = csv.reader(fh, delimiter=delim)
        for row in reader:
            if not row:
                continue
            ts_raw = row[0]
            dt = parse_timestamp_ddmm(ts_raw, default_year)
            if dt is None:
                continue
            kw = parse_kw(row[1] if len(row) > 1 else "")
            rows.append({"sensor_id": SENSOR_ID, "meter_name": meter_name, "datetime": dt, "power_avg_kw": kw})

# === Step 3: Build DataFrame and sort by timestamp ===
df = pd.DataFrame(rows, columns=["sensor_id", "meter_name", "datetime", "power_avg_kw"])
if df.empty:
    df = pd.DataFrame(columns=["sensor_id", "meter_name", "datetime", "power_avg_kw"])
    print("⚠ No valid rows found. Output file not written.")
else:
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)
    print(f"Combined rows (pre-dedup): {len(df)}")

    # === Step 4: Remove duplicate rows ===
    before = len(df)
    df = df.drop_duplicates()
    after = len(df)
    print(f"Rows after row-level dedup: {after} (removed {before - after})")

    # === Step 5: Detect timestamp frequency ===
    print("\nDetecting timestamp frequency...")
    freq = detect_frequency(df)
    print(f"  Detected frequency: {freq}")

    # === Step 6: Look up cutoff and trim ===
    print(f"\nLooking up cutoff timestamp for meter '{meter_name}' (freq={freq})...")
    cutoff = get_cutoff_timestamp(dates_csv_path, meter_name, freq)

    if cutoff is not None:
        before_trim = len(df)
        df = df[df["datetime"] > cutoff].reset_index(drop=True)
        after_trim = len(df)
        print(f"  Cutoff: {cutoff}  →  Kept rows after cutoff: {after_trim} (trimmed {before_trim - after_trim})")
    else:
        print("  No trimming applied.")

    if df.empty:
        print("\n⚠ No data remains after trimming. Output file not written.")
    else:
        # === Step 7: Format datetime and save ===
        df["datetime"] = df["datetime"].dt.strftime("%m/%d/%Y %H:%M")

        # Append _hr to filename if data is hourly
        final_output = OUTPUT.replace(".csv", "_hr.csv") if freq == "1h" else OUTPUT

        os.makedirs(EXPORT_FOLDER, exist_ok=True)
        df.to_csv(final_output, index=False)

        print(f"\n=== Done ===")
        print(f" Files processed  : {len(unique_paths)}")
        print(f" Rows before dedup: {before}")
        print(f" Rows after dedup : {after}")
        print(f" Frequency        : {freq}")
        print(f" Cutoff applied   : {cutoff}")
        print(f" Final rows       : {len(df)}")
        print(f"✅ Wrote {len(df)} rows to {final_output}")