"""Switch platform for APsystems EZHI local API integration."""
from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.components.switch import SwitchEntity, PLATFORM_SCHEMA
from homeassistant.const import CONF_IP_ADDRESS, CONF_NAME
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import DiscoveryInfoType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

import voluptuous as vol

from .const import DOMAIN
from . import ApSystemsDataCoordinator


PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_IP_ADDRESS): cv.string,
    vol.Optional(CONF_NAME, default="ezhi"): cv.string,
})


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None
) -> None:
    """Set up the switch platform."""
    config = hass.data[DOMAIN][config_entry.entry_id]
    coordinator = config["COORDINATOR"]
    
    # Currently, there are no specific switches in the API documentation
    # This is a placeholder for future functionality
    # If you discover additional API endpoints for switching features, add them here
    
    # Example of how to add a switch if you have one:
    # add_entities([
    #    EZHIModeSwitchEntity(
    #        coordinator,
    #        device_name=config[CONF_NAME],
    #        switch_name="Local Mode",
    #        switch_id="local_mode",
    #    )
    # ])
    
    # Since we don't have any actual switches to add yet, we'll just return
    return


class BaseEZHISwitchEntity(CoordinatorEntity, SwitchEntity):
    """Base switch entity for APsystems EZHI."""
    
    def __init__(
        self,
        coordinator: ApSystemsDataCoordinator,
        device_name: str,
        switch_name: str,
        switch_id: str,
    ):
        """Initialize the switch."""
        super().__init__(coordinator)
        self._device_name = device_name
        self._switch_name = switch_name
        self._switch_id = switch_id
        self._is_on = False
    
    @property
    def name(self):
        """Return the name of the switch."""
        return f"{self._device_name} {self._switch_name}"
    
    @property
    def is_on(self) -> bool:
        """Return True if entity is on."""
        return self._is_on
    
    @property
    def unique_id(self) -> str:
        """Return the unique ID of this switch."""
        return f"apsystems_{self._device_name}_{self._switch_id}"
    
    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_name)},
            name=self._device_name,
            manufacturer="APsystems",
            model="EZHI",
        )

# Example switch implementation for future use
# class EZHIModeSwitchEntity(BaseEZHISwitchEntity):
#     """Switch entity for controlling a specific mode."""
#
#     async def async_turn_on(self, **kwargs: Any) -> None:
#         """Turn the entity on."""
#         try:
#             # Call the API to turn on the feature
#             # await self.coordinator.api.turn_on_feature()
#             self._is_on = True
#         except Exception as e:
#             self.coordinator.logger.error("Could not turn on feature: %s", e)
#
#     async def async_turn_off(self, **kwargs: Any) -> None:
#         """Turn the entity off."""
#         try:
#             # Call the API to turn off the feature
#             # await self.coordinator.api.turn_off_feature()
#             self._is_on = False
#         except Exception as e:
#             self.coordinator.logger.error("Could not turn off feature: %s", e)
