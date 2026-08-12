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

from .cloud import control_config, wire_str
from .const import CLOUD_COORDINATOR, DOMAIN, local_setpoint_ignored_by

# Deadline for a service-call write to the cloud (switch/select/number's
# async_turn_on/off, async_select_option, async_set_native_value). This is
# not cloud.py's own per-HTTP-round-trip timeout (EzhiCloudApi's self._timeout,
# 15 s default): cloud.py's ponytail: comment ties its no-wrapping-deadline
# stance to DataUpdateCoordinator being the only caller, and worst case per
# attempt is already ~4x that. select.py/number.py's writes are a GET+POST,
# so unguarded worst case is 60-120 s. Without this, a slow cloud leaves the
# service call hanging, the frontend times out, the user reads that as
# failure and presses again -- a second write to a hybrid inverter, the
# exact hazard _attr_assumed_state exists to reduce, arriving through
# another door. 30 s surfaces that risk as a clear error well before the
# true worst case.
CLOUD_WRITE_TIMEOUT_S = 30


def mode_ignoring_local_writes(entry_data: dict) -> str | None:
    """Name of the system mode that will discard a local setPower, or None.

    Lives here rather than in either caller because there are two ways to write
    the setpoint -- the number entity and the set_power service -- and a rule
    that guards only one of them is worse than no rule: it teaches the log
    reader that silence means the write landed.

    None when the cloud side is not configured. Reading the mode is what makes
    the warning possible at all, and that is optional.
    """
    coordinator = entry_data.get(CLOUD_COORDINATOR)
    if coordinator is None:
        return None
    raw = control_config(coordinator.data).get("systemMode")
    return local_setpoint_ignored_by(None if raw is None else wire_str(raw))


class EzhiCloudEntity(CoordinatorEntity):
    """Common device binding and naming for a cloud-backed control entity.

    `unique_id_suffix` and `name_suffix` are the only things that differ
    between the on/off switch, the system-mode select and the two SOC
    numbers -- everything else (device identity, manufacturer/model, the
    "apsystems_<device>_cloud_<suffix>" unique-id convention) was previously
    copied verbatim into all three.
    """

    # The name is the entity's alone ("Backup Power"); Home Assistant puts the
    # device name in front of it. Baking it in here as well produced "EZHI
    # APsystems EZHI Backup Power" wherever the frontend shows both.
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator,
        device_name: str,
        unique_id_suffix: str,
        name_suffix: str,
    ) -> None:
        super().__init__(coordinator)
        self._device_name = device_name
        self._attr_name = name_suffix
        self._attr_unique_id = f"apsystems_{device_name}_cloud_{unique_id_suffix}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_name)},
            name=self._device_name,
            manufacturer="APsystems",
            model="EZHI",
        )
