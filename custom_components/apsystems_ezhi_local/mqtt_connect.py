"""Wire the MQTT transport to Home Assistant's own broker client.

The Home-Assistant-shaped half of the local MQTT transport, kept apart from
mqtt_api.py for the same reason ble_connect.py is kept apart from ble_link.py:
everything that talks protocol stays testable without Home Assistant, and
everything that talks to Home Assistant lives in one small file.

Import this lazily. The mqtt integration is a soft dependency, so an entry on
another transport must not pay for it.
"""
from __future__ import annotations


from homeassistant.components import mqtt
from homeassistant.core import callback

from .mqtt_api import EzhiMqttApi

# The device publishes at QoS 1 and so do we: a dropped command is worse than
# a repeated one here, and the envelope carries a correlation id, so a
# duplicate resolves the same future twice -- which the transport ignores.
QOS = 1


def make_mqtt_api(hass, device_id: str) -> EzhiMqttApi:
    """An EzhiMqttApi talking through Home Assistant's broker connection."""

    async def publish(topic: str, payload: str) -> None:
        await mqtt.async_publish(hass, topic, payload, qos=QOS)

    async def subscribe(topic: str, handler):
        # @callback is load-bearing, not decoration. Home Assistant infers the
        # job type from the function it is handed: a plain one becomes
        # HassJobType.Executor and is dispatched with run_in_executor. The
        # transport resolves asyncio Futures inside this handler, which is
        # only safe on the event loop -- off it, it races wait_for's
        # cancellation at the timeout boundary, and raises on every single
        # reply once the loop runs in debug mode.
        @callback
        def _forward(message) -> None:
            handler(message.payload)

        return await mqtt.async_subscribe(hass, topic, _forward, qos=QOS)

    return EzhiMqttApi(device_id, publish, subscribe)
