"""Getting a connection at all -- including opening the radio window first.

Nothing here touches a radio or the cloud: the finder, the connect step and the
sleep are all injected, so the two things that actually matter can be pinned
without hardware. Those two are:

  * the wake is edge-triggered (0, then 1) -- writing 1 while it already reads
    1 does nothing, measured 2026-08-05 and reproduced four times, and
  * a shut window without cloud credentials is a clear error, not a hang.

No pytest-asyncio in this project: the coroutines are driven with asyncio.run().
"""
from __future__ import annotations

import asyncio

import pytest
from ezhi_component.ble_connect import (
    ReconnectingLink,
    async_connect_with_wake,
    async_wake_radio,
)
from ezhi_component.ble_link import EzhiBleError

DEVICE_ID = "D00000000000"
HASS = object()          # opaque here: only the injected finder ever reads it


class FakeCloud:
    """Records setRemote calls; the real one posts them to the vendor cloud."""

    def __init__(self, log: list | None = None):
        self.log = [] if log is None else log

    async def async_set_remote(self, identifier: str, params: dict) -> dict:
        self.log.append((identifier, params["status"]))
        return {"flag": "0"}


def recording_sleep(log: list):
    async def _sleep(seconds: float) -> None:
        log.append(("sleep", seconds))
    return _sleep


class FakeDevice:
    def __init__(self, name="EZHI_D00000000000"):
        self.name = name
        self.address = "AA:BB:CC:DD:EE:11"


class FakeClient:
    is_connected = True


def finder_returning(*results):
    """A finder that yields the given results in order, repeating the last."""
    queue = list(results)

    def _find(hass, device_id):
        assert hass is HASS
        return queue.pop(0) if len(queue) > 1 else queue[0]

    return _find


def connect_returning(*results):
    """A connect step that yields clients or raises the exceptions given.

    The sentinel "hang" suspends forever -- the shape of establish_connection
    retrying against a device whose radio is off.
    """
    queue, calls, kwargs_log = list(results), [], []

    async def _connect(device, name, **kwargs):
        calls.append(device)
        kwargs_log.append(kwargs)
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        if item == "hang":
            await asyncio.Event().wait()
        return item

    _connect.calls = calls
    _connect.kwargs = kwargs_log
    return _connect


def adv_returning(*results):
    """A post-wake advertisement wait yielding the given devices (or None)."""
    queue, timeouts = list(results), []

    async def _await_adv(hass, device_id, timeout):
        assert hass is HASS
        timeouts.append(timeout)
        return queue.pop(0) if len(queue) > 1 else queue[0]

    _await_adv.timeouts = timeouts
    return _await_adv


# --- the wake ---------------------------------------------------------------


def test_wake_toggles_zero_then_one_with_a_gap():
    """btOnOff is edge-triggered: setting 1 while it reads 1 does nothing.

    Measured 2026-08-05: the value already read "1" while the radio was off,
    and writing "1" again changed nothing. Only 0 -> 1 switches it on -- and
    the two writes need a gap, or the cloud delivers them as one state.
    """
    log: list = []

    asyncio.run(async_wake_radio(FakeCloud(log), sleep=recording_sleep(log)))

    assert log[0] == ("btOnOff", "0"), "the falling edge has to come first"
    assert log[-1] == ("btOnOff", "1")
    assert log[1][0] == "sleep" and log[1][1] > 0, "the two edges must not merge"
    assert len(log) == 3


# --- connecting -------------------------------------------------------------


def test_an_open_window_connects_without_touching_the_cloud():
    """The wake costs two cloud calls and ~15 s -- not on the happy path."""
    async def scenario():
        cloud, client = FakeCloud(), FakeClient()
        got = await async_connect_with_wake(
            HASS, DEVICE_ID, cloud,
            finder=finder_returning(FakeDevice()),
            connect=connect_returning(client),
        )
        assert got is client
        assert cloud.log == [], "the cloud was called although the window was open"

    asyncio.run(scenario())


