"""Config flow to configure Mikrotik Router."""

import logging

import voluptuous as vol
from homeassistant.config_entries import (
    CONN_CLASS_LOCAL_POLL,
    ConfigFlow,
    OptionsFlow,
)
from homeassistant.const import (
    CONF_NAME,
    CONF_HOST,
    CONF_PORT,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_SSL,
    CONF_VERIFY_SSL,
    CONF_ZONE,
    STATE_HOME,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    SelectOptionDict,
)

from .const import (
    DOMAIN,
    CONF_TRACK_IFACE_CLIENTS,
    DEFAULT_TRACK_IFACE_CLIENTS,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    CONF_TRACK_HOSTS,
    DEFAULT_TRACK_HOSTS,
    CONF_SENSOR_PORT_TRACKER,
    DEFAULT_SENSOR_PORT_TRACKER,
    CONF_SENSOR_PORT_TRAFFIC,
    DEFAULT_SENSOR_PORT_TRAFFIC,
    CONF_SENSOR_CLIENT_TRAFFIC,
    DEFAULT_SENSOR_CLIENT_TRAFFIC,
    CONF_SENSOR_CLIENT_CAPTIVE,
    DEFAULT_SENSOR_CLIENT_CAPTIVE,
    CONF_SENSOR_SIMPLE_QUEUES,
    DEFAULT_SENSOR_SIMPLE_QUEUES,
    CONF_SENSOR_NAT,
    DEFAULT_SENSOR_NAT,
    CONF_SENSOR_MANGLE,
    DEFAULT_SENSOR_MANGLE,
    CONF_SENSOR_ROUTING_RULES,
    DEFAULT_SENSOR_ROUTING_RULES,
    CONF_SENSOR_FILTER,
    DEFAULT_SENSOR_FILTER,
    CONF_SENSOR_WIREGUARD,
    DEFAULT_SENSOR_WIREGUARD,
    CONF_SENSOR_CONTAINERS,
    DEFAULT_SENSOR_CONTAINERS,
    CONF_SENSOR_KIDCONTROL,
    DEFAULT_SENSOR_KIDCONTROL,
    CONF_SENSOR_PPP,
    DEFAULT_SENSOR_PPP,
    CONF_SENSOR_SCRIPTS,
    DEFAULT_SENSOR_SCRIPTS,
    CONF_SENSOR_ENVIRONMENT,
    DEFAULT_SENSOR_ENVIRONMENT,
    CONF_TRACK_HOSTS_TIMEOUT,
    DEFAULT_TRACK_HOST_TIMEOUT,
    DEFAULT_HOST,
    DEFAULT_USERNAME,
    DEFAULT_PORT,
    DEFAULT_DEVICE_NAME,
    DEFAULT_SSL,
    DEFAULT_VERIFY_SSL,
    DEFAULT_SENSOR_NETWATCH_TRACKER,
    CONF_SENSOR_NETWATCH_TRACKER,
)
from .mikrotikapi import MikrotikAPI

_LOGGER = logging.getLogger(__name__)




def _ssl_mode_from_bools(ssl: bool, verify_ssl: bool) -> str:
    if ssl and verify_ssl:
        return "ssl_verify"
    if ssl:
        return "ssl"
    return "none"


