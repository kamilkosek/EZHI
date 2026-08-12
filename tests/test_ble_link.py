"""A fake client is enough here -- the real radio is covered by the E2E task.

No pytest-asyncio in this project: the older tests drive their coroutines with
asyncio.run(), and so does this one.
"""
from __future__ import annotations

import asyncio

import pytest
from ezhi_component import ble_protocol as p
from ezhi_component.ble_link import EzhiBleLink, EzhiBleError

DEVICE_ID = "D00000000000"
# Device -> phone frame control: fragment follows / last fragment.
FC_DEVICE_FRAG, FC_DEVICE_LAST = 0x14, 0x04


def device_frames(reply: dict) -> list[bytes]:
    """Fragment a reply the way the inverter does: raw ciphertext, no hex layer."""
    payload = bytes.fromhex(p.build_payload(reply).decode())
    frames, off, seq, frag_max = [], 0, 0, 64 - 4 - 2
    while True:
        remaining = len(payload) - off
        if remaining > frag_max:
            body = remaining.to_bytes(2, "little") + payload[off:off + frag_max]
            fc, off = FC_DEVICE_FRAG, off + frag_max
        else:
            body, fc, off = payload[off:], FC_DEVICE_LAST, len(payload)
        frames.append(bytes([0x4D, fc, seq & 0xFF, len(body)]) + body)
        seq += 1
        if off >= len(payload):
            return frames


class FakeClient:
    """Answers a command once its last fragment has been written."""

    def __init__(self, reply: dict | None = None, answer: bool = True):
        self.is_connected, self.writes, self.mtu_size = True, [], 64
        self._notify = None
        self._reply = reply or {"code": 200, "message": "SUCCESS"}
        self._answer = answer
        self._rx = bytearray()

    async def start_notify(self, uuid, cb):
        self._notify = cb

    async def write_gatt_char(self, uuid, data, response=True):
        # Yields control on every fragment, so an unserialised sender would
        # interleave two commands here and the reassembly below would notice.
        await asyncio.sleep(0)
        self.writes.append(bytes(data))
        self._rx.extend(data[6:] if data[1] & p.FC_FRAG else data[4:])
        if not data[1] & p.FC_FRAG and self._answer:
            # Echo the command's identifier, as the real device does.
            command, self._rx = p.decrypt_hex(bytes(self._rx)), bytearray()
            reply = {"identifier": command.get("identifier"), **self._reply}
            for frame in device_frames(reply):
                self._notify(None, frame)

    async def disconnect(self):
        self.is_connected = False


def connector_for(client):
    async def _connect():
        return client
    return _connect


def messages_in(writes: list[bytes]) -> list[dict]:
    """Reassemble the write log the way the device would."""
    out, buf = [], bytearray()
    for frame in writes:
        buf.extend(frame[6:] if frame[1] & p.FC_FRAG else frame[4:])
        if not frame[1] & p.FC_FRAG:
            out.append(p.decrypt_hex(bytes(buf)))
            buf = bytearray()
    return out


async def connected(client=None) -> EzhiBleLink:
    client = client or FakeClient()
    link = EzhiBleLink(DEVICE_ID, connector=connector_for(client))
    await link.async_connect()
    return link


def test_a_cancelled_connect_leaves_no_half_wired_client_behind():
    """Cancellation between connect and subscribe used to leave a connected
    client with no notify channel: available, but every command times out --
    and the device accepts exactly one connection, so the leaked client also
    blocks every reconnect until the radio drops it."""
    async def scenario():
        hold = asyncio.Event()

        class SlowNotifyClient(FakeClient):
            async def start_notify(self, uuid, cb):
                await hold.wait()

        client = SlowNotifyClient()
        link = EzhiBleLink(DEVICE_ID, connector=connector_for(client))
        task = asyncio.create_task(link.async_connect())
        for _ in range(3):
            await asyncio.sleep(0)   # let it reach start_notify
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert client.is_connected is False, "the client was left connected"
        assert link.available is False

    asyncio.run(scenario())


def test_a_failing_subscribe_disconnects_rather_than_leaks():
    async def scenario():
        class BrokenNotifyClient(FakeClient):
            async def start_notify(self, uuid, cb):
                raise OSError("subscribe refused")

        client = BrokenNotifyClient()
        link = EzhiBleLink(DEVICE_ID, connector=connector_for(client))
        with pytest.raises(OSError):
            await link.async_connect()
        assert client.is_connected is False
        assert link.available is False

    asyncio.run(scenario())


