"""RAPT Batches: keep fermentation batch data outside the HA recorder."""
from __future__ import annotations

from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.typing import ConfigType

from . import websocket
from .const import (
    CONF_STATUS,
    DB_NAME,
    DOMAIN,
    PANEL_URL,
    PLATFORMS,
    STATIC_URL,
    STATUS_ACTIVE,
    VERSION,
)
from .manager import BatchManager
from .store import BatchStore


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the websocket API and the stop_batch service."""
    websocket.async_register(hass)

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
                try:
                    await entry.runtime_data.async_finish(sid, call.data.get("final_gravity"))
                except HomeAssistantError as err:
                    raise ServiceValidationError(str(err)) from err
                return
        raise ServiceValidationError(f"No active batch named '{name}'")

    hass.services.async_register(DOMAIN, "stop_batch", _stop_batch)
    return True


async def _async_register_panel(hass: HomeAssistant) -> None:
    flags = hass.data.setdefault(DOMAIN, {})
    if not flags.get("static"):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL, str(Path(__file__).parent / "frontend"), False)]
        )
        flags["static"] = True
    if not flags.get("panel"):
        await panel_custom.async_register_panel(
            hass,
            frontend_url_path=PANEL_URL,
            webcomponent_name="rapt-batches-panel",
            sidebar_title="Brewing",
            sidebar_icon="mdi:beer-outline",
            module_url=f"{STATIC_URL}/rapt-batches-panel.js?v={VERSION}",
            embed_iframe=False,
            require_admin=False,
        )
        flags["panel"] = True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    store = BatchStore(hass, hass.config.path(DB_NAME))
    await store.async_open()
    manager = BatchManager(hass, entry, store)
    entry.runtime_data = manager
    await manager.async_start()

    await _async_register_panel(hass)
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


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove the sidebar panel when the integration itself is removed."""
    flags = hass.data.get(DOMAIN, {})
    if flags.get("panel"):
        frontend.async_remove_panel(hass, PANEL_URL)
        flags["panel"] = False


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
