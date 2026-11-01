"""Config flow: one hub entry, and one 'batch' subentry per fermentation."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er, selector
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DEVICE,
    CONF_END,
    CONF_FG,
    CONF_NAME,
    CONF_OG,
    CONF_PANEL_ICON,
    CONF_PANEL_TITLE,
    CONF_START,
    CONF_STATUS,
    DEFAULT_PANEL_ICON,
    DEFAULT_PANEL_TITLE,
    DOMAIN,
    STATUS_ACTIVE,
    STATUS_COMPLETED,
    entity_key,
)

GRAVITY = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=1.0, max=1.2, step=0.001, mode=selector.NumberSelectorMode.BOX
    )
)
SENSOR = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))


def _guess_entities(hass, device_id: str) -> dict[str, str]:
    """Find the Pill's sensors on a device by entity id suffix."""
    guessed: dict[str, str] = {}
    registry = er.async_get(hass)
    for ent in er.async_entries_for_device(registry, device_id):
        if ent.domain != "sensor":
            continue
        eid = ent.entity_id
        if eid.endswith("_specific_gravity_velocity"):
            guessed["velocity"] = eid
        elif eid.endswith("_specific_gravity"):
            guessed["sg"] = eid
        elif eid.endswith("_temperature"):
            guessed["temp"] = eid
        elif eid.endswith("_battery"):
            guessed["battery"] = eid
    return guessed


def _to_utc_iso(value: str) -> str:
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        raise ValueError(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.get_default_time_zone())
    return dt_util.as_utc(parsed.replace(second=0, microsecond=0)).isoformat()


def _now_minute() -> str:
    """Current local time with seconds zeroed (HA's picker always shows seconds)."""
    return dt_util.now().strftime("%Y-%m-%d %H:%M:00")


def _float_state(hass, entity_id: str | None) -> float | None:
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    try:
        return float(state.state) if state else None
    except ValueError:
        return None


def _panel_schema(title: str, icon: str) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_PANEL_TITLE, default=title): selector.TextSelector(),
            vol.Required(CONF_PANEL_ICON, default=icon): selector.IconSelector(),
        }
    )


class RaptBatchesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create the single hub entry."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="RAPT Batch Library", data=user_input)
        return self.async_show_form(
            step_id="user", data_schema=_panel_schema(DEFAULT_PANEL_TITLE, DEFAULT_PANEL_ICON)
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return RaptBatchesOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {"batch": BatchSubentryFlow}


class RaptBatchesOptionsFlow(OptionsFlow):
    """Rename the sidebar panel or change its icon."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        cur = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=_panel_schema(
                cur.get(CONF_PANEL_TITLE) or DEFAULT_PANEL_TITLE,
                cur.get(CONF_PANEL_ICON) or DEFAULT_PANEL_ICON,
            ),
        )


class BatchSubentryFlow(ConfigSubentryFlow):
    """Wizard: name and pill, sensors, then how the batch starts."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    # ---- new batch ---------------------------------------------------

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            names = {s.title for s in self._get_entry().subentries.values()}
            if user_input[CONF_NAME] in names:
                errors[CONF_NAME] = "name_exists"
            else:
                self._data.update(user_input)
                return await self.async_step_entities()
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): selector.TextSelector(),
                vol.Required(CONF_DEVICE): selector.DeviceSelector(
                    selector.DeviceSelectorConfig(integration="rapt_ble")
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_entities(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_details()
        guess = _guess_entities(self.hass, self._data[CONF_DEVICE])
        schema = vol.Schema(
            {
                vol.Required(
                    entity_key("sg"), description={"suggested_value": guess.get("sg")}
                ): SENSOR,
                vol.Optional(
                    entity_key("temp"), description={"suggested_value": guess.get("temp")}
                ): SENSOR,
                vol.Optional(
                    entity_key("battery"), description={"suggested_value": guess.get("battery")}
                ): SENSOR,
                vol.Optional(
                    entity_key("velocity"), description={"suggested_value": guess.get("velocity")}
                ): SENSOR,
            }
        )
        return self.async_show_form(step_id="entities", data_schema=schema)

    async def async_step_details(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """A real choice (two buttons) instead of a form that may hold stale values."""
        return self.async_show_menu(step_id="details", menu_options=["details_now", "details_past"])

    async def async_step_details_now(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        og = _float_state(self.hass, self._data.get(entity_key("sg")))
        return await self._details("details_now", user_input, og, _now_minute())

    async def async_step_details_past(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        return await self._details("details_past", user_input, None, None)

    async def _details(
        self, step_id: str, user_input: dict[str, Any] | None, og: float | None, start: str | None
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                start_iso = _to_utc_iso(user_input[CONF_START])
            except ValueError:
                errors[CONF_START] = "invalid_start"
            else:
                data = {
                    **self._data,
                    CONF_OG: user_input[CONF_OG],
                    CONF_START: start_iso,
                    CONF_STATUS: STATUS_ACTIVE,
                    CONF_END: None,
                    CONF_FG: None,
                }
                return self.async_create_entry(title=self._data[CONF_NAME], data=data)
        schema = vol.Schema(
            {
                vol.Required(CONF_OG, description={"suggested_value": og}): GRAVITY,
                vol.Required(
                    CONF_START, description={"suggested_value": start}
                ): selector.DateTimeSelector(),
            }
        )
        return self.async_show_form(step_id=step_id, data_schema=schema, errors=errors)

    # ---- manage an existing batch ------------------------------------

    def _batch(self):
        return self._get_reconfigure_subentry()

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        status = self._batch().data[CONF_STATUS]
        options = ["edit", "finish"] if status == STATUS_ACTIVE else ["edit", "reopen", "archive"]
        return self.async_show_menu(step_id="reconfigure", menu_options=options)

    async def async_step_edit(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        sub = self._batch()
        data = sub.data
        if user_input is not None:
            new = {**data, CONF_NAME: user_input[CONF_NAME], CONF_OG: user_input[CONF_OG]}
            if user_input.get(CONF_FG) is not None:
                new[CONF_FG] = user_input[CONF_FG]
            return self.async_update_and_abort(
                self._get_entry(), sub, title=user_input[CONF_NAME], data=new
            )
        fields: dict[Any, Any] = {
            vol.Required(CONF_NAME, default=sub.title): selector.TextSelector(),
            vol.Required(CONF_OG, default=data[CONF_OG]): GRAVITY,
        }
        if data[CONF_STATUS] != STATUS_ACTIVE:
            fields[vol.Optional(CONF_FG, description={"suggested_value": data.get(CONF_FG)})] = GRAVITY
        return self.async_show_form(step_id="edit", data_schema=vol.Schema(fields))

    async def async_step_finish(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        sub = self._batch()
        data = sub.data
        if user_input is not None:
            fg = user_input.get(CONF_FG)
            if fg is None:
                fg = _float_state(self.hass, data.get(entity_key("sg")))
            new = {
                **data,
                CONF_STATUS: STATUS_COMPLETED,
                CONF_END: dt_util.utcnow().isoformat(),
                CONF_FG: fg,
            }
            return self.async_update_and_abort(self._get_entry(), sub, data=new)
        return self.async_show_form(
            step_id="finish", data_schema=vol.Schema({vol.Optional(CONF_FG): GRAVITY})
        )

    async def async_step_reopen(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        sub = self._batch()
        if user_input is not None:
            new = {**sub.data, CONF_STATUS: STATUS_ACTIVE, CONF_END: None, CONF_FG: None}
            return self.async_update_and_abort(self._get_entry(), sub, data=new)
        return self.async_show_form(step_id="reopen")

    async def async_step_archive(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        sub = self._batch()
        if user_input is not None:
            try:
                await self._get_entry().runtime_data.async_archive(sub.subentry_id)
            except HomeAssistantError:
                return self.async_abort(reason="archive_failed")
            return self.async_abort(reason="archived")
        return self.async_show_form(step_id="archive")
