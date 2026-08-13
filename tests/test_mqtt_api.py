"""The local-MQTT transport must be interchangeable with the cloud one.

Entities call coordinator.api.async_set_*, so anything the cloud API offers
and this one does not is a crash waiting for the user to flip the option.

The config fixture is the inverter's real systemMode payload, read out of the
2026-08-10 capture (serial scrubbed) -- a made-up one would not exercise the
required-field rules in build_system_mode_params.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from ezhi_component import mqtt_protocol as p
from ezhi_component.mqtt_api import (
    EXTRA_IDENTIFIERS,
    EzhiMqttApi,
    EzhiMqttError,
)

DEVICE_ID = "D00000000000"

DEVICE_CONFIG = {
    "systemMode": "4", "userSetPower": "200", "socMax": "100", "socMin": "10",
    "isOPStrategy": "1", "outputPowerStrategy": [],
    "outputPowerStrategyWeekly": [],
    "EPS": "1", "ECO": "0", "acSwitch": "1", "noBattery": "0", "onOff": "0",
    "grid": "0", "thirdLink": "0", "singlePhase": "0",
    "dischargeProtection": "12", "stayOn": "0", "powerLimit": "1200",
    "config": {}, "winter": "1",
}


class FakeBroker:
    """A broker with the device behind it, answering the way the capture did."""

    def __init__(self, config=None, code=200, answer=True, publish_error=None):
        self.config = dict(DEVICE_CONFIG if config is None else config)
        self.code = code
        self.answer = answer
        self.publish_error = publish_error
        self.published: list[tuple[str, dict]] = []
        self.handlers: dict[str, callable] = {}
        self.unsubscribed = 0

    async def subscribe(self, topic, handler):
        self.handlers[topic] = handler

        def unsubscribe():
            self.unsubscribed += 1
            self.handlers.pop(topic, None)

        return unsubscribe

    async def publish(self, topic, payload):
        if self.publish_error is not None:
            raise self.publish_error
        body = json.loads(payload)
        self.published.append((topic, body))
        if not self.answer:
            return
        handler = self.handlers.get(f"{topic}_reply")
        if handler is None:
            return
        data = self.config if body["method"] == "get" else body.get("params", {})
        handler(json.dumps({
            "data": data, "code": self.code, "id": body["id"],
            "message": "SUCCESS" if self.code == 200 else "FAIL",
            "deviceId": DEVICE_ID, "identifier": body["identifier"],
        }))

    # convenience for the tests
    def writes(self):
        return [b for t, b in self.published if b["method"] == "set"]


async def connected(broker: FakeBroker | None = None, **kwargs) -> EzhiMqttApi:
    broker = broker or FakeBroker()
    api = EzhiMqttApi(DEVICE_ID, broker.publish, broker.subscribe, **kwargs)
    await api.async_subscribe()
    return api


# async_set_remote is the vendor's cloud-only control channel: an HTTP call to
# their server, not something a local broker can offer. It is called on a cloud
# object, never on coordinator.api, so no entity can reach for it here.
CLOUD_ONLY = {"async_set_remote"}


def test_mqtt_api_offers_every_method_the_cloud_api_does():
    """Entities call coordinator.api.* -- the transports must be interchangeable."""
    from ezhi_component.cloud import EzhiCloudApi

    required = {n for n in dir(EzhiCloudApi)
                if n.startswith("async_") and not n.startswith("async__")} - CLOUD_ONLY
    assert required, "the surface check found nothing to compare against"
    missing = required - set(dir(EzhiMqttApi))
    assert not missing, f"MQTT API is missing: {sorted(missing)}"


def test_get_config_asks_for_system_mode_and_unwraps_the_reply():
    async def scenario():
        broker = FakeBroker()
        api = await connected(broker)
        config = await api.async_get_config()
        assert config["systemMode"] == "4"
        topic, body = broker.published[-1]
        assert topic == p.topic_get(DEVICE_ID)
        assert body["identifier"] == "systemMode"
        assert body["method"] == "get"

    asyncio.run(scenario())


def test_a_request_fails_loudly_when_it_cannot_subscribe_either():
    """The self-healing path is allowed to fail -- it must not swallow it. If
    the broker refuses the subscription there is no way to hear the reply, and
    publishing anyway would leave a request hanging until its timeout."""
    async def scenario():
        async def refusing_subscribe(topic, handler):
            raise RuntimeError("no broker client")

        api = EzhiMqttApi(DEVICE_ID, FakeBroker().publish, refusing_subscribe)
        with pytest.raises(EzhiMqttError, match="cannot subscribe"):
            await api.async_get_config()

    asyncio.run(scenario())


def test_subscribe_listens_on_both_reply_topics():
    async def scenario():
        broker = FakeBroker()
        await connected(broker)
        assert set(broker.handlers) == set(p.reply_topics(DEVICE_ID))

    asyncio.run(scenario())


def test_a_timeout_raises_and_leaves_no_pending_future():
    """A future left behind is a leak a late reply would resolve into nothing."""
    async def scenario():
        api = await connected(FakeBroker(answer=False), timeout=0.05)
        with pytest.raises(EzhiMqttError, match="did not answer"):
            await api.async_get_config()
        assert api._pending == {}

    asyncio.run(scenario())


def test_a_late_reply_is_dropped_and_the_next_request_still_works():
    """The device answering after we gave up must not resolve anything, and
    must not poison the transport for the request after it."""
    async def scenario():
        broker = FakeBroker(answer=False)
        api = await connected(broker, timeout=0.05)
        with pytest.raises(EzhiMqttError):
            await api.async_get_config()
        late_id = broker.published[-1][1]["id"]
        broker.handlers[p.topic_get_reply(DEVICE_ID)](json.dumps(
            {"id": late_id, "code": 200, "data": {"systemMode": "9"}}))
        broker.answer = True
        assert (await api.async_get_config())["systemMode"] == "4"

    asyncio.run(scenario())


def test_a_reply_to_a_cancelled_request_is_dropped():
    async def scenario():
        broker = FakeBroker(answer=False)
        api = await connected(broker)
        task = asyncio.ensure_future(api.async_get_config())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        corr_id = broker.published[-1][1]["id"]
        # must not raise InvalidStateError on the cancelled future
        broker.handlers[p.topic_get_reply(DEVICE_ID)](json.dumps(
            {"id": corr_id, "code": 200, "data": {}}))

    asyncio.run(scenario())


def test_a_rejection_code_raises():
    async def scenario():
        api = await connected(FakeBroker(code=400))
        with pytest.raises(EzhiMqttError, match="rejected"):
            await api.async_get_config()

    asyncio.run(scenario())


def test_a_broker_error_becomes_a_transport_error():
    """Publishing without a client raises HomeAssistantError, which the
    coordinator and the entities do not catch. Everything gets translated."""
    async def scenario():
        broker = FakeBroker(publish_error=RuntimeError("no mqtt client"))
        api = await connected(broker)
        with pytest.raises(EzhiMqttError, match="no mqtt client"):
            await api.async_get_config()
        assert api._pending == {}

    asyncio.run(scenario())


def test_a_failing_subscribe_becomes_a_transport_error():
    async def scenario():
        async def subscribe(topic, handler):
            raise RuntimeError("no mqtt client")

        api = EzhiMqttApi(DEVICE_ID, FakeBroker().publish, subscribe)
        with pytest.raises(EzhiMqttError, match="cannot subscribe"):
            await api.async_subscribe()

    asyncio.run(scenario())


def test_junk_on_the_reply_topic_does_not_break_the_transport():
    """Anyone can publish to a topic; one stray message must not be fatal."""
    async def scenario():
        broker = FakeBroker()
        api = await connected(broker)
        broker.handlers[p.topic_get_reply(DEVICE_ID)]("not json at all")
        broker.handlers[p.topic_get_reply(DEVICE_ID)](
            json.dumps({"id": "someone-elses", "code": 200, "data": {}}))
        assert (await api.async_get_config())["systemMode"] == "4"

    asyncio.run(scenario())


def test_set_system_mode_reads_the_config_first_then_writes_it_back():
    """A poll can be a minute old; a stale EPS written back undoes the app."""
    async def scenario():
        broker = FakeBroker()
        api = await connected(broker)
        await api.async_set_system_mode(systemMode="1")
        methods = [b["method"] for _, b in broker.published]
        assert methods == ["get", "set"]
        write = broker.writes()[-1]
        assert write["params"]["systemMode"] == "1"
        # untouched fields carried forward, not dropped
        assert write["params"]["EPS"] == "1"
        assert write["params"]["userSetPower"] == "200"

    asyncio.run(scenario())


def test_a_misspelled_field_is_refused_rather_than_silently_ignored():
    """The cloud builder's typo guard is exactly why it gets reused here."""
    async def scenario():
        api = await connected()
        with pytest.raises(Exception, match="unknown systemMode field"):
            await api.async_set_system_mode(systemMod="1")

    asyncio.run(scenario())


