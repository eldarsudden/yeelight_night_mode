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
   - attaches to the SAME device as the light entity, so it shows up in
     the "Controls" section of that device's page (no separate device,
     no separate entry in the entity list),
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
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
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
    dev_reg = dr.async_get(hass)
    entities: list[YeelightNightModeSwitch] = []

    for yee_entry in yeelight_entries:
        host = yee_entry.data.get(CONF_HOST) or yee_entry.options.get(CONF_HOST)
        if not host:
            _LOGGER.debug(
                "Skipping Yeelight entry %s: no host found", yee_entry.entry_id
            )
            continue

        light_entity_id = None
        light_reg_entry = None
        device = None
        for reg_entry in er.async_entries_for_config_entry(
            ent_reg, yee_entry.entry_id
        ):
            if reg_entry.domain == "light":
                light_entity_id = reg_entry.entity_id
                light_reg_entry = reg_entry
                if reg_entry.device_id:
                    device = dev_reg.async_get(reg_entry.device_id)
                break

        name = _resolve_name(hass, yee_entry, light_entity_id, light_reg_entry, host)

        device_identifiers = None
        if device is not None:
            device_identifiers = device.identifiers
            # Safety net: if the device genuinely has no name at all (rare,
            # but happens with some setup paths), give it the same real
            # name we just resolved so it doesn't show as "Unnamed device".
            if not device.name and not device.name_by_user:
                dev_reg.async_update_device(device.id, name=name)
                _LOGGER.debug("Named previously unnamed device %s -> %s", device.id, name)

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

        entities.append(
            YeelightNightModeSwitch(host, name, light_entity_id, device_identifiers)
        )

    if entities:
        async_add_entities(entities, True)
    else:
        _LOGGER.warning(
            "No Yeelight devices reporting nightlight/moonlight support "
            "were found. This mode is typically only available on "
            "'ceiling' models with a built-in nightlight."
        )


def _resolve_name(
    hass: HomeAssistant,
    yee_entry: ConfigEntry,
    light_entity_id: str | None,
    light_reg_entry,
    host: str,
) -> str:
    """Best-effort *real* name for a bulb, in priority order:

    1. The light's current friendly_name (state machine) -- this is what
       the user actually sees for the light everywhere in the UI.
    2. User-renamed entity in the entity registry.
    3. The entity's original (integration-provided) name.
    4. The Yeelight config entry title.
    5. Raw IP as a last resort.
    """
    if light_entity_id:
        state = hass.states.get(light_entity_id)
        if state is not None:
            friendly_name = state.attributes.get("friendly_name")
            if friendly_name:
                return friendly_name

    if light_reg_entry is not None:
        if light_reg_entry.name:
            return light_reg_entry.name
        if light_reg_entry.original_name:
            return light_reg_entry.original_name

    if yee_entry.title:
        return yee_entry.title

    return host


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
    _attr_has_entity_name = True
    _attr_translation_key = "night_mode"

    def __init__(
        self,
        host: str,
        name: str,
        light_entity_id: str | None,
        device_identifiers: set[tuple[str, str]] | None,
    ) -> None:
        self._host = host
        self._light_entity_id = light_entity_id
        self._attr_unique_id = f"{DOMAIN}_{host}_night_mode"
        self._attr_is_on = False
        self._attr_available = True

        if device_identifiers:
            # Attach to the light's existing device -- this is what makes
            # the switch appear in the "Controls" section of that
            # device's page instead of as a separate, unlinked entity.
            self._attr_device_info = DeviceInfo(identifiers=device_identifiers)
        else:
            # Fallback: no matching device found (e.g. YAML-configured
            # Yeelight without a device registry entry). Keep a readable
            # standalone name rather than failing setup.
            self._attr_has_entity_name = False
            self._attr_name = f"{name} Night Mode"

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
