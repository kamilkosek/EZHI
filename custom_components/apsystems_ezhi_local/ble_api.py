"""The cloud API's surface, spoken over Bluetooth.

Same method names on purpose: entities and coordinator call
coordinator.api.async_set_*, so the two transports are drop-in replacements for
each other and nothing above has to know which one is active.

The validation is imported from cloud.py rather than repeated. The SOC window,
the discharge-protection floor and the power-limit-versus-schedule rule are
properties of the inverter, not of the wire it is reached over -- a copy here
would drift, and the copy that drifted would be the one guarding real hardware.
Two of those helpers are private to cloud.py; importing them inside the same
integration is the lesser evil against duplicating them.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from . import ble_protocol
from .ble_link import EzhiBleError
from .cloud import (
    HIGH_POWER_LIMIT,
    STANDARD_POWER_LIMIT,
    _check_discharge_protection,
    _check_power_limit_vs_schedule,
    _check_soc_window,
    _to_int,
    build_system_mode_params,
    control_output,
)

_LOGGER = logging.getLogger(__name__)

# The app's own message ids. They are echoed back in the reply, so keeping them
# makes a capture of this integration read like a capture of the app.
MSG_ID_SYSTEM_MODE_GET = "33"


# --- the BLE-only output sensors ---------------------------------------------
# Which outputData fields become sensors, and how they present. Lives here and
# not in sensor.py so the table and its parsing are testable without Home
# Assistant; sensor.py maps the plain strings onto its enums (the string
# values ARE the enum values). unit/device_class/state_class come from the
# 2026-08-08 empirics against the real device
# (docs/ezhi-onoff-mqtt-session-2026-08-08.md).
#
# Only the fields whose semantics are measured. The other ~18 extras of the
# reply (batCT, batS, cMode, batCap, metL1/L2/L3, metDC, plug, rTime, rS,
# reUpdate, freeRam, mode, ...) stay out: unclear meaning, and a sensor built
# on a guess reads as truth. They remain reachable through the ble_raw_get
# diagnostic service.

@dataclass(frozen=True)
class OutputField:
    key: str           # field name in the outputData reply
    uid: str           # unique-id suffix (EzhiCloudEntity convention)
    name: str          # display name; HA prefixes the device name
    unit: str          # native unit of measurement
    device_class: str  # SensorDeviceClass value
    state_class: str   # SensorStateClass value


OUTPUT_SENSOR_FIELDS: tuple[OutputField, ...] = (
    # DC battery -- the local HTTP API only has the power (batP).
    OutputField("batV", "ble_battery_voltage", "Battery Voltage",
                "V", "voltage", "measurement"),
    # Signed, taken raw (sample: -0.4 A while lightly charging). Which sign
    # means charge and which discharge is NOT verified -- do not flip it here;
    # flipping would bake a guess into recorded history.
    OutputField("batC", "ble_battery_current", "Battery Current",
                "A", "current", "measurement"),
    # Per-string PV. PV1 kept -- it may be the off-grid input, to be
    # verified in daylight; the 0 in the 2026-08-08 sample was a night
    # capture and proves nothing. PV2/PV3 dropped 2026-08-09 (no module on
    # those DC inputs). No pv3P in the reply. Re-add pv2/pv3 OutputFields
    # here if a string is ever wired.
    OutputField("pv1V", "ble_pv1_voltage", "PV1 Voltage",
                "V", "voltage", "measurement"),
    OutputField("pv1C", "ble_pv1_current", "PV1 Current",
                "A", "current", "measurement"),
    OutputField("pv1P", "ble_pv1_power", "PV1 Power",
                "W", "power", "measurement"),
    # Two more temperatures beside the local API's devTemp.
    OutputField("devTemp2", "ble_device_temperature_2", "Device Temperature 2",
                "°C", "temperature", "measurement"),
    OutputField("devTemp3", "ble_device_temperature_3", "Device Temperature 3",
                "°C", "temperature", "measurement"),
    # Grid quality (sample: 233.3 V / 50.0 Hz).
    OutputField("ogV", "ble_grid_voltage", "Grid Voltage",
                "V", "voltage", "measurement"),
    OutputField("gF", "ble_grid_frequency", "Grid Frequency",
                "Hz", "frequency", "measurement"),
    # Lifetime energy for the kept string. 0.0 is a real value (a dark
    # string) and total_increasing handles it as such.
    OutputField("pv1TE", "ble_pv1_total_energy", "PV1 Total Energy",
                "kWh", "energy", "total_increasing"),
)


def output_value(output: Any, key: str) -> float | None:
    """One field of an outputData payload as a float, or None.

    None for missing or unparsable -- never a default: these sensors feed
    recorded history, and a fabricated 0 V is indistinguishable from a real
    one. 0.0 itself is a value (a dark PV string reports exactly that).
    """
    raw = (output or {}).get(key)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def ble_output_available(coordinator_data: Any) -> bool:
    """Whether the output sensors have real data to show.

    False on the cloud transport (its polls always carry output={}) and after
    a failed BLE extra read -- unavailable, not a held-over stale value.
    """
    return bool(control_output(coordinator_data))


class EzhiBleApi:
    """Control the inverter over its BluFi channel instead of the cloud."""

    def __init__(self, link: Any, device_id: str, cloud: Any | None = None) -> None:
        self._link = link
        self._device_id = device_id
        # The cloud object the connect path holds anyway. Only async_set_on_off
        # uses it -- see there for why that one command does not go over BLE.
        self._cloud = cloud
        # The link serialises single commands; this serialises the read-modify-
        # write pairs, so two entities cannot each read the config, then each
        # write their own field back over the other's.
        self._write_lock = asyncio.Lock()

    @property
    def device_id(self) -> str:
        return self._device_id

    async def _send(self, command: dict) -> dict:
        reply = await self._link.async_send(command)
        code = reply.get("code")
        if code != 200:
            raise EzhiBleError(
                f"the inverter rejected {command.get('method')} "
                f"{command.get('identifier')}: {reply}"
            )
        # Note for anyone reading a green result here: code 200 means the
        # device parsed the command, not that it acted on it. It answers
        # SUCCESS for writes it ignores -- only the effect proves the effect.
        return reply

    # --- public API -------------------------------------------------------

    async def async_get_config(self) -> dict:
        """The full controllable config -- the same payload the cloud GET returns."""
        reply = await self._send(
            ble_protocol.cmd_get(
                self._device_id, "systemMode", MSG_ID_SYSTEM_MODE_GET)
        )
        return reply.get("data") or {}

    async def async_get_output_data(self) -> dict:
        """The BLE outputData reply, unwrapped -- live values the local HTTP
        API does not have.

        Measured 2026-08-08 against the local getOutputData+getPower pair: the
        BLE reply carries 35 extra fields, among them the DC-side battery
        numbers (batV, batC), per-string PV values (pv1V..pv3C, pv1P/pv2P,
        pv1TE..pv3TE), two more temperatures (devTemp2/devTemp3) and grid
        quality (ogV, gF). A first-class method rather than async_get_raw so
        the coordinator's poll does not ride a diagnostic tool.

        BLE-only on purpose: the cloud API has no such read, and the sensors
        built on this must go unavailable there instead of guessing.
        """
        reply = await self._send(
            ble_protocol.cmd_get(self._device_id, "outputData"))
        return reply.get("data") or {}

    async def async_get_raw(self, identifier: str) -> dict:
        """Diagnostic read of any get-identifier over BLE, reply untouched.

        The BLE `outputData` reply carries pcsOriginalData -- raw inverter
        frames the local HTTP API does not expose. Nothing is parsed here: this
        is a capture tool, and the point is the bytes exactly as the device
        sent them. BLE-only, because that raw field is BLE-exclusive.
        """
        return await self._send(ble_protocol.cmd_get(self._device_id, identifier))

    async def async_set_system_mode(self, **changes: Any) -> None:
        """Write systemMode, carrying every untouched field forward.

        Reads the current config first rather than trusting a cached one, for
        the same reason the cloud path does: a poll can be a minute old, and
        writing a stale EPS/ECO back would undo a change made from the vendor
        app in the meantime.
        """
        async with self._write_lock:
            config = await self.async_get_config()
            _check_discharge_protection(config, changes)
            _check_power_limit_vs_schedule(config, changes)
            params = build_system_mode_params(config, **changes)
            await self._send(
                ble_protocol.cmd_set_system_mode(self._device_id, params))

    async def async_set_on_off(self, on: bool) -> None:
        """Turn the inverter on or off -- over the cloud, even on this transport.

        Deliberately not BLE, now for a measured reason (2026-08-08). The BLE
        onOff frame is verified: an iOS HCI snoop of the vendor app's own
        BLE-direct "off" decrypts to exactly what cmd_set_on_off builds
        (byte-identical ciphertext). But that same "off" takes the whole ESP32
        down -- a lockstep ping monitor showed the device off the network for
        ~3 min (WLAN, BLE and the local HTTP API all dead), recoverable only by
        the 3 s battery button. WLAN and BLE MACs are neighbours; killing one
        kills the other. So the frame works and is exactly why we must not send
        it. onOff stays on the cloud. (The dedicated cloud onOff endpoint
        answers code 4001, so the cloud client routes onOff over setRemote --
        see docs/ezhi-onoff-mqtt-session-2026-08-08.md.)
        """
        if self._cloud is None:
            raise EzhiBleError(
                "onOff ueber Bluetooth ist unverifiziert und es ist kein "
                "Cloud-Client verfuegbar — an echter Hardware wird nicht "
                "geraten"
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
        the cloud path -- picking Bluetooth must not be a way around it.
        """
        await self.async_set_system_mode(
            powerLimit=HIGH_POWER_LIMIT if enable else STANDARD_POWER_LIMIT
        )

    async def async_set_soc_limit(
        self, soc_min: int | None = None, soc_max: int | None = None
    ) -> None:
        """Write the SOC bounds.

        There is no separate socLimit command over Bluetooth. The app's own
        setSocLimit() posts {socMax, socMin, dischargeProtection} through the
        systemMode setter, so that is what happens here -- and it is why this
        does not go through async_set_system_mode: build_system_mode_params
        knows socMin but not socMax, because on the cloud side socMax belongs
        to a different endpoint.
        """
        requested = {
            key: value
            for key, value in (("socMin", soc_min), ("socMax", soc_max))
            if value is not None
        }
        if not requested:
            raise EzhiBleError("async_set_soc_limit needs at least one bound")
        if soc_min is not None and soc_max is not None:
            _check_soc_window(_to_int(soc_min, "socMin"), _to_int(soc_max, "socMax"))
        async with self._write_lock:
            config = await self.async_get_config()
            if soc_min is None:
                soc_min = config.get("socMin")
            if soc_max is None:
                soc_max = config.get("socMax")
            if soc_min is None or soc_max is None:
                raise EzhiBleError(
                    "cannot build a socLimit payload, the config is missing "
                    "socMin/socMax -- refusing to write a partial configuration"
                )
            soc_min = _to_int(soc_min, "socMin")
            soc_max = _to_int(soc_max, "socMax")
            _check_soc_window(soc_min, soc_max)
            # Raising socMin above dischargeProtection - 2 is refused here too;
            # otherwise the SOC Minimum entity would be a way around the guard.
            _check_discharge_protection(config, requested)
            # The app's own BLE setSocLimit() sends only {socMax, socMin,
            # dischargeProtection} -- and measured 2026-08-07 00:32 on the real
            # device, that subset is never answered (2x reproduced; the write
            # does not land either). The full merged field set, the shape every
            # verified write uses, answers in ~8-10 s. That reconstructed app
            # path never appeared in the capture, so the device's measured
            # behaviour wins. socMax is added past build_system_mode_params'
            # typo guard on purpose: the cloud-side builder does not know it,
            # because on the cloud socMax belongs to the separate socLimit
            # endpoint that Bluetooth does not have.
            params = build_system_mode_params(config, socMin=str(soc_min))
            params["socMax"] = str(soc_max)
            await self._send(
                ble_protocol.cmd_set_system_mode(self._device_id, params))
