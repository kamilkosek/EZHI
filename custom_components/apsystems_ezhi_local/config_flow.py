"""Config flow for APsystems EZHI local API integration."""
import asyncio
from typing import Any

from aiohttp import client_exceptions
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_IP_ADDRESS, CONF_NAME
from homeassistant.core import callback

from .const import (
    DOMAIN,
    LOGGER,
    SCAN_INTERVAL_OUTPUT,
    SCAN_INTERVAL_ALARM,
    DEFAULT_SCAN_INTERVAL_OUTPUT,
    DEFAULT_SCAN_INTERVAL_ALARM,
    UPDATE_INTERVAL,
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
                }
            ),
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
            }
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )
            # Reload the integration to apply new intervals
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            return self.async_create_entry(title="", data=user_input)

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
                }
            ),
        )
