"""Config flow for senec integration."""
import logging
import voluptuous as vol
from homeassistant.data_entry_flow import FlowResultType

from custom_components.senec.pysenec_ha import Senec, MySenecWebPortal
from custom_components.senec.pysenec_ha import Inverter
from requests.exceptions import HTTPError, Timeout
from aiohttp import ClientResponseError

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_SCAN_INTERVAL, CONF_TYPE, CONF_USERNAME, CONF_PASSWORD
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
    DEFAULT_NAME_WEB,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL_SENECV2,

    SYSTEM_TYPES,
    SYSTYPE_SENECV2,
    SYSTYPE_SENECV4,
    SYSTYPE_WEBAPI,
    SYSTYPE_INVERTV3,
    SYSTEM_MODES,
    MODE_WEB,

    SETUP_SYS_TYPE,
    SETUP_SYS_MODE,
    CONF_DEV_TYPE,
    CONF_DEV_TYPE_INT,
    CONF_USE_HTTPS,
    CONF_SUPPORT_STATS,
    CONF_SUPPORT_BDC,
    CONF_DEV_NAME,
    CONF_DEV_SERIAL,
    CONF_DEV_VERSION,
    CONF_SYSTYPE_SENEC,
    CONF_SYSTYPE_SENEC_V2,
    CONF_SYSTYPE_INVERTER,
    CONF_SYSTYPE_WEB, DEFAULT_SCAN_INTERVAL_WEB, DEFAULT_USERNAME
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
            self._stats_available = senec_client.grid_total_export is not None

            # just for local testing...
            #self._stats_available = False

            _LOGGER.info(
                "Successfully connect to SENEC.Home (using https? %s) at %s",
                use_https, host,
            )
            return True
        except (OSError, HTTPError, Timeout, ClientResponseError):
            # _LOGGER.exception("Please Report @ https://github.com/marq24/ha-senec-v3/issues:")
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

    async def _test_connection_webapi(self, user, pwd):
        """Check if we can connect to the Senec WEB."""
        self._errors = {}
        websession = self.hass.helpers.aiohttp_client.async_get_clientsession()
        try:
            senec_web_client = MySenecWebPortal(user=user, pwd=pwd, websession=websession)
            await senec_web_client.authenticate(doUpdate=True)
            await senec_web_client.update_context()

            # TODO: fetch VERSION and other Info from WebApi...
            self._device_type = "SENEC WebAPI"
            # self._device_type_internal = senec_client.device_type_internal
            self._device_type = senec_web_client.product_name
            self._device_name = 'SENEC.Num: ' + senec_web_client.senec_num
            self._device_serial = senec_web_client.serial_number
            self._device_version = senec_web_client.firmwareVersion
            _LOGGER.info("Successfully connect to mein-senec.de with '%s'", user)
            return True
        except (OSError, HTTPError, Timeout, ClientResponseError):
            self._errors[CONF_USERNAME] = "login_failed"
            _LOGGER.warning("Could not connect to mein-senec.de with '%s', check credentials", user)
        return False

    async def async_step_user(self, user_input=None):
        self._errors = {}
        if user_input is not None:
            self._selected_system = user_input

            # SenecV4 - WebONLY Option...
            if self._selected_system.get(SETUP_SYS_TYPE) == SYSTYPE_SENECV4 or self._selected_system.get(
                    SETUP_SYS_TYPE) == SYSTYPE_WEBAPI:
                return await self.async_step_websetup()

            # Inverter option...
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
            last_step=False,
            errors=self._errors,
        )

    # async def async_step_mode(self, user_input=None):
    #     self._errors = {}
    #     if user_input is not None:
    #         if self._selected_system.get(SETUP_SYS_MODE) == MODE_WEB:
    #             return await self.async_step_websetup()
    #         else:
    #             return await self.async_step_system()
    #     else:
    #         user_input = {}
    #         user_input[SETUP_SYS_MODE] = DEFAULT_MODE
    #
    #     return self.async_show_form(
    #         step_id="mode",
    #         data_schema=vol.Schema(
    #             {
    #                 vol.Required(SETUP_SYS_MODE, default=user_input.get(SETUP_SYS_MODE, DEFAULT_MODE)):
    #                     selector.SelectSelector(
    #                         selector.SelectSelectorConfig(
    #                             options=SYSTEM_MODES,
    #                             mode=selector.SelectSelectorMode.DROPDOWN,
    #                             translation_key=SETUP_SYS_MODE,
    #                         )
    #                     )
    #             }
    #         ),
    #         errors=self._errors,
    #     )

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
                host_entry = host_entry.replace("http://", "")
            if host_entry.startswith('https://'):
                host_entry = host_entry.replace("https://", "")

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
                    if await self._test_connection_senec(host_entry, False) or await self._test_connection_senec(
                            host_entry, True):

                        a_data = {CONF_NAME: name,
                                  CONF_HOST: host_entry,
                                  CONF_USE_HTTPS: self._use_https,
                                  CONF_SCAN_INTERVAL: scan,
                                  CONF_TYPE: CONF_SYSTYPE_SENEC,
                                  CONF_SUPPORT_STATS: self._stats_available,
                                  CONF_DEV_TYPE_INT: self._device_type_internal,
                                  CONF_DEV_TYPE: self._device_type,
                                  CONF_DEV_NAME: self._device_name,
                                  CONF_DEV_SERIAL: self._device_serial,
                                  CONF_DEV_VERSION: self._device_version
                                  }

                        if not self._stats_available:
                            # we have to show the user, that he should add also WEB-API
                            _LOGGER.warning("Need WEB-API for full data...")
                            self._xdata = a_data;
                            self._xname = name;
                            return self.async_show_form(
                                step_id="optional_websetup_required_info",
                                last_step=False,
                                errors=self._errors
                            )
                        else:
                            return self.async_create_entry(title=name, data=a_data)

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
            last_step=True,
            errors=self._errors,
        )

    async def async_step_websetup(self, user_input=None):
        self._errors = {}
        if user_input is not None:
            # set some defaults in case we need to return to the form
            name = user_input.get(CONF_NAME, DEFAULT_NAME_WEB)
            scan = DEFAULT_SCAN_INTERVAL_WEB
            user = user_input.get(CONF_USERNAME, DEFAULT_USERNAME)
            pwd = user_input.get(CONF_PASSWORD, "")

            if self._host_in_configuration_exists(user):
                self._errors[CONF_USERNAME] = "already_configured"
            else:
                if await self._test_connection_webapi(user, pwd):
                    return self.async_create_entry(title=name, data={CONF_NAME: name,
                                                                     CONF_HOST: user,
                                                                     CONF_USERNAME: user,
                                                                     CONF_PASSWORD: pwd,
                                                                     CONF_SCAN_INTERVAL: scan,
                                                                     CONF_TYPE: CONF_SYSTYPE_WEB,
                                                                     CONF_DEV_TYPE_INT: self._device_type_internal,
                                                                     CONF_DEV_TYPE: self._device_type,
                                                                     CONF_DEV_NAME: self._device_name,
                                                                     CONF_DEV_SERIAL: self._device_serial,
                                                                     CONF_DEV_VERSION: self._device_version
                                                                     })
                else:
                    _LOGGER.error("Could not connect to mein-senec.de with User '%s', check credentials", user)
                    self._errors[CONF_USERNAME]

        else:
            user_input = {}
            user_input[CONF_NAME] = DEFAULT_NAME_WEB
            user_input[CONF_USERNAME] = DEFAULT_USERNAME
            user_input[CONF_PASSWORD] = ""

        return self.async_show_form(
            step_id="websetup",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_NAME, default=user_input.get(CONF_NAME, DEFAULT_NAME_WEB)
                    ): str,
                    vol.Required(
                        CONF_USERNAME, default=user_input.get(CONF_USERNAME, DEFAULT_USERNAME)
                    ): str,
                    vol.Required(
                        CONF_PASSWORD, default=user_input.get(CONF_PASSWORD, "")
                    ): str
                }
            ),
            last_step=True,
            errors=self._errors,
        )

    async def async_step_optional_websetup_required_info(self, user_input=None):
        return self.async_create_entry(title=self._xname, data=self._xdata)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return SenecOptionsFlowHandler(config_entry)

    # async def _show_config_form(self, user_input):  # pylint: disable=unused-argument
    #     return self.async_show_form(
    #         step_id="user",
    #         data_schema=vol.Schema(
    #             {
    #                 vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
    #                 vol.Required(CONF_HOST, default=DEFAULT_HOST): str,
    #                 vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int,
    #             }
    #         ),
    #         errors=self._errors,
    #     )


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
        if CONF_TYPE in self.options and self.options[CONF_TYPE] == CONF_SYSTYPE_WEB:
            return await self.async_step_websetup()
        else:
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

    async def async_step_websetup(self, user_input=None):
        """Handle a flow initialized by the user."""
        if user_input is not None:
            self.options.update(user_input)
            return await self._update_options()

        dataSchema = vol.Schema(
            {
                vol.Required(
                    CONF_NAME, default=self.options.get(CONF_NAME, DEFAULT_NAME_WEB)
                ): str,
                vol.Required(
                    CONF_USERNAME, default=self.options.get(CONF_USERNAME, DEFAULT_USERNAME)
                ): str,
                vol.Required(
                    CONF_PASSWORD, default=self.options.get(CONF_PASSWORD, "")
                ): str
            }
        )
        return self.async_show_form(
            step_id="websetup",
            data_schema=dataSchema,
        )

    async def _update_options(self):
        """Update config entry options."""
        return self.async_create_entry(data=self.options)
