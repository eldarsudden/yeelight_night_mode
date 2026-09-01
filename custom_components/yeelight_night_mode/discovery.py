"""Discovery of Yeelight bulbs that support the moonlight/night mode.

This is shared by the `switch` and `light` platforms -- which one is
actually used is decided by the `entity_type` option (see
`config_flow.py` / `__init__.py`), but both platforms build their
entities from the exact same discovery logic below, so the set of
bulbs and the data attached to each one is identical either way.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import CONF_HOST

_LOGGER = logging.getLogger(__name__)


@dataclass
class NightModeTarget:
    """One Yeelight bulb that supports the moonlight/night mode."""

    host: str
    name: str
    light_entity_id: str | None
    night_sensor_entity_id: str
    device_id: str | None


async def async_discover_targets(hass: HomeAssistant) -> list[NightModeTarget]:
    """Find every Yeelight bulb that already has a core nightlight
    binary_sensor entity.

    The mere *presence* of that entity in the entity registry is the
    signal that the bulb supports the mode -- if it isn't there, the
    bulb doesn't support it and no target is returned for it.
    """

    yeelight_entries = hass.config_entries.async_entries("yeelight")
    if not yeelight_entries:
        _LOGGER.warning(
            "No Yeelight integration entries found. Set up the core "
            "Yeelight integration first, then reload Yeelight Night Mode."
        )
        return []

    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    targets: list[NightModeTarget] = []

    for yee_entry in yeelight_entries:
        host = yee_entry.data.get(CONF_HOST) or yee_entry.options.get(CONF_HOST)
        if not host:
            _LOGGER.debug(
                "Skipping Yeelight entry %s: no host found", yee_entry.entry_id
            )
            continue

        light_entity_id = None
        light_reg_entry = None
        night_sensor_entity_id = None
        night_sensor_device_id = None

        for reg_entry in er.async_entries_for_config_entry(
            ent_reg, yee_entry.entry_id
        ):
            if reg_entry.domain == "light" and light_entity_id is None:
                light_entity_id = reg_entry.entity_id
                light_reg_entry = reg_entry
            elif reg_entry.domain == "binary_sensor" and night_sensor_entity_id is None:
                # This is the core integration's own nightlight sensor.
                # Its mere existence means the core integration has
                # already determined the bulb supports the mode -- we
                # don't need to probe the bulb ourselves.
                night_sensor_entity_id = reg_entry.entity_id
                night_sensor_device_id = reg_entry.device_id

                if reg_entry.disabled_by is not None:
                    # The core integration disables this sensor by
                    # default (it's a secondary/diagnostic entity). We
                    # now depend on its live state, so enable it -- it
                    # will start reporting state after the next reload
                    # of the core Yeelight entry (or of Home Assistant).
                    ent_reg.async_update_entity(
                        reg_entry.entity_id, disabled_by=None
                    )
                    _LOGGER.warning(
                        "Enabled '%s' (was disabled by default) because "
                        "Night Mode needs its state. Reload the Yeelight "
                        "integration (or restart Home Assistant) for it "
                        "to start reporting.",
                        reg_entry.entity_id,
                    )

        # Prefer the nightlight sensor's device -- it's the same physical
        # device as the light in practice -- and fall back to the light's
        # device if, for some reason, it's missing one.
        target_device_id = night_sensor_device_id
        if target_device_id is None and light_reg_entry is not None:
            target_device_id = light_reg_entry.device_id

        name = _resolve_name(hass, yee_entry, light_entity_id, light_reg_entry, host)

        if night_sensor_entity_id is None:
            _LOGGER.debug(
                "Skipping '%s' (%s): no nightlight binary_sensor entity "
                "found for this Yeelight entry -- the core integration "
                "did not detect nightlight support for this device",
                name,
                host,
            )
            continue

        if target_device_id is not None:
            # Safety net: if the device genuinely has no name at all (rare,
            # but happens with some setup paths), give it the same real
            # name we just resolved so it doesn't show as "Unnamed device".
            device = dev_reg.async_get(target_device_id)
            if device is not None and not device.name and not device.name_by_user:
                dev_reg.async_update_device(device.id, name=name)
                _LOGGER.debug(
                    "Named previously unnamed device %s -> %s", device.id, name
                )

        targets.append(
            NightModeTarget(
                host=host,
                name=name,
                light_entity_id=light_entity_id,
                night_sensor_entity_id=night_sensor_entity_id,
                device_id=target_device_id,
            )
        )

    if not targets:
        _LOGGER.warning(
            "No Yeelight devices with a nightlight binary_sensor were "
            "found. This mode is typically only available on 'ceiling' "
            "models with a built-in nightlight."
        )

    return targets


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
