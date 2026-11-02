"""RAPT Batches: keep fermentation batch data outside the HA recorder."""
from __future__ import annotations

from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.typing import ConfigType

from . import websocket
from .const import (
    CONF_PANEL_ICON,
    CONF_PANEL_TITLE,
    CONF_STATUS,
    DB_NAME,
    DEFAULT_PANEL_ICON,
    DEFAULT_PANEL_TITLE,
    DOMAIN,
    PANEL_URL,
    PLATFORMS,
    STATIC_URL,
    STATUS_ACTIVE,
    VERSION,
)
from .manager import BatchManager
from .resources import async_register_cards, async_remove_cards
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


async def _async_register_panel(hass: HomeAssistant, entry: ConfigEntry) -> None:
    settings = {**entry.data, **entry.options}
    title = settings.get(CONF_PANEL_TITLE) or DEFAULT_PANEL_TITLE
    icon = settings.get(CONF_PANEL_ICON) or DEFAULT_PANEL_ICON
    flags = hass.data.setdefault(DOMAIN, {})
    if not flags.get("static"):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL, str(Path(__file__).parent / "frontend"), False)]
        )
        flags["static"] = True
    if not flags.get("cards"):
        frontend.add_extra_js_url(hass, f"{STATIC_URL}/rapt-cards.js?v={VERSION}")
        flags["cards"] = True
    if flags.get("panel") and flags.get("panel_cfg") != (title, icon):
        frontend.async_remove_panel(hass, PANEL_URL)  # title or icon changed
        flags["panel"] = False
    if not flags.get("panel"):
        await panel_custom.async_register_panel(
            hass,
            frontend_url_path=PANEL_URL,
            webcomponent_name="rapt-batches-panel",
            sidebar_title=title,
            sidebar_icon=icon,
            module_url=f"{STATIC_URL}/rapt-batches-panel.js?v={VERSION}",
            embed_iframe=False,
            require_admin=False,
            config={"title": title},
        )
        flags["panel"] = True
        flags["panel_cfg"] = (title, icon)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    store = BatchStore(hass, hass.config.path(DB_NAME))
    await store.async_open()
    manager = BatchManager(hass, entry, store)
    entry.runtime_data = manager
    await manager.async_start()

    await _async_register_panel(hass, entry)
    # The mobile app ignores add_extra_js_url, so also register the cards as a dashboard resource.
    async_at_started(hass, async_register_cards)
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
    await async_remove_cards(hass)
    flags = hass.data.get(DOMAIN, {})
    if flags.get("panel"):
        frontend.async_remove_panel(hass, PANEL_URL)
        flags["panel"] = False
    if flags.get("cards"):
        frontend.remove_extra_js_url(hass, f"{STATIC_URL}/rapt-cards.js?v={VERSION}")
        flags["cards"] = False


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
