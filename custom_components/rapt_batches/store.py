"""SQLite storage that lives outside the HA recorder, so purges never touch it."""
from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any, Callable

from homeassistant.core import HomeAssistant

SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    start_ts REAL NOT NULL,
    end_ts REAL,
    og REAL,
    fg REAL,
    status TEXT NOT NULL,
    config TEXT
);
CREATE TABLE IF NOT EXISTS readings (
    batch_id TEXT NOT NULL,
    key TEXT NOT NULL,
    ts REAL NOT NULL,
    value REAL NOT NULL,
    PRIMARY KEY (batch_id, key, ts)
) WITHOUT ROWID;
"""


class BatchStore:
    """Thin async wrapper around a SQLite file."""

    def __init__(self, hass: HomeAssistant, path: str) -> None:
        self._hass = hass
        self._path = path
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    async def _run(self, func: Callable[[], Any]) -> Any:
        def _call() -> Any:
            with self._lock:
                return func()

        return await self._hass.async_add_executor_job(_call)

    async def async_open(self) -> None:
        def _open() -> None:
            self._conn = sqlite3.connect(self._path, check_same_thread=False)
            self._conn.executescript(SCHEMA)
            self._conn.commit()

        await self._run(_open)

    async def async_close(self) -> None:
        def _close() -> None:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

        await self._run(_close)

    async def async_has_batch(self, batch_id: str) -> bool:
        def _q() -> bool:
            row = self._conn.execute(
                "SELECT 1 FROM batches WHERE id = ?", (batch_id,)
            ).fetchone()
            return row is not None

        return await self._run(_q)

    async def async_upsert_batch(
        self,
        batch_id: str,
        name: str,
        start_ts: float,
        end_ts: float | None,
        og: float | None,
        fg: float | None,
        status: str,
        config: dict[str, Any],
    ) -> None:
        def _q() -> None:
            self._conn.execute(
                """
                INSERT INTO batches (id, name, start_ts, end_ts, og, fg, status, config)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    start_ts = excluded.start_ts,
                    end_ts = excluded.end_ts,
                    og = excluded.og,
                    fg = excluded.fg,
                    status = excluded.status,
                    config = excluded.config
                """,
                (batch_id, name, start_ts, end_ts, og, fg, status, json.dumps(config)),
            )
            self._conn.commit()

        await self._run(_q)

    async def async_add_readings(
        self, batch_id: str, rows: list[tuple[str, float, float]]
    ) -> None:
        """Insert (key, ts, value) rows, ignoring duplicates."""
        if not rows:
            return

        def _q() -> None:
            self._conn.executemany(
                "INSERT OR IGNORE INTO readings (batch_id, key, ts, value) VALUES (?, ?, ?, ?)",
                [(batch_id, k, ts, v) for k, ts, v in rows],
            )
            self._conn.commit()

        await self._run(_q)

    async def async_latest(self, batch_id: str) -> dict[str, float]:
        def _q() -> dict[str, float]:
            rows = self._conn.execute(
                """
                SELECT r.key, r.value FROM readings r
                WHERE r.batch_id = ?
                  AND r.ts = (SELECT MAX(ts) FROM readings
                              WHERE batch_id = r.batch_id AND key = r.key)
                """,
                (batch_id,),
            ).fetchall()
            return {k: v for k, v in rows}

        return await self._run(_q)