def test_a_failed_reply_cycle_drops_the_connection():
    """Measured 2026-08-06 23:37: a set that timed out answered LATE, the late
    fragments poisoned the next command's reassembly buffer ("length is not a
    multiple of the block length"), and because the client was still connected
    the ReconnectingLink never reconnected -- every poll failed until a manual
    reload. A session that missed or mangled a reply is desynced; the only
    safe continuation is a fresh connection (new buffer, new seq, both sides)."""
    async def scenario():
        # Timeout case: the device never answers.
        client = FakeClient(answer=False)
        link = EzhiBleLink(DEVICE_ID, connector=connector_for(client), timeout=0.05)
        await link.async_connect()
        with pytest.raises(EzhiBleError, match="did not answer"):
            await link.async_send(p.cmd_get(DEVICE_ID, "systemMode", "33"))
        assert client.is_connected is False, "a timed-out session was kept"
        assert link.available is False

        # Decode case: the device answers ONLY garbage. The garbage is
        # discarded (it may be the ~65 s status push, not the reply), so the
        # command runs into its timeout -- and the timeout drops the session.
        client = FakeClient()
        link = EzhiBleLink(DEVICE_ID, connector=connector_for(client), timeout=0.05)
        await link.async_connect()

        async def poisoned_write(uuid, data, response=True):
            await asyncio.sleep(0)
            if not data[1] & p.FC_FRAG:
                client._notify(None, bytes([0x4D, 0x04, 0x00, 0x03]) + b"xyz")
        client.write_gatt_char = poisoned_write
        with pytest.raises(EzhiBleError, match="did not answer"):
            await link.async_send(p.cmd_get(DEVICE_ID, "systemMode", "33"))
        assert client.is_connected is False, "a desynced session was kept"
        assert link.available is False

    asyncio.run(scenario())


def test_a_foreign_frame_type_is_ignored_even_mid_reassembly():
    """Measured 2026-08-07 08:01-10:05: the device pushes an unsolicited
    ~184-byte notification every ~65 s. If such a frame lands between two
    fragments of a real reply, blindly buffering it poisons the reassembly
    ("length is not a multiple of the block length") and the poll fails."""
    async def scenario():
        client = FakeClient(reply={"code": 200, "message": "SUCCESS",
                                   "identifier": "systemMode"})

        async def interleaving_write(uuid, data, response=True):
            await asyncio.sleep(0)
            if not data[1] & p.FC_FRAG:
                frames = device_frames(client._reply)
                assert len(frames) > 1, "reply too small to interleave"
                client._notify(None, frames[0])
                # a non-custom-data frame barges in mid-message
                client._notify(None, bytes([0x49, 0x04, 0x77, 0x03]) + b"\x01\x02\x03")
                for frame in frames[1:]:
                    client._notify(None, frame)
        client.write_gatt_char = interleaving_write
        link = EzhiBleLink(DEVICE_ID, connector=connector_for(client))
        await link.async_connect()
        reply = await link.async_send(p.cmd_get(DEVICE_ID, "systemMode", "33"))
        assert reply["code"] == 200

    asyncio.run(scenario())


def test_an_undecodable_message_does_not_fail_the_pending_command():
    """A complete foreign message (the push) arriving while a reply is awaited
    must be discarded, not handed to the caller as its answer -- the real
    reply is still on its way."""
    async def scenario():
        client = FakeClient(reply={"code": 200, "message": "SUCCESS",
                                   "identifier": "systemMode"})

        async def push_then_reply(uuid, data, response=True):
            await asyncio.sleep(0)
            if not data[1] & p.FC_FRAG:
                # 184 bytes of not-a-multiple-of-16 garbage, as one message
                client._notify(None, bytes([0x4D, 0x04, 0x63, 184]) + b"\xa5" * 184)
                for frame in device_frames(client._reply):
                    client._notify(None, frame)
        client.write_gatt_char = push_then_reply
        link = EzhiBleLink(DEVICE_ID, connector=connector_for(client))
        await link.async_connect()
        reply = await link.async_send(p.cmd_get(DEVICE_ID, "systemMode", "33"))
        assert reply["code"] == 200

    asyncio.run(scenario())


