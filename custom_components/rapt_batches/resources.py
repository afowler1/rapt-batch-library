"""Register the dashboard cards as a Lovelace resource.

The Home Assistant Companion app does not run scripts added with
frontend.add_extra_js_url, but it does load dashboard resources. So the cards
are registered as a resource too (using the identical URL, so a browser that
sees both only loads the file once). This needs dashboards in storage mode,
the default. In YAML mode the resource has to be added by hand.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .const import STATIC_URL, VERSION

_LOGGER = logging.getLogger(__name__)

CARDS_PATH = f"{STATIC_URL}/rapt-cards.js"


def cards_url() -> str:
    return f"{CARDS_PATH}?v={VERSION}"


def _collection(hass: HomeAssistant) -> Any | None:
    """The dashboard resources, or None when they cannot be edited."""
    lovelace = hass.data.get("lovelace")
    resources = getattr(lovelace, "resources", None)
    if resources is None and isinstance(lovelace, dict):
        resources = lovelace.get("resources")
    if resources is None or not hasattr(resources, "async_create_item"):
        return None  # missing, or YAML mode (read-only)
    return resources


async def _items(resources: Any) -> list[dict[str, Any]]:
    if not getattr(resources, "loaded", True):
        await resources.async_load()
        resources.loaded = True
    return [i for i in resources.async_items() if str(i.get("url", "")).split("?")[0] == CARDS_PATH]


async def async_register_cards(hass: HomeAssistant) -> None:
    """Make sure exactly one resource points at the current cards URL."""
    url = cards_url()
    resources = _collection(hass)
    if resources is None:
        _LOGGER.info(
            "Dashboards are in YAML mode, so add %s as a JavaScript module under resources "
            "to use the RAPT cards in the mobile app",
            url,
        )
        return
    try:
        ours = await _items(resources)
        current = [i for i in ours if i["url"] == url]
        if current:
            stale = [i for i in ours if i is not current[0]]
        elif ours:
            await resources.async_update_item(ours[0]["id"], {"res_type": "module", "url": url})
            stale = ours[1:]
        else:
            await resources.async_create_item({"res_type": "module", "url": url})
            stale = []
        for item in stale:
            await resources.async_delete_item(item["id"])
    except Exception:  # noqa: BLE001
        _LOGGER.warning(
            "Could not register the dashboard resource. Add %s as a JavaScript module under "
            "Settings > Dashboards > Resources",
            url,
            exc_info=True,
        )


async def async_remove_cards(hass: HomeAssistant) -> None:
    """Remove our resource when the integration is removed."""
    resources = _collection(hass)
    if resources is None:
        return
    try:
        for item in await _items(resources):
            await resources.async_delete_item(item["id"])
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Could not remove the dashboard resource", exc_info=True)
