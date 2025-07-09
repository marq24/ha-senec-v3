"""Config flow for senec integration."""
import logging

import voluptuous as vol
from aiohttp import ClientResponseError
from requests.exceptions import HTTPError, Timeout

from custom_components.senec.pysenec_ha import Inverter
from custom_components.senec.pysenec_ha import Senec, MySenecWebPortal
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_SCAN_INTERVAL, CONF_TYPE, CONF_USERNAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.util import slugify
from .const import (
    DOMAIN,
    DEFAULT_SYSTEM,
    DEFAULT_HOST,
    DEFAULT_HOST_INVERTER,
    DEFAULT_NAME,
    DEFAULT_NAME_INVERTER,
    DEFAULT_NAME_WEB,
    DEFAULT_USERNAME,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL_SENECV2,
    DEFAULT_SCAN_INTERVAL_WEB,
    DEFAULT_SCAN_INTERVAL_WEB_SENECV4,

    SYSTEM_TYPES,
    SYSTYPE_SENECV2,
    SYSTYPE_SENECV4,
    SYSTYPE_WEBAPI,
    SYSTYPE_INVERTV3,
    MASTER_PLANT_NUMBERS,

    SYSTYPE_NAME_SENEC,
    SYSTYPE_NAME_INVERTER,
    SYSTYPE_NAME_WEBAPI,

    SETUP_SYS_TYPE,
    CONF_DEV_TYPE,
    CONF_DEV_TYPE_INT,
    CONF_USE_HTTPS,
    CONF_SUPPORT_BDC,
    CONF_DEV_MODEL,
    CONF_DEV_SERIAL,
    CONF_DEV_VERSION,
    CONF_SYSTYPE_SENEC,
    CONF_SYSTYPE_INVERTER,
    CONF_SYSTYPE_WEB,
    CONF_DEV_MASTER_NUM,
    CONF_IGNORE_SYSTEM_STATE,
    CONF_APP_TOKEN,
    CONF_APP_SYSTEMID,
    CONF_APP_WALLBOX_COUNT,
)

_LOGGER = logging.getLogger(__name__)


@callback
def senec_host_entries(hass: HomeAssistant):
    """Return the hosts already configured."""
    conf_hosts = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        if hasattr(entry, 'options') and CONF_HOST in entry.options:
            conf_hosts.append(entry.options[CONF_HOST])
        else:
            conf_hosts.append(entry.data[CONF_HOST])
    return conf_hosts


@staticmethod
def host_in_configuration_exists(hass: HomeAssistant, host: str) -> bool:
    """Return True if host exists in configuration."""
    if host in senec_host_entries(hass):
        return True
    return False


@callback
def senec_title_entries(hass: HomeAssistant):
    """Return the hosts already configured."""
    conf_titles = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        conf_titles.append(slugify(entry.title))
    return conf_titles


@staticmethod
def title_in_configuration_exists(hass: HomeAssistant, a_title: str) -> bool:
    """Return True if name exists in configuration."""
    if slugify(a_title) in senec_title_entries(hass):
        return True
    return False


class SenecConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for senec."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    def __init__(self):
        """Initialize."""
        self._errors = {}
        self._selected_system = None

        self._use_https = False
        self._device_type_internal = ""
        self._support_bdc = False
        self._device_master_plant_number = -1

        self._device_type = ""
        self._device_model = ""
        self._device_serial = ""
        self._device_version = ""
        self._stats_available = False

        self._app_token = None
        self._app_master_plant_id = None
        self._app_wallbox_num_max = None

    # async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
    #     entry_data = self._get_reconfigure_entry().data
    #     self._default_name = entry_data.get(CONF_NAME, DEFAULT_NAME)
    #     self._default_host = entry_data.get(CONF_HOST, DEFAULT_HOST)
    #     self._default_pwd = entry_data.get(CONF_PASSWORD, DEFAULT_PWD)
    #     self._default_scan_interval = entry_data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    #     self._default_node_number = entry_data.get(CONF_NODE_NUMBER, DEFAULT_NODE_NUMBER)
    #     return await self.async_step_user()

    async def _test_connection_senec(self, host, use_https):
        """Check if we can connect to the Senec device."""
        self._errors = {}
        try:
            senec_client = Senec(host=host, use_https=use_https, lala_session=async_create_clientsession(self.hass, verify_ssl=False))
            await senec_client.update_version()
            await senec_client.update()
            self._use_https = use_https
            self._device_type_internal = senec_client.device_type_internal

            # these values will also read with every restart...
            self._device_type = SYSTYPE_NAME_SENEC
            self._device_model = senec_client.device_type + ' | ' + senec_client.batt_type
            self._device_serial = 'S' + senec_client.device_id
            self._device_version = senec_client.versions
            self._stats_available = senec_client.grid_total_export is not None

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
        try:
            inverter_client = Inverter(host=host, inv_session=async_get_clientsession(self.hass))
            await inverter_client.update_version()
            self._support_bdc = inverter_client.has_bdc

            # these values will also read with every restart...
            self._device_type = SYSTYPE_NAME_INVERTER
            self._device_model = inverter_client.device_name + ' Netbios: ' + inverter_client.device_netbiosname
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

    async def _test_connection_webapi(self, user: str, pwd: str, master_plant: int):
        """Check if we can connect to the Senec WEB."""
        self._errors = {}
        web_session = async_create_clientsession(self.hass, auto_cleanup=False)
        try:
            senec_web_client = MySenecWebPortal(user=user, pwd=pwd, web_session=web_session,
                                                master_plant_number=master_plant)
            await senec_web_client.app_authenticate(retry=False, do_update=False)
            if senec_web_client._app_is_authenticated:
                await senec_web_client.app_update_context()
                self._device_master_plant_number = senec_web_client.masterPlantNumber

                await senec_web_client.app_update_tech_data()
                if senec_web_client.product_name is None:
                    prod_name = "UNKNOWN_PROD_NAME"
                else:
                    prod_name = senec_web_client.product_name

                if senec_web_client.senec_num is None:
                    senec_num = "UNKNOWN_SENEC_NUM"
                else:
                    senec_num = senec_web_client.senec_num

                if senec_web_client.serial_number is None:
                    serial_num = "UNKNOWN_SERIAL_NUM"
                else:
                    serial_num = senec_web_client.serial_number

                # these values will also read with every restart...
                self._device_type = SYSTYPE_NAME_WEBAPI
                self._device_model =  prod_name + ' | SENEC.Num: ' + senec_num
                self._device_serial = serial_num
                self._app_token = senec_web_client._app_token
                self._app_master_plant_id = senec_web_client._app_master_plant_id
                self._app_wallbox_num_max = senec_web_client._app_wallbox_num_max
                self._device_version = senec_web_client.versions

                _LOGGER.info(f"Successfully connect to mein-senec.de and APP-API with '{user}'")
                return True
            else:
                self._errors[CONF_USERNAME] = "login_failed"
                self._errors[CONF_PASSWORD] = "login_failed"
                _LOGGER.warning(
                    f"Could not connect to mein-senec.de with '{user}', check credentials (! _is_authenticated)")
        except (OSError, HTTPError, Timeout, ClientResponseError):
            self._errors[CONF_USERNAME] = "login_failed"
            self._errors[CONF_PASSWORD] = "login_failed"
            _LOGGER.warning(f"Could not connect to mein-senec.de with '{user}', check credentials (exception)")
        finally:
            web_session.detach()
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

            if host_in_configuration_exists(self.hass, host_entry):
                self._errors[CONF_HOST] = "already_configured"
            if title_in_configuration_exists(self.hass, name):
                self._errors[CONF_NAME] = "already_configured"
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
                                                                         CONF_DEV_MODEL: self._device_model,
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
                                  CONF_DEV_TYPE_INT: self._device_type_internal,
                                  CONF_DEV_TYPE: self._device_type,
                                  CONF_DEV_MODEL: self._device_model,
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
            name = user_input.get(CONF_NAME, DEFAULT_NAME_WEB)
            # this is an extremely lousy check!
            if "ome V4 " in self._device_type:
                scan = DEFAULT_SCAN_INTERVAL_WEB_SENECV4
            else:
                scan = DEFAULT_SCAN_INTERVAL_WEB
            user = user_input.get(CONF_USERNAME, DEFAULT_USERNAME)
            pwd = user_input.get(CONF_PASSWORD, "")

            # when the user has multiple masters, the auto-detect does
            # not work - so we allow the specification of the AnlagenNummer
            master_plant_val = user_input.get(CONF_DEV_MASTER_NUM, "auto")
            if master_plant_val == 'auto':
                already_exist_ident = user
                master_plant_num = -1
            else:
                already_exist_ident = f"{user}_{master_plant_val}"
                master_plant_num = int(master_plant_val)

            if host_in_configuration_exists(self.hass, already_exist_ident):
                self._errors[CONF_USERNAME] = "already_configured"
            else:
                if await self._test_connection_webapi(user, pwd, master_plant_num):
                    data = {CONF_NAME: name,
                            CONF_HOST: user,
                            CONF_USERNAME: user,
                            CONF_PASSWORD: pwd,
                            CONF_SCAN_INTERVAL: scan,
                            CONF_TYPE: CONF_SYSTYPE_WEB,
                            CONF_DEV_TYPE_INT: self._device_type_internal,
                            CONF_DEV_TYPE: self._device_type,
                            CONF_DEV_MODEL: self._device_model,
                            CONF_DEV_SERIAL: self._device_serial,
                            CONF_DEV_VERSION: self._device_version,
                            CONF_DEV_MASTER_NUM: self._device_master_plant_number
                            }

                    if self._app_token is not None and \
                            self._app_master_plant_id is not None and \
                            self._app_wallbox_num_max is not None:
                        data[CONF_APP_TOKEN] = self._app_token
                        data[CONF_APP_SYSTEMID] = self._app_master_plant_id
                        data[CONF_APP_WALLBOX_COUNT] = self._app_wallbox_num_max

                    return self.async_create_entry(title=name, data=data)
                else:
                    _LOGGER.error("Could not connect to mein-senec.de with User '%s', check credentials", user)
                    self._errors[CONF_USERNAME]
                    self._errors[CONF_PASSWORD]

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
                    ): str,
                    vol.Required(CONF_DEV_MASTER_NUM, default=user_input.get(CONF_DEV_MASTER_NUM, "auto")):
                        selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=MASTER_PLANT_NUMBERS,
                                mode=selector.SelectSelectorMode.DROPDOWN,
                                translation_key=CONF_DEV_MASTER_NUM,
                            )
                        )
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


