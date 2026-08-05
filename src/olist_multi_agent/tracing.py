"""Append-only event writer for one run; the file is reset at run start."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class TraceWriter:
    def __init__(self, path: Path) -> None:
        self.path = path

    def reset(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")

    def event(self, **payload: Any) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            **payload,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