def test_writes_go_to_the_set_topic():
    async def scenario():
        broker = FakeBroker()
        api = await connected(broker)
        await api.async_set_system_mode(systemMode="4")
        assert broker.published[-1][0] == p.topic_set(DEVICE_ID)

    asyncio.run(scenario())


def test_backup_power_on_clears_eco_in_the_same_write():
    """The firmware treats EPS and ECO as mutually exclusive."""
    async def scenario():
        broker = FakeBroker()
        api = await connected(broker)
        await api.async_set_backup_power(True)
        params = broker.writes()[-1]["params"]
        assert (params["EPS"], params["ECO"]) == ("1", "0")

    asyncio.run(scenario())


def test_backup_power_off_does_not_turn_eco_on():
    async def scenario():
        broker = FakeBroker()
        api = await connected(broker)
        await api.async_set_backup_power(False)
        params = broker.writes()[-1]["params"]
        assert (params["EPS"], params["ECO"]) == ("0", "0")

    asyncio.run(scenario())


def test_eco_on_clears_backup_power():
    async def scenario():
        broker = FakeBroker()
        api = await connected(broker)
        await api.async_set_eco(True)
        params = broker.writes()[-1]["params"]
        assert (params["ECO"], params["EPS"]) == ("1", "0")

    asyncio.run(scenario())


