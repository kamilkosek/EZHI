"""Which transport carries the control commands -- and what happens by default.

The default is the whole point of this file: an installation that upgrades into
this feature must keep behaving exactly as it did, so anything that is not an
explicit "bluetooth" has to resolve to cloud. That includes the empty string,
which is what the frontend sends for a cleared field, and a value from a newer
version than this one.

The translation checks are here rather than in a linter because a select
selector with a missing translation key renders as the raw value ("bluetooth")
in the options dialog -- it still works, so nothing else would catch it.
"""
from __future__ import annotations

import json
from pathlib import Path

from ezhi_component.const import (
    CONF_CONTROL_TRANSPORT,
    CONTROL_TRANSPORTS,
    DEFAULT_CONTROL_TRANSPORT,
    TRANSPORT_BLUETOOTH,
    TRANSPORT_CLOUD,
    TRANSPORT_LOCAL_MQTT,
    resolve_transport,
)

COMPONENT_DIR = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "apsystems_ezhi_local"
)


def load(name: str) -> dict:
    return json.loads((COMPONENT_DIR / name).read_text(encoding="utf-8"))


def test_transport_option_defaults_to_cloud():
    """An existing installation must not change behaviour on upgrade."""
    assert DEFAULT_CONTROL_TRANSPORT == TRANSPORT_CLOUD
    assert resolve_transport({}) == TRANSPORT_CLOUD
    assert resolve_transport({"scan_interval_output": 5}) == TRANSPORT_CLOUD


def test_an_explicit_choice_is_honoured():
    assert resolve_transport(
        {CONF_CONTROL_TRANSPORT: TRANSPORT_BLUETOOTH}) == TRANSPORT_BLUETOOTH
    assert resolve_transport(
        {CONF_CONTROL_TRANSPORT: TRANSPORT_CLOUD}) == TRANSPORT_CLOUD
    assert resolve_transport(
        {CONF_CONTROL_TRANSPORT: TRANSPORT_LOCAL_MQTT}) == TRANSPORT_LOCAL_MQTT


def test_an_empty_or_unknown_value_falls_back_to_cloud():
    """The frontend strips cleared fields, and a downgrade can leave a value
    this version has never heard of. Neither may silently pick a transport."""
    assert resolve_transport({CONF_CONTROL_TRANSPORT: ""}) == TRANSPORT_CLOUD
    assert resolve_transport({CONF_CONTROL_TRANSPORT: None}) == TRANSPORT_CLOUD
    assert resolve_transport({CONF_CONTROL_TRANSPORT: "carrier-pigeon"}) == TRANSPORT_CLOUD


def test_every_option_has_a_label_in_every_language():
    for name in ("strings.json", "translations/en.json", "translations/de.json"):
        data = load(name)
        options = (data.get("selector", {})
                       .get(CONF_CONTROL_TRANSPORT, {})
                       .get("options", {}))
        # Against CONTROL_TRANSPORTS, not a hard-coded pair: the selector is
        # built from that tuple, so a transport added there without a label
        # renders in the dialog as its raw value.
        assert set(options) == set(CONTROL_TRANSPORTS), name
        assert all(options.values()), f"empty label in {name}"


def test_the_option_itself_is_labelled_in_the_options_dialog():
    for name in ("strings.json", "translations/en.json", "translations/de.json"):
        fields = load(name)["options"]["step"]["device_options"]["data"]
        assert CONF_CONTROL_TRANSPORT in fields, name


def test_the_local_mqtt_label_names_its_precondition():
    """This one is cloud-free, but only once the device has been redirected at
    the broker -- picking it without that gets silence, not an error."""
    de = load("translations/de.json")["selector"][CONF_CONTROL_TRANSPORT]["options"]
    en = load("translations/en.json")["selector"][CONF_CONTROL_TRANSPORT]["options"]
    assert "MQTT" in de[TRANSPORT_LOCAL_MQTT]
    assert "MQTT" in en[TRANSPORT_LOCAL_MQTT]
    # the redirect is the part a user cannot guess
    assert "umgeleitet" in de[TRANSPORT_LOCAL_MQTT]
    assert "pointed at it" in en[TRANSPORT_LOCAL_MQTT]


def test_the_bluetooth_label_names_the_cloud_dependency():
    """Bluetooth still needs the cloud to open the radio window. Picking it in
    the belief that it makes the integration cloud-free would be a surprise
    waiting for the first closed window, so the label says so up front."""
    de = load("translations/de.json")["selector"][CONF_CONTROL_TRANSPORT]["options"]
    en = load("translations/en.json")["selector"][CONF_CONTROL_TRANSPORT]["options"]
    assert "Cloud" in de[TRANSPORT_BLUETOOTH]
    assert "cloud" in en[TRANSPORT_BLUETOOTH].lower()
