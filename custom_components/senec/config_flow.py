"""Config flow for senec integration."""
import logging
import voluptuous as vol

from custom_components.senec.pysenec_ha import Senec
from custom_components.senec.pysenec_ha import Inverter
from requests.exceptions import HTTPError, Timeout
from aiohttp import ClientResponseError

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_SCAN_INTERVAL, CONF_TYPE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    DEFAULT_SYSTEM,
    DEFAULT_MODE,
    DEFAULT_HOST,
    DEFAULT_HOST_INVERTER,
    DEFAULT_NAME,
    DEFAULT_NAME_INVERTER,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL_SENECV2,

    SYSTEM_TYPES,
    SYSTYPE_SENECV2,
    SYSTYPE_SENECV4,
    SYSTYPE_INVERTV3,
    SYSTEM_MODES,
    MODE_WEB,

    SETUP_SYS_TYPE,
    SETUP_SYS_MODE,
    CONF_DEV_TYPE,
    CONF_DEV_TYPE_INT,
    CONF_USE_HTTPS,
    CONF_SUPPORT_BDC,
    CONF_DEV_NAME,
    CONF_DEV_SERIAL,
    CONF_DEV_VERSION,
    CONF_SYSTYPE_SENEC,
    CONF_SYSTYPE_SENEC_V2,
    CONF_SYSTYPE_INVERTER,
    CONF_SYSTYPE_WEB
)

_LOGGER = logging.getLogger(__name__)


