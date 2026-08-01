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
# Only ever read out of the options form to mint a token pair -- deliberately
# not persisted, so the account password never lands in .storage.
CONF_CLOUD_USERNAME = "cloud_username"
CONF_CLOUD_PASSWORD = "cloud_password"
CONF_CLOUD_SCAN_INTERVAL = "cloud_scan_interval"
DEFAULT_CLOUD_SCAN_INTERVAL = 60

# Cached from the local API, not user-entered: the cloud layer needs a deviceId
# and must not be disabled for good by one transient local-API failure.
CONF_CLOUD_DEVICE_ID = "cloud_device_id"

CLOUD_COORDINATOR = "CLOUD_COORDINATOR"

# systemMode values, read off the vendor app's own scenario picker
# ({text: $t("applicationSceN"), value: N}) and cross-checked against both the
# per-mode payload field sets and screenshots of the live app.
#
# TRAP: the i18n key numbers are NOT the mode numbers. applicationSce6 is mode
# 5 and applicationSce5 is mode 3 -- mapping by key name silently swaps two
# modes. See docs/ezhi-cloud-api-from-app-source.md.
SYSTEM_MODE_BALCONY = "1"
SYSTEM_MODE_PORTABLE = "2"
SYSTEM_MODE_AI = "3"
SYSTEM_MODE_LOCAL = "4"
SYSTEM_MODE_BALCONY_AC = "5"
SYSTEM_MODE_NO_BATTERY = "6"

# Mode 5 is deliberately absent: it is the AC-coupled hardware variant, and the
# app only offers it to devices that have it. Offering a mode the hardware does
# not support is a worse failure than not offering it at all.
SYSTEM_MODE_OPTIONS = {
    "Balcony Storage": SYSTEM_MODE_BALCONY,
    "Portable": SYSTEM_MODE_PORTABLE,
    "AI": SYSTEM_MODE_AI,
    "Local": SYSTEM_MODE_LOCAL,
    "No Battery": SYSTEM_MODE_NO_BATTERY,
}
