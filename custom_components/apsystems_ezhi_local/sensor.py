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
from homeassistant.const import CONF_IP_ADDRESS, CONF_NAME, EntityCategory, SIGNAL_STRENGTH_DECIBELS_MILLIWATT, UnitOfEnergy, UnitOfPower, PERCENTAGE, UnitOfTemperature
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
    ble_device_available,
    ble_output_available,
    output_value,
)
from .const import (
    BLE_LINK,
    CLOUD_COORDINATOR,
    DOMAIN,
    TRANSPORT_BLUETOOTH,
    TRANSPORT_CLOUD,
    TRANSPORT_LOCAL_MQTT,
    resolve_transport,
)
from .cloud import (
    HIGH_POWER_LIMIT,
    STANDARD_POWER_LIMIT,
    control_config,
    control_device,
    control_extras,
    control_output,
)
from .device_fields import (
    EXTRA_SENSOR_FIELDS,
    INFO_SENSOR_FIELDS,
    ExtraField,
    InfoField,
    extra_value,
    info_value,
)
from .entity import EzhiCloudEntity
from .api import ReturnDeviceInfo

# What the vendor cloud is still doing on each transport -- an attribute on the
# transport sensor, so a user debugging "why did that write not land" can see
# whether a third-party server is involved at all.
_CLOUD_ROLE = {
    TRANSPORT_CLOUD: "control commands and polling",
    TRANSPORT_BLUETOOTH:
        "only opens the radio window when the 15 min idle timer closed it",
    TRANSPORT_LOCAL_MQTT: "not used",
}

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
        # The outputData fields are not in the local HTTP reply, so these ride
        # the control coordinator. Both control transports can read them:
        # Bluetooth since 2026-08-08, MQTT since 2026-08-11 (`get` with
        # identifier outputData, answered with 50 fields -- this gate said
        # TRANSPORT_BLUETOOTH alone until that capture). The cloud transport
        # has no such read, so there they are not created at all rather than
        # being permanently unavailable. Their availability still re-checks the
        # polled data -- creation gating and value gating are two different
        # guards, and only the second one sees a failed read.
        transport = resolve_transport(config)
        if transport in (TRANSPORT_BLUETOOTH, TRANSPORT_LOCAL_MQTT):
            cloud_entities.extend(
                EzhiBleOutputSensor(cloud_coordinator, config[CONF_NAME], field)
                for field in OUTPUT_SENSOR_FIELDS
            )
        # deviceInfo is answered on request over MQTT as well (verified
        # 2026-08-10), so the signal sensor rides along on both too.
        if transport in (TRANSPORT_BLUETOOTH, TRANSPORT_LOCAL_MQTT):
            cloud_entities.append(
                EzhiWifiSignalSensor(cloud_coordinator, config[CONF_NAME]))
            # ...and so does the rest of that reply. deviceInfo is already read
            # every poll for the signal sensor above; twenty-four of its fields
            # were parsed and thrown away until 2026-08-11. These entities cost
            # no extra round trip at all. Not created on the cloud transport,
            # where `device` is always {} -- they would be permanently
            # unavailable rather than merely empty.
            cloud_entities.extend(
                EzhiInfoSensor(cloud_coordinator, config[CONF_NAME], field)
                for field in INFO_SENSOR_FIELDS
            )
        # The six extra reads are MQTT-only -- see mqtt_api.async_poll_all: on
        # a serial Bluetooth link they would be six more round trips per poll,
        # so they are not created there rather than created and never answered.
        if transport == TRANSPORT_LOCAL_MQTT:
            cloud_entities.extend(
                EzhiExtraSensor(cloud_coordinator, config[CONF_NAME], field)
                for field in EXTRA_SENSOR_FIELDS
            )
        add_entities(cloud_entities)


