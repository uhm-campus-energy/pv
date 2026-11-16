import re
from pathlib import Path

# Where raw files go once they're uploaded:
#   data/<folder>/<file>  ->  data_archive/<site>/<site>_<start>_<end>_<freq>.csv
# <site> is the data folder without the vendor suffix (dancestudio_alsoenergy -> dancestudio).
# Used by "2) upload_outputs.py" and move_archives_to_data_archive.py — keep this file even
# after the one-time move, or uploads will fail.

# SunnyPortal exports are named Analysis_YYYY_MM_DD_YYYY_MM_DD.csv (WRC is hourly)
WRC_EXPORT = re.compile(r"Analysis_(\d{4})_(\d{2})_(\d{2})_(\d{4})_(\d{2})_(\d{2})\.csv$", re.IGNORECASE)


def site_name(folder_name):
    return folder_name.rsplit("_", 1)[0]


def archive_file_name(folder_name, file_name):
    site = site_name(folder_name)
    # Files the cleaning scripts renamed: <folder>_<start>_<end>_<freq>.csv
    if file_name.startswith(folder_name + "_"):
        return site + file_name[len(folder_name):]
    match = WRC_EXPORT.match(file_name)
    if site == "wrc" and match:
        y1, m1, d1, y2, m2, d2 = match.groups()
        return f"{site}_{y1}-{m1}-{d1}_{y2}-{m2}-{d2}_1hr.csv"
    # Anything else (e.g. the Burns PDF) keeps its name
    return file_name


def archive_destination(archive_root, folder_name, file_name, taken=()):
    """Path in data_archive/<site>/ for a raw file. Never reuses an existing name (adds _2, _3, ...)."""
    dest_dir = Path(archive_root) / site_name(folder_name)
    name = Path(archive_file_name(folder_name, file_name))
    destination = dest_dir / name
    n = 2
    while destination.exists() or destination in taken:
        destination = dest_dir / f"{name.stem}_{n}{name.suffix}"
        n += 1
    return destination

