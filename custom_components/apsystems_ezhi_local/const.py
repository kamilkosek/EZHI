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
# local API is read-only apart from setPower.
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
# The held BLE link, kept only so unloading the entry can close it. An open
# client would block the next connect after a reload.
BLE_LINK = "BLE_LINK"

# --- which wire the control commands take -----------------------------------
# The same commands can go through the vendor cloud or straight to the device
# over Bluetooth. Cloud stays the default forever: an installation that
# upgrades into this option must not change behaviour because of the upgrade.
# Bluetooth still needs the cloud credentials -- they are what opens the
# device's radio window when it has timed out (see ble_connect.py).
CONF_CONTROL_TRANSPORT = "control_transport"
TRANSPORT_CLOUD = "cloud"
TRANSPORT_BLUETOOTH = "bluetooth"
DEFAULT_CONTROL_TRANSPORT = TRANSPORT_CLOUD
CONTROL_TRANSPORTS = (TRANSPORT_CLOUD, TRANSPORT_BLUETOOTH)


def resolve_transport(entry_data) -> str:
    """Read the transport out of an entry's data, falling back to cloud.

    Everything that is not an explicit, known choice resolves to cloud: a
    missing key (never configured), an empty string (the frontend strips
    cleared fields before submitting) and an unknown value (a downgrade from a
    later version that offers more transports). Picking a transport on a guess
    would mean changing how a device is controlled without being told to.
    """
    value = (entry_data or {}).get(CONF_CONTROL_TRANSPORT)
    if not value:
        return DEFAULT_CONTROL_TRANSPORT
    if value not in CONTROL_TRANSPORTS:
        LOGGER.warning(
            "Unknown control transport %r configured; falling back to %s",
            value, DEFAULT_CONTROL_TRANSPORT,
        )
        return DEFAULT_CONTROL_TRANSPORT
    return value

# systemMode values, read off the vendor app's own scenario picker
# ({text: $t("applicationSceN"), value: N}) and cross-checked against both the
# per-mode payload field sets and screenshots of the live app.
#
# TRAP: the i18n key numbers are NOT the mode numbers. applicationSce6 is mode
# 5 and applicationSce5 is mode 3 -- mapping by key name silently swaps two
# modes.
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

SYSTEM_MODE_NAMES = {value: name for name, value in SYSTEM_MODE_OPTIONS.items()}

# Every mode the device can actually be in, including the two with no entity
# option (the AC-coupled variant, and No Battery which is write-guarded).
SYSTEM_MODE_ALL = frozenset({
    SYSTEM_MODE_BALCONY, SYSTEM_MODE_PORTABLE, SYSTEM_MODE_AI,
    SYSTEM_MODE_LOCAL, SYSTEM_MODE_BALCONY_AC, SYSTEM_MODE_NO_BATTERY,
})


def local_setpoint_ignored_by(mode: str | None) -> str | None:
    """Name of the mode that will ignore a local setPower write, or None.

    Measured on firmware 1.9.0.16 across all four selectable modes, with the
    setpoint written to -300 W: the inverter followed it in Local (grid flow
    went from -146 W to +272 W) and ignored it in Balcony Storage, Portable and
    AI, where it kept running its own strategy. setPower answers SUCCESS in
    every mode, so nothing about the response tells the caller their write did
    nothing. The vendor app agrees: it only sends a power target
    (`userSetPower`) in the Balcony Storage and Portable scenarios, and its
    Local screen offers no power control at all -- that is the slot the local
    API writes into.

    None when the mode is unknown, not just when it is Local: the cloud side is
    optional, and warning on a guess is worse than staying quiet. "Unknown"
    includes a value that does not normalise to one of the six real modes --
    wire_str leaves "4.0" and " 4 " as they are, and those must not read as
    "not Local" and warn on every write while the inverter sits in Local.
    """
    if mode is None or mode == SYSTEM_MODE_LOCAL:
        return None
    if mode not in SYSTEM_MODE_ALL:
        return None
    return SYSTEM_MODE_NAMES.get(mode, f"mode {mode}")
