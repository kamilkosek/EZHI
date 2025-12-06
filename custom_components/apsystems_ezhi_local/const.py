"""Constants for the APsystems EZHI local API integration."""
from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)
DOMAIN = "apsystems_ezhi_local"

# Scan intervals
SCAN_INTERVAL_OUTPUT = "scan_interval_output"
SCAN_INTERVAL_ALARM = "scan_interval_alarm"

# Legacy support (for migration from old config)
UPDATE_INTERVAL = "update_interval"

# Default intervals (seconds)
DEFAULT_SCAN_INTERVAL_OUTPUT = 5
DEFAULT_SCAN_INTERVAL_ALARM = 60

# Power limits
MIN_VALUE = -1200
MAX_VALUE = 1200
