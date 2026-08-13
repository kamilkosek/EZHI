"""The APsystems EZHI local API integration."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging

import voluptuous as vol
from aiohttp import client_exceptions
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_IP_ADDRESS, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import device_registry as dr
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
    BLE_LINK,
    CLOUD_COORDINATOR,
    CONF_CLOUD_ACCESS_TOKEN,
    CONF_CLOUD_DEVICE_ID,
    CONF_CLOUD_REFRESH_TOKEN,
    CONF_CLOUD_SCAN_INTERVAL,
    DEFAULT_CLOUD_SCAN_INTERVAL,
    MQTT_TRANSPORT,
    TRANSPORT_BLUETOOTH,
    TRANSPORT_LOCAL_MQTT,
    resolve_transport,
    wants_control_layer,
)
from .api import APsystemsEZHI, ReturnOutputData, ReturnDeviceInfo, ReturnAlarmData
from .ble_api import EzhiBleApi
from .ble_connect import ReconnectingLink, make_connector
from .ble_link import EzhiBleLink
from .mqtt_api import EzhiMqttApi
from .cloud import (
    EzhiCloudApi,
    EzhiCloudAuthError,
    EzhiCloudError,
    poll_control_data,
)
from .entity import CLOUD_WRITE_TIMEOUT_S, mode_ignoring_local_writes

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
]


def _resolve_entry_data(hass: HomeAssistant, call) -> dict:
    """Which EZHI a service call is for.

    The services are registered once for the integration, so the handler cannot
    close over one entry -- with two inverters set up, whichever loaded last
    would silently win every call. For set_high_power_mode that would mean
    raising a regulatory ceiling on the wrong device, quietly.

    So: an explicit device_id decides, a single loaded entry is unambiguous,
    and anything else is refused rather than guessed at.
    """
    loaded = {
        entry.entry_id: entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.entry_id in hass.data.get(DOMAIN, {})
    }
    if not loaded:
        raise HomeAssistantError("no APsystems EZHI device is currently loaded")

    device_id = call.data.get("device_id")
    if device_id:
        device = dr.async_get(hass).async_get(device_id)
        if device is None:
            raise HomeAssistantError(f"no such device: {device_id}")
        for entry_id in device.config_entries:
            if entry_id in loaded:
                return hass.data[DOMAIN][entry_id]
        raise HomeAssistantError(
            f"device {device.name or device_id} does not belong to a loaded "
            "APsystems EZHI entry"
        )

    if len(loaded) > 1:
        raise HomeAssistantError(
            f"{len(loaded)} APsystems EZHI devices are set up -- pass device_id "
            "to say which one you mean. This call changes hardware settings, so "
            "it will not pick one for you."
        )
    return next(iter(hass.data[DOMAIN].values()))


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up this integration using UI."""
    hass.data.setdefault(DOMAIN, {})
    
    api = APsystemsEZHI(ip_address=entry.data[CONF_IP_ADDRESS], timeout=8,
                        session=async_get_clientsession(hass))
    
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
    ble_link = None
    mqtt_api = None
    transport = resolve_transport(entry.data)
    has_cloud_credentials = bool(entry.data.get(CONF_CLOUD_REFRESH_TOKEN))
    # Local MQTT is the one transport that needs no vendor account, so it opens
    # this layer on its own -- everything below therefore has to cope with
    # cloud_api being None, which it did not have to before.
    # The condition lives in const.wants_control_layer so it can be tested
    # without Home Assistant: an entry without credentials must keep behaving
    # exactly as it did before any of these transports existed.
    if wants_control_layer(entry.data):
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
            # Load-bearing for every transport, not just the cloud one: it is
            # the serial in the MQTT topics as much as it is the cloud's
            # device id.
            _LOGGER.warning(
                "Control is configured but no deviceId is known yet "
                "(the local API returned none and none is cached) — skipping "
                "the control layer for this run. Reloading the integration "
                "will retry once the local API answers."
            )
        else:
            # None on a pure local-MQTT entry: there are no credentials to
            # build it from, and that transport needs none.
            cloud_api = None
            if has_cloud_credentials:
                cloud_api = EzhiCloudApi(
                    session=async_get_clientsession(hass),
                    device_id=device_id,
                    access_token=entry.data.get(CONF_CLOUD_ACCESS_TOKEN, ""),
                    refresh_token=entry.data[CONF_CLOUD_REFRESH_TOKEN],
                )
            # Which wire the control commands take. Everything above this line
            # -- coordinator, entities, services -- is unaware of the choice:
            # the two API objects have the same surface on purpose, so only
            # this one assignment differs.
            #
            # The cloud object is built either way and stays in use even on the
            # Bluetooth path: it is what opens the inverter's radio window when
            # the 15-minute idle timer has closed it. Bluetooth here means
            # "control over Bluetooth", not "no cloud".
            control_api = cloud_api
            if transport == TRANSPORT_BLUETOOTH:
                ble_link = ReconnectingLink(
                    EzhiBleLink(
                        device_id,
                        connector=make_connector(hass, device_id, cloud_api),
                    )
                )
                control_api = EzhiBleApi(ble_link, device_id, cloud=cloud_api)
                _LOGGER.info(
                    "EZHI %s: control commands go over Bluetooth; the cloud "
                    "credentials stay in use to open the radio window",
                    device_id,
                )
            elif transport == TRANSPORT_LOCAL_MQTT:
                try:
                    # Imported here, not at module level: the mqtt integration
                    # is a soft dependency and this module pulls it in. Under
                    # the guard for the same reason everything else on this
                    # path is -- we run before async_forward_entry_setups, so
                    # an exception escaping would take the local sensors down.
                    from .mqtt_connect import make_mqtt_api

                    mqtt_api = make_mqtt_api(hass, device_id)
                except Exception as err:  # noqa: BLE001 - never fail the entry
                    # Explicitly no control layer, rather than the cloud client
                    # this variable still holds. Falling back would look like a
                    # safety net and be the opposite: this transport is chosen
                    # because the inverter was redirected at a local broker,
                    # which means it is not connected to the vendor cloud at
                    # all. Cloud commands then answer 200 and change nothing --
                    # measured on a live install 2026-08-13. Silence beats a
                    # control surface that quietly does nothing.
                    control_api = None
                    _LOGGER.warning(
                        "EZHI: the local MQTT transport could not be set up "
                        "(%s); the control layer is skipped for this run. Not "
                        "falling back to the cloud -- a redirected inverter "
                        "cannot be reached that way", err,
                    )
                else:
                    control_api = mqtt_api
                    _LOGGER.info(
                        "EZHI %s: control commands go over the local MQTT broker",
                        device_id,
                    )
            if control_api is None:
                # Reachable whenever the local-MQTT transport failed to
                # build, with or without cloud credentials. Falling back to
                # the cloud is deliberately not done: this transport means the
                # inverter was redirected at a local broker, so it is not on
                # the vendor cloud and those commands would answer 200 and
                # change nothing. No control layer is the honest outcome -- a
                # coordinator polling None would traceback once a minute for
                # as long as the entry lives.
                _LOGGER.warning(
                    "EZHI: no usable control transport, so the control "
                    "entities are not created. The local sensors are "
                    "unaffected; reload the entry to retry"
                )
            else:
                cloud_coordinator = ApSystemsCloudCoordinator(
                    hass,
                    entry,
                    control_api,
                    entry.data.get(CONF_CLOUD_SCAN_INTERVAL, DEFAULT_CLOUD_SCAN_INTERVAL),
                )
                if mqtt_api is not None:
                    # Subscribe first, then poll. The device answers in
                    # milliseconds and a reply nobody is listening for is gone, so
                    # publishing before the subscription is a race it always wins.
                    #
                    # Every failure in here is caught and logged, none re-raised:
                    # this runs before async_forward_entry_setups, so an exception
                    # escaping would take down the local sensors too -- over a
                    # broker that is merely not configured yet.
                    try:
                        # Inside the guard on purpose: the mqtt integration is a
                        # soft dependency, so even an import problem must degrade
                        # rather than take the entry down.
                        from homeassistant.components import mqtt

                        # Under our own deadline: the helper waits up to 50 s for a
                        # broker entry that is still setting up, and this runs
                        # before the platforms are forwarded -- the local sensors
                        # must not wait that long for a control transport.
                        # Eigener Timeout-Handler, weil hier NICHT das Geraet
                        # antwortet, sondern Home Assistants MQTT-Integration.
                        # Beides in einen except-Zweig zu werfen erzeugte den
                        # Text "the inverter did not answer" fuer ein reines
                        # Broker-Problem -- und schickt den Nutzer das Geraet
                        # debuggen statt HA.
                        try:
                            async with asyncio.timeout(20):
                                client_ready = await mqtt.async_wait_for_mqtt_client(hass)
                        except TimeoutError:
                            _LOGGER.warning(
                                "EZHI: Home Assistant's MQTT integration did "
                                "not become ready within 20 s. This is the "
                                "broker side, not the inverter"
                            )
                            client_ready = False
                        if not client_ready:
                            _LOGGER.warning(
                                "EZHI: the MQTT integration is not ready, so the "
                                "control entities start unavailable. They recover "
                                "on the next reload once a broker is configured"
                            )
                        else:
                            await mqtt_api.async_subscribe()
                            # Same deadline and the same reasoning as the cloud
                            # arm below: async_refresh never raises, the timeout
                            # does, and neither may reach the local sensors.
                            async with asyncio.timeout(20):
                                await cloud_coordinator.async_refresh()
                    except TimeoutError:
                        _LOGGER.warning(
                            "EZHI: the inverter did not answer over MQTT within "
                            "20 s at startup; the control entities start "
                            "unavailable and recover on the next successful poll",
                        )
                    except Exception as err:  # noqa: BLE001 - never fail the entry
                        _LOGGER.warning(
                            "EZHI: setting up the local MQTT transport failed "
                            "(%s); the control entities start unavailable and the "
                            "local sensors are unaffected", err,
                        )
                elif ble_link is not None:
                    # The Bluetooth first contact runs off the setup path entirely.
                    # A closed radio window costs the wake (two cloud writes plus a
                    # 5 s edge gap) and then up to WAKE_DISCOVERY_TIMEOUT_S of
                    # waiting for a fresh advertisement -- structurally more than
                    # any reasonable setup budget. Measured 2026-08-06: the inline
                    # 60 s budget timed out twice, reproducibly, and its
                    # cancellation is what could leak a half-wired client. So the
                    # entities appear immediately (unavailable) and recover with
                    # the first successful poll; this task just makes that poll
                    # find a warm connection.
                    warm_link = ble_link
                    warm_coordinator = cloud_coordinator

                    async def _warm_ble_link() -> None:
                        try:
                            await warm_link.async_ensure_connected()
                        except Exception as err:  # noqa: BLE001 - report, don't crash the task
                            _LOGGER.warning(
                                "EZHI BLE: startup connect failed (%s); the "
                                "control entities stay unavailable until a "
                                "scheduled poll gets through", err,
                            )
                            return
                        await warm_coordinator.async_request_refresh()

                    entry.async_create_background_task(
                        hass, _warm_ble_link(),
                        name="apsystems_ezhi_local BLE warm connect",
                    )
                else:
                    # async_refresh, NOT async_config_entry_first_refresh: the
                    # latter raises ConfigEntryNotReady and would tear down the
                    # whole entry — local sensors included — over a cloud outage.
                    # The wrapping deadline keeps a hung cloud off the local
                    # sensors' critical path; async_refresh itself never raises,
                    # the timeout does.
                    try:
                        async with asyncio.timeout(20):
                            await cloud_coordinator.async_refresh()
                    except TimeoutError:
                        _LOGGER.warning(
                            "EZHI control layer did not answer within 20 s at "
                            "startup; the control entities start unavailable and "
                            "recover on the next successful poll",
                        )
                    if not cloud_coordinator.last_update_success:
                        _LOGGER.warning(
                            "EZHI cloud is unreachable at startup; the control "
                            "entities start unavailable and recover on the next "
                            "successful poll"
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
        # Only so unloading can close it -- nothing reads this to talk to the
        # device. A client left open across a reload blocks the next connect.
        BLE_LINK: ble_link,
        # Same, for the MQTT subscriptions.
        MQTT_TRANSPORT: mqtt_api,
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register the set_power service
    async def set_power_service(call):
        # The local API object of whichever entry this call targets -- not the
        # one this setup closed over, which would be the last entry loaded.
        entry_data = _resolve_entry_data(hass, call)
        api = entry_data["COORDINATOR"].api
        power = call.data["power"]
        _LOGGER.debug("Setting power for %s watts", power)
        if power < MIN_VALUE:
            _LOGGER.warning("Power value %s is below minimum %s", power, MIN_VALUE)
            power = MIN_VALUE
        elif power > MAX_VALUE:
            _LOGGER.warning("Power value %s is above maximum %s", power, MAX_VALUE)
            power = MAX_VALUE
        # The number entity is the other way to write this value and warns the
        # same way. An automation calling the service is the likelier of the
        # two to be writing into a mode that discards it, unattended.
        if (mode := mode_ignoring_local_writes(entry_data)) is not None:
            _LOGGER.warning(
                "Setting the on-grid power to %s W while the inverter is in %s "
                "mode. The device will answer SUCCESS and ignore it -- only "
                "Local mode acts on the local setpoint. See the README.",
                power, mode,
            )
        if not await api.set_power(power):
            raise HomeAssistantError(f"the inverter rejected the setpoint {power} W")

    if not hass.services.has_service(DOMAIN, "set_power"):
        hass.services.async_register(
            DOMAIN, "set_power", set_power_service, schema=vol.Schema({
                vol.Optional("device_id"): cv.string,
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
        cloud_coordinator = _resolve_entry_data(hass, call).get(CLOUD_COORDINATOR)
        if cloud_coordinator is None:
            raise HomeAssistantError(
                "high power mode needs the control layer, which this device "
                "has none of -- configure vendor credentials, or select the "
                "local MQTT transport"
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
                f"the inverter did not answer within {CLOUD_WRITE_TIMEOUT_S} s "
                "-- the power limit change may or may not have been applied"
            ) from err
        except EzhiCloudError as err:
            raise HomeAssistantError(str(err)) from err
        await cloud_coordinator.async_request_refresh()

    if not hass.services.has_service(DOMAIN, "set_high_power_mode"):
        hass.services.async_register(
            DOMAIN, "set_high_power_mode", set_high_power_mode_service,
            schema=vol.Schema({
                vol.Optional("device_id"): cv.string,
                vol.Required("enable"): cv.boolean,
                vol.Optional("acknowledge_regulatory_risk", default=False): cv.boolean,
            })
        )

    # Diagnostic-only: read one get-identifier over BLE and log the raw reply.
    # The point is `outputData`, whose reply carries pcsOriginalData -- inverter
    # frames the local HTTP API never returns. A service rather than a poll so
    # it fires once, on demand, and only where someone is looking.
    async def ble_raw_get_service(call):
        # The control API, not COORDINATOR.api -- that one is the local HTTP
        # poller. The BLE transport lives on the cloud/control coordinator,
        # same as set_high_power_mode reaches for.
        cloud_coordinator = _resolve_entry_data(hass, call).get(CLOUD_COORDINATOR)
        api = getattr(cloud_coordinator, "api", None)
        get_raw = getattr(api, "async_get_raw", None)
        if get_raw is None:
            raise HomeAssistantError(
                "ble_raw_get needs a transport that talks to the device "
                "directly (Bluetooth or local MQTT) -- the active one is the "
                "cloud, which has no raw read"
            )
        identifier = call.data.get("identifier", "outputData")
        try:
            reply = await get_raw(identifier)
        except EzhiCloudError as err:
            raise HomeAssistantError(str(err)) from err
        _LOGGER.warning("EZHI ble_raw_get %s -> %s", identifier, reply)

    if not hass.services.has_service(DOMAIN, "ble_raw_get"):
        hass.services.async_register(
            DOMAIN, "ble_raw_get", ble_raw_get_service,
            schema=vol.Schema({
                vol.Optional("device_id"): cv.string,
                vol.Optional("identifier", default="outputData"): cv.string,
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
        # The Bluetooth link does need explicit cleanup: an options change
        # reloads the entry, and a client still holding the inverter would make
        # the new one's connect fail against a device that accepts exactly one.
        # After the platforms, not before: while the entities are still there a
        # scheduled poll could reopen what was just closed. Failing to close it
        # must not fail the unload -- a half-unloaded entry is the worse state.
        ble_link = hass.data[DOMAIN][entry.entry_id].get(BLE_LINK)
        if ble_link is not None:
            try:
                await ble_link.async_disconnect()
            except Exception as err:  # noqa: BLE001 - bleak's error family varies
                _LOGGER.warning("EZHI: closing the Bluetooth link failed: %r", err)

        # Same reasoning for MQTT: subscriptions surviving a reload would hand
        # replies to a dead object's futures, and the reply topics would end
        # up with two listeners.
        mqtt_api = hass.data[DOMAIN][entry.entry_id].get(MQTT_TRANSPORT)
        if mqtt_api is not None:
            try:
                await mqtt_api.async_unsubscribe()
            except Exception as err:  # noqa: BLE001 - unload must not fail
                _LOGGER.warning("EZHI: dropping the MQTT subscriptions failed: %r", err)

        hass.data[DOMAIN].pop(entry.entry_id)
        # The services are registered once for the integration, not per entry,
        # so they have to go when the last entry does. Leaving them behind gave
        # a KeyError from a handler holding a dead entry_id.
        if not hass.data[DOMAIN]:
            for service in ("set_power", "set_high_power_mode", "ble_raw_get"):
                hass.services.async_remove(DOMAIN, service)

    return unload_ok


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

    async def _async_update_data(self) -> ReturnOutputData:
        """Update output data via library (fast interval)."""
        try:
            data = await self.api.get_output_data()
            return data
        except (TimeoutError, client_exceptions.ClientConnectionError) as err:
            # UpdateFailed statt eigener Ausnahme plus nachgebautem
            # _async_refresh: Home Assistant behandelt das seit jeher genau so,
            # wie es hier gebraucht wird -- last_update_success faellt, die
            # Meldung kommt einmal, danach ist Ruhe bis zur Erholung. Der
            # Nachbau kopierte dafuer HA-Interna (_shutdown_requested,
            # _debounced_refresh, _schedule_refresh) und waere bei einem
            # HA-Upgrade still gebrochen.
            raise UpdateFailed(f"the inverter did not answer: {err}") from err



class ApSystemsCloudCoordinator(DataUpdateCoordinator):
    """Polls the control API: the configuration, plus outputData over BLE.

    Deliberately a second, separate coordinator: the local sensors must keep
    working when the cloud token dies, the internet drops or APsystems has an
    outage. Nothing in here may raise into the local coordinator's path.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        # Either transport: the two APIs have the same surface, and this
        # coordinator only ever calls async_get_config on it. EzhiBleError is
        # an EzhiCloudError, so the error handling below covers both.
        api: EzhiCloudApi | EzhiBleApi,
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
            # On the cloud transport the config barely changes, so this skips
            # waking every listener just to write back an identical dict. On
            # Bluetooth the poll also carries outputData, whose live values
            # change almost every cycle -- those listener wakes are real
            # updates, not waste, and this stays correct for both.
            always_update=False,
        )
        self.api = api

    async def _async_update_data(self) -> dict:
        # The poll policy -- config always, outputData only where the
        # transport has it -- lives in cloud.py as poll_control_data, where
        # the tests can reach it without importing Home Assistant. The data
        # shape is {"config": ..., "output": ...}; entities read it through
        # cloud.py's control_config/control_output.
        try:
            return await poll_control_data(self.api)
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