def test_high_power_switches_the_ceiling():
    async def scenario():
        broker = FakeBroker()
        api = await connected(broker)
        await api.async_set_high_power(True)
        assert broker.writes()[-1]["params"]["powerLimit"] == "1200"
        await api.async_set_high_power(False)
        assert broker.writes()[-1]["params"]["powerLimit"] == "800"

    asyncio.run(scenario())


def test_soc_limit_writes_both_bounds_through_system_mode():
    """socMin stays under the fixture's discharge floor of 12% on purpose --
    raising it past that is refused, which the guard test below covers."""
    async def scenario():
        broker = FakeBroker()
        api = await connected(broker)
        await api.async_set_soc_limit(soc_min=5, soc_max=95)
        params = broker.writes()[-1]["params"]
        assert (params["socMin"], params["socMax"]) == ("5", "95")

    asyncio.run(scenario())


def test_soc_limit_keeps_the_other_bound_from_the_config():
    async def scenario():
        broker = FakeBroker()
        api = await connected(broker)
        await api.async_set_soc_limit(soc_max=90)
        params = broker.writes()[-1]["params"]
        assert (params["socMin"], params["socMax"]) == ("10", "90")

    asyncio.run(scenario())


def test_soc_limit_refuses_an_impossible_window():
    async def scenario():
        api = await connected()
        with pytest.raises(Exception, match="implausible SOC window"):
            await api.async_set_soc_limit(soc_min=90, soc_max=20)

    asyncio.run(scenario())