class EzhiBleOutputSensor(EzhiCloudEntity, SensorEntity):
    """One outputData value -- DC battery, per-string PV, extra temperatures,
    grid quality, and the raw fields whose meaning is not established.

    The local HTTP API does not carry any of these (measured 2026-08-08),
    which is exactly why the entity rides the control coordinator's poll and
    not the local one. That poll reads outputData over Bluetooth or over MQTT
    (verified 2026-08-11); the class name still says Ble for the sake of the
    entity unique-ids, which are user-visible and must not churn.

    Unavailable rather than stale or guessed whenever the last poll carried
    no output: on the cloud transport (always), and after a failed extra read
    (until the next successful poll).
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
        #
        # All three are optional. A raw field carries none of them because each
        # one would assert a meaning that has not been established -- and
        # SensorDeviceClass(None) would raise here anyway.
        if field.unit is not None:
            self._attr_native_unit_of_measurement = field.unit
        if field.device_class is not None:
            self._attr_device_class = SensorDeviceClass(field.device_class)
        if field.state_class is not None:
            self._attr_state_class = SensorStateClass(field.state_class)
        if field.diagnostic:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        if not field.enabled:
            self._attr_entity_registry_enabled_default = False

    @property
    def available(self) -> bool:
        return super().available and ble_output_available(self.coordinator.data)

    @property
    def native_value(self) -> float | None:
        return output_value(
            control_output(self.coordinator.data), self._field.key)


class EzhiWifiSignalSensor(EzhiCloudEntity, SensorEntity):
    """The inverter's own WiFi signal strength, in dBm.

    Answers "is the device on a decent link?" without a ping or a router
    lookup -- the number is the device's own view of its uplink, which is what
    actually decides whether the cloud and the local HTTP API stay reachable.

    The field is `rssi` in the BLE deviceInfo reply. Not `si`, and not in
    `wifiStatus`: measured 2026-08-10, wifiStatus answers with connetStatus and
    ssid only. Diagnostic category, because it explains failures rather than
    driving anything.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, device_name: str) -> None:
        super().__init__(coordinator, device_name, "ble_wifi_rssi", "WiFi Signal")

    @property
    def available(self) -> bool:
        return super().available and ble_device_available(self.coordinator.data)

    @property
    def native_value(self) -> int | None:
        raw = control_device(self.coordinator.data).get("rssi")
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None


