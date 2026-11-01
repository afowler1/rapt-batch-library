"""Parsers for importing historical batches recorded by other tools.

Each source maps a file's text to readings. To support another source, write a
parse function returning an ImportResult and add it to SOURCES; the panel's
import wizard lists whatever is registered here.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from homeassistant.exceptions import HomeAssistantError

_FRACTION = re.compile(r"(\.\d{6})\d+")  # the portal writes 7 fractional digits


# A gravity outside this range is not a fermenting beer: it is the Pill sitting
# in air or in someone's hand (readings like 1.26 or 2.96 appear at the end of a batch).
SG_MIN, SG_MAX = 0.980, 1.200
# After that, a reading that jumps this far from the previous ones at the very end is dropped too.
TAIL_WINDOW, TAIL_JUMP = 10, 0.010


@dataclass
class ImportResult:
    """Readings parsed from a file, as (key, unix_ts, value) rows."""

    rows: list[tuple[str, float, float]]
    skipped: int  # rows that could not be read
    dropped: int  # rows left out because the gravity was implausible
    trimmed: int  # rows left out at the end because they jumped away from the batch
    start_ts: float
    end_ts: float
    og_guess: float  # highest gravity in the first day
    fg_guess: float  # median gravity over the last 12 hours

    def summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for key, _ts, _value in self.rows:
            counts[key] = counts.get(key, 0) + 1
        return {
            "readings": counts.get("sg", 0),
            "counts": counts,
            "skipped": self.skipped,
            "dropped": self.dropped,
            "trimmed": self.trimmed,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "og_guess": self.og_guess,
            "fg_guess": self.fg_guess,
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
    Signal Strength, Battery (tab, comma or semicolon separated; signal strength
    is not stored)."""
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

    records: list[tuple[float, dict[str, float]]] = []
    skipped = 0
    for line in lines[1:]:
        cells = line.split(delim)
        if not any(c.strip() for c in cells):
            continue  # a blank row (exports end with one) is not an error
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
        records.append((ts, values))
    if not records:
        raise HomeAssistantError("No valid gravity readings were found in the file.")

    # Units: judge by the typical reading, so a few bad ones cannot reject the file.
    gravities = sorted(v["sg"] for _ts, v in records)
    median = gravities[len(gravities) // 2]
    if 900 <= median <= 1300:  # gravity written in points, e.g. 1041
        for _ts, v in records:
            v["sg"] /= 1000
    elif not 0.95 <= median <= 1.3:
        raise HomeAssistantError(
            "Gravity values do not look like specific gravity (for example 1.050). Plato and Brix exports are not supported yet."
        )

    records.sort(key=lambda r: r[0])
    before = len(records)
    records = [r for r in records if SG_MIN <= r[1]["sg"] <= SG_MAX]
    dropped = before - len(records)

    trimmed = 0
    while len(records) > TAIL_WINDOW + 1:
        ref = statistics.median(r[1]["sg"] for r in records[-TAIL_WINDOW - 1 : -1])
        if abs(records[-1][1]["sg"] - ref) > TAIL_JUMP:
            records.pop()
            trimmed += 1
        else:
            break
    if not records:
        raise HomeAssistantError("Every gravity reading in the file looks implausible.")

    first_ts, last_ts = records[0][0], records[-1][0]
    og_guess = max(v["sg"] for ts, v in records if ts <= first_ts + 86400)
    fg_guess = statistics.median(v["sg"] for ts, v in records if ts >= last_ts - 43200)
    rows = [(key, ts, number) for ts, v in records for key, number in v.items()]
    return ImportResult(
        rows=rows,
        skipped=skipped,
        dropped=dropped,
        trimmed=trimmed,
        start_ts=first_ts,
        end_ts=last_ts,
        og_guess=round(og_guess, 4),
        fg_guess=round(fg_guess, 4),
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
