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
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from .const import (
    DOMAIN,
    SCAN_INTERVAL_OUTPUT,
    SCAN_INTERVAL_ALARM,
    DEFAULT_SCAN_INTERVAL_OUTPUT,
    DEFAULT_SCAN_INTERVAL_ALARM,
    UPDATE_INTERVAL,
    MIN_VALUE,
    MAX_VALUE,
    CLOUD_COORDINATOR,
    CONF_CLOUD_ACCESS_TOKEN,
    CONF_CLOUD_DEVICE_ID,
    CONF_CLOUD_REFRESH_TOKEN,
    CONF_CLOUD_SCAN_INTERVAL,
    DEFAULT_CLOUD_SCAN_INTERVAL,
)
from .api import APsystemsEZHI, ReturnOutputData, ReturnDeviceInfo, ReturnAlarmData
from .cloud import EzhiCloudApi, EzhiCloudAuthError, EzhiCloudError
from .entity import CLOUD_WRITE_TIMEOUT_S

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
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

    # --- optional cloud control layer ---------------------------------------
    # Strictly isolated: every failure path here leaves the local sensors alone.
    cloud_coordinator = None
    if entry.data.get(CONF_CLOUD_REFRESH_TOKEN):
        # Prefer the live deviceId, fall back to the cached one: the local
        # coordinator swallows a failed get_device_info() and leaves
        # device_info None, and the deviceId is stable hardware identity, so
        # one transient local-API failure must not disable the cloud layer
        # for the entry's whole lifetime.
        live_device_id = coordinator.device_info.deviceId if coordinator.device_info else ""
        device_id = live_device_id or entry.data.get(CONF_CLOUD_DEVICE_ID, "")
        if live_device_id and live_device_id != entry.data.get(CONF_CLOUD_DEVICE_ID):
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_CLOUD_DEVICE_ID: live_device_id}
            )
        if not device_id:
            _LOGGER.warning(
                "Cloud control is configured but no deviceId is known yet "
                "(the local API returned none and none is cached) — skipping "
                "the cloud layer for this run. Reloading the integration "
                "will retry once the local API answers."
            )
        else:
            cloud_api = EzhiCloudApi(
                session=async_get_clientsession(hass),
                device_id=device_id,
                access_token=entry.data.get(CONF_CLOUD_ACCESS_TOKEN, ""),
                refresh_token=entry.data[CONF_CLOUD_REFRESH_TOKEN],
            )
            cloud_coordinator = ApSystemsCloudCoordinator(
                hass,
                entry,
                cloud_api,
                entry.data.get(CONF_CLOUD_SCAN_INTERVAL, DEFAULT_CLOUD_SCAN_INTERVAL),
            )
            # async_refresh, NOT async_config_entry_first_refresh: the latter
            # raises ConfigEntryNotReady and would tear down the whole entry —
            # local sensors included — over a cloud outage.
            # The wrapping deadline keeps a hung cloud off the local sensors'
            # critical path; async_refresh itself never raises, the timeout does.
            try:
                async with asyncio.timeout(20):
                    await cloud_coordinator.async_refresh()
            except TimeoutError:
                _LOGGER.warning(
                    "EZHI cloud did not answer within 20 s at startup; the "
                    "control entities start unavailable and recover on the "
                    "next successful poll"
                )
            if not cloud_coordinator.last_update_success:
                _LOGGER.warning(
                    "EZHI cloud is unreachable at startup; the control entities "
                    "start unavailable and recover on the next successful poll"
                )
    elif entry.data.get(CONF_CLOUD_ACCESS_TOKEN):
        # Half-configured: an access token with no refresh token can never
        # bootstrap (refreshToken needs both), so the cloud layer is skipped
        # -- but silently, with no entities and no error, was indistinguishable
        # from "cloud not configured at all". Name the missing field.
        _LOGGER.warning(
            "Cloud control has a cloud_access_token but no "
            "cloud_refresh_token configured; both are required, so the "
            "cloud layer is skipped. Add the missing refresh token to "
            "enable it."
        )

    hass.data[DOMAIN][entry.entry_id] = {
        **entry.data,
        "COORDINATOR": coordinator,
        CLOUD_COORDINATOR: cloud_coordinator,
    }
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

    # High power mode is a service, not a switch entity, and the reason is the
    # disclaimer the vendor app puts in front of it: 1200 W "may cause the
    # device output to exceed regulatory limits for grid connection", with the
    # legal risk on the operator. Home Assistant has no confirmation dialog for
    # an entity -- a switch is always one tap -- but a service field is a
    # deliberate act. Hence the acknowledgement, required only in the direction
    # that carries the risk.
    async def set_high_power_mode_service(call):
        cloud_coordinator = hass.data[DOMAIN][entry.entry_id].get(CLOUD_COORDINATOR)
        if cloud_coordinator is None:
            raise HomeAssistantError(
                "high power mode is a cloud setting and no cloud credentials are "
                "configured for this device"
            )
        enable = call.data["enable"]
        if enable and not call.data.get("acknowledge_regulatory_risk"):
            raise HomeAssistantError(
                "enabling high power mode raises the output ceiling to 1200 W, "
                "which may exceed the regulatory limit for your grid connection. "
                "Set acknowledge_regulatory_risk: true to confirm you accept "
                "responsibility for that."
            )
        try:
            async with asyncio.timeout(CLOUD_WRITE_TIMEOUT_S):
                await cloud_coordinator.api.async_set_high_power(enable)
        except TimeoutError as err:
            raise HomeAssistantError(
                f"the EZHI cloud did not answer within {CLOUD_WRITE_TIMEOUT_S} s "
                "-- the power limit change may or may not have been applied"
            ) from err
        except EzhiCloudError as err:
            raise HomeAssistantError(str(err)) from err
        await cloud_coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN, "set_high_power_mode", set_high_power_mode_service,
        schema=vol.Schema({
            vol.Required("enable"): cv.boolean,
            vol.Optional("acknowledge_regulatory_risk", default=False): cv.boolean,
        })
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["COORDINATOR"]
    coordinator.stop_alarm_timer()
    # The cloud coordinator (if any) needs no explicit cleanup here:
    # DataUpdateCoordinator.__init__ already registers
    # async_on_unload(self.async_shutdown) for itself.

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
            name="APsystems EZHI Data",
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


