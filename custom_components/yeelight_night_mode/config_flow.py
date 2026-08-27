"""Config flow for Yeelight Night Mode."""
from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN


class YeelightNightModeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Yeelight Night Mode.

    This integration needs no configuration: it discovers every light
    that belongs to the core Yeelight integration and, for each one,
    checks whether the device itself reports support for the
    moonlight/night mode before creating a switch for it.
    """

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        """Handle the (single) setup step."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(title="Yeelight Night Mode", data={})

        return self.async_show_form(step_id="user", data_schema=vol.Schema({}))
