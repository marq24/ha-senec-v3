"""Config flow for senec integration."""
import asyncio
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, unquote, parse_qs

import voluptuous as vol
from aiohttp import ClientResponseError
from homeassistant import config_entries, data_entry_flow
from homeassistant.config_entries import ConfigFlowResult, SOURCE_RECONFIGURE
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_SCAN_INTERVAL, CONF_TYPE, CONF_USERNAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.storage import STORAGE_DIR
from homeassistant.util import slugify
from requests.exceptions import HTTPError, Timeout

from custom_components.senec.pysenec_ha import InverterLocal
from custom_components.senec.pysenec_ha import SenecLocal, SenecOnline
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
    DEFAULT_MIN_SCAN_INTERVAL,
    DEFAULT_MIN_SCAN_INTERVAL_WEB,

    SYSTEM_TYPES,
    SYSTYPE_SENECV2,
    SYSTYPE_SENECV3,
    SYSTYPE_SENECV4,
    SYSTYPE_WEBAPI,
    SYSTYPE_INVERTV3,
    MASTER_PLANT_NUMBERS,

    SYSTYPE_NAME_SENEC,
    SYSTYPE_NAME_INVERTER,
    SYSTYPE_NAME_WEBAPI,

    SETUP_SYS_TYPE,
    CONF_TOTP,
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
    CONFIG_VERSION,
    CONFIG_MINOR_VERSION
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

    VERSION = CONFIG_VERSION
    MINOR_VERSION = CONFIG_MINOR_VERSION

    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    def __init__(self):
        self._default_name = None
        self._default_interval = None
        # local/inverter defaults
        self._default_host = None
        self._default_ignore_system_state = False
        # web-api defaults
        self._default_user = None
        self._default_pwd = None
        self._default_totp = None
        self._default_master_plant_number = None

        """Initialize."""
        self._errors = {}
        self._selected_system = None

        self._use_https = False
        self._device_type_internal = ""
        self._support_bdc = False
        self._app_master_plant_number = -1

        self._device_type = ""
        self._device_model = ""
        self._device_serial = ""
        self._device_version = ""
        self._stats_available = False

        # just a container to transport the user-input data to the next step...
        self._xdata = None
        self._xname = None

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry_data = self._get_reconfigure_entry().data
        self._selected_system = entry_data.get(CONF_TYPE, None)
        if self._selected_system is None:
            _LOGGER.error("Reconfigure called without system type, this should not happen!")
            return self.async_abort(reason="reconfigure_error")

        if self._selected_system in [CONF_SYSTYPE_INVERTER, CONF_SYSTYPE_SENEC]:
            self._default_name      = entry_data[CONF_NAME]
            self._default_interval  = entry_data[CONF_SCAN_INTERVAL]
            self._default_host      = entry_data[CONF_HOST]
            self._default_ignore_system_state = entry_data.get(CONF_IGNORE_SYSTEM_STATE, False)
            return await self.async_step_localsystem()

        elif self._selected_system == CONF_SYSTYPE_WEB:
            self._default_name      = entry_data[CONF_NAME]
            self._default_interval  = entry_data[CONF_SCAN_INTERVAL]
            self._default_user      = entry_data[CONF_USERNAME]
            self._default_pwd       = entry_data[CONF_PASSWORD]
            self._default_totp      = entry_data.get(CONF_TOTP, "") # TOTP can be empty!!!
            self._default_master_plant_number = entry_data[CONF_DEV_MASTER_NUM]
            return await self.async_step_websetup()

        return self.async_abort(reason="reconfigure_error")

    async def _test_connection_senec_local(self, host, use_https):
        """Check if we can connect to the Senec device."""
        self._errors = {}
        try:
            senec_client = SenecLocal(host=host, use_https=use_https, lala_session=async_create_clientsession(self.hass, verify_ssl=False))
            await senec_client.update_version()
            await senec_client.update()
            self._use_https = use_https
            self._device_type_internal = senec_client.device_type_internal

            # these values will also read with every restart...
            self._device_type = SYSTYPE_NAME_SENEC
            self._device_model = f"{senec_client.device_type} | {senec_client.batt_type}"
            self._device_serial = f"S{senec_client.device_id}"
            self._device_version = senec_client.versions
            self._stats_available = senec_client.grid_total_export is not None

            _LOGGER.info(f"Successfully connect to SENEC.Home (using https? {use_https}) at {host}")
            return True
        except (OSError, HTTPError, Timeout, ClientResponseError):
            # _LOGGER.exception("Please Report @ https://github.com/marq24/ha-senec-v3/issues:")
            self._errors[CONF_HOST] = "cannot_connect"
            _LOGGER.warning(f"Could not connect to SENEC.Home (using https? {use_https}) at {host}, check host ip address")
        return False

    async def _test_connection_inverter(self, host):
        """Check if we can connect to the Senec device."""
        self._errors = {}
        try:
            inverter_client = InverterLocal(host=host, inv_session=async_create_clientsession(self.hass))
            await inverter_client.update_version()
            self._support_bdc = inverter_client.has_bdc

            # these values will also read with every restart...
            self._device_type = SYSTYPE_NAME_INVERTER
            self._device_model = f"{inverter_client.device_name} Netbios: {inverter_client.device_netbiosname}"
            self._device_serial = inverter_client.device_serial
            self._device_version = inverter_client.device_versions

            _LOGGER.info(f"Successfully connect to build-in Inverter device at {host}")
            return True
        except (OSError, HTTPError, Timeout, ClientResponseError):
            self._errors[CONF_HOST] = "cannot_connect"
            _LOGGER.warning(f"Could not connect to build-in Inverter device at {host}, check host ip address")
        return False

    async def _test_connection_senec_online(self, user: str, pwd: str, totp_secret: str, user_master_plant: int):
        """Check if we can connect to the Senec WEB."""
        self._errors = {}
        web_session = async_create_clientsession(self.hass, auto_cleanup=False)
        try:
            senec_online = SenecOnline(user=user, pwd=pwd, totp=totp_secret, web_session=web_session,
                                       app_master_plant_number=user_master_plant,
                                       storage_path=Path(self.hass.config.config_dir).joinpath(STORAGE_DIR))

            # we check, if we can authenticate with the APP-API
            await senec_online.app_authenticate()
            if senec_online._app_is_authenticated:
                # the 'app_authenticate()' call will also update all the required meta data
                # so we don't have the need for additional calls... and also our properties
                # are already stored in the token file!

                # well - we need the system details... *sigh*
                await senec_online.app_get_system_details()

                # the 'app_authenticate()' have also probably corrected the
                # master plant number... so we use it..
                self._app_master_plant_number = senec_online.appMasterPlantNumber

                # collecting other properties...
                if senec_online.product_name is None:
                    prod_name = "UNKNOWN_PROD_NAME"
                else:
                    prod_name = senec_online.product_name

                if senec_online.senec_num is None:
                    senec_num = "UNKNOWN_SENEC_NUM"
                else:
                    senec_num = senec_online.senec_num

                if senec_online.serial_number is None:
                    serial_num = "UNKNOWN_SERIAL_NUM"
                else:
                    serial_num = senec_online.serial_number

                # these values will also read with every restart...
                self._device_type = SYSTYPE_NAME_WEBAPI
                self._device_model = f"{prod_name} | SENEC.Num: {senec_num}"
                self._device_serial = serial_num
                self._device_version = senec_online.versions

                loc_device_info = {
                    "device_type": self._device_type,
                    "device_model": self._device_model,
                    "device_serial": self._device_serial,
                    "device_version": self._device_version
                }
                _LOGGER.info(f"Successfully connect to mein-senec.de and APP-API with '{user}' -> {loc_device_info}")
                return True
            else:
                self._errors[CONF_USERNAME] = "login_failed"
                self._errors[CONF_PASSWORD] = "login_failed"
                _LOGGER.warning(f"Could not connect to mein-senec.de with '{user}', check credentials (! _is_authenticated)")
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
            self._selected_system = user_input[SETUP_SYS_TYPE]

            # SenecV4 - WebONLY Option...
            if self._selected_system in [SYSTYPE_SENECV4, SYSTYPE_WEBAPI]:
                return await self.async_step_websetup()
            # Inverter option...
            elif self._selected_system == SYSTYPE_INVERTV3:
                return await self.async_step_localsystem()
            else:
                # return await self.async_step_mode()
                return await self.async_step_localsystem()
        else:
            user_input = {
                SETUP_SYS_TYPE: DEFAULT_SYSTEM
            }

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(SETUP_SYS_TYPE, default=user_input[SETUP_SYS_TYPE]):
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

    async def async_step_localsystem(self, user_input=None):
        """Step when user initializes a integration."""
        self._errors = {}
        if user_input is not None:
            # set some defaults in case we need to return to the form
            name_entry = user_input[CONF_NAME]
            host_entry = user_input[CONF_HOST].lower()
            # make sure we just handle host/ip's - removing http/https
            if host_entry.startswith("http://"):
                host_entry = host_entry.replace("http://", "")
            if host_entry.startswith('https://'):
                host_entry = host_entry.replace("https://", "")

            # check if the input is some sort of valid...
            if self.source == SOURCE_RECONFIGURE:
                self._abort_if_unique_id_configured()
            else:
                if host_in_configuration_exists(self.hass, host_entry):
                    self._errors[CONF_HOST] = "already_configured"
                    raise data_entry_flow.AbortFlow("already_configured")

                if title_in_configuration_exists(self.hass, name_entry):
                    self._errors[CONF_NAME] = "already_configured"
                    raise data_entry_flow.AbortFlow("already_configured")

            # Build-In Inverter stuff
            if self._selected_system in [SYSTYPE_INVERTV3, CONF_SYSTYPE_INVERTER]:
                if await self._test_connection_inverter(host_entry):
                    inv_data = {
                        CONF_TYPE: CONF_SYSTYPE_INVERTER,
                        CONF_NAME: name_entry,
                        CONF_HOST: host_entry,
                        CONF_USE_HTTPS: False,
                        CONF_SCAN_INTERVAL: max(user_input[CONF_SCAN_INTERVAL], DEFAULT_MIN_SCAN_INTERVAL),
                        CONF_DEV_TYPE: self._device_type,
                        CONF_SUPPORT_BDC: self._support_bdc,
                        CONF_DEV_MODEL: self._device_model,
                        CONF_DEV_SERIAL: self._device_serial,
                        CONF_DEV_VERSION: self._device_version
                    }
                    if self.source == SOURCE_RECONFIGURE:
                        return self.async_update_reload_and_abort(entry=self._get_reconfigure_entry(), data=inv_data)
                    else:
                        # initial setup...
                        return self.async_create_entry(title=name_entry, data=inv_data)
                else:
                    _LOGGER.error(f"Could not connect to build-in Inverter device at {host_entry}, check host ip address")

            # SENEC.Home stuff
            else:
                if (await self._test_connection_senec_local(host_entry, False) or
                        await self._test_connection_senec_local(host_entry, True)):
                    local_data = {
                        CONF_TYPE: CONF_SYSTYPE_SENEC,
                        CONF_NAME: name_entry,
                        CONF_HOST: host_entry,
                        CONF_SCAN_INTERVAL: max(user_input[CONF_SCAN_INTERVAL], DEFAULT_MIN_SCAN_INTERVAL),
                        CONF_IGNORE_SYSTEM_STATE: user_input[CONF_IGNORE_SYSTEM_STATE],
                        CONF_USE_HTTPS: self._use_https,
                        CONF_DEV_TYPE_INT: self._device_type_internal,
                        CONF_DEV_TYPE: self._device_type,
                        CONF_DEV_MODEL: self._device_model,
                        CONF_DEV_SERIAL: self._device_serial,
                        CONF_DEV_VERSION: self._device_version
                    }
                    if self.source == SOURCE_RECONFIGURE:
                        return self.async_update_reload_and_abort(entry=self._get_reconfigure_entry(), data=local_data)
                    else:
                        # initial setup...
                        if not self._stats_available:
                            # we have to show the user, that he should add also WEB-API
                            _LOGGER.warning("Need WEB-API for full data...")
                            self._xdata = local_data
                            self._xname = name_entry
                            return self.async_show_form(step_id="optional_websetup_required_info", last_step=False, errors=self._errors)
                        else:
                            return self.async_create_entry(title=name_entry, data=local_data)

                else:
                    _LOGGER.error(f"Could not connect to via http or https to SENEC.Home at {host_entry}, check host ip address")

        else:
            user_input = {
                CONF_IGNORE_SYSTEM_STATE: self._default_ignore_system_state
            }

            if all(x is not None for x in [self._default_name, self._default_host]):
                user_input[CONF_NAME] = self._default_name
                user_input[CONF_HOST] = self._default_host
            else:
                if self._selected_system == SYSTYPE_INVERTV3:
                    user_input[CONF_NAME] = DEFAULT_NAME_INVERTER
                    user_input[CONF_HOST] = DEFAULT_HOST_INVERTER
                else:
                    user_input[CONF_NAME] = DEFAULT_NAME
                    user_input[CONF_HOST] = DEFAULT_HOST

            if self._default_interval is not None:
                user_input[CONF_SCAN_INTERVAL] = self._default_interval
            else:
                if self._selected_system == SYSTYPE_SENECV2:
                    user_input[CONF_SCAN_INTERVAL] = DEFAULT_SCAN_INTERVAL_SENECV2
                else:
                    user_input[CONF_SCAN_INTERVAL] = DEFAULT_SCAN_INTERVAL

            if self._selected_system in [SYSTYPE_SENECV3, SYSTYPE_SENECV2, CONF_SYSTYPE_SENEC]:
                a_schema = vol.Schema({
                    vol.Required(CONF_NAME, default=user_input[CONF_NAME]): str,
                    vol.Required(CONF_HOST, default=user_input[CONF_HOST]): str,
                    vol.Required(CONF_SCAN_INTERVAL, default=user_input[CONF_SCAN_INTERVAL]): int,
                    vol.Required(CONF_IGNORE_SYSTEM_STATE, default=user_input[CONF_IGNORE_SYSTEM_STATE]): bool}
                )
            else:
                a_schema = vol.Schema({
                    vol.Required(CONF_NAME, default=user_input[CONF_NAME]): str,
                    vol.Required(CONF_HOST, default=user_input[CONF_HOST]): str,
                    vol.Required(CONF_SCAN_INTERVAL, default=user_input[CONF_SCAN_INTERVAL]): int
                })

            return self.async_show_form(step_id="localsystem", data_schema=a_schema, last_step=True, errors=self._errors)

    async def async_step_websetup(self, user_input=None):
        self._errors = {}
        if user_input is not None:
            name_entry = user_input[CONF_NAME]
            scan_entry = max(user_input[CONF_SCAN_INTERVAL], DEFAULT_MIN_SCAN_INTERVAL_WEB)
            user_entry = user_input[CONF_USERNAME]
            pwd_entry = user_input[CONF_PASSWORD]
            totp_entry = user_input[CONF_TOTP]
            if totp_entry is not None:
                if len(totp_entry) == 0:
                    totp_entry = None
                else:
                    # check, if the user has pasted a TOTP-Secret URL
                    if totp_entry.startswith("otpauth://"):
                        parsed_uri = urlparse(unquote(totp_entry))
                        pq = parse_qs(parsed_uri.query)
                        issuer = pq.get('issuer', [""])[0]
                        if issuer.lower() == "senec":
                            totp_entry = pq.get('secret', [None])[0]
                        else:
                            totp_entry = None
                            self._errors[CONF_TOTP] = "invalid_totp_secret"

                #validate, if the 'totp_entry' can be processed by the lib
                if totp_entry is not None:
                    try:
                        import pyotp
                        totp_test = pyotp.TOTP(totp_entry)
                        check_otp = totp_test.now()
                        if len(check_otp) == 6:
                            _LOGGER.debug(f"async_step_websetup(): current TOTP code: {check_otp}")
                        else:
                            self._errors[CONF_TOTP] = "invalid_totp_secret"
                    except ValueError as e:
                        _LOGGER.error(f"async_step_websetup(): Invalid TOTP secret: {type(e)} - {e}")
                        self._errors[CONF_TOTP] = "invalid_totp_secret"

            if CONF_TOTP not in self._errors:
                # when the user has multiple masters, the auto-detect does
                # not work - so we allow the specification of the AnlagenNummer
                master_plant_val = user_input[CONF_DEV_MASTER_NUM]
                if master_plant_val == 'auto':
                    already_exist_ident = user_entry
                    master_plant_num = -1
                else:
                    already_exist_ident = f"{user_entry}_{master_plant_val}"
                    master_plant_num = int(master_plant_val)

                if self.source == SOURCE_RECONFIGURE:
                    self._abort_if_unique_id_configured()
                else:
                    if host_in_configuration_exists(self.hass, already_exist_ident):
                        self._errors[CONF_USERNAME] = "already_configured"
                        raise data_entry_flow.AbortFlow("already_configured")

                if await self._test_connection_senec_online(user_entry, pwd_entry, totp_entry, master_plant_num):
                    web_data = {
                        CONF_TYPE: CONF_SYSTYPE_WEB,
                        CONF_NAME: name_entry,
                        CONF_HOST: user_entry,
                        CONF_USERNAME: user_entry,
                        CONF_PASSWORD: pwd_entry,
                        CONF_TOTP: totp_entry,
                        CONF_SCAN_INTERVAL: scan_entry,
                        CONF_DEV_TYPE_INT: self._device_type_internal, # must check what function this has for 'online' systems
                        CONF_DEV_TYPE: self._device_type,
                        CONF_DEV_MODEL: self._device_model,
                        CONF_DEV_SERIAL: self._device_serial,
                        CONF_DEV_VERSION: self._device_version,
                        CONF_DEV_MASTER_NUM: self._app_master_plant_number
                    }
                    if self.source == SOURCE_RECONFIGURE:
                        return self.async_update_reload_and_abort(entry=self._get_reconfigure_entry(), data=web_data)
                    else:
                        return self.async_create_entry(title=name_entry, data=web_data)
                else:
                    _LOGGER.error(f"Could not connect to mein-senec.de with User '{user_entry}', check credentials")
                    self._errors[CONF_USERNAME]
                    self._errors[CONF_PASSWORD]
                    if CONF_TOTP in self._errors:
                        self._errors[CONF_TOTP]
            else:
                _LOGGER.error(f"Could not connect to mein-senec.de with User '{user_entry}', check credentials")
                self._errors[CONF_TOTP]
        else:
            user_input = {}
            if all(x is not None for x in
                   [self._default_name, self._default_user, self._default_pwd, self._default_totp,
                    self._default_master_plant_number, self._default_interval]):
                user_input[CONF_NAME] = self._default_name
                user_input[CONF_USERNAME] = self._default_user
                user_input[CONF_PASSWORD] = self._default_pwd
                user_input[CONF_TOTP] = self._default_totp
                user_input[CONF_DEV_MASTER_NUM] = str(self._default_master_plant_number)
                user_input[CONF_SCAN_INTERVAL] = self._default_interval
            else:
                user_input[CONF_NAME] = DEFAULT_NAME_WEB
                user_input[CONF_USERNAME] = DEFAULT_USERNAME
                user_input[CONF_PASSWORD] = ""
                user_input[CONF_TOTP] = ""
                user_input[CONF_DEV_MASTER_NUM] = "auto"
                if self._selected_system == SYSTYPE_SENECV4:
                    user_input[CONF_SCAN_INTERVAL] = DEFAULT_SCAN_INTERVAL_WEB_SENECV4
                else:
                    user_input[CONF_SCAN_INTERVAL] = DEFAULT_SCAN_INTERVAL_WEB

        has_fs_write_access = await asyncio.get_running_loop().run_in_executor(None,
                                                                               SenecOnline.check_general_fs_access,
                                                                               Path(self.hass.config.config_dir).joinpath(STORAGE_DIR))
        if not has_fs_write_access:
            return self.async_abort(reason="no_filesystem_access")
        else:
            return self.async_show_form(
                step_id="websetup",
                data_schema=vol.Schema({
                    vol.Required(CONF_NAME, default=user_input[CONF_NAME]): str,
                    vol.Required(CONF_USERNAME, default=user_input[CONF_USERNAME]): str,
                    vol.Required(CONF_PASSWORD, default=user_input[CONF_PASSWORD]): str,
                    vol.Optional(CONF_TOTP, default=user_input[CONF_TOTP]): str,
                    vol.Required(CONF_DEV_MASTER_NUM, default=user_input[CONF_DEV_MASTER_NUM]):
                        selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=MASTER_PLANT_NUMBERS,
                                mode=selector.SelectSelectorMode.DROPDOWN,
                                translation_key=CONF_DEV_MASTER_NUM,
                            )
                        ),
                    vol.Required(CONF_SCAN_INTERVAL, default=user_input[CONF_SCAN_INTERVAL]): int
                }),
                last_step=True,
                errors=self._errors,
            )

    async def async_step_optional_websetup_required_info(self, user_input=None):
        return self.async_create_entry(title=self._xname, data=self._xdata)

