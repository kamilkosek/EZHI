"""Binary sensor platform for APsystems EZHI local API integration."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from homeassistant import config_entries
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ApSystemsDataCoordinator
from .api import ReturnAlarmData
from .const import DOMAIN


@dataclass(frozen=True, kw_only=True)
class EZHIBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes EZHI binary sensor entity."""
    
    value_fn: Callable[[ReturnAlarmData], bool]


ALARM_SENSORS: tuple[EZHIBinarySensorEntityDescription, ...] = (
    EZHIBinarySensorEntityDescription(
        key="battery_overtemp",
        name="Battery Overtemperature",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda data: str(data.BatHTP) == "1",
    ),
    EZHIBinarySensorEntityDescription(
        key="battery_undertemp",
        name="Battery Undertemperature",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda data: str(data.BatLTP) == "1",
    ),
    EZHIBinarySensorEntityDescription(
        key="battery_comm_error",
        name="Battery Communication Error",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda data: str(data.BatCE) == "1",
    ),
    EZHIBinarySensorEntityDescription(
        key="battery_overvoltage",
        name="Battery Overvoltage",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda data: str(data.BatHV) == "1",
    ),
    EZHIBinarySensorEntityDescription(
        key="battery_undervoltage",
        name="Battery Undervoltage",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda data: str(data.BatLV) == "1",
    ),
    EZHIBinarySensorEntityDescription(
        key="battery_overcurrent",
        name="Battery Overcurrent",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda data: str(data.BatHI) == "1",
    ),
    EZHIBinarySensorEntityDescription(
        key="battery_error",
        name="Battery Error",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda data: str(data.BatE) == "1",
    ),
    EZHIBinarySensorEntityDescription(
        key="battery_shutdown",
        name="Battery Shutdown",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda data: str(data.SBS) == "1",
    ),
    EZHIBinarySensorEntityDescription(
        key="device_overtemp",
        name="Device Overtemperature",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda data: str(data.DTP) == "1",
    ),
    EZHIBinarySensorEntityDescription(
        key="device_error",
        name="Device Error",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda data: str(data.EE) == "1",
    ),
    EZHIBinarySensorEntityDescription(
        key="ac_abnormal",
        name="AC Abnormal",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda data: str(data.ACA) == "1",
    ),
    EZHIBinarySensorEntityDescription(
        key="offgrid_overcurrent",
        name="Off-Grid Overcurrent",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda data: str(data.OfOI) == "1",
    ),
    EZHIBinarySensorEntityDescription(
        key="offgrid_short",
        name="Off-Grid Short Circuit",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda data: str(data.OfGS) == "1",
    ),
    EZHIBinarySensorEntityDescription(
        key="pv_overvoltage",
        name="PV Overvoltage",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda data: str(data.PvHV) == "1",
    ),
    EZHIBinarySensorEntityDescription(
        key="pv_overcurrent",
        name="PV Overcurrent",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda data: str(data.PvOC) == "1",
    ),
    EZHIBinarySensorEntityDescription(
        key="pv_wiring_error",
        name="PV Wiring Error",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda data: str(data.PVWE) == "1",
    ),
    EZHIBinarySensorEntityDescription(
        key="ird_error",
        name="IRD Error",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda data: str(data.IRDE) == "1",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensor platform."""
    config = hass.data[DOMAIN][config_entry.entry_id]
    coordinator = config["COORDINATOR"]

    add_entities(
        EZHIAlarmBinarySensor(
            coordinator=coordinator,
            description=description,
            device_name=config[CONF_NAME],
        )
        for description in ALARM_SENSORS
    )


class EZHIAlarmBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Representation of an EZHI alarm binary sensor."""

    entity_description: EZHIBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: ApSystemsDataCoordinator,
        description: EZHIBinarySensorEntityDescription,
        device_name: str,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._device_name = device_name
        self._attr_unique_id = f"apsystems_{device_name}_{description.key}"
        self._attr_name = f"{device_name} {description.name}"

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        if self.coordinator.alarm_data is None:
            return None
        try:
            return self.entity_description.value_fn(self.coordinator.alarm_data)
        except (AttributeError, TypeError):
            return None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        info = DeviceInfo(
            identifiers={(DOMAIN, self._device_name)},
            name=self._device_name,
            manufacturer="APsystems",
            model="EZHI",
        )
        
        # Add dynamic info from coordinator if available
        if self.coordinator.device_info is not None:
            dev = self.coordinator.device_info
            if dev.devVer:
                info["sw_version"] = dev.devVer
            if dev.deviceId:
                info["serial_number"] = dev.deviceId
            if dev.ip:
                info["configuration_url"] = f"http://{dev.ip}/getDeviceInfo"
        
        return info