_SENSOR_PRESETS = {
    "minimal": {
        CONF_SENSOR_PORT_TRACKER: True,
        CONF_SENSOR_PORT_TRAFFIC: False,
        CONF_SENSOR_CLIENT_TRAFFIC: False,
        CONF_SENSOR_CLIENT_CAPTIVE: False,
        CONF_SENSOR_SIMPLE_QUEUES: False,
        CONF_SENSOR_NAT: False,
        CONF_SENSOR_MANGLE: False,
        CONF_SENSOR_ROUTING_RULES: False,
        CONF_SENSOR_FILTER: False,
        CONF_SENSOR_WIREGUARD: False,
        CONF_SENSOR_CONTAINERS: False,
        CONF_SENSOR_PPP: False,
        CONF_SENSOR_KIDCONTROL: False,
        CONF_SENSOR_SCRIPTS: False,
        CONF_SENSOR_ENVIRONMENT: False,
        CONF_SENSOR_NETWATCH_TRACKER: False,
        CONF_TRACK_HOSTS: False,
    },
    "recommended": {
        CONF_SENSOR_PORT_TRACKER: True,
        CONF_SENSOR_PORT_TRAFFIC: False,
        CONF_SENSOR_CLIENT_TRAFFIC: False,
        CONF_SENSOR_CLIENT_CAPTIVE: False,
        CONF_SENSOR_SIMPLE_QUEUES: False,
        CONF_SENSOR_NAT: True,
        CONF_SENSOR_MANGLE: True,
        CONF_SENSOR_ROUTING_RULES: False,
        CONF_SENSOR_FILTER: True,
        CONF_SENSOR_WIREGUARD: False,
        CONF_SENSOR_CONTAINERS: False,
        CONF_SENSOR_PPP: False,
        CONF_SENSOR_KIDCONTROL: False,
        CONF_SENSOR_SCRIPTS: True,
        CONF_SENSOR_ENVIRONMENT: False,
        CONF_SENSOR_NETWATCH_TRACKER: True,
        CONF_TRACK_HOSTS: False,
    },
    "full": {
        CONF_SENSOR_PORT_TRACKER: True,
        CONF_SENSOR_PORT_TRAFFIC: True,
        CONF_SENSOR_CLIENT_TRAFFIC: True,
        CONF_SENSOR_CLIENT_CAPTIVE: True,
        CONF_SENSOR_SIMPLE_QUEUES: True,
        CONF_SENSOR_NAT: True,
        CONF_SENSOR_MANGLE: True,
        CONF_SENSOR_ROUTING_RULES: True,
        CONF_SENSOR_FILTER: True,
        CONF_SENSOR_WIREGUARD: True,
        CONF_SENSOR_CONTAINERS: True,
        CONF_SENSOR_PPP: True,
        CONF_SENSOR_KIDCONTROL: True,
        CONF_SENSOR_SCRIPTS: True,
        CONF_SENSOR_ENVIRONMENT: True,
        CONF_SENSOR_NETWATCH_TRACKER: True,
        CONF_TRACK_HOSTS: True,
    },
}


