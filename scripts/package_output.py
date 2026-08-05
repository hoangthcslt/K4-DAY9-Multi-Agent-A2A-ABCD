"""Create the exact submission archive required by README.md."""

from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT_DIR / "output"
ARCHIVE_PATH = ROOT_DIR / "output.zip"
EXPECTED_NAMES = [f"EC_{index:03d}.json" for index in range(1, 51)]


def main() -> int:
    actual_names = sorted(path.name for path in OUTPUT_DIR.glob("*.json"))
    if actual_names != EXPECTED_NAMES:
        missing = sorted(set(EXPECTED_NAMES) - set(actual_names))
        extra = sorted(set(actual_names) - set(EXPECTED_NAMES))
        raise SystemExit(f"output set mismatch; missing={missing}; extra={extra}")

    with ZipFile(ARCHIVE_PATH, "w", compression=ZIP_DEFLATED) as archive:
        for name in EXPECTED_NAMES:
            archive.write(OUTPUT_DIR / name, f"output/{name}")

    with ZipFile(ARCHIVE_PATH) as archive:
        names = archive.namelist()
    if names != [f"output/{name}" for name in EXPECTED_NAMES]:
        raise SystemExit("output.zip entries do not match the required exact order")
    print(f"Created {ARCHIVE_PATH} with {len(names)} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
