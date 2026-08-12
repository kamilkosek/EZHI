"""Field tables for the device-diagnostics entities.

Home-Assistant-free on purpose, exactly like the OutputField table in
ble_api.py: the tests run without homeassistant installed, so the tables and
their extraction must not import it. sensor.py and binary_sensor.py map the
plain strings onto their enums -- the string values ARE the enum values, and a
typo therefore fails at setup rather than silently.

Two sources feed these tables.

deviceInfo is already read on every control poll (cloud.py, poll_control_data)
on both local transports. Twenty-four of its twenty-seven fields had no entity
and were parsed and thrown away every cycle; the other three already have one
elsewhere and are deliberately absent here (see INFO_SENSOR_FIELDS).

The six extra identifiers are answered on `get` over MQTT and are read nowhere
else. They are MQTT-only by construction -- see mqtt_api.EXTRA_IDENTIFIERS and
async_poll_all for why that is a design decision and not an oversight.

The measured/raw split is the same as in ble_api.py: a field whose meaning was
established carries unit, device_class and state_class; a field whose meaning
was not carries none of the three and is named after the wire ("batteryCompany"
is called batteryCompany). A friendly name on an unverified field is a guess
wearing the clothes of a fact, and it would read as truth in the history
forever.

Every entity from these tables is EntityCategory.DIAGNOSTIC -- they explain the
device rather than drive it -- so there is no per-field diagnostic flag.

Payloads measured against the real device 2026-08-11 over local_mqtt; see
docs/superpowers/specs/2026-08-11-ezhi-geraete-diagnose-entities.md.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InfoField:
    """One deviceInfo field and how it presents."""

    key: str           # field name in the deviceInfo reply
    uid: str           # unique-id suffix (EzhiCloudEntity convention)
    name: str          # display name; HA prefixes the device name
    unit: str | None = None            # native unit of measurement
    device_class: str | None = None    # Sensor/BinarySensorDeviceClass value
    state_class: str | None = None     # SensorStateClass value
    enabled: bool = False              # entity_registry_enabled_default


# Default ON is a short list on purpose: what a stranger wants without asking.
# The firmware versions, the address, and the link flags that explain why a
# transport is not working. Everything else is off -- static, cryptic, or
# identifying. Nobody should silently gain two dozen entities from an update.
#
# NOT in this table, and each absence is deliberate:
#   rssi     -- EzhiWifiSignalSensor owns it (sensor.py, since 2026-08-08)
#   freeRam  -- already an OutputField ("raw_freeram", ble_api.py); that entry
#               is promoted to enabled rather than duplicated here
#   batCap   -- already BatteryCapacitySensor (sensor.py), from the local HTTP
#               API and enabled by default
# Two entities of one name on one device is the kind of damage an update must
# never do; HA would suffix one of them _2 and neither would be findable.
#
# devVer, deviceId and ip DO get entities even though they are also in the
# device registry (sw_version, serial_number, configuration_url). A registry
# field cannot be recorded and cannot trigger an automation -- a firmware
# change as a state change in the history is a different thing from a line in
# the device dialog.
INFO_SENSOR_FIELDS: tuple[InfoField, ...] = (
    # --- versions and address --------------------------------------------
    InfoField("devVer", "info_firmware_version", "Firmware Version",
              enabled=True),
    InfoField("batFwVer", "info_battery_firmware", "Battery Firmware Version",
              enabled=True),
    InfoField("ip", "info_ip_address", "IP Address", enabled=True),
    InfoField("dspVer", "info_dsp_version", "DSP Version"),
    InfoField("dcmVer", "info_dcm_version", "DCM Version"),
    InfoField("batHwVer", "info_battery_hardware", "Battery Hardware Version"),
    # Empty on this device; info_value turns "" into None rather than into a
    # blank box that reads like a broken sensor.
    InfoField("batVer", "info_bat_ver", "batVer"),
    # --- identifying: off by default -------------------------------------
    # These end up in the recorder if enabled. Nobody gains a serial number or
    # an SSID in their history because they updated an integration.
    InfoField("deviceId", "info_device_id", "Device ID"),
    InfoField("ssid", "info_ssid", "SSID"),
    InfoField("bluetoothMac", "info_bluetooth_mac", "Bluetooth MAC"),
    InfoField("wifiMac", "info_wifi_mac", "WiFi MAC"),
    # --- locale -----------------------------------------------------------
    InfoField("timezone", "info_timezone", "Timezone"),
    InfoField("timeOffset", "info_time_offset", "timeOffset"),
    # --- raw codes: the wire name, because the meaning is not established --
    # country "24" and state "9" are indices into a vendor list nobody has.
    InfoField("country", "info_country", "country"),
    InfoField("state", "info_state", "state"),
    InfoField("batteryCompany", "info_battery_company", "batteryCompany"),
    InfoField("batteryModel", "info_battery_model", "batteryModel"),
    InfoField("model", "info_model", "model"),
    InfoField("dcmType", "info_dcm_type", "dcmType"),
    InfoField("type", "info_type", "type"),
)

INFO_BINARY_FIELDS: tuple[InfoField, ...] = (
    # "1"/"0" on the wire. isOnline is the device's own view of its cloud
    # link -- 0 on an install that reroutes the vendor broker to a local one,
    # which is exactly the kind of thing this entity should make visible.
    InfoField("isOnline", "info_cloud_online", "Cloud Connected",
              device_class="connectivity", enabled=True),
    InfoField("connetStatus", "info_wifi_connected", "WiFi Connected",
              device_class="connectivity", enabled=True),
    # Not connectivity: this is the radio's configured state, not a link. On by
    # default because it answers "why does the Bluetooth transport not work?"
    # in one look.
    InfoField("btEnable", "info_bluetooth_enabled", "Bluetooth Enabled",
              enabled=True),
    InfoField("btConnected", "info_bluetooth_connected", "Bluetooth Connected",
              device_class="connectivity"),
)


def info_value(device: dict, key: str):
    """One deviceInfo field, or None when it is absent or empty.

    Empty string to None deliberately: batVer is "" on this hardware, and an
    empty state renders in HA as a blank box that reads like a broken sensor
    rather than like "the device did not fill this in".
    """
    value = (device or {}).get(key)
    if value is None or value == "":
        return None
    return value


@dataclass(frozen=True)
class ExtraField:
    """One field out of one of the six extra identifier reads."""

    identifier: str    # which read it comes from
    key: str           # field name inside that reply
    uid: str
    name: str
    unit: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    enabled: bool = False
    # supportFunction answers {"supportFunction": {...}} -- its payload sits
    # one level down, under a key of the same name. No other read does this.
    nested: bool = False
    # bindDevice answers {"list": [...]}; the entity is the length, because a
    # list is not a state.
    count: bool = False


# All of these are off by default. They explain exceptional cases -- an
# external meter, a paired device, a firmware feature flag -- and nobody
# should gain twenty-one entities from an update they did not ask for.
EXTRA_SENSOR_FIELDS: tuple[ExtraField, ...] = (
    # --- light: four LED state codes --------------------------------------
    # "10", "11", "12" -- an enumeration whose mapping to colour or blink
    # pattern is not established, so: wire names, no classes.
    ExtraField("light", "sys", "extra_light_sys", "LED sys"),
    ExtraField("light", "ofg", "extra_light_ofg", "LED ofg"),
    ExtraField("light", "bat", "extra_light_bat", "LED bat"),
    ExtraField("light", "wifi", "extra_light_wifi", "LED wifi"),
    # --- alarm: the raw bitmasks ------------------------------------------
    # Kept even though ALARM_SENSORS already decodes si, because the masks
    # carry more: pv reads ...01100000... while si.PvHV and si.PVWE are both 0
    # at the same moment (measured 2026-08-11). Which bit means what is open,
    # so the string goes in raw. 64 characters, well inside HA's 255 limit.
    ExtraField("alarm", "dsp", "extra_alarm_dsp", "alarm dsp"),
    ExtraField("alarm", "battery", "extra_alarm_battery", "alarm battery"),
    ExtraField("alarm", "pv", "extra_alarm_pv", "alarm pv"),
    # --- meterStatus: the external meter -----------------------------------
    # All zero on an install with no meter attached. Left in for the installs
    # that have one -- that is the case where these are the interesting
    # entities, and it is not this one.
    ExtraField("meterStatus", "meterPower", "extra_meter_power", "Meter Power",
               "W", "power", "measurement"),
    # The meter's signal, not the inverter's. The name says Meter so it cannot
    # be confused with EzhiWifiSignalSensor ("WiFi Signal", ble_wifi_rssi) on a
    # dashboard, where the uid is not visible.
    ExtraField("meterStatus", "rssi", "extra_meter_rssi", "Meter Signal",
               "dBm", "signal_strength", "measurement"),
    ExtraField("meterStatus", "company", "extra_meter_company", "meter company"),
    ExtraField("meterStatus", "isTcpNoDataCount", "extra_meter_no_data_count",
               "isTcpNoDataCount"),
    ExtraField("meterStatus", "channel", "extra_meter_channel", "meter channel"),
    ExtraField("meterStatus", "channel0", "extra_meter_channel0",
               "meter channel0"),
    # --- bindDevice: how many devices are paired ---------------------------
    ExtraField("bindDevice", "list", "extra_bound_devices", "Bound Devices",
               count=True),
)

EXTRA_BINARY_FIELDS: tuple[ExtraField, ...] = (
    # --- supportFunction: which features this firmware admits to -----------
    ExtraField("supportFunction", "AIMode", "extra_supports_ai_mode",
               "Supports AIMode", nested=True),
    ExtraField("supportFunction", "acProtect", "extra_supports_ac_protect",
               "Supports acProtect", nested=True),
    ExtraField("supportFunction", "weeklyStrategy", "extra_supports_weekly",
               "Supports weeklyStrategy", nested=True),
    ExtraField("supportFunction", "pvForcedCharging", "extra_supports_pv_forced",
               "Supports pvForcedCharging", nested=True),
    ExtraField("supportFunction", "noBattery", "extra_supports_no_battery",
               "Supports noBattery", nested=True),
    # --- meterStatus / btLock ----------------------------------------------
    ExtraField("meterStatus", "status", "extra_meter_status", "Meter Status"),
    ExtraField("btLock", "status", "extra_bt_lock", "Bluetooth Lock"),
)


def extra_value(extras: dict, field: ExtraField):
    """One field out of the extras payload, or None when its read failed.

    `extras` is {identifier: payload}; a read that failed is simply absent from
    it, so a missing identifier is the normal degraded case and not an error.

    Values come back as they are on the wire. Most fields are strings, but
    meterStatus sends channel, channel0 and isTcpNoDataCount as ints -- there
    is deliberately no coercion here, because turning either into the other
    would be a claim about the field that nothing supports.
    """
    reply = (extras or {}).get(field.identifier)
    if reply is None:
        return None
    if field.nested:
        reply = reply.get(field.identifier) or {}
    value = reply.get(field.key)
    if field.count:
        return len(value) if isinstance(value, list) else None
    if value is None or value == "":
        return None
    return value
