"""Control the inverter over a local MQTT broker instead of the vendor cloud.

The device's cloud link *is* MQTT, and it validates nothing about the broker
it lands on -- no certificate pinning, no mutual TLS. Redirecting its DNS to a
broker on the local network therefore hands over the vendor's own control
channel, intact: the same identifiers, the same params, the same replies.
The wire format was verified end to end on 2026-08-10 against the real device
-- read a config, change a field, read it back, restore it, all of it with the
vendor cloud disconnected. That round trip was driven by hand against a
mosquitto broker, though, not by this module. So what is proven is the
protocol; this code path has not yet driven the device itself. Until it has,
treat a failure here as "our framing" before "their firmware".

Same method names as EzhiCloudApi and EzhiBleApi on purpose: the entities and
the coordinator call `coordinator.api.async_*` and must not know which
transport is underneath.

No Home Assistant here: `publish` and `subscribe` are handed in, the way
ble_link.py takes its connector. In production they wrap
homeassistant.components.mqtt; in the tests they are a fake broker. Nothing
below needs a real one.

Wire format and the capture it came from: mqtt_protocol.py.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from . import mqtt_protocol
from .cloud import (
    HIGH_POWER_LIMIT,
    STANDARD_POWER_LIMIT,
    EzhiCloudError,
    _check_discharge_protection,
    _check_power_limit_vs_schedule,
    _check_soc_window,
    _to_int,
    build_system_mode_params,
)

_LOGGER = logging.getLogger(__name__)

# The device answers on a roughly 5 s firmware tick: measured 2026-08-11 across
# ten identifiers, every one of them 5.05-5.09 s, sequentially. 12 s therefore
# covers two ticks. (An earlier version of this comment claimed "well under a
# second", read off a capture of unprompted pushes rather than of
# request/response -- a push arrives when the device feels like it, a reply
# waits for the next tick.)
#
# The ceiling is for a broker that is briefly wedged, not for a device that is
# gone -- and it is deliberately under half of the 30 s the entity layer allows
# a write, because a write is two round trips (read the config, then write it)
# and both have to fit inside that budget.
REPLY_TIMEOUT = 12.0

# The identifiers that carry diagnostics and are read nowhere else in this
# integration. Every one of them verified answered over MQTT on 2026-08-11.
#
# Four identifiers that DO answer are deliberately not here:
#   si                          -- binary_sensor.ALARM_SENSORS already covers
#                                  all twenty of its protection flags
#   wifiStatus, caTz,           -- every field they carry is in deviceInfo,
#   combineVersion                 which is read every poll anyway
# And one that does not answer at all: batteryCellData is silent on `get` (BLE
# 2026-08-10, 20 s timeout; MQTT 2026-08-11, no reply inside REPLY_TIMEOUT).
# It exists only as a push, and its payload there is empty -- {"cell": [],
# "cellStatus": 0}. There is nothing behind it to read.
EXTRA_IDENTIFIERS: tuple[str, ...] = (
    "light", "alarm", "supportFunction", "meterStatus", "btLock", "bindDevice",
)


def _raise_anything_unexpected(results: list) -> None:
    """Re-raise every failure that is not a known transport error.

    The sequential path in poll_control_data degrades on `except
    EzhiCloudError` and nothing wider, so a TypeError in our own framing code
    surfaces there instead of vanishing -- pinned by
    test_an_unexpected_output_error_is_not_swallowed. `gather(...,
    return_exceptions=True)` collects BaseException indiscriminately, which
    would silently downgrade exactly those bugs to a log line on this transport
    only. This restores the contract.

    Also covers CancelledError, which is a BaseException and not an
    EzhiCloudError: a cancelled poll must propagate as cancelled, never be
    reported as "the device did not answer".
    """
    for result in results:
        if isinstance(result, BaseException) and not isinstance(
                result, EzhiCloudError):
            raise result


def _log_failed_reads(missing: list[str], diagnostic: list[str]) -> None:
    """What did not answer this cycle, at the level each half deserves.

    `missing` is outputData and deviceInfo -- between them they feed some forty
    entities, and them going quiet is worth a WARNING, exactly as on the
    sequential path (cloud.py). Losing that visibility on MQTT alone would mean
    forty sensors can sit unavailable with nothing in the log to say why.

    `diagnostic` is the six extra identifiers, aggregated onto DEBUG. Six
    identifiers failing forever -- a firmware update dropping one -- would
    otherwise be six warnings a minute for good. A diagnostic read that stays
    silent is not an incident, and the entity going unavailable is already the
    visible signal.
    """
    if missing:
        _LOGGER.warning(
            "EZHI poll: no answer for %s; the sensors built on them go "
            "unavailable until the next successful poll", ", ".join(missing))
    if diagnostic:
        _LOGGER.debug(
            "EZHI poll: no answer for the diagnostic reads %s; their entities "
            "go unavailable until the next successful poll",
            ", ".join(diagnostic))


class EzhiMqttError(EzhiCloudError):
    """A local-MQTT transport failure.

    Subclasses EzhiCloudError for the same reason EzhiBleError does: switch.py,
    number.py and select.py catch that and nothing else, so an error family
    outside it would surface as an unhandled exception the moment a user picks
    this transport.

    Deliberately never EzhiCloudAuthError: the coordinator turns that into a
    reauth flow that asks for cloud tokens, which an entry running purely on a
    local broker does not have and does not need.
    """


class EzhiMqttApi:
    """Control the inverter over its own MQTT protocol, on a local broker.

    `publish(topic, payload)` and `subscribe(topic, handler)` are awaitables
    supplied by the caller; `subscribe` returns an unsubscribe callable, and
    `handler` is called with the raw payload of each message.
    """

    def __init__(
        self,
        device_id: str,
        publish: Callable[[str, str], Awaitable[Any]],
        subscribe: Callable[[str, Callable[[Any], None]], Awaitable[Callable[[], Any]]],
        cloud: Any | None = None,
        timeout: float = REPLY_TIMEOUT,
    ) -> None:
        self._device_id = device_id
        self._publish = publish
        self._subscribe = subscribe
        # Only async_set_on_off uses this -- see there for why that one command
        # does not go over MQTT yet.
        self._cloud = cloud
        self._timeout = timeout
        # Correlation id -> the future waiting for that reply.
        self._pending: dict[str, asyncio.Future] = {}
        self._unsubscribe: list[Callable[[], Any]] = []
        # Serialises the read-modify-write pairs, so two entities cannot each
        # read the config and then each write their own field back over the
        # other's. The correlation ids keep single commands apart on their own.
        self._write_lock = asyncio.Lock()

    @property
    def device_id(self) -> str:
        return self._device_id

    # --- connection -------------------------------------------------------

    async def async_subscribe(self) -> None:
        """Start listening for replies. Must complete before the first request.

        Subscribing after publishing would be a race the device always wins:
        it answers in milliseconds, and a reply nobody is listening for is
        gone. The startup path therefore subscribes, then polls.
        """
        if self._unsubscribe:
            return
        for topic in mqtt_protocol.reply_topics(self._device_id):
            try:
                self._unsubscribe.append(await self._subscribe(topic, self._on_reply))
            except Exception as err:  # no broker client, bad topic, ...
                await self.async_unsubscribe()
                raise EzhiMqttError(f"cannot subscribe to {topic}: {err}") from err

    async def async_unsubscribe(self) -> None:
        """Drop the subscriptions and fail every request still waiting."""
        while self._unsubscribe:
            try:
                result = self._unsubscribe.pop()()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as err:  # unloading must not raise
                _LOGGER.debug("unsubscribe failed, continuing: %s", err)
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(EzhiMqttError("transport shut down"))
        self._pending.clear()

    def _on_reply(self, payload: Any) -> None:
        """Hand one reply to whoever is waiting for it."""
        try:
            corr_id, code, data = mqtt_protocol.parse_reply(payload)
        except ValueError as err:
            # Anyone can publish to a topic. Log it, drop it, stay up.
            _LOGGER.debug("ignoring an unreadable reply: %s", err)
            return
        future = self._pending.get(corr_id)
        if future is None or future.done():
            # A reply to a request that already timed out, or one we never
            # sent -- a retained message, or a second controller on the broker.
            return
        future.set_result((code, data))

    # --- request/response --------------------------------------------------

    async def _request(self, topic: str, payload: str, corr_id: str, what: str) -> dict:
        """Publish one command and wait for the device's answer to it."""
        if not self._unsubscribe:
            raise EzhiMqttError(
                f"cannot {what}: not subscribed to the reply topics"
            )
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[corr_id] = future
        try:
            await self._publish(topic, payload)
            code, data = await asyncio.wait_for(future, self._timeout)
        except asyncio.TimeoutError as err:
            raise EzhiMqttError(
                f"the inverter did not answer {what} within {self._timeout:.0f} s"
            ) from err
        except EzhiMqttError:
            raise
        except Exception as err:
            # Publishing without a broker client raises HomeAssistantError,
            # which is outside the family the coordinator and the entities
            # catch. Translate everything, or a missing broker turns into an
            # unhandled traceback every poll.
            raise EzhiMqttError(f"cannot {what} over MQTT: {err}") from err
        finally:
            # Also on the timeout path: a future left behind here is a leak
            # that a late reply would then resolve into nothing.
            self._pending.pop(corr_id, None)
        if code != mqtt_protocol.SUCCESS_CODE:
            raise EzhiMqttError(f"the inverter rejected {what}: code {code}, {data}")
        # As on the other transports: a 200 says the device parsed the
        # command, not that it acted on it. Only the effect proves the effect.
        return data

    async def _get(self, identifier: str) -> dict:
        corr_id = mqtt_protocol.new_corr_id()
        return await self._request(
            mqtt_protocol.topic_get(self._device_id),
            mqtt_protocol.build_get(self._device_id, identifier, corr_id),
            corr_id,
            f"read {identifier}",
        )

    async def _set(self, identifier: str, params: dict) -> dict:
        corr_id = mqtt_protocol.new_corr_id()
        return await self._request(
            mqtt_protocol.topic_set(self._device_id),
            mqtt_protocol.build_set(self._device_id, identifier, params, corr_id),
            corr_id,
            f"write {identifier}",
        )

    # --- public API -------------------------------------------------------

    async def async_get_config(self) -> dict:
        """The full controllable config -- the payload the cloud GET returns too.

        Asked for rather than waited for: the device pushes plenty of telemetry
        unprompted, but never systemMode. A cache fed from the push would be
        missing exactly the blob every write has to carry forward.
        """
        return await self._get("systemMode")

    async def async_get_output_data(self) -> dict:
        """The telemetry read: the 50 fields the local HTTP API does not carry.

        Asked for, not waited for. The 2026-08-10 capture saw outputData only
        as a push on /event/<p>/<s>/post, and the conclusion drawn at the time
        -- that a push was the only way to it -- was wrong. `get` with this
        identifier is answered exactly like systemMode is: verified against the
        real device 2026-08-11, code 200, 50 fields, batV/batC, pv1-3 V+C+P,
        gF, ogV, devTemp2/3 among them.

        Asking is also the more robust half of that choice. The device was not
        seen pushing at all in two captures (150 s, and 190 s on a connection
        it had just made), and the push is known to arrive incomplete anyway --
        see async_get_device_info below.

        poll_control_data() picks this up by name through getattr, so adding
        the method is the whole of the wiring.
        """
        return await self._get("outputData")

    async def async_get_device_info(self) -> dict:
        """Identity, firmware and link health -- carries `rssi` for the WiFi sensor.

        Answered over MQTT in the capture, as outputData now is too (see above:
        the read was verified 2026-08-11, after this docstring first claimed
        there was none).

        There is a second, independent reason not to substitute the push, found
        by comparing frames across both transports and both operating regimes
        (2026-08-11): **the push is incomplete**. Five bytes of the
        `pvOriginalData` frame -- offsets 52, 55, 56, 57 and 61 -- arrive zero
        in the push while Bluetooth carries them populated in every regime
        measured. Nothing reports this; the frame simply arrives short.

        That is a property of the push, not of the transport. Re-measured
        2026-08-11 against a `get` reply over MQTT: all five offsets are
        populated there (75, 46490, 41397, 161, 143). An earlier version of
        this docstring called it a transport artefact and concluded MQTT could
        not carry the frame -- wrong, and the correction matters, because it is
        the difference between "the local path loses data" and "do not read the
        push".
        """
        return await self._get("deviceInfo")

    async def async_get_raw(self, identifier: str) -> dict:
        """Diagnostic read of any identifier, data block untouched.

        Unlike the two above, this makes no claim that the identifier answers.
        It is the tool for finding out which ones do.
        """
        return await self._get(identifier)

    async def async_poll_all(self) -> dict:
        """One whole poll cycle -- config, outputData, deviceInfo and the six
        extras -- in a single round of requests.

        Returns the control coordinator's data shape directly:
        {"config": ..., "output": ..., "device": ..., "extras": {...}}.

        poll_control_data() finds this by name through getattr and hands the
        whole cycle over when it exists. It exists only here, and that is the
        design rather than an omission: MQTT correlates replies by corr_id
        through self._pending, so any number of requests may be open at once.
        Bluetooth is a serial link -- the same gather would push nine requests
        into one wire -- so there the sequential path in poll_control_data
        stays.

        Why the whole cycle and not just the six new reads: the first refresh
        after startup has a 20 s budget (__init__.py, asyncio.timeout(20)),
        and nine sequential reads at the measured 5.05 s each would not have
        fit in it under any arrangement. In one gather the cycle costs one
        firmware tick -- measured 2026-08-11: ten
        identifiers fired together answered in 2.5-3.0 s wall clock across
        three runs, against 5.05 s for a single sequential read, because the
        one request waits half a tick for the next collection window and ten
        of them fall into the same one.

        Failure policy, matching the sequential path in three steps:

        1. Anything that is not an EzhiCloudError is re-raised, so a bug in our
           own framing surfaces instead of turning into an empty dict. gather()
           would otherwise collect it like any other failure -- and it is
           precisely a silent default fallback that the sequential path's
           `except EzhiCloudError` was written to avoid.
        2. A config failure fails the whole poll (the coordinator turns it into
           UpdateFailed): without systemMode we do not know what the device is
           doing, and every control entity would be showing a value it cannot
           vouch for.
        3. Everything else degrades to empty, because the entities built on it
           go unavailable on empty and must never show a stale value as live.
        """
        identifiers = ("systemMode", "outputData", "deviceInfo") + EXTRA_IDENTIFIERS
        results = await asyncio.gather(
            *(self._get(identifier) for identifier in identifiers),
            return_exceptions=True,
        )
        _raise_anything_unexpected(results)
        config, output, device = results[0], results[1], results[2]
        if isinstance(config, BaseException):
            raise config
        # Two lists, because the two halves are worth different log levels:
        # outputData and deviceInfo feed some forty entities between them.
        missing: list[str] = []
        diagnostic: list[str] = []
        extras: dict = {}
        for identifier, result in zip(EXTRA_IDENTIFIERS, results[3:]):
            if isinstance(result, BaseException):
                diagnostic.append(identifier)
                continue
            extras[identifier] = result
        if isinstance(output, BaseException):
            missing.append("outputData")
            output = {}
        if isinstance(device, BaseException):
            missing.append("deviceInfo")
            device = {}
        _log_failed_reads(missing, diagnostic)
        return {"config": config, "output": output, "device": device,
                "extras": extras}

    async def async_set_system_mode(self, **changes: Any) -> None:
        """Write systemMode, carrying every untouched field forward.

        Reads the config first for the same reason the other transports do: a
        poll can be a minute old, and writing a stale EPS/ECO back would undo
        a change made from the vendor app in the meantime.

        The full merged field set goes on the wire, not just `changes`, even
        though the vendor app's own MQTT writes are partial. The merge
        semantics are the same either way (measured 2026-08-01, see cloud.py),
        and reusing the cloud builder keeps its typo guard, which turns a
        misspelled kwarg into an error instead of a silent no-op.

        Be precise about what that rests on: multi-field writes over MQTT are
        verified (the app sends them for some modes and the device answers
        200), and every individual field here is verified -- but this exact
        combination in one write is not. The one MQTT write we made ourselves
        was partial. So the first write from this transport has to be checked
        against its effect, not against its 200.
        """
        async with self._write_lock:
            config = await self.async_get_config()
            _check_discharge_protection(config, changes)
            _check_power_limit_vs_schedule(config, changes)
            params = build_system_mode_params(config, **changes)
            await self._set("systemMode", params)

    async def async_set_on_off(self, on: bool) -> None:
        """Turn the inverter on or off -- over the cloud, if there is one.

        The MQTT payload for this has not been captured. Everything else here
        was read off the wire; guessing at the one command that can take the
        whole device off the network -- the radio dies with it, and only the
        3 s battery button brings it back -- is not where to start.

        Capturing it needs the vendor app driving a bridged broker, which is a
        deliberate session at the device, not something to infer.
        """
        if self._cloud is None:
            raise EzhiMqttError(
                "onOff over MQTT has not been captured yet and no cloud "
                "client is available -- not guessing against real hardware"
            )
        await self._cloud.async_set_on_off(on)

    async def async_set_backup_power(self, on: bool) -> None:
        """Turn EPS (backup / emergency power) on or off.

        Enabling backup also clears ECO in the same write: the firmware treats
        them as mutually exclusive. Disabling backup does NOT set ECO.
        """
        changes = {"EPS": "1", "ECO": "0"} if on else {"EPS": "0"}
        await self.async_set_system_mode(**changes)

    async def async_set_eco(self, on: bool) -> None:
        """Mirror image of async_set_backup_power -- see there for the pairing."""
        changes = {"ECO": "1", "EPS": "0"} if on else {"ECO": "0"}
        await self.async_set_system_mode(**changes)

    async def async_set_high_power(self, enable: bool) -> None:
        """Switch the output ceiling between 800 W and 1200 W.

        The acknowledgement gate for 1200 W lives in the service handler, as on
        the other transports -- picking this one must not be a way around it.
        """
        await self.async_set_system_mode(
            powerLimit=HIGH_POWER_LIMIT if enable else STANDARD_POWER_LIMIT
        )

    async def async_set_soc_limit(
        self, soc_min: int | None = None, soc_max: int | None = None
    ) -> None:
        """Write the SOC bounds.

        Both bounds travel through the systemMode setter, as on Bluetooth:
        there is no separate socLimit command on this channel either. socMax is
        added past build_system_mode_params' typo guard on purpose -- the cloud
        builder does not know the field, because on the cloud side socMax
        belongs to a separate endpoint that this transport does not have.
        """
        requested = {
            key: value
            for key, value in (("socMin", soc_min), ("socMax", soc_max))
            if value is not None
        }
        if not requested:
            raise EzhiMqttError("async_set_soc_limit needs at least one bound")
        if soc_min is not None and soc_max is not None:
            _check_soc_window(_to_int(soc_min, "socMin"), _to_int(soc_max, "socMax"))
        async with self._write_lock:
            config = await self.async_get_config()
            if soc_min is None:
                soc_min = config.get("socMin")
            if soc_max is None:
                soc_max = config.get("socMax")
            if soc_min is None or soc_max is None:
                raise EzhiMqttError(
                    "cannot build a socLimit payload, the config is missing "
                    "socMin/socMax -- refusing to write a partial configuration"
                )
            soc_min = _to_int(soc_min, "socMin")
            soc_max = _to_int(soc_max, "socMax")
            _check_soc_window(soc_min, soc_max)
            # Raising socMin above dischargeProtection - 2 is refused here too;
            # otherwise the SOC Minimum entity would be a way around the guard.
            _check_discharge_protection(config, requested)
            params = build_system_mode_params(config, socMin=str(soc_min))
            params["socMax"] = str(soc_max)
            await self._set("systemMode", params)
