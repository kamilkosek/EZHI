"""Config flow for APsystems EZHI local API integration."""
import asyncio
from collections.abc import Mapping
from typing import Any

from aiohttp import client_exceptions
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_IP_ADDRESS, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    DOMAIN,
    LOGGER,
    SCAN_INTERVAL_OUTPUT,
    SCAN_INTERVAL_ALARM,
    DEFAULT_SCAN_INTERVAL_OUTPUT,
    DEFAULT_SCAN_INTERVAL_ALARM,
    UPDATE_INTERVAL,
    CONF_CLOUD_ACCESS_TOKEN,
    CONF_CLOUD_DEVICE_ID,
    CONF_CLOUD_PASSWORD,
    CONF_CLOUD_REFRESH_TOKEN,
    CONF_CLOUD_SCAN_INTERVAL,
    CONF_CLOUD_USERNAME,
    CONF_CONTROL_TRANSPORT,
    CONTROL_TRANSPORTS,
    DEFAULT_CLOUD_SCAN_INTERVAL,
    DEFAULT_CONTROL_TRANSPORT,
    TRANSPORT_LOCAL_MQTT,
    resolve_transport,
)
from .api import APsystemsEZHI
from .cloud import EzhiCloudApi, EzhiCloudAuthError, EzhiCloudError, async_login


class APsystemsEZHILocalAPIFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for APsystems EZHI Local API."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return APsystemsEZHIOptionsFlow()

    async def async_step_user(
            self,
            user_input: dict | None = None,
    ) -> config_entries.FlowResult:
        """Handle a flow initialized by the user."""
        _errors = {}

        if user_input is not None:
            try:
                if user_input.get("check", True):
                    api = APsystemsEZHI(user_input[CONF_IP_ADDRESS])
                    await api.get_device_info()
            except (client_exceptions.ClientConnectionError, asyncio.TimeoutError) as exception:
                LOGGER.warning(exception)
                _errors["base"] = "connection_refused"
            else:
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_IP_ADDRESS): str,
                    vol.Required(CONF_NAME): str,
                    vol.Optional("check", default=True): bool,
                    vol.Optional(SCAN_INTERVAL_OUTPUT, default=DEFAULT_SCAN_INTERVAL_OUTPUT): vol.All(
                        int, vol.Range(min=1)
                    ),
                    vol.Optional(SCAN_INTERVAL_ALARM, default=DEFAULT_SCAN_INTERVAL_ALARM): vol.All(
                        int, vol.Range(min=1)
                    ),
                    # Optional cloud control. Leave empty for a purely local setup.
                    vol.Optional(CONF_CLOUD_ACCESS_TOKEN, default=""): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Optional(CONF_CLOUD_REFRESH_TOKEN, default=""): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    # Range, not bare int: a 0 would make the coordinator hammer the vendor cloud.
                    vol.Optional(CONF_CLOUD_SCAN_INTERVAL, default=DEFAULT_CLOUD_SCAN_INTERVAL): vol.All(int, vol.Range(min=30)),
                }
            ),
            errors=_errors,
        )

    async def async_step_reauth(
            self,
            entry_data: Mapping[str, Any],
    ) -> config_entries.FlowResult:
        """The stored cloud refresh_token died — ask for a fresh one."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
            self,
            user_input: dict | None = None,
    ) -> config_entries.FlowResult:
        """Take a new token pair, verify it, and reload the entry."""
        entry = self._get_reauth_entry()
        _errors: dict[str, str] = {}

        if user_input is not None:
            device_id = entry.data.get(CONF_CLOUD_DEVICE_ID, "")
            if device_id:
                # Cheap: the deviceId is already cached, so this costs one
                # extra cloud call instead of leaving the user staring at
                # "Cloud credentials updated" right before the same reauth
                # dialog reopens on the next failed poll. This also happens
                # to exercise the refresh_token specifically -- __init__
                # forces _token_expires = 0.0, so the first call always goes
                # through _fetch_access_token first.
                api = EzhiCloudApi(
                    session=async_get_clientsession(self.hass),
                    device_id=device_id,
                    access_token=user_input[CONF_CLOUD_ACCESS_TOKEN],
                    refresh_token=user_input[CONF_CLOUD_REFRESH_TOKEN],
                )
                try:
                    # A caller sitting in front of a modal dialog is exactly
                    # the "overlapping refresh" case cloud.py's _call() opts
                    # out of a wrapping deadline for -- so this one supplies
                    # its own rather than risking ~4x15s on a hung cloud.
                    async with asyncio.timeout(20):
                        await api.async_get_config()
                except EzhiCloudAuthError:
                    _errors["base"] = "cloud_auth_failed"
                except (EzhiCloudError, TimeoutError) as err:
                    # A transport hiccup, a cloud outage or our own timeout
                    # must not stop the user from fixing their credentials --
                    # and must not stop someone whose inverter is simply
                    # switched off (EzhiCloudOfflineError) from doing so either.
                    LOGGER.warning(
                        "Could not verify the new cloud credentials: %s", err
                    )
            # No cached device_id -> nothing to call the API with; accept the
            # tokens unverified rather than blocking on a check that cannot run.

            if not _errors:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_CLOUD_ACCESS_TOKEN: user_input[CONF_CLOUD_ACCESS_TOKEN],
                        CONF_CLOUD_REFRESH_TOKEN: user_input[CONF_CLOUD_REFRESH_TOKEN],
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_CLOUD_ACCESS_TOKEN): vol.All(
                    TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
                    vol.Length(min=1),
                ),
                vol.Required(CONF_CLOUD_REFRESH_TOKEN): vol.All(
                    TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
                    vol.Length(min=1),
                ),
            }
        )
        return self.async_show_form(
            step_id="reauth_confirm",
            # None on the first call (no user_input yet); add_suggested_values_
            # to_schema handles that by leaving the schema untouched. On a
            # cloud_auth_failed re-show it re-populates both fields so a typo
            # doesn't mean pasting a long token pair a second time.
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=_errors,
        )


class APsystemsEZHIOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for APsystems EZHI."""

    # No __init__ needed - self.config_entry is set automatically by HA

    async def async_step_init(self, user_input=None):
        """Manage the options - redirect to device_options."""
        return await self.async_step_device_options()

    async def async_step_device_options(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Manage the device options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            access_token = user_input.get(CONF_CLOUD_ACCESS_TOKEN, "")
            refresh_token = user_input.get(CONF_CLOUD_REFRESH_TOKEN, "")

            # Credentials, when given, win over whatever is in the token
            # fields: the user filled them in precisely to replace those.
            username = (user_input.get(CONF_CLOUD_USERNAME) or "").strip()
            password = user_input.get(CONF_CLOUD_PASSWORD) or ""
            if username and password:
                try:
                    tokens = await async_login(
                        async_get_clientsession(self.hass), username, password
                    )
                except EzhiCloudAuthError as err:
                    LOGGER.warning("EZHI cloud login rejected: %s", err)
                    errors["base"] = "invalid_auth"
                except EzhiCloudError as err:
                    LOGGER.warning("EZHI cloud login failed: %s", err)
                    errors["base"] = "cannot_connect"
                else:
                    access_token = tokens["access_token"]
                    refresh_token = tokens["refresh_token"]
            elif username or password:
                # Half a credential pair is a typo, not an intent to clear the
                # cloud layer -- clearing is done by emptying the token fields.
                errors["base"] = "incomplete_credentials"

            # Local MQTT is the one transport whose precondition lives outside
            # Home Assistant: the inverter has to have been redirected at a
            # broker. Get that wrong and nothing says so -- the entry saves,
            # the control entities appear, and every poll quietly times out
            # until someone reads the log. Ask the device before saving.
            chosen = user_input.get(CONF_CONTROL_TRANSPORT,
                                    DEFAULT_CONTROL_TRANSPORT)
            if not errors and chosen == TRANSPORT_LOCAL_MQTT:
                problem = await self._probe_local_mqtt()
                if problem:
                    errors["base"] = problem

            if errors:
                # Mit den Eingaben des Nutzers, nicht mit den gespeicherten
                # Werten: sonst steht der Transport nach einem Probe-Fehler
                # wieder auf dem alten, und wer den Fehler behebt und erneut
                # absendet, speichert stillschweigend den alten Transport --
                # ohne Probe, also mit dem Anschein von Erfolg.
                return self.async_show_form(
                    step_id="device_options",
                    data_schema=self.add_suggested_values_to_schema(
                        self._device_options_schema(), user_input
                    ),
                    errors=errors,
                )

            new_data = {
                **self.config_entry.data,
                SCAN_INTERVAL_OUTPUT: user_input[SCAN_INTERVAL_OUTPUT],
                SCAN_INTERVAL_ALARM: user_input[SCAN_INTERVAL_ALARM],
                CONF_CLOUD_ACCESS_TOKEN: access_token,
                CONF_CLOUD_REFRESH_TOKEN: refresh_token,
                CONF_CLOUD_SCAN_INTERVAL: user_input.get(
                    CONF_CLOUD_SCAN_INTERVAL, DEFAULT_CLOUD_SCAN_INTERVAL
                ),
                # .get with the default, not [..]: an entry saved by an older
                # version has no such key, and the absent case must land on
                # cloud rather than raise.
                CONF_CONTROL_TRANSPORT: user_input.get(
                    CONF_CONTROL_TRANSPORT, DEFAULT_CONTROL_TRANSPORT
                ),
            }
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )
            # Reload the integration to apply new intervals
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            # Everything is persisted to entry.data above; passing user_input
            # here would duplicate both cloud tokens into entry.options, where
            # nothing reads them and a later reauth would leave them stale.
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="device_options", data_schema=self._device_options_schema()
        )

    async def _device_id_for_probe(self) -> str:
        """The device id, asked for rather than looked up.

        The cache in entry.data is written only while the control layer is
        being built (see __init__), and that layer is not built for an entry
        with no vendor credentials -- which is precisely the installation this
        transport exists for. Relying on the cache made the probe a
        chicken-and-egg: saving local_mqtt needed the probe, the probe needed
        the id, and the id only appeared once local_mqtt had been saved. A
        fresh install without a vendor account could never turn it on.

        So: live coordinator first if the entry happens to be loaded, cache
        second, and the inverter's own local HTTP API last. That last one is
        always available -- the integration cannot exist without the address -
        and it is what fills the cache in the first place.
        """
        stored = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id, {})
        coordinator = stored.get("COORDINATOR")
        info = getattr(coordinator, "device_info", None)
        if info is not None and getattr(info, "deviceId", ""):
            return info.deviceId

        cached = self.config_entry.data.get(CONF_CLOUD_DEVICE_ID, "")
        if cached:
            return cached

        try:
            api = APsystemsEZHI(
                ip_address=self.config_entry.data[CONF_IP_ADDRESS],
                session=async_get_clientsession(self.hass),
            )
            async with asyncio.timeout(10):
                return (await api.get_device_info()).deviceId
        except Exception as err:  # noqa: BLE001 - no id is no id
            LOGGER.warning("EZHI: could not read the device id locally: %s", err)
            return ""

    async def _probe_local_mqtt(self) -> str | None:
        """Ask the inverter one question over MQTT. Error key, or None if it answered.

        Deliberately a real read, not a broker ping. A configured broker proves
        nothing about this setup: the part that actually goes wrong is the
        redirect, and a broker with no inverter behind it looks perfectly
        healthy from Home Assistant's side.

        The probe subscribes and unsubscribes around itself rather than
        borrowing the running transport. The entry may not be loaded at all
        (first configuration), and reaching into another object's subscriptions
        from a config flow is how you end up unsubscribing someone else's.
        """
        try:
            from homeassistant.components import mqtt
        except ImportError:
            return "mqtt_not_configured"

        if "mqtt" not in self.hass.config.components:
            return "mqtt_not_configured"
        try:
            async with asyncio.timeout(10):
                if not await mqtt.async_wait_for_mqtt_client(self.hass):
                    return "mqtt_not_configured"
        except Exception:  # noqa: BLE001 - Timeout wie jeder andere Fehler
            return "mqtt_not_configured"

        device_id = await self._device_id_for_probe()
        if not device_id:
            # Nothing to address. Only reachable when the local HTTP API is
            # unreachable too, which is a different problem from a missing
            # redirect and deserves its own message.
            return "mqtt_device_unknown"

        from .mqtt_connect import make_mqtt_api

        api = make_mqtt_api(self.hass, device_id)
        try:
            # Generous next to the transport's own deadline: the firmware
            # answers on a ~5 s tick, and a user watching a spinner would
            # rather wait than be told "no" by a stopwatch.
            async with asyncio.timeout(25):
                try:
                    await api.async_subscribe()
                except Exception as err:  # noqa: BLE001
                    # Broker-Seite, nicht Geraeteseite. In die Umleitungs-
                    # Schublade zu stecken schickte den Nutzer zum falschen
                    # Problem.
                    LOGGER.warning("EZHI: cannot subscribe for the probe: %s", err)
                    return "mqtt_not_configured"
                await api.async_get_config()
        except Exception as err:  # noqa: BLE001 - any failure means "not proven"
            LOGGER.warning("EZHI local MQTT probe failed: %s", err)
            return "mqtt_no_reply"
        finally:
            await api.async_unsubscribe()
        return None

    def _device_options_schema(self) -> vol.Schema:
        """The options form. Built here so the error path can re-show it."""
        # Get current intervals from config entry (with legacy fallback)
        legacy_interval = self.config_entry.data.get(UPDATE_INTERVAL, DEFAULT_SCAN_INTERVAL_OUTPUT)
        current_output_interval = self.config_entry.data.get(SCAN_INTERVAL_OUTPUT, legacy_interval)
        current_alarm_interval = self.config_entry.data.get(SCAN_INTERVAL_ALARM, DEFAULT_SCAN_INTERVAL_ALARM)

        return vol.Schema(
                {
                    vol.Required(
                        SCAN_INTERVAL_OUTPUT,
                        default=current_output_interval,
                    ): vol.All(int, vol.Range(min=1)),
                    vol.Required(
                        SCAN_INTERVAL_ALARM,
                        default=current_alarm_interval,
                    ): vol.All(int, vol.Range(min=1)),
                    # description=suggested_value (not default=) is deliberate:
                    # the frontend strips empty-string fields before sending, so
                    # a default would make voluptuous silently reinsert the old
                    # token whenever the user clears the field to disable the
                    # cloud layer -- default= would make .get(key, "") below
                    # unreachable. suggested_value pre-fills the same way but
                    # leaves the key genuinely absent when submitted empty.
                    #
                    # ponytail: lost-update window -- if this dialog was opened
                    # before a concurrent reauth wrote a fresh token pair, the
                    # suggested_value below is already stale, and submitting
                    # this form unchanged overwrites the fresh pair with it.
                    # Narrow (both flows are human-timescale and rare together);
                    # the remedy is just another reauth, not worth a sentinel.
                    vol.Optional(
                        CONF_CLOUD_ACCESS_TOKEN,
                        description={
                            "suggested_value": self.config_entry.data.get(
                                CONF_CLOUD_ACCESS_TOKEN, ""
                            )
                        },
                    ): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
                    vol.Optional(
                        CONF_CLOUD_REFRESH_TOKEN,
                        description={
                            "suggested_value": self.config_entry.data.get(
                                CONF_CLOUD_REFRESH_TOKEN, ""
                            )
                        },
                    ): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
                    # Filling these in fetches a fresh token pair and writes it
                    # into the two fields above. Neither is persisted, which is
                    # also why they never come back pre-filled.
                    #
                    # TEXT, not EMAIL: loginEncrypt wants the EMA account's
                    # *username*. The e-mail address is rejected. An email
                    # selector would put the wrong keyboard on mobile and
                    # invite exactly the credential that does not work.
                    vol.Optional(CONF_CLOUD_USERNAME): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT)
                    ),
                    vol.Optional(CONF_CLOUD_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Optional(
                        CONF_CLOUD_SCAN_INTERVAL,
                        default=self.config_entry.data.get(
                            CONF_CLOUD_SCAN_INTERVAL, DEFAULT_CLOUD_SCAN_INTERVAL
                        ),
                    ): vol.All(int, vol.Range(min=30)),
                    # Which wire the control commands take. resolve_transport,
                    # not a raw .get: an entry that has never seen this option
                    # -- or carries a value from a later version -- has to
                    # open this dialog showing the transport it is actually
                    # using, which is cloud.
                    vol.Optional(
                        CONF_CONTROL_TRANSPORT,
                        default=resolve_transport(self.config_entry.data),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=list(CONTROL_TRANSPORTS),
                            translation_key=CONF_CONTROL_TRANSPORT,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
        )
