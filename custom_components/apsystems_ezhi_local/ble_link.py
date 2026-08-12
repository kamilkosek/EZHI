"""One held Bluetooth connection to the inverter, with commands serialised on it.

No Home Assistant here either: the client is handed in, so this is testable
against a fake and the radio only appears in ble_connect.py.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from . import ble_protocol
from .ble_protocol import BLUFI_CUSTOM_DATA, FC_FRAG, NOTIFY_UUID, WRITE_UUID
from .cloud import EzhiCloudError

_LOGGER = logging.getLogger(__name__)

# The device's own answer arrives within a few hundred ms in the capture. The
# generous ceiling is for a busy connection, not for a device that is gone.
DEFAULT_TIMEOUT = 20.0


class EzhiBleError(EzhiCloudError):
    """A Bluetooth transport failure.

    Subclasses EzhiCloudError on purpose. switch.py, number.py and select.py
    catch EzhiCloudError and nothing else, so an error family outside it would
    surface as an unhandled exception in the entity handler the moment the user
    picks Bluetooth. The name on the base class is historical; it is the
    integration's "the transport failed" exception, not a cloud-only one.
    """


class EzhiBleLink:
    """One held connection to the inverter.

    Held, not opened per command: the radio switches off after 15 minutes of
    idleness, and a live connection counts as use (34.5 min measured without a
    drop). Reconnecting per command would race that timer for no gain.

    `connector` is an awaitable factory returning a connected client -- bleak's
    BleakClient in production, a fake in the tests. Keeping it injected is what
    lets everything below be checked without a radio.
    """

    def __init__(
        self,
        device_id: str,
        connector: Callable[[], Awaitable[Any]],
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._device_id = device_id
        self._connector = connector
        self._timeout = timeout
        self._client: Any | None = None
        self._lock = asyncio.Lock()
        self._reply: asyncio.Future | None = None
        self._expected: str | None = None
        self._buffer = bytearray()
        # BluFi validates the sequence number per connection, so it belongs to
        # the connection and not to the command. It resets on reconnect,
        # exactly as the capture's four sessions show.
        self._seq = 0

    @property
    def device_id(self) -> str:
        return self._device_id

    @property
    def available(self) -> bool:
        # Deliberately NOT tied to advertisements: the device stops advertising
        # while connected, which would read as a fault and is not one.
        return self._client is not None and self._client.is_connected

    async def async_connect(self) -> None:
        # Assigned only once fully wired: a connected client without its notify
        # subscription would read as available while every command times out.
        # And on cancellation or failure the client is closed rather than
        # leaked -- the device accepts exactly one connection, so a leaked
        # client blocks every reconnect until the radio drops it.
        client = None
        try:
            client = await self._connector()
            await client.start_notify(NOTIFY_UUID, self._on_notify)
        except BaseException:
            if client is not None:
                try:
                    await asyncio.shield(client.disconnect())
                except BaseException:  # noqa: BLE001 - best effort, original error wins
                    pass
            raise
        self._buffer = bytearray()
        self._seq = 0
        self._client = client

    async def async_disconnect(self) -> None:
        client, self._client = self._client, None
        if client is not None and client.is_connected:
            await client.disconnect()

    def _on_notify(self, _char: Any, data: bytes) -> None:
        """Reassemble BluFi fragments, then hand the finished message over.

        Runs in bleak's callback, so it must not raise: an exception here is
        swallowed by the stack and the caller would sit out its full timeout
        with no explanation.

        Not everything arriving here is the pending command's reply. Measured
        2026-08-07 08:01-10:05 (and again 18:xx and 23:xx): after a device-side
        glitch the inverter pushes an unsolicited ~184-byte notification every
        ~65 s until its radio power-cycles. Blindly buffering those poisoned
        the reassembly mid-reply, failed the poll, and the desync reconnect ran
        straight into the next push. So: foreign frame types never touch the
        buffer, and a completed message that does not decrypt -- or answers
        some other identifier -- is logged and discarded while the caller
        keeps waiting for its real reply. A session where the reply truly got
        mangled still heals through the timeout path's reconnect.
        """
        if len(data) < 4 or data[0] != BLUFI_CUSTOM_DATA:
            _LOGGER.warning("ignored a foreign BLE frame: %s", bytes(data).hex())
            return
        self._buffer.extend(data[6:] if data[1] & FC_FRAG else data[4:])
        if data[1] & FC_FRAG:
            return
        payload, self._buffer = bytes(self._buffer), bytearray()
        if self._reply is None or self._reply.done():
            # Unsolicited, or arriving after the caller gave up. Dropping it is
            # correct -- there is no one to hand it to -- but the hex is worth
            # logging: it is the only sample of the push we ever get.
            _LOGGER.warning("dropped an unexpected %d-byte BLE message: %s",
                            len(payload), payload.hex())
            return
        try:
            message = ble_protocol.decrypt_hex(payload)
        except Exception:  # noqa: BLE001 - foreign bytes take many shapes
            _LOGGER.warning("discarded an undecodable %d-byte BLE message "
                            "while waiting for %s: %s",
                            len(payload), self._expected, payload.hex())
            return
        if self._expected is not None and message.get("identifier") != self._expected:
            _LOGGER.warning("dropped a %r message while waiting for %r",
                            message.get("identifier"), self._expected)
            return
        self._reply.set_result(message)

    async def async_send(self, command: dict) -> dict:
        """Write one command and wait for its answer.

        Serialised behind a lock: the sequence numbers of two commands must not
        interleave on the wire, and there is only one notify channel to hang a
        reply on.
        """
        async with self._lock:
            if not self.available:
                raise EzhiBleError(
                    f"not connected to {self._device_id} -- the inverter's radio "
                    "window is closed or the connection was dropped"
                )
            self._reply = asyncio.get_running_loop().create_future()
            self._expected = command.get("identifier")
            self._buffer = bytearray()
            # Never write more than the link can carry. 64 is the size every
            # write in the capture has; a smaller MTU is respected rather than
            # exceeded, at the cost of leaving the verified frame size.
            limit = min(getattr(self._client, "mtu_size", None) or ble_protocol.PKG_LIMIT,
                        ble_protocol.PKG_LIMIT)
            frames = ble_protocol.build_frames(
                command, pkg_limit=limit, seq0=self._seq)
            self._seq = (self._seq + len(frames)) & 0xFF
            try:
                for frame in frames:
                    await self._client.write_gatt_char(
                        WRITE_UUID, frame, response=True)
            except EzhiBleError:
                raise
            except Exception as err:  # noqa: BLE001 - bleak's error family varies
                raise EzhiBleError(
                    f"writing to {self._device_id} failed: {err!r}") from err
            try:
                return await asyncio.wait_for(self._reply, self._timeout)
            except TimeoutError as err:
                # A bare TimeoutError would escape the entities' except clauses.
                await self._drop_desynced_session()
                raise EzhiBleError(
                    f"the inverter did not answer within {self._timeout}s "
                    f"({command.get('method')} {command.get('identifier')})"
                ) from err
            finally:
                self._reply = None
                self._expected = None

    async def _drop_desynced_session(self) -> None:
        """Close the connection after a reply cycle went wrong.

        Measured 2026-08-06 23:37: a set that timed out answered LATE, and the
        late fragments poisoned the next command's reassembly buffer -- while
        the still-connected client kept `available` True, so the reconnect
        layer never healed it and every poll failed until a manual reload.
        A session that missed or mangled a reply is desynced on one side or
        the other; the only safe continuation is a fresh connection, which
        resets buffer and sequence numbers on both ends. The radio window is
        open (we were just talking), so the reconnect is cheap and wake-free.
        """
        try:
            await self.async_disconnect()
        except Exception as err:  # noqa: BLE001 - the command error is the story
            _LOGGER.debug("EZHI BLE: closing a desynced session failed: %r", err)
