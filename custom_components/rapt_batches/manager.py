"""Records readings for active batches and backfills from the recorder."""
from __future__ import annotations

import logging
from functools import partial
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DEVICE,
    CONF_END,
    CONF_FG,
    CONF_NAME,
    CONF_OG,
    CONF_START,
    CONF_STATUS,
    KEYS,
    STATUS_ACTIVE,
    entity_key,
    signal,
)
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

    async def async_start(self) -> None:
        for sid, sub in self.entry.subentries.items():
            data = sub.data
            if data[CONF_STATUS] == STATUS_ACTIVE:
                # Listen first so nothing is missed while backfilling; the
                # primary key drops any overlap.
                self._track(sid, data)
            if not await self.store.async_has_batch(sid):
                await self._async_backfill(sid, data)
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
        config = {k: data.get(k) for k in (CONF_DEVICE, *(entity_key(x) for x in KEYS))}
        await self.store.async_upsert_batch(
            sid,
            sub.title,
            start.timestamp(),
            end.timestamp() if end else None,
            data.get(CONF_OG),
            data.get(CONF_FG),
            data[CONF_STATUS],
            config,
        )

    @callback
    def _track(self, sid: str, data: Any) -> None:
        entities = {
            data[entity_key(k)]: k for k in KEYS if data.get(entity_key(k))
        }
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
                self.store.async_add_readings(
                    sid, [(key, new.last_updated.timestamp(), value)]
                )
            )
            async_dispatcher_send(self.hass, signal(sid))

        self._unsubs.append(
            async_track_state_change_event(self.hass, list(entities), _handle)
        )

    async def _async_backfill(self, sid: str, data: Any) -> None:
        """Pull history from the recorder so a batch can start in the past."""
        try:
            from homeassistant.components.recorder import get_instance, history

            start = dt_util.parse_datetime(data[CONF_START])
            end = (
                dt_util.parse_datetime(data[CONF_END])
                if data.get(CONF_END)
                else dt_util.utcnow()
            )
            rows: list[tuple[str, float, float]] = []
            for key in KEYS:
                eid = data.get(entity_key(key))
                if not eid:
                    continue
                states = await get_instance(self.hass).async_add_executor_job(
                    partial(
                        history.get_significant_states,
                        self.hass,
                        start,
                        end,
                        [eid],
                        include_start_time_state=True,
                        significant_changes_only=False,
                        no_attributes=True,
                    )
                )
                for st in states.get(eid, []):
                    try:
                        value = float(st.state)
                    except (ValueError, TypeError):
                        continue
                    rows.append((key, st.last_updated.timestamp(), value))
            await self.store.async_add_readings(sid, rows)
            _LOGGER.debug("Backfilled %s readings for batch %s", len(rows), sid)
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Backfill failed for batch %s", sid, exc_info=True)
