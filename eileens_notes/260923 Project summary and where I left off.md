# PV project: script summary and where I left off

*Written 2026-09-23 from the repo's contents (scripts, notes/, data/ folders, git log). Last commit: "more updates" (Aug 6, 2026).*

---

## What the project does

This project cleans solar (PV) generation exports from each campus site's monitoring portal. It turns them into one common format and loads them into the `uhm2023` Postgres database:

- `pv.pv_power`: 15-minute data
- `pv.pv_power_hr`: hourly data

Every cleaned file has the same columns: `datetime, sensor_id, power_avg_kw, meter_name`. The datetime format is `YYYY-MM-DD HH:MM:SS`.

The upload and refresh scripts use server paths (`/home/campusenergy/shared/pv/...`), so they run on the server. The cleaning scripts use paths relative to the project root.

## The workflow

1. **`00_refresh_dates.py`**: exports `pv.dates_pv_power` from the DB to `extracts/dates_pv_power.csv`. That table lists the last timestamp already in the DB for each meter: `pv_power_end` for 15-min data and `pv_power_hr_end` for hourly data.
2. **Download** new raw exports from each portal into `data/<site>/`.
3. **Run the site's cleaning script**. It:
   - reads the raw export
   - picks the PV power column and renames it
   - adds `sensor_id` and `meter_name`
   - sorts by time
   - detects the frequency (15min vs 1hr)
   - drops every row at or before that meter's cutoff in `dates_pv_power.csv`, so nothing is uploaded twice
   - writes `outputs/<meter>_pv_cleaned_<start>_<end>_<freq>.csv`
4. **`01_upload_outputs.py`** handles every file in `outputs/`:
   - `\copy`s it into `pv.pv_power` (`*_15min.csv`) or `pv.pv_power_hr` (`*_1hr.csv`)
   - on success, moves the site's raw input into `data/<site>/archive/` and deletes the output file
   - at the end, re-runs `00_refresh_dates.py` so the cutoffs are current

## Scripts by site

### Single-file sites

These scripts all use the same template. Each one expects exactly **one** CSV in its data folder. It renames that raw file to `<folder>_<start>_<end>_<freq>.csv` and detects the frequency automatically.

| Script | meter_name | sensor_id | Portal | Source column | Notes |
|---|---|---|---|---|---|
| `dancestudio_alsoenergy.py` | dance_pv | 1 | AlsoEnergy | Production meter active power Kilowatts | |
| `gartley_alsoenergy.py` | gartley_pv | 5 | AlsoEnergy | PV Inverter active power Kilowatts | |
| `pbrc_alsoenergy.py` | pbrc_pv | 8 | AlsoEnergy | PV Inverter active power Kilowatts | |
| `parkingphase2_alsoenergy.py` | parking_phase2_pv | 7 | AlsoEnergy | Production meter active power Kilowatts | |
| `frog1_egauge.py` | frog1_pv | 3 | eGauge | pv [kW] | **Sign flipped** (×-1) |
| `frog2_egauge.py` | frog2_pv | 4 | eGauge | PV [kW] | **Sign flipped** (×-1) |
| `bachman_egauge.py` | bachman_pv | 14 | eGauge | Generation [kW] | |
| `gym_egauge.py` | gyms1,2_pv | 13 | eGauge | Generation [kW] | Output file prefix is `gyms_1_2_pv_cleaned` |
| `parkingphase1_egauge.py` | parking_phase1_pv | 12 | eGauge | Generation [kW] | The model the other scripts were updated to match |

### Multi-file sites

| Script | meter_name | sensor_id | What's different |
|---|---|---|---|
| `wrc_sunnyportal.py` | warrior_pv | 11 | Combines about 20 overlapping weekly SunnyPortal `Analysis_*.csv` exports. Parses day-first (DD/MM) AM/PM timestamps and takes the year from the filename. Moves byte-identical duplicate files to `duplicates/`, then removes duplicate rows. Night hours have no readings, and that's expected. |
| `lifescience_solaredge.py` | life_science_pv | 6 | Combines about 20 SolarEdge per-inverter exports and sums the inverter columns (W → kW). Frequency is fixed at `1hr`. Writes the combined raw data to `archive/` and **deletes the source files**. |
| `lawclinic_solaredge.py` | law_clinic_pv | 9 | Same as Life Science. The output prefix is `law_pv_cleaned` (kept on purpose to match the older convention). |

