"""Parsers for importing historical batches recorded by other tools.

Each source maps a file's text to readings. To support another source, write a
parse function returning an ImportResult and add it to SOURCES; the panel's
import wizard lists whatever is registered here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from homeassistant.exceptions import HomeAssistantError

_FRACTION = re.compile(r"(\.\d{6})\d+")  # the portal writes 7 fractional digits


@dataclass
class ImportResult:
    """Readings parsed from a file, as (key, unix_ts, value) rows."""

    rows: list[tuple[str, float, float]]
    skipped: int
    start_ts: float
    end_ts: float
    first_sg: float
    last_sg: float

    def summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for key, _ts, _value in self.rows:
            counts[key] = counts.get(key, 0) + 1
        return {
            "readings": counts.get("sg", 0),
            "counts": counts,
            "skipped": self.skipped,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "first_sg": self.first_sg,
            "last_sg": self.last_sg,
        }


def _parse_time(value: str) -> float | None:
    try:
        parsed = datetime.fromisoformat(_FRACTION.sub(r"\1", value.strip()))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


_LEGACY_COLUMNS = {
    "gravity": "sg",
    "temperature": "temp",
    "gravity velocity": "velocity",
    "battery": "battery",
}


def parse_legacy_rapt(text: str) -> ImportResult:
    """Legacy RAPT Portal export: Date, Temperature, Gravity, Gravity Velocity,
    Signal Strength, Battery (tab separated; signal strength is not stored)."""
    lines = [ln for ln in text.lstrip("\ufeff").splitlines() if ln.strip()]
    if len(lines) < 2:
        raise HomeAssistantError("The file has no data rows.")
    head = lines[0]
    delim = "\t" if "\t" in head else ("," if "," in head else ";")
    headers = [h.strip().lower() for h in head.split(delim)]
    if "date" not in headers or "gravity" not in headers:
        raise HomeAssistantError(
            "This does not look like a Legacy RAPT Portal export (expected Date and Gravity columns)."
        )
    date_idx = headers.index("date")
    cols = {headers.index(name): key for name, key in _LEGACY_COLUMNS.items() if name in headers}

    rows: list[tuple[str, float, float]] = []
    skipped = 0
    for line in lines[1:]:
        cells = line.split(delim)
        ts = _parse_time(cells[date_idx]) if date_idx < len(cells) else None
        values: dict[str, float] = {}
        for idx, key in cols.items():
            if idx < len(cells) and cells[idx].strip():
                try:
                    number = float(cells[idx])
                except ValueError:
                    continue
                if number == number:  # drop NaN
                    values[key] = number
        if ts is None or "sg" not in values:
            skipped += 1
            continue
        rows.extend((key, ts, number) for key, number in values.items())

    sgs = [v for key, _ts, v in rows if key == "sg"]
    if not sgs:
        raise HomeAssistantError("No valid gravity readings were found in the file.")
    low, high = min(sgs), max(sgs)
    if 900 <= low and high <= 1300:  # gravity written in points, e.g. 1041
        rows = [(k, ts, v / 1000 if k == "sg" else v) for k, ts, v in rows]
    elif low < 0.95 or high > 1.3:
        raise HomeAssistantError(
            "Gravity values do not look like specific gravity (for example 1.050). Plato and Brix exports are not supported yet."
        )
    sg_rows = [(ts, v) for key, ts, v in rows if key == "sg"]
    first = min(sg_rows)
    last = max(sg_rows)
    return ImportResult(
        rows=rows,
        skipped=skipped,
        start_ts=min(ts for _k, ts, _v in rows),
        end_ts=max(ts for _k, ts, _v in rows),
        first_sg=first[1],
        last_sg=last[1],
    )


SOURCES: dict[str, dict[str, Any]] = {
    "legacy_rapt_portal": {
        "label": "Legacy RAPT Portal",
        "description": "Export from the old RAPT portal (Date, Temperature, Gravity, Gravity Velocity, Signal Strength, Battery).",
        "help": "Choose the file you exported from the legacy RAPT portal.",
        "accept": ".csv,.tsv,.txt",
        "parse": parse_legacy_rapt,
    },
}


def source_list() -> list[dict[str, Any]]:
    return [
        {"id": sid, **{k: v for k, v in src.items() if k != "parse"}}
        for sid, src in SOURCES.items()
    ]


def parse(source: str, text: str) -> ImportResult:
    src = SOURCES.get(source)
    if src is None:
        raise HomeAssistantError(f"Unknown import source '{source}'")
    parser: Callable[[str], ImportResult] = src["parse"]
    return parser(text)
