"""The diagnostics dump must not carry anything identifying.

This is the file people paste into public issue threads, so the redaction is
the feature. Tested against nesting on purpose: the interesting parts of the
device replies sit one and two levels down, and a flat pass would leave the
serial in place while looking like it had worked.
"""
from __future__ import annotations

import json
from pathlib import Path

from ezhi_component.diagnostics import TO_REDACT, TO_REDACT_WIRE, _as_dict, _clean

COMPONENT_DIR = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "apsystems_ezhi_local"
)


def test_the_serial_does_not_survive_at_any_depth():
    payload = {
        "config": {"deviceId": "D00000000000", "systemMode": "4"},
        "device": {"net": {"ssid": "Home", "wifiMac": "aa:bb:cc:dd:ee:01"}},
        "output": [{"sn": "D00000000000", "batV": "52.1"}],
    }
    dumped = json.dumps(_clean(payload))
    assert "D00000000000" not in dumped
    assert "aa:bb:cc:dd:ee:01" not in dumped
    assert "Home" not in dumped
    # and the values worth having are still there
    assert "52.1" in dumped and '"systemMode": "4"' in dumped


def test_redaction_keeps_the_shape():
    """A dump with the keys stripped out would be unreadable -- the point is
    that a reader still sees which fields the device answered with."""
    cleaned = _clean({"a": {"deviceId": "X"}})
    assert cleaned == {"a": {"deviceId": "**REDACTED**"}}


def test_credentials_are_in_the_entry_redaction_set():
    for key in ("cloud_access_token", "cloud_refresh_token",
                "cloud_password", "cloud_username", "cloud_device_id"):
        assert key in TO_REDACT, key


def test_the_wire_set_uses_names_the_device_actually_sends():
    """The first version of the list carried "bleMac", a name that exists
    nowhere in this project -- the real field is bluetoothMac. The redaction
    looked complete and let the Bluetooth MAC through. Pinned against the real
    field definitions so a rename cannot repeat that."""
    from ezhi_component.device_fields import INFO_SENSOR_FIELDS

    identifying = {
        field.key for field in INFO_SENSOR_FIELDS
        if any(mark in field.key.lower() for mark in ("mac", "ssid", "deviceid"))
    }
    assert identifying, "no identifying info fields found -- has the shape changed?"
    missing = identifying - TO_REDACT_WIRE
    assert not missing, f"these reach the dump unredacted: {sorted(missing)}"


def test_the_bluetooth_mac_does_not_survive():
    """The regression itself, by its real name: a BLE MAC is observable over
    the air and identifies the household."""
    cleaned = _clean({"device": {"bluetoothMac": "AA:BB:CC:DD:EE:11"}})
    assert "AA:BB:CC:DD:EE:11" not in json.dumps(cleaned)


def test_as_dict_survives_the_shapes_a_coordinator_holds():
    class Payload:
        def __init__(self):
            self.batSoc = "90"

    assert _as_dict(None) is None
    assert _as_dict({"a": 1}) == {"a": 1}
    assert _as_dict(Payload()) == {"batSoc": "90"}


def test_home_assistant_finds_the_entry_point():
    """HA calls async_get_config_entry_diagnostics by name; a rename would
    leave the download button silently missing."""
    source = (COMPONENT_DIR / "diagnostics.py").read_text(encoding="utf-8")
    assert "async def async_get_config_entry_diagnostics(" in source