def test_soc_limit_needs_at_least_one_bound():
    async def scenario():
        api = await connected()
        with pytest.raises(EzhiMqttError, match="at least one bound"):
            await api.async_set_soc_limit()

    asyncio.run(scenario())


def test_raising_soc_min_into_the_discharge_floor_is_refused():
    """Otherwise the SOC Minimum entity is a way around the app's own rule."""
    async def scenario():
        api = await connected()
        with pytest.raises(Exception, match="discharge"):
            await api.async_set_soc_limit(soc_min=11)

    asyncio.run(scenario())


def test_read_modify_write_pairs_are_serialised():
    """Two entities must not each read the config and each write over the other."""
    async def scenario():
        broker = FakeBroker()
        api = await connected(broker)
        await asyncio.gather(
            api.async_set_system_mode(systemMode="1"),
            api.async_set_system_mode(systemMode="2"),
        )
        methods = [b["method"] for _, b in broker.published]
        assert methods == ["get", "set", "get", "set"]

    asyncio.run(scenario())


def test_on_off_goes_out_on_this_transport():
    """It used to be refused here and handed to the cloud. That was wrong for
    the one installation this transport exists for: pointing the device at a
    local broker means it is NOT on the vendor cloud, so a cloud onOff cannot
    reach it -- it answers 200 and nothing happens (measured 2026-08-13)."""
    async def scenario():
        broker = FakeBroker()
        api = await connected(broker)
        await api.async_set_on_off(False)
        write = broker.writes()[-1]
        assert write["identifier"] == "onOff"
        assert write["method"] == "set"
        assert broker.published[-1][0] == p.topic_set(DEVICE_ID)

    asyncio.run(scenario())


def test_on_off_keeps_the_protocol_inversion():
    """status "0" is ON. Byte-verified against the vendor app's own BLE write
    (iOS HCI snoop, 2026-08-08): off is "1". Getting this backwards would turn
    a standby command into a no-op and an on command into a radio kill."""
    async def scenario():
        broker = FakeBroker()
        api = await connected(broker)
        await api.async_set_on_off(False)
        assert broker.writes()[-1]["params"] == {"status": "1"}
        await api.async_set_on_off(True)
        assert broker.writes()[-1]["params"] == {"status": "0"}

    asyncio.run(scenario())


def test_on_off_matches_the_frame_bluetooth_sends():
    """The MQTT and BLE envelopes differ in packaging, not in content. This
    pins identifier and params against ble_protocol so the two transports
    cannot drift apart -- that shared shape is the whole reason this payload
    did not need its own capture."""
    async def scenario():
        ble_protocol = pytest.importorskip(
            "ezhi_component.ble_protocol",
            reason="ble_protocol needs cryptography (requirements-test.txt)")
        broker = FakeBroker()
        api = await connected(broker)
        await api.async_set_on_off(False)
        mqtt_write = broker.writes()[-1]
        ble_frame = ble_protocol.cmd_set_on_off(DEVICE_ID, on=False)
        assert mqtt_write["identifier"] == ble_frame["identifier"]
        assert mqtt_write["params"] == ble_frame["params"]
        assert mqtt_write["method"] == ble_frame["method"] == "set"

    asyncio.run(scenario())


def test_a_request_subscribes_itself_when_startup_could_not():
    """A broker that comes up after Home Assistant used to leave this transport
    unsubscribed for good: every poll failed until someone reloaded the entry.
    Subscribe-before-publish still holds -- it happens inside the request."""
    async def scenario():
        broker = FakeBroker()
        api = EzhiMqttApi(DEVICE_ID, broker.publish, broker.subscribe)
        # deliberately no async_subscribe() -- this is the startup-failed state
        assert await api.async_get_config()
        assert broker.handlers, "nothing was subscribed"

    asyncio.run(scenario())


