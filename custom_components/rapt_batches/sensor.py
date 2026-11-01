"""Per-batch sensors: ABV, time fermenting, status."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import PERCENTAGE, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    ABV_FACTOR,
    CONF_END,
    CONF_FG,
    CONF_OG,
    CONF_START,
    CONF_STATUS,
    DOMAIN,
    STATUS_ACTIVE,
    signal,
)
from .manager import BatchManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    manager: BatchManager = entry.runtime_data
    for sid, sub in entry.subentries.items():
        async_add_entities(
            [
                BatchAbvSensor(manager, sid, sub),
                BatchDaysSensor(manager, sid, sub),
                BatchStatusSensor(manager, sid, sub),
            ],
            config_subentry_id=sid,
        )


class BatchSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _suffix = ""

    def __init__(self, manager: BatchManager, sid: str, sub: ConfigSubentry) -> None:
        self._manager = manager
        self._sid = sid
        self._sub = sub
        self._attr_unique_id = f"{sid}_{self._suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, sid)},
            name=f"Batch: {sub.title}",
            manufacturer="RAPT Batches",
        )

    @property
    def _data(self) -> Any:
        return self._sub.data

    @property
    def _active(self) -> bool:
        return self._data[CONF_STATUS] == STATUS_ACTIVE

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal(self._sid), self.async_write_ha_state)
        )
        if self._active:
            self.async_on_remove(
                async_track_time_interval(
                    self.hass,
                    lambda _now: self.async_write_ha_state(),
                    timedelta(minutes=10),
                )
            )


class BatchAbvSensor(BatchSensor):
    _suffix = "abv"
    _attr_name = "ABV"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    @property
    def _gravity(self) -> float | None:
        if not self._active and self._data.get(CONF_FG) is not None:
            return self._data[CONF_FG]
        return self._manager.latest.get(self._sid, {}).get("sg")

    @property
    def native_value(self) -> float | None:
        sg = self._gravity
        og = self._data.get(CONF_OG)
        if sg is None or og is None:
            return None
        return round(max(0.0, (og - sg) * ABV_FACTOR), 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"original_gravity": self._data.get(CONF_OG), "current_gravity": self._gravity}


class BatchDaysSensor(BatchSensor):
    _suffix = "days"
    _attr_name = "Days fermenting"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_suggested_display_precision = 1

    @property
    def native_value(self) -> float | None:
        start = dt_util.parse_datetime(self._data[CONF_START])
        end = (
            dt_util.utcnow()
            if self._active
            else dt_util.parse_datetime(self._data[CONF_END])
        )
        if start is None or end is None:
            return None
        return round((end - start).total_seconds() / 86400, 2)


class BatchStatusSensor(BatchSensor):
    _suffix = "status"
    _attr_name = "Status"

    @property
    def native_value(self) -> str:
        status = self._data[CONF_STATUS]
        return "finished" if status == "completed" else status
