"""The BLE-only output sensors: which fields, how a value is read, when
they are available.

sensor.py itself imports Home Assistant and cannot be imported here, so it is
a thin shell: field table, value parsing and the availability rule all live in
ble_api.py and are pinned by this file. The sample values are the real device's
outputData reply from 2026-08-08 (docs/ezhi-pcsoriginaldata-samples.md), not
invented numbers.
"""
from __future__ import annotations

import pytest
from ezhi_component.ble_api import (
    OUTPUT_SENSOR_FIELDS,
    ble_output_available,
    output_value,
)

# The 2026-08-08 sample, reduced to the fields that become sensors. pv strings
# were dark or near-dark at capture time; 0.0 is a real value, not "missing".
SAMPLE_OUTPUT = {
    "batV": 50.5, "batC": -0.4,
    "pv1V": 0.0, "pv1C": 0.0, "pv1P": 0.0,
    "pv2V": 0.0, "pv2C": 0.0, "pv2P": 0.0,
    "pv3V": 0.0, "pv3C": 0.0,
    "devTemp2": 32.0, "devTemp3": 31.0,
    "ogV": 233.3, "gF": 50.0,
    "pv1TE": 0.0, "pv2TE": 0.0, "pv3TE": 0.0,
}

FIELDS_BY_KEY = {field.key: field for field in OUTPUT_SENSOR_FIELDS}


MEASURED_KEYS = {
    "batV", "batC",
    # No pv3P: the reply only reports power for strings 1 and 2.
    "pv1V", "pv2V", "pv3V", "pv1C", "pv2C", "pv3C", "pv1P", "pv2P",
    "devTemp2", "devTemp3", "ogV", "gF",
    "pv1TE", "pv2TE", "pv3TE",
    # Added 2026-08-11, meaning established against the real device.
    "ofgV", "ofgC", "rTime",
}

# Exposed under their wire names because the meaning is NOT established --
# see the table header in ble_api.py. They carry no unit, no device_class and
# no state_class, which is what keeps them from reading as truth.
RAW_KEYS = {
    "batCT", "cMode", "rS", "mode", "reUpdate",
    "metL1", "metL2", "metL3", "metDC", "freeRam",
}


def test_the_field_table_covers_exactly_the_agreed_fields():
    """HIGH + MED from the 2026-08-08 empirics, plus off-grid V/C and uptime
    (2026-08-11), plus the raw fields under their wire names."""
    assert set(FIELDS_BY_KEY) == MEASURED_KEYS | RAW_KEYS


def test_every_field_has_a_unique_uid_and_name():
    uids = [field.uid for field in OUTPUT_SENSOR_FIELDS]
    names = [field.name for field in OUTPUT_SENSOR_FIELDS]
    assert len(set(uids)) == len(uids)
    assert len(set(names)) == len(names)


@pytest.mark.parametrize("key,unit,device_class", [
    ("batV", "V", "voltage"),
    ("batC", "A", "current"),
    ("pv1V", "V", "voltage"),
    ("pv3C", "A", "current"),
    ("pv2P", "W", "power"),
    ("devTemp2", "°C", "temperature"),
    ("ogV", "V", "voltage"),
    ("gF", "Hz", "frequency"),
    ("pv1TE", "kWh", "energy"),
])
def test_units_and_device_classes_match_the_measured_semantics(key, unit, device_class):
    field = FIELDS_BY_KEY[key]
    assert field.unit == unit
    assert field.device_class == device_class


def test_energy_totals_are_total_increasing_and_everything_else_measures():
    """Holds for the measured fields. Raw ones carry no state_class at all --
    that is the whole point of them, and it is pinned separately below."""
    for field in OUTPUT_SENSOR_FIELDS:
        if field.key in RAW_KEYS:
            continue
        expected = "total_increasing" if field.key.endswith("TE") else "measurement"
        assert field.state_class == expected, field.key


def test_uptime_counts_up_but_is_not_a_total():
    """rTime drops to 0 when the device restarts, and that drop is the entire
    signal -- it is the only way to notice an EZHI reboot. total_increasing
    would read the drop as a counter wrap, add the pre-restart total on top,
    and hide exactly the event worth seeing."""
    uptime = FIELDS_BY_KEY["rTime"]
    assert uptime.state_class == "measurement"
    assert uptime.device_class == "duration"
    assert uptime.unit == "s"


