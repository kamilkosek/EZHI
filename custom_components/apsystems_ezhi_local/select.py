"""Select platform for the APsystems EZHI integration (cloud-backed)."""
from __future__ import annotations

import asyncio

from homeassistant import config_entries
from homeassistant.components.select import SelectEntity
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .cloud import EzhiCloudError, wire_str
from .const import (
    CLOUD_COORDINATOR,
    DOMAIN,
    SYSTEM_MODE_NO_BATTERY,
    SYSTEM_MODE_OPTIONS,
)
from .entity import CLOUD_WRITE_TIMEOUT_S, EzhiCloudEntity

_VALUE_TO_OPTION = {value: name for name, value in SYSTEM_MODE_OPTIONS.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    add_entities: AddEntitiesCallback,
) -> None:
    """Set up the select platform."""
    config = hass.data[DOMAIN][config_entry.entry_id]
    cloud_coordinator = config.get(CLOUD_COORDINATOR)
    if cloud_coordinator is None:
        return

    add_entities([EzhiCloudSystemModeSelect(cloud_coordinator, config[CONF_NAME])])


class EzhiCloudSystemModeSelect(EzhiCloudEntity, SelectEntity):
    """The inverter's system mode.

    Five of the six modes are offered; see const.SYSTEM_MODE_OPTIONS for why
    the AC-coupled variant is not.

    Switching to Local mode is what enables the local HTTP API this integration
    reads from. Leaving it does not break the cloud entities, but it does stop
    the local sensors updating -- that is a property of the device, not of this
    code.
    """

    _attr_icon = "mdi:home-lightning-bolt"
    _attr_options = list(SYSTEM_MODE_OPTIONS)

    def __init__(self, coordinator, device_name: str):
        super().__init__(coordinator, device_name, "system_mode", "System Mode")

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        return {
            "no_battery_mode_warning": (
                "'No Battery' is for inverters running without a battery attached. "
                "Selecting it while a battery is connected is the 'battery connection "
                "conflict' the vendor app warns about; this entity refuses the write "
                "while the cloud still reports a battery."
            ),
            "local_mode_note": (
                "'Local' is the mode that enables the local HTTP API. Switching away "
                "from it stops this integration's local sensors updating."
            ),
        }

    @property
    def current_option(self) -> str | None:
        raw = (self.coordinator.data or {}).get("systemMode")
        if raw is None:
            return None
        # wire_str, not a bare str(): build_system_mode_params normalises the
        # same payload's fields with wire_str for writes (str(2.0) == "2.0",
        # not the "2" this key table uses). None for an unmapped mode (e.g. 3)
        # rather than a wrong label.
        return _VALUE_TO_OPTION.get(wire_str(raw))

    async def async_select_option(self, option: str) -> None:
        if SYSTEM_MODE_OPTIONS[option] == SYSTEM_MODE_NO_BATTERY:
            # A guard, not a label. The vendor app raises "battery connection
            # conflict" for exactly this and tells the user to disconnect the
            # battery first. noBattery is the device's own report, so this
            # lifts by itself once a battery really is gone -- no override
            # switch to leave lying around, and nothing to remember to undo.
            no_battery = wire_str((self.coordinator.data or {}).get("noBattery", ""))
            if no_battery == "0":
                raise HomeAssistantError(
                    "refusing to switch to 'No Battery' mode: the inverter still "
                    "reports a battery connected (noBattery=0). That combination is "
                    "the 'battery connection conflict' the vendor app warns about. "
                    "Physically disconnect the battery first, or make this change "
                    "from the APsystems app if you know what you are doing."
                )
            if no_battery != "1":
                # Absent or unparsable, so we cannot tell. This used to fall
                # through and allow the switch -- failing open on the one
                # question the guard exists to answer. Refusing costs nothing
                # when the field is there (every firmware seen reports it), and
                # the message says exactly where to go when it is not.
                raise HomeAssistantError(
                    "refusing to switch to 'No Battery' mode: the cloud config "
                    f"does not say whether a battery is connected (noBattery="
                    f"{no_battery!r}). Switching blind is how the 'battery "
                    "connection conflict' happens. Use the APsystems app, which "
                    "asks the device directly."
                )
        try:
            async with asyncio.timeout(CLOUD_WRITE_TIMEOUT_S):
                # No config argument: the client re-reads the live config
                # itself, so a mode switch cannot write back a minute-old
                # EPS/ECO. That re-read is a GET before the POST, so the
                # unguarded worst case here is roughly double switch.py's.
                await self.coordinator.api.async_set_system_mode(
                    systemMode=SYSTEM_MODE_OPTIONS[option]
                )
        except TimeoutError as err:
            raise HomeAssistantError(
                f"the EZHI cloud did not answer within {CLOUD_WRITE_TIMEOUT_S} s "
                "-- the system mode change may or may not have been applied"
            ) from err
        except EzhiCloudError as err:
            raise HomeAssistantError(str(err)) from err
        await self.coordinator.async_request_refresh()
