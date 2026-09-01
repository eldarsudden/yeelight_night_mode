"""Constants for the Yeelight Night Mode integration."""

DOMAIN = "yeelight_night_mode"

# How often (seconds) each switch polls its bulb for the current mode.
SCAN_INTERVAL_SECONDS = 30

CONF_HOST = "host"

# Which kind of entity to create for each bulb's night mode.
CONF_ENTITY_TYPE = "entity_type"
ENTITY_TYPE_SWITCH = "switch"
ENTITY_TYPE_LIGHT = "light"
ENTITY_TYPES = [ENTITY_TYPE_SWITCH, ENTITY_TYPE_LIGHT]