class SenecOptionsFlowHandler(config_entries.OptionsFlow):
    """Config flow options handler for waterkotte_heatpump."""

    def __init__(self, config_entry):
        """Initialize HACS options flow."""
        self.data = dict(config_entry.data);
        if len(dict(config_entry.options)) == 0:
            self.options = {}
        else:
            self.options = dict(config_entry.options)

    async def async_step_init(self, user_input=None):  # pylint: disable=unused-argument
        """Manage the options."""
        if CONF_TYPE in self.data and self.data[CONF_TYPE] == CONF_SYSTYPE_WEB:
            return await self.async_step_websetup()
        else:
            return await self.async_step_system()

    async def async_step_system(self, user_input=None):
        """Handle a flow initialized by the user."""
        self._errors = {}
        if user_input is not None:

            # verify the entered host...
            host_entry = user_input.get(CONF_HOST, DEFAULT_HOST).lower()
            # make sure we just handle host/ip's - removing http/https
            if host_entry.startswith("http://"):
                host_entry = host_entry.replace("http://", "")
            if host_entry.startswith('https://'):
                host_entry = host_entry.replace("https://", "")

            user_input[CONF_HOST] = host_entry

            self.options.update(user_input)
            if self.data.get(CONF_HOST) != self.options.get(CONF_HOST):
                # ok looks like the host has been changed... we need to do some things...
                if host_in_configuration_exists(self.hass, host_entry):
                    self._errors[CONF_HOST] = "already_configured"
                else:
                    return self._update_options()
            else:
                # host did not change...
                return self._update_options()

        if CONF_TYPE in self.data and self.data[CONF_TYPE] == CONF_SYSTYPE_INVERTER:
            dataSchema = vol.Schema(
                {
                    vol.Required(
                        CONF_NAME, default=self.options.get(CONF_NAME, self.data.get(CONF_NAME, DEFAULT_NAME)),
                    ): str,
                    vol.Required(
                        CONF_HOST, default=self.options.get(CONF_HOST, self.data.get(CONF_HOST, DEFAULT_HOST)),
                    ): str,  # pylint: disable=line-too-long
                    vol.Required(
                        CONF_SCAN_INTERVAL, default=self.options.get(CONF_SCAN_INTERVAL,
                                                                     self.data.get(CONF_SCAN_INTERVAL,
                                                                                   DEFAULT_SCAN_INTERVAL)),
                    ): int
                }
            )
        else:
            dataSchema = vol.Schema(
                {
                    vol.Required(
                        CONF_NAME, default=self.options.get(CONF_NAME, self.data.get(CONF_NAME, DEFAULT_NAME)),
                    ): str,
                    vol.Required(
                        CONF_HOST, default=self.options.get(CONF_HOST, self.data.get(CONF_HOST, DEFAULT_HOST)),
                    ): str,  # pylint: disable=line-too-long
                    vol.Required(
                        CONF_SCAN_INTERVAL, default=self.options.get(CONF_SCAN_INTERVAL,
                                                                     self.data.get(CONF_SCAN_INTERVAL,
                                                                                   DEFAULT_SCAN_INTERVAL)),
                    ): int,  # pylint: disable=line-too-long
                    vol.Required(
                        CONF_IGNORE_SYSTEM_STATE, default=self.options.get(CONF_IGNORE_SYSTEM_STATE,
                                                                           self.data.get(CONF_IGNORE_SYSTEM_STATE,
                                                                                         False)),
                    ): bool,  # pylint: disable=line-too-long
                }
            )
        return self.async_show_form(
            step_id="system",
            data_schema=dataSchema,
        )

    async def async_step_websetup(self, user_input=None):
        """Handle a flow initialized by the user."""
        if user_input is not None:
            # we need to check the scan_interval (configured by the user)... we hard code a limit of 1 minute for all
            # SENEC.Home V2 & V3 Systems - only V4 can set it to 30 seconds
            if "ome V4" in self.data.get(CONF_DEV_TYPE):
                user_input[CONF_SCAN_INTERVAL] = max(user_input.get(CONF_SCAN_INTERVAL), 30)
            else:
                user_input[CONF_SCAN_INTERVAL] = max(user_input.get(CONF_SCAN_INTERVAL), 60)
            self.options.update(user_input)
            return self._update_options()

        dataSchema = vol.Schema(
            {
                vol.Required(
                    CONF_NAME, default=self.options.get(CONF_NAME, self.data.get(CONF_NAME, DEFAULT_NAME_WEB))
                ): str,
                vol.Required(
                    CONF_USERNAME,
                    default=self.options.get(CONF_USERNAME, self.data.get(CONF_USERNAME, DEFAULT_USERNAME))
                ): str,
                vol.Required(
                    CONF_PASSWORD, default=self.options.get(CONF_PASSWORD, self.data.get(CONF_PASSWORD, ""))
                ): str,
                vol.Required(
                    CONF_SCAN_INTERVAL, default=self.options.get(CONF_SCAN_INTERVAL, self.data.get(CONF_SCAN_INTERVAL,
                                                                                                   DEFAULT_SCAN_INTERVAL)),
                ): int  # pylint: disable=line-too-long
            }
        )
        return self.async_show_form(
            step_id="websetup",
            data_schema=dataSchema,
        )

    def _update_options(self):
        """Update config entry options."""
        return self.async_create_entry(data=self.options)
