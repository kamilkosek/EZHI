"""The device-diagnostics field tables and their value extraction.

Every payload here was measured against a real device over the local_mqtt
transport, through apsystems_ezhi_local.ble_raw_get. They are the contract these
tables are written against: a table entry for a field the device does not send is
a permanently unknown entity, and a field the device sends with no table entry is
a value fetched and thrown away every poll.

The identifying values - serial, MAC addresses, IP and SSID - are placeholders.
Only their shape matters to these tests, and a real serial in a public repository
identifies somebody's hardware for good.
"""
from __future__ import annotations

from ezhi_component.device_fields import (
    EXTRA_BINARY_FIELDS,
    EXTRA_SENSOR_FIELDS,
    INFO_BINARY_FIELDS,
    INFO_SENSOR_FIELDS,
    extra_value,
    info_value,
)

DEVICE_INFO = {
    "deviceId": "D00000000000", "dcmType": "C3", "devVer": "EZHI 1.9.0.16",
    "dcmVer": "0.1.34.0", "model": "1", "dspVer": "1.1.6.15", "batVer": "",
    "batFwVer": "3.2.1", "batHwVer": "5.2.1", "batCap": "7.20", "type": "EZHI",
    "bluetoothMac": "AA:BB:CC:DD:EE:11", "wifiMac": "AA:BB:CC:DD:EE:10",
    "isOnline": "0", "country": "24", "state": "9", "timezone": "Europe/Berlin",
    "timeOffset": "7200000", "batteryCompany": "4", "batteryModel": "2",
    "connetStatus": "1", "ip": "192.0.2.10", "ssid": "EXAMPLE-SSID", "rssi": -50,
    "btEnable": "0", "btConnected": "0", "freeRam": 46404,
}

EXTRAS = {
    "light": {"ofg": "10", "sys": "10", "bat": "12", "wifi": "10"},
    "alarm": {
        "dsp": "0" * 64,
        "battery": "0" * 32,
        "pv": "00000000000001100000000000000000",
    },
    "supportFunction": {"supportFunction": {
        "AIMode": "1", "acProtect": "1", "weeklyStrategy": "1",
        "pvForcedCharging": "1", "noBattery": "1"}},
    "meterStatus": {"status": "1", "company": "0", "meterPower": "0",
                    "isTcpNoDataCount": 5, "channel": 11, "channel0": 0,
                    "rssi": 0},
    "btLock": {"status": "1"},
    "bindDevice": {"list": []},
}

# The twenty si protection flags. binary_sensor.ALARM_SENSORS already covers
# all twenty of them, out of the local HTTP API's getAlarm.
SI_CODES = frozenset(
    "BatLTP BatHTP BatCE BatHV BatLV BatHI BatE DTP EE SBS ACA OfOI PvHV "
    "PvOC IRDE PVWE OfGS BCC BCI VRP".split())

ALL_INFO = INFO_SENSOR_FIELDS + INFO_BINARY_FIELDS
ALL_EXTRA = EXTRA_SENSOR_FIELDS + EXTRA_BINARY_FIELDS


# --- deviceInfo ------------------------------------------------------------

def test_every_info_field_is_in_the_measured_reply():
    """No table entry invents a field the device does not send."""
    for field in ALL_INFO:
        assert field.key in DEVICE_INFO, f"{field.key} is not in the reply"


def test_the_already_owned_fields_have_no_second_entity():
    """Three deviceInfo fields already have entities elsewhere in this
    integration. A table entry here would put a second entity of the same name
    on the same device, and HA would suffix one of them _2 -- exactly the kind
    of damage an update must not do."""
    keys = {f.key for f in ALL_INFO}
    assert "rssi" not in keys      # EzhiWifiSignalSensor, sensor.py
    assert "freeRam" not in keys   # OutputField raw_freeram, ble_api.py
    assert "batCap" not in keys    # BatteryCapacitySensor, sensor.py


def test_the_table_covers_every_remaining_field():
    """27 measured fields minus the three already owned = 24 entities. Pinned
    as numbers so a field added by a firmware update shows up as a failing test
    rather than as silence."""
    owned = {"rssi", "freeRam", "batCap"}
    covered = {f.key for f in ALL_INFO}
    assert covered == set(DEVICE_INFO) - owned
    assert len(covered) == 24
    assert len(INFO_SENSOR_FIELDS) == 20
    assert len(INFO_BINARY_FIELDS) == 4


def test_six_info_fields_are_on_by_default():
    on = {f.key for f in ALL_INFO if f.enabled}
    assert on == {"devVer", "batFwVer", "ip", "isOnline", "connetStatus",
                  "btEnable"}


def test_identifying_fields_are_off_by_default():
    """A serial number or an SSID must not land in a stranger's recorder
    because they updated the integration."""
    off = {f.key for f in ALL_INFO if not f.enabled}
    for key in ("deviceId", "ssid", "bluetoothMac", "wifiMac"):
        assert key in off, f"{key} must be disabled by default"


def test_the_binary_fields_are_exactly_the_boolean_ones():
    """Everything in the binary table reads "1"/"0" on the wire; anything else
    would silently become False."""
    for field in INFO_BINARY_FIELDS:
        assert DEVICE_INFO[field.key] in ("0", "1")


def test_info_value_reads_a_present_field():
    assert info_value(DEVICE_INFO, "devVer") == "EZHI 1.9.0.16"
    assert info_value(DEVICE_INFO, "ip") == "192.0.2.10"


