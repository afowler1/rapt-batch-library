"""Records readings, owns batch state changes, and serves the panel."""
from __future__ import annotations

import csv
import io
import logging
import re
from functools import partial
from types import MappingProxyType
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util
from homeassistant.util.ulid import ulid_now

from .const import (
    CONF_END,
    CONF_FG,
    CONF_NAME,
    CONF_OG,
    CONF_START,
    CONF_STATUS,
    KEYS,
    STATUS_ACTIVE,
    STATUS_ARCHIVED,
    STATUS_COMPLETED,
    entity_key,
    signal,
)
from . import rapt_brew
from .importers import ImportResult, parse as parse_import, suggest_og_fg
from .store import BatchStore

_LOGGER = logging.getLogger(__name__)


class BatchManager:
    """Owns the store and the state listeners for every batch."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, store: BatchStore) -> None:
        self.hass = hass
        self.entry = entry
        self.store = store
        self.latest: dict[str, dict[str, float]] = {}
        self._unsubs: list[Any] = []

    # ---- lifecycle ---------------------------------------------------

    async def async_start(self) -> None:
        subs = self.entry.subentries
        # A batch removed from the integration page is archived, never lost.
        await self.store.async_archive_missing(set(subs))
        for sid, sub in subs.items():
            data = sub.data
            is_new = not await self.store.async_has_batch(sid)
            active = data[CONF_STATUS] == STATUS_ACTIVE
            if active:
                # Listen first so nothing is missed while catching up; the
                # primary key drops any overlap.
                self._track(sid, data)
            if is_new or active:
                since = await self.store.async_last_ts(sid)
                await self._async_backfill(sid, data, since)
            await self._async_upsert(sid, sub)
            self.latest[sid] = await self.store.async_latest(sid)

    @callback
    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    async def _async_upsert(self, sid: str, sub: ConfigSubentry) -> None:
        data = sub.data
        start = dt_util.parse_datetime(data[CONF_START])
        end = dt_util.parse_datetime(data[CONF_END]) if data.get(CONF_END) else None
        await self.store.async_upsert_batch(
            sid,
            sub.title,
            start.timestamp(),
            end.timestamp() if end else None,
            data.get(CONF_OG),
            data.get(CONF_FG),
            data[CONF_STATUS],
            dict(data),
        )

    @callback
    def _track(self, sid: str, data: Any) -> None:
        entities = {data[entity_key(k)]: k for k in KEYS if data.get(entity_key(k))}
        if not entities:
            return

        @callback
        def _handle(event: Event) -> None:
            new = event.data.get("new_state")
            if new is None or new.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                return
            try:
                value = float(new.state)
            except (ValueError, TypeError):
                return
            key = entities[event.data["entity_id"]]
            self.latest.setdefault(sid, {})[key] = value
            self.hass.async_create_task(
                self.store.async_add_readings(sid, [(key, new.last_updated.timestamp(), value)])
            )
            async_dispatcher_send(self.hass, signal(sid))

        self._unsubs.append(async_track_state_change_event(self.hass, list(entities), _handle))

    async def _async_history(self, entity_id: str, begin: Any, end: Any) -> list[tuple[float, float]]:
        """Numeric states of an entity between two datetimes, from the recorder.

        The state in force at `begin` is stamped at `begin`, not at whenever it last
        changed, so it falls inside the window being filled.
        """
        from homeassistant.components.recorder import get_instance, history

        states = await get_instance(self.hass).async_add_executor_job(
            partial(
                history.get_significant_states,
                self.hass,
                begin,
                end,
                [entity_id],
                include_start_time_state=True,
                significant_changes_only=False,
                no_attributes=True,
            )
        )
        floor = begin.timestamp()
        out: list[tuple[float, float]] = []
        for st in states.get(entity_id, []):
            try:
                value = float(st.state)
            except (ValueError, TypeError):
                continue
            out.append((max(st.last_updated.timestamp(), floor), value))
        return out

    async def _async_backfill(self, sid: str, data: Any, since: dict[str, float]) -> None:
        """Fill history from the recorder, from the last stored reading onward."""
        try:
            batch_start = dt_util.parse_datetime(data[CONF_START])
            end = (
                dt_util.parse_datetime(data[CONF_END])
                if data.get(CONF_END) and data[CONF_STATUS] != STATUS_ACTIVE
                else dt_util.utcnow()
            )
            rows: list[tuple[str, float, float]] = []
            for key in KEYS:
                eid = data.get(entity_key(key))
                if not eid:
                    continue
                begin = batch_start
                if key in since:
                    begin = max(begin, dt_util.utc_from_timestamp(since[key]))
                if begin >= end:
                    continue
                rows.extend((key, ts, value) for ts, value in await self._async_history(eid, begin, end))
            await self.store.async_add_readings(sid, rows)
            _LOGGER.debug("Backfilled %s readings for batch %s", len(rows), sid)
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Backfill failed for batch %s", sid, exc_info=True)

    async def _async_fetch_range(self, bid: str, config: Any, begin_ts: float, end_ts: float) -> int:
        """Pull a stretch of history from the recorder for a batch. Returns new readings added."""
        added = 0
        try:
            begin = dt_util.utc_from_timestamp(begin_ts)
            end = dt_util.utc_from_timestamp(end_ts)
            for key in KEYS:
                eid = config.get(entity_key(key))
                if not eid:
                    continue
                rows = [(key, ts, v) for ts, v in await self._async_history(eid, begin, end)]
                added += await self.store.async_add_readings(bid, rows)
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Could not read the recorder for batch %s", bid, exc_info=True)
        return added

    # ---- helpers -----------------------------------------------------

    def _sub(self, sid: str, status: str | None = None) -> ConfigSubentry:
        sub = self.entry.subentries.get(sid)
        if sub is None:
            raise HomeAssistantError("Batch not found (is it archived?)")
        if status is not None and sub.data[CONF_STATUS] != status:
            raise HomeAssistantError(f"Batch is not {status}")
        return sub

    # ---- state changes -----------------------------------------------

    async def async_finish(self, sid: str, fg: float | None = None) -> None:
        sub = self._sub(sid, STATUS_ACTIVE)
        if fg is None:
            fg = self.latest.get(sid, {}).get("sg")
        new = {
            **sub.data,
            CONF_STATUS: STATUS_COMPLETED,
            CONF_END: dt_util.utcnow().isoformat(),
            CONF_FG: fg,
        }
        self.hass.config_entries.async_update_subentry(self.entry, sub, data=new)

    async def async_reopen(self, sid: str) -> None:
        sub = self._sub(sid, STATUS_COMPLETED)
        if not sub.data.get(entity_key("sg")):
            raise HomeAssistantError("This batch was imported, so there is no sensor to record from.")
        new = {**sub.data, CONF_STATUS: STATUS_ACTIVE, CONF_END: None, CONF_FG: None}
        self.hass.config_entries.async_update_subentry(self.entry, sub, data=new)

    async def async_archive(self, sid: str) -> None:
        """Move a finished batch off the integration page into the panel."""
        sub = self._sub(sid, STATUS_COMPLETED)
        await self._async_upsert(sid, sub)  # make sure the database copy is current
        await self.store.async_set_status(sid, STATUS_ARCHIVED)
        self.hass.config_entries.async_remove_subentry(self.entry, sid)

    async def async_unarchive(self, bid: str) -> None:
        row = await self.store.async_get_batch(bid)
        if row is None or row["status"] != STATUS_ARCHIVED:
            raise HomeAssistantError("Batch is not archived")
        end_ts = row["end_ts"]
        data = {
            **row["config"],
            CONF_NAME: row["name"],
            CONF_OG: row["og"],
            CONF_FG: row["fg"],
            CONF_START: dt_util.utc_from_timestamp(row["start_ts"]).isoformat(),
            CONF_END: (
                dt_util.utc_from_timestamp(end_ts) if end_ts else dt_util.utcnow()
            ).isoformat(),
            CONF_STATUS: STATUS_COMPLETED,
        }
        await self.store.async_set_status(bid, STATUS_COMPLETED)
        sub = ConfigSubentry(
            data=MappingProxyType(data),
            subentry_id=bid,
            subentry_type="batch",
            title=row["name"],
            unique_id=None,
        )
        self.hass.config_entries.async_add_subentry(self.entry, sub)

    async def async_delete(self, bid: str) -> None:
        row = await self.store.async_get_batch(bid)
        if row is None:
            raise HomeAssistantError("Batch not found")
        if row["status"] != STATUS_ARCHIVED or bid in self.entry.subentries:
            raise HomeAssistantError("Only archived batches can be deleted")
        await self.store.async_delete_batch(bid)

    async def async_update_batch(
        self,
        bid: str,
        name: str | None = None,
        notes: str | None = None,
        og: float | None = None,
        fg: float | None = None,
    ) -> None:
        if notes is not None:
            await self.store.async_set_notes(bid, notes)
        sub = self.entry.subentries.get(bid)
        if sub is not None:
            new = dict(sub.data)
            if og is not None:
                new[CONF_OG] = og
            if fg is not None and new[CONF_STATUS] != STATUS_ACTIVE:
                new[CONF_FG] = fg
            if name:
                new[CONF_NAME] = name
            title = name or sub.title
            if new != dict(sub.data) or title != sub.title:
                self.hass.config_entries.async_update_subentry(
                    self.entry, sub, data=new, title=title
                )
            return
        row = await self.store.async_get_batch(bid)
        if row is None or row["status"] != STATUS_ARCHIVED:
            raise HomeAssistantError("Batch not found")
        await self.store.async_update_archived(bid, name, og, fg)

    # ---- panel data --------------------------------------------------

    async def async_list(self) -> list[dict[str, Any]]:
        rows = await self.store.async_list_batches()
        for row in rows:
            if row["status"] == STATUS_ACTIVE:
                row["latest"] = {**row["latest"], **self.latest.get(row["id"], {})}
        return rows

    async def async_readings(self, bid: str, max_points: int, include_hidden: bool = False) -> dict[str, Any]:
        row = await self.store.async_get_batch(bid)
        if row is None:
            raise HomeAssistantError("Batch not found")
        window = None if include_hidden else (row["start_ts"], row["end_ts"])
        return {
            "series": await self.store.async_readings(bid, max_points, window),
            "window": {"start_ts": row["start_ts"], "end_ts": row["end_ts"]},
        }

    async def async_export(self, bid: str) -> dict[str, str]:
        row = await self.store.async_get_batch(bid)
        if row is None:
            raise HomeAssistantError("Batch not found")
        table: dict[int, dict[str, float]] = {}
        for key, ts, value in await self.store.async_all_readings(bid, (row["start_ts"], row["end_ts"])):
            table.setdefault(int(round(ts / 60) * 60), {})[key] = value
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["timestamp", *KEYS])
        for t in sorted(table):
            writer.writerow(
                [dt_util.utc_from_timestamp(t).isoformat(), *[table[t].get(k, "") for k in KEYS]]
            )
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", row["name"]).strip("_") or "batch"
        return {"filename": f"{safe}.csv", "csv": out.getvalue()}

    # ---- import ------------------------------------------------------

    async def async_import(
        self, source: str, text: str, name: str, og: float | None, fg: float | None
    ) -> str:
        """Create an archived batch from another tool's export."""
        result = await self.hass.async_add_executor_job(parse_import, source, text)
        return await self._async_store_import(source, result, name, og, fg)

    async def async_import_remote(
        self, cookie: str, recording: str, name: str | None, og: float | None, fg: float | None
    ) -> str:
        """Pull a recording from the RAPT Brew website and store it as an archived batch."""
        title, result = await rapt_brew.async_pull(self.hass, cookie, recording)
        return await self._async_store_import("rapt_brew", result, name or title, og, fg)

    async def _async_store_import(
        self, source: str, result: ImportResult, name: str, og: float | None, fg: float | None
    ) -> str:
        existing = await self.store.async_list_batches()
        if any(abs(b["start_ts"] - result.start_ts) < 1 for b in existing):
            raise HomeAssistantError("A batch that starts at the same time already exists.")
        og = og if og is not None else result.og_guess
        fg = fg if fg is not None else result.fg_guess
        bid = ulid_now()
        config = {
            CONF_NAME: name,
            CONF_OG: og,
            CONF_FG: fg,
            CONF_START: dt_util.utc_from_timestamp(result.start_ts).isoformat(),
            CONF_END: dt_util.utc_from_timestamp(result.end_ts).isoformat(),
            CONF_STATUS: STATUS_COMPLETED,
            "imported_from": source,
        }
        await self.store.async_upsert_batch(
            bid, name, result.start_ts, result.end_ts, og, fg, STATUS_ARCHIVED, config
        )
        await self.store.async_add_readings(bid, result.rows)
        return bid

    # ---- window ------------------------------------------------------

    async def async_window_preview(self, bid: str, start_ts: float, end_ts: float) -> dict[str, Any]:
        """What a window would contain, without changing anything."""
        if await self.store.async_get_batch(bid) is None:
            raise HomeAssistantError("Batch not found")
        series = await self.store.async_sg_series(bid, start_ts, end_ts)
        out: dict[str, Any] = {"readings": len(series), "og_guess": None, "fg_guess": None}
        if series:
            out["og_guess"], out["fg_guess"] = suggest_og_fg(series)
        return out

    async def async_set_window(
        self, bid: str, start_ts: float, end_ts: float, recalc: bool = False
    ) -> dict[str, Any]:
        """Change a finished or archived batch's start and end.

        Readings outside the window stay stored, only hidden, so the change can be
        undone. Widening it asks the recorder for the extra stretch (batches recorded
        here only; imported ones cannot grow past their file).
        """
        row = await self.store.async_get_batch(bid)
        if row is None:
            raise HomeAssistantError("Batch not found")
        if row["status"] == STATUS_ACTIVE:
            raise HomeAssistantError("Finish the batch before adjusting its window")
        if end_ts > dt_util.utcnow().timestamp() + 60:
            raise HomeAssistantError("The end cannot be in the future")
        if start_ts >= end_ts - 60:
            raise HomeAssistantError("The start must be at least a minute before the end")

        config = row["config"]
        can_record = bool(config.get(entity_key("sg")))
        added = 0
        if can_record:
            old_start, old_end = row["start_ts"], row["end_ts"] or end_ts
            if start_ts < old_start:
                added += await self._async_fetch_range(bid, config, start_ts, old_start)
            if end_ts > old_end:
                added += await self._async_fetch_range(bid, config, old_end, end_ts)

        series = await self.store.async_sg_series(bid, start_ts, end_ts)
        if len(series) < 2:
            raise HomeAssistantError("That window has fewer than two gravity readings")
        og, fg = row["og"], row["fg"]
        if recalc:
            og, fg = suggest_og_fg(series)

        await self.store.async_update_window(bid, start_ts, end_ts, og, fg)
        sub = self.entry.subentries.get(bid)
        if sub is not None:  # still on the integration page: keep its copy in step
            new = {
                **sub.data,
                CONF_START: dt_util.utc_from_timestamp(start_ts).isoformat(),
                CONF_END: dt_util.utc_from_timestamp(end_ts).isoformat(),
                CONF_OG: og,
                CONF_FG: fg,
            }
            if new != dict(sub.data):
                self.hass.config_entries.async_update_subentry(self.entry, sub, data=new)
        return {"added": added, "og": og, "fg": fg, "can_record": can_record, "readings": len(series)}
