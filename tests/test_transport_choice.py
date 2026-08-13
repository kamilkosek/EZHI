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
    CONF_CLOUD_REFRESH_TOKEN,
    CONF_CONTROL_TRANSPORT,
    CONTROL_TRANSPORTS,
    DEFAULT_CONTROL_TRANSPORT,
    TRANSPORT_BLUETOOTH,
    TRANSPORT_CLOUD,
    TRANSPORT_LOCAL_MQTT,
    resolve_transport,
    wants_control_layer,
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


# --- an entry with no vendor credentials ------------------------------------
#
# This is the majority installation and the one an update must not disturb: no
# cloud account, only the local HTTP API. The whole control layer is skipped for
# it, so none of the cloud, Bluetooth or MQTT entities are created -- absent,
# not permanently unavailable. Pinned here because the condition is cheap to
# break and the breakage is invisible until somebody's sensors vanish.


def test_no_credentials_means_no_control_layer():
    assert wants_control_layer({}) is False


def test_no_credentials_survives_missing_data():
    """async_setup_entry passes entry.data straight in; None must not raise."""
    assert wants_control_layer(None) is False


def test_an_explicit_cloud_choice_without_credentials_stays_off():
    assert wants_control_layer({CONF_CONTROL_TRANSPORT: TRANSPORT_CLOUD}) is False


def test_bluetooth_without_credentials_stays_off():
    """Bluetooth is not a cloud-free mode: the radio switches itself off after
    15 minutes and the only unattended way to reopen it is the cloud call
    btOnOff. Opening the layer without credentials would build a transport that
    cannot recover on its own."""
    assert wants_control_layer({CONF_CONTROL_TRANSPORT: TRANSPORT_BLUETOOTH}) is False


def test_local_mqtt_is_the_one_transport_that_opens_without_credentials():
    assert wants_control_layer({CONF_CONTROL_TRANSPORT: TRANSPORT_LOCAL_MQTT}) is True


def test_an_empty_refresh_token_counts_as_no_credentials():
    """The frontend submits an empty string for a cleared field, so a user who
    removes their credentials must land in the no-control case rather than in a
    layer that builds an API client around ''."""
    assert wants_control_layer({CONF_CLOUD_REFRESH_TOKEN: ""}) is False


def test_credentials_alone_are_enough():
    assert wants_control_layer({CONF_CLOUD_REFRESH_TOKEN: "RT-UUID"}) is True


def test_credentials_open_the_layer_on_every_transport():
    for transport in CONTROL_TRANSPORTS:
        assert wants_control_layer({
            CONF_CLOUD_REFRESH_TOKEN: "RT-UUID",
            CONF_CONTROL_TRANSPORT: transport,
        }) is True, transport


def test_every_platform_skips_its_entities_without_a_coordinator():
    """The second half of the guarantee, checked in the source because these
    modules import Home Assistant and cannot be loaded here.

    wants_control_layer() decides whether the coordinator is built; each
    platform then has to actually skip its entities when it is None. Miss one
    and that platform creates entities against a coordinator that never
    refreshes -- the permanently-unavailable failure this design avoids."""
    for platform in ("sensor.py", "binary_sensor.py", "number.py",
                     "select.py", "switch.py"):
        source = (COMPONENT_DIR / platform).read_text(encoding="utf-8")
        assert "cloud_coordinator is None" in source or \
               "cloud_coordinator is not None" in source, platform


# --- the local-MQTT precondition check --------------------------------------
#
# Choosing this transport is the one setting whose precondition lives outside
# Home Assistant: the inverter has to have been redirected at a broker. Get it
# wrong and nothing says so -- the entry saves, the entities appear, and every
# poll times out into the log. The options flow probes before saving, and these
# pin that the three outcomes it can report are actually renderable. An error
# key with no string shows up in the dialog as the raw key.


def test_every_probe_error_has_a_string_in_every_language():
    for name in ("strings.json", "translations/en.json", "translations/de.json"):
        errors = load(name)["options"]["error"]
        for key in ("mqtt_not_configured", "mqtt_device_unknown", "mqtt_no_reply"):
            assert key in errors, f"{key} missing from {name}"
            assert errors[key].strip(), f"{key} empty in {name}"


def test_the_no_reply_text_names_the_redirect():
    """This is the message a misconfigured install actually gets, and "the
    inverter did not answer" alone would send them to the inverter. The cause is
    almost always the missing redirect."""
    en = load("translations/en.json")["options"]["error"]["mqtt_no_reply"]
    de = load("translations/de.json")["options"]["error"]["mqtt_no_reply"]
    assert "redirect" in en.lower()
    assert "umgeleitet" in de.lower()


def test_the_probe_runs_only_for_local_mqtt():
    """Checked in the source: the other transports have no such precondition,
    and a probe on every options save would put a spinner in front of a user
    changing a poll interval."""
    source = (COMPONENT_DIR / "config_flow.py").read_text(encoding="utf-8")
    assert "chosen == TRANSPORT_LOCAL_MQTT" in source
    assert "_probe_local_mqtt" in source


def test_the_probe_asks_the_device_not_just_the_broker():
    """A configured broker proves nothing: one with no inverter behind it looks
    perfectly healthy from Home Assistant's side. The probe has to read."""
    source = (COMPONENT_DIR / "config_flow.py").read_text(encoding="utf-8")
    probe = source.split("async def _probe_local_mqtt")[1].split("def _device_options_schema")[0]
    assert "async_get_config()" in probe, "the probe never reads from the device"
    assert "async_unsubscribe()" in probe, "the probe leaves its subscriptions behind"
