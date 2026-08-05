"""Command-line validation scaffold for generated output files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .contracts import CaseInput
from .data_loader import OlistIndexes
from .verifier import verify_candidate


def validate_output_dir(
    output_dir: Path,
    expected_count: int = 50,
    input_dir: Path | None = None,
    indexes: OlistIndexes | None = None,
) -> list[str]:
    errors: list[str] = []
    files = sorted(output_dir.glob("EC_*.json"))
    if len(files) != expected_count:
        errors.append(f"expected {expected_count} JSON files, found {len(files)}")
    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{path.name}: invalid JSON ({exc})")
            continue
        if payload.get("case_id") != path.stem:
            errors.append(f"{path.name}: case_id does not match filename")
        if input_dir is not None and indexes is not None:
            input_path = input_dir / path.name
            try:
                case = CaseInput.model_validate(
                    json.loads(input_path.read_text(encoding="utf-8"))
                )
                result = verify_candidate(
                    payload,
                    expected_case_id=case.case_id,
                    expected_order_id=case.claimed_order_id,
                    indexes=indexes,
                )
                errors.extend(f"{path.name}: {error}" for error in result.errors)
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                errors.append(f"{path.name}: input validation failed ({exc})")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--input-dir", type=Path, default=Path("input"))
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args()
    indexes = OlistIndexes.load(args.data_dir)
    errors = validate_output_dir(
        args.output_dir,
        input_dir=args.input_dir,
        indexes=indexes,
    )
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"OK: {args.output_dir} contains valid JSON files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
