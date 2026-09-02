"""Light platform for Yeelight Night Mode.

Used when the `entity_type` option is set to "light". Exposes the
moonlight/night mode as a simple on/off light instead of a switch --
useful if you want it to show up alongside other lights, be grouped in
a light group/area card, or be voice-controlled as a light ("turn on
night mode"). Discovery and state logic are shared with the `switch`
platform -- see `discovery.py` and `entity.py`.
"""
from __future__ import annotations

import logging

from homeassistant.components.light import ColorMode, LightEntity
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
    """Discover Yeelight bulbs and add a night-mode light for each one
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
        YeelightNightModeLight(
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


class YeelightNightModeLight(YeelightNightModeEntityMixin, LightEntity):
    """Represents the moonlight/night mode of a single Yeelight bulb as
    a simple on/off light entity (no brightness/color control -- it's
    just a toggle for the mode)."""

    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

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
