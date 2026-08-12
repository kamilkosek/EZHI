"""The Home-Assistant-shaped half of the MQTT transport.

This file exists because of a bug that every other test in the suite was
structurally unable to see. mqtt_api.py is written against injected
publish/subscribe callables, which is what makes it testable without Home
Assistant -- but it moved the risk into the wiring that does the injecting,
and the wiring had no tests at all. What sat there was a plain lambda handed
to mqtt.async_subscribe: Home Assistant infers the job type from the callable,
a plain one becomes HassJobType.Executor, and the reply handler then resolves
asyncio Futures from an executor thread. Off the loop that races wait_for's
cancellation, and raises on every reply once the loop runs in debug mode.

So: a real homeassistant.core.callback, and a fake broker component. No event
loop harness, no pytest plugin -- the one thing worth locking here is that the
handler is dispatched on the loop, and that is visible on the callable itself.
"""
from __future__ import annotations

import asyncio
import sys
import types

import pytest

# The broker component is faked before the module under test imports it, so
# nothing here pulls in Home Assistant's mqtt integration or touches a broker.
_fake_mqtt = types.ModuleType("homeassistant.components.mqtt")
_fake_mqtt.calls = {"publish": [], "subscribe": []}


async def _fake_publish(hass, topic, payload, qos=0, **kwargs):
    _fake_mqtt.calls["publish"].append((hass, topic, payload, qos))


async def _fake_subscribe(hass, topic, handler, qos=0, **kwargs):
    _fake_mqtt.calls["subscribe"].append((hass, topic, handler, qos))
    return lambda: None


_fake_mqtt.async_publish = _fake_publish
_fake_mqtt.async_subscribe = _fake_subscribe
sys.modules["homeassistant.components.mqtt"] = _fake_mqtt

from ezhi_component.mqtt_connect import make_mqtt_api  # noqa: E402

DEVICE_ID = "D00000000000"
HASS = object()          # opaque: only the faked component ever reads it


class FakeMessage:
    def __init__(self, payload):
        self.payload = payload


@pytest.fixture(autouse=True)
def _clear_calls():
    _fake_mqtt.calls = {"publish": [], "subscribe": []}
    yield


def test_the_reply_handler_is_dispatched_on_the_event_loop():
    """The regression this file was written for.

    Without @callback Home Assistant runs the handler in an executor thread,
    and the transport resolves asyncio Futures in it -- unsafe off the loop,
    and fatal with loop debug on.
    """
    async def scenario():
        api = make_mqtt_api(HASS, DEVICE_ID)
        await api.async_subscribe()
        for _hass, _topic, handler, _qos in _fake_mqtt.calls["subscribe"]:
            assert getattr(handler, "_hass_callback", False) is True, (
                "the message handler must be @callback, or Home Assistant "
                "dispatches it with run_in_executor"
            )

    asyncio.run(scenario())


def test_the_handler_forwards_the_payload_and_nothing_else():
    async def scenario():
        seen = []
        api = make_mqtt_api(HASS, DEVICE_ID)
        api._on_reply = seen.append          # stand in for the transport
        await api.async_subscribe()
        handler = _fake_mqtt.calls["subscribe"][0][2]
        handler(FakeMessage('{"id":"1","code":200}'))
        assert seen == ['{"id":"1","code":200}']

    asyncio.run(scenario())


def test_it_subscribes_to_both_reply_topics_at_qos_1():
    async def scenario():
        api = make_mqtt_api(HASS, DEVICE_ID)
        await api.async_subscribe()
        topics = {topic for _h, topic, _cb, _q in _fake_mqtt.calls["subscribe"]}
        assert topics == {
            f"/properties/EZHI/{DEVICE_ID}/get_reply",
            f"/properties/EZHI/{DEVICE_ID}/set_reply",
        }
        assert all(qos == 1 for *_rest, qos in _fake_mqtt.calls["subscribe"])

    asyncio.run(scenario())


def test_publishing_goes_through_home_assistant_at_qos_1():
    async def scenario():
        api = make_mqtt_api(HASS, DEVICE_ID)
        await api.async_subscribe()
        # answer the request from the fake broker so it does not hang
        handler = _fake_mqtt.calls["subscribe"][0][2]

        async def answer():
            await asyncio.sleep(0)
            _hass, _topic, payload, _qos = _fake_mqtt.calls["publish"][0]
            import json
            corr_id = json.loads(payload)["id"]
            handler(FakeMessage(
                f'{{"id":"{corr_id}","code":200,"data":{{"systemMode":"4"}}}}'))

        _, config = await asyncio.gather(answer(), api.async_get_config())
        assert config["systemMode"] == "4"
        hass, topic, _payload, qos = _fake_mqtt.calls["publish"][0]
        assert hass is HASS
        assert topic == f"/properties/EZHI/{DEVICE_ID}/get"
        assert qos == 1

    asyncio.run(scenario())


def test_the_cloud_object_is_passed_through_for_on_off():
    api = make_mqtt_api(HASS, DEVICE_ID, cloud="the-cloud-object")
    assert api._cloud == "the-cloud-object"
