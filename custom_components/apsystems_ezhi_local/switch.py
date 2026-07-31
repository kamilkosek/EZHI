"""Switch platform for the APsystems EZHI integration.

The only switch is cloud-backed: on/off does not exist in the local API.
"""
from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .cloud import EzhiCloudError, is_running
from .const import CLOUD_COORDINATOR, DOMAIN


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

    add_entities([EzhiCloudOnOffSwitch(cloud_coordinator, config[CONF_NAME])])


class EzhiCloudOnOffSwitch(CoordinatorEntity, SwitchEntity):
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
        super().__init__(coordinator)
        self._device_name = device_name
        self._attr_name = f"APsystems {device_name} Inverter On"
        self._attr_unique_id = f"apsystems_{device_name}_cloud_on_off"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_name)},
            name=self._device_name,
            manufacturer="APsystems",
            model="EZHI",
        )

    @property
    def is_on(self) -> bool | None:
        # is_running lives in cloud.py, beside async_set_on_off, so the one
        # piece of inverted-wire knowledge has a single home -- and one this
        # entity file cannot itself have a test for (no HA test harness here).
        return is_running((self.coordinator.data or {}).get("onOff"))

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
            await self.coordinator.api.async_set_on_off(on)
        except EzhiCloudError as err:
            raise HomeAssistantError(str(err)) from err
        # Re-read rather than trusting the write: confirm against the device.
        await self.coordinator.async_request_refresh()
