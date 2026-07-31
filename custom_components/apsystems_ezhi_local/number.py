"""Number platform for APsystems EZHI local API integration."""
from __future__ import annotations

import asyncio

from aiohttp import client_exceptions
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.number import (
    PLATFORM_SCHEMA,
    NumberDeviceClass,
    NumberEntity,
    NumberMode,
)
from homeassistant.const import CONF_IP_ADDRESS, CONF_NAME, PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import DiscoveryInfoType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CLOUD_COORDINATOR, DOMAIN, MAX_VALUE, MIN_VALUE
from .api import APsystemsEZHI
from .cloud import EzhiCloudError

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_IP_ADDRESS): cv.string,
    vol.Optional(CONF_NAME, default="ezhi"): cv.string
})


async def async_setup_entry(
        hass: HomeAssistant,
        config_entry: config_entries.ConfigEntry,
        add_entities: AddEntitiesCallback,
        discovery_info: DiscoveryInfoType | None = None
) -> None:
    """Set up the number platform."""
    config = hass.data[DOMAIN][config_entry.entry_id]
    api = APsystemsEZHI(ip_address=config[CONF_IP_ADDRESS])

    # update_before_add=True: PowerLimit is a plain, should_poll=True
    # NumberEntity and would otherwise sit at `unknown` until its first poll.
    add_entities([
        PowerLimit(api, device_name=config[CONF_NAME], sensor_name="On-Grid Power", sensor_id="max_output_power"),
    ], True)

    cloud_coordinator = config.get(CLOUD_COORDINATOR)
    if cloud_coordinator is not None:
        # No update_before_add here: these already have the coordinator's
        # data. update_before_add=True is not fire-and-forget -- entity_
        # platform awaits it, so it would put an undeadlined cloud GET
        # (cloud.py's no-deadline exemption is scoped to DataUpdateCoordinator
        # as the caller) on the setup path, on top of the refresh __init__.py
        # already did and deliberately capped at 20 s.
        add_entities([
            EzhiCloudSocNumber(cloud_coordinator, config[CONF_NAME], "socMin", "SOC Minimum"),
            EzhiCloudSocNumber(cloud_coordinator, config[CONF_NAME], "socMax", "SOC Maximum"),
        ])


class PowerLimit(NumberEntity):
    """Representation of a power limit control."""
    _attr_device_class = NumberDeviceClass.POWER
    _attr_available = False
    _attr_native_min_value = MIN_VALUE
    _attr_native_max_value = MAX_VALUE
    _attr_native_step = 10

    def __init__(self, api: APsystemsEZHI, device_name: str, sensor_name: str, sensor_id: str):
        """Initialize the sensor."""
        self._api = api
        self._state = None
        self._device_name = device_name
        self._name = sensor_name
        self._sensor_id = sensor_id

    async def async_update(self):
        """Update the entity."""
        try:
            self._state = await self._api.get_power()
            self._attr_available = True
        except (TimeoutError, client_exceptions.ClientConnectionError):
            self._attr_available = False

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def unique_id(self) -> str | None:
        """Return the unique ID of the sensor."""
        return f"apsystems_{self._device_name}_{self._sensor_id}"

    @property
    def name(self):
        """Return the name of the sensor."""
        return f"APsystems {self._device_name} {self._name}"

    async def async_set_native_value(self, value: float) -> None:
        """Set the value of the power limit."""
        try:
            await self._api.set_power(int(value))
            self._attr_available = True
        except (TimeoutError, client_exceptions.ClientConnectionError):
            self._attr_available = False
        await self.async_update()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={
                (DOMAIN, self._device_name)
            },
            name=self._device_name,
            manufacturer="APsystems",
            model="EZHI",
        )


_KEY_TO_KWARG = {"socMin": "soc_min", "socMax": "soc_max"}


class EzhiCloudSocNumber(CoordinatorEntity, NumberEntity):
    """One of the two SOC bounds, written through the EMA cloud.

    The socLimit endpoint takes both bounds at once. Rather than pairing them
    up here from `coordinator.data` (which can be up to a poll interval old),
    only this entity's own bound is sent -- async_set_soc_limit re-reads the
    other one fresh. That keeps the untestable pairing logic out of this file
    (no HA harness here) and in cloud.py, where it is covered by
    tests/test_cloud.py.
    """

    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = NumberDeviceClass.BATTERY
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, device_name: str, key: str, label: str):
        super().__init__(coordinator)
        self._device_name = device_name
        self._key = key  # "socMin" or "socMax"
        self._attr_name = f"APsystems {device_name} {label}"
        self._attr_unique_id = f"apsystems_{device_name}_cloud_{key.lower()}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_name)},
            name=self._device_name,
            manufacturer="APsystems",
            model="EZHI",
        )

    @property
    def native_value(self) -> float | None:
        raw = (self.coordinator.data or {}).get(self._key)
        return None if raw is None else float(raw)

    async def async_set_native_value(self, value: float) -> None:
        try:
            await self.coordinator.api.async_set_soc_limit(
                **{_KEY_TO_KWARG[self._key]: int(value)}
            )
        except EzhiCloudError as err:
            raise HomeAssistantError(str(err)) from err
        await self.coordinator.async_request_refresh()
