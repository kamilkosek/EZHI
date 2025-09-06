"""Constants for the APsystems EZHI local API integration."""
from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)
DOMAIN = "apsystems_ezhi_local"
UPDATE_INTERVAL = "update_interval"
MIN_VALUE = -1200
MAX_VALUE = 1200
