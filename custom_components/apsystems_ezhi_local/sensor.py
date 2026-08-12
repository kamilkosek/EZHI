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
from homeassistant.const import CONF_IP_ADDRESS, CONF_NAME, EntityCategory, UnitOfEnergy, UnitOfPower, PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import DiscoveryInfoType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ApSystemsDataCoordinator
from .ble_api import (
    OUTPUT_SENSOR_FIELDS,
    OutputField,
    ble_output_available,
    output_value,
)
from .const import (
    BLE_LINK,
    CLOUD_COORDINATOR,
    DOMAIN,
    TRANSPORT_BLUETOOTH,
    TRANSPORT_CLOUD,
    resolve_transport,
)
from .cloud import HIGH_POWER_LIMIT, STANDARD_POWER_LIMIT, control_config, control_output
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
        cloud_entities: list[SensorEntity] = [
            EzhiCloudPowerLimitSensor(cloud_coordinator, config[CONF_NAME]),
            EzhiControlTransportSensor(
                cloud_coordinator, config[CONF_NAME],
                resolve_transport(config), config.get(BLE_LINK),
            ),
        ]
        # The outputData fields exist only in the BLE reply; on the cloud
        # transport these sensors would be permanently unavailable, so they
        # are not created there at all. Their availability still re-checks
        # the polled data -- creation gating and value gating are two
        # different guards, and only the second one sees a failed read.
        if resolve_transport(config) == TRANSPORT_BLUETOOTH:
            cloud_entities.extend(
                EzhiBleOutputSensor(cloud_coordinator, config[CONF_NAME], field)
                for field in OUTPUT_SENSOR_FIELDS
            )
        add_entities(cloud_entities)


class EzhiBleOutputSensor(EzhiCloudEntity, SensorEntity):
    """One BLE-only outputData value -- DC battery, per-string PV, extra
    temperatures, grid quality. The local HTTP API does not carry these
    fields (measured 2026-08-08), which is exactly why the entity rides the
    control coordinator's BLE poll and not the local one.

    Unavailable rather than stale or guessed whenever the last poll carried
    no output: on the cloud transport (always), and after a failed BLE extra
    read (until the next successful poll).
    """

    def __init__(
        self,
        coordinator,
        device_name: str,
        field: OutputField,
    ) -> None:
        super().__init__(coordinator, device_name, field.uid, field.name)
        self._field = field
        # The spec table is HA-free on purpose (tests run without
        # homeassistant); its strings are the enum values, looked up here
        # rather than assigned raw so a typo fails at setup, not silently.
        self._attr_native_unit_of_measurement = field.unit
        self._attr_device_class = SensorDeviceClass(field.device_class)
        self._attr_state_class = SensorStateClass(field.state_class)

    @property
    def available(self) -> bool:
        return super().available and ble_output_available(self.coordinator.data)

    @property
    def native_value(self) -> float | None:
        return output_value(
            control_output(self.coordinator.data), self._field.key)


class EzhiControlTransportSensor(EzhiCloudEntity, SensorEntity):
    """Which wire the control commands take, and what the device last reported.

    Two jobs, because they answer the same question ("is my control path
    working?"): the state names the transport, and the attributes carry the
    raw config fields that have no entity of their own. Those fields are the
    only way to tell from Home Assistant which app toggle maps to which wire
    field -- flip one in the vendor app, watch which attribute moves.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:transit-connection-variant"

    # Everything from a systemMode GET that no other entity surfaces. Values
    # travel as-is; interpreting them is the point of looking at them.
    RAW_FIELDS = (
        "thirdLink", "thirdDevice", "bindDevice", "meterDeviceNum",
        "acSwitch", "isOPStrategy", "winter", "grid", "singlePhase",
        "noBattery", "stayOn", "isLocal", "area", "governmentLevies",
    )

    def __init__(self, coordinator, device_name: str, transport: str, ble_link) -> None:
        super().__init__(coordinator, device_name, "control_transport", "Control Transport")
        self._transport = transport
        self._ble_link = ble_link

    @property
    def native_value(self) -> str:
        return self._transport

    @property
    def available(self) -> bool:
        # Deliberately not tied to the coordinator: when the control layer is
        # down, which transport is configured is exactly what one wants to see.
        return True

    @property
    def extra_state_attributes(self) -> dict:
        config = control_config(self.coordinator.data)
        attrs: dict = {
            "poll_ok": self.coordinator.last_update_success,
            "cloud_role": (
                "control commands and polling"
                if self._transport == TRANSPORT_CLOUD
                else "only opens the radio window when the 15 min idle timer closed it"
            ),
        }
        if self._ble_link is not None:
            attrs["ble_connected"] = self._ble_link.available
        attrs.update({key: config[key] for key in self.RAW_FIELDS if key in config})
        return attrs


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
        raw = control_config(self.coordinator.data).get("powerLimit")
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
            try:
                self._state = float(self.coordinator.data.pvTE)
            except (ValueError, TypeError):
                self._state = None
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
            try:
                self._state = float(self.coordinator.data.batCTE)
            except (ValueError, TypeError):
                self._state = None
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
            try:
                self._state = float(self.coordinator.data.batDTE)
            except (ValueError, TypeError):
                self._state = None
        self.async_write_ha_state()


class BatteryCapacitySensor(BaseSensor):
    """Representation of the battery capacity in kWh."""
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY_STORAGE
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
            try:
                self._state = float(self.coordinator.data.ogOTE)
            except (ValueError, TypeError):
                self._state = None
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
            try:
                self._state = float(self.coordinator.data.ogITE)
            except (ValueError, TypeError):
                self._state = None
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
            try:
                self._state = float(self.coordinator.data.ofgOTE)
            except (ValueError, TypeError):
                self._state = None
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
            try:
                self._state = float(self.coordinator.data.ofgITE)
            except (ValueError, TypeError):
                self._state = None
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
