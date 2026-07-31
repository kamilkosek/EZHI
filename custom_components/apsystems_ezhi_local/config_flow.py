"""Config flow for APsystems EZHI local API integration."""
import asyncio
from typing import Any

from aiohttp import client_exceptions
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_IP_ADDRESS, CONF_NAME
from homeassistant.core import callback
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
    CONF_CLOUD_REFRESH_TOKEN,
    CONF_CLOUD_SCAN_INTERVAL,
    DEFAULT_CLOUD_SCAN_INTERVAL,
)
from .api import APsystemsEZHI


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
                    vol.Optional(SCAN_INTERVAL_OUTPUT, default=DEFAULT_SCAN_INTERVAL_OUTPUT): int,
                    vol.Optional(SCAN_INTERVAL_ALARM, default=DEFAULT_SCAN_INTERVAL_ALARM): int,
                    # Optional cloud control. Leave empty for a purely local setup.
                    vol.Optional(CONF_CLOUD_ACCESS_TOKEN, default=""): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Optional(CONF_CLOUD_REFRESH_TOKEN, default=""): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    # Range, nicht nur int: eine 0 laesst den Coordinator die Hersteller-Cloud hämmern.
                    vol.Optional(CONF_CLOUD_SCAN_INTERVAL, default=DEFAULT_CLOUD_SCAN_INTERVAL): vol.All(int, vol.Range(min=30)),
                }
            ),
            errors=_errors,
        )

    async def async_step_reauth(
            self,
            entry_data: dict[str, Any],
    ) -> config_entries.FlowResult:
        """The stored cloud refresh_token died — ask for a fresh one."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
            self,
            user_input: dict | None = None,
    ) -> config_entries.FlowResult:
        """Take a new token pair and reload the entry."""
        entry = self._get_reauth_entry()

        if user_input is not None:
            self.hass.config_entries.async_update_entry(
                entry,
                data={
                    **entry.data,
                    CONF_CLOUD_ACCESS_TOKEN: user_input[CONF_CLOUD_ACCESS_TOKEN],
                    CONF_CLOUD_REFRESH_TOKEN: user_input[CONF_CLOUD_REFRESH_TOKEN],
                },
            )
            await self.hass.config_entries.async_reload(entry.entry_id)
            return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CLOUD_ACCESS_TOKEN): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Required(CONF_CLOUD_REFRESH_TOKEN): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
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
                    ): int,
                    vol.Required(
                        SCAN_INTERVAL_ALARM,
                        default=current_alarm_interval,
                    ): int,
                    vol.Optional(
                        CONF_CLOUD_ACCESS_TOKEN,
                        default=self.config_entry.data.get(CONF_CLOUD_ACCESS_TOKEN, ""),
                    ): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
                    vol.Optional(
                        CONF_CLOUD_REFRESH_TOKEN,
                        default=self.config_entry.data.get(CONF_CLOUD_REFRESH_TOKEN, ""),
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
