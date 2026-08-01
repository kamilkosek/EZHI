"""Sensor platform for APsystems EZHI local API integration."""
from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.sensor import (
    PLATFORM_SCHEMA,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import CONF_IP_ADDRESS, CONF_NAME, UnitOfEnergy, UnitOfPower, PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import DiscoveryInfoType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ApSystemsDataCoordinator
from .const import CLOUD_COORDINATOR, DOMAIN
from .cloud import HIGH_POWER_LIMIT, STANDARD_POWER_LIMIT
from .entity import EzhiCloudEntity
from .api import ReturnDeviceInfo

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_IP_ADDRESS): cv.string,
        vol.Optional(CONF_NAME, default="ezhi"): cv.string,
    }
)


# Battery status mapping (per API documentation)
BATTERY_STATUS_MAP = {
    "1": "Idle",
    "2": "Charging",
    "3": "Discharging",
    "4": "Fault",
    "5": "Shutdown",
    "6": "No Communication",
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the sensor platform."""
    config = hass.data[DOMAIN][config_entry.entry_id]
    coordinator = config["COORDINATOR"]

    sensors = [
        # Battery Status Sensor (NEW)
        BatteryStatusSensor(
            coordinator,
            device_name=config[CONF_NAME],
            sensor_name="Battery Status",
            sensor_id="battery_status",
        ),
        
        # PV Sensors
        PhotovoltaicPowerSensor(
            coordinator,
            device_name=config[CONF_NAME],
            sensor_name="Photovoltaic Power",
            sensor_id="photovoltaic_power",
        ),
        PhotovoltaicEnergySensor(
            coordinator,
            device_name=config[CONF_NAME],
            sensor_name="Photovoltaic Energy",
            sensor_id="photovoltaic_energy",
        ),
        
        # Battery Sensors
        BatteryPowerSensor(
            coordinator,
            device_name=config[CONF_NAME],
            sensor_name="Battery Power",
            sensor_id="battery_power",
        ),
        BatteryChargeSensor(
            coordinator,
            device_name=config[CONF_NAME],
            sensor_name="Battery State of Charge",
            sensor_id="battery_soc",
        ),
        BatteryHealthSensor(
            coordinator,
            device_name=config[CONF_NAME],
            sensor_name="Battery State of Health",
            sensor_id="battery_soh",
        ),
        BatteryTemperatureSensor(
            coordinator,
            device_name=config[CONF_NAME],
            sensor_name="Battery Temperature",
            sensor_id="battery_temperature",
        ),
        BatteryChargeEnergySensor(
            coordinator,
            device_name=config[CONF_NAME],
            sensor_name="Battery Total Charge Energy",
            sensor_id="battery_charge_energy",
        ),
        BatteryDischargeEnergySensor(
            coordinator,
            device_name=config[CONF_NAME],
            sensor_name="Battery Total Discharge Energy",
            sensor_id="battery_discharge_energy",
        ),
        BatteryCapacitySensor(
            coordinator,
            device_name=config[CONF_NAME],
            sensor_name="Battery Capacity",
            sensor_id="battery_capacity",
        ),
        
        # On-Grid Sensors
        OnGridPowerSensor(
            coordinator,
            device_name=config[CONF_NAME],
            sensor_name="On-Grid Power",
            sensor_id="ongrid_power",
        ),
        OnGridOutputEnergySensor(
            coordinator,
            device_name=config[CONF_NAME],
            sensor_name="On-Grid Output Energy",
            sensor_id="ongrid_output_energy",
        ),
        OnGridInputEnergySensor(
            coordinator,
            device_name=config[CONF_NAME],
            sensor_name="On-Grid Input Energy",
            sensor_id="ongrid_input_energy",
        ),
        
        # Off-Grid Sensors
        OffGridPowerSensor(
            coordinator,
            device_name=config[CONF_NAME],
            sensor_name="Off-Grid Power",
            sensor_id="offgrid_power",
        ),
        OffGridOutputEnergySensor(
            coordinator,
            device_name=config[CONF_NAME],
            sensor_name="Off-Grid Output Energy",
            sensor_id="offgrid_output_energy",
        ),
        OffGridInputEnergySensor(
            coordinator,
            device_name=config[CONF_NAME],
            sensor_name="Off-Grid Input Energy",
            sensor_id="offgrid_input_energy",
        ),
        
        # Device Sensors
        DeviceTemperatureSensor(
            coordinator,
            device_name=config[CONF_NAME],
            sensor_name="Device Temperature",
            sensor_id="device_temperature",
        ),
    ]

    add_entities(sensors)

    cloud_coordinator = config.get(CLOUD_COORDINATOR)
    if cloud_coordinator is not None:
        add_entities([EzhiCloudPowerLimitSensor(cloud_coordinator, config[CONF_NAME])])


class EzhiCloudPowerLimitSensor(EzhiCloudEntity, SensorEntity):
    """The output power ceiling -- read-only on purpose.

    This is the app's "high power mode": 800 W standard, 1200 W high. It is a
    sensor and not a number or a switch because raising it carries the vendor's
    disclaimer about exceeding regulatory feed-in limits, and Home Assistant
    cannot put a confirmation in front of an entity. Changing it goes through
    the apsystems_ezhi_local.set_high_power_mode service, which requires an
    explicit acknowledgement.

    Not to be confused with the local "On-Grid Power" number, which is the
    momentary setpoint (-1200..1200 W), not a ceiling.
    """

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = "mdi:speedometer"

    def __init__(self, coordinator, device_name: str):
        super().__init__(coordinator, device_name, "power_limit_state", "Power Limit")

    @property
    def native_value(self) -> int | None:
        raw = (self.coordinator.data or {}).get("powerLimit")
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        value = self.native_value
        return {
            "high_power_mode": {
                HIGH_POWER_LIMIT: "on",
                STANDARD_POWER_LIMIT: "off",
            }.get(value, "unknown"),
            "change_with": (
                "action: apsystems_ezhi_local.set_high_power_mode -- read-only "
                "here because enabling 1200 W may exceed the regulatory limit "
                "for your grid connection and needs an explicit acknowledgement."
            ),
        }


class BaseSensor(CoordinatorEntity, SensorEntity):
    """Representation of an APsystem sensor."""

    # See EzhiCloudEntity: the device name comes from device_info, so the
    # entity carries only its own half of the name.
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ApSystemsDataCoordinator,
        device_name: str,
        sensor_name: str,
        sensor_id: str,
    ):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._state = None
        self._device_name = device_name
        self._attr_name = sensor_name
        self._sensor_id = sensor_id

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def unique_id(self) -> str | None:
        """Return a unique ID for the sensor."""
        return f"apsystems_{self._device_name}_{self._sensor_id}"

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


# NEW: Battery Status Sensor
class BatteryStatusSensor(BaseSensor):
    """Representation of a battery status sensor."""
    
    @callback
    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        if self.coordinator.data is not None:
            # Convert to string to handle both int and string values from API
            status_code = str(self.coordinator.data.batS)
            self._state = BATTERY_STATUS_MAP.get(status_code, f"Unknown ({status_code})")
        self.async_write_ha_state()


# PV Sensors
class PhotovoltaicPowerSensor(BaseSensor):
    """Representation of a photovoltaic power sensor."""
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    
    @callback
    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        if self.coordinator.data is not None:
            try:
                self._state = float(self.coordinator.data.pvP)
            except (ValueError, TypeError):
                self._state = 0
        self.async_write_ha_state()


class PhotovoltaicEnergySensor(BaseSensor):
    """Representation of a photovoltaic energy sensor."""
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    
    @callback
    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        if self.coordinator.data is not None:
            self._state = float(self.coordinator.data.pvTE)
        self.async_write_ha_state()


# Battery Sensors
class BatteryPowerSensor(BaseSensor):
    """Representation of a battery power sensor."""
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    
    @callback
    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        if self.coordinator.data is not None:
            try:
                self._state = float(self.coordinator.data.batP)
            except (ValueError, TypeError):
                self._state = 0
        self.async_write_ha_state()


class BatteryChargeSensor(BaseSensor):
    """Representation of a battery state of charge sensor."""
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    
    @callback
    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        if self.coordinator.data is not None:
            try:
                self._state = int(float(self.coordinator.data.batSoc))
            except (ValueError, TypeError):
                self._state = 0
        self.async_write_ha_state()


class BatteryHealthSensor(BaseSensor):
    """Representation of a battery state of health sensor."""
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    
    @callback
    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        if self.coordinator.data is not None:
            try:
                self._state = float(self.coordinator.data.batSoh)
            except (ValueError, TypeError):
                self._state = 0
        self.async_write_ha_state()


class BatteryTemperatureSensor(BaseSensor):
    """Representation of a battery temperature sensor."""
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    
    @callback
    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        if self.coordinator.data is not None:
            try:
                self._state = float(self.coordinator.data.batTemp)
            except (ValueError, TypeError):
                self._state = 0
        self.async_write_ha_state()


class BatteryChargeEnergySensor(BaseSensor):
    """Representation of a battery total charge energy sensor."""
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    
    @callback
    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        if self.coordinator.data is not None:
            self._state = float(self.coordinator.data.batCTE)
        self.async_write_ha_state()


class BatteryDischargeEnergySensor(BaseSensor):
    """Representation of a battery total discharge energy sensor."""
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    
    @callback
    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        if self.coordinator.data is not None:
            self._state = float(self.coordinator.data.batDTE)
        self.async_write_ha_state()


class BatteryCapacitySensor(BaseSensor):
    """Representation of the battery capacity in kWh."""
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.MEASUREMENT
    
    @callback
    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        if self.coordinator.device_info is not None:
            try:
                self._state = float(self.coordinator.device_info.batteryCapacity)
            except (ValueError, TypeError):
                self._state = 0
        self.async_write_ha_state()


# On-Grid Sensors
class OnGridPowerSensor(BaseSensor):
    """Representation of an on-grid power sensor."""
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    
    @callback
    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        if self.coordinator.data is not None:
            try:
                self._state = float(self.coordinator.data.ogP)
            except (ValueError, TypeError):
                self._state = 0
        self.async_write_ha_state()


class OnGridOutputEnergySensor(BaseSensor):
    """Representation of an on-grid output energy sensor."""
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    
    @callback
    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        if self.coordinator.data is not None:
            self._state = float(self.coordinator.data.ogOTE)
        self.async_write_ha_state()


class OnGridInputEnergySensor(BaseSensor):
    """Representation of an on-grid input energy sensor."""
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    
    @callback
    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        if self.coordinator.data is not None:
            self._state = float(self.coordinator.data.ogITE)
        self.async_write_ha_state()


# Off-Grid Sensors
class OffGridPowerSensor(BaseSensor):
    """Representation of an off-grid power sensor."""
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    
    @callback
    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        if self.coordinator.data is not None:
            try:
                self._state = float(self.coordinator.data.ofgP)
            except (ValueError, TypeError):
                self._state = 0
        self.async_write_ha_state()


class OffGridOutputEnergySensor(BaseSensor):
    """Representation of an off-grid output energy sensor."""
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    
    @callback
    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        if self.coordinator.data is not None:
            self._state = float(self.coordinator.data.ofgOTE)
        self.async_write_ha_state()


class OffGridInputEnergySensor(BaseSensor):
    """Representation of an off-grid input energy sensor."""
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    
    @callback
    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        if self.coordinator.data is not None:
            self._state = float(self.coordinator.data.ofgITE)
        self.async_write_ha_state()


class DeviceTemperatureSensor(BaseSensor):
    """Representation of a device temperature sensor."""
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    
    @callback
    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        if self.coordinator.data is not None:
            try:
                self._state = float(self.coordinator.data.devTemp)
            except (ValueError, TypeError):
                self._state = 0
        self.async_write_ha_state()
