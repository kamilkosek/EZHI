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
    control_output,
    poll_control_data,
)

CONFIG = {"systemMode": "4", "socMax": "100", "powerLimit": "800"}
OUTPUT = {"batV": 50.5, "batC": -0.4, "ogV": 233.3, "gF": 50.0}


class FakeCloudApi:
    """The cloud surface: has async_get_config, has NO async_get_output_data."""

    async def async_get_config(self) -> dict:
        return dict(CONFIG)


class FakeBleApi(FakeCloudApi):
    def __init__(self, output=None, output_error=None):
        self._output = dict(OUTPUT if output is None else output)
        self._output_error = output_error

    async def async_get_output_data(self) -> dict:
        if self._output_error is not None:
            raise self._output_error
        return dict(self._output)


def test_a_ble_poll_carries_config_and_output():
    data = asyncio.run(poll_control_data(FakeBleApi()))
    assert data == {"config": CONFIG, "output": OUTPUT}


def test_a_cloud_poll_leaves_output_empty_rather_than_guessing():
    """The cloud API has no outputData read; an empty dict is what makes the
    BLE-only sensors unavailable there."""
    data = asyncio.run(poll_control_data(FakeCloudApi()))
    assert data["config"] == CONFIG
    assert data["output"] == {}


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