class EzhiInfoSensor(EzhiCloudEntity, SensorEntity):
    """One deviceInfo field: firmware versions, addresses, locale, vendor codes.

    Free, which is the point: deviceInfo is already read on every control poll
    for the WiFi signal sensor above, and twenty-four of its twenty-seven
    fields were parsed and thrown away every cycle until 2026-08-11. These
    entities add no round trip.

    Unavailable rather than stale whenever the last poll carried no deviceInfo:
    the values are mostly static, which is exactly why a stale one is
    dangerous -- a firmware version that keeps showing the old number after the
    device stopped answering is worse than no number.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_name: str, field: InfoField) -> None:
        super().__init__(coordinator, device_name, field.uid, field.name)
        self._field = field
        # The table is HA-free on purpose (the tests run without
        # homeassistant); its strings are the enum values, looked up here so a
        # typo fails at setup rather than silently. All three are optional --
        # a raw field carries none of them, because each one would assert a
        # meaning that has not been established.
        if field.unit is not None:
            self._attr_native_unit_of_measurement = field.unit
        if field.device_class is not None:
            self._attr_device_class = SensorDeviceClass(field.device_class)
        if field.state_class is not None:
            self._attr_state_class = SensorStateClass(field.state_class)
        if not field.enabled:
            self._attr_entity_registry_enabled_default = False

    @property
    def available(self) -> bool:
        return super().available and ble_device_available(self.coordinator.data)

    @property
    def native_value(self):
        return info_value(control_device(self.coordinator.data), self._field.key)


class EzhiExtraSensor(EzhiCloudEntity, SensorEntity):
    """One field out of one of the six extra identifier reads.

    light, alarm, meterStatus and bindDevice are answered on `get` over MQTT
    and are read nowhere else in this integration. All of these are off by
    default: they explain exceptional cases -- an external meter, a paired
    device, an LED code -- and nobody should gain twenty-one entities from an
    update they did not ask for.

    Unavailable rather than stale whenever its own identifier is missing from
    the last poll. async_poll_all drops a read that failed and keeps the rest,
    so a missing identifier means precisely "this one did not answer this
    cycle", and showing the previous value would claim a freshness the poll did
    not deliver.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_name: str, field: ExtraField) -> None:
        super().__init__(coordinator, device_name, field.uid, field.name)
        self._field = field
        if field.unit is not None:
            self._attr_native_unit_of_measurement = field.unit
        if field.device_class is not None:
            self._attr_device_class = SensorDeviceClass(field.device_class)
        if field.state_class is not None:
            self._attr_state_class = SensorStateClass(field.state_class)
        if not field.enabled:
            self._attr_entity_registry_enabled_default = False

    @property
    def available(self) -> bool:
        return super().available and self._field.identifier in control_extras(
            self.coordinator.data)

    @property
    def native_value(self):
        return extra_value(control_extras(self.coordinator.data), self._field)


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
            "cloud_role": _CLOUD_ROLE.get(
                self._transport,
                "only opens the radio window when the 15 min idle timer closed it",
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
                # None, nicht 0. Ein fabriziertes 0 W landet sonst als echter
                # Messwert in der History und ist dort von einem stehenden
                # Wechselrichter nicht zu unterscheiden. Die Energie-Sensoren
                # dieser Datei machen es seit jeher so; die Leistungs-, Temp-
                # und SoC-Sensoren waren die Ausnahme.
                self._state = None
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
                # None, nicht 0. Ein fabriziertes 0 W landet sonst als echter
                # Messwert in der History und ist dort von einem stehenden
                # Wechselrichter nicht zu unterscheiden. Die Energie-Sensoren
                # dieser Datei machen es seit jeher so; die Leistungs-, Temp-
                # und SoC-Sensoren waren die Ausnahme.
                self._state = None
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
                # None, nicht 0. Ein fabriziertes 0 W landet sonst als echter
                # Messwert in der History und ist dort von einem stehenden
                # Wechselrichter nicht zu unterscheiden. Die Energie-Sensoren
                # dieser Datei machen es seit jeher so; die Leistungs-, Temp-
                # und SoC-Sensoren waren die Ausnahme.
                self._state = None
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
                # None, nicht 0. Ein fabriziertes 0 W landet sonst als echter
                # Messwert in der History und ist dort von einem stehenden
                # Wechselrichter nicht zu unterscheiden. Die Energie-Sensoren
                # dieser Datei machen es seit jeher so; die Leistungs-, Temp-
                # und SoC-Sensoren waren die Ausnahme.
                self._state = None
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
                # None, nicht 0. Ein fabriziertes 0 W landet sonst als echter
                # Messwert in der History und ist dort von einem stehenden
                # Wechselrichter nicht zu unterscheiden. Die Energie-Sensoren
                # dieser Datei machen es seit jeher so; die Leistungs-, Temp-
                # und SoC-Sensoren waren die Ausnahme.
                self._state = None
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
                # None, nicht 0. Ein fabriziertes 0 W landet sonst als echter
                # Messwert in der History und ist dort von einem stehenden
                # Wechselrichter nicht zu unterscheiden. Die Energie-Sensoren
                # dieser Datei machen es seit jeher so; die Leistungs-, Temp-
                # und SoC-Sensoren waren die Ausnahme.
                self._state = None
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
                # None, nicht 0. Ein fabriziertes 0 W landet sonst als echter
                # Messwert in der History und ist dort von einem stehenden
                # Wechselrichter nicht zu unterscheiden. Die Energie-Sensoren
                # dieser Datei machen es seit jeher so; die Leistungs-, Temp-
                # und SoC-Sensoren waren die Ausnahme.
                self._state = None
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
                # None, nicht 0. Ein fabriziertes 0 W landet sonst als echter
                # Messwert in der History und ist dort von einem stehenden
                # Wechselrichter nicht zu unterscheiden. Die Energie-Sensoren
                # dieser Datei machen es seit jeher so; die Leistungs-, Temp-
                # und SoC-Sensoren waren die Ausnahme.
                self._state = None
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
                # None, nicht 0. Ein fabriziertes 0 W landet sonst als echter
                # Messwert in der History und ist dort von einem stehenden
                # Wechselrichter nicht zu unterscheiden. Die Energie-Sensoren
                # dieser Datei machen es seit jeher so; die Leistungs-, Temp-
                # und SoC-Sensoren waren die Ausnahme.
                self._state = None
        self.async_write_ha_state()
