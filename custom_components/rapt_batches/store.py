"""SQLite storage that lives outside the HA recorder, so purges never touch it."""
from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any, Callable

from homeassistant.core import HomeAssistant

ARCHIVED = "archived"  # keep in sync with const.STATUS_ARCHIVED

SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    start_ts REAL NOT NULL,
    end_ts REAL,
    og REAL,
    fg REAL,
    status TEXT NOT NULL,
    config TEXT,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS readings (
    batch_id TEXT NOT NULL,
    key TEXT NOT NULL,
    ts REAL NOT NULL,
    value REAL NOT NULL,
    PRIMARY KEY (batch_id, key, ts)
) WITHOUT ROWID;
"""


def _dicts(cur: sqlite3.Cursor) -> list[dict[str, Any]]:
    names = [c[0] for c in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


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
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(batches)")}
            if "notes" not in cols:  # database created by v0.1
                self._conn.execute("ALTER TABLE batches ADD COLUMN notes TEXT")
            self._conn.commit()

        await self._run(_open)

    async def async_close(self) -> None:
        def _close() -> None:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

        await self._run(_close)

    # ---- batches -----------------------------------------------------

    async def async_has_batch(self, batch_id: str) -> bool:
        def _q() -> bool:
            return (
                self._conn.execute("SELECT 1 FROM batches WHERE id = ?", (batch_id,)).fetchone()
                is not None
            )

        return await self._run(_q)

    async def async_get_batch(self, batch_id: str) -> dict[str, Any] | None:
        def _q() -> dict[str, Any] | None:
            cur = self._conn.execute("SELECT * FROM batches WHERE id = ?", (batch_id,))
            rows = _dicts(cur)
            if not rows:
                return None
            row = rows[0]
            row["config"] = json.loads(row["config"]) if row["config"] else {}
            return row

        return await self._run(_q)

    async def async_list_batches(self) -> list[dict[str, Any]]:
        def _q() -> list[dict[str, Any]]:
            cur = self._conn.execute(
                "SELECT id, name, start_ts, end_ts, og, fg, status, notes, config FROM batches"
            )
            batches = _dicts(cur)
            for b in batches:
                cfg = json.loads(b.pop("config") or "{}")
                b["can_record"] = bool(cfg.get("sg_entity"))  # imported batches have no sensor
                b["imported_from"] = cfg.get("imported_from")
            latest: dict[str, dict[str, float]] = {}
            for bid, key, val in self._conn.execute(
                """
                SELECT r.batch_id, r.key, r.value FROM readings r
                WHERE r.ts = (SELECT MAX(ts) FROM readings
                              WHERE batch_id = r.batch_id AND key = r.key)
                """
            ):
                latest.setdefault(bid, {})[key] = val
            for b in batches:
                b["latest"] = latest.get(b["id"], {})
            return batches

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
        """Insert or update a batch. Notes are never touched here."""

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

    async def async_set_status(self, batch_id: str, status: str) -> None:
        def _q() -> None:
            self._conn.execute("UPDATE batches SET status = ? WHERE id = ?", (status, batch_id))
            self._conn.commit()

        await self._run(_q)

    async def async_set_notes(self, batch_id: str, notes: str) -> None:
        def _q() -> None:
            self._conn.execute("UPDATE batches SET notes = ? WHERE id = ?", (notes, batch_id))
            self._conn.commit()

        await self._run(_q)

    async def async_update_archived(
        self, batch_id: str, name: str | None, og: float | None, fg: float | None
    ) -> None:
        """Edit an archived batch (columns and the stored config copy)."""

        def _q() -> None:
            row = self._conn.execute(
                "SELECT name, og, fg, config FROM batches WHERE id = ?", (batch_id,)
            ).fetchone()
            if row is None:
                return
            cur_name, cur_og, cur_fg, cfg = row
            config = json.loads(cfg) if cfg else {}
            name_ = name or cur_name
            og_ = og if og is not None else cur_og
            fg_ = fg if fg is not None else cur_fg
            config.update({"name": name_, "og": og_, "fg": fg_})
            self._conn.execute(
                "UPDATE batches SET name = ?, og = ?, fg = ?, config = ? WHERE id = ?",
                (name_, og_, fg_, json.dumps(config), batch_id),
            )
            self._conn.commit()

        await self._run(_q)

    async def async_archive_missing(self, keep_ids: set[str]) -> None:
        """Any batch without a config subentry is archived, never lost."""

        def _q() -> None:
            if keep_ids:
                marks = ",".join("?" * len(keep_ids))
                self._conn.execute(
                    f"UPDATE batches SET status = ? WHERE status != ? AND id NOT IN ({marks})",
                    (ARCHIVED, ARCHIVED, *keep_ids),
                )
            else:
                self._conn.execute(
                    "UPDATE batches SET status = ? WHERE status != ?", (ARCHIVED, ARCHIVED)
                )
            self._conn.commit()

        await self._run(_q)

    async def async_delete_batch(self, batch_id: str) -> None:
        def _q() -> None:
            self._conn.execute("DELETE FROM readings WHERE batch_id = ?", (batch_id,))
            self._conn.execute("DELETE FROM batches WHERE id = ?", (batch_id,))
            self._conn.commit()

        await self._run(_q)

    # ---- readings ----------------------------------------------------

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

    async def async_last_ts(self, batch_id: str) -> dict[str, float]:
        def _q() -> dict[str, float]:
            rows = self._conn.execute(
                "SELECT key, MAX(ts) FROM readings WHERE batch_id = ? GROUP BY key",
                (batch_id,),
            ).fetchall()
            return {k: ts for k, ts in rows}

        return await self._run(_q)

    async def async_readings(
        self, batch_id: str, max_points: int = 1500
    ) -> dict[str, dict[str, list[float]]]:
        """Readings per key as {t: [...], v: [...]}, bucket-averaged if long."""

        def _q() -> dict[str, dict[str, list[float]]]:
            out: dict[str, dict[str, list[float]]] = {}
            stats = self._conn.execute(
                "SELECT key, COUNT(*), MIN(ts), MAX(ts) FROM readings WHERE batch_id = ? GROUP BY key",
                (batch_id,),
            ).fetchall()
            for key, count, lo, hi in stats:
                if count <= max_points:
                    rows = self._conn.execute(
                        "SELECT ts, value FROM readings WHERE batch_id = ? AND key = ? ORDER BY ts",
                        (batch_id, key),
                    ).fetchall()
                else:
                    width = max((hi - lo) / max_points, 1.0)
                    rows = self._conn.execute(
                        """
                        SELECT AVG(ts), AVG(value) FROM readings
                        WHERE batch_id = ? AND key = ?
                        GROUP BY CAST((ts - ?) / ? AS INTEGER)
                        ORDER BY 1
                        """,
                        (batch_id, key, lo, width),
                    ).fetchall()
                out[key] = {"t": [r[0] for r in rows], "v": [r[1] for r in rows]}
            return out

        return await self._run(_q)

    async def async_all_readings(self, batch_id: str) -> list[tuple[str, float, float]]:
        def _q() -> list[tuple[str, float, float]]:
            return self._conn.execute(
                "SELECT key, ts, value FROM readings WHERE batch_id = ? ORDER BY ts",
                (batch_id,),
            ).fetchall()

        return await self._run(_q)