def test_the_late_subscribe_happens_before_the_publish():
    """The other order is a race the device always wins: it answers in
    milliseconds, and a reply nobody listens for is gone."""
    async def scenario():
        broker = FakeBroker()
        order = []
        publish, subscribe = broker.publish, broker.subscribe

        async def traced_publish(topic, payload):
            order.append("publish")
            return await publish(topic, payload)

        async def traced_subscribe(topic, handler):
            order.append("subscribe")
            return await subscribe(topic, handler)

        api = EzhiMqttApi(DEVICE_ID, traced_publish, traced_subscribe)
        await api.async_get_config()
        assert order[0] == "subscribe", order

    asyncio.run(scenario())


def test_a_shut_down_transport_does_not_resubscribe_itself():
    """The self-healing path must not outlive the unload. A poll landing in the
    window between async_unsubscribe and the coordinator shutting down would
    otherwise create subscriptions nobody cleans up afterwards -- and a reload
    would leave two sets of handlers on the same reply topics."""
    async def scenario():
        broker = FakeBroker()
        api = await connected(broker)
        await api.async_unsubscribe()
        before = len(broker.handlers)
        with pytest.raises(EzhiMqttError, match="shut down"):
            await api.async_get_config()
        assert len(broker.handlers) == before, "it subscribed after the unload"

    asyncio.run(scenario())


def test_device_info_is_a_first_class_read():
    async def scenario():
        broker = FakeBroker()
        api = await connected(broker)
        await api.async_get_device_info()
        assert broker.published[-1][1]["identifier"] == "deviceInfo"

    asyncio.run(scenario())


def test_output_data_is_offered():
    """The capture this test used to wait for arrived on 2026-08-11.

    It read: "It is only ever pushed, never answered on request -- so the
    sensors built on it stay Bluetooth-only until a capture proves otherwise."
    A `get` with identifier outputData was then answered with 50 fields, and
    the device was not seen pushing at all in two captures. The assumption is
    inverted here rather than deleted, so the reversal stays visible in the
    history of this file.
    """
    assert hasattr(EzhiMqttApi, "async_get_output_data")


def test_unsubscribe_drops_the_subscriptions_and_fails_what_is_waiting():
    async def scenario():
        broker = FakeBroker(answer=False)
        api = await connected(broker)
        pending = asyncio.ensure_future(api.async_get_config())
        await asyncio.sleep(0)
        await api.async_unsubscribe()
        with pytest.raises(EzhiMqttError):
            await pending
        assert broker.unsubscribed == 2
        assert api._pending == {}

    asyncio.run(scenario())


def test_unsubscribe_is_safe_when_a_handle_raises():
    """Unloading must not raise, whatever the broker client does."""
    async def scenario():
        async def subscribe(topic, handler):
            def unsubscribe():
                raise RuntimeError("already gone")
            return unsubscribe

        api = EzhiMqttApi(DEVICE_ID, FakeBroker().publish, subscribe)
        await api.async_subscribe()
        await api.async_unsubscribe()

    asyncio.run(scenario())


def test_errors_are_never_the_cloud_auth_kind():
    """That one triggers a reauth flow asking for cloud tokens -- which an
    entry running purely on a local broker does not have."""
    from ezhi_component.cloud import EzhiCloudAuthError

    assert not issubclass(EzhiMqttError, EzhiCloudAuthError)


# --- outputData: the telemetry read (added 2026-08-11) ------------------------
# Until then the MQTT transport had no output read at all and the sensors built
# on it were Bluetooth-only, on the assumption that the device only ever pushes
# outputData. It does not have to be pushed: `get` with that identifier is
# answered like any other, verified against the real device with 50 fields.

OUTPUT_PAYLOAD = {
    "batV": "50.8", "batC": "-0.4", "gF": "50.0", "ogV": "232.3",
    "ofgV": "232.1", "ofgC": "0.2", "rTime": "94876", "devTemp2": "31.3",
}


