"""What one control-coordinator poll cycle produces, on either transport.

The coordinator itself lives in __init__.py, which imports Home Assistant and
therefore cannot be imported here. poll_control_data is the whole of its poll
policy, extracted into cloud.py exactly so this file can pin it: the shape of
the data, the BLE-only extra read, and what happens when only the extra fails.
"""
from __future__ import annotations

import asyncio

import pytest
from ezhi_component.ble_link import EzhiBleError
from ezhi_component.cloud import (
    EzhiCloudError,
    control_config,
    control_extras,
    control_output,
    poll_control_data,
)

CONFIG = {"systemMode": "4", "socMax": "100", "powerLimit": "800"}
OUTPUT = {"batV": 50.5, "batC": -0.4, "ogV": 233.3, "gF": 50.0}
DEVICE = {"rssi": -52, "ssid": "wlan", "devVer": "EZHI 1.9.0.16"}


class FakeCloudApi:
    """The cloud surface: async_get_config only -- neither BLE extra read."""

    async def async_get_config(self) -> dict:
        return dict(CONFIG)


class FakeBleApi(FakeCloudApi):
    def __init__(self, output=None, output_error=None, device_error=None):
        self._output = dict(OUTPUT if output is None else output)
        self._output_error = output_error
        self._device_error = device_error

    async def async_get_output_data(self) -> dict:
        if self._output_error is not None:
            raise self._output_error
        return dict(self._output)

    async def async_get_device_info(self) -> dict:
        if self._device_error is not None:
            raise self._device_error
        return dict(DEVICE)


def test_a_ble_poll_carries_config_output_and_device():
    data = asyncio.run(poll_control_data(FakeBleApi()))
    # extras is empty here, and deliberately so: FakeBleApi has no
    # async_poll_all, which is how the serial Bluetooth link avoids having six
    # more round trips added to its poll.
    assert data == {"config": CONFIG, "output": OUTPUT, "device": DEVICE,
                    "extras": {}}


def test_a_cloud_poll_leaves_output_empty_rather_than_guessing():
    """The cloud API has no outputData read; an empty dict is what makes the
    BLE-only sensors unavailable there."""
    data = asyncio.run(poll_control_data(FakeCloudApi()))
    assert data["config"] == CONFIG
    assert data["output"] == {}
    assert data["device"] == {}


def test_a_failed_output_read_degrades_instead_of_taking_control_down():
    """The extra read must never cost the control entities: config landed, so
    the poll succeeds and only the output sensors go unavailable.

    Injects the PRODUCTION error type, EzhiBleError -- what async_get_output_data
    actually raises over a real link. That it is caught here rests on
    EzhiBleError being an EzhiCloudError subclass; injecting the real type pins
    that inheritance, which the whole degradation path depends on."""
    data = asyncio.run(
        poll_control_data(FakeBleApi(output_error=EzhiBleError("link hiccup")))
    )
    assert data["config"] == CONFIG
    assert data["output"] == {}


def test_a_failed_config_read_still_fails_the_whole_poll():
    """Unchanged contract: the coordinator turns this into UpdateFailed."""
    class BrokenApi(FakeBleApi):
        async def async_get_config(self) -> dict:
            raise EzhiCloudError("cloud down")

    with pytest.raises(EzhiCloudError):
        asyncio.run(poll_control_data(BrokenApi()))


def test_an_unexpected_output_error_is_not_swallowed():
    """Only the known transport error degrades; a programming error must
    surface, not vanish into an empty dict."""
    with pytest.raises(TypeError):
        asyncio.run(poll_control_data(FakeBleApi(output_error=TypeError("bug"))))


# --- the accessors every entity reads the poll result through ---------------

def test_control_config_unwraps_the_poll_shape():
    assert control_config({"config": CONFIG, "output": {}}) == CONFIG


@pytest.mark.parametrize("data", [None, {}, {"config": None}, {"output": OUTPUT}])
def test_control_config_is_empty_on_anything_but_a_real_config(data):
    """None before the first refresh, and partial shapes, all read as 'no
    config' -- every consumer does .get() on the result and must not crash."""
    assert control_config(data) == {}


