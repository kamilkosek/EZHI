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
from .const import CLOUD_COORDINATOR, DOMAIN, SYSTEM_MODE_OPTIONS
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

    Only the two verified modes are offered. The API also accepts a mode 3, but
    what it actually does is unconfirmed — and this select writes to real
    hardware, so it does not guess.
    """

    _attr_icon = "mdi:home-lightning-bolt"
    _attr_options = list(SYSTEM_MODE_OPTIONS)

    def __init__(self, coordinator, device_name: str):
        super().__init__(coordinator, device_name, "system_mode", "System Mode")

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
