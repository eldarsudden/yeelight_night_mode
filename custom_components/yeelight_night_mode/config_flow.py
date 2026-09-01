"""Config flow for Yeelight Night Mode."""
from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import CONF_ENTITY_TYPE, DOMAIN, ENTITY_TYPE_SWITCH, ENTITY_TYPES


def _entity_type_schema(default: str) -> vol.Schema:
    """Schema for the single "which entity type to create" field,
    shared by the initial setup step and the options flow."""
    return vol.Schema(
        {
            vol.Required(CONF_ENTITY_TYPE, default=default): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=ENTITY_TYPES,
                    translation_key=CONF_ENTITY_TYPE,
                    mode=selector.SelectSelectorMode.LIST,
                )
            )
        }
    )


class YeelightNightModeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Yeelight Night Mode.

    This integration discovers every light that belongs to the core
    Yeelight integration and, for each one, checks whether the device
    itself reports support for the moonlight/night mode before creating
    an entity for it. The only choice to make is which kind of entity
    to create: `switch` (default) or `light`. That choice can be
    changed later via the integration's Options.
    """

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        """Handle the (single) setup step."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(title="Yeelight Night Mode", data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=_entity_type_schema(ENTITY_TYPE_SWITCH)
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return YeelightNightModeOptionsFlow(config_entry)


class YeelightNightModeOptionsFlow(config_entries.OptionsFlow):
    """Let the user change the entity type (switch/light) after setup.

    Changing it triggers a reload of the config entry, which unloads
    the old platform's entities and creates the new ones.
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options.get(
            CONF_ENTITY_TYPE,
            self.config_entry.data.get(CONF_ENTITY_TYPE, ENTITY_TYPE_SWITCH),
        )
        return self.async_show_form(
            step_id="init", data_schema=_entity_type_schema(current)
        )
