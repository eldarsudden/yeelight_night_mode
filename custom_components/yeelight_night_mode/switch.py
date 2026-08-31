"""Switch platform for Yeelight Night Mode.

For every config entry of the core `yeelight` integration, this platform:

1. Looks for the `binary_sensor` entity that the core integration itself
   creates for bulbs that support the nightlight/moonlight mode (currently
   only "ceiling" models with a built-in nightlight -- see the Yeelight
   integration docs). The mere *presence* of that entity in the entity
   registry is the signal that the bulb supports the mode; if it isn't
   there, the bulb doesn't support it and no switch is created.
2. For every bulb that does have that sensor, a switch entity is created
   that:
   - is reassigned, directly in the entity registry, onto the SAME
     device as the light/sensor entities (see the note in
     `async_added_to_hass` for why this can't be done via the normal
     `device_info` mechanism), so it shows up in the "Controls" section
     of that device's page instead of on a separate device,
   - turns moonlight mode on/off via `set_power_mode` (direct LAN write),
   - tracks the *existing* nightlight binary_sensor's state to know
     whether the mode is currently on, instead of polling the bulb
     itself.
"""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import CONF_HOST, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Discover Yeelight bulbs and add a night-mode switch for each one
    that already has a core nightlight binary_sensor (i.e. the core
    integration itself has determined it supports the mode)."""

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
                        "the Night Mode switch needs its state. Reload "
                        "the Yeelight integration (or restart Home "
                        "Assistant) for it to start reporting.",
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

        entities.append(
            YeelightNightModeSwitch(
                host, name, light_entity_id, night_sensor_entity_id, target_device_id
            )
        )

    if entities:
        async_add_entities(entities)
    else:
        _LOGGER.warning(
            "No Yeelight devices with a nightlight binary_sensor were "
            "found. This mode is typically only available on 'ceiling' "
            "models with a built-in nightlight."
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


class YeelightNightModeSwitch(SwitchEntity):
    """Represents the moonlight/night mode of a single Yeelight bulb.

    Reads its on/off state from the core integration's own nightlight
    binary_sensor (via a state-change subscription, not its own polling
    loop), and writes changes directly to the bulb over LAN.
    """

    _attr_icon = "mdi:weather-night"
    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_translation_key = "night_mode"

    def __init__(
        self,
        host: str,
        name: str,
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
            self._attr_name = f"{name} Night Mode"

    @property
    def extra_state_attributes(self) -> dict:
        attrs = {"host": self._host, "night_sensor_entity_id": self._night_sensor_entity_id}
        if self._light_entity_id:
            attrs["light_entity_id"] = self._light_entity_id
        return attrs

    async def async_added_to_hass(self) -> None:
        """Attach to the existing device, then seed state and subscribe."""
        await super().async_added_to_hass()

        if self._target_device_id:
            # `device_info` can't cross config entries anymore (see the
            # note in __init__), so we attach to the light's/sensor's
            # existing device the direct way: reassign this entity's own
            # registry row to that device_id. This has no bearing on who
            # *owns* the device -- it just changes which device this
            # entity is grouped under -- so it isn't affected by the
            # "one config entry per device" rule, which only governs
            # device *creation*.
            registry_entry = self.registry_entry
            if registry_entry is not None and registry_entry.device_id != self._target_device_id:
                er.async_get(self.hass).async_update_entity(
                    self.entity_id, device_id=self._target_device_id
                )

        source_state = self.hass.states.get(self._night_sensor_entity_id)
        if source_state is None:
            _LOGGER.warning(
                "'%s': source sensor '%s' has no state in Home Assistant "
                "yet -- it is either disabled, not yet loaded, or no "
                "longer exists. This switch will show as unavailable "
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
