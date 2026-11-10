"""Websocket API used by the Brewing panel."""
from __future__ import annotations

from typing import Any, Callable, Awaitable

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from . import importers, rapt_brew
from .const import DOMAIN
from .manager import BatchManager

ACTIONS = ("finish", "reopen", "archive", "unarchive", "delete")


def _manager(hass: HomeAssistant) -> BatchManager | None:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            return entry.runtime_data
    return None


async def _with_manager(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    call: Callable[[BatchManager], Awaitable[Any]],
) -> None:
    manager = _manager(hass)
    if manager is None:
        connection.send_error(msg["id"], "not_loaded", "RAPT Batches is not loaded")
        return
    try:
        result = await call(manager)
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "failed", str(err))
        return
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command({vol.Required("type"): "rapt_batches/list"})
@websocket_api.async_response
async def ws_list(hass, connection, msg) -> None:
    async def _call(m: BatchManager) -> Any:
        return {"batches": await m.async_list()}

    await _with_manager(hass, connection, msg, _call)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "rapt_batches/readings",
        vol.Required("batch_id"): str,
        vol.Optional("max_points", default=1500): vol.All(int, vol.Range(min=50, max=10000)),
        vol.Optional("include_hidden", default=False): bool,
    }
)
@websocket_api.async_response
async def ws_readings(hass, connection, msg) -> None:
    await _with_manager(
        hass,
        connection,
        msg,
        lambda m: m.async_readings(msg["batch_id"], msg["max_points"], msg["include_hidden"]),
    )


@websocket_api.websocket_command(
    {vol.Required("type"): "rapt_batches/export", vol.Required("batch_id"): str}
)
@websocket_api.async_response
async def ws_export(hass, connection, msg) -> None:
    await _with_manager(hass, connection, msg, lambda m: m.async_export(msg["batch_id"]))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "rapt_batches/action",
        vol.Required("batch_id"): str,
        vol.Required("action"): vol.In(ACTIONS),
        vol.Optional("fg"): vol.Any(None, vol.Coerce(float)),
    }
)
@websocket_api.async_response
async def ws_action(hass, connection, msg) -> None:
    async def _call(m: BatchManager) -> Any:
        bid, action = msg["batch_id"], msg["action"]
        if action == "finish":
            await m.async_finish(bid, msg.get("fg"))
        elif action == "reopen":
            await m.async_reopen(bid)
        elif action == "archive":
            await m.async_archive(bid)
        elif action == "unarchive":
            await m.async_unarchive(bid)
        elif action == "delete":
            await m.async_delete(bid)
        return {"ok": True}

    await _with_manager(hass, connection, msg, _call)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "rapt_batches/update",
        vol.Required("batch_id"): str,
        vol.Optional("name"): str,
        vol.Optional("notes"): str,
        vol.Optional("og"): vol.Any(None, vol.Coerce(float)),
        vol.Optional("fg"): vol.Any(None, vol.Coerce(float)),
    }
)
@websocket_api.async_response
async def ws_update(hass, connection, msg) -> None:
    async def _call(m: BatchManager) -> Any:
        await m.async_update_batch(
            msg["batch_id"],
            name=msg.get("name"),
            notes=msg.get("notes"),
            og=msg.get("og"),
            fg=msg.get("fg"),
        )
        return {"ok": True}

    await _with_manager(hass, connection, msg, _call)


@websocket_api.websocket_command({vol.Required("type"): "rapt_batches/import_sources"})
@websocket_api.async_response
async def ws_import_sources(hass, connection, msg) -> None:
    connection.send_result(msg["id"], {"sources": importers.source_list()})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "rapt_batches/import_preview",
        vol.Required("source"): str,
        vol.Required("text"): str,
    }
)
@websocket_api.async_response
async def ws_import_preview(hass, connection, msg) -> None:
    try:
        result = await hass.async_add_executor_job(importers.parse, msg["source"], msg["text"])
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "failed", str(err))
        return
    connection.send_result(msg["id"], result.summary())


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "rapt_batches/import",
        vol.Required("source"): str,
        vol.Required("text"): str,
        vol.Required("name"): vol.All(str, vol.Length(min=1)),
        vol.Optional("og"): vol.Any(None, vol.Coerce(float)),
        vol.Optional("fg"): vol.Any(None, vol.Coerce(float)),
    }
)
@websocket_api.async_response
async def ws_import(hass, connection, msg) -> None:
    async def _call(m: BatchManager) -> Any:
        bid = await m.async_import(
            msg["source"], msg["text"], msg["name"].strip(), msg.get("og"), msg.get("fg")
        )
        return {"id": bid}

    await _with_manager(hass, connection, msg, _call)


# The RAPT site commands take the user's login cookie. They are admin only because
# they make requests from the server, and the cookie is used for that call alone.
@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "rapt_batches/remote_list",
        vol.Required("cookie"): str,
    }
)
@websocket_api.async_response
async def ws_remote_list(hass, connection, msg) -> None:
    try:
        result = await rapt_brew.async_list_recordings(hass, msg["cookie"])
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "failed", str(err))
        return
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "rapt_batches/remote_preview",
        vol.Required("cookie"): str,
        vol.Required("recording"): str,
    }
)
@websocket_api.async_response
async def ws_remote_preview(hass, connection, msg) -> None:
    try:
        title, result = await rapt_brew.async_pull(hass, msg["cookie"], msg["recording"])
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "failed", str(err))
        return
    connection.send_result(msg["id"], {**result.summary(), "title": title})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "rapt_batches/remote_import",
        vol.Required("cookie"): str,
        vol.Required("recording"): str,
        vol.Required("name"): vol.All(str, vol.Length(min=1)),
        vol.Optional("og"): vol.Any(None, vol.Coerce(float)),
        vol.Optional("fg"): vol.Any(None, vol.Coerce(float)),
    }
)
@websocket_api.async_response
async def ws_remote_import(hass, connection, msg) -> None:
    async def _call(m: BatchManager) -> Any:
        bid = await m.async_import_remote(
            msg["cookie"], msg["recording"], msg["name"].strip(), msg.get("og"), msg.get("fg")
        )
        return {"id": bid}

    await _with_manager(hass, connection, msg, _call)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "rapt_batches/window_preview",
        vol.Required("batch_id"): str,
        vol.Required("start"): vol.Coerce(float),
        vol.Required("end"): vol.Coerce(float),
    }
)
@websocket_api.async_response
async def ws_window_preview(hass, connection, msg) -> None:
    await _with_manager(
        hass, connection, msg, lambda m: m.async_window_preview(msg["batch_id"], msg["start"], msg["end"])
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "rapt_batches/set_window",
        vol.Required("batch_id"): str,
        vol.Required("start"): vol.Coerce(float),
        vol.Required("end"): vol.Coerce(float),
        vol.Optional("recalc", default=False): bool,
    }
)
@websocket_api.async_response
async def ws_set_window(hass, connection, msg) -> None:
    await _with_manager(
        hass,
        connection,
        msg,
        lambda m: m.async_set_window(msg["batch_id"], msg["start"], msg["end"], msg["recalc"]),
    )


def async_register(hass: HomeAssistant) -> None:
    for handler in (
        ws_list,
        ws_readings,
        ws_export,
        ws_action,
        ws_update,
        ws_import_sources,
        ws_import_preview,
        ws_import,
        ws_remote_list,
        ws_remote_preview,
        ws_remote_import,
        ws_window_preview,
        ws_set_window,
    ):
        websocket_api.async_register_command(hass, handler)