def test_a_shut_window_is_opened_over_the_cloud_and_then_retried():
    async def scenario():
        log: list = []
        client = FakeClient()
        adv = adv_returning(FakeDevice())
        got = await async_connect_with_wake(
            HASS, DEVICE_ID, FakeCloud(log),
            finder=finder_returning(None),
            connect=connect_returning(client),
            sleep=recording_sleep(log),
            await_adv=adv,
        )
        assert got is client
        assert [entry for entry in log if entry[0] == "btOnOff"] == [
            ("btOnOff", "0"), ("btOnOff", "1")]
        assert adv.timeouts, "after the wake the code must wait for a fresh " \
            "advertisement, not glance at the scanner cache once"

    asyncio.run(scenario())


def test_a_stale_advertisement_costs_one_wake_not_a_failure():
    """HA's scanner remembers a device for minutes after its radio went off, so
    "found" does not mean "reachable". A refused connection is a shut window."""
    async def scenario():
        log: list = []
        client = FakeClient()
        connect = connect_returning(OSError("connection refused"), client)
        got = await async_connect_with_wake(
            HASS, DEVICE_ID, FakeCloud(log),
            finder=finder_returning(FakeDevice()),
            connect=connect,
            sleep=recording_sleep(log),
            await_adv=adv_returning(FakeDevice()),
        )
        assert got is client
        assert len(connect.calls) == 2
        assert [entry for entry in log if entry[0] == "btOnOff"] == [
            ("btOnOff", "0"), ("btOnOff", "1")], "the wake ran twice or not at all"

    asyncio.run(scenario())


def test_no_cloud_credentials_means_no_wake_attempt():
    """Without the cloud there is nothing to open the window with -- say so,
    including the one thing the user can do about it."""
    async def scenario():
        with pytest.raises(EzhiBleError, match="Batterie-Taster"):
            await async_connect_with_wake(
                HASS, DEVICE_ID, None,
                finder=finder_returning(None),
                connect=connect_returning(FakeClient()),
            )

    asyncio.run(scenario())


def test_still_missing_after_the_wake_is_an_error_not_a_second_wake():
    """Two wakes in a row would be two more cloud writes for nothing."""
    async def scenario():
        log: list = []
        with pytest.raises(EzhiBleError):
            await async_connect_with_wake(
                HASS, DEVICE_ID, FakeCloud(log),
                finder=finder_returning(None),
                connect=connect_returning(FakeClient()),
                sleep=recording_sleep(log),
                await_adv=adv_returning(None),
            )
        assert len([e for e in log if e[0] == "btOnOff"]) == 2

    asyncio.run(scenario())


def test_a_connect_failure_after_the_wake_surfaces_as_a_ble_error():
    """bleak's own error family would escape the entity handlers."""
    async def scenario():
        log: list = []
        with pytest.raises(EzhiBleError):
            await async_connect_with_wake(
                HASS, DEVICE_ID, FakeCloud(log),
                finder=finder_returning(FakeDevice()),
                connect=connect_returning(OSError("nope")),
                sleep=recording_sleep(log),
                await_adv=adv_returning(FakeDevice()),
            )

    asyncio.run(scenario())


def test_a_hanging_probe_is_bounded_and_buys_the_wake():
    """establish_connection against a stale scanner entry retries for up to
    80 s by default (4 x 20 s) -- measured 2026-08-06 as the reproducible 60 s
    startup timeout. The probe's only job is "window open or not"; it gets one
    attempt and a hard deadline, then the wake path takes over.
    """
    async def scenario():
        log: list = []
        client = FakeClient()
        connect = connect_returning("hang", client)
        got = await async_connect_with_wake(
            HASS, DEVICE_ID, FakeCloud(log),
            finder=finder_returning(FakeDevice()),
            connect=connect,
            sleep=recording_sleep(log),
            await_adv=adv_returning(FakeDevice()),
            probe_timeout=0.01,
        )
        assert got is client
        assert connect.kwargs[0].get("max_attempts") == 1, \
            "the probe must not inherit the connector's four attempts"
        assert "max_attempts" not in connect.kwargs[1], \
            "the post-wake connect may retry -- the device just woke up"
        assert [e for e in log if e[0] == "btOnOff"] == [
            ("btOnOff", "0"), ("btOnOff", "1")]

    asyncio.run(scenario())


