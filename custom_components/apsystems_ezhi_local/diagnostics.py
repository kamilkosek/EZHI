"""Diagnostics for the APsystems EZHI integration.

Exists because almost every question about this integration is "which
transport, and what did the device actually answer" -- and the answer has so
far meant asking someone to paste log lines, which is how device serials and
WiFi credentials end up in public issue threads.

Everything identifying is redacted: the tokens and the account name, the
device id and serial, both MAC addresses, the SSID and the address the
inverter sits on. What remains is the shape of the installation, which is what
a diagnosis needs.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

from .const import (
    CLOUD_COORDINATOR,
    CONF_CLOUD_ACCESS_TOKEN,
    CONF_CLOUD_DEVICE_ID,
    CONF_CLOUD_PASSWORD,
    CONF_CLOUD_REFRESH_TOKEN,
    CONF_CLOUD_USERNAME,
    DOMAIN,
    resolve_transport,
    wants_control_layer,
)

# Config-entry keys. CONF_IP_ADDRESS is a local address and harmless on its
# own, but it pins the subnet a reporter is on, and it is never needed to
# understand a report.
TO_REDACT = {
    CONF_CLOUD_ACCESS_TOKEN,
    CONF_CLOUD_REFRESH_TOKEN,
    CONF_CLOUD_PASSWORD,
    CONF_CLOUD_USERNAME,
    CONF_CLOUD_DEVICE_ID,
    "ip_address",
    "host",
}

# Wire field names, whatever nesting they turn up in. deviceId and sn identify
# the unit; the MACs and the SSID identify the household.
#
# The names here are the ones the device actually sends -- see device_fields.py.
# The first version of this list carried "bleMac", which exists nowhere in this
# project: the real field is bluetoothMac, so the Bluetooth MAC went into the
# dump unredacted while the list looked complete. test_diagnostics pins these
# against device_fields now, so the next rename cannot slip through the same way.
TO_REDACT_WIRE = {
    "deviceId", "sn", "serialNumber",
    "wifiMac", "bluetoothMac", "bleMac", "mac", "macAddress",
    "ssid", "SSID",
    "ip", "ipAddr", "ipAddress",
    "userName", "password", "token",
}


def _clean(value: Any) -> Any:
    """Redact by field name at any depth.

    Recursive rather than a flat pass because the device's replies nest: the
    interesting parts of deviceInfo and outputData sit one or two levels down,
    and a flat redaction would leave the serial in place while looking like it
    had done its job.
    """
    if isinstance(value, dict):
        return {
            key: "**REDACTED**" if key in TO_REDACT_WIRE else _clean(inner)
            for key, inner in value.items()
        }
    if isinstance(value, list):
        return [_clean(item) for item in value]
    return value


async def async_get_config_entry_diagnostics(
    hass: "HomeAssistant", entry: "ConfigEntry"
) -> dict[str, Any]:
    """The state a diagnosis needs, with nothing identifying in it."""
    # Imported here rather than at module level so the redaction helpers below
    # can be tested without Home Assistant, like everything else in this
    # package. Redaction is the whole point of this file; it should not be the
    # one part with no test.
    from homeassistant.components.diagnostics import async_redact_data

    stored = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    coordinator = stored.get("COORDINATOR")
    cloud_coordinator = stored.get(CLOUD_COORDINATOR)

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "version": entry.version,
        },
        "transport": {
            # The configured choice and whether the control layer was actually
            # built. Those two disagreeing is a failure mode in its own right:
            # a transport that could not be set up used to leave the entry
            # quietly on another one.
            "configured": resolve_transport(entry.data),
            "control_layer_wanted": wants_control_layer(entry.data),
            "control_layer_built": cloud_coordinator is not None,
            "has_credentials": bool(entry.data.get(CONF_CLOUD_REFRESH_TOKEN)),
        },
        "local": {
            "last_update_success": getattr(
                coordinator, "last_update_success", None),
            "data": _clean(_as_dict(getattr(coordinator, "data", None))),
        },
        "control": {
            "last_update_success": getattr(
                cloud_coordinator, "last_update_success", None),
            "data": _clean(_as_dict(getattr(cloud_coordinator, "data", None))),
        },
    }


def _as_dict(data: Any) -> Any:
    """Coordinator payloads are dataclass-ish objects or plain dicts."""
    if data is None or isinstance(data, (dict, list, str, int, float, bool)):
        return data
    for attribute in ("__dict__", "_asdict"):
        candidate = getattr(data, attribute, None)
        if callable(candidate):
            return candidate()
        if isinstance(candidate, dict):
            return dict(candidate)
    return repr(data)