def test_get_output_data_reads_the_outputdata_identifier():
    broker = FakeBroker(config=OUTPUT_PAYLOAD)

    async def scenario():
        api = await connected(broker)
        return await api.async_get_output_data()

    result = asyncio.run(scenario())

    assert result["batV"] == "50.8"
    assert result["rTime"] == "94876"
    topic, payload = broker.published[-1]
    assert topic == p.topic_get(DEVICE_ID)
    assert payload["identifier"] == "outputData"
    # companyKey is the field that looks like decoration and is not: a get
    # without it reaches the device and is simply never answered.
    assert payload["companyKey"] == p.COMPANY_KEY


def test_output_read_failure_stays_in_the_cloud_error_family():
    """poll_control_data degrades a failed extra read instead of failing the
    whole poll -- but only because it catches EzhiCloudError. If this ever
    stops being a subclass, a transient telemetry failure would take the
    control entities down with it, silently."""
    from ezhi_component.cloud import EzhiCloudError

    assert issubclass(EzhiMqttError, EzhiCloudError)


# --- the diagnostic reads, and the parallel poll ---------------------------
# Measured 2026-08-11 against the real device: ten identifiers fired together
# answered in 2.5-3.0 s wall clock over three runs, while a single sequential
# read took 5.05 s. The device answers on a ~5 s firmware tick, so requests
# that land in one window are all answered by it. These tests pin the property
# that makes that usable: the reads must go out together, not one after
# another.


def test_one_failed_diagnostic_read_does_not_cost_the_others():
    """One identifier timing out must not cost the other five. Their entities
    stay live; only the failed one's go unavailable."""
    async def scenario():
        api = await connected()

        async def flaky_get(identifier):
            if identifier == "meterStatus":
                raise EzhiMqttError("the inverter did not answer meterStatus")
            return {"ok": identifier}

        api._get = flaky_get
        extras = (await api.async_poll_all())["extras"]
        assert "meterStatus" not in extras
        assert extras["btLock"] == {"ok": "btLock"}
        assert len(extras) == len(EXTRA_IDENTIFIERS) - 1

    asyncio.run(scenario())


def test_every_diagnostic_read_failing_is_still_a_valid_poll():
    """The control entities must not lose availability because the diagnostic
    reads did."""
    async def scenario():
        api = await connected()

        async def only_diagnostics_fail(identifier):
            if identifier in EXTRA_IDENTIFIERS:
                raise EzhiMqttError("no answer")
            return {"ok": identifier}

        api._get = only_diagnostics_fail
        data = await api.async_poll_all()
        assert data["extras"] == {}
        assert data["config"] == {"ok": "systemMode"}
        assert data["output"] == {"ok": "outputData"}

    asyncio.run(scenario())


def test_extra_identifiers_match_the_field_tables():
    """A table entry for an identifier nobody reads is a permanently
    unavailable entity; a read nobody has a table for is a wasted round trip
    every poll."""
    from ezhi_component.device_fields import (
        EXTRA_BINARY_FIELDS, EXTRA_SENSOR_FIELDS)

    used = {f.identifier for f in EXTRA_SENSOR_FIELDS + EXTRA_BINARY_FIELDS}
    assert used == set(EXTRA_IDENTIFIERS)


def test_extra_identifiers_exclude_the_duplicates_and_the_silent_one():
    """si is covered by ALARM_SENSORS; wifiStatus, caTz and combineVersion
    carry nothing deviceInfo does not; batteryCellData does not answer `get` at
    all. Reading any of them would be a round trip for nothing, every poll."""
    for identifier in ("si", "wifiStatus", "caTz", "combineVersion",
                       "batteryCellData"):
        assert identifier not in EXTRA_IDENTIFIERS


