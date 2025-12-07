"""The APsystems EZHI local API integration."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from time import monotonic

import voluptuous as vol
from aiohttp import client_exceptions
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_IP_ADDRESS, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from .const import (
    DOMAIN,
    SCAN_INTERVAL_OUTPUT,
    SCAN_INTERVAL_ALARM,
    DEFAULT_SCAN_INTERVAL_OUTPUT,
    DEFAULT_SCAN_INTERVAL_ALARM,
    UPDATE_INTERVAL,
    MIN_VALUE,
    MAX_VALUE,
)
from .api import APsystemsEZHI, ReturnOutputData, ReturnDeviceInfo, ReturnAlarmData

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.BINARY_SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up this integration using UI."""
    hass.data.setdefault(DOMAIN, {})
    
    api = APsystemsEZHI(ip_address=entry.data[CONF_IP_ADDRESS], timeout=8)
    
    # Get intervals (with legacy fallback)
    legacy_interval = entry.data.get(UPDATE_INTERVAL, DEFAULT_SCAN_INTERVAL_OUTPUT)
    output_interval = entry.data.get(SCAN_INTERVAL_OUTPUT, legacy_interval)
    alarm_interval = entry.data.get(SCAN_INTERVAL_ALARM, DEFAULT_SCAN_INTERVAL_ALARM)
    
    coordinator = ApSystemsDataCoordinator(
        hass, api,
        output_interval=output_interval,
        alarm_interval=alarm_interval,
    )
    
    # Fetch initial data BEFORE setting up platforms
    # This ensures device_info is available for device registration
    await coordinator.async_fetch_initial_data()
    
    hass.data[DOMAIN][entry.entry_id] = {**entry.data, "COORDINATOR": coordinator}
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register the set_power service
    async def set_power_service(call):
        power = call.data["power"]
        _LOGGER.debug("Setting power for %s watts", power)
        if power < MIN_VALUE:
            _LOGGER.warning("Power value %s is below minimum %s", power, MIN_VALUE)
            power = MIN_VALUE
        elif power > MAX_VALUE:
            _LOGGER.warning("Power value %s is above maximum %s", power, MAX_VALUE)
            power = MAX_VALUE
        await api.set_power(power)

    hass.services.async_register(
        DOMAIN, "set_power", set_power_service, schema=vol.Schema({
            vol.Required("power"): int,
        })
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["COORDINATOR"]
    coordinator.stop_alarm_timer()
    
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update listener."""
    await hass.config_entries.async_reload(entry.entry_id)


class InverterNotAvailable(Exception):
    """Exception raised when the inverter is not available."""
    pass


class ApSystemsDataCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: APsystemsEZHI,
        output_interval: int = DEFAULT_SCAN_INTERVAL_OUTPUT,
        alarm_interval: int = DEFAULT_SCAN_INTERVAL_ALARM,
    ):
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="APSystems EZHI Data",
            update_interval=timedelta(seconds=output_interval),
        )
        self.api = api
        self.always_update = True
        self.device_info: ReturnDeviceInfo | None = None
        self.alarm_data: ReturnAlarmData | None = None
        self._alarm_interval = alarm_interval
        self._alarm_unsub = None
    
    async def async_fetch_initial_data(self) -> None:
        """Fetch initial data before platforms are set up."""
        # Fetch device info first - needed for device registration
        try:
            self.device_info = await self.api.get_device_info()
            _LOGGER.debug("Initial device info loaded: %s", self.device_info.deviceId)
        except Exception as e:
            _LOGGER.warning("Failed to get initial device info: %s", e)
        
        # Fetch alarm data
        try:
            self.alarm_data = await self.api.get_alarm()
        except Exception as e:
            _LOGGER.warning("Failed to get initial alarm data: %s", e)
        
        # Fetch initial output data
        try:
            self.data = await self.api.get_output_data()
        except Exception as e:
            _LOGGER.warning("Failed to get initial output data: %s", e)
        
        # Now start the periodic timer for alarm/device updates
        self._start_alarm_timer()
    
    def _start_alarm_timer(self) -> None:
        """Start the timer for alarm and device info updates."""
        @callback
        def _async_alarm_update(_now=None):
            """Trigger alarm and device info update."""
            self.hass.async_create_task(self._async_update_alarm_and_device())
        
        # Schedule periodic updates (initial fetch already done)
        self._alarm_unsub = async_track_time_interval(
            self.hass,
            _async_alarm_update,
            timedelta(seconds=self._alarm_interval),
        )
    
    def stop_alarm_timer(self) -> None:
        """Stop the alarm timer."""
        if self._alarm_unsub:
            self._alarm_unsub()
            self._alarm_unsub = None
    
    async def _async_update_alarm_and_device(self) -> None:
        """Update alarm and device info data."""
        try:
            # Fetch device info
            try:
                self.device_info = await self.api.get_device_info()
            except Exception as e:
                _LOGGER.warning("Failed to get device info: %s", e)
            
            # Fetch alarm data
            try:
                self.alarm_data = await self.api.get_alarm()
            except Exception as e:
                _LOGGER.warning("Failed to get alarm data: %s", e)
            
            # Notify listeners that data has changed
            self.async_update_listeners()
            
        except Exception as e:
            _LOGGER.error("Error updating alarm/device data: %s", e)

    async def _async_update_data(self) -> ReturnOutputData | None:
        """Update output data via library (fast interval)."""
        try:
            data = await self.api.get_output_data()
            return data
        except (TimeoutError, client_exceptions.ClientConnectionError):
            raise InverterNotAvailable()

    async def _async_refresh(
        self,
        log_failures: bool = True,
        raise_on_auth_failed: bool = False,
        scheduled: bool = False,
        raise_on_entry_error: bool = False,
    ) -> None:
        """Refresh data and handle failures appropriately."""
        self._async_unsub_refresh()
        self._debounced_refresh.async_cancel()
        if self._shutdown_requested or scheduled and self.hass.is_stopping:
            return

        if log_timing := self.logger.isEnabledFor(logging.DEBUG):
            start = monotonic()

        auth_failed = False
        previous_update_success = self.last_update_success
        previous_data = self.data
        exc_triggered = False
        try:
            self.data = await self._async_update_data()
        except InverterNotAvailable:
            self.last_update_success = False
            exc_triggered = True
        except Exception as err:
            self.last_exception = err
            self.last_update_success = False
            self.logger.exception("Unexpected error fetching %s data", self.name)
            exc_triggered = True
        else:
            if not self.last_update_success and not exc_triggered:
                self.last_update_success = True
                self.logger.info("Fetching %s data recovered", self.name)
        finally:
            if log_timing:
                self.logger.debug(
                    "Finished fetching %s data in %.3f seconds (success: %s)",
                    self.name,
                    monotonic() - start,
                    self.last_update_success,
                )
            if not auth_failed and self._listeners and not self.hass.is_stopping:
                self._schedule_refresh()
        if not self.last_update_success and not previous_update_success:
            return
        if (
            self.always_update
            or self.last_update_success != previous_update_success
            or previous_data != self.data
        ):
            self.async_update_listeners()