@callback
def senec_entries(hass: HomeAssistant):
    """Return the hosts already configured."""
    return {entry.data[CONF_HOST] for entry in hass.config_entries.async_entries(DOMAIN)}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for senec."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    def __init__(self):
        """Initialize."""
        self._errors = {}
        self._device_type = ""
        self._device_type_internal = ""
        self._support_bdc = False
        self._device_name = ""
        self._device_serial = ""
        self._device_version = ""
        self._selected_system = None
        self._use_https = False

    def _host_in_configuration_exists(self, host) -> bool:
        """Return True if host exists in configuration."""
        if host in senec_entries(self.hass):
            return True
        return False

    async def _test_connection_senec(self, host, use_https):
        """Check if we can connect to the Senec device."""
        self._errors = {}
        websession = self.hass.helpers.aiohttp_client.async_get_clientsession()
        try:
            senec_client = Senec(host=host, use_https=use_https, websession=websession)
            await senec_client.update_version()
            self._device_type = "SENEC Main-Unit"
            self._device_type_internal = senec_client.device_type_internal
            self._device_name = senec_client.device_type + ' | ' + senec_client.batt_type
            self._device_serial = 'S' + senec_client.device_id
            self._device_version = senec_client.versions
            self._use_https = use_https
            _LOGGER.info(
                "Successfully connect to SENEC.Home (using https? %s) at %s",
                use_https, host,
            )
            return True
        except (OSError, HTTPError, Timeout, ClientResponseError):
            #_LOGGER.exception("Please Report @ https://github.com/marq24/ha-senec-v3/issues:")
            self._errors[CONF_HOST] = "cannot_connect"
            _LOGGER.warning(
                "Could not connect to SENEC.Home (using https? %s) at %s, check host ip address",
                use_https, host,
            )
        return False

    async def _test_connection_inverter(self, host):
        """Check if we can connect to the Senec device."""
        self._errors = {}
        websession = self.hass.helpers.aiohttp_client.async_get_clientsession()
        try:
            inverter_client = Inverter(host=host, websession=websession)
            await inverter_client.update_version()
            self._device_type = "SENEC Inverter Module"
            self._support_bdc = inverter_client.has_bdc
            self._device_name = inverter_client.device_name + ' Netbios: ' + inverter_client.device_netbiosname
            self._device_serial = inverter_client.device_serial
            self._device_version = inverter_client.device_versions
            _LOGGER.info(
                "Successfully connect to build-in Inverter device at %s",
                host,
            )
            return True
        except (OSError, HTTPError, Timeout, ClientResponseError):
            self._errors[CONF_HOST] = "cannot_connect"
            _LOGGER.warning(
                "Could not connect to build-in Inverter device at %s, check host ip address",
                host,
            )
        return False

    async def async_step_user(self, user_input=None):
        self._errors = {}
        if user_input is not None:
            self._selected_system = user_input
            if self._selected_system.get(SETUP_SYS_TYPE) == SYSTYPE_SENECV4:
                return await self.async_step_websetup()
            if self._selected_system.get(SETUP_SYS_TYPE) == SYSTYPE_INVERTV3:
                return await self.async_step_system()
            else:
                # return await self.async_step_mode()
                return await self.async_step_system()
        else:
            user_input = {}
            user_input[SETUP_SYS_TYPE] = DEFAULT_SYSTEM

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(SETUP_SYS_TYPE, default=user_input.get(SETUP_SYS_TYPE, DEFAULT_SYSTEM)):
                        selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=SYSTEM_TYPES,
                                mode=selector.SelectSelectorMode.DROPDOWN,
                                translation_key=SETUP_SYS_TYPE,
                            )
                        )
                }
            ),
            errors=self._errors,
        )

    async def async_step_mode(self, user_input=None):
        self._errors = {}
        if user_input is not None:
            if self._selected_system.get(SETUP_SYS_MODE) == MODE_WEB:
                return await self.async_step_websetup()
            else:
                return await self.async_step_system()
        else:
            user_input = {}
            user_input[SETUP_SYS_MODE] = DEFAULT_MODE

        return self.async_show_form(
            step_id="mode",
            data_schema=vol.Schema(
                {
                    vol.Required(SETUP_SYS_MODE, default=user_input.get(SETUP_SYS_MODE, DEFAULT_MODE)):
                        selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=SYSTEM_MODES,
                                mode=selector.SelectSelectorMode.DROPDOWN,
                                translation_key=SETUP_SYS_MODE,
                            )
                        )
                }
            ),
            errors=self._errors,
        )

    async def async_step_system(self, user_input=None):
        """Step when user initializes a integration."""
        self._errors = {}
        if user_input is not None:
            # set some defaults in case we need to return to the form
            name = user_input.get(CONF_NAME, DEFAULT_NAME)
            host_entry = user_input.get(CONF_HOST, DEFAULT_HOST).lower()
            scan = user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

            # make sure we just handle host/ip's - removing http/https
            if host_entry.startswith("http://"):
                host_entry = host_entry.replace("http://","")
            if host_entry.startswith('https://'):
                host_entry = host_entry.replace("https://","")

            if self._host_in_configuration_exists(host_entry):
                self._errors[CONF_HOST] = "already_configured"
            else:
                # Build-In Inverter stuff
                if self._selected_system is not None and self._selected_system.get(SETUP_SYS_TYPE) == SYSTYPE_INVERTV3:
                    if await self._test_connection_inverter(host_entry):
                        return self.async_create_entry(title=name, data={CONF_NAME: name,
                                                                         CONF_HOST: host_entry,
                                                                         CONF_USE_HTTPS: False,
                                                                         CONF_SCAN_INTERVAL: scan,
                                                                         CONF_TYPE: CONF_SYSTYPE_INVERTER,
                                                                         CONF_DEV_TYPE: self._device_type,
                                                                         CONF_SUPPORT_BDC: self._support_bdc,
                                                                         CONF_DEV_NAME: self._device_name,
                                                                         CONF_DEV_SERIAL: self._device_serial,
                                                                         CONF_DEV_VERSION: self._device_version
                                                                         })
                    else:
                        _LOGGER.error(
                            "Could not connect to build-in Inverter device at %s, check host ip address",
                            host_entry,
                        )

                # SENEC.Home stuff
                else:
                    if await self._test_connection_senec(host_entry, False) or await self._test_connection_senec(host_entry, True):
                        return self.async_create_entry(title=name, data={CONF_NAME: name,
                                                                         CONF_HOST: host_entry,
                                                                         CONF_USE_HTTPS: self._use_https,
                                                                         CONF_SCAN_INTERVAL: scan,
                                                                         CONF_TYPE: CONF_SYSTYPE_SENEC,
                                                                         CONF_DEV_TYPE_INT: self._device_type_internal,
                                                                         CONF_DEV_TYPE: self._device_type,
                                                                         CONF_DEV_NAME: self._device_name,
                                                                         CONF_DEV_SERIAL: self._device_serial,
                                                                         CONF_DEV_VERSION: self._device_version
                                                                         })
                    else:
                        _LOGGER.error(
                            "Could not connect to via http or https to SENEC.Home at %s, check host ip address",
                            host_entry,
                        )
        else:
            user_input = {}

            if self._selected_system is not None and self._selected_system.get(SETUP_SYS_TYPE) == SYSTYPE_INVERTV3:
                user_input[CONF_NAME] = DEFAULT_NAME_INVERTER
                user_input[CONF_HOST] = DEFAULT_HOST_INVERTER
            else:
                user_input[CONF_NAME] = DEFAULT_NAME
                user_input[CONF_HOST] = DEFAULT_HOST

            if self._selected_system is not None and self._selected_system.get(SETUP_SYS_TYPE) == SYSTYPE_SENECV2:
                user_input[CONF_SCAN_INTERVAL] = DEFAULT_SCAN_INTERVAL_SENECV2
            else:
                user_input[CONF_SCAN_INTERVAL] = DEFAULT_SCAN_INTERVAL

        return self.async_show_form(
            step_id="system",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_NAME, default=user_input.get(CONF_NAME, DEFAULT_NAME)
                    ): str,
                    vol.Required(
                        CONF_HOST, default=user_input.get(CONF_HOST, DEFAULT_HOST)
                    ): str,
                    vol.Required(
                        CONF_SCAN_INTERVAL, default=user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                    ): int,
                }
            ),
            errors=self._errors,
        )

    async def async_step_import(self, user_input=None):
        """Import a config entry."""
        host_entry = user_input.get(CONF_HOST, DEFAULT_HOST)

        if self._host_in_configuration_exists(host_entry):
            return self.async_abort(reason="already_configured")
        return await self.async_step_user(user_input)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return SenecOptionsFlowHandler(config_entry)

    async def _show_config_form(self, user_input):  # pylint: disable=unused-argument
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
                    vol.Required(CONF_HOST, default=DEFAULT_HOST): str,
                    vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int,
                }
            ),
            errors=self._errors,
        )


class SenecOptionsFlowHandler(config_entries.OptionsFlow):
    """Config flow options handler for waterkotte_heatpump."""

    def __init__(self, config_entry):
        """Initialize HACS options flow."""
        self.config_entry = config_entry
        if len(dict(config_entry.options)) == 0:
            self.options = dict(config_entry.data)
        else:
            self.options = dict(config_entry.options)

    async def async_step_init(self, user_input=None):  # pylint: disable=unused-argument
        """Manage the options."""
        return await self.async_step_user()

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        if user_input is not None:
            self.options.update(user_input)
            return await self._update_options()

        dataSchema = vol.Schema(
            {
                vol.Required(
                    CONF_NAME, default=self.options.get(CONF_NAME, DEFAULT_NAME),
                ): str,
                vol.Required(
                    CONF_HOST, default=self.options.get(CONF_HOST, DEFAULT_HOST),
                ): str,  # pylint: disable=line-too-long
                vol.Required(
                    CONF_SCAN_INTERVAL, default=self.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): int,  # pylint: disable=line-too-long
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=dataSchema,
        )

    async def _update_options(self):
        """Update config entry options."""
        return self.async_create_entry(data=self.options)
