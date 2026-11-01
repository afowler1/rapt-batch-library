"""Config flow: one hub entry, and one 'batch' subentry per fermentation."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er, selector
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DEVICE,
    CONF_END,
    CONF_FG,
    CONF_FINISH,
    CONF_NAME,
    CONF_OG,
    CONF_START,
    CONF_STATUS,
    DOMAIN,
    KEYS,
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
    return dt_util.as_utc(parsed).isoformat()


def _float_state(hass, entity_id: str | None) -> float | None:
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    try:
        return float(state.state) if state else None
    except ValueError:
        return None


class RaptBatchesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create the single hub entry."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="RAPT Batches", data={})
        return self.async_show_form(step_id="user")

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {"batch": BatchSubentryFlow}


class BatchSubentryFlow(ConfigSubentryFlow):
    """Wizard: name and pill, then sensors, then OG and start time."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

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
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                start = _to_utc_iso(user_input[CONF_START])
            except ValueError:
                errors[CONF_START] = "invalid_start"
            else:
                data = {
                    **self._data,
                    CONF_OG: user_input[CONF_OG],
                    CONF_START: start,
                    CONF_STATUS: STATUS_ACTIVE,
                    CONF_END: None,
                    CONF_FG: None,
                }
                return self.async_create_entry(title=self._data[CONF_NAME], data=data)
        og = _float_state(self.hass, self._data.get(entity_key("sg")))
        schema = vol.Schema(
            {
                vol.Required(CONF_OG, description={"suggested_value": og}): GRAVITY,
                vol.Required(
                    CONF_START, default=dt_util.now().strftime("%Y-%m-%d %H:%M:%S")
                ): selector.DateTimeSelector(),
            }
        )
        return self.async_show_form(step_id="details", data_schema=schema, errors=errors)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Edit a batch, or finish it by entering the final gravity."""
        subentry = self._get_reconfigure_subentry()
        data = subentry.data
        active = data[CONF_STATUS] == STATUS_ACTIVE
        if user_input is not None:
            new = {**data, CONF_OG: user_input[CONF_OG]}
            if user_input.get(CONF_FG) is not None:
                new[CONF_FG] = user_input[CONF_FG]
            if active and user_input.get(CONF_FINISH):
                new[CONF_STATUS] = STATUS_COMPLETED
                new[CONF_END] = dt_util.utcnow().isoformat()
                if new.get(CONF_FG) is None:
                    new[CONF_FG] = _float_state(self.hass, data.get(entity_key("sg")))
            return self.async_update_and_abort(
                self._get_entry(), subentry, title=user_input[CONF_NAME], data=new
            )
        fields: dict[Any, Any] = {
            vol.Required(CONF_NAME, default=subentry.title): selector.TextSelector(),
            vol.Required(CONF_OG, default=data[CONF_OG]): GRAVITY,
            vol.Optional(
                CONF_FG, description={"suggested_value": data.get(CONF_FG)}
            ): GRAVITY,
        }
        if active:
            fields[vol.Required(CONF_FINISH, default=False)] = selector.BooleanSelector()
        return self.async_show_form(step_id="reconfigure", data_schema=vol.Schema(fields))
