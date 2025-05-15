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
)
from homeassistant.const import CONF_IP_ADDRESS, CONF_NAME
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import DiscoveryInfoType

from .const import DOMAIN, MAX_VALUE, MIN_VALUE
from .api import APsystemsEZHI

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

    numbers = [
        PowerLimit(api, device_name=config[CONF_NAME], sensor_name="On-Grid Power", sensor_id="max_output_power")
    ]

    add_entities(numbers, True)


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
