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

# --- Optional cloud control layer -------------------------------------------
# Control commands (on/off, mode, SOC limits) exist only in the EMA cloud; the
# local API is read-only apart from setPower. See docs/ezhi-cloud-api-map.md.
CONF_CLOUD_ACCESS_TOKEN = "cloud_access_token"
CONF_CLOUD_REFRESH_TOKEN = "cloud_refresh_token"
CONF_CLOUD_SCAN_INTERVAL = "cloud_scan_interval"
DEFAULT_CLOUD_SCAN_INTERVAL = 60

CLOUD_COORDINATOR = "CLOUD_COORDINATOR"

# systemMode values. Only these two are verified; mode 3 exists but its meaning
# is unconfirmed, so it is deliberately not offered.
SYSTEM_MODE_PORTABLE = "2"
SYSTEM_MODE_LOCAL = "4"
SYSTEM_MODE_OPTIONS = {
    "Portable": SYSTEM_MODE_PORTABLE,
    "Local": SYSTEM_MODE_LOCAL,
}
