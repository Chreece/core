"""Snapcast config flow for the custom test integration."""

import socket
from typing import override

import probatio
import snapcast.control
from snapcast.control.server import CONTROL_PORT

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT

DOMAIN = "snapcast"
DEFAULT_TITLE = "Snapcast"

SNAPCAST_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_HOST): str,
        probatio.Required(CONF_PORT, default=CONTROL_PORT): int,
    }
)


class SnapcastConfigFlow(ConfigFlow, domain=DOMAIN):
    """Snapcast config flow."""

    @override
    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        """Handle first step."""
        errors = {}
        if user_input:
            self._async_abort_entries_match(user_input)
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]

            try:
                client = await snapcast.control.create_server(
                    self.hass.loop, host, port, reconnect=False
                )
            except socket.gaierror:
                errors["base"] = "invalid_host"
            except OSError:
                errors["base"] = "cannot_connect"
            else:
                client.stop()
                return self.async_create_entry(title=DEFAULT_TITLE, data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=SNAPCAST_SCHEMA, errors=errors
        )