#     @staticmethod
#     @callback
#     def async_get_options_flow(config_entry):
#         return SenecOptionsFlowHandler(config_entry)
#
#
# class SenecOptionsFlowHandler(config_entries.OptionsFlow):
#     """Config flow options handler for waterkotte_heatpump."""
#
#     def __init__(self, config_entry):
#         """Initialize HACS options flow."""
#         self.data = dict(config_entry.data);
#         if len(dict(config_entry.options)) == 0:
#             self.options = {}
#         else:
#             self.options = dict(config_entry.options)
#
#     async def async_step_init(self, user_input=None):  # pylint: disable=unused-argument
#         """Manage the options."""
#         if CONF_TYPE in self.data and self.data[CONF_TYPE] == CONF_SYSTYPE_WEB:
#             return await self.async_step_websetup()
#         else:
#             return await self.async_step_system()
#
#     async def async_step_system(self, user_input=None):
#         """Handle a flow initialized by the user."""
#         self._errors = {}
#         if user_input is not None:
#
#             # verify the entered host...
#             host_entry = user_input.get(CONF_HOST, DEFAULT_HOST).lower()
#             # make sure we just handle host/ip's - removing http/https
#             if host_entry.startswith("http://"):
#                 host_entry = host_entry.replace("http://", "")
#             if host_entry.startswith('https://'):
#                 host_entry = host_entry.replace("https://", "")
#
#             user_input[CONF_HOST] = host_entry
#
#             self.options.update(user_input)
#             if self.data.get(CONF_HOST) != self.options.get(CONF_HOST):
#                 # ok looks like the host has been changed... we need to do some things...
#                 if host_in_configuration_exists(self.hass, host_entry):
#                     self._errors[CONF_HOST] = "already_configured"
#                 else:
#                     return self._update_options()
#             else:
#                 # host did not change...
#                 return self._update_options()
#
#         if CONF_TYPE in self.data and self.data[CONF_TYPE] == CONF_SYSTYPE_INVERTER:
#             dataSchema = vol.Schema(
#                 {
#                     vol.Required(
#                         CONF_NAME, default=self.options.get(CONF_NAME, self.data.get(CONF_NAME, DEFAULT_NAME)),
#                     ): str,
#                     vol.Required(
#                         CONF_HOST, default=self.options.get(CONF_HOST, self.data.get(CONF_HOST, DEFAULT_HOST)),
#                     ): str,  # pylint: disable=line-too-long
#                     vol.Required(
#                         CONF_SCAN_INTERVAL, default=self.options.get(CONF_SCAN_INTERVAL,
#                                                                      self.data.get(CONF_SCAN_INTERVAL,
#                                                                                    DEFAULT_SCAN_INTERVAL)),
#                     ): int
#                 }
#             )
#         else:
#             dataSchema = vol.Schema(
#                 {
#                     vol.Required(
#                         CONF_NAME, default=self.options.get(CONF_NAME, self.data.get(CONF_NAME, DEFAULT_NAME)),
#                     ): str,
#                     vol.Required(
#                         CONF_HOST, default=self.options.get(CONF_HOST, self.data.get(CONF_HOST, DEFAULT_HOST)),
#                     ): str,  # pylint: disable=line-too-long
#                     vol.Required(
#                         CONF_SCAN_INTERVAL, default=self.options.get(CONF_SCAN_INTERVAL,
#                                                                      self.data.get(CONF_SCAN_INTERVAL,
#                                                                                    DEFAULT_SCAN_INTERVAL)),
#                     ): int,  # pylint: disable=line-too-long
#                     vol.Required(
#                         CONF_IGNORE_SYSTEM_STATE, default=self.options.get(CONF_IGNORE_SYSTEM_STATE,
#                                                                            self.data.get(CONF_IGNORE_SYSTEM_STATE,
#                                                                                          False)),
#                     ): bool,  # pylint: disable=line-too-long
#                 }
#             )
#         return self.async_show_form(
#             step_id="system",
#             data_schema=dataSchema,
#         )
#
#     async def async_step_websetup(self, user_input=None):
#         """Handle a flow initialized by the user."""
#         if user_input is not None:
#             # we need to check the scan_interval (configured by the user)... we hard code a limit of 1 minute for all
#             # SENEC.Home V2 & V3 Systems - only V4 can set it to 30 seconds
#             if "ome V4" in self.data.get(CONF_DEV_TYPE):
#                 user_input[CONF_SCAN_INTERVAL] = max(user_input.get(CONF_SCAN_INTERVAL), 30)
#             else:
#                 user_input[CONF_SCAN_INTERVAL] = max(user_input.get(CONF_SCAN_INTERVAL), 60)
#             self.options.update(user_input)
#             return self._update_options()
#
#         dataSchema = vol.Schema(
#             {
#                 vol.Required(
#                     CONF_NAME, default=self.options.get(CONF_NAME, self.data.get(CONF_NAME, DEFAULT_NAME_WEB))
#                 ): str,
#                 vol.Required(
#                     CONF_USERNAME,
#                     default=self.options.get(CONF_USERNAME, self.data.get(CONF_USERNAME, DEFAULT_USERNAME))
#                 ): str,
#                 vol.Required(
#                     CONF_PASSWORD, default=self.options.get(CONF_PASSWORD, self.data.get(CONF_PASSWORD, ""))
#                 ): str,
#                 vol.Required(
#                     CONF_SCAN_INTERVAL, default=self.options.get(CONF_SCAN_INTERVAL, self.data.get(CONF_SCAN_INTERVAL,
#                                                                                                    DEFAULT_SCAN_INTERVAL)),
#                 ): int  # pylint: disable=line-too-long
#             }
#         )
#         return self.async_show_form(
#             step_id="websetup",
#             data_schema=dataSchema,
#         )
#
#     def _update_options(self):
#         """Update config entry options."""
#         return self.async_create_entry(data=self.options)
