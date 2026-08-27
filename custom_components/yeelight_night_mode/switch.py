"""Switch platform for Yeelight Night Mode.

For every config entry of the core `yeelight` integration, this platform:

1. Reads the bulb's IP (host) from that config entry.
2. Queries the bulb directly (LAN API) for the `active_mode` / `nl_br`
   properties. Per the Yeelight LAN API, a bulb returns an *empty string*
   for any property it does not support. If both come back empty, the
   device has no nightlight/moonlight capability (most colour bulbs and
   light strips) and is skipped -- no switch is created for it.
3. For every bulb that *does* report support (mainly "ceiling" models
   with a built-in nightlight), a switch entity is created that:
   - turns moonlight mode on/off via `set_power_mode`,
   - polls the bulb periodically to reflect the mode actually set on the
     device (e.g. if it was changed from the Yeelight app or voice).
"""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_HOST, DOMAIN, SCAN_INTERVAL_SECONDS

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=SCAN_INTERVAL_SECONDS)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Discover Yeelight bulbs and add a night-mode switch for each
    one that reports it actually supports the mode."""

    try:
        import yeelight  # noqa: F401
    except ImportError:
        _LOGGER.error(
            "The 'yeelight' python library is not installed. It should "
            "have been installed automatically as a requirement of this "
            "integration."
        )
        return

    yeelight_entries = hass.config_entries.async_entries("yeelight")
    if not yeelight_entries:
        _LOGGER.warning(
            "No Yeelight integration entries found. Set up the core "
            "Yeelight integration first, then reload Yeelight Night Mode."
        )
        return

    ent_reg = er.async_get(hass)
    entities: list[YeelightNightModeSwitch] = []

    for yee_entry in yeelight_entries:
        host = yee_entry.data.get(CONF_HOST) or yee_entry.options.get(CONF_HOST)
        if not host:
            _LOGGER.debug(
                "Skipping Yeelight entry %s: no host found", yee_entry.entry_id
            )
            continue

        light_entity_id = None
        for reg_entry in er.async_entries_for_config_entry(
            ent_reg, yee_entry.entry_id
        ):
            if reg_entry.domain == "light":
                light_entity_id = reg_entry.entity_id
                break

        name = yee_entry.title or host

        supported = await hass.async_add_executor_job(
            _device_supports_night_mode, host
        )

        if not supported:
            _LOGGER.debug(
                "Skipping '%s' (%s): device does not report support for "
                "night/moonlight mode",
                name,
                host,
            )
            continue

        entities.append(YeelightNightModeSwitch(host, name, light_entity_id))

    if entities:
        async_add_entities(entities, True)
    else:
        _LOGGER.warning(
            "No Yeelight devices reporting nightlight/moonlight support "
            "were found. This mode is typically only available on "
            "'ceiling' models with a built-in nightlight."
        )


def _device_supports_night_mode(host: str) -> bool:
    """Return True if the bulb at `host` supports the night/moonlight mode.

    Runs in the executor thread (blocking socket I/O).
    """
    from yeelight import Bulb

    try:
        bulb = Bulb(host)
        props = bulb.get_properties(["active_mode", "nl_br"])
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Could not query capabilities of %s: %s", host, err)
        return False

    if not props:
        return False

    # get_properties() returns a dict of {property_name: value}. Unsupported
    # properties are either missing from the dict or come back as an empty
    # string / None, depending on library version.
    active_mode = props.get("active_mode")
    nl_br = props.get("nl_br")
    return bool(active_mode not in (None, "")) or bool(nl_br not in (None, ""))


class YeelightNightModeSwitch(SwitchEntity):
    """Represents the moonlight/night mode of a single Yeelight bulb."""

    _attr_icon = "mdi:weather-night"
    _attr_should_poll = True
    _attr_has_entity_name = False

    def __init__(self, host: str, name: str, light_entity_id: str | None) -> None:
        self._host = host
        self._attr_name = f"{name} Night Mode"
        self._attr_unique_id = f"{DOMAIN}_{host}_night_mode"
        self._light_entity_id = light_entity_id
        self._attr_is_on = False
        self._attr_available = True

    @property
    def extra_state_attributes(self) -> dict:
        attrs = {"host": self._host}
        if self._light_entity_id:
            attrs["light_entity_id"] = self._light_entity_id
        return attrs

    def update(self) -> None:
        """Poll the bulb for its current mode (blocking, runs in executor)."""
        from yeelight import Bulb

        try:
            bulb = Bulb(self._host)
            props = bulb.get_properties(["active_mode"])
            active_mode = props.get("active_mode") if props else None
            self._attr_available = True
            # Per the Yeelight LAN API, active_mode == "1" means moonlight.
            self._attr_is_on = active_mode == "1"
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Update failed for %s: %s", self._host, err)
            self._attr_available = False

    def turn_on(self, **kwargs) -> None:
        """Enable moonlight/night mode (blocking, runs in executor)."""
        from yeelight import Bulb, PowerMode

        try:
            bulb = Bulb(self._host)
            bulb.set_power_mode(PowerMode.MOONLIGHT)
            self._attr_is_on = True
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to enable night mode on %s: %s", self._host, err)

    def turn_off(self, **kwargs) -> None:
        """Disable moonlight/night mode, back to normal (blocking)."""
        from yeelight import Bulb, PowerMode

        try:
            bulb = Bulb(self._host)
            bulb.set_power_mode(PowerMode.NORMAL)
            self._attr_is_on = False
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to disable night mode on %s: %s", self._host, err)