# ---------------------------
#   MikrotikControllerConfigFlow
# ---------------------------
class MikrotikControllerConfigFlow(ConfigFlow, domain=DOMAIN):
    """MikrotikControllerConfigFlow class"""

    VERSION = 2
    CONNECTION_CLASS = CONN_CLASS_LOCAL_POLL

    def __init__(self):
        """Initialize MikrotikControllerConfigFlow."""
        self._user_input = {}
        self._options = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return MikrotikControllerOptionsFlowHandler(config_entry)

    async def async_step_import(self, user_input=None):
        """Occurs when a previously entry setup fails and is re-initiated."""
        return await self.async_step_user(user_input)

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        errors = {}
        if user_input is not None:
            # Convert ssl_mode selector to ssl + verify_ssl booleans
            ssl_mode = user_input.pop("ssl_mode", "none")
            user_input[CONF_SSL] = ssl_mode in ("ssl", "ssl_verify")
            user_input[CONF_VERIFY_SSL] = ssl_mode == "ssl_verify"

            # Test connection
            api = MikrotikAPI(
                host=user_input[CONF_HOST],
                username=user_input[CONF_USERNAME],
                password=user_input[CONF_PASSWORD],
                port=user_input[CONF_PORT],
                use_ssl=user_input[CONF_SSL],
                ssl_verify=user_input[CONF_VERIFY_SSL],
            )
            if not api.connect():
                errors[CONF_HOST] = api.error

            # Save instance
            if not errors:
                await self.async_set_unique_id(user_input[CONF_HOST])
                self._abort_if_unique_id_configured()
                self._user_input = user_input
                return await self.async_step_basic_options()

            return self._show_config_form(user_input=user_input, errors=errors)

        return self._show_config_form(
            user_input={
                CONF_NAME: DEFAULT_DEVICE_NAME,
                CONF_HOST: DEFAULT_HOST,
                CONF_USERNAME: DEFAULT_USERNAME,
                CONF_PASSWORD: DEFAULT_USERNAME,
                CONF_PORT: DEFAULT_PORT,
                CONF_SSL: DEFAULT_SSL,
                CONF_VERIFY_SSL: DEFAULT_VERIFY_SSL,
            },
            errors=errors,
        )

    # ---------------------------
    #   async_step_basic_options
    # ---------------------------
    async def async_step_basic_options(self, user_input=None):
        """Handle basic options step during initial setup."""
        if user_input is not None:
            self._options.update(user_input)
            return await self.async_step_sensor_mode()

        return self.async_show_form(
            step_id="basic_options",
            last_step=False,
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(int, vol.Range(min=10)),
                    vol.Optional(CONF_TRACK_HOSTS_TIMEOUT, default=DEFAULT_TRACK_HOST_TIMEOUT): int,
                    vol.Optional(CONF_ZONE, default=STATE_HOME): str,
                }
            ),
        )

    # ---------------------------
    #   async_step_sensor_mode
    # ---------------------------
    async def async_step_sensor_mode(self, user_input=None):
        """Handle sensor mode selection step during initial setup."""
        if user_input is not None:
            mode = user_input.get("sensor_preset", "recommended")
            if mode == "custom":
                return await self.async_step_sensor_select()
            self._options.update(_SENSOR_PRESETS[mode])
            return self.async_create_entry(
                title=self._user_input[CONF_NAME],
                data=self._user_input,
                options=self._options,
            )

        return self.async_show_form(
            step_id="sensor_mode",
            last_step=False,
            data_schema=vol.Schema(
                {
                    vol.Optional("sensor_preset", default="recommended"): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value="minimal", label="Minimal — port tracker only"),
                                SelectOptionDict(value="recommended", label="Recommended — port tracker, NAT, mangle, filter, scripts, netwatch"),
                                SelectOptionDict(value="full", label="Full — all sensors enabled (warning: can generate hundreds of entities on large networks)"),
                                SelectOptionDict(value="custom", label="Custom — manually select sensors"),
                            ],
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )

    # ---------------------------
    #   async_step_sensor_select
    # ---------------------------
    async def async_step_sensor_select(self, user_input=None):
        """Handle sensor selection step during initial setup."""
        if user_input is not None:
            self._options.update(user_input)
            return self.async_create_entry(
                title=self._user_input[CONF_NAME],
                data=self._user_input,
                options=self._options,
            )

        return self.async_show_form(
            step_id="sensor_select",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_SENSOR_CLIENT_CAPTIVE, default=DEFAULT_SENSOR_CLIENT_CAPTIVE): bool,
                    vol.Optional(CONF_SENSOR_CLIENT_TRAFFIC, default=DEFAULT_SENSOR_CLIENT_TRAFFIC): bool,
                    vol.Optional(CONF_SENSOR_CONTAINERS, default=DEFAULT_SENSOR_CONTAINERS): bool,
                    vol.Optional(CONF_SENSOR_ENVIRONMENT, default=DEFAULT_SENSOR_ENVIRONMENT): bool,
                    vol.Optional(CONF_SENSOR_FILTER, default=DEFAULT_SENSOR_FILTER): bool,
                    vol.Optional(CONF_SENSOR_KIDCONTROL, default=DEFAULT_SENSOR_KIDCONTROL): bool,
                    vol.Optional(CONF_SENSOR_MANGLE, default=DEFAULT_SENSOR_MANGLE): bool,
                    vol.Optional(CONF_SENSOR_NAT, default=DEFAULT_SENSOR_NAT): bool,
                    vol.Optional(CONF_SENSOR_NETWATCH_TRACKER, default=DEFAULT_SENSOR_NETWATCH_TRACKER): bool,
                    vol.Optional(CONF_SENSOR_PORT_TRACKER, default=DEFAULT_SENSOR_PORT_TRACKER): bool,
                    vol.Optional(CONF_SENSOR_PORT_TRAFFIC, default=DEFAULT_SENSOR_PORT_TRAFFIC): bool,
                    vol.Optional(CONF_SENSOR_PPP, default=DEFAULT_SENSOR_PPP): bool,
                    vol.Optional(CONF_SENSOR_ROUTING_RULES, default=DEFAULT_SENSOR_ROUTING_RULES): bool,
                    vol.Optional(CONF_SENSOR_SCRIPTS, default=DEFAULT_SENSOR_SCRIPTS): bool,
                    vol.Optional(CONF_SENSOR_SIMPLE_QUEUES, default=DEFAULT_SENSOR_SIMPLE_QUEUES): bool,
                    vol.Optional(CONF_TRACK_HOSTS, default=DEFAULT_TRACK_HOSTS): bool,
                    vol.Optional(CONF_SENSOR_WIREGUARD, default=DEFAULT_SENSOR_WIREGUARD): bool,
                },
            ),
        )

    # ---------------------------
    #   _show_config_form
    # ---------------------------
    def _show_config_form(self, user_input, errors=None):
        """Show the configuration form to edit data."""
        ssl_mode = _ssl_mode_from_bools(
            user_input.get(CONF_SSL, DEFAULT_SSL),
            user_input.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
        )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=user_input[CONF_NAME]): str,
                    vol.Required(CONF_HOST, default=user_input[CONF_HOST]): str,
                    vol.Required(CONF_USERNAME, default=user_input[CONF_USERNAME]): str,
                    vol.Required(CONF_PASSWORD, default=user_input[CONF_PASSWORD]): str,
                    vol.Optional(CONF_PORT, default=user_input[CONF_PORT]): int,
                    vol.Optional("ssl_mode", default=ssl_mode): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value="none", label="No SSL — unencrypted connection (default, port 8728)"),
                                SelectOptionDict(value="ssl", label="SSL — encrypted, accepts self-signed certificates (port 8729)"),
                                SelectOptionDict(value="ssl_verify", label="SSL with verification — requires a valid CA-signed certificate"),
                            ],
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
            errors=errors,
        )


