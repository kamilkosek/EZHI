"""Getting a connection to the inverter, and opening its radio window first.

This is the only module that knows about Home Assistant's bluetooth component,
bleak and the vendor cloud at the same time, and it is deliberately the only
one: ble_protocol.py is pure, ble_link.py takes its client from a factory, and
ble_api.py takes its link. Everything below this file is testable without a
radio because everything radio-shaped ends up here.

The awkward part is not the connecting, it is the window. The inverter's radio
switches itself off after 15 minutes of idleness, and while it is off the
device does not advertise at all -- there is nothing to connect to. Two things
are known to open it again: the physical battery button (3 s off, back on), and
the cloud call `btOnOff`. Only the second one can run unattended, which is why
a Bluetooth transport still wants cloud credentials.

`btOnOff` is edge-triggered. Measured 2026-08-05 and reproduced four times: the
value already read "1" while the radio was off, and writing "1" again did
nothing at all. Only 0 -> 1 switches it on. The cloud values are a permission,
not the live state of the radio.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable

from .ble_link import EzhiBleError

_LOGGER = logging.getLogger(__name__)

# Between the falling and the rising edge. The two writes travel to the device
# over the vendor's MQTT bridge; sent back to back they can arrive as one state
# change, which is exactly the no-op this whole dance exists to avoid.
WAKE_EDGE_GAP_S = 5.0
# The probe against a possibly-stale scanner entry. Its only job is "window
# open or not" -- left to its defaults, establish_connection retries for up to
# 4 x 20 s against a radio that is simply off, which is what reproducibly ate
# the whole 60 s startup budget on 2026-08-06.
PROBE_TIMEOUT_S = 15.0
# After the rising edge, how long a fresh advertisement may take. Measured
# ~8-10 s from the edge to visibility; generous because a proxy hop can add to
# it and nothing above waits on a budget anymore.
WAKE_DISCOVERY_TIMEOUT_S = 45.0
# Between two wake attempts that did not end in a connection. The coordinator
# polls every minute for the lifetime of the entry; without this, a device out
# of range means two cloud writes per minute, forever (the spec's explicit
# "kein Dauerfeuer auf die Cloud"). A successful connect clears it.
WAKE_COOLDOWN_S = 600.0

# The BLE name is EZHI_<deviceId> -- same id the local HTTP API reports, so
# nothing extra has to be configured to find the right device.
BLE_NAME_PREFIX = "EZHI_"

NO_CLOUD_MESSAGE = (
    "Funkfenster geschlossen und keine Cloud-Zugangsdaten hinterlegt "
    "— Geraet ueber den Batterie-Taster aufwecken (3 s aus, wieder ein)"
)


def ble_name(device_id: str) -> str:
    return f"{BLE_NAME_PREFIX}{device_id}"


async def async_wake_radio(cloud: Any, *, sleep=asyncio.sleep) -> None:
    """Open the radio window over the cloud. Edge-triggered: 0, then 1.

    Costs two cloud writes and WAKE_EDGE_GAP_S, so callers only run it once
    they have evidence the window is shut.
    """
    _LOGGER.debug("EZHI BLE: opening the radio window via btOnOff 0 -> 1")
    await cloud.async_set_remote("btOnOff", {"status": "0"})
    await sleep(WAKE_EDGE_GAP_S)
    await cloud.async_set_remote("btOnOff", {"status": "1"})


def _find_device(hass: Any, device_id: str) -> Any:
    """The BLEDevice advertising as EZHI_<deviceId>, or None.

    By name, not by MAC address: the BLE name carries the same deviceId the
    local HTTP API already reports, so the Bluetooth transport needs nothing
    configured beyond the option itself.

    Imported inside the function rather than at module scope: the tests inject
    their own finder and never have Home Assistant installed.
    """
    try:
        from homeassistant.components import bluetooth
        infos = bluetooth.async_discovered_service_info(hass, connectable=True)
    except Exception as err:  # noqa: BLE001 - missing or unloaded integration
        raise EzhiBleError(
            "Home Assistants Bluetooth-Integration ist nicht verfuegbar "
            f"({err!r}) — ohne sie gibt es keinen Bluetooth-Steuerweg"
        ) from err

    wanted = ble_name(device_id)
    for info in infos:
        if info.name == wanted:
            return info.device
    return None


async def _establish(device: Any, name: str, **kwargs: Any) -> Any:
    """bleak-retry-connector's establish_connection, imported lazily.

    Not a plain BleakClient.connect(): the retry connector is what makes this
    survive an ESPHome proxy handing the connection over, and Home Assistant
    ships it with the bluetooth integration anyway -- which is also why it is
    not in the manifest's requirements.
    """
    try:
        from bleak import BleakClient
        from bleak_retry_connector import establish_connection
    except ImportError as err:
        raise EzhiBleError(
            f"bleak/bleak-retry-connector nicht importierbar ({err}) — sie "
            "kommen mit Home Assistants Bluetooth-Integration"
        ) from err

    return await establish_connection(BleakClient, device, name, **kwargs)


async def _await_advertisement(hass: Any, device_id: str, timeout: float) -> Any:
    """The BLEDevice once a fresh EZHI_<deviceId> advertisement arrives, or None.

    A fresh advertisement, not the scanner cache: right after the wake the
    cache still holds the pre-sleep entry, and only a new advertisement proves
    the radio actually came back. A fixed sleep plus one cache lookup missed
    the device whenever it took a moment longer than the sleep.
    """
    try:
        from homeassistant.components import bluetooth
    except Exception as err:  # noqa: BLE001 - missing or unloaded integration
        raise EzhiBleError(
            "Home Assistants Bluetooth-Integration ist nicht verfuegbar "
            f"({err!r}) — ohne sie gibt es keinen Bluetooth-Steuerweg"
        ) from err

    wanted = ble_name(device_id)
    try:
        info = await bluetooth.async_process_advertisements(
            hass,
            lambda service_info: service_info.name == wanted,
            {"local_name": wanted, "connectable": True},
            bluetooth.BluetoothScanningMode.ACTIVE,
            timeout,
        )
    except TimeoutError:
        return None
    return info.device


async def async_connect_with_wake(
    hass: Any,
    device_id: str,
    cloud: Any | None,
    *,
    finder: Callable[[Any, str], Any] | None = None,
    connect: Callable[..., Awaitable[Any]] | None = None,
    sleep=asyncio.sleep,
    await_adv: Callable[[Any, str, float], Awaitable[Any]] | None = None,
    wake_state: dict | None = None,
    clock: Callable[[], float] = time.monotonic,
    probe_timeout: float = PROBE_TIMEOUT_S,
) -> Any:
    """Return a connected client, opening the radio window if it has closed.

    "Found" is not "reachable": Home Assistant's scanner remembers a device for
    a few minutes after its last advertisement, so a stale entry survives the
    radio switching off. The probe against it is therefore kept short -- one
    attempt, PROBE_TIMEOUT_S -- because its failure is information, not a
    fault: it buys the single wake attempt a missing device also gets. After
    the wake the code waits for a fresh advertisement rather than sleeping a
    fixed time; only a new advertisement proves the radio came back.

    `wake_state` is the caller's cooldown memory ({"last": float | None}).
    Passing it makes consecutive failed wakes respect WAKE_COOLDOWN_S; a
    successful connect clears it.
    """
    finder = finder or _find_device
    connect = connect or _establish
    await_adv = await_adv or _await_advertisement
    name = ble_name(device_id)

    device = finder(hass, device_id)
    if device is None:
        _LOGGER.debug(
            "EZHI BLE: %s is not in the scanner cache — the radio is "
            "presumably off", name,
        )
    else:
        try:
            async with asyncio.timeout(probe_timeout):
                client = await connect(device, name, max_attempts=1)
        except EzhiBleError:
            # The connect step itself says the transport cannot work at all
            # (bleak missing). Waking a radio changes nothing about that.
            raise
        except Exception as err:  # noqa: BLE001 - bleak's family + TimeoutError
            _LOGGER.debug(
                "EZHI BLE: %s was advertised but refused the connection (%r) "
                "— treating it as a closed radio window", name, err,
            )
        else:
            if wake_state is not None:
                wake_state["last"] = None
            return client

    if cloud is None:
        raise EzhiBleError(NO_CLOUD_MESSAGE)

    now = clock()
    if wake_state is not None and wake_state.get("last") is not None:
        remaining = WAKE_COOLDOWN_S - (now - wake_state["last"])
        if remaining > 0:
            raise EzhiBleError(
                f"Funkfenster zu; der letzte Weckversuch blieb erfolglos, der "
                f"naechste ist in {remaining:.0f} s faellig (Cooldown gegen "
                "Cloud-Dauerfeuer)"
            )
    if wake_state is not None:
        wake_state["last"] = now

    await async_wake_radio(cloud, sleep=sleep)

    device = await await_adv(hass, device_id, WAKE_DISCOVERY_TIMEOUT_S)
    if device is None:
        raise EzhiBleError(
            f"{name} hat auch {WAKE_DISCOVERY_TIMEOUT_S:.0f} s nach dem "
            "Aufwecken nicht advertised — steht ein Bluetooth-Adapter oder "
            "-Proxy in Reichweite?"
        )
    _LOGGER.debug(
        "EZHI BLE: %s advertised %.1f s after the wake", name, clock() - now)
    try:
        client = await connect(device, name)
    except Exception as err:  # noqa: BLE001 - see above
        raise EzhiBleError(
            f"Verbindung zu {name} nach dem Aufwecken fehlgeschlagen: {err!r}"
        ) from err
    _LOGGER.debug("EZHI BLE: connected to %s", name)
    if wake_state is not None:
        wake_state["last"] = None
    return client


def make_connector(hass: Any, device_id: str, cloud: Any | None):
    """The zero-argument awaitable factory EzhiBleLink expects."""
    wake_state: dict = {"last": None}

    async def _connect() -> Any:
        return await async_connect_with_wake(
            hass, device_id, cloud, wake_state=wake_state)

    return _connect


class ReconnectingLink:
    """An EzhiBleLink that reopens its connection when it has gone.

    The link itself deliberately does not: it reports "not connected" and lets
    the caller decide, because reconnecting mid-command would hide a dropped
    write. But the cloud coordinator polls every minute for the lifetime of the
    entry, and without this the first dropped connection would leave every
    control entity dead until Home Assistant restarts.

    What it does NOT do is retry a failed send. A command that failed in flight
    may well have landed -- the reply is the only part that is guaranteed
    missing -- and this writes to a battery inverter.
    """

    def __init__(self, link: Any) -> None:
        self._link = link
        # Two entities writing at once would otherwise each open their own
        # connection, and the second would knock the first one's client out.
        self._connect_lock = asyncio.Lock()

    @property
    def available(self) -> bool:
        return self._link.available

    async def async_connect(self) -> None:
        await self._link.async_connect()

    async def async_disconnect(self) -> None:
        await self._link.async_disconnect()

    async def async_ensure_connected(self) -> None:
        """Connect if the connection is gone, behind the shared lock.

        Public because the startup warm-connect uses it too; going around the
        lock there would race the first scheduled poll into a second parallel
        connect, and the device accepts exactly one connection.
        """
        if not self._link.available:
            async with self._connect_lock:
                # Another caller may have connected while we waited for it.
                if not self._link.available:
                    await self._link.async_connect()

    async def async_send(self, command: dict) -> dict:
        await self.async_ensure_connected()
        return await self._link.async_send(command)