### Meters with no script

- **Burns Hall** (`burns_pv`, sensor 2): the DB only has data through 2022-06-30.
- **Sinclair** (`sinclair_pv`, sensor 10): decommissioned in 2023, so no script is needed.

---

## Where you left off

### Done (Aug 5–6, 2026)
- Moved the code onto the server and switched every script to project-relative paths and the standard output format and filenames.
- Built the upload script (`01_upload_outputs.py`), which also archives inputs and refreshes the dates extract.
- Rewrote Life Science and Law Clinic to match the Parking Phase 1 conventions (see `notes/260806 ...txt`).
- Downloaded new raw data for every site, covering roughly late March through Aug 6, 2026.
- **Uploaded** (the raw files are in `archive/`):
  - Parking Phase 1: through 2026-08-04
  - Parking Phase 2: through 2026-08-06
  - Gartley: through 2026-08-06, but see the checks below

### Downloaded but not yet cleaned or uploaded
The raw files are still in `data/<site>/` under their original download names, and `outputs/` is empty.
- **PBRC, Dance Studio**: AlsoEnergy, 2026-03-24 → 08-06
- **Frog 1, Frog 2, Bachman, Gyms 1&2**: eGauge, about 2026-03-21/04-10 → 08-06
- **WRC**: 20 SunnyPortal weekly files, 2026-03-20 → 08-06
- **Life Science, Law Clinic**: 20 SolarEdge files each. The rewritten scripts have **never been run on real data**, and they delete the source files after archiving. Run them by hand and check `outputs/` and `archive/` before you upload. Back up the raw files first if you're unsure.

### Newest item: Burns Hall (added Sep 22, 2026)
`data/burns_monthly/PV 2025-2026 Burns Hall.pdf` is an EWC monthly billing sheet. It has monthly PV kWh at $0.215/kWh:
- FY2025: Oct 2024 – Sep 2025, 150,528 kWh
- FY2026: Oct 2025 – Aug 2026, 121,273 kWh; September is still blank

There's no script for it yet. It is **monthly energy (kWh)**, not interval power (kW), so it doesn't fit `pv_power` or `pv_power_hr` as they are. Decide where monthly totals should go (a new table?) before writing the script.

### Open decisions and things to check
1. **Upload error summary** (`notes/260805 Upload error summary.txt`): still undecided. Failed uploads currently print to the console and are skipped; nothing is collected or logged. The note recommends a "FAILED UPLOADS" block printed at the end, plus a log file if the script ever runs unattended.
2. **Gartley end date**: Gartley's raw file is in `archive/`, which means the upload reported success. But the local `extracts/dates_pv_power.csv` still shows `gartley_pv` ending 2026-03-24. Check the DB, or re-run `00_refresh_dates.py` and pull the fresh extract.
3. **eGauge timestamps off the 15-min grid**: Frog 2, Bachman and Gyms exports have minute offsets (e.g. `11:16`, `23:32`, `23:33`) instead of `:00/:15/:30/:45`. The scripts don't round them. Check whether that matters for the DB or for later analysis.
4. **The local dates extract is from Aug 6.** Refresh it on the server before cleaning, so the cutoffs match what's actually in the DB.

### Suggested next steps
1. On the server, run `00_refresh_dates.py` and confirm the Gartley end date.
2. Run the single-file cleaners (PBRC, Dance, Frog 1/2, Bachman, Gyms), spot-check `outputs/`, then run `01_upload_outputs.py`.
3. Run `wrc_sunnyportal.py`, then Life Science and Law Clinic one at a time (they're destructive, so check the results), then upload.
4. Decide how failed uploads should be reported.
5. Plan how to store the Burns Hall monthly data.
