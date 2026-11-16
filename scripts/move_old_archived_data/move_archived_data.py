import sys
from pathlib import Path

from archive_naming import archive_destination  # same folder as this script

# One-time move of every data/<folder>/archive/ into data_archive/<site>/,
# then removes the emptied archive/ folders.
#
# Usage:
#   python move_archived_data.py          preview only, nothing is moved
#   python move_archived_data.py --move   move the files
#
# A file that can't be moved (e.g. open in Excel or locked by OneDrive) is skipped and listed
# at the end; its archive/ folder is left in place. Fix it and run again to move the rest.

# This file is in scripts/move_old_archived_data/, so the project root is three levels up
project_root = Path(__file__).resolve().parent.parent.parent
data_dir = project_root / "data"
archive_root = project_root / "data_archive"
do_move = "--move" in sys.argv

print("=" * 80)
print("MOVING data/*/archive/ TO data_archive/" + ("" if do_move else "  (PREVIEW — nothing will be moved)"))
print("=" * 80)

planned = []
for old_archive in sorted(data_dir.glob("*/archive")):
    folder_name = old_archive.parent.name
    taken = set()
    for f in sorted(old_archive.iterdir()):
        if not f.is_file():
            print(f"  ⚠ Skipping subfolder {folder_name}/archive/{f.name}")
            continue
        destination = archive_destination(archive_root, folder_name, f.name, taken)
        taken.add(destination)
        planned.append((f, destination))

if not planned:
    print("\nNothing to move — no files in any data/*/archive/ folder.")
    sys.exit(0)

current = None
for source, destination in planned:
    if source.parent != current:
        current = source.parent
        print(f"\ndata/{current.parent.name}/archive/  →  data_archive/{destination.parent.name}/")
    print(f"  {source.name}  →  {destination.name}")

if not do_move:
    print(f"\n{len(planned)} file(s) would be moved. Run again with --move to move them.")
    sys.exit(0)

print()
moved = 0
skipped = []
for source, destination in planned:
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)
        moved += 1
    except OSError as e:  # PermissionError and other access errors
        skipped.append((source, e))
        print(f"  ⚠ Skipped data/{source.parent.parent.name}/archive/{source.name}: {e}")

# Remove the archive/ folders that are now empty
for old_archive in sorted(data_dir.glob("*/archive")):
    if any(old_archive.iterdir()):
        print(f"  ⚠ data/{old_archive.parent.name}/archive/ still has files — not removed")
        continue
    try:
        old_archive.rmdir()
        print(f"  ↳ Removed empty data/{old_archive.parent.name}/archive/")
    except OSError as e:
        print(f"  ⚠ Could not remove data/{old_archive.parent.name}/archive/: {e}")

print(f"\n✅ Moved {moved} of {len(planned)} file(s) into {archive_root}")
if skipped:
    print(f"⚠ Skipped {len(skipped)} file(s) — close them (Excel, VS Code) or wait for OneDrive, then run again:")
    for source, _ in skipped:
        print(f"    data/{source.parent.parent.name}/archive/{source.name}")
print("=" * 80)
