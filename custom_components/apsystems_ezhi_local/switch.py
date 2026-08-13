"""Switch platform for the APsystems EZHI integration.

Every switch here is cloud-backed -- none of on/off, backup power (EPS) or
ECO exists in the local API. That is the whole reason the cloud layer was
built.
"""
from __future__ import annotations

import asyncio
from typing import Any

from homeassistant import config_entries
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .cloud import EzhiCloudError, control_config, is_running, wire_str
from .const import (
    CLOUD_COORDINATOR,
    DOMAIN,
    SYSTEM_MODE_LOCAL,
    SYSTEM_MODE_NAMES,
)
from .entity import CLOUD_WRITE_TIMEOUT_S, EzhiCloudEntity


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    add_entities: AddEntitiesCallback,
) -> None:
    """Set up the switch platform."""
    config = hass.data[DOMAIN][config_entry.entry_id]
    cloud_coordinator = config.get(CLOUD_COORDINATOR)
    if cloud_coordinator is None:
        # No cloud credentials configured — local-only setup, nothing to add.
        return

    add_entities([
        EzhiCloudOnOffSwitch(cloud_coordinator, config[CONF_NAME]),
        EzhiCloudBackupPowerSwitch(cloud_coordinator, config[CONF_NAME]),
        EzhiCloudEcoSwitch(cloud_coordinator, config[CONF_NAME]),
        EzhiCloudThirdLinkSwitch(cloud_coordinator, config[CONF_NAME]),
    ])


