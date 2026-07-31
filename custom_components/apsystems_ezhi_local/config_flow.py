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
    CONF_CLOUD_REFRESH_TOKEN,
    CONF_CLOUD_SCAN_INTERVAL,
    DEFAULT_CLOUD_SCAN_INTERVAL,
)
from .api import APsystemsEZHI
from .cloud import EzhiCloudApi, EzhiCloudAuthError, EzhiCloudError


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
        if user_input is not None:
            # Update the config entry data with new intervals
            new_data = {
                **self.config_entry.data,
                SCAN_INTERVAL_OUTPUT: user_input[SCAN_INTERVAL_OUTPUT],
                SCAN_INTERVAL_ALARM: user_input[SCAN_INTERVAL_ALARM],
                CONF_CLOUD_ACCESS_TOKEN: user_input.get(CONF_CLOUD_ACCESS_TOKEN, ""),
                CONF_CLOUD_REFRESH_TOKEN: user_input.get(CONF_CLOUD_REFRESH_TOKEN, ""),
                CONF_CLOUD_SCAN_INTERVAL: user_input.get(
                    CONF_CLOUD_SCAN_INTERVAL, DEFAULT_CLOUD_SCAN_INTERVAL
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

        # Get current intervals from config entry (with legacy fallback)
        legacy_interval = self.config_entry.data.get(UPDATE_INTERVAL, DEFAULT_SCAN_INTERVAL_OUTPUT)
        current_output_interval = self.config_entry.data.get(SCAN_INTERVAL_OUTPUT, legacy_interval)
        current_alarm_interval = self.config_entry.data.get(SCAN_INTERVAL_ALARM, DEFAULT_SCAN_INTERVAL_ALARM)

        return self.async_show_form(
            step_id="device_options",
            data_schema=vol.Schema(
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
                    vol.Optional(
                        CONF_CLOUD_SCAN_INTERVAL,
                        default=self.config_entry.data.get(
                            CONF_CLOUD_SCAN_INTERVAL, DEFAULT_CLOUD_SCAN_INTERVAL
                        ),
                    ): vol.All(int, vol.Range(min=30)),
                }
            ),
        )
