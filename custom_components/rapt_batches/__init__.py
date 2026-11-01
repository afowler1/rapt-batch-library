"""RAPT Batches: keep fermentation batch data outside the HA recorder."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .const import (
    CONF_END,
    CONF_FG,
    CONF_STATUS,
    DB_NAME,
    DOMAIN,
    PLATFORMS,
    STATUS_ACTIVE,
    STATUS_COMPLETED,
)
from .manager import BatchManager
from .store import BatchStore


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the stop_batch service."""

    async def _stop_batch(call: ServiceCall) -> None:
        entries = [
            e
            for e in hass.config_entries.async_entries(DOMAIN)
            if e.state is ConfigEntryState.LOADED
        ]
        if not entries:
            raise ServiceValidationError("RAPT Batches is not loaded")
        entry = entries[0]
        name = call.data["batch_name"]
        for sid, sub in entry.subentries.items():
            if sub.title == name and sub.data[CONF_STATUS] == STATUS_ACTIVE:
                fg = call.data.get("final_gravity") or entry.runtime_data.latest.get(
                    sid, {}
                ).get("sg")
                new = {
                    **sub.data,
                    CONF_STATUS: STATUS_COMPLETED,
                    CONF_END: dt_util.utcnow().isoformat(),
                    CONF_FG: fg,
                }
                hass.config_entries.async_update_subentry(entry, sub, data=new)
                return
        raise ServiceValidationError(f"No active batch named '{name}'")

    hass.services.async_register(DOMAIN, "stop_batch", _stop_batch)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    store = BatchStore(hass, hass.config.path(DB_NAME))
    await store.async_open()
    manager = BatchManager(hass, entry, store)
    entry.runtime_data = manager
    await manager.async_start()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        manager: BatchManager = entry.runtime_data
        manager.async_stop()
        await manager.store.async_close()
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
