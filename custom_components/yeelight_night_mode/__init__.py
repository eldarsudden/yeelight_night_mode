"""The Yeelight Night Mode integration.

Automatically creates an entity for every Yeelight bulb (managed by
the core `yeelight` integration) that actually supports the moonlight /
nightlight power mode, and lets you flip it on/off from the UI.

The entity is created as a `switch` or a `light`, depending on the
`entity_type` chosen in the config flow -- changeable afterwards via
the integration's Options, which reloads the entry with the new type.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_ENTITY_TYPE, DOMAIN, ENTITY_TYPE_SWITCH

_LOGGER = logging.getLogger(__name__)


def _platform_for_entry(entry: ConfigEntry) -> str:
    """Which platform ("switch" or "light") this entry is currently
    configured to use, options taking precedence over the original
    setup data."""
    return entry.options.get(
        CONF_ENTITY_TYPE, entry.data.get(CONF_ENTITY_TYPE, ENTITY_TYPE_SWITCH)
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Yeelight Night Mode from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    platform = _platform_for_entry(entry)
    # Remember which platform we actually loaded for this entry: options
    # may already have changed (via the options flow) by the time
    # async_unload_entry runs, so we can't just recompute this then --
    # we need to unload the platform that is actually still loaded.
    hass.data[DOMAIN][entry.entry_id] = platform

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, [platform])
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options (i.e. the entity type) change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    platform = hass.data.get(DOMAIN, {}).pop(entry.entry_id, ENTITY_TYPE_SWITCH)
    return await hass.config_entries.async_unload_platforms(entry, [platform])
