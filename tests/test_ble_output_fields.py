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

# The 2026-08-08 sample (raw device reply). The pv fields stopped being
# sensors on 2026-08-09 (no DC module wired) but stay here: output_value is
# generic and 0.0 being a real value is best shown on the real reply.
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


def test_the_field_table_covers_exactly_the_agreed_fields():
    """HIGH + MED from the 2026-08-08 empirics. The rest of the 35 fields
    (batCT, batS, cMode, metL1..., freeRam, ...) have unclear semantics and
    stay reachable through ble_raw_get instead of being guessed at."""
    assert set(FIELDS_BY_KEY) == {
        "batV", "batC",
        # PV1 kept (off-grid-input candidate); PV2/PV3 dropped 2026-08-09.
        # No pv3P: the reply only reports power for strings 1 and 2.
        "pv1V", "pv1C", "pv1P", "pv1TE",
        "devTemp2", "devTemp3", "ogV", "gF",
    }


def test_every_field_has_a_unique_uid_and_name():
    uids = [field.uid for field in OUTPUT_SENSOR_FIELDS]
    names = [field.name for field in OUTPUT_SENSOR_FIELDS]
    assert len(set(uids)) == len(uids)
    assert len(set(names)) == len(names)


@pytest.mark.parametrize("key,unit,device_class", [
    ("batV", "V", "voltage"),
    ("batC", "A", "current"),
    ("pv1V", "V", "voltage"),
    ("pv1P", "W", "power"),
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
    for field in OUTPUT_SENSOR_FIELDS:
        expected = "total_increasing" if field.key.endswith("TE") else "measurement"
        assert field.state_class == expected, field.key


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