def test_a_reply_for_a_different_identifier_keeps_waiting():
    """Replies echo the command's identifier. A decryptable message for some
    other identifier is not this command's answer."""
    async def scenario():
        client = FakeClient()

        async def wrong_then_right(uuid, data, response=True):
            await asyncio.sleep(0)
            if not data[1] & p.FC_FRAG:
                wrong = {"code": 200, "message": "SUCCESS",
                         "identifier": "pcsOriginalData", "data": {"x": 1}}
                for frame in device_frames(wrong):
                    client._notify(None, frame)
                right = {"code": 200, "message": "SUCCESS",
                         "identifier": "systemMode", "data": {"mode": 4}}
                for frame in device_frames(right):
                    client._notify(None, frame)
        client.write_gatt_char = wrong_then_right
        link = EzhiBleLink(DEVICE_ID, connector=connector_for(client))
        await link.async_connect()
        reply = await link.async_send(p.cmd_get(DEVICE_ID, "systemMode", "33"))
        assert reply["identifier"] == "systemMode"
        assert reply["data"] == {"mode": 4}

    asyncio.run(scenario())


def test_send_fragments_and_awaits_the_reply():
    async def scenario():
        link = await connected()
        reply = await link.async_send(p.cmd_get(DEVICE_ID, "systemMode", "33"))
        assert reply["code"] == 200
        assert link._client.writes, "nothing was written to the characteristic"
        assert messages_in(link._client.writes)[0]["identifier"] == "systemMode"

    asyncio.run(scenario())


def test_missing_advertisement_is_not_a_disconnect():
    """The device stops advertising while connected -- measured 2026-08-05."""
    async def scenario():
        link = await connected()
        assert link.available is True

    asyncio.run(scenario())


def test_the_sequence_counter_runs_across_commands():
    """BluFi validates seq per connection. Restarting at 0 per command is an
    error the device would reject, so the counter lives on the link."""
    async def scenario():
        link = await connected()
        await link.async_send(p.cmd_get(DEVICE_ID, "systemMode", "33"))
        first = len(link._client.writes)
        await link.async_send(p.cmd_get(DEVICE_ID, "si", "5"))
        seqs = [f[2] for f in link._client.writes]
        assert seqs == list(range(len(seqs)))
        assert seqs[first] == first, "the second command restarted the counter"

    asyncio.run(scenario())


def test_a_reconnect_restarts_the_sequence():
    """...and the device resets its own expectation on reconnect."""
    async def scenario():
        link = await connected()
        await link.async_send(p.cmd_get(DEVICE_ID, "systemMode", "33"))
        second = FakeClient()
        link._connector = connector_for(second)
        await link.async_connect()
        await link.async_send(p.cmd_get(DEVICE_ID, "systemMode", "33"))
        assert [f[2] for f in second.writes] == list(range(len(second.writes)))

    asyncio.run(scenario())


def test_commands_are_serialised():
    """Two callers at once must not interleave their fragments on the wire."""
    async def scenario():
        link = await connected()
        await asyncio.gather(
            link.async_send(p.cmd_get(DEVICE_ID, "systemMode", "33")),
            link.async_send(p.cmd_get(DEVICE_ID, "si", "5")),
        )
        ids = [m["id"] for m in messages_in(link._client.writes)]
        assert ids == ["33", "5"], f"fragments interleaved: {ids}"

    asyncio.run(scenario())


def test_sending_without_a_connection_is_an_error_not_a_silent_no_op():
    async def scenario():
        link = EzhiBleLink(DEVICE_ID, connector=connector_for(FakeClient()))
        with pytest.raises(EzhiBleError):
            await link.async_send(p.cmd_get(DEVICE_ID, "systemMode", "33"))

    asyncio.run(scenario())


def test_a_silent_device_times_out_as_a_ble_error():
    """A bare TimeoutError would escape the entities' except clauses."""
    async def scenario():
        link = EzhiBleLink(
            DEVICE_ID, connector=connector_for(FakeClient(answer=False)),
            timeout=0.05,
        )
        await link.async_connect()
        with pytest.raises(EzhiBleError):
            await link.async_send(p.cmd_get(DEVICE_ID, "systemMode", "33"))

    asyncio.run(scenario())


def test_a_ble_error_is_catchable_as_a_cloud_error():
    """switch.py, number.py and select.py catch EzhiCloudError and nothing
    else. A transport that raised something outside that family would surface
    as an unhandled exception in the entity handler."""
    from ezhi_component.cloud import EzhiCloudError

    assert issubclass(EzhiBleError, EzhiCloudError)