def test_poll_all_fires_config_output_device_and_extras_together():
    """Nine reads, one firmware tick. Sequential they are ~45 s -- over the
    20 s startup budget and most of a 60 s poll interval."""
    async def scenario():
        api = await connected()
        in_flight = []

        async def slow_get(identifier):
            in_flight.append(identifier)
            await asyncio.sleep(0.05)
            return {}

        api._get = slow_get
        task = asyncio.create_task(api.async_poll_all())
        await asyncio.sleep(0.01)            # long before any read returns
        assert len(in_flight) == 3 + len(EXTRA_IDENTIFIERS)
        assert set(in_flight) >= {"systemMode", "outputData", "deviceInfo"}
        await task

    asyncio.run(scenario())


def test_poll_all_returns_the_coordinator_data_shape():
    async def scenario():
        api = await connected()

        async def ok_get(identifier):
            return {"ok": identifier}

        api._get = ok_get
        data = await api.async_poll_all()
        assert set(data) == {"config", "output", "device", "extras"}
        assert data["config"] == {"ok": "systemMode"}
        assert data["output"] == {"ok": "outputData"}
        assert data["device"] == {"ok": "deviceInfo"}
        assert set(data["extras"]) == set(EXTRA_IDENTIFIERS)

    asyncio.run(scenario())


def test_poll_all_still_fails_the_whole_poll_on_a_config_error():
    """Unchanged contract: no config, no poll. The coordinator turns this into
    UpdateFailed -- honest, because without systemMode we do not know what the
    device is doing."""
    async def scenario():
        api = await connected()

        async def only_config_fails(identifier):
            if identifier == "systemMode":
                raise EzhiMqttError("no answer")
            return {}

        api._get = only_config_fails
        with pytest.raises(EzhiMqttError):
            await api.async_poll_all()

    asyncio.run(scenario())


def test_poll_all_degrades_rather_than_fails_when_another_read_dies():
    """A telemetry or diagnostic read must never cost the control entities
    their availability."""
    async def scenario():
        api = await connected()

        async def output_and_extra_fail(identifier):
            if identifier in ("outputData", "meterStatus"):
                raise EzhiMqttError("no answer")
            return {"ok": identifier}

        api._get = output_and_extra_fail
        data = await api.async_poll_all()
        assert data["config"] == {"ok": "systemMode"}
        assert data["output"] == {}          # empty, never stale
        assert data["device"] == {"ok": "deviceInfo"}
        assert "meterStatus" not in data["extras"]
        assert data["extras"]["btLock"] == {"ok": "btLock"}

    asyncio.run(scenario())


def test_a_programming_error_is_not_swallowed_by_the_gather():
    """The sequential path degrades on `except EzhiCloudError` and nothing
    wider, so a bug in our own framing surfaces instead of vanishing -- see
    test_an_unexpected_output_error_is_not_swallowed in test_control_poll.py.

    gather(..., return_exceptions=True) collects BaseException
    indiscriminately, which would have downgraded exactly those bugs to a log
    line on this transport only. That is the silent-default-fallback shape, and
    this test is what keeps it out."""
    async def scenario():
        api = await connected()

        async def buggy_get(identifier):
            if identifier == "outputData":
                raise TypeError("bug in our own framing")
            return {}

        api._get = buggy_get
        with pytest.raises(TypeError):
            await api.async_poll_all()

    asyncio.run(scenario())


def test_a_cancelled_poll_propagates_as_cancelled():
    """CancelledError is a BaseException and not an EzhiCloudError. A cancelled
    poll must surface as cancelled, never be reported as "the device did not
    answer" -- HA shutting down mid-poll is not a device fault."""
    async def scenario():
        api = await connected()

        async def cancelled_get(identifier):
            if identifier == "deviceInfo":
                raise asyncio.CancelledError()
            return {}

        api._get = cancelled_get
        with pytest.raises(asyncio.CancelledError):
            await api.async_poll_all()

    asyncio.run(scenario())