class EzhiCloudOnOffSwitch(EzhiCloudEntity, SwitchEntity):
    """Turns the inverter on and off through the EMA cloud.

    Two things about this switch are not obvious:

    1. The wire format is inverted — the cloud field ``onOff`` reads "0" while
       the inverter is running.
    2. Switching it off is a one-way trip from Home Assistant. Once the inverter
       is down it drops off MQTT and the cloud can no longer reach it, so turning
       it back on needs PV/DC input or a 3 s press on the battery button.
    """

    _attr_icon = "mdi:power"
    # Not literally true -- we do poll real state -- but taken deliberately
    # for two practical reasons, not semantic purity:
    #   1. Renders as two separate buttons instead of one toggle. Turning
    #      this inverter off cannot be undone from HA, so it should take a
    #      deliberate press, not an accidental brush of a toggle.
    #   2. Removes a snap-back hazard. The cloud coordinator has
    #      always_update=False, so an unchanged post-write GET fires no
    #      listener and this entity gets no state write after the service
    #      call. A toggle's optimistic flip then has nothing confirming it,
    #      reverts, reads as "it didn't work" -- and risks a second write to
    #      a hybrid inverter. Do not "fix" this back to False.
    _attr_assumed_state = True

    def __init__(self, coordinator, device_name: str):
        super().__init__(coordinator, device_name, "on_off", "Inverter On")

    @property
    def is_on(self) -> bool | None:
        # is_running lives in cloud.py, beside async_set_on_off, so the one
        # piece of inverted-wire knowledge has a single home -- and one this
        # entity file cannot itself have a test for (no HA test harness here).
        return is_running(control_config(self.coordinator.data).get("onOff"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "remote_turn_on_limitation": (
                "Only works while the inverter is still online. Once off, wake it "
                "with PV/DC input or a 3 s press on the battery button."
            )
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)

    async def _async_set(self, on: bool) -> None:
        try:
            async with asyncio.timeout(CLOUD_WRITE_TIMEOUT_S):
                await self.coordinator.api.async_set_on_off(on)
        except TimeoutError as err:
            raise HomeAssistantError(
                f"the inverter did not answer within {CLOUD_WRITE_TIMEOUT_S} s "
                "-- the on/off command may or may not have been applied"
            ) from err
        except EzhiCloudError as err:
            raise HomeAssistantError(str(err)) from err
        # Re-read rather than trusting the write: confirm against the device.
        await self.coordinator.async_request_refresh()


class _EzhiCloudSystemModeSwitch(EzhiCloudEntity, SwitchEntity):
    """A boolean field inside the systemMode config blob.

    Not assumed_state, unlike the on/off switch above: these are reversible
    from Home Assistant, so a plain toggle is right and there is no reason to
    make them two deliberate buttons.
    """

    _key: str

    @property
    def is_on(self) -> bool | None:
        raw = control_config(self.coordinator.data).get(self._key)
        if raw is None:
            return None
        # Same normalisation the write path uses, so "1"/1/1.0/True all agree.
        return wire_str(raw) == "1"

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_write(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_write(False)

    async def _async_write(self, on: bool) -> None:
        raise NotImplementedError

    async def _async_guarded(self, coro_factory, what: str) -> None:
        try:
            async with asyncio.timeout(CLOUD_WRITE_TIMEOUT_S):
                # The client re-reads the live config before posting, so this
                # is a GET plus a POST -- roughly double a single-call write.
                await coro_factory()
        except TimeoutError as err:
            raise HomeAssistantError(
                f"the inverter did not answer within {CLOUD_WRITE_TIMEOUT_S} s "
                f"-- the {what} change may or may not have been applied"
            ) from err
        except EzhiCloudError as err:
            raise HomeAssistantError(str(err)) from err
        await self.coordinator.async_request_refresh()


class EzhiCloudBackupPowerSwitch(_EzhiCloudSystemModeSwitch):
    """EPS -- backup / emergency power on the off-grid side.

    This is the control the whole cloud layer was built for: it is not in the
    local API at all.

    Turning it on also clears ECO, because the firmware treats the two as
    mutually exclusive. That pairing lives in cloud.async_set_backup_power so
    it has one home and a test; this file has no HA test harness.

    The vendor app hides this switch in Local mode, but the write works there
    anyway -- measured 2026-08-01 from Home Assistant, EPS 1 -> 0 -> 1 while
    the device stayed in mode 4, no other field touched. A UI decision in the
    app, not an API restriction.
    """

    _attr_icon = "mdi:home-battery"
    _key = "EPS"

    def __init__(self, coordinator, device_name: str):
        super().__init__(coordinator, device_name, "eps", "Backup Power")

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        return {
            "mutually_exclusive_with": "ECO -- enabling backup power disables ECO",
            "vendor_app_visibility": (
                "The vendor app hides this switch in Local mode. Writing it from "
                "here works there regardless -- verified 2026-08-01."
            ),
        }

    async def _async_write(self, on: bool) -> None:
        await self._async_guarded(
            lambda: self.coordinator.api.async_set_backup_power(on), "backup power"
        )


class EzhiCloudEcoSwitch(_EzhiCloudSystemModeSwitch):
    """ECO -- shuts the off-grid side down after an hour with no load.

    Measured, so nobody re-derives it: ECO does NOT reduce standby draw. An
    A/B test found the same ~17 W either way. It only powers down the off-grid
    output when nothing is drawing from it.
    """

    _attr_icon = "mdi:leaf"
    _key = "ECO"

    def __init__(self, coordinator, device_name: str):
        super().__init__(coordinator, device_name, "eco", "ECO Mode")

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        return {
            "mutually_exclusive_with": "EPS -- enabling ECO disables backup power",
            "does_not_reduce_standby": (
                "Measured 2026-07-31: battery draw was ~17 W with and without ECO."
            ),
        }

    async def _async_write(self, on: bool) -> None:
        await self._async_guarded(
            lambda: self.coordinator.api.async_set_eco(on), "ECO mode"
        )


class EzhiCloudThirdLinkSwitch(_EzhiCloudSystemModeSwitch):
    """thirdLink -- the vendor app's "smart linking" master switch.

    It is what a smart meter (Shelly, EcoTracker) hangs off: with it on, the
    app offers zero-export, relay control and phase detection. The reason to
    have it in Home Assistant is that the app couples the two -- turn linking
    on there and it will only let you do zero export, never surplus feed-in
    with demand-driven discharge. Toggling the master from here leaves that
    choice open.

    Field values, from two devices (the second one is what made this
    readable):

    * ``"0"`` -- off.
    * ``"1"`` -- on, with a device actually coupled. Measured on a user's
      inverter that has a meter bound (``bindList`` non-empty,
      ``meterDeviceNum: 1``).
    * ``"2"`` -- on, with nothing coupled. Measured on a device where linking
      was enabled but no meter exists to pair.

    So the state is not a boolean and `is_on` must not compare against "1":
    a device reading "2" is on. Writing "1" is what turns it on; the firmware
    is the one that decides whether that settles at 1 or 2.

    Untested against real coupled hardware -- neither of the two devices above
    could be driven from here. The values are verified, the write path is the
    same one every other systemMode field uses, but a smart-meter owner is the
    first person to see this work end to end.
    """

    _attr_icon = "mdi:link-variant"
    _key = "thirdLink"

    # Turning linking on and staying in Local mode is not a combination the
    # device offers: measured 2026-08-07, the device moves to mode 1. Local is
    # also the only mode where a local setPower setpoint is obeyed, so a
    # silent mode change here would quietly disable that.
    _REFUSED_IN = SYSTEM_MODE_LOCAL

    def __init__(self, coordinator, device_name: str):
        super().__init__(coordinator, device_name, "third_link", "Smart Linking")

    @property
    def is_on(self) -> bool | None:
        raw = control_config(self.coordinator.data).get(self._key)
        if raw is None:
            return None
        # Not `== "1"`: "2" is on as well, it just means nothing is coupled.
        return wire_str(raw) != "0"

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        raw = control_config(self.coordinator.data).get(self._key)
        attrs = {
            "raw_value": wire_str(raw) if raw is not None else "unknown",
            "value_meaning": (
                "0 = off, 1 = on with a device coupled, 2 = on with nothing "
                "coupled"
            ),
            "forces_system_mode": (
                "Turning this on moves the inverter to Balcony mode -- it "
                "cannot be combined with Local mode, where the local setPower "
                "setpoint is obeyed"
            ),
        }
        return attrs

    async def _async_write(self, on: bool) -> None:
        mode = wire_str(control_config(self.coordinator.data).get("systemMode"))
        if on and mode == self._REFUSED_IN:
            raise HomeAssistantError(
                "smart linking cannot be turned on while the inverter is in "
                f"{SYSTEM_MODE_NAMES.get(self._REFUSED_IN, 'Local')} mode: the "
                "device would switch itself to Balcony mode, and the local "
                "power setpoint only takes effect in Local. Change the system "
                "mode first if that is what you want."
            )
        await self._async_guarded(
            lambda: self.coordinator.api.async_set_system_mode(
                thirdLink="1" if on else "0"
            ),
            "smart linking",
        )