def test_control_output_unwraps_the_poll_shape():
    assert control_output({"config": CONFIG, "output": OUTPUT}) == OUTPUT


@pytest.mark.parametrize("data", [None, {}, {"output": None}, {"config": CONFIG}])
def test_control_output_is_empty_when_the_poll_carried_none(data):
    assert control_output(data) == {}


def test_a_failed_device_read_degrades_on_its_own():
    """deviceInfo is the third read and the least important one: when only it
    fails, config and output must both survive untouched. Same production
    error type as the output path, for the same reason -- it pins that
    EzhiBleError is caught here, not just EzhiCloudError."""
    data = asyncio.run(
        poll_control_data(FakeBleApi(device_error=EzhiBleError("radio window shut")))
    )
    assert data["config"] == CONFIG
    assert data["output"] == OUTPUT
    assert data["device"] == {}


class FakeMqttApi(FakeCloudApi):
    """The MQTT surface as of 2026-08-11: config plus the outputData read.

    No deviceInfo here on purpose -- poll_control_data finds each extra by
    name, and this pins that a transport offering only one of them still gets
    that one polled.
    """

    async def async_get_output_data(self) -> dict:
        return dict(OUTPUT)


def test_mqtt_transport_now_carries_output():
    """Before 2026-08-11 the MQTT transport was assumed push-only and had no
    output read at all. The `get` is verified, so poll_control_data has to pick
    it up through the same getattr it already used for Bluetooth -- without a
    single line in the poll policy changing."""
    result = asyncio.run(poll_control_data(FakeMqttApi()))

    assert control_config(result) == CONFIG
    assert control_output(result)["batV"] == 50.5


# --- the parallel poll, and the diagnostic reads it carries ----------------

EXTRAS = {"btLock": {"status": "1"}, "light": {"sys": "10"}}


class FakePollAllMqttApi(FakeBleApi):
    """The MQTT surface: it does the whole cycle in one round of requests.

    async_poll_all exists only on this transport. Its replies are correlated by
    corr_id, so any number of requests may be open at once -- on the serial
    Bluetooth link the same gather would push nine requests into one wire.
    """

    def __init__(self, extras=None, **kwargs):
        super().__init__(**kwargs)
        self._extras = dict(EXTRAS if extras is None else extras)

    async def async_poll_all(self) -> dict:
        return {"config": dict(CONFIG), "output": dict(OUTPUT),
                "device": dict(DEVICE), "extras": dict(self._extras)}


def test_an_mqtt_poll_carries_the_extras_too():
    data = asyncio.run(poll_control_data(FakePollAllMqttApi()))
    assert control_extras(data) == EXTRAS
    # and it still carries everything the sequential path did
    assert control_config(data) == CONFIG
    assert control_output(data) == OUTPUT


def test_a_ble_poll_leaves_extras_empty_rather_than_reading_them_serially():
    """BLE has no async_poll_all -- getattr finds nothing and the poll is
    unchanged. Six more serial round trips inside a 60 s poll is exactly what
    this absence prevents; do not lift the method into a shared base class."""
    data = asyncio.run(poll_control_data(FakeBleApi()))
    assert control_extras(data) == {}


def test_a_cloud_poll_leaves_extras_empty():
    data = asyncio.run(poll_control_data(FakeCloudApi()))
    assert control_extras(data) == {}


def test_control_extras_tolerates_no_data_yet():
    """Before the first refresh the coordinator data is None."""
    assert control_extras(None) == {}
    assert control_extras({}) == {}


def test_an_empty_extras_result_does_not_fail_the_poll():
    """async_poll_all never raises for a diagnostic read -- it drops what
    failed and returns the rest. An empty result is a degraded poll, not a
    failed one, and the control entities keep their availability through it."""
    data = asyncio.run(poll_control_data(FakePollAllMqttApi(extras={})))
    assert control_config(data) == CONFIG
    assert control_extras(data) == {}