def test_info_value_is_none_on_a_missing_field():
    """Older firmware may not send every field, and an empty poll result is
    the normal degraded case. None, never a guess."""
    assert info_value({}, "devVer") is None
    assert info_value(None, "devVer") is None


def test_info_value_turns_an_empty_string_into_none():
    """batVer is "" on this device. An empty state renders as a blank box that
    reads like a broken sensor rather than like "not filled in"."""
    assert info_value(DEVICE_INFO, "batVer") is None


# --- the six extra reads ---------------------------------------------------

def test_every_extra_field_is_in_a_measured_reply():
    for field in ALL_EXTRA:
        reply = EXTRAS[field.identifier]
        if field.nested:
            reply = reply[field.identifier]
        assert field.key in reply, f"{field.identifier}.{field.key} not in the reply"


def test_no_extra_field_duplicates_an_si_flag():
    """si is fully covered by ALARM_SENSORS. A second set of the same twenty
    entities is the failure this test exists to prevent."""
    for field in ALL_EXTRA:
        assert field.key not in SI_CODES


def test_no_extra_field_duplicates_deviceinfo():
    """wifiStatus and caTz carry nothing deviceInfo does not already have, and
    are read nowhere for that reason. light and alarm have their own namespace
    (sys/ofg/bat/wifi, dsp/battery/pv) and are exempt."""
    info_keys = {f.key for f in ALL_INFO}
    for field in ALL_EXTRA:
        if field.identifier in ("light", "alarm"):
            continue
        assert field.key not in info_keys, (
            f"{field.key} is already a deviceInfo entity")


def test_unique_ids_do_not_collide():
    """unique-ids are forever on a public fork; a collision here is not
    fixable later without breaking someone's history."""
    uids = [f.uid for f in ALL_INFO] + [f.uid for f in ALL_EXTRA]
    assert len(uids) == len(set(uids))
    # EzhiWifiSignalSensor's; nothing may reuse it.
    assert "ble_wifi_rssi" not in uids


def test_display_names_do_not_collide():
    """Two entities of one name on one device are indistinguishable on a
    dashboard, where the uid is not visible. meterStatus.rssi is the near miss
    this guards: "Meter Signal" against the existing "WiFi Signal"."""
    names = [f.name for f in ALL_INFO] + [f.name for f in ALL_EXTRA]
    assert len(names) == len(set(names))
    assert "WiFi Signal" not in names


def test_every_extra_is_off_by_default():
    """These explain exceptional cases. Nobody gains twenty-one entities from
    an update they did not ask for."""
    for field in ALL_EXTRA:
        assert not field.enabled


def test_the_extra_table_has_the_expected_shape():
    assert len(EXTRA_SENSOR_FIELDS) == 14
    assert len(EXTRA_BINARY_FIELDS) == 7


def test_extra_value_reads_a_nested_field():
    """supportFunction wraps its payload in a second key of the same name."""
    field = next(f for f in EXTRA_BINARY_FIELDS if f.key == "AIMode")
    assert extra_value(EXTRAS, field) == "1"


def test_extra_value_reads_a_flat_field():
    field = next(f for f in EXTRA_SENSOR_FIELDS if f.key == "pv")
    assert extra_value(EXTRAS, field) == "00000000000001100000000000000000"


def test_extra_value_survives_an_int_payload():
    """Most fields are strings, but meterStatus sends channel and
    isTcpNoDataCount as ints. A generic extraction must not assume either."""
    field = next(f for f in EXTRA_SENSOR_FIELDS if f.key == "channel")
    assert extra_value(EXTRAS, field) == 11


def test_extra_value_is_none_when_the_read_failed():
    """A failed extra read leaves its identifier out of the dict entirely.
    None, so the entity goes unavailable rather than showing a stale value as
    if it were live."""
    field = next(f for f in EXTRA_SENSOR_FIELDS if f.key == "pv")
    assert extra_value({}, field) is None
    assert extra_value(None, field) is None


def test_extra_value_is_none_when_only_the_other_reads_succeeded():
    """Per-read isolation: btLock answering does not make alarm's fields
    appear."""
    field = next(f for f in EXTRA_SENSOR_FIELDS if f.key == "pv")
    assert extra_value({"btLock": {"status": "1"}}, field) is None


def test_bind_device_counts_the_list():
    field = next(f for f in EXTRA_SENSOR_FIELDS if f.identifier == "bindDevice")
    assert extra_value(EXTRAS, field) == 0
    assert extra_value({"bindDevice": {"list": ["a", "b"]}}, field) == 2


def test_bind_device_is_none_when_the_list_is_missing():
    field = next(f for f in EXTRA_SENSOR_FIELDS if f.identifier == "bindDevice")
    assert extra_value({"bindDevice": {}}, field) is None


def test_a_measured_field_carries_its_presentation():
    """The split that matters: meterPower was established as watts, so it
    carries unit/device_class/state_class."""
    field = next(f for f in EXTRA_SENSOR_FIELDS if f.key == "meterPower")
    assert (field.unit, field.device_class, field.state_class) == (
        "W", "power", "measurement")


def test_a_raw_field_claims_nothing():
    """A field whose meaning is not established carries none of the three --
    each one would be an assertion about what the value means."""
    for field in ALL_INFO + ALL_EXTRA:
        if field.name != field.key:
            continue  # named field: its meaning was established
        assert field.unit is None
        assert field.device_class is None
        assert field.state_class is None