def test_a_failed_wake_is_not_repeated_inside_the_cooldown():
    """Polling every minute against an absent device must not mean two cloud
    writes a minute, forever (spec: kein Dauerfeuer auf die Cloud)."""
    async def scenario():
        log: list = []
        now = [1000.0]
        state: dict = {"last": None}
        kwargs = dict(
            finder=finder_returning(None),
            connect=connect_returning(FakeClient()),
            sleep=recording_sleep(log),
            await_adv=adv_returning(None),
            wake_state=state,
            clock=lambda: now[0],
        )
        with pytest.raises(EzhiBleError):
            await async_connect_with_wake(HASS, DEVICE_ID, FakeCloud(log), **kwargs)
        assert len([e for e in log if e[0] == "btOnOff"]) == 2

        with pytest.raises(EzhiBleError, match="ooldown"):
            await async_connect_with_wake(HASS, DEVICE_ID, FakeCloud(log), **kwargs)
        assert len([e for e in log if e[0] == "btOnOff"]) == 2, \
            "the second attempt woke the radio again inside the cooldown"

        now[0] += 601.0
        with pytest.raises(EzhiBleError):
            await async_connect_with_wake(HASS, DEVICE_ID, FakeCloud(log), **kwargs)
        assert len([e for e in log if e[0] == "btOnOff"]) == 4

    asyncio.run(scenario())


def test_a_successful_connect_resets_the_cooldown():
    """The cooldown throttles consecutive failures, not recovery: after a
    successful session the next legitimate wake must not have to wait."""
    async def scenario():
        log: list = []
        state: dict = {"last": None}
        got = await async_connect_with_wake(
            HASS, DEVICE_ID, FakeCloud(log),
            finder=finder_returning(None),
            connect=connect_returning(FakeClient()),
            sleep=recording_sleep(log),
            await_adv=adv_returning(FakeDevice()),
            wake_state=state,
            clock=lambda: 1000.0,
        )
        assert got is not None
        assert state["last"] is None, "success must clear the cooldown"

    asyncio.run(scenario())


# --- reconnecting -----------------------------------------------------------


class FakeLink:
    """Stands in for EzhiBleLink: connects on demand, drops when told to."""

    def __init__(self):
        self.connects, self.sent, self.available = 0, [], False

    async def async_connect(self) -> None:
        await asyncio.sleep(0)      # a real connect suspends; so must this one
        self.connects += 1
        self.available = True

    async def async_send(self, command: dict) -> dict:
        self.sent.append(command)
        return {"code": 200}

    async def async_disconnect(self) -> None:
        self.available = False


def test_the_first_send_opens_the_connection():
    async def scenario():
        link = FakeLink()
        await ReconnectingLink(link).async_send({"id": "1"})
        assert link.connects == 1
        assert link.sent == [{"id": "1"}]

    asyncio.run(scenario())


def test_a_dropped_connection_is_reopened_rather_than_reported():
    """Without this the first hiccup leaves the control entities dead until
    Home Assistant restarts."""
    async def scenario():
        link = FakeLink()
        reconnecting = ReconnectingLink(link)
        await reconnecting.async_send({"id": "1"})
        link.available = False
        await reconnecting.async_send({"id": "2"})
        assert link.connects == 2
        assert [c["id"] for c in link.sent] == ["1", "2"]

    asyncio.run(scenario())


def test_two_callers_at_once_open_one_connection_not_two():
    async def scenario():
        link = FakeLink()
        reconnecting = ReconnectingLink(link)
        await asyncio.gather(
            reconnecting.async_send({"id": "1"}),
            reconnecting.async_send({"id": "2"}),
        )
        assert link.connects == 1

    asyncio.run(scenario())


def test_ensure_connected_shares_the_lock_with_send():
    """The startup warm-connect and the first scheduled poll can overlap; two
    parallel connects would knock each other's client out."""
    async def scenario():
        link = FakeLink()
        reconnecting = ReconnectingLink(link)
        await asyncio.gather(
            reconnecting.async_ensure_connected(),
            reconnecting.async_send({"id": "1"}),
        )
        assert link.connects == 1
        assert [c["id"] for c in link.sent] == ["1"]

    asyncio.run(scenario())


def test_a_send_is_never_retried_by_itself():
    """A command that failed mid-flight may well have landed. Retrying it would
    write to the hardware twice."""
    async def scenario():
        link = FakeLink()

        async def failing(command):
            raise EzhiBleError("boom")

        link.async_send = failing
        with pytest.raises(EzhiBleError):
            await ReconnectingLink(link).async_send({"id": "1"})
        assert link.connects == 1

    asyncio.run(scenario())