# ---------------------------
#   MikrotikControllerOptionsFlowHandler
# ---------------------------
class MikrotikControllerOptionsFlowHandler(OptionsFlow):
    """Handle options."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self._config_entry = config_entry
        self.options = dict(config_entry.options)

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        return await self.async_step_basic_options(user_input)

    async def async_step_basic_options(self, user_input=None):
        """Manage the basic options options."""
        if user_input is not None:
            self.options.update(user_input)
            return await self.async_step_sensor_select()

        return self.async_show_form(
            step_id="basic_options",
            last_step=False,
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=self._config_entry.options.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    ): vol.All(int, vol.Range(min=10)),
                    vol.Optional(
                        CONF_TRACK_HOSTS_TIMEOUT,
                        default=self._config_entry.options.get(
                            CONF_TRACK_HOSTS_TIMEOUT, DEFAULT_TRACK_HOST_TIMEOUT
                        ),
                    ): int,
                    vol.Optional(
                        CONF_ZONE,
                        default=self._config_entry.options.get(CONF_ZONE, STATE_HOME),
                    ): str,
                }
            ),
        )

    async def async_step_sensor_select(self, user_input=None):
        """Manage the sensor select options."""
        if user_input is not None:
            self.options.update(user_input)
            return self.async_create_entry(title="", data=self.options)

        return self.async_show_form(
            step_id="sensor_select",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SENSOR_CLIENT_CAPTIVE,
                        default=self._config_entry.options.get(
                            CONF_SENSOR_CLIENT_CAPTIVE, DEFAULT_SENSOR_CLIENT_CAPTIVE
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_SENSOR_CLIENT_TRAFFIC,
                        default=self._config_entry.options.get(
                            CONF_SENSOR_CLIENT_TRAFFIC, DEFAULT_SENSOR_CLIENT_TRAFFIC
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_SENSOR_CONTAINERS,
                        default=self._config_entry.options.get(
                            CONF_SENSOR_CONTAINERS, DEFAULT_SENSOR_CONTAINERS
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_SENSOR_ENVIRONMENT,
                        default=self._config_entry.options.get(
                            CONF_SENSOR_ENVIRONMENT, DEFAULT_SENSOR_ENVIRONMENT
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_SENSOR_FILTER,
                        default=self._config_entry.options.get(
                            CONF_SENSOR_FILTER, DEFAULT_SENSOR_FILTER
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_SENSOR_KIDCONTROL,
                        default=self._config_entry.options.get(
                            CONF_SENSOR_KIDCONTROL, DEFAULT_SENSOR_KIDCONTROL
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_SENSOR_MANGLE,
                        default=self._config_entry.options.get(
                            CONF_SENSOR_MANGLE, DEFAULT_SENSOR_MANGLE
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_SENSOR_NAT,
                        default=self._config_entry.options.get(
                            CONF_SENSOR_NAT, DEFAULT_SENSOR_NAT
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_SENSOR_NETWATCH_TRACKER,
                        default=self._config_entry.options.get(
                            CONF_SENSOR_NETWATCH_TRACKER,
                            DEFAULT_SENSOR_NETWATCH_TRACKER,
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_SENSOR_PORT_TRACKER,
                        default=self._config_entry.options.get(
                            CONF_SENSOR_PORT_TRACKER, DEFAULT_SENSOR_PORT_TRACKER
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_SENSOR_PORT_TRAFFIC,
                        default=self._config_entry.options.get(
                            CONF_SENSOR_PORT_TRAFFIC, DEFAULT_SENSOR_PORT_TRAFFIC
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_SENSOR_PPP,
                        default=self._config_entry.options.get(
                            CONF_SENSOR_PPP, DEFAULT_SENSOR_PPP
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_SENSOR_ROUTING_RULES,
                        default=self._config_entry.options.get(
                            CONF_SENSOR_ROUTING_RULES, DEFAULT_SENSOR_ROUTING_RULES
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_SENSOR_SCRIPTS,
                        default=self._config_entry.options.get(
                            CONF_SENSOR_SCRIPTS, DEFAULT_SENSOR_SCRIPTS
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_SENSOR_SIMPLE_QUEUES,
                        default=self._config_entry.options.get(
                            CONF_SENSOR_SIMPLE_QUEUES, DEFAULT_SENSOR_SIMPLE_QUEUES
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_TRACK_HOSTS,
                        default=self._config_entry.options.get(
                            CONF_TRACK_HOSTS, DEFAULT_TRACK_HOSTS
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_SENSOR_WIREGUARD,
                        default=self._config_entry.options.get(
                            CONF_SENSOR_WIREGUARD, DEFAULT_SENSOR_WIREGUARD
                        ),
                    ): bool,
                },
            ),
        )
