"""Switch platform for Yeelight Night Mode.

Used when the `entity_type` option is set to "switch" (the default).
Discovery and state logic are shared with the `light` platform -- see
`discovery.py` and `entity.py`.
"""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .discovery import async_discover_targets
from .entity import YeelightNightModeEntityMixin

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Discover Yeelight bulbs and add a night-mode switch for each one
    that supports the mode."""

    try:
        import yeelight  # noqa: F401
    except ImportError:
        _LOGGER.error(
            "The 'yeelight' python library is not installed. It should "
            "have been installed automatically as a requirement of this "
            "integration."
        )
        return

    targets = await async_discover_targets(hass, entry)
    async_add_entities(
        YeelightNightModeSwitch(
            target.host,
            target.name,
            target.entity_id_object,
            target.display_name,
            target.light_entity_id,
            target.night_sensor_entity_id,
            target.device_id,
        )
        for target in targets
    )


class YeelightNightModeSwitch(YeelightNightModeEntityMixin, SwitchEntity):
    """Represents the moonlight/night mode of a single Yeelight bulb as
    a switch entity."""

    def __init__(
        self,
        host: str,
        name: str,
        entity_id_object: str,
        display_name: str,
        light_entity_id: str | None,
        night_sensor_entity_id: str,
        target_device_id: str | None,
    ) -> None:
        self._init_night_mode(
            host, name, entity_id_object, display_name, light_entity_id, night_sensor_entity_id, target_device_id
        )
