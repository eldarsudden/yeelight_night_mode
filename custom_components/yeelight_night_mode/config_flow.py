"""Config flow for Yeelight Night Mode."""
from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_CUSTOM_ENTITY_NAME,
    CONF_ENTITY_NAME_MODE,
    CONF_ENTITY_TYPE,
    DOMAIN,
    ENTITY_NAME_MODE_NIGHT_SENSOR,
    ENTITY_NAME_MODES,
    ENTITY_TYPE_SWITCH,
    ENTITY_TYPES,
)

CUSTOM_ENTITY_NAME_EXAMPLE = "<light_entity_id>_nightlight_mode"

def _schema(entity_type: str, name_mode: str, custom_name: str) -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_ENTITY_TYPE, default=entity_type): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=ENTITY_TYPES, translation_key=CONF_ENTITY_TYPE,
                mode=selector.SelectSelectorMode.LIST,
            )
        ),
        vol.Required(CONF_ENTITY_NAME_MODE, default=name_mode): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=ENTITY_NAME_MODES, translation_key=CONF_ENTITY_NAME_MODE,
                mode=selector.SelectSelectorMode.LIST,
            )
        ),
        vol.Optional(
            CONF_CUSTOM_ENTITY_NAME,
            default=custom_name or CUSTOM_ENTITY_NAME_EXAMPLE,
        ): selector.TextSelector(
            selector.TextSelectorConfig()
        ),
    })

def _validate_name_mode(user_input: dict) -> str | None:
    if user_input.get(CONF_ENTITY_NAME_MODE) == "custom" and not str(
        user_input.get(CONF_CUSTOM_ENTITY_NAME, "")
    ).strip():
        return "custom_entity_name_required"
    return None

class YeelightNightModeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            error = _validate_name_mode(user_input)
            if error is None:
                return self.async_create_entry(title="Yeelight Night Mode", data=user_input)
        else:
            error = None
        return self.async_show_form(
            step_id="user",
            data_schema=_schema(ENTITY_TYPE_SWITCH, ENTITY_NAME_MODE_NIGHT_SENSOR, ""),
            errors={"custom_entity_name": error} if error else {},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return YeelightNightModeOptionsFlow(config_entry)

class YeelightNightModeOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        current_type = self.config_entry.options.get(
            CONF_ENTITY_TYPE, self.config_entry.data.get(CONF_ENTITY_TYPE, ENTITY_TYPE_SWITCH)
        )
        current_mode = self.config_entry.options.get(
            CONF_ENTITY_NAME_MODE,
            self.config_entry.data.get(CONF_ENTITY_NAME_MODE, ENTITY_NAME_MODE_NIGHT_SENSOR),
        )
        # "Light entity ID" was available in older versions; keep old configs usable
        # while removing that choice from the UI.
        if current_mode == "light":
            current_mode = ENTITY_NAME_MODE_NIGHT_SENSOR
        current_custom = self.config_entry.options.get(
            CONF_CUSTOM_ENTITY_NAME, self.config_entry.data.get(CONF_CUSTOM_ENTITY_NAME, "")
        )
        if user_input is not None:
            error = _validate_name_mode(user_input)
            if error is None:
                return self.async_create_entry(title="", data=user_input)
        else:
            error = None
        return self.async_show_form(
            step_id="init",
            data_schema=_schema(current_type, current_mode, current_custom),
            errors={"custom_entity_name": error} if error else {},
        )