class ApSystemsCloudCoordinator(DataUpdateCoordinator):
    """Polls the EMA cloud for the controllable configuration.

    Deliberately a second, separate coordinator: the local sensors must keep
    working when the cloud token dies, the internet drops or APsystems has an
    outage. Nothing in here may raise into the local coordinator's path.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: EzhiCloudApi,
        interval: int,
    ):
        super().__init__(
            hass,
            _LOGGER,
            name="APsystems EZHI Cloud",
            update_interval=timedelta(seconds=interval),
            # Explicit rather than relying on the current_entry ContextVar:
            # the reauth flow needs self.config_entry to be set.
            config_entry=entry,
            # The cloud config barely changes; don't wake every listener each
            # poll just to write back an identical dict.
            always_update=False,
        )
        self.api = api

    async def _async_update_data(self) -> dict:
        try:
            return await self.api.async_get_config()
        except EzhiCloudAuthError as err:
            # Raising this makes HA start a reauth flow instead of retrying a
            # credential that will never work again.
            raise ConfigEntryAuthFailed(str(err)) from err
        except EzhiCloudError as err:
            # cloud.py's _http() already wraps every transport failure (and
            # timeout) into EzhiCloudError itself, so catching it alone is
            # sufficient here — no separate client_exceptions.ClientError /
            # TimeoutError arm needed.
            raise UpdateFailed(f"EZHI cloud poll failed: {err}") from err
