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
from .alarm_texts import alarm_text
from .api import ReturnAlarmData
from .const import DOMAIN


@dataclass(frozen=True, kw_only=True)
class EZHIBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes EZHI binary sensor entity."""
    
    # The getAlarm field this sensor reads, which is also the key into
    # ALARM_TEXTS. Carried explicitly rather than parsed back out of value_fn.
    alarm_code: str

    # bool | None, not bool: the three newest alarm fields are absent on
    # older firmware, and "we don't know" is not the same answer as "no".
    value_fn: Callable[[ReturnAlarmData], bool | None]


def _alarm_flag(raw) -> bool | None:
    """One alarm field to on/off, or None when the firmware did not report it.

    The older sensors in this file compare to "1" directly and so read a
    missing field as "off". For a field that may genuinely be absent, that
    would assert the absence of a fault the device never denied.
    """
    if raw is None or str(raw) == "":
        return None
    return str(raw) == "1"


ALARM_SENSORS: tuple[EZHIBinarySensorEntityDescription, ...] = (
    EZHIBinarySensorEntityDescription(
        key="battery_overtemp",
        name="Battery Overtemperature",
        device_class=BinarySensorDeviceClass.PROBLEM,
        alarm_code="BatHTP",
        value_fn=lambda data: str(data.BatHTP) == "1",
    ),
    EZHIBinarySensorEntityDescription(
        key="battery_undertemp",
        name="Battery Undertemperature",
        device_class=BinarySensorDeviceClass.PROBLEM,
        alarm_code="BatLTP",
        value_fn=lambda data: str(data.BatLTP) == "1",
    ),
    EZHIBinarySensorEntityDescription(
        key="battery_comm_error",
        name="Battery Communication Error",
        device_class=BinarySensorDeviceClass.PROBLEM,
        alarm_code="BatCE",
        value_fn=lambda data: str(data.BatCE) == "1",
    ),
    EZHIBinarySensorEntityDescription(
        key="battery_overvoltage",
        name="Battery Overvoltage",
        device_class=BinarySensorDeviceClass.PROBLEM,
        alarm_code="BatHV",
        value_fn=lambda data: str(data.BatHV) == "1",
    ),
    EZHIBinarySensorEntityDescription(
        key="battery_undervoltage",
        name="Battery Undervoltage",
        device_class=BinarySensorDeviceClass.PROBLEM,
        alarm_code="BatLV",
        value_fn=lambda data: str(data.BatLV) == "1",
    ),
    EZHIBinarySensorEntityDescription(
        key="battery_overcurrent",
        name="Battery Overcurrent",
        device_class=BinarySensorDeviceClass.PROBLEM,
        alarm_code="BatHI",
        value_fn=lambda data: str(data.BatHI) == "1",
    ),
    EZHIBinarySensorEntityDescription(
        key="battery_error",
        name="Battery Error",
        device_class=BinarySensorDeviceClass.PROBLEM,
        alarm_code="BatE",
        value_fn=lambda data: str(data.BatE) == "1",
    ),
    EZHIBinarySensorEntityDescription(
        key="battery_shutdown",
        name="Battery Shutdown",
        device_class=BinarySensorDeviceClass.PROBLEM,
        alarm_code="SBS",
        value_fn=lambda data: str(data.SBS) == "1",
    ),
    EZHIBinarySensorEntityDescription(
        key="device_overtemp",
        name="Device Overtemperature",
        device_class=BinarySensorDeviceClass.PROBLEM,
        alarm_code="DTP",
        value_fn=lambda data: str(data.DTP) == "1",
    ),
    EZHIBinarySensorEntityDescription(
        key="device_error",
        name="Device Error",
        device_class=BinarySensorDeviceClass.PROBLEM,
        alarm_code="EE",
        value_fn=lambda data: str(data.EE) == "1",
    ),
    EZHIBinarySensorEntityDescription(
        key="ac_abnormal",
        name="AC Abnormal",
        device_class=BinarySensorDeviceClass.PROBLEM,
        alarm_code="ACA",
        value_fn=lambda data: str(data.ACA) == "1",
    ),
    EZHIBinarySensorEntityDescription(
        key="offgrid_overcurrent",
        name="Off-Grid Overcurrent",
        device_class=BinarySensorDeviceClass.PROBLEM,
        alarm_code="OfOI",
        value_fn=lambda data: str(data.OfOI) == "1",
    ),
    EZHIBinarySensorEntityDescription(
        key="offgrid_short",
        name="Off-Grid Short Circuit",
        device_class=BinarySensorDeviceClass.PROBLEM,
        alarm_code="OfGS",
        value_fn=lambda data: str(data.OfGS) == "1",
    ),
    EZHIBinarySensorEntityDescription(
        key="pv_overvoltage",
        name="PV Overvoltage",
        device_class=BinarySensorDeviceClass.PROBLEM,
        alarm_code="PvHV",
        value_fn=lambda data: str(data.PvHV) == "1",
    ),
    EZHIBinarySensorEntityDescription(
        key="pv_overcurrent",
        name="PV Overcurrent",
        device_class=BinarySensorDeviceClass.PROBLEM,
        alarm_code="PvOC",
        value_fn=lambda data: str(data.PvOC) == "1",
    ),
    EZHIBinarySensorEntityDescription(
        key="pv_wiring_error",
        name="PV Wiring Error",
        device_class=BinarySensorDeviceClass.PROBLEM,
        alarm_code="PVWE",
        value_fn=lambda data: str(data.PVWE) == "1",
    ),
    EZHIBinarySensorEntityDescription(
        key="ird_error",
        name="IRD Error",
        device_class=BinarySensorDeviceClass.PROBLEM,
        alarm_code="IRDE",
        value_fn=lambda data: str(data.IRDE) == "1",
    ),
    # The three fields getAlarm reports but the integration never mapped.
    # Names and meanings are the vendor app's own, not invented here.
    EZHIBinarySensorEntityDescription(
        key="soc_calibration",
        name="SOC Calibration Needed",
        device_class=BinarySensorDeviceClass.PROBLEM,
        alarm_code="BCC",
        value_fn=lambda data: _alarm_flag(data.BCC),
    ),
    EZHIBinarySensorEntityDescription(
        key="battery_access_conflict",
        name="Battery Access Conflict",
        device_class=BinarySensorDeviceClass.PROBLEM,
        alarm_code="BCI",
        value_fn=lambda data: _alarm_flag(data.BCI),
    ),
    EZHIBinarySensorEntityDescription(
        key="voltage_reset_protection",
        name="Voltage Reset Protection",
        device_class=BinarySensorDeviceClass.PROBLEM,
        alarm_code="VRP",
        value_fn=lambda data: _alarm_flag(data.VRP),
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

    # See EzhiCloudEntity: with this set the name is entity_description.name
    # alone, and Home Assistant prefixes the device name itself.
    _attr_has_entity_name = True

    # These never change, and there are twenty of these entities: recording a
    # paragraph of static text on every alarm poll would grow the database for
    # nothing.
    _unrecorded_attributes = frozenset(
        {"alarm_code", "vendor_name", "cause", "suggested_action"}
    )

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
    def extra_state_attributes(self) -> dict[str, str]:
        """What the vendor app would tell you about this alarm.

        Carried whether or not the alarm is active: someone looking at a
        problem sensor wants to know what it would mean before it fires, and
        an attribute that only appears during a fault is one nobody finds when
        they need it.
        """
        code = self.entity_description.alarm_code
        text = alarm_text(code, self.hass.config.language if self.hass else None)
        attrs = {"alarm_code": code}
        if text.get("name"):
            attrs["vendor_name"] = text["name"]
        if text.get("reason"):
            attrs["cause"] = text["reason"]
        if text.get("suggest"):
            attrs["suggested_action"] = text["suggest"]
        return attrs

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
