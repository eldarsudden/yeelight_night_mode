"""Shared entity logic for the switch and light representations of a
Yeelight bulb's moonlight/night mode.

Both `YeelightNightModeSwitch` (switch.py) and `YeelightNightModeLight`
(light.py) mix this class in alongside their Home Assistant entity base
class (SwitchEntity / LightEntity), so behaviour -- including the IP
address shown in the entity's details -- stays identical no matter which
entity type was picked in the config/options flow.
"""
from __future__ import annotations

import logging

from homeassistant.core import Event, EventStateChangedData, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class YeelightNightModeEntityMixin:
    """Common behaviour shared by the switch and light entities.

    Reads its on/off state from the core integration's own nightlight
    binary_sensor (via a state-change subscription, not its own polling
    loop), and writes changes directly to the bulb over LAN.

    Expects the concrete class to also inherit from a Home Assistant
    entity base class (SwitchEntity or LightEntity) that provides
    `hass`, `entity_id`, `registry_entry`, `async_write_ha_state`,
    `schedule_update_ha_state`, `async_on_remove`, etc.
    """

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_translation_key = "night_mode"
    _attr_icon = "mdi:weather-night"

    def _init_night_mode(
        self,
        host: str,
        name: str,
        entity_id_object: str,
        light_entity_id: str | None,
        night_sensor_entity_id: str,
        target_device_id: str | None,
    ) -> None:
        self._host = host
        self._light_entity_id = light_entity_id
        self._night_sensor_entity_id = night_sensor_entity_id
        self._target_device_id = target_device_id
        self._attr_unique_id = f"{DOMAIN}_{host}_night_mode"
        self._attr_is_on = False
        self._attr_available = False

        # The entity display name is fixed. The selected naming mode controls
        # only the object ID / entity ID of the newly created entity.
        self._attr_has_entity_name = False
        self._attr_name = "Nightlight Mode"
        self._attr_suggested_object_id = entity_id_object
        self._requested_object_id = entity_id_object

        # NOTE: we deliberately do NOT set `device_info` / `_attr_device_info`
        # here. In current Home Assistant, a device belongs to exactly one
        # config entry -- identifiers are only matched against devices of
        # the *same* config entry. Since this entry's device (the light's)
        # is owned by the core `yeelight` entry, not ours, returning
        # matching identifiers here would just create a second, separate
        # device under our own entry instead of attaching to the existing
        # one. Instead, we attach directly by device_id in
        # `async_added_to_hass`, see there for details.
        if not target_device_id:
            # Fallback: no matching device found (e.g. YAML-configured
            # Yeelight without a device registry entry). Keep a readable
            # standalone name rather than failing setup.
            self._attr_has_entity_name = False
            self._attr_name = "Nightlight Mode"

    @property
    def extra_state_attributes(self) -> dict:
        """Extra attributes shown in the entity's "Attributes" panel,
        including the bulb's current IP address."""
        attrs = {
            "ip_address": self._host,
            "night_sensor_entity_id": self._night_sensor_entity_id,
        }
        if self._light_entity_id:
            attrs["light_entity_id"] = self._light_entity_id
        return attrs

    async def async_added_to_hass(self) -> None:
        """Attach to the existing device, then seed state and subscribe."""
        await super().async_added_to_hass()

        # Enforce the configured Entity ID naming after registration.
        # LightEntity can otherwise retain the default object ID generated
        # from its display name (for example light.night_mode).
        registry = er.async_get(self.hass)
        if self.registry_entry is not None:
            domain = self.entity_id.split(".", 1)[0]
            requested_entity_id = f"{domain}.{self._requested_object_id}"
            if self.entity_id != requested_entity_id:
                try:
                    registry.async_update_entity(
                        self.entity_id, new_entity_id=requested_entity_id
                    )
                except ValueError as err:
                    _LOGGER.warning(
                        "Could not set requested entity ID '%s' for '%s': %s",
                        requested_entity_id,
                        self.entity_id,
                        err,
                    )

        if self._target_device_id:
            # `device_info` can't cross config entries anymore (see the
            # note in `_init_night_mode`), so we attach to the light's/
            # sensor's existing device the direct way: reassign this
            # entity's own registry row to that device_id. This has no
            # bearing on who *owns* the device -- it just changes which
            # device this entity is grouped under -- so it isn't affected
            # by the "one config entry per device" rule, which only
            # governs device *creation*.
            registry_entry = self.registry_entry
            if registry_entry is not None and registry_entry.device_id != self._target_device_id:
                registry.async_update_entity(
                    self.entity_id, device_id=self._target_device_id
                )

        source_state = self.hass.states.get(self._night_sensor_entity_id)
        if source_state is None:
            _LOGGER.warning(
                "'%s': source sensor '%s' has no state in Home Assistant "
                "yet -- it is either disabled, not yet loaded, or no "
                "longer exists. This entity will show as unavailable "
                "until that sensor reports a state.",
                self.entity_id,
                self._night_sensor_entity_id,
            )
        else:
            _LOGGER.debug(
                "'%s': seeding state from '%s' = %s",
                self.entity_id,
                self._night_sensor_entity_id,
                source_state.state,
            )
        self._apply_sensor_state(source_state)
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [self._night_sensor_entity_id],
                self._handle_sensor_event,
            )
        )

    @callback
    def _handle_sensor_event(self, event: Event[EventStateChangedData]) -> None:
        self._apply_sensor_state(event.data.get("new_state"))
        self.async_write_ha_state()

    def _apply_sensor_state(self, state) -> None:
        if state is None or state.state in ("unknown", "unavailable"):
            self._attr_available = False
            return
        self._attr_available = True
        self._attr_is_on = state.state == "on"

    def turn_on(self, **kwargs) -> None:
        """Enable moonlight/night mode (blocking, runs in executor)."""
        from yeelight import Bulb, PowerMode

        try:
            bulb = Bulb(self._host)
            bulb.set_power_mode(PowerMode.MOONLIGHT)
            # Optimistic update -- the authoritative state will arrive
            # shortly via the nightlight sensor's next state change.
            self._attr_is_on = True
            self.schedule_update_ha_state()
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to enable night mode on %s: %s", self._host, err)

    def turn_off(self, **kwargs) -> None:
        """Disable moonlight/night mode, back to normal (blocking)."""
        from yeelight import Bulb, PowerMode

        try:
            bulb = Bulb(self._host)
            bulb.set_power_mode(PowerMode.NORMAL)
            self._attr_is_on = False
            self.schedule_update_ha_state()
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to disable night mode on %s: %s", self._host, err)
