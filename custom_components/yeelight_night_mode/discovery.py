"""Discovery of Yeelight bulbs that support moonlight/night mode."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_CUSTOM_ENTITY_NAME,
    CONF_ENTITY_NAME_MODE,
    CONF_HOST,
    ENTITY_NAME_MODE_CUSTOM,
    ENTITY_NAME_MODE_NIGHT_SENSOR,
)

_LOGGER = logging.getLogger(__name__)

@dataclass
class NightModeTarget:
    host: str
    name: str
    entity_id_object: str
    light_entity_id: str | None
    night_sensor_entity_id: str
    device_id: str | None

async def async_discover_targets(hass: HomeAssistant, entry: ConfigEntry) -> list[NightModeTarget]:
    yeelight_entries = hass.config_entries.async_entries("yeelight")
    if not yeelight_entries:
        _LOGGER.warning("No Yeelight integration entries found.")
        return []

    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    name_mode = entry.options.get(
        CONF_ENTITY_NAME_MODE,
        entry.data.get(CONF_ENTITY_NAME_MODE, ENTITY_NAME_MODE_NIGHT_SENSOR),
    )
    custom_name = entry.options.get(
        CONF_CUSTOM_ENTITY_NAME, entry.data.get(CONF_CUSTOM_ENTITY_NAME, "")
    )
    targets = []

    for yee_entry in yeelight_entries:
        host = yee_entry.data.get(CONF_HOST) or yee_entry.options.get(CONF_HOST)
        if not host:
            continue
        light_entity_id = None
        light_reg_entry = None
        night_sensor_entity_id = None
        night_sensor_device_id = None
        for reg_entry in er.async_entries_for_config_entry(ent_reg, yee_entry.entry_id):
            if reg_entry.domain == "light" and light_entity_id is None:
                light_entity_id = reg_entry.entity_id
                light_reg_entry = reg_entry
            elif reg_entry.domain == "binary_sensor" and night_sensor_entity_id is None:
                night_sensor_entity_id = reg_entry.entity_id
                night_sensor_device_id = reg_entry.device_id
                if reg_entry.disabled_by is not None:
                    ent_reg.async_update_entity(reg_entry.entity_id, disabled_by=None)
                    _LOGGER.warning(
                        "Enabled '%s' because Night Mode needs its state.",
                        reg_entry.entity_id,
                    )

        target_device_id = night_sensor_device_id
        if target_device_id is None and light_reg_entry is not None:
            target_device_id = light_reg_entry.device_id

        name = _resolve_name(hass, yee_entry, light_entity_id, light_reg_entry, host)
        if night_sensor_entity_id is None:
            continue

        if target_device_id is not None:
            device = dev_reg.async_get(target_device_id)
            if device is not None and not device.name and not device.name_by_user:
                dev_reg.async_update_device(device.id, name=name)

        entity_id_object = _resolve_entity_id_object(
            name_mode, custom_name, light_entity_id, night_sensor_entity_id, name
        )
        targets.append(NightModeTarget(
            host=host, name=name, entity_id_object=entity_id_object,
            light_entity_id=light_entity_id,
            night_sensor_entity_id=night_sensor_entity_id,
            device_id=target_device_id,
        ))
    return targets

def _resolve_name(hass, yee_entry, light_entity_id, light_reg_entry, host) -> str:
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

def _object_id(entity_id: str | None) -> str | None:
    if not entity_id:
        return None
    return entity_id.split(".", 1)[1] if "." in entity_id else entity_id

def _resolve_entity_id_object(
    mode: str,
    custom_name: str,
    light_entity_id: str | None,
    night_sensor_entity_id: str,
    fallback_name: str,
) -> str:
    """Resolve the object_id used for the created entity.

    The visible entity name is always "Nightlight Mode"; this value controls
    only the entity ID/object ID.
    """
    if mode == ENTITY_NAME_MODE_CUSTOM:
        return custom_name.replace(
            "<binary_sensor_id>", _object_id(night_sensor_entity_id) or ""
        ).replace("<light_entity_id>", _object_id(light_entity_id) or "")
    return _object_id(night_sensor_entity_id) or fallback_name