def test_raw_fields_are_named_after_the_wire_and_claim_nothing():
    """Decision 2026-08-11: unknown meaning -> the field name IS the sensor
    name. 'Battery Cycles' would be a guess wearing the clothes of a fact;
    'batCT' asserts nothing. No unit, no device_class, no state_class, because
    each of those would be such an assertion."""
    for key in RAW_KEYS:
        field = FIELDS_BY_KEY[key]
        assert field.name == key
        assert field.unit is None
        assert field.device_class is None
        assert field.state_class is None
        assert field.diagnostic is True
        # freeRam is the one raw field that is on by default: it is the only
        # value in the diagnostic set that moves, and a falling trend across
        # days is the early warning for a firmware memory leak. Being visible
        # is not a claim about its meaning -- it still carries no unit and no
        # class, and it is still named after the wire.
        assert field.enabled is (key == "freeRam")


def test_measured_fields_kept_their_presentation():
    """Making the three attributes optional must not have emptied them."""
    for key in MEASURED_KEYS:
        field = FIELDS_BY_KEY[key]
        assert field.unit is not None, key
        assert field.device_class is not None, key
        assert field.state_class is not None, key
        assert field.diagnostic is False, key
        assert field.enabled is True, key


# --- reading a value ---------------------------------------------------------

def test_the_sample_values_read_back_as_floats():
    assert output_value(SAMPLE_OUTPUT, "batV") == 50.5
    # Signed and taken raw: the sign convention (charge vs discharge) is
    # unverified, so flipping it here would bake in a guess.
    assert output_value(SAMPLE_OUTPUT, "batC") == -0.4
    assert output_value(SAMPLE_OUTPUT, "ogV") == 233.3
    assert output_value(SAMPLE_OUTPUT, "gF") == 50.0


def test_zero_is_a_value_not_an_absence():
    """pv1TE was 0.0 in the real sample -- a dark string's truth, not a gap."""
    assert output_value(SAMPLE_OUTPUT, "pv1TE") == 0.0


def test_a_string_number_reads_like_a_number():
    """systemMode fields arrive as strings; the same may happen here."""
    assert output_value({"batV": "50.5"}, "batV") == 50.5


@pytest.mark.parametrize("output,key", [
    (SAMPLE_OUTPUT, "noSuchField"),
    ({}, "batV"),
    (None, "batV"),
    ({"batV": "garbage"}, "batV"),
    ({"batV": None}, "batV"),
])
def test_missing_or_unreadable_is_none_never_a_default(output, key):
    assert output_value(output, key) is None


# --- availability ------------------------------------------------------------

def test_sensors_are_available_only_when_the_poll_carried_output():
    """The cloud transport polls output={} every cycle; the sensors must show
    unavailable there, never a stale or guessed number."""
    assert ble_output_available({"config": {"systemMode": "4"}, "output": SAMPLE_OUTPUT})
    assert not ble_output_available({"config": {"systemMode": "4"}, "output": {}})
    assert not ble_output_available({})
    assert not ble_output_available(None)


def test_raw_field_types_survive_output_value():
    """The raw fields are not all strings like the measured ones: freeRam
    arrives as an int, and plug as a list. output_value must turn the first
    into a number and the second into None -- a sensor that reads `unknown`
    is fine, one that raises during a poll is not."""
    reply = {
        "batCT": "234", "cMode": "7", "rS": "1001", "mode": "4",
        "reUpdate": "0", "metL1": "0", "metDC": "0",
        "freeRam": 48672,   # int, not str
        "plug": [],         # list -- deliberately not a sensor
    }
    assert output_value(reply, "batCT") == 234.0
    assert output_value(reply, "freeRam") == 48672.0
    assert output_value(reply, "mode") == 4.0
    assert output_value(reply, "plug") is None
    assert output_value(reply, "notThere") is None


def test_free_ram_is_the_one_visible_raw_field():
    """Promoted 2026-08-11 instead of building a second freeRam out of
    deviceInfo, which carries the same field. Two entities of one name on one
    device is update damage; making the existing one visible is not."""
    visible = {key for key in RAW_KEYS if FIELDS_BY_KEY[key].enabled}
    assert visible == {"freeRam"}
