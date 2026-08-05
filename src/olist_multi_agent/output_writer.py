"""Safe JSON output writer used only after verification."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_case_output(output_dir: Path, case_id: str, payload: dict[str, Any]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{case_id}.json"
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target
