"""Shared base for the cloud-backed control entities.

Kept out of const.py: this needs Home Assistant imports (CoordinatorEntity,
DeviceInfo), and const.py stays import-light on purpose so cloud.py -- which
is deliberately free of homeassistant imports -- never has a reason to touch
this module.

Scoped to the three cloud entity classes only (switch.py, select.py,
number.py's EzhiCloudSocNumber). sensor.py, binary_sensor.py and the existing
local PowerLimit number have their own device_info variants and are not
touched by this base.
"""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


class EzhiCloudEntity(CoordinatorEntity):
    """Common device binding and naming for a cloud-backed control entity.

    `unique_id_suffix` and `name_suffix` are the only things that differ
    between the on/off switch, the system-mode select and the two SOC
    numbers -- everything else (device identity, manufacturer/model, the
    "apsystems_<device>_cloud_<suffix>" unique-id convention) was previously
    copied verbatim into all three.
    """

    def __init__(
        self,
        coordinator,
        device_name: str,
        unique_id_suffix: str,
        name_suffix: str,
    ) -> None:
        super().__init__(coordinator)
        self._device_name = device_name
        self._attr_name = f"APsystems {device_name} {name_suffix}"
        self._attr_unique_id = f"apsystems_{device_name}_cloud_{unique_id_suffix}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_name)},
            name=self._device_name,
            manufacturer="APsystems",
            model="EZHI",
        )
