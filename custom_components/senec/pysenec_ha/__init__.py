import asyncio
import base64
import calendar
# all for the new openId stuff
import copy
import hashlib
import json
import logging
import os
import random
import re
import secrets
import string
import traceback
from base64 import urlsafe_b64encode
from datetime import datetime, timezone, timedelta
from json import JSONDecodeError
from pathlib import Path
from time import time, strftime, localtime
from typing import Final
from urllib.parse import quote, urlparse, parse_qs

import aiohttp
import pyotp
import xmltodict
from aiohttp import ClientResponseError, ClientConnectorError

from custom_components.senec.const import (
    QUERY_PV1_KEY,
    QUERY_PM1OBJ1_KEY,
    QUERY_PM1OBJ2_KEY,
    QUERY_BMS_KEY,
    QUERY_BMS_CELLS_KEY,
    QUERY_FANDATA_KEY,
    QUERY_WALLBOX_KEY,
    QUERY_SOCKETS_KEY,
    QUERY_SPARE_CAPACITY_KEY,
    QUERY_PEAK_SHAVING_KEY,
    QUERY_TOTALS_KEY,
    QUERY_SYSTEM_DETAILS_KEY,
    IGNORE_SYSTEM_STATE_KEY,
    CONF_APP_SYSTEMID,
    CONF_APP_SERIALNUM,
    CONF_APP_WALLBOX_COUNT,
    CONF_APP_DATA_START,
    CONF_APP_DATA_END,
    CONF_APP_TOTAL_DATA,
    CONF_INCLUDE_WALLBOX_IN_HOUSE_CONSUMPTION,
    DOMAIN
)
from custom_components.senec.pysenec_ha.constants import (
    SYSTEM_STATE_NAME,
    WALLBOX_STATE_NAME,
    SYSTEM_TYPE_NAME,
    BATT_TYPE_NAME,

    SENEC_SECTION_BMS,
    SENEC_SECTION_ENERGY,
    SENEC_SECTION_FAN_SPEED,
    SENEC_SECTION_STATISTIC,
    SENEC_SECTION_TEMPMEASURE,
    SENEC_SECTION_PWR_UNIT,
    SENEC_SECTION_PV1,
    SENEC_SECTION_PM1OBJ1,
    SENEC_SECTION_PM1OBJ2,
    SENEC_SECTION_SOCKETS,
    SENEC_SECTION_WALLBOX,

    SENEC_SECTION_FACTORY,
    SENEC_SECTION_SYS_UPDATE,
    SENEC_SECTION_BAT1,
    SENEC_SECTION_WIZARD,
    SENEC_SECTION_LOG,

    APP_API_WB_MODE_LOCKED,
    APP_API_WB_MODE_FASTEST,
    APP_API_WB_MODE_SSGCM,

    APP_API_WB_MODE_2025_SOLAR,
    APP_API_WB_MODE_2025_FAST,

    LOCAL_WB_MODE_LOCKED,
    LOCAL_WB_MODE_SSGCM_3,
    LOCAL_WB_MODE_SSGCM_4,
    LOCAL_WB_MODE_FASTEST,
    LOCAL_WB_MODE_UNKNOWN,

    SGREADY_CONF_KEYS,
    SGREADY_MODES,
    SGREADY_CONFKEY_ENABLED,
    SENEC_ENERGY_FIELDS,
    SENEC_ENERGY_FIELDS_2408_MIN,

    NO_LIMIT,
    UPDATE_INTERVALS,
    UPDATE_INTERVAL_OPTIONS
)
from custom_components.senec.pysenec_ha.phones import PHONE_BUILD_MAPPING
from custom_components.senec.pysenec_ha.util import parse

# 4: "INITIAL CHARGE",
# 5: "MAINTENANCE CHARGE",
# 8: "MAN. SAFETY CHARGE",
# 10: "FULL CHARGE",
# 11: "EQUALIZATION: CHARGE",
# 12: "DESULFATATION: CHARGE",
# 14: "CHARGE",
# 43: "CAPACITY TEST: CHARGE",
# 71: "OFFPEAK-CHARGE",
SYSTEM_STATUS_CHARGE = {4, 5, 8, 10, 11, 12, 14, 23, 24, 25, 33, 43, 71}

# 16: "DISCHARGE",
# 17: "PV + DISCHARGE",
# 18: "GRID + DISCHARGE"
# 21: "OWN CONSUMPTION"
# 44: "CAPACITY TEST: DISCHARGE",
# 97: "SAFETY DISCHARGE",
SYSTEM_STATUS_DISCHARGE = {16, 17, 18, 21, 29, 44, 97}

_LOGGER = logging.getLogger(__name__)

SET_COOKIE = "Set-Cookie"

class SenecLocal:
    """Senec Home Battery Sensor"""

    _defaultHeaders = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Encoding": "gzip, deflate, br, zstd",
    }
    _lalaHeaders = {
        **_defaultHeaders,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Connection": "keep-alive",
        "Keep-Alive": "timeout=60, max=0",
    }

    def __init__(self, host, use_https, lala_session, lang: str = "en", options: dict = None, integ_version: str = None):
        self._integration_version = integ_version if integ_version is not None else "UNKNOWN"
        _LOGGER.info(f"__init__() -> (re)starting SenecLocal (lala.cgi) integration v{self._integration_version} for host: '{host}' with options: {options}")
        self._lang = lang

        # this property will be finally set on config_read
        self._QUERY_STATS = True
        self._QUERY_USER_LEVEL = False

        # all other query fields depends from the config
        self._QUERY_PV1 = False
        self._QUERY_PM1OBJ1 = False
        self._QUERY_PM1OBJ2 = False
        self._QUERY_BMS = False
        self._QUERY_BMS_CELLS = False
        self._QUERY_WALLBOX = False
        self._QUERY_WALLBOX_APPAPI = False
        self._QUERY_SOCKETSDATA = False
        self._IGNORE_SYSTEM_STATUS = False
        self._QUERY_FANDATA = False

        if options is not None:
            if QUERY_PV1_KEY in options:
                self._QUERY_PV1 = options[QUERY_PV1_KEY]

            if QUERY_PM1OBJ1_KEY in options:
                self._QUERY_PM1OBJ1 = options[QUERY_PM1OBJ1_KEY]

            if QUERY_PM1OBJ2_KEY in options:
                self._QUERY_PM1OBJ2 = options[QUERY_PM1OBJ2_KEY]

            if QUERY_BMS_KEY in options:
                self._QUERY_BMS = options[QUERY_BMS_KEY]

            if QUERY_BMS_CELLS_KEY in options:
                self._QUERY_BMS_CELLS = options[QUERY_BMS_CELLS_KEY]
                if self._QUERY_BMS_CELLS:
                    self._QUERY_BMS = True

            if QUERY_WALLBOX_KEY in options:
                self._QUERY_WALLBOX = options[QUERY_WALLBOX_KEY]
                # do we need some additional information for our wallbox (that are only available via the app-api!
                self._QUERY_WALLBOX_APPAPI = options[QUERY_WALLBOX_KEY]

            if QUERY_FANDATA_KEY in options:
                self._QUERY_FANDATA = options[QUERY_FANDATA_KEY]

            if QUERY_SOCKETS_KEY in options:
                self._QUERY_SOCKETSDATA = options[QUERY_SOCKETS_KEY]

            if IGNORE_SYSTEM_STATE_KEY in options:
                self._IGNORE_SYSTEM_STATUS = options[IGNORE_SYSTEM_STATE_KEY]



        self._host = host
        if use_https:
            self._host_and_schema = f"https://{host}"
        else:
            self._host_and_schema = f"http://{host}"

        self.url = f"{self._host_and_schema}/lala.cgi"
        self.lala_session: aiohttp.websession = lala_session

        # we need to use a cookieJar that accept also IP's!
        if hasattr(self.lala_session, "_cookie_jar"):
            the_jar = getattr(self.lala_session, "_cookie_jar")
            if hasattr(the_jar, "_unsafe"):
                the_jar._unsafe = True
                _LOGGER.debug("WEB_SESSION cookie_jar accept cookies for IP's")


        # evil HACK - since SENEC does not switch the property fast enough…
        # so for five seconds after the switch take place we will return
        # the 'faked' value
        self._OVERWRITES = {
            "LI_STORAGE_MODE_RUNNING": {"TS": 0, "VALUE": False},
            "SAFE_CHARGE_RUNNING": {"TS": 0, "VALUE": False},

            SENEC_SECTION_SOCKETS + "_FORCE_ON": {"TS": 0, "VALUE": [0, 0]},
            SENEC_SECTION_SOCKETS + "_ENABLE": {"TS": 0, "VALUE": [0, 0]},
            SENEC_SECTION_SOCKETS + "_USE_TIME": {"TS": 0, "VALUE": [0, 0]},
            SENEC_SECTION_SOCKETS + "_LOWER_LIMIT": {"TS": 0, "VALUE": [0, 0]},
            SENEC_SECTION_SOCKETS + "_UPPER_LIMIT": {"TS": 0, "VALUE": [0, 0]},
            SENEC_SECTION_SOCKETS + "_POWER_ON_TIME": {"TS": 0, "VALUE": [0, 0]},
            SENEC_SECTION_SOCKETS + "_SWITCH_ON_HOUR": {"TS": 0, "VALUE": [0, 0]},
            SENEC_SECTION_SOCKETS + "_SWITCH_ON_MINUTE": {"TS": 0, "VALUE": [0, 0]},
            SENEC_SECTION_SOCKETS + "_TIME_LIMIT": {"TS": 0, "VALUE": [0, 0]},

            SENEC_SECTION_WALLBOX + "_ALLOW_INTERCHARGE": {"TS": 0, "VALUE": False},
            SENEC_SECTION_WALLBOX + "_PROHIBIT_USAGE": {"TS": 0, "VALUE": [0, 0, 0, 0]},
            SENEC_SECTION_WALLBOX + "_SET_ICMAX": {"TS": 0, "VALUE": [0, 0, 0, 0]},
            SENEC_SECTION_WALLBOX + "_MIN_CHARGING_CURRENT": {"TS": 0, "VALUE": [0, 0, 0, 0]},
            SENEC_SECTION_WALLBOX + "_SET_IDEFAULT": {"TS": 0, "VALUE": [0, 0, 0, 0]},
            SENEC_SECTION_WALLBOX + "_SMART_CHARGE_ACTIVE": {"TS": 0, "VALUE": [0, 0, 0, 0]},
        }

        self._raw_post = None
        self._raw = None
        self._raw_version = None
        self._last_version_update = 0
        self._last_system_reset = 0
        self._timeout = aiohttp.ClientTimeout(total=10, connect=None, sock_connect=None, sock_read=None,
                                              ceil_threshold=5)
        self._SenecOnline = None

        #try:
        #    asyncio.create_task(self.update_version())
        #except Exception as exc:
        #    _LOGGER.debug(f"Exception while try to call 'self.update_version()': {exc}")

    def setSenecOnline(self, senecOnline):
        self._SenecOnline = senecOnline
        _LOGGER.debug(f"SenecOnline initialized, establish bridge between SenecLocal and SenecOnline")
        if self._QUERY_WALLBOX_APPAPI:
            self._SenecOnline._QUERY_WALLBOX = True
            # ok let's force an UPDATE of the WEB-API
            _LOGGER.debug("force refresh of wallbox-data via app-api…")
            try:
                asyncio.create_task(self._SenecOnline.update())
            except Exception as exc:
                _LOGGER.debug(f"Exception while try to call 'self._SenecOnline.update': {exc}")        

    async def update(self):
        if self._raw_version is None or len(self._raw_version) == 0:
            await self.update_version()
        await self._read_senec_lala_with_retry(retry=True)

    async def update_version(self):
        # we do not expect that the version info will update in the next 60 minutes…
        if self._last_version_update + 3600 < time():
            await self._init_gui_cookies(retry=True)
            await self._read_version()

    async def _init_gui_cookies(self, retry:bool):
        # with NPU 2411 we must start the communication with the backend with this single call…
        # no clue what type of special SENEC-Style security this is?!…
        form = {SENEC_SECTION_FACTORY:{"SYS_TYPE":"","COUNTRY":"","DEVICE_ID":""}}
        async with self.lala_session.post(self.url, json=form, ssl=False, headers=self._lalaHeaders, timeout=self._timeout) as res:
            _LOGGER.debug(f"_init_gui_cookies() {util.mask_map(form)} from '{self.url}' - with headers: {res.request_info.headers}")
            try:
                res.raise_for_status()
                data = parse(await res.json())
                if SET_COOKIE in res.headers:
                    _LOGGER.debug(f"init-cookies: {util.mask_map(data)} - {res.headers[SET_COOKIE]}")
                else:
                    if(retry):
                        _LOGGER.debug(f"init-cookies: {util.mask_map(data)} - NO COOKIES in RESPONSE (try to logout)")
                        await asyncio.sleep(1)
                        await self._senec_local_access_stop_no_checks()
                        await asyncio.sleep(2)
                        await self._init_gui_cookies(retry=False)
                    else:
                        _LOGGER.debug(f"init-cookies: {util.mask_map(data)} - NO COOKIES in RESPONSE")

            except JSONDecodeError as exc:
                _LOGGER.warning(f"JSONDecodeError while 'await res.json()' {exc}")

    async def _read_version(self):
        form = {
            SENEC_SECTION_FACTORY: {
                "SYS_TYPE": "",
                "COUNTRY": "",
                "DEVICE_ID": ""
            },
            SENEC_SECTION_WIZARD: {
                "APPLICATION_VERSION": "",
                "FIRMWARE_VERSION": "",
                "INTERFACE_VERSION": "",
                # "SETUP_PM_GRID_ADR": "u8_01",
                # "SETUP_PM_HOUSE_ADR": "u8_02",
                # "MASTER_SLAVE_MODE": "u8_00",
                # "SETUP_NUMBER_WALLBOXES": "u8_00"
            },
            SENEC_SECTION_BAT1: {
                "TYPE": "",
                # "ISLAND_ENABLE": "u8_00",
                # "NSP_FW": "u1_0000",
                # "NSP2_FW": "u1_0000"
            },
            SENEC_SECTION_SYS_UPDATE: {
                "NPU_VER": "",
                "NPU_IMAGE_VERSION": ""
            },
            SENEC_SECTION_STATISTIC: {},
            SENEC_SECTION_BMS:{
                "MODULES_CONFIGURED": ""
            }
        }

        async with self.lala_session.post(self.url, json=form, ssl=False, headers=self._lalaHeaders, timeout=self._timeout) as res:
            _LOGGER.debug(f"_read_version() {util.mask_map(form)} from '{self.url}' - with headers: {res.request_info.headers}")
            try:
                res.raise_for_status()
                self._raw_version = parse(await res.json())
                self._last_version_update = time()
            except JSONDecodeError as exc:
                _LOGGER.warning(f"JSONDecodeError while 'await res.json()' {exc}")

    @property
    def number_of_configured_bms_modules(self) -> int:
        if self._raw_version is not None and "BMS" in self._raw_version and "MODULES_CONFIGURED" in self._raw_version["BMS"]:
            return int(self._raw_version["BMS"]["MODULES_CONFIGURED"])
        else:
            return 0

    ###################################
    # LOCAL-READ
    ###################################
    async def _read_senec_lala_with_retry(self, retry: bool = False):
        try:
            await self._read_senec_lala()
        except ClientConnectorError as exc:
            _LOGGER.info(f"{exc}")
            if retry:
                await asyncio.sleep(5)
                await self._read_senec_lala_with_retry(retry=False)

    async def _read_senec_lala(self):
        form = {
            SENEC_SECTION_TEMPMEASURE: {
                "BATTERY_TEMP": "",
                "CASE_TEMP": "",
                "MCU_TEMP": "",
            },
        }
        if self._QUERY_PV1:
            # the OLD SENEC_SECTION_PV1 section (but we don't use the POWER_RATIO stuff, nor we handle
            # SENEC_SECTION_PWR_UNIT values anywhere - so don't query them!)
            # SENEC_SECTION_PV1: {
            #     #"POWER_RATIO": "",
            #     #"POWER_RATIO_L1": "",
            #     #"POWER_RATIO_L2": "",
            #     #"POWER_RATIO_L3": "",
            #     "MPP_VOL": "",
            #     "MPP_CUR": "",
            #     "MPP_POWER": ""},
            # # SENEC_SECTION_PWR_UNIT: {"POWER_L1": "", "POWER_L2": "", "POWER_L3": ""}
            form[SENEC_SECTION_PV1] = {"MPP_VOL": "", "MPP_CUR": "", "MPP_POWER": ""}

        # when we query wallbox data, then we also need the U_AC values in ''
        if self._QUERY_PM1OBJ1 or self._QUERY_WALLBOX:
            form[SENEC_SECTION_PM1OBJ1] = {"FREQ": "", "U_AC": "", "I_AC": "", "P_AC": "", "P_TOTAL": ""}

        if self._QUERY_PM1OBJ2:
            form[SENEC_SECTION_PM1OBJ2] = {"FREQ": "", "U_AC": "", "I_AC": "", "P_AC": "", "P_TOTAL": ""}

        if self._is_2408_or_higher():
            # 2025/07/06 why we should poll all the data - if we simply don't use them yet…
            form[SENEC_SECTION_ENERGY]  = SENEC_ENERGY_FIELDS_2408_MIN

            if self._QUERY_USER_LEVEL:
                form[SENEC_SECTION_LOG] = {"USER_LEVEL": "", "LOG_IN_NOK_COUNT": ""}

            form[SENEC_SECTION_BAT1]    = {"SPARE_CAPACITY": ""}
        else:
            if self._QUERY_STATS:
                form[SENEC_SECTION_STATISTIC] = {}
            form[SENEC_SECTION_ENERGY] = SENEC_ENERGY_FIELDS

        if self._QUERY_FANDATA:
            form[SENEC_SECTION_FAN_SPEED] = {}

        if self._QUERY_SOCKETSDATA:
            form[SENEC_SECTION_SOCKETS] = {}

        if self._QUERY_BMS:
            bms_query = {
                SENEC_SECTION_BMS: {
                    "CURRENT": "",
                    "VOLTAGE": "",
                    "SOC": "",
                    "SOH": "",
                    "CYCLES": ""
                }}
            if self._QUERY_BMS_CELLS:
                # Add temperature and voltage fields for each configured BMS module
                module_letters = ['A', 'B', 'C', 'D']
                for i in range(min(self.number_of_configured_bms_modules, len(module_letters))):
                    letter = module_letters[i]
                    bms_query[SENEC_SECTION_BMS][f"CELL_TEMPERATURES_MODULE_{letter}"] = ""

                for i in range(min(self.number_of_configured_bms_modules, len(module_letters))):
                    letter = module_letters[i]
                    bms_query[SENEC_SECTION_BMS][f"CELL_VOLTAGES_MODULE_{letter}"] = ""

            form.update(bms_query)

        if self._QUERY_WALLBOX:
            form[SENEC_SECTION_WALLBOX] = {
                "L1_CHARGING_CURRENT": "",
                "L1_USED": "",
                "L2_CHARGING_CURRENT": "",
                "L2_USED": "",
                "L3_CHARGING_CURRENT": "",
                "L3_USED": "",
                "EV_CONNECTED": "",
                "MIN_CHARGING_CURRENT": "",
                "ALLOW_INTERCHARGE": "",
                "SET_ICMAX": "",
                "SET_IDEFAULT": "",
                "SMART_CHARGE_ACTIVE": "",
                "STATE": "",
                "PROHIBIT_USAGE": ""
            }

        try:
            async with self.lala_session.post(self.url, json=form, ssl=False, headers=self._lalaHeaders, timeout=self._timeout) as res:
                _LOGGER.debug(f"_read_senec_lala() {util.mask_map(form)} from '{self.url}' - with headers: {res.request_info.headers}")
                try:
                    res.raise_for_status()
                    data = await res.json()
                    self._raw = parse(data)
                except JSONDecodeError as exc:
                    _LOGGER.warning(f"JSONDecodeError while 'await res.json()' {exc}")
                except Exception as err:
                    _LOGGER.warning(f"read_senec_lala caused: {err}")
        except BaseException as e:
            _LOGGER.info(f"_read_senec_lala() caused: {type(e)} - {e}")

    async def _read_all_fields(self) -> []:
        async with self.lala_session.post(self.url, json={"DEBUG": {"SECTIONS": ""}}, ssl=False, headers=self._lalaHeaders, timeout=self._timeout) as res:
            try:
                res.raise_for_status()
                data = await res.json()
                obj = parse(data)
                form = {}
                for section in obj["DEBUG"]["SECTIONS"]:
                    form[section] = {}
            except JSONDecodeError as exc:
                _LOGGER.warning(f"JSONDecodeError while 'await res.json()' {exc}")

        async with self.lala_session.post(self.url, json=form, ssl=False, headers=self._lalaHeaders, timeout=self._timeout) as res:
            try:
                res.raise_for_status()
                data = await res.json()
                return parse(data)
            except JSONDecodeError as exc:
                _LOGGER.warning(f"JSONDecodeError while 'await res.json()' {exc}")

        return None


    ###################################
    # LOCAL-WRITE
    ###################################
    async def _write(self, data):
        await self._write_senec_v31(data)

    async def _write_senec_v31(self, data):
        _LOGGER.debug(f"posting data (raw): {util.mask_map(data)}")
        async with self.lala_session.post(self.url, json=data, ssl=False, headers=self._lalaHeaders, timeout=self._timeout) as res:
            try:
                res.raise_for_status()
                self._raw_post = parse(await res.json())
                _LOGGER.debug(f"post result (already parsed): {util.mask_map(self._raw_post)}")
                return self._raw_post
            except Exception as err:
                _LOGGER.warning(f"Error while 'posting data' {err}")

    async def _senec_v31_post_plain_form_data(self, form_data_str:str):
        _LOGGER.debug(f"posting x-www-form-urlencoded: {form_data_str}")
        special_hdrs = {
            "Host": self._host,
            "Origin": self._host_and_schema,
            "Referer": f"{self._host_and_schema}/",
            #"Sec-Fetch-Dest": "empty",
            #"Sec-Fetch-Mode": "cors",
            #"Sec-Fetch-Site": "same-origin",
            #"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest",
            #"sec-ch-ua": 'Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132',
            #"sec-ch-ua-mobile": "?0",
            #"sec-ch-ua-platform": "\"Windows\"",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Keep-Alive": "timeout=60, max=0",
        }
        async with self.lala_session.post(self.url, data=form_data_str, headers=special_hdrs, ssl=False, chunked=None) as res:
            _LOGGER.debug(f"senec_v31_post_plain_form_data() '{self.url}' with headers: {res.request_info.headers}")
            try:
                res.raise_for_status()
                self._raw_post = parse(await res.json())
                _LOGGER.debug(f"post result (already parsed): {util.mask_map(self._raw_post)}")
                return self._raw_post
            except Exception as err:
                _LOGGER.warning(f"Error while 'posting data' {err}")


    ###################################
    # VERSION-CHECKS
    ###################################
    async def _is_2408_or_higher_async(self) -> bool:
        if self._last_version_update == 0:
            await self.update_version()
        return self._is_2408_or_higher()

    def _is_2408_or_higher(self) -> bool:
        if self._raw_version is not None and \
                SENEC_SECTION_SYS_UPDATE in self._raw_version and \
                "NPU_IMAGE_VERSION" in self._raw_version[SENEC_SECTION_SYS_UPDATE]:
            return int(self._raw_version[SENEC_SECTION_SYS_UPDATE]["NPU_IMAGE_VERSION"]) >= 2408
        return False

    async def _is_2411_or_higher_async(self) -> bool:
        if self._last_version_update == 0:
            await self.update_version()
        return self._is_2411_or_higher()

    def _is_2411_or_higher(self) -> bool:
        if self._raw_version is not None and \
                SENEC_SECTION_SYS_UPDATE in self._raw_version and \
                "NPU_IMAGE_VERSION" in self._raw_version[SENEC_SECTION_SYS_UPDATE]:
            return int(self._raw_version[SENEC_SECTION_SYS_UPDATE]["NPU_IMAGE_VERSION"]) >= 2411
        return False

    ###################################
    # BUTTON-STUFF
    ###################################
    async def _trigger_button(self, key: str, payload: str):
        return await getattr(self, 'trigger_' + key)(payload)

    async def trigger_system_reboot(self, payload:str):
        if await self._is_2408_or_higher_async():
            if self._last_system_reset + 300 < time():
                data = {"SYS_UPDATE": {"BOOT_REPORT_SUCCESS": "", "USER_REBOOT_DEVICE": "u8_01"}}
                await self._write_senec_v31(data)
                self._last_system_reset = time()
            else:
                _LOGGER.debug(f"Last Reset too recent…")

    ###################################
    # CORE-SWITCHES
    ###################################
    ## LADEN…
    ## {"ENERGY":{"SAFE_CHARGE_FORCE":"u8_01","SAFE_CHARGE_PROHIBIT":"","SAFE_CHARGE_RUNNING":"","LI_STORAGE_MODE_START":"","LI_STORAGE_MODE_STOP":"","LI_STORAGE_MODE_RUNNING":""}}

    ## Freigeben…
    ## {"ENERGY":{"SAFE_CHARGE_FORCE":"","SAFE_CHARGE_PROHIBIT":"u8_01","SAFE_CHARGE_RUNNING":"","LI_STORAGE_MODE_START":"","LI_STORAGE_MODE_STOP":"","LI_STORAGE_MODE_RUNNING":""}}

    # function sendTestPower(e) {
    #    var t = "[";
    # for (c = 0; c < 3; c++) t += '"', t += e ? pageObj.castVarValue("fl", -$("#itestpower").val() / 3) : pageObj.castVarValue("fl", $("#itestpower").val() / 3), c < 2 && (t += '",');
    # t += '"]', pageObj.add_property_to_object("ENERGY", "GRID_POWER_OFFSET", t)
    # }
    # function ChargebtnClickEvent() {
    #    1 == chargeState ? (pageObj.handleCheckBoxUpdate("ENERGY", "TEST_CHARGE_ENABLE", "u8_00"), pageObj.add_property_to_object("ENERGY", "GRID_POWER_OFFSET", '["fl_00000000","fl_00000000","fl_00000000"]')) : isValidFloat($("#itestpower").val()) && 0 < $("#itestpower").val() ? (sendTestPower(!0), pageObj.handleCheckBoxUpdate("ENERGY", "TEST_CHARGE_ENABLE", "u8_01")) : alert(lng.lSetupTestPowerError)
    # }
    # function DischargebtnClickEvent() {
    #    1 == dischargeState ? (pageObj.handleCheckBoxUpdate("ENERGY", "TEST_CHARGE_ENABLE", "u8_00"), pageObj.add_property_to_object("ENERGY", "GRID_POWER_OFFSET", '["fl_00000000","fl_00000000","fl_00000000"]')) : isValidFloat($("#itestpower").val()) && 0 < $("#itestpower").val() ? (sendTestPower(!1), pageObj.handleCheckBoxUpdate("ENERGY", "TEST_CHARGE_ENABLE", "u8_01")) : alert(lng.lSetupTestPowerError)
    # }

    @property
    def safe_charge(self) -> bool:
        if self._raw is not None:
            # if it just has been switched on/off we provide a FAKE value for 5 sec…
            # since senec unit do not react 'instant' on some requests…
            if self._OVERWRITES["SAFE_CHARGE_RUNNING"]["TS"] + 5 > time():
                return self._OVERWRITES["SAFE_CHARGE_RUNNING"]["VALUE"]
            else:
                return self._raw[SENEC_SECTION_ENERGY]["SAFE_CHARGE_RUNNING"] == 1

    async def switch_safe_charge(self, value: bool):
        # first of all getting the real current state from the device… (we don't trust local settings)
        data = await self._senec_v31_post_plain_form_data('{"ENERGY":{"SAFE_CHARGE_FORCE":"","SAFE_CHARGE_PROHIBIT":"","SAFE_CHARGE_RUNNING":"","LI_STORAGE_MODE_START":"","LI_STORAGE_MODE_STOP":"","LI_STORAGE_MODE_RUNNING":""}}')

        if (value and data[SENEC_SECTION_ENERGY]["SAFE_CHARGE_RUNNING"] == 0) or (not value and data[SENEC_SECTION_ENERGY]["SAFE_CHARGE_RUNNING"] == 1):
            self._OVERWRITES["SAFE_CHARGE_RUNNING"].update({"VALUE": value})
            self._OVERWRITES["SAFE_CHARGE_RUNNING"].update({"TS": time()})
            post_data_str = None
            if (value):
                self._raw[SENEC_SECTION_ENERGY]["SAFE_CHARGE_RUNNING"] = 1
                post_data_str = '{"ENERGY":{"SAFE_CHARGE_FORCE":"u8_01","SAFE_CHARGE_PROHIBIT":"","SAFE_CHARGE_RUNNING":"","LI_STORAGE_MODE_START":"","LI_STORAGE_MODE_STOP":"","LI_STORAGE_MODE_RUNNING":""}}'
            else:
                self._raw[SENEC_SECTION_ENERGY]["SAFE_CHARGE_RUNNING"] = 0
                post_data_str = '{"ENERGY":{"SAFE_CHARGE_FORCE":"","SAFE_CHARGE_PROHIBIT":"u8_01","SAFE_CHARGE_RUNNING":"","LI_STORAGE_MODE_START":"","LI_STORAGE_MODE_STOP":"","LI_STORAGE_MODE_RUNNING":""}}'

            await self._senec_v31_post_plain_form_data(post_data_str)
            await asyncio.sleep(1)
            await self._read_senec_lala()
        else:
            _LOGGER.debug(f"Safe Charge already in requested state… requested: {value}  is: {data[SENEC_SECTION_ENERGY]}")

    @property
    def li_storage_mode(self) -> bool:
        if self._raw is not None:
            # if it just has been switched on/off we provide a FAKE value for 5 sec…
            # since senec unit do not react 'instant' on some requests…
            if self._OVERWRITES["LI_STORAGE_MODE_RUNNING"]["TS"] + 5 > time():
                return self._OVERWRITES["LI_STORAGE_MODE_RUNNING"]["VALUE"]
            else:
                return self._raw[SENEC_SECTION_ENERGY]["LI_STORAGE_MODE_RUNNING"] == 1

    async def switch_li_storage_mode(self, value: bool):
        self._OVERWRITES["LI_STORAGE_MODE_RUNNING"].update({"VALUE": value})
        self._OVERWRITES["LI_STORAGE_MODE_RUNNING"].update({"TS": time()})
        post_data = {}
        if (value):
            self._raw[SENEC_SECTION_ENERGY]["LI_STORAGE_MODE_RUNNING"] = 1
            post_data = {
                SENEC_SECTION_ENERGY: {"SAFE_CHARGE_FORCE": "", "SAFE_CHARGE_PROHIBIT": "", "SAFE_CHARGE_RUNNING": "",
                                       "LI_STORAGE_MODE_START": "u8_01", "LI_STORAGE_MODE_STOP": "",
                                       "LI_STORAGE_MODE_RUNNING": ""}}
        else:
            self._raw[SENEC_SECTION_ENERGY]["LI_STORAGE_MODE_RUNNING"] = 0
            post_data = {
                SENEC_SECTION_ENERGY: {"SAFE_CHARGE_FORCE": "", "SAFE_CHARGE_PROHIBIT": "", "SAFE_CHARGE_RUNNING": "",
                                       "LI_STORAGE_MODE_START": "", "LI_STORAGE_MODE_STOP": "u8_01",
                                       "LI_STORAGE_MODE_RUNNING": ""}}

        await self._write(post_data)

    # async def trigger_cap_test_start(self):
    #     if await self.is_2408_or_higher_async():
    #         if (self._raw is not None and "GUI_CAP_TEST_STATE" in self._raw[SENEC_SECTION_ENERGY] and
    #                 self._raw[SENEC_SECTION_ENERGY]["GUI_CAP_TEST_STATE"] == 0):
    #             await self._senec_local_access_start()
    #             # ok we set the new state…
    #             data = {SENEC_SECTION_ENERGY: { "GUI_CAP_TEST_START": "u8_01"}}
    #             await self.write_senec_v31(data)
    #             await self._senec_local_access_stop()
    #         else:
    #             _LOGGER.debug(f"ENERGY GUI_CAP_TEST_STATE unknown or not OFF")
    #
    # async def trigger_cap_test_stop(self):
    #     if await self.is_2408_or_higher_async():
    #         if (self._raw is not None and "GUI_CAP_TEST_STATE" in self._raw[SENEC_SECTION_ENERGY] and
    #             self._raw[SENEC_SECTION_ENERGY]["GUI_CAP_TEST_STATE"] == 1):
    #             await self._senec_local_access_start()
    #             # ok we set the new state…
    #             data = {SENEC_SECTION_ENERGY: { "GUI_CAP_TEST_STOP": "u8_01"}}
    #             await self.write_senec_v31(data)
    #             await self._senec_local_access_stop()
    #         else:
    #             _LOGGER.debug(f"ENERGY GUI_CAP_TEST_STATE unknown or not ON")

    # trigger_load_test_start & trigger_load_test_stop
    # are not really working…
    # async def trigger_load_test_start(self, requested_watts: int):
    #     if await self.is_2408_or_higher_async():
    #         if (self._raw is not None and "GUI_TEST_CHARGE_STAT" in self._raw[SENEC_SECTION_ENERGY] and
    #                 self._raw[SENEC_SECTION_ENERGY]["GUI_TEST_CHARGE_STAT"] == 0):
    #             await self._senec_local_access_start()
    #             # ok we set the new state…
    #             wat_val = f"fl_{util.get_float_as_IEEE754_hex(float(float(requested_watts)/-3))}"
    #             data = {SENEC_SECTION_ENERGY: { "GUI_TEST_CHARGE_STAT": "",
    #                                             "GRID_POWER_OFFSET": [wat_val, wat_val, wat_val],
    #                                             "TEST_CHARGE_ENABLE": "u8_01"} }
    #             await self.write_senec_v31(data)
    #             # as soon as we will logout, the test_load will be cancled…
    #             #await self.senec_local_access_stop()
    #         else:
    #             _LOGGER.debug(f"ENERGY GUI_TEST_CHARGE_STAT unknown or not OFF")
    #
    # async def trigger_load_test_stop(self):
    #     if await self.is_2408_or_higher_async():
    #         if (self._raw is not None and "GUI_TEST_CHARGE_STAT" in self._raw[SENEC_SECTION_ENERGY] and
    #                 self._raw[SENEC_SECTION_ENERGY]["GUI_TEST_CHARGE_STAT"] == 1):
    #             await self._senec_local_access_start()
    #             # ok we set the new state…
    #             wat_val = f"fl_{util.get_float_as_IEEE754_hex(float(0))}"
    #             data = {SENEC_SECTION_ENERGY: { "GUI_TEST_CHARGE_STAT": "",
    #                                             "GRID_POWER_OFFSET": [wat_val, wat_val, wat_val],
    #                                             "TEST_CHARGE_ENABLE": "u8_00"} }
    #             await self.write_senec_v31(data)
    #             # as soon as we will logout, the test_load will be cancled…
    #             #await self.senec_local_access_stop()
    #         else:
    #             _LOGGER.debug(f"ENERGY GUI_TEST_CHARGE_STAT unknown or not OFF")


    ###################################
    # LOCAL-ACCESS
    ###################################
    _senec_a:Final = base64.b64decode("c3RfaW5zdGFsbGF0ZXVy".encode('utf-8')).decode('utf-8')
    _senec_b:Final = base64.b64decode("c3RfU2VuZWNJbnN0YWxs".encode('utf-8')).decode('utf-8')

    @property
    def has_user_level(self) -> bool:
        return SENEC_SECTION_LOG in self._raw and "USER_LEVEL" in self._raw[SENEC_SECTION_LOG]

    @property
    def is_is_user_level_two_or_higher(self) -> bool:
        if not self._QUERY_USER_LEVEL:
            _LOGGER.warning(f"USER_LEVEL will not be requested")

        if SENEC_SECTION_LOG in self._raw and "USER_LEVEL" in self._raw[SENEC_SECTION_LOG]:
            val = self._raw[SENEC_SECTION_LOG]["USER_LEVEL"]
            try:
                return int(val) >= 2
            except:
                pass
        return False

    async def _senec_local_access_start(self):
        self._QUERY_USER_LEVEL = True
        if await self._is_2408_or_higher_async():
            if not self.has_user_level:
                await self.update()
                await asyncio.sleep(2)

            if (self._raw is not None and
                    SENEC_SECTION_LOG in self._raw and
                    "USER_LEVEL" in self._raw[SENEC_SECTION_LOG] and
                    ("VARIABLE_NOT_FOUND" == self._raw[SENEC_SECTION_LOG]["USER_LEVEL"] or
                     int(self._raw[SENEC_SECTION_LOG]["USER_LEVEL"]) < 2)):
                data = {SENEC_SECTION_LOG: {"USER_LEVEL": "", "USERNAME": self._senec_a, "LOG_IN_NOK_COUNT": "", "PASSWORD": self._senec_b, "LOG_IN_BUTT": "u8_01"}}
                await self._write_senec_v31(data)
                await asyncio.sleep(2)
                await self.update()
                _LOGGER.debug(f"LoginOk? {self._raw[SENEC_SECTION_LOG]}")

        self._QUERY_USER_LEVEL = False

    async def _senec_local_access_stop(self):
        self._QUERY_USER_LEVEL = True
        if await self._is_2408_or_higher_async():
            if not self.has_user_level:
                await self.update()
                await asyncio.sleep(2)

            if (self._raw is not None and
                    SENEC_SECTION_LOG in self._raw and
                    "USER_LEVEL" in self._raw[SENEC_SECTION_LOG] and
                    ("VARIABLE_NOT_FOUND" == self._raw[SENEC_SECTION_LOG]["USER_LEVEL"] or
                     int(self._raw[SENEC_SECTION_LOG]["USER_LEVEL"]) > 1)):
                await self._senec_local_access_stop_no_checks()
                await asyncio.sleep(2)
                await self.update()
        self._QUERY_USER_LEVEL = False

    async def _senec_local_access_stop_no_checks(self):
        data = {SENEC_SECTION_LOG: {"LOG_IN_NOK_COUNT": "", "LOG_OUT_BUTT": "u8_01"}}
        await self._write_senec_v31(data)


    def dict_data(self) -> dict:
        # will be called by the UpdateCoordinator (to get the current data)
        # self._raw = None
        # self._raw_version = None
        return {"data": self._raw, "version": self._raw_version}

    @property
    def device_id(self) -> str:
        if self._raw_version is not None and SENEC_SECTION_FACTORY in self._raw_version:
            return self._raw_version[SENEC_SECTION_FACTORY]["DEVICE_ID"]

    @property
    def versions(self) -> str:
        a = self._raw_version[SENEC_SECTION_WIZARD]["APPLICATION_VERSION"]
        b = self._raw_version[SENEC_SECTION_WIZARD]["FIRMWARE_VERSION"]
        c = self._raw_version[SENEC_SECTION_WIZARD]["INTERFACE_VERSION"]
        d = str(self._raw_version[SENEC_SECTION_SYS_UPDATE]["NPU_VER"])
        e = str(self._raw_version[SENEC_SECTION_SYS_UPDATE]["NPU_IMAGE_VERSION"])
        return f"App:{a} FW:{b} NPU-Image:{e}(v{d})"

    @property
    def device_type(self) -> str:
        if self._raw_version is not None and SENEC_SECTION_FACTORY in self._raw_version:
            value = self._raw_version[SENEC_SECTION_FACTORY]["SYS_TYPE"]
            return SYSTEM_TYPE_NAME.get(value, "UNKNOWN")

    @property
    def device_type_internal(self) -> str:
        if self._raw_version is not None and SENEC_SECTION_FACTORY in self._raw_version:
            return self._raw_version[SENEC_SECTION_FACTORY]["SYS_TYPE"]

    @property
    def batt_type(self) -> str:
        if self._raw_version is not None and SENEC_SECTION_BAT1 in self._raw_version:
            value = self._raw_version[SENEC_SECTION_BAT1]["TYPE"]
            return BATT_TYPE_NAME.get(value, "UNKNOWN")

    @property
    def system_state(self) -> str:
        """
        Textual description of energy status

        """
        if self._raw is not None and SENEC_SECTION_ENERGY in self._raw:
            value = self._raw[SENEC_SECTION_ENERGY]["STAT_STATE"]
            if self._lang in SYSTEM_STATE_NAME:
                return SYSTEM_STATE_NAME[self._lang].get(value, "UNKNOWN")
            else:
                return SYSTEM_STATE_NAME["en"].get(value, "UNKNOWN")

    @property
    def hours_of_operation(self) -> int:
        if self._raw is not None and SENEC_SECTION_ENERGY in self._raw:
            if "STAT_HOURS_OF_OPERATION" in self._raw[SENEC_SECTION_ENERGY]:
                return self._raw[SENEC_SECTION_ENERGY]["STAT_HOURS_OF_OPERATION"]

    @property
    def raw_status(self) -> dict:
        """
        Raw dict with all information

        """
        return self._raw

    @property
    def house_power(self) -> float:
        """
        Current power consumption (W)

        """
        if self._raw is not None and SENEC_SECTION_ENERGY in self._raw:
            return self._raw[SENEC_SECTION_ENERGY]["GUI_HOUSE_POW"]

    @property
    def house_total_consumption(self) -> float:
        """
        Total energy used by house (kWh)
        Does not include Wallbox.
        """
        if self._raw is not None and SENEC_SECTION_STATISTIC in self._raw and "LIVE_HOUSE_CONS" in self._raw[
            SENEC_SECTION_STATISTIC]:
            return self._raw[SENEC_SECTION_STATISTIC]["LIVE_HOUSE_CONS"]

    @property
    def solar_generated_power(self) -> float:
        """
        Current power generated by solar panels (W)
        """
        if self._raw is not None and SENEC_SECTION_ENERGY in self._raw:
            return abs(self._raw[SENEC_SECTION_ENERGY]["GUI_INVERTER_POWER"])

    @property
    def solar_total_generated(self) -> float:
        """
        Total energy generated by solar panels (kWh)
        """
        if self._raw is not None and SENEC_SECTION_STATISTIC in self._raw and "LIVE_PV_GEN" in self._raw[
            SENEC_SECTION_STATISTIC]:
            return self._raw[SENEC_SECTION_STATISTIC]["LIVE_PV_GEN"]

    @property
    def battery_charge_percent(self) -> float:
        """
        Current battery charge value (%)
        """
        if self._raw is not None and SENEC_SECTION_ENERGY in self._raw:
            return self._raw[SENEC_SECTION_ENERGY]["GUI_BAT_DATA_FUEL_CHARGE"]

    @property
    def battery_charge_power(self) -> float:
        """
        Current battery charging power (W)
        """
        if self._raw is not None and SENEC_SECTION_ENERGY in self._raw:
            value = self._raw[SENEC_SECTION_ENERGY]["GUI_BAT_DATA_POWER"]
            if value > 0:
                if self._IGNORE_SYSTEM_STATUS or self.is_system_state_charging():
                    return value
        return 0

    @property
    def battery_discharge_power(self) -> float:
        """
        Current battery discharging power (W)
        """
        if self._raw is not None and SENEC_SECTION_ENERGY in self._raw:
            value = self._raw[SENEC_SECTION_ENERGY]["GUI_BAT_DATA_POWER"]
            if value < 0:
                if self._IGNORE_SYSTEM_STATUS or self.is_system_state_discharging():
                    return abs(value)
        return 0

    @property
    def battery_state_power(self) -> float:
        """
        Battery charging power (W)
        Value is positive when battery is charging
        Value is negative when battery is discharging.
        """
        if self._raw is not None and SENEC_SECTION_ENERGY in self._raw:
            return self._raw[SENEC_SECTION_ENERGY]["GUI_BAT_DATA_POWER"]

    @property
    def battery_state_current(self) -> float:
        if self._raw is not None and SENEC_SECTION_ENERGY in self._raw:
            return self._raw[SENEC_SECTION_ENERGY]["GUI_BAT_DATA_CURRENT"]

    @property
    def battery_state_voltage(self) -> float:
        if self._raw is not None and SENEC_SECTION_ENERGY in self._raw:
            return self._raw[SENEC_SECTION_ENERGY]["GUI_BAT_DATA_VOLTAGE"]

    @property
    def battery_total_charged(self) -> float:
        """
        Total energy charged to battery (kWh)
        """
        if self._raw is not None and SENEC_SECTION_STATISTIC in self._raw and "LIVE_BAT_CHARGE" in self._raw[SENEC_SECTION_STATISTIC]:
            return self._raw[SENEC_SECTION_STATISTIC]["LIVE_BAT_CHARGE"]

    @property
    def battery_total_discharged(self) -> float:
        """
        Total energy discharged from battery (kWh)
        """
        if self._raw is not None and SENEC_SECTION_STATISTIC in self._raw and "LIVE_BAT_DISCHARGE" in self._raw[SENEC_SECTION_STATISTIC]:
            return self._raw[SENEC_SECTION_STATISTIC]["LIVE_BAT_DISCHARGE"]

    @property
    def grid_imported_power(self) -> float:
        """
        Current power imported from grid (W)
        """
        if self._raw is not None and SENEC_SECTION_ENERGY in self._raw:
            value = self._raw[SENEC_SECTION_ENERGY]["GUI_GRID_POW"]
            if value > 0:
                return value
        return 0

    @property
    def grid_exported_power(self) -> float:
        """
        Current power exported to grid (W)
        """
        if self._raw is not None and SENEC_SECTION_ENERGY in self._raw:
            value = self._raw[SENEC_SECTION_ENERGY]["GUI_GRID_POW"]
            if value < 0:
                return abs(value)
        return 0

    @property
    def grid_state_power(self) -> float:
        """
        Grid exchange power (W)

        Value is positive when power is imported from grid.
        Value is negative when power is exported to grid.
        """
        if self._raw is not None and SENEC_SECTION_ENERGY in self._raw:
            return self._raw[SENEC_SECTION_ENERGY]["GUI_GRID_POW"]

    @property
    def grid_total_export(self) -> float:
        """
        Total energy exported to grid export (kWh)
        """
        if self._raw is not None and \
                SENEC_SECTION_STATISTIC in self._raw and \
                "LIVE_GRID_EXPORT" in self._raw[SENEC_SECTION_STATISTIC] and \
                self._raw[SENEC_SECTION_STATISTIC]["LIVE_GRID_EXPORT"] != "VARIABLE_NOT_FOUND":
            return self._raw[SENEC_SECTION_STATISTIC]["LIVE_GRID_EXPORT"]

    @property
    def grid_total_import(self) -> float:
        """
        Total energy imported from grid (kWh)
        """
        if self._raw is not None and \
                SENEC_SECTION_STATISTIC in self._raw and \
                "LIVE_GRID_IMPORT" in self._raw[SENEC_SECTION_STATISTIC]:
            return self._raw[SENEC_SECTION_STATISTIC]["LIVE_GRID_IMPORT"]

    @property
    def battery_temp(self) -> float:
        """
        Current battery temperature
        """
        if self._raw is not None and SENEC_SECTION_TEMPMEASURE in self._raw:
            return self._raw[SENEC_SECTION_TEMPMEASURE]["BATTERY_TEMP"]

    @property
    def case_temp(self) -> float:
        """
        Current case temperature
        """
        if self._raw is not None and SENEC_SECTION_TEMPMEASURE in self._raw:
            return self._raw[SENEC_SECTION_TEMPMEASURE]["CASE_TEMP"]

    @property
    def mcu_temp(self) -> float:
        """
        Current controller temperature
        """
        if self._raw is not None and SENEC_SECTION_TEMPMEASURE in self._raw:
            return self._raw[SENEC_SECTION_TEMPMEASURE]["MCU_TEMP"]

    @property
    def solar_mpp1_potential(self) -> float:
        if self._raw is not None and SENEC_SECTION_PV1 in self._raw:
            return self._raw[SENEC_SECTION_PV1]["MPP_VOL"][0]

    @property
    def solar_mpp1_current(self) -> float:
        if self._raw is not None and SENEC_SECTION_PV1 in self._raw:
            return self._raw[SENEC_SECTION_PV1]["MPP_CUR"][0]

    @property
    def solar_mpp1_power(self) -> float:
        if self._raw is not None and SENEC_SECTION_PV1 in self._raw:
            return self._raw[SENEC_SECTION_PV1]["MPP_POWER"][0]

    @property
    def solar_mpp2_potential(self) -> float:
        if self._raw is not None and SENEC_SECTION_PV1 in self._raw:
            return self._raw[SENEC_SECTION_PV1]["MPP_VOL"][1]

    @property
    def solar_mpp2_current(self) -> float:
        if self._raw is not None and SENEC_SECTION_PV1 in self._raw:
            return self._raw[SENEC_SECTION_PV1]["MPP_CUR"][1]

    @property
    def solar_mpp2_power(self) -> float:
        if self._raw is not None and SENEC_SECTION_PV1 in self._raw:
            return self._raw[SENEC_SECTION_PV1]["MPP_POWER"][1]

    @property
    def solar_mpp3_potential(self) -> float:
        if self._raw is not None and SENEC_SECTION_PV1 in self._raw:
            return self._raw[SENEC_SECTION_PV1]["MPP_VOL"][2]

    @property
    def solar_mpp3_current(self) -> float:
        if self._raw is not None and SENEC_SECTION_PV1 in self._raw:
            return self._raw[SENEC_SECTION_PV1]["MPP_CUR"][2]

    @property
    def solar_mpp3_power(self) -> float:
        if self._raw is not None and SENEC_SECTION_PV1 in self._raw:
            return self._raw[SENEC_SECTION_PV1]["MPP_POWER"][2]

    @property
    def enfluri_net_freq(self) -> float:
        if self._raw is not None and SENEC_SECTION_PM1OBJ1 in self._raw:
            return self._raw[SENEC_SECTION_PM1OBJ1]["FREQ"]

    @property
    def enfluri_net_potential_p1(self) -> float:
        if self._raw is not None and SENEC_SECTION_PM1OBJ1 in self._raw:
            return self._raw[SENEC_SECTION_PM1OBJ1]["U_AC"][0]

    @property
    def enfluri_net_potential_p2(self) -> float:
        if self._raw is not None and SENEC_SECTION_PM1OBJ1 in self._raw:
            return self._raw[SENEC_SECTION_PM1OBJ1]["U_AC"][1]

    @property
    def enfluri_net_potential_p3(self) -> float:
        if self._raw is not None and SENEC_SECTION_PM1OBJ1 in self._raw:
            return self._raw[SENEC_SECTION_PM1OBJ1]["U_AC"][2]

    @property
    def enfluri_net_current_p1(self) -> float:
        if self._raw is not None and SENEC_SECTION_PM1OBJ1 in self._raw:
            return self._raw[SENEC_SECTION_PM1OBJ1]["I_AC"][0]

    @property
    def enfluri_net_current_p2(self) -> float:
        if self._raw is not None and SENEC_SECTION_PM1OBJ1 in self._raw:
            return self._raw[SENEC_SECTION_PM1OBJ1]["I_AC"][1]

    @property
    def enfluri_net_current_p3(self) -> float:
        if self._raw is not None and SENEC_SECTION_PM1OBJ1 in self._raw:
            return self._raw[SENEC_SECTION_PM1OBJ1]["I_AC"][2]

    @property
    def enfluri_net_power_p1(self) -> float:
        if self._raw is not None and SENEC_SECTION_PM1OBJ1 in self._raw:
            return self._raw[SENEC_SECTION_PM1OBJ1]["P_AC"][0]

    @property
    def enfluri_net_power_p2(self) -> float:
        if self._raw is not None and SENEC_SECTION_PM1OBJ1 in self._raw:
            return self._raw[SENEC_SECTION_PM1OBJ1]["P_AC"][1]

    @property
    def enfluri_net_power_p3(self) -> float:
        if self._raw is not None and SENEC_SECTION_PM1OBJ1 in self._raw:
            return self._raw[SENEC_SECTION_PM1OBJ1]["P_AC"][2]

    @property
    def enfluri_net_power_total(self) -> float:
        if self._raw is not None and SENEC_SECTION_PM1OBJ1 in self._raw:
            return self._raw[SENEC_SECTION_PM1OBJ1]["P_TOTAL"]

    @property
    def enfluri_usage_freq(self) -> float:
        if self._raw is not None and SENEC_SECTION_PM1OBJ2 in self._raw:
            return self._raw[SENEC_SECTION_PM1OBJ2]["FREQ"]

    @property
    def enfluri_usage_potential_p1(self) -> float:
        if self._raw is not None and SENEC_SECTION_PM1OBJ2 in self._raw:
            return self._raw[SENEC_SECTION_PM1OBJ2]["U_AC"][0]

    @property
    def enfluri_usage_potential_p2(self) -> float:
        if self._raw is not None and SENEC_SECTION_PM1OBJ2 in self._raw:
            return self._raw[SENEC_SECTION_PM1OBJ2]["U_AC"][1]

    @property
    def enfluri_usage_potential_p3(self) -> float:
        if self._raw is not None and SENEC_SECTION_PM1OBJ2 in self._raw:
            return self._raw[SENEC_SECTION_PM1OBJ2]["U_AC"][2]

    @property
    def enfluri_usage_current_p1(self) -> float:
        if self._raw is not None and SENEC_SECTION_PM1OBJ2 in self._raw:
            return self._raw[SENEC_SECTION_PM1OBJ2]["I_AC"][0]

    @property
    def enfluri_usage_current_p2(self) -> float:
        if self._raw is not None and SENEC_SECTION_PM1OBJ2 in self._raw:
            return self._raw[SENEC_SECTION_PM1OBJ2]["I_AC"][1]

    @property
    def enfluri_usage_current_p3(self) -> float:
        if self._raw is not None and SENEC_SECTION_PM1OBJ2 in self._raw:
            return self._raw[SENEC_SECTION_PM1OBJ2]["I_AC"][2]

    @property
    def enfluri_usage_power_p1(self) -> float:
        if self._raw is not None and SENEC_SECTION_PM1OBJ2 in self._raw:
            return self._raw[SENEC_SECTION_PM1OBJ2]["P_AC"][0]

    @property
    def enfluri_usage_power_p2(self) -> float:
        if self._raw is not None and SENEC_SECTION_PM1OBJ2 in self._raw:
            return self._raw[SENEC_SECTION_PM1OBJ2]["P_AC"][1]

    @property
    def enfluri_usage_power_p3(self) -> float:
        if self._raw is not None and SENEC_SECTION_PM1OBJ2 in self._raw:
            return self._raw[SENEC_SECTION_PM1OBJ2]["P_AC"][2]

    @property
    def enfluri_usage_power_total(self) -> float:
        if self._raw is not None and SENEC_SECTION_PM1OBJ2 in self._raw:
            return self._raw[SENEC_SECTION_PM1OBJ2]["P_TOTAL"]

    def is_battery_empty(self) -> bool:
        # 15: "BATTERY EMPTY",
        if self._raw is not None and SENEC_SECTION_ENERGY in self._raw:
            bat_state_is_empty = self._raw[SENEC_SECTION_ENERGY]["STAT_STATE"] == 15
            bat_percent_is_zero = self._raw[SENEC_SECTION_ENERGY]["GUI_BAT_DATA_FUEL_CHARGE"] == 0
            return bat_state_is_empty or bat_percent_is_zero

    def is_system_state_charging(self) -> bool:
        if self._raw is not None and SENEC_SECTION_ENERGY in self._raw:
            return self._raw[SENEC_SECTION_ENERGY]["STAT_STATE"] in SYSTEM_STATUS_CHARGE

    def is_system_state_discharging(self) -> bool:
        if self._raw is not None and SENEC_SECTION_ENERGY in self._raw:
            return self._raw[SENEC_SECTION_ENERGY]["STAT_STATE"] in SYSTEM_STATUS_DISCHARGE

    @property
    def bms_cell_temp_a1(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_A" in self._raw["BMS"]:
            if len(self._raw["BMS"]["CELL_TEMPERATURES_MODULE_A"]) > 0:
                return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_A"][0]

    @property
    def bms_cell_temp_a2(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_A" in self._raw["BMS"]:
            if len(self._raw["BMS"]["CELL_TEMPERATURES_MODULE_A"]) > 1:
                return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_A"][1]

    @property
    def bms_cell_temp_a3(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_A" in self._raw["BMS"]:
            if len(self._raw["BMS"]["CELL_TEMPERATURES_MODULE_A"]) > 2:
                return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_A"][2]

    @property
    def bms_cell_temp_a4(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_A" in self._raw["BMS"]:
            if len(self._raw["BMS"]["CELL_TEMPERATURES_MODULE_A"]) > 3:
                return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_A"][3]

    @property
    def bms_cell_temp_a5(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_A" in self._raw["BMS"]:
            if len(self._raw["BMS"]["CELL_TEMPERATURES_MODULE_A"]) > 4:
                return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_A"][4]

    @property
    def bms_cell_temp_a6(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_A" in self._raw["BMS"]:
            if len(self._raw["BMS"]["CELL_TEMPERATURES_MODULE_A"]) > 5:
                return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_A"][5]

    @property
    def bms_cell_temp_b1(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_B" in self._raw["BMS"]:
            if len(self._raw["BMS"]["CELL_TEMPERATURES_MODULE_B"]) > 0:
                return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_B"][0]

    @property
    def bms_cell_temp_b2(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_B" in self._raw["BMS"]:
            if len(self._raw["BMS"]["CELL_TEMPERATURES_MODULE_B"]) > 1:
                return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_B"][1]

    @property
    def bms_cell_temp_b3(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_B" in self._raw["BMS"]:
            if len(self._raw["BMS"]["CELL_TEMPERATURES_MODULE_B"]) > 2:
                return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_B"][2]

    @property
    def bms_cell_temp_b4(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_B" in self._raw["BMS"]:
            if len(self._raw["BMS"]["CELL_TEMPERATURES_MODULE_B"]) > 3:
                return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_B"][3]

    @property
    def bms_cell_temp_b5(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_B" in self._raw["BMS"]:
            if len(self._raw["BMS"]["CELL_TEMPERATURES_MODULE_B"]) > 4:
                return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_B"][4]

    @property
    def bms_cell_temp_b6(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_B" in self._raw["BMS"]:
            if len(self._raw["BMS"]["CELL_TEMPERATURES_MODULE_B"]) > 5:
                return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_B"][5]

    @property
    def bms_cell_temp_c1(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_C" in self._raw["BMS"]:
            if len(self._raw["BMS"]["CELL_TEMPERATURES_MODULE_C"]) > 0:
                return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_C"][0]

    @property
    def bms_cell_temp_c2(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_C" in self._raw["BMS"]:
            if len(self._raw["BMS"]["CELL_TEMPERATURES_MODULE_C"]) > 1:
                return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_C"][1]

    @property
    def bms_cell_temp_c3(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_C" in self._raw["BMS"]:
            if len(self._raw["BMS"]["CELL_TEMPERATURES_MODULE_C"]) > 2:
                return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_C"][2]

    @property
    def bms_cell_temp_c4(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_C" in self._raw["BMS"]:
            if len(self._raw["BMS"]["CELL_TEMPERATURES_MODULE_C"]) > 3:
                return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_C"][3]

    @property
    def bms_cell_temp_c5(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_C" in self._raw["BMS"]:
            if len(self._raw["BMS"]["CELL_TEMPERATURES_MODULE_C"]) > 4:
                return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_C"][4]

    @property
    def bms_cell_temp_c6(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_C" in self._raw["BMS"]:
            if len(self._raw["BMS"]["CELL_TEMPERATURES_MODULE_C"]) > 5:
                return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_C"][5]

    @property
    def bms_cell_temp_d1(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_D" in self._raw["BMS"]:
            if len(self._raw["BMS"]["CELL_TEMPERATURES_MODULE_D"]) > 0:
                return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_D"][0]

    @property
    def bms_cell_temp_d2(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_D" in self._raw["BMS"]:
            if len(self._raw["BMS"]["CELL_TEMPERATURES_MODULE_D"]) > 1:
                return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_D"][1]

    @property
    def bms_cell_temp_d3(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_D" in self._raw["BMS"]:
            if len(self._raw["BMS"]["CELL_TEMPERATURES_MODULE_D"]) > 2:
                return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_D"][2]

    @property
    def bms_cell_temp_d4(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_D" in self._raw["BMS"]:
            if len(self._raw["BMS"]["CELL_TEMPERATURES_MODULE_D"]) > 3:
                return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_D"][3]

    @property
    def bms_cell_temp_d5(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_D" in self._raw["BMS"]:
            if len(self._raw["BMS"]["CELL_TEMPERATURES_MODULE_D"]) > 4:
                return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_D"][4]

    @property
    def bms_cell_temp_d6(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_D" in self._raw["BMS"]:
            if len(self._raw["BMS"]["CELL_TEMPERATURES_MODULE_D"]) > 5:
                return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_D"][5]

    @property
    def bms_cell_volt_a1(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_A"][0]

    @property
    def bms_cell_volt_a2(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_A"][1]

    @property
    def bms_cell_volt_a3(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_A"][2]

    @property
    def bms_cell_volt_a4(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_A"][3]

    @property
    def bms_cell_volt_a5(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_A"][4]

    @property
    def bms_cell_volt_a6(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_A"][5]

    @property
    def bms_cell_volt_a7(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_A"][6]

    @property
    def bms_cell_volt_a8(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_A"][7]

    @property
    def bms_cell_volt_a9(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_A"][8]

    @property
    def bms_cell_volt_a10(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_A"][9]

    @property
    def bms_cell_volt_a11(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_A"][10]

    @property
    def bms_cell_volt_a12(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_A"][11]

    @property
    def bms_cell_volt_a13(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_A"][12]

    @property
    def bms_cell_volt_a14(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_A"][13]

    @property
    def bms_cell_volt_a15(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_A"][14]

    @property
    def bms_cell_volt_a16(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_A"][15]

    @property
    def bms_cell_volt_b1(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_B"][0]

    @property
    def bms_cell_volt_b2(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_B"][1]

    @property
    def bms_cell_volt_b3(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_B"][2]

    @property
    def bms_cell_volt_b4(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_B"][3]

    @property
    def bms_cell_volt_b5(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_B"][4]

    @property
    def bms_cell_volt_b6(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_B"][5]

    @property
    def bms_cell_volt_b7(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_B"][6]

    @property
    def bms_cell_volt_b8(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_B"][7]

    @property
    def bms_cell_volt_b9(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_B"][8]

    @property
    def bms_cell_volt_b10(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_B"][9]

    @property
    def bms_cell_volt_b11(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_B"][10]

    @property
    def bms_cell_volt_b12(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_B"][11]

    @property
    def bms_cell_volt_b13(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_B"][12]

    @property
    def bms_cell_volt_b14(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_B"][13]

    @property
    def bms_cell_volt_b15(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_B"][14]

    @property
    def bms_cell_volt_b16(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_B"][15]

    @property
    def bms_cell_volt_c1(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_C"][0]

    @property
    def bms_cell_volt_c2(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_C"][1]

    @property
    def bms_cell_volt_c3(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_C"][2]

    @property
    def bms_cell_volt_c4(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_C"][3]

    @property
    def bms_cell_volt_c5(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_C"][4]

    @property
    def bms_cell_volt_c6(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_C"][5]

    @property
    def bms_cell_volt_c7(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_C"][6]

    @property
    def bms_cell_volt_c8(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_C"][7]

    @property
    def bms_cell_volt_c9(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_C"][8]

    @property
    def bms_cell_volt_c10(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_C"][9]

    @property
    def bms_cell_volt_c11(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_C"][10]

    @property
    def bms_cell_volt_c12(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_C"][11]

    @property
    def bms_cell_volt_c13(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_C"][12]

    @property
    def bms_cell_volt_c14(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_C"][13]

    @property
    def bms_cell_volt_c15(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_C"][14]

    @property
    def bms_cell_volt_c16(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_C"][15]

    @property
    def bms_cell_volt_d1(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_D"][0]

    @property
    def bms_cell_volt_d2(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_D"][1]

    @property
    def bms_cell_volt_d3(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_D"][2]

    @property
    def bms_cell_volt_d4(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_D"][3]

    @property
    def bms_cell_volt_d5(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_D"][4]

    @property
    def bms_cell_volt_d6(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_D"][5]

    @property
    def bms_cell_volt_d7(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_D"][6]

    @property
    def bms_cell_volt_d8(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_D"][7]

    @property
    def bms_cell_volt_d9(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_D"][8]

    @property
    def bms_cell_volt_d10(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_D"][9]

    @property
    def bms_cell_volt_d11(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_D"][10]

    @property
    def bms_cell_volt_d12(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_D"][11]

    @property
    def bms_cell_volt_d13(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_D"][12]

    @property
    def bms_cell_volt_d14(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_D"][13]

    @property
    def bms_cell_volt_d15(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_D"][14]

    @property
    def bms_cell_volt_d16(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_D"][15]

    @property
    def bms_soc_a(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "SOC" in self._raw["BMS"] and (
                self.number_of_configured_bms_modules > 0 or len(self._raw["BMS"]["SOC"]) > 0):
            return self._raw["BMS"]["SOC"][0]

    @property
    def bms_soc_b(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "SOC" in self._raw["BMS"] and (
                self.number_of_configured_bms_modules > 1 or len(self._raw["BMS"]["SOC"]) > 1):
            return self._raw["BMS"]["SOC"][1]

    @property
    def bms_soc_c(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "SOC" in self._raw["BMS"] and (
                self.number_of_configured_bms_modules > 2 or len(self._raw["BMS"]["SOC"]) > 2):
            return self._raw["BMS"]["SOC"][2]

    @property
    def bms_soc_d(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "SOC" in self._raw["BMS"] and (
                self.number_of_configured_bms_modules > 3 or len(self._raw["BMS"]["SOC"]) > 3):
            return self._raw["BMS"]["SOC"][3]

    @property
    def bms_soh_a(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "SOH" in self._raw["BMS"] and (
                self.number_of_configured_bms_modules > 0 or len(self._raw["BMS"]["SOH"]) > 0):
            return self._raw["BMS"]["SOH"][0]

    @property
    def bms_soh_b(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "SOH" in self._raw["BMS"] and (
                self.number_of_configured_bms_modules > 1 or len(self._raw["BMS"]["SOH"]) > 1):
            return self._raw["BMS"]["SOH"][1]

    @property
    def bms_soh_c(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "SOH" in self._raw["BMS"] and (
                self.number_of_configured_bms_modules > 2 or len(self._raw["BMS"]["SOH"]) > 2):
            return self._raw["BMS"]["SOH"][2]

    @property
    def bms_soh_d(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "SOH" in self._raw["BMS"] and (
                self.number_of_configured_bms_modules > 3 or len(self._raw["BMS"]["SOH"]) > 3):
            return self._raw["BMS"]["SOH"][3]

    @property
    def bms_voltage_a(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "VOLTAGE" in self._raw["BMS"] and (
                self.number_of_configured_bms_modules > 0 or len(self._raw["BMS"]["VOLTAGE"]) > 0):
            return self._raw["BMS"]["VOLTAGE"][0]

    @property
    def bms_voltage_b(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "VOLTAGE" in self._raw["BMS"] and (
                self.number_of_configured_bms_modules > 1 or len(self._raw["BMS"]["VOLTAGE"]) > 1):
            return self._raw["BMS"]["VOLTAGE"][1]

    @property
    def bms_voltage_c(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "VOLTAGE" in self._raw["BMS"] and (
                self.number_of_configured_bms_modules > 2 or len(self._raw["BMS"]["VOLTAGE"]) > 2):
            return self._raw["BMS"]["VOLTAGE"][2]

    @property
    def bms_voltage_d(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "VOLTAGE" in self._raw["BMS"] and (
                self.number_of_configured_bms_modules > 3 or len(self._raw["BMS"]["VOLTAGE"]) > 3):
            return self._raw["BMS"]["VOLTAGE"][3]

    @property
    def bms_current_a(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CURRENT" in self._raw["BMS"] and (
                self.number_of_configured_bms_modules > 0 or len(self._raw["BMS"]["CURRENT"]) > 0):
            return self._raw["BMS"]["CURRENT"][0]

    @property
    def bms_current_b(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CURRENT" in self._raw["BMS"] and (
                self.number_of_configured_bms_modules > 1 or len(self._raw["BMS"]["CURRENT"]) > 1):
            return self._raw["BMS"]["CURRENT"][1]

    @property
    def bms_current_c(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CURRENT" in self._raw["BMS"] and (
                self.number_of_configured_bms_modules > 2 or len(self._raw["BMS"]["CURRENT"]) > 2):
            return self._raw["BMS"]["CURRENT"][2]

    @property
    def bms_current_d(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CURRENT" in self._raw["BMS"] and (
                self.number_of_configured_bms_modules > 3 or len(self._raw["BMS"]["CURRENT"]) > 3):
            return self._raw["BMS"]["CURRENT"][3]

    @property
    def bms_cycles_a(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CYCLES" in self._raw["BMS"] and (
                self.number_of_configured_bms_modules > 0 or len(self._raw["BMS"]["CYCLES"]) > 0):
            return self._raw["BMS"]["CYCLES"][0]

    @property
    def bms_cycles_b(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CYCLES" in self._raw["BMS"] and (
                self.number_of_configured_bms_modules > 1 or len(self._raw["BMS"]["CYCLES"]) > 1):
            return self._raw["BMS"]["CYCLES"][1]

    @property
    def bms_cycles_c(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CYCLES" in self._raw["BMS"] and (
                self.number_of_configured_bms_modules > 2 or len(self._raw["BMS"]["CYCLES"]) > 2):
            return self._raw["BMS"]["CYCLES"][2]

    @property
    def bms_cycles_d(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CYCLES" in self._raw["BMS"] and (
                self.number_of_configured_bms_modules > 3 or len(self._raw["BMS"]["CYCLES"]) > 3):
            return self._raw["BMS"]["CYCLES"][3]

    @property
    def bms_fw_a(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "FW" in self._raw["BMS"] and (
                self.number_of_configured_bms_modules > 0 or len(self._raw["BMS"]["FW"]) > 0):
            return self._raw["BMS"]["FW"][0]

    @property
    def bms_fw_b(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "FW" in self._raw["BMS"] and (
                self.number_of_configured_bms_modules > 1 or len(self._raw["BMS"]["FW"]) > 1):
            return self._raw["BMS"]["FW"][1]

    @property
    def bms_fw_c(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "FW" in self._raw["BMS"] and (
                self.number_of_configured_bms_modules > 2 or len(self._raw["BMS"]["FW"]) > 2):
            return self._raw["BMS"]["FW"][2]

    @property
    def bms_fw_d(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "FW" in self._raw["BMS"] and (
                self.number_of_configured_bms_modules > 3 or len(self._raw["BMS"]["FW"]) > 3):
            return self._raw["BMS"]["FW"][3]

    @property
    def wallbox_1_state(self) -> str:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "STATE" in self._raw[SENEC_SECTION_WALLBOX]:
            value = self._raw[SENEC_SECTION_WALLBOX]["STATE"][0]
            if self._lang in WALLBOX_STATE_NAME:
                return WALLBOX_STATE_NAME[self._lang].get(value, "UNKNOWN")
            else:
                return WALLBOX_STATE_NAME["en"].get(value, "UNKNOWN")

    @property
    def wallbox_1_power(self) -> float:
        """
        Wallbox Total Charging Power (W)
        Derived from the 3 phase voltages multiplied with the phase currents from the wallbox
        """
        if (self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and
                "L1_CHARGING_CURRENT" in self._raw[SENEC_SECTION_WALLBOX] and
                "L2_CHARGING_CURRENT" in self._raw[SENEC_SECTION_WALLBOX] and
                "L3_CHARGING_CURRENT" in self._raw[SENEC_SECTION_WALLBOX] and
                SENEC_SECTION_PM1OBJ1 in self._raw and "U_AC" in self._raw[SENEC_SECTION_PM1OBJ1] and
                len(self._raw[SENEC_SECTION_PM1OBJ1]["U_AC"]) >= 3
        ):
            total = 0
            if self._raw[SENEC_SECTION_WALLBOX]["L1_USED"][0] == 1:
                total += self._raw[SENEC_SECTION_WALLBOX]["L1_CHARGING_CURRENT"][0] * \
                         self._raw[SENEC_SECTION_PM1OBJ1]["U_AC"][0]
            if self._raw[SENEC_SECTION_WALLBOX]["L2_USED"][0] == 1:
                total += self._raw[SENEC_SECTION_WALLBOX]["L2_CHARGING_CURRENT"][0] * \
                         self._raw[SENEC_SECTION_PM1OBJ1]["U_AC"][1]
            if self._raw[SENEC_SECTION_WALLBOX]["L3_USED"][0] == 1:
                total += self._raw[SENEC_SECTION_WALLBOX]["L3_CHARGING_CURRENT"][0] * \
                         self._raw[SENEC_SECTION_PM1OBJ1]["U_AC"][2]
            return total

    @property
    def wallbox_1_ev_connected(self) -> bool:
        """
        Wallbox EV Connected
        """
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "EV_CONNECTED" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["EV_CONNECTED"][0]

    @property
    def wallbox_1_energy(self) -> float:
        """
        Wallbox Total Energy
        """
        if self._raw is not None and SENEC_SECTION_STATISTIC in self._raw and "LIVE_WB_ENERGY" in self._raw[
            SENEC_SECTION_STATISTIC]:
            return self._raw[SENEC_SECTION_STATISTIC]["LIVE_WB_ENERGY"][0]

    @property
    def wallbox_1_l1_used(self) -> bool:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L1_USED"][0] == 1

    @property
    def wallbox_1_l2_used(self) -> bool:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L2_USED"][0] == 1

    @property
    def wallbox_1_l3_used(self) -> bool:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L3_USED"][0] == 1

    @property
    def wallbox_1_l1_charging_current(self) -> float:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L1_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L1_CHARGING_CURRENT"][0]

    @property
    def wallbox_1_l2_charging_current(self) -> float:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L2_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L2_CHARGING_CURRENT"][0]

    @property
    def wallbox_1_l3_charging_current(self) -> float:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L3_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L3_CHARGING_CURRENT"][0]

    @property
    def wallbox_1_min_charging_current(self) -> float:
        return self.read_array_data(SENEC_SECTION_WALLBOX, "MIN_CHARGING_CURRENT")[0]

    @property
    def wallbox_2_state(self) -> str:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "STATE" in self._raw[SENEC_SECTION_WALLBOX]:
            value = self._raw[SENEC_SECTION_WALLBOX]["STATE"][1]
            if self._lang in WALLBOX_STATE_NAME:
                return WALLBOX_STATE_NAME[self._lang].get(value, "UNKNOWN")
            else:
                return WALLBOX_STATE_NAME["en"].get(value, "UNKNOWN")

    @property
    def wallbox_2_power(self) -> float:
        """
        Wallbox Total Charging Power (W)
        Derived from the 3 phase voltages multiplied with the phase currents from the wallbox
        """
        if (self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and
                "L1_CHARGING_CURRENT" in self._raw[SENEC_SECTION_WALLBOX] and
                "L2_CHARGING_CURRENT" in self._raw[SENEC_SECTION_WALLBOX] and
                "L3_CHARGING_CURRENT" in self._raw[SENEC_SECTION_WALLBOX] and
                SENEC_SECTION_PM1OBJ1 in self._raw and "U_AC" in self._raw[SENEC_SECTION_PM1OBJ1] and
                len(self._raw[SENEC_SECTION_PM1OBJ1]["U_AC"]) >= 3
        ):
            total = 0
            if self._raw[SENEC_SECTION_WALLBOX]["L1_USED"][1] == 1:
                total += self._raw[SENEC_SECTION_WALLBOX]["L1_CHARGING_CURRENT"][1] * \
                         self._raw[SENEC_SECTION_PM1OBJ1]["U_AC"][0]
            if self._raw[SENEC_SECTION_WALLBOX]["L2_USED"][1] == 1:
                total += self._raw[SENEC_SECTION_WALLBOX]["L2_CHARGING_CURRENT"][1] * \
                         self._raw[SENEC_SECTION_PM1OBJ1]["U_AC"][1]
            if self._raw[SENEC_SECTION_WALLBOX]["L3_USED"][1] == 1:
                total += self._raw[SENEC_SECTION_WALLBOX]["L3_CHARGING_CURRENT"][1] * \
                         self._raw[SENEC_SECTION_PM1OBJ1]["U_AC"][2]
            return total

    @property
    def wallbox_2_ev_connected(self) -> bool:
        """
        Wallbox EV Connected
        """
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "EV_CONNECTED" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["EV_CONNECTED"][1]

    @property
    def wallbox_2_energy(self) -> float:
        """
        Wallbox Total Energy
        """
        if self._raw is not None and SENEC_SECTION_STATISTIC in self._raw and "LIVE_WB_ENERGY" in self._raw[
            SENEC_SECTION_STATISTIC]:
            return self._raw[SENEC_SECTION_STATISTIC]["LIVE_WB_ENERGY"][1]

    @property
    def wallbox_2_l1_used(self) -> bool:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L1_USED"][1] == 1

    @property
    def wallbox_2_l2_used(self) -> bool:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L2_USED"][1] == 1

    @property
    def wallbox_2_l3_used(self) -> bool:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L3_USED"][1] == 1

    @property
    def wallbox_2_l1_charging_current(self) -> float:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L1_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L1_CHARGING_CURRENT"][1]

    @property
    def wallbox_2_l2_charging_current(self) -> float:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L2_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L2_CHARGING_CURRENT"][1]

    @property
    def wallbox_2_l3_charging_current(self) -> float:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L3_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L3_CHARGING_CURRENT"][1]

    @property
    def wallbox_2_min_charging_current(self) -> float:
        return self.read_array_data(SENEC_SECTION_WALLBOX, "MIN_CHARGING_CURRENT")[1]

    @property
    def wallbox_3_state(self) -> str:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "STATE" in self._raw[SENEC_SECTION_WALLBOX]:
            value = self._raw[SENEC_SECTION_WALLBOX]["STATE"][2]
            if self._lang in WALLBOX_STATE_NAME:
                return WALLBOX_STATE_NAME[self._lang].get(value, "UNKNOWN")
            else:
                return WALLBOX_STATE_NAME["en"].get(value, "UNKNOWN")

    @property
    def wallbox_3_power(self) -> float:
        """
        Wallbox Total Charging Power (W)
        Derived from the 3 phase voltages multiplied with the phase currents from the wallbox
        """
        if (self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and
                "L1_CHARGING_CURRENT" in self._raw[SENEC_SECTION_WALLBOX] and
                "L2_CHARGING_CURRENT" in self._raw[SENEC_SECTION_WALLBOX] and
                "L3_CHARGING_CURRENT" in self._raw[SENEC_SECTION_WALLBOX] and
                SENEC_SECTION_PM1OBJ1 in self._raw and "U_AC" in self._raw[SENEC_SECTION_PM1OBJ1] and
                len(self._raw[SENEC_SECTION_PM1OBJ1]["U_AC"]) >= 3
        ):
            total = 0
            if self._raw[SENEC_SECTION_WALLBOX]["L1_USED"][2] == 1:
                total += self._raw[SENEC_SECTION_WALLBOX]["L1_CHARGING_CURRENT"][2] * \
                         self._raw[SENEC_SECTION_PM1OBJ1]["U_AC"][0]
            if self._raw[SENEC_SECTION_WALLBOX]["L2_USED"][2] == 1:
                total += self._raw[SENEC_SECTION_WALLBOX]["L2_CHARGING_CURRENT"][2] * \
                         self._raw[SENEC_SECTION_PM1OBJ1]["U_AC"][1]
            if self._raw[SENEC_SECTION_WALLBOX]["L3_USED"][2] == 1:
                total += self._raw[SENEC_SECTION_WALLBOX]["L3_CHARGING_CURRENT"][2] * \
                         self._raw[SENEC_SECTION_PM1OBJ1]["U_AC"][2]
            return total

    @property
    def wallbox_3_ev_connected(self) -> bool:
        """
        Wallbox EV Connected
        """
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "EV_CONNECTED" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["EV_CONNECTED"][2]

    @property
    def wallbox_3_energy(self) -> float:
        """
        Wallbox Total Energy
        """
        if self._raw is not None and SENEC_SECTION_STATISTIC in self._raw and "LIVE_WB_ENERGY" in self._raw[
            SENEC_SECTION_STATISTIC]:
            return self._raw[SENEC_SECTION_STATISTIC]["LIVE_WB_ENERGY"][2]

    @property
    def wallbox_3_l1_used(self) -> bool:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L1_USED"][2] == 1

    @property
    def wallbox_3_l2_used(self) -> bool:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L2_USED"][2] == 1

    @property
    def wallbox_3_l3_used(self) -> bool:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L3_USED"][2] == 1

    @property
    def wallbox_3_l1_charging_current(self) -> float:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L1_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L1_CHARGING_CURRENT"][2]

    @property
    def wallbox_3_l2_charging_current(self) -> float:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L2_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L2_CHARGING_CURRENT"][2]

    @property
    def wallbox_3_l3_charging_current(self) -> float:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L3_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L3_CHARGING_CURRENT"][2]

    @property
    def wallbox_3_min_charging_current(self) -> float:
        return self.read_array_data(SENEC_SECTION_WALLBOX, "MIN_CHARGING_CURRENT")[2]

    @property
    def wallbox_4_state(self) -> str:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "STATE" in self._raw[SENEC_SECTION_WALLBOX]:
            value = self._raw[SENEC_SECTION_WALLBOX]["STATE"][3]
            if self._lang in WALLBOX_STATE_NAME:
                return WALLBOX_STATE_NAME[self._lang].get(value, "UNKNOWN")
            else:
                return WALLBOX_STATE_NAME["en"].get(value, "UNKNOWN")

    @property
    def wallbox_4_power(self) -> float:
        """
        Wallbox Total Charging Power (W)
        Derived from the 3 phase voltages multiplied with the phase currents from the wallbox
        """
        if (self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and
                "L1_CHARGING_CURRENT" in self._raw[SENEC_SECTION_WALLBOX] and
                "L2_CHARGING_CURRENT" in self._raw[SENEC_SECTION_WALLBOX] and
                "L3_CHARGING_CURRENT" in self._raw[SENEC_SECTION_WALLBOX] and
                SENEC_SECTION_PM1OBJ1 in self._raw and "U_AC" in self._raw[SENEC_SECTION_PM1OBJ1] and
                len(self._raw[SENEC_SECTION_PM1OBJ1]["U_AC"]) >= 3
        ):
            total = 0
            if self._raw[SENEC_SECTION_WALLBOX]["L1_USED"][3] == 1:
                total += self._raw[SENEC_SECTION_WALLBOX]["L1_CHARGING_CURRENT"][3] * \
                         self._raw[SENEC_SECTION_PM1OBJ1]["U_AC"][0]
            if self._raw[SENEC_SECTION_WALLBOX]["L2_USED"][3] == 1:
                total += self._raw[SENEC_SECTION_WALLBOX]["L2_CHARGING_CURRENT"][3] * \
                         self._raw[SENEC_SECTION_PM1OBJ1]["U_AC"][1]
            if self._raw[SENEC_SECTION_WALLBOX]["L3_USED"][3] == 1:
                total += self._raw[SENEC_SECTION_WALLBOX]["L3_CHARGING_CURRENT"][3] * \
                         self._raw[SENEC_SECTION_PM1OBJ1]["U_AC"][2]
            return total

    @property
    def wallbox_4_ev_connected(self) -> bool:
        """
        Wallbox EV Connected
        """
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "EV_CONNECTED" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["EV_CONNECTED"][3]

    @property
    def wallbox_4_energy(self) -> float:
        """
        Wallbox Total Energy
        """
        if self._raw is not None and SENEC_SECTION_STATISTIC in self._raw and "LIVE_WB_ENERGY" in self._raw[
            SENEC_SECTION_STATISTIC]:
            return self._raw[SENEC_SECTION_STATISTIC]["LIVE_WB_ENERGY"][3]

    @property
    def wallbox_4_l1_used(self) -> bool:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L1_USED"][3] == 1

    @property
    def wallbox_4_l2_used(self) -> bool:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L2_USED"][3] == 1

    @property
    def wallbox_4_l3_used(self) -> bool:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L3_USED"][3] == 1

    @property
    def wallbox_4_l1_charging_current(self) -> float:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L1_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L1_CHARGING_CURRENT"][3]

    @property
    def wallbox_4_l2_charging_current(self) -> float:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L2_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L2_CHARGING_CURRENT"][3]

    @property
    def wallbox_4_l3_charging_current(self) -> float:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L3_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L3_CHARGING_CURRENT"][3]

    @property
    def wallbox_4_min_charging_current(self) -> float:
        return self.read_array_data(SENEC_SECTION_WALLBOX, "MIN_CHARGING_CURRENT")[3]

    @property
    def fan_inv_lv(self) -> bool:
        if self._raw is not None and SENEC_SECTION_FAN_SPEED in self._raw and "INV_LV" in self._raw[
            SENEC_SECTION_FAN_SPEED]:
            return self._raw[SENEC_SECTION_FAN_SPEED]["INV_LV"] > 0

    @property
    def fan_inv_hv(self) -> bool:
        if self._raw is not None and SENEC_SECTION_FAN_SPEED in self._raw and "INV_HV" in self._raw[
            SENEC_SECTION_FAN_SPEED]:
            return self._raw[SENEC_SECTION_FAN_SPEED]["INV_HV"] > 0

    @property
    def spare_capacity(self) -> int:
        if self._raw is not None and SENEC_SECTION_BAT1 in self._raw and "SPARE_CAPACITY" in self._raw[
            SENEC_SECTION_BAT1]:
            return self._raw[SENEC_SECTION_BAT1]["SPARE_CAPACITY"]

    @property
    def sockets_already_switched(self) -> [int]:
        if self._raw is not None and SENEC_SECTION_SOCKETS in self._raw and "ALREADY_SWITCHED" in self._raw[
            SENEC_SECTION_SOCKETS]:
            return self._raw[SENEC_SECTION_SOCKETS]["ALREADY_SWITCHED"]

    @property
    def sockets_power_on(self) -> [float]:
        if self._raw is not None and SENEC_SECTION_SOCKETS in self._raw and "POWER_ON" in self._raw[
            SENEC_SECTION_SOCKETS]:
            return self._raw[SENEC_SECTION_SOCKETS]["POWER_ON"]

    @property
    def sockets_priority(self) -> [float]:
        if self._raw is not None and SENEC_SECTION_SOCKETS in self._raw and "PRIORITY" in self._raw[
            SENEC_SECTION_SOCKETS]:
            return self._raw[SENEC_SECTION_SOCKETS]["PRIORITY"]

    @property
    def sockets_time_rem(self) -> [float]:
        if self._raw is not None and SENEC_SECTION_SOCKETS in self._raw and "TIME_REM" in self._raw[
            SENEC_SECTION_SOCKETS]:
            return self._raw[SENEC_SECTION_SOCKETS]["TIME_REM"]

    @property
    def wallbox_allow_intercharge(self) -> bool:
        # please note this is not ARRAY data - so we code it here again…
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "ALLOW_INTERCHARGE" in self._raw[
            SENEC_SECTION_WALLBOX]:
            # if it just has been switched on/off we provide a FAKE value for 5 sec…
            # since senec unit do not react 'instant' on some requests…
            if self._OVERWRITES[SENEC_SECTION_WALLBOX + "_ALLOW_INTERCHARGE"]["TS"] + 5 > time():
                return self._OVERWRITES[SENEC_SECTION_WALLBOX + "_ALLOW_INTERCHARGE"]["VALUE"]
            else:
                return self._raw[SENEC_SECTION_WALLBOX]["ALLOW_INTERCHARGE"] == 1

    async def switch_wallbox_allow_intercharge(self, value: bool, sync: bool = True):
        # please note this is not ARRAY data - so we code it here again…
        self._OVERWRITES[SENEC_SECTION_WALLBOX + "_ALLOW_INTERCHARGE"].update({"VALUE": value})
        self._OVERWRITES[SENEC_SECTION_WALLBOX + "_ALLOW_INTERCHARGE"].update({"TS": time()})
        post_data = {}
        if (value):
            self._raw[SENEC_SECTION_WALLBOX]["ALLOW_INTERCHARGE"] = 1
            post_data = {SENEC_SECTION_WALLBOX: {"ALLOW_INTERCHARGE": "u8_01"}}
        else:
            self._raw[SENEC_SECTION_WALLBOX]["ALLOW_INTERCHARGE"] = 0
            post_data = {SENEC_SECTION_WALLBOX: {"ALLOW_INTERCHARGE": "u8_00"}}

        await self._write(post_data)

        if sync and self._SenecOnline is not None:
            # ALLOW_INTERCHARGE seams to be a wallbox-number independent setting… so we need to push
            # this to all 4 possible wallboxes…
            await self._SenecOnline.app_set_allow_intercharge_all(value_to_set=value, sync=False)

    async def switch(self, switch_key, value):
        return await getattr(self, 'switch_' + str(switch_key))(value)

    """SWITCH ARRAY FROM HERE…"""

    @property
    def sockets_enable(self) -> [int]:
        return self.read_array_data(SENEC_SECTION_SOCKETS, "ENABLE")

    async def switch_array_sockets_enable(self, pos: int, value: bool):
        await self.switch_array_post(SENEC_SECTION_SOCKETS, "ENABLE", pos, 2, value)

    @property
    def sockets_force_on(self) -> [int]:
        return self.read_array_data(SENEC_SECTION_SOCKETS, "FORCE_ON")

    async def switch_array_sockets_force_on(self, pos: int, value: bool):
        await self.switch_array_post(SENEC_SECTION_SOCKETS, "FORCE_ON", pos, 2, value)

    @property
    def sockets_use_time(self) -> [int]:
        return self.read_array_data(SENEC_SECTION_SOCKETS, "USE_TIME")

    async def switch_array_sockets_use_time(self, pos: int, value: bool):
        await self.switch_array_post(SENEC_SECTION_SOCKETS, "USE_TIME", pos, 2, value)

    @property
    def wallbox_smart_charge_active(self) -> [int]:
        return self.read_array_data(SENEC_SECTION_WALLBOX, "SMART_CHARGE_ACTIVE")

    # SET the "switch" SMART_CHARGE_ACTIVE is a bit different, since the ON value is not 01 - it's (for what
    # ever reason 03)…
    # async def switch_array_smart_charge_active(self, pos: int, value: int):
    #    await self.set_nva_post(SENEC_SECTION_WALLBOX, "SMART_CHARGE_ACTIVE", pos, 4, "u8", value)

    @property
    def wallbox_prohibit_usage(self) -> [int]:
        return self.read_array_data(SENEC_SECTION_WALLBOX, "PROHIBIT_USAGE")

    # 2025/08/03 - the complete 'switch_array_wallbox_prohibit_usage' was not implemented since
    # the APP-API was added (2024.0.1)
    # The main reason is, that on "restore" - we don't the previous (old) state, that we should
    # restore befor the system went to lock state.
    # When the integration is started and the LOCK is active, we don't know the previous state!
    # async def switch_array_wallbox_prohibit_usage(self, pos: int, value: bool, sync: bool = True):
    #     mode = None
    #     if value:
    #         mode = LOCAL_WB_MODE_LOCKED
    #     else:
    #         # no clue what should be the starte to be restored?!
    #         mode = APP_API_WEB_MODE_SSGCM
    #         if self._SenecOnline._app_last_wallbox_modes_lc[pos] is not None:
    #             mode = self._SenecOnline._app_last_wallbox_modes_lc[pos]
    #         elif self._SenecOnline._app_raw_wallbox[pos] is not None:
    #             pass
    #
    #     await self.set_wallbox_mode_post_int(pos=pos, local_value=mode)
    #     if sync and self._SenecOnline is not None:
    #         await self._SenecOnline.app_set_wallbox_mode(local_mode_to_set=mode, wallbox_num=(pos + 1), sync=False)

    def read_array_data(self, section_key: str, array_values_key) -> []:
        if self._raw is not None and section_key in self._raw and array_values_key in self._raw[section_key]:
            if self._OVERWRITES[section_key + "_" + array_values_key]["TS"] + 5 > time():
                return self._OVERWRITES[section_key + "_" + array_values_key]["VALUE"]
            else:
                return self._raw[section_key][array_values_key]

    async def switch_array(self, switch_array_key, array_pos, value):
        return await getattr(self, 'switch_array_' + str(switch_array_key))(array_pos, value)

    """NUMBER ARRAY VALUES FROM HERE…"""

    @property
    def sockets_lower_limit(self) -> [int]:
        return self.read_array_data(SENEC_SECTION_SOCKETS, "LOWER_LIMIT")

    async def set_nva_sockets_lower_limit(self, pos: int, value: float):
        await self.set_nva_post(SENEC_SECTION_SOCKETS, "LOWER_LIMIT", pos, 2, "u1", int(value))

    @property
    def sockets_upper_limit(self) -> [int]:
        return self.read_array_data(SENEC_SECTION_SOCKETS, "UPPER_LIMIT")

    async def set_nva_sockets_upper_limit(self, pos: int, value: float):
        await self.set_nva_post(SENEC_SECTION_SOCKETS, "UPPER_LIMIT", pos, 2, "u1", int(value))

    @property
    def sockets_power_on_time(self) -> [int]:
        return self.read_array_data(SENEC_SECTION_SOCKETS, "POWER_ON_TIME")

    async def set_nva_sockets_power_on_time(self, pos: int, value: float):
        await self.set_nva_post(SENEC_SECTION_SOCKETS, "POWER_ON_TIME", pos, 2, "u1", int(value))

    @property
    def sockets_switch_on_hour(self) -> [int]:
        return self.read_array_data(SENEC_SECTION_SOCKETS, "SWITCH_ON_HOUR")

    async def set_nva_sockets_switch_on_hour(self, pos: int, value: float):
        await self.set_nva_post(SENEC_SECTION_SOCKETS, "SWITCH_ON_HOUR", pos, 2, "u8", int(value))

    @property
    def sockets_switch_on_minute(self) -> [int]:
        return self.read_array_data(SENEC_SECTION_SOCKETS, "SWITCH_ON_MINUTE")

    async def set_nva_sockets_switch_on_minute(self, pos: int, value: float):
        await self.set_nva_post(SENEC_SECTION_SOCKETS, "SWITCH_ON_MINUTE", pos, 2, "u8", int(value))

    @property
    def sockets_time_limit(self) -> [int]:
        return self.read_array_data(SENEC_SECTION_SOCKETS, "TIME_LIMIT")

    async def set_nva_sockets_time_limit(self, pos: int, value: float):
        await self.set_nva_post(SENEC_SECTION_SOCKETS, "TIME_LIMIT", pos, 2, "u1", int(value))

    @property
    def wallbox_1_set_icmax_extrema(self) -> [float]:
        if self._SenecOnline is not None:
            wb_data = self._SenecOnline._app_get_wallbox_object_at_index(0)
            return self._wallbox_set_icmax_extrema(wb_data)
        return None

    @property
    def wallbox_2_set_icmax_extrema(self) -> [float]:
        if self._SenecOnline is not None:
            wb_data = self._SenecOnline._app_get_wallbox_object_at_index(1)
            return self._wallbox_set_icmax_extrema(wb_data)
        return None

    @property
    def wallbox_3_set_icmax_extrema(self) -> [float]:
        if self._SenecOnline is not None:
            wb_data = self._SenecOnline._app_get_wallbox_object_at_index(2)
            return self._wallbox_set_icmax_extrema(wb_data)
        return None

    @property
    def wallbox_4_set_icmax_extrema(self) -> [float]:
        if self._SenecOnline is not None:
            wb_data = self._SenecOnline._app_get_wallbox_object_at_index(3)
            return self._wallbox_set_icmax_extrema(wb_data)
        return None

    def _wallbox_set_icmax_extrema(self, wb_data):
        if len(wb_data) > 0:
            # OLD-API CODE
            # if "maxPossibleChargingCurrentInA" in wb_data and "minPossibleChargingCurrentInA" in wb_data:
            #     return [float(wb_data["minPossibleChargingCurrentInA"]),
            #             float(wb_data["maxPossibleChargingCurrentInA"])]

            current_data = wb_data.get("chargingCurrents", {})
            # if "minPossibleCharging" in current_data and "???" in current_data:
            #     return [float(current_data["minPossibleCharging"]), float(current_data["???"])]

            # 2025/08/03 using a hardcoded MAX value of 16.02 for now - since with API changes, no
            # value similar to 'maxPossibleChargingCurrentInA' can be found
            if "minPossibleCharging" in current_data:
                return [float(current_data["minPossibleCharging"]), 16.02]  # 16.02 is the max value for SSGCM_3
        return None

    @property
    def wallbox_set_icmax(self) -> [float]:
        return self.read_array_data(SENEC_SECTION_WALLBOX, "SET_ICMAX")

    async def set_nva_wallbox_set_icmax(self, pos: int, value: float, sync: bool = True, verify_state: bool = True):
        if verify_state:
            if self._SenecOnline is not None:
                local_mode = self._SenecOnline._app_get_local_wallbox_mode_from_api_values(pos)
            else:
                local_mode = "no-bridge-avail"
        else:
            local_mode = LOCAL_WB_MODE_SSGCM_3

        if local_mode == LOCAL_WB_MODE_SSGCM_3:  # or local_mode == LOCAL_WB_MODE_SSGCM_4:
            await self.set_multi_post(4, pos,
                                      SENEC_SECTION_WALLBOX, "SET_ICMAX", "fl", value,
                                      SENEC_SECTION_WALLBOX, "MIN_CHARGING_CURRENT", "fl", value)

            if sync and self._SenecOnline is not None:
                await self._SenecOnline.app_set_wallbox_icmax(value_to_set=value, wallbox_num=(pos + 1), sync=False)
        else:
            _LOGGER.debug(
                f"Ignoring 'set_wallbox_{(pos + 1)}_set_icmax' to '{value}' since current mode is: {local_mode}")

    @property
    def wallbox_set_idefault(self) -> [float]:
        return self.read_array_data(SENEC_SECTION_WALLBOX, "SET_IDEFAULT")

    async def set_nva_wallbox_set_idefault(self, pos: int, value: float):
        await self.set_nva_post(SENEC_SECTION_WALLBOX, "SET_IDEFAULT", pos, 4, "fl", value)

    async def set_number_value_array(self, array_key: str, array_pos: int, value: float):
        return await getattr(self, 'set_nva_' + str(array_key))(array_pos, value)

    @property
    def wallbox_1_mode(self) -> str:
        if self._SenecOnline is not None:
            return self._SenecOnline._app_get_local_wallbox_mode_from_api_values(0)
        return LOCAL_WB_MODE_UNKNOWN

    async def set_string_value_wallbox_1_mode(self, value: str):
        await self.set_wallbox_mode_post_int(0, value)
        if self._SenecOnline is not None:
            await self._SenecOnline.app_set_wallbox_mode(local_mode_to_set=value, wallbox_num=1, sync=False)

    @property
    def wallbox_2_mode(self) -> str:
        if self._SenecOnline is not None:
            return self._SenecOnline._app_get_local_wallbox_mode_from_api_values(1)
        return LOCAL_WB_MODE_UNKNOWN

    async def set_string_value_wallbox_2_mode(self, value: str):
        await self.set_wallbox_mode_post_int(1, value)
        if self._SenecOnline is not None:
            await self._SenecOnline.app_set_wallbox_mode(local_mode_to_set=value, wallbox_num=2, sync=False)

    @property
    def wallbox_3_mode(self) -> str:
        if self._SenecOnline is not None:
            return self._SenecOnline._app_get_local_wallbox_mode_from_api_values(2)
        return LOCAL_WB_MODE_UNKNOWN

    async def set_string_value_wallbox_3_mode(self, value: str):
        await self.set_wallbox_mode_post_int(2, value)
        if self._SenecOnline is not None:
            await self._SenecOnline.app_set_wallbox_mode(local_mode_to_set=value, wallbox_num=3, sync=False)

    @property
    def wallbox_4_mode(self) -> str:
        if self._SenecOnline is not None:
            return self._SenecOnline._app_get_local_wallbox_mode_from_api_values(3)
        return LOCAL_WB_MODE_UNKNOWN

    async def set_string_value_wallbox_4_mode(self, value: str):
        await self.set_wallbox_mode_post_int(3, value)
        if self._SenecOnline is not None:
            await self._SenecOnline.app_set_wallbox_mode(local_mode_to_set=value, wallbox_num=4, sync=False)

    async def set_wallbox_mode_post_int(self, pos: int, local_value: str):
        if local_value == LOCAL_WB_MODE_LOCKED:
            await self.set_multi_post(4, pos,
                                      SENEC_SECTION_WALLBOX, "PROHIBIT_USAGE", "u8", 1,
                                      SENEC_SECTION_WALLBOX, "SMART_CHARGE_ACTIVE", "u8", 0)
        elif local_value == LOCAL_WB_MODE_SSGCM_3:
            await self.set_multi_post(4, pos,
                                      SENEC_SECTION_WALLBOX, "PROHIBIT_USAGE", "u8", 0,
                                      SENEC_SECTION_WALLBOX, "SMART_CHARGE_ACTIVE", "u8", 3)
        elif local_value == LOCAL_WB_MODE_SSGCM_4:
            await self.set_multi_post(4, pos,
                                      SENEC_SECTION_WALLBOX, "PROHIBIT_USAGE", "u8", 0,
                                      SENEC_SECTION_WALLBOX, "SMART_CHARGE_ACTIVE", "u8", 4)
        elif local_value == LOCAL_WB_MODE_FASTEST:
            await self.set_multi_post(4, pos,
                                      SENEC_SECTION_WALLBOX, "PROHIBIT_USAGE", "u8", 0,
                                      SENEC_SECTION_WALLBOX, "SMART_CHARGE_ACTIVE", "u8", 0)

    async def set_string_value(self, key: str, value: str):
        return await getattr(self, 'set_string_value_' + key)(value)

    """NORMAL NUMBER HANDLING… currently no 'none-array' entities are implemented"""

    async def set_number_value(self, a_key: str, value: float):
        # this will cause a method not found exception…
        return await getattr(self, 'set_nv_' + a_key)(value)

    async def switch_array_post(self, section_key: str, value_key: str, pos: int, array_length: int, value: bool):
        post_data = {}
        self.prepare_post_data(post_data, array_length, pos, section_key, value_key, "u8", value=(1 if value else 0))
        await self._write(post_data)

    async def set_nva_post(self, section_key: str, value_key: str, pos: int, array_length: int, data_type: str, value):
        post_data = {}
        self.prepare_post_data(post_data, array_length, pos, section_key, value_key, data_type, value)
        await self._write(post_data)

    async def set_multi_post(self, array_length: int, pos: int,
                             section_key1: str, value_key1: str, data_type1: str, value1,
                             section_key2: str, value_key2: str, data_type2: str, value2
                             ):
        post_data = {}
        self.prepare_post_data(post_data, array_length, pos, section_key1, value_key1, data_type1, value1)
        self.prepare_post_data(post_data, array_length, pos, section_key2, value_key2, data_type2, value2)
        await self._write(post_data)

    def prepare_post_data(self, post_data: dict, array_length: int, pos: int, section_key: str, value_key: str,
                          data_type: str, value):
        self._OVERWRITES[section_key + "_" + value_key].update({"VALUE": self._raw[section_key][value_key]})
        self._OVERWRITES[section_key + "_" + value_key]["VALUE"][pos] = value
        self._OVERWRITES[section_key + "_" + value_key]["TS"] = time()

        value_data = [""] * array_length
        self._raw[section_key][value_key][pos] = value
        if data_type == "u1":
            value_data[pos] = "u1_" + util.get_as_hex(int(value), 4)
        elif data_type == "u8":
            value_data[pos] = "u8_" + util.get_as_hex(int(value), 2)
        elif data_type == "fl":
            value_data[pos] = "fl_" + util.get_float_as_IEEE754_hex(float(value))

        if section_key in post_data:
            post_data[section_key][value_key] = value_data
        else:
            post_data[section_key] = {value_key: value_data}


class InverterLocal:
    """Senec Home Inverter addon"""

    _keepAliveHeaders = {
        "Connection": "keep-alive",
        "Keep-Alive": "timeout=60, max=0",
    }

    def __init__(self, host, inv_session, integ_version: str = None):
        self._integration_version = integ_version if integ_version is not None else "UNKNOWN"
        _LOGGER.info(f"__init__() -> (re)starting Inverter integration v{self._integration_version} for host: '{host}'")
        self.host = host
        self.inv_session: aiohttp.websession = inv_session
        self.url1 = f"http://{host}/all.xml"
        self.url2 = f"http://{host}/measurements.xml"
        self.url3 = f"http://{host}/versions.xml"
        self.url_yield = f"http://{host}/yields.json?total=1"
        self._version_infos = ''
        self._has_bdc = False
        self._raw = None
        self._raw_version = None
        self._YIELD_DATA_READ_TS = 0
        self._timeout = aiohttp.ClientTimeout(total=10, connect=None, sock_connect=None, sock_read=None, ceil_threshold=5)

    def dict_data(self) -> dict:
        # will be called by the UpdateCoordinator (to get the current data)
        return {"data": self._raw, "version": self._raw_version}

    async def update_version(self):
        await self.read_inverter_version()

    def _process_sw_hw_entry(self, a_entry, last_dev):
        """Process a single entry, handling both list items and dict keys"""
        if '@Device' not in a_entry:
            return

        a_dev = a_entry["@Device"]
        if not self._has_bdc:
            self._has_bdc = a_dev == 'BDC'

        # Handle device separation
        if a_dev != last_dev:
            if len(self._version_infos) > 0:
                self._version_infos = f"{self._version_infos} \n"
            self._version_infos = f"{self._version_infos} [{a_dev}]:\t"
        else:
            if len(self._version_infos) > 0:
                self._version_infos = f"{self._version_infos} | "

        # Add version info
        if '@Name' in a_entry and '@Version' in a_entry:
            self._version_infos = f'{self._version_infos + a_entry["@Name"]} v{a_entry["@Version"]}'
        elif '@Device' in a_entry and '@Version' in a_entry:
            self._version_infos = f'{self._version_infos + a_entry["@Device"]} v{a_entry["@Version"]}'

        return a_dev

    async def read_inverter_version(self):
        async with self.inv_session.get(self.url3, headers=self._keepAliveHeaders) as res:
            res.raise_for_status()
            txt = await res.text()
            self._raw_version = xmltodict.parse(txt, force_list=('Software', 'Hardware', ))
            last_dev = ''
            if self._raw_version is not None:
                if "root" in self._raw_version:
                    if "Device" in self._raw_version["root"]:
                        a_device_dict = self._raw_version["root"]["Device"]
                        if not self._has_bdc and "@Name" in a_device_dict:
                            self._has_bdc = a_device_dict["@Name"].upper().endswith("_BDC")
                        if "Versions" in a_device_dict:
                            a_version_dict = a_device_dict["Versions"]
                            a_dict = None
                            if "Software" in a_version_dict:
                                a_dict = a_version_dict["Software"]
                            elif "Hardware" in a_version_dict:
                                a_dict = a_version_dict["Hardware"]

                            if a_dict is not None and len(a_dict) > 0:
                                if isinstance(a_dict, list):
                                    for a_entry in a_dict:
                                        result = self._process_sw_hw_entry(a_entry, last_dev)
                                        if result:
                                            last_dev = result
                                elif isinstance(a_dict, dict):
                                    for a_entry_key in a_dict.keys():
                                        result = self._process_sw_hw_entry(a_entry_key, last_dev)
                                        if result:
                                            last_dev = result

    async def update(self):
        await self.read_inverter_with_retry(retry=True)

    async def read_inverter_with_retry(self, retry: bool = False):
        try:
            await self.read_inverter()
        except ClientConnectorError as exc:
            _LOGGER.info(f"{exc}")
            if retry:
                await asyncio.sleep(5)
                await self.read_inverter_with_retry(retry=False)

    async def read_inverter(self):
        async with self.inv_session.get(url=f"{self.url2}?{datetime.now()}", headers=self._keepAliveHeaders, timeout=self._timeout) as res:
            res.raise_for_status()
            txt = await res.text()
            self._raw = xmltodict.parse(txt)
            if self._raw is not None:
                if "root" in self._raw:
                    if "Device" in self._raw["root"]:
                        if "Measurements" in self._raw["root"]["Device"]:
                            if "Measurement" in self._raw["root"]["Device"]["Measurements"]:
                                m_dict = self._raw["root"]["Device"]["Measurements"]["Measurement"]
                                for a_dict in m_dict:
                                    if '@Type' in a_dict and '@Value' in a_dict:
                                        match a_dict["@Type"]:
                                            case 'AC_Voltage':
                                                self._ac_voltage = a_dict["@Value"]
                                            case 'AC_Current':
                                                self._ac_current = a_dict["@Value"]
                                            case 'AC_Power':
                                                self._ac_power = a_dict["@Value"]
                                            case 'AC_Power_fast':
                                                self._ac_power_fast = a_dict["@Value"]
                                            case 'AC_Frequency':
                                                self._ac_frequency = a_dict["@Value"]

                                            case 'BDC_BAT_Voltage':
                                                self._bdc_bat_voltage = a_dict["@Value"]
                                            case 'BDC_BAT_Current':
                                                self._bdc_bat_current = a_dict["@Value"]
                                            case 'BDC_BAT_Power':
                                                self._bdc_bat_power = a_dict["@Value"]
                                            case 'BDC_LINK_Voltage':
                                                self._bdc_link_voltage = a_dict["@Value"]
                                            case 'BDC_LINK_Current':
                                                self._bdc_link_current = a_dict["@Value"]
                                            case 'BDC_LINK_Power':
                                                self._bdc_link_power = a_dict["@Value"]

                                            case 'DC_Voltage1':
                                                self._dc_voltage1 = a_dict["@Value"]
                                            case 'DC_Voltage2':
                                                self._dc_voltage2 = a_dict["@Value"]
                                            case 'DC_Current1':
                                                self._dc_current1 = a_dict["@Value"]
                                            case 'DC_Current2':
                                                self._dc_current2 = a_dict["@Value"]
                                            case 'LINK_Voltage':
                                                self._link_voltage = a_dict["@Value"]

                                            case 'GridPower':
                                                self._gridpower = a_dict["@Value"]
                                            case 'GridConsumedPower':
                                                self._gridconsumedpower = a_dict["@Value"]
                                            case 'GridInjectedPower':
                                                self._gridinjectedpower = a_dict["@Value"]
                                            case 'OwnConsumedPower':
                                                self._ownconsumedpower = a_dict["@Value"]

                                            case 'Derating':
                                                self._derating = float(100.0 - float(a_dict["@Value"]))

        if self._YIELD_DATA_READ_TS + 300 < time():
            async with self.inv_session.get(url=f"{self.url_yield}&_={time()}", headers=self._keepAliveHeaders, timeout=self._timeout) as res:
                self._YIELD_DATA_READ_TS = time()
                res.raise_for_status()
                yield_data = await res.json()
                if "TotalCurves" in yield_data and "Datasets" in yield_data["TotalCurves"]:
                    # Extract the PV1 dataset
                    pv1_yield_data = next(dataset["Data"] for dataset in yield_data["TotalCurves"]["Datasets"] if dataset["Type"] == "PV1")

                    # Calculate the sum of all Data fields in PV1
                    pv1_yield_sum = sum(entry["Data"] for entry in pv1_yield_data)
                    if pv1_yield_sum > 0:
                        self._yield_pv1_total = pv1_yield_sum / 1000
                        if self._raw is not None:
                            self._raw["yield_pv1_total"] = pv1_yield_sum / 1000

                    # Extract the Produced dataset
                    produced_yield_data = next(dataset["Data"] for dataset in yield_data["TotalCurves"]["Datasets"] if dataset["Type"] == "Produced")

                    # Calculate the sum of all Data fields in 'Produced'
                    prod_yield_sum = sum(entry["Data"] for entry in produced_yield_data)
                    if prod_yield_sum > 0:
                        self._yield_produced_total = prod_yield_sum / 1000
                        if self._raw is not None:
                            self._raw["yield_produced_total"] = prod_yield_sum / 1000

    @property
    def device_versions(self) -> str:
        return self._version_infos

    @property
    def has_bdc(self) -> bool:
        return self._has_bdc

    @property
    def device_name(self) -> str:
        return self._raw_version["root"]["Device"]["@Name"]

    @property
    def device_serial(self) -> str:
        return self._raw_version["root"]["Device"]["@Serial"]

    @property
    def device_netbiosname(self) -> str:
        return self._raw_version["root"]["Device"]["@NetBiosName"]

    # @property
    # def measurements(self) -> dict:
    #    if ('Measurements' in self._raw["root"]["Device"] and "Measurement" in self._raw["root"]["Device"][
    #        "Measurements"]):
    #        return self._raw["root"]["Device"]["Measurements"]["Measurement"]

    # @property
    # def versions(self) -> dict:
    #    if ('Versions' in self._raw_version["root"]["Device"] and 'Software' in self._raw_version["root"]["Device"]["Versions"]):
    #        return self._raw_version["root"]["Device"]["Versions"]["Software"]

    @property
    def ac_voltage(self) -> float:
        if (hasattr(self, '_ac_voltage')):
            return self._ac_voltage
        return None

    @property
    def ac_current(self) -> float:
        if (hasattr(self, '_ac_current')):
            return self._ac_current
        return None

    @property
    def ac_power(self) -> float:
        if (hasattr(self, '_ac_power')):
            return self._ac_power
        return None

    @property
    def ac_power_fast(self) -> float:
        if (hasattr(self, '_ac_power_fast')):
            return self._ac_power_fast
        return None

    @property
    def ac_frequency(self) -> float:
        if (hasattr(self, '_ac_frequency')):
            return self._ac_frequency
        return None

    @property
    def dc_voltage1(self) -> float:
        if (hasattr(self, '_dc_voltage1')):
            return self._dc_voltage1
        return None

    @property
    def dc_voltage2(self) -> float:
        if (hasattr(self, '_dc_voltage2')):
            return self._dc_voltage2
        return None

    @property
    def bdc_bat_voltage(self) -> float:
        if (hasattr(self, '_bdc_bat_voltage')):
            return self._bdc_bat_voltage
        return None

    @property
    def bdc_bat_current(self) -> float:
        if (hasattr(self, '_bdc_bat_current')):
            return self._bdc_bat_current
        return None

    @property
    def bdc_bat_power(self) -> float:
        if (hasattr(self, '_bdc_bat_power')):
            return self._bdc_bat_power
        return None

    @property
    def bdc_link_voltage(self) -> float:
        if (hasattr(self, '_bdc_link_voltage')):
            return self._bdc_link_voltage
        return None

    @property
    def bdc_link_current(self) -> float:
        if (hasattr(self, '_bdc_link_current')):
            return self._bdc_link_current
        return None

    @property
    def bdc_link_power(self) -> float:
        if (hasattr(self, '_bdc_link_power')):
            return self._bdc_link_power
        return None

    @property
    def dc_current1(self) -> float:
        if (hasattr(self, '_dc_current1')):
            return self._dc_current1
        return None

    @property
    def dc_current2(self) -> float:
        if (hasattr(self, '_dc_current2')):
            return self._dc_current2
        return None

    @property
    def link_voltage(self) -> float:
        if (hasattr(self, '_link_voltage')):
            return self._link_voltage
        return None

    @property
    def gridpower(self) -> float:
        if (hasattr(self, '_gridpower')):
            return self._gridpower
        return None

    @property
    def gridconsumedpower(self) -> float:
        if (hasattr(self, '_gridconsumedpower')):
            return self._gridconsumedpower
        return None

    @property
    def gridinjectedpower(self) -> float:
        if (hasattr(self, '_gridinjectedpower')):
            return self._gridinjectedpower
        return None

    @property
    def ownconsumedpower(self) -> float:
        if (hasattr(self, '_ownconsumedpower')):
            return self._ownconsumedpower
        return None

    @property
    def derating(self) -> float:
        if (hasattr(self, '_derating')):
            return self._derating
        return None

    @property
    def yield_pv_total(self) -> float:
        if (hasattr(self, '_yield_pv1_total')):
            return self._yield_pv1_total
        return None

    @property
    def yield_produced_total(self) -> float:
        if (hasattr(self, '_yield_produced_total')):
            return self._yield_produced_total
        return None


def app_has_dict_timeseries_with_values(a_dict:dict, ts_key_name:str="timeSeries") -> bool:
    if (a_dict is None or
            ts_key_name not in a_dict or
            len(a_dict[ts_key_name]) == 0 or
            "measurements" not in a_dict[ts_key_name][0] or
            "values" not in a_dict[ts_key_name][0]["measurements"]):
        _LOGGER.debug(f"Data '{a_dict}' does not contain the expected structure for timeseries measurements.")
        return False
    return True

def app_summ_total_dict_values(src_dict, dest_dict, ts_key_name:str="timeSeries"):
    """Add corresponding values from two measurement dictionaries"""
    #src_dict = app_aggregate_timeseries_data_if_needed(src_dict)

    # Get the value arrays from both dictionaries
    src_values = src_dict[ts_key_name][0]["measurements"]["values"]
    dest_values = dest_dict[ts_key_name][0]["measurements"]["values"]

    # Add corresponding values together
    summed_values = [src_val + dest_val for src_val, dest_val in zip(src_values, dest_values)]

    # Create a result dictionary with the structure of the first one
    dest_dict[ts_key_name][0]["measurements"]["values"] = summed_values
    return dest_dict

def app_aggregate_timeseries_data_if_needed(data, ts_key_name:str="timeSeries"):
    if data is None or not data[ts_key_name] or len(data[ts_key_name]) == 1:
        return data

    first_date = data[ts_key_name][0]['date']
    total_duration = 0
    total_values = [0] * len(data["measurements"])

    for ts in data[ts_key_name]:
        total_duration += ts["measurements"]["durationInSeconds"]
        values = ts["measurements"]["values"]
        for i in range(len(values)):
            total_values[i] += values[i]

    return {
        "measurements": data["measurements"],
        "totals": data["totals"] if "totals" in data else {},
        ts_key_name: [{
            "date": first_date,
            "measurements": {
                "durationInSeconds": total_duration,
                "values": total_values
            }
        }]
    }

STRFTIME_DATE_FORMAT:Final = '%Y-%m-%dT%H:%M:%SZ'
def app_get_utc_date_start(year, month:int = 1, day:int = -1):
    # January 1st at 00:00:00 UTC+1 of the year
    if day < 1:
        day = 1
    return datetime(year, month, day, 0, 0, 0).astimezone(timezone.utc).strftime(STRFTIME_DATE_FORMAT)

def app_get_utc_date_end(year, month:int = 12, day:int = -1):
    # December 31st at 23:59:59 UTC+1 of the year
    if day < 1:
        day = calendar.monthrange(year, month)[1]
    return (datetime(year, month, day, 0, 0, 0) + timedelta(days=1)).astimezone(timezone.utc).strftime(STRFTIME_DATE_FORMAT)

class ReConfigurationRequired(Exception):
    """The provided TOTP Secret could not be validated"""

class SenecOnline:

    USE_DEFAULT_USER_AGENT:Final = True

    def __init__(self, user, pwd, totp, web_session, app_master_plant_number: int = 0, lang: str = "en", options: dict = None,
                 storage_path: Path = None, tokens_location: str = None, integ_version: str = None):
        self._integration_version = integ_version if integ_version is not None else "UNKNOWN"
        self._init_user_agents()
        self._lang = lang
        if options is not None:
            _LOGGER.info(f"__init__() -> (re)starting SenecOnline v{self._integration_version} for user: '{util.mask_string(user)}' with options: {options}")
        else:
            _LOGGER.info(f"__init__() -> (re)starting SenecOnline v{self._integration_version} for user: '{util.mask_string(user)}' without options")

        if options is not None and QUERY_WALLBOX_KEY in options:
            self._QUERY_WALLBOX = options[QUERY_WALLBOX_KEY]
        else:
            self._QUERY_WALLBOX = False

        # Check if spare capacity is in options
        if options is not None and QUERY_SPARE_CAPACITY_KEY in options:
            self._QUERY_SPARE_CAPACITY = options[QUERY_SPARE_CAPACITY_KEY]
        else:
            self._QUERY_SPARE_CAPACITY = False
        # Variable to save latest update time for spare capacity
        self._QUERY_SPARE_CAPACITY_TS = 0

        # check if peak shaving is in options
        if options is not None and QUERY_PEAK_SHAVING_KEY in options:
            self._QUERY_PEAK_SHAVING = options[QUERY_PEAK_SHAVING_KEY]
        else:
            self._QUERY_PEAK_SHAVING = False
        # Variable to save the latest update time for peak shaving
        self._QUERY_PEAK_SHAVING_TS = 0

        if options is not None and QUERY_TOTALS_KEY in options:
            self._QUERY_TOTALS = options[QUERY_TOTALS_KEY]
        else:
            self._QUERY_TOTALS = False
        # Variable to save the latest update time for Total data…
        self._QUERY_TOTALS_TS = 0

        if options is not None and QUERY_SYSTEM_DETAILS_KEY in options:
            self._QUERY_SYSTEM_DETAILS = options[QUERY_SYSTEM_DETAILS_KEY]
        else:
            self._QUERY_SYSTEM_DETAILS = False

        # be default Senec's API does not inlcude the energy consumed by the wallbox in the
        # house consumption data...
        if options is not None and CONF_INCLUDE_WALLBOX_IN_HOUSE_CONSUMPTION in options:
            self._INCLUDE_WALLBOX_IN_HOUSE_CONSUMPTION = options[CONF_INCLUDE_WALLBOX_IN_HOUSE_CONSUMPTION]
        else:
            self._INCLUDE_WALLBOX_IN_HOUSE_CONSUMPTION = True

        # Variable to save the latest update time for system-details/system_state data…
        self._QUERY_SYSTEM_DETAILS_TS = 0
        self._QUERY_SYSTEM_STATE_TS = 0

        # Variable to save the latest update time for SG-Ready state
        self._QUERY_SGREADY_STATE_TS = 0
        # Variable to save the latest update time for SG-Ready configuration
        self._QUERY_SGREADY_CONF_TS = 0

        self.web_session: aiohttp.websession = web_session

        self._SENEC_USERNAME = user
        self._SENEC_PASSWORD = pwd

        if totp is not None:
            # make sure that the TOTP secret is a string without spaces
            if ' ' in totp:
                totp  = totp.replace(' ', '')

            try:
                if len(pyotp.TOTP(totp).now()) != 6:
                    raise ValueError("Invalid TOTP secret length")
            except BaseException as exc:
                _LOGGER.error(f"Invalid TOTP secret: {util.mask_string(totp)} - please check your configuration! - {type(exc).__name__} - {exc}")
                totp = None
                raise ReConfigurationRequired(exc)

        # if we passed all tests, we can set the propperty
        self._SENEC_TOTP_SECRET = totp

        ###################################
        # mein-senec.de
        ###################################
        self.web_totp_required = False
        self._WEB_BASE_URL          = "https://mein-senec.de"
        self._WEB_GET_CUSTOMER      = f"{self._WEB_BASE_URL}/endkunde/api/context/getEndkunde"
        self._WEB_GET_SYSTEM_INFO   = f"{self._WEB_BASE_URL}/endkunde/api/context/getAnlageBasedNavigationViewModel?anlageNummer=%s"

        self._WEB_GET_OVERVIEW_URL  = f"{self._WEB_BASE_URL}/endkunde/api/status/getstatusoverview.php?anlageNummer=%s"
        self._WEB_GET_STATUS        = f"{self._WEB_BASE_URL}/endkunde/api/status/getstatus.php?type=%s&period=all&anlageNummer=%s"

        # Calls for spare capacity - Base URL has to be followed by master plant number
        # calls will look like self._WEB_SPARE_CAPACITY_BASE_URL + AnlagenNummer + self._WEB_GET_SPARE_CAPACITY
        self._WEB_SPARE_CAPACITY_BASE_URL = f"{self._WEB_BASE_URL}/endkunde/api/senec/"
        # Call the following URL (GET-Request) in order to get the spare capacity as int in the response body
        self._WEB_GET_SPARE_CAPACITY = "/emergencypower/reserve-in-percent"
        # Call the following URL (Post Request) in order to set the spare capacity
        self._WEB_SET_SPARE_CAPACITY = "/emergencypower?reserve-in-percent="

        # Call for export limit and current peak shaving information - to be followed by master plant number
        self._WEB_GET_PEAK_SHAVING  = f"{self._WEB_BASE_URL}/endkunde/api/peakshaving/getSettings?anlageNummer="
        # Call to set spare capacity information - Base URL
        self._WEB_SET_PEAK_SHAVING = f"{self._WEB_BASE_URL}/endkunde/api/peakshaving/saveSettings?anlageNummer="

        self._WEB_GET_SGREADY_STATE = f"{self._WEB_BASE_URL}/endkunde/api/senec/%s/sgready/state"
        self._WEB_GET_SGREADY_CONF  = f"{self._WEB_BASE_URL}/endkunde/api/senec/%s/sgready/config"
        # {"enabled":false,"modeChangeDelayInMinutes":20,"powerOnProposalThresholdInWatt":2000,"powerOnCommandThresholdInWatt":2500}
        self._WEB_SET_SGREADY_CONF  = f"{self._WEB_BASE_URL}/endkunde/api/senec/%s/sgready"

        # can be used in all api calls, names come from senec website
        self._WEB_REQUEST_KEYS = [
            "accuimport",  # what comes OUT OF the accu
            "accuexport",  # what goes INTO the accu
            "gridimport",  # what comes OUT OF the grid
            "gridexport",  # what goes INTO the grid
            "powergenerated",  # power produced
            "consumption"  # power used
        ]
        # can only be used in some api calls, names come from senec website
        self._WEB_REQUEST_KEYS_EXTRA = [
            "acculevel"  # accu level
        ]

        # WEBDATA STORAGE
        self._web_is_authenticated = False
        self._web_dev_number = None
        self._web_serial_number = None
        self._web_product_name = None
        self._web_raw = None
        self._web_energy_entities = {}
        self._web_power_entities = {}
        self._web_battery_entities = {}
        self._web_spare_capacity = 0  # initialize the spare_capacity with 0
        self._web_peak_shaving_entities = {}
        self._web_sgready_conf_data = {}
        self._web_sgready_mode_code = 0
        self._web_sgready_mode = None
        self.SGREADY_SUPPORTED = False

        # genius - _app_master_plant_number does not have to be the same then _web_master_plant_number…
        self._app_master_plant_number = app_master_plant_number
        self._web_master_plant_number = None

        ###################################
        # SenecApp
        ###################################
        # OpenID related fields…
        self.APP_OPENID_CLIENT_ID: Final        = "endcustomer-app-frontend"
        self.APP_REDIRECT_KEYCLOAK_URI: Final   = "senec-app-auth://keycloak.prod"
        #self.APP_SCOPE: Final           = "email roles profile web-origins meinsenec openid"
        # based on the feedback from @ledermann we can use reduced scope
        self.APP_SCOPE: Final           = "roles profile meinsenec"

        # these fields are all not required - since 'mein-senec.de' will not include a 'code_challenge'
        #self.WEB_OPENID_CLIENT_ID: Final= "meinsenec-login-portal"
        #self.WEB_REDIRECT_URI: Final    = "https://mein-senec.de/login/oauth2/code/login-portal"
        #self.WEB_SCOPE: Final           = "openid"

        SSO_BASE_URL    = "https://sso.senec.com/realms/senec/protocol/openid-connect"
        self.LOGIN_URL  = SSO_BASE_URL + "/auth?redirect_uri={redirect_url}&client_id={client_id}&response_type=code&prompt=login&state={state}&nonce={nonce}&scope={scope}&code_challenge={code_challenge}&code_challenge_method=S256"
        self.TOKEN_URL  = SSO_BASE_URL + "/token"
        self._code_verifier = None

        APP_SYSTEM_BASE_URL         = "https://senec-app-systems-proxy.prod.senec.dev"
        self.APP_SYSTEM_LIST        = APP_SYSTEM_BASE_URL + "/v1/systems"
        self.APP_SYSTEM_DETAILS     = APP_SYSTEM_BASE_URL + "/systems/{master_plant_id}/details"
        self.APP_SYSTEM_STATUS      = APP_SYSTEM_BASE_URL + "/systems/status/{master_plant_id}"

        # post https://senec-app-measurements-proxy.prod.senec.dev/v1/systems/{{SENEC_ANLAGE}}/wallboxes/measurements?wallboxIds=1&resolution=HOUR&from=2025-07-20T22%3A00%3A00Z&to=2025-07-21T22%3A00%3A00Z
        # patch https://senec-app-wallbox-proxy.prod.senec.dev/v1/systems/{{SENEC_ANLAGE}}/wallboxes/1/locked/true
        # patch https://senec-app-wallbox-proxy.prod.senec.dev/v1/systems/{{SENEC_ANLAGE}}/wallboxes/1/locked/false
        # THIS IS probably NOT correct!!!
        APP_WALLBOX_BASE_URL        = "https://senec-app-wallbox-proxy.prod.senec.dev"
        # THIS DOES NOT EXISTs anylonger…
        #self.APP_SET_WALLBOX        = APP_WALLBOX_BASE_URL + "/v1/systems/{master_plant_id}/wallboxes/{wb_id}"

        self.APP_WALLBOX_SEARCH     = APP_WALLBOX_BASE_URL + "/v1/systems/wallboxes/search"
        self.APP_SET_WALLBOX_LOCK   = APP_WALLBOX_BASE_URL + "/v1/systems/{master_plant_id}/wallboxes/{wb_id}/locked/{lc_lock_state}"
        self.APP_SET_WALLBOX_FC     = APP_WALLBOX_BASE_URL + "/v1/systems/{master_plant_id}/wallboxes/{wb_id}/settings/fast-charge"
        self.APP_SET_WALLBOX_SC     = APP_WALLBOX_BASE_URL + "/v1/systems/{master_plant_id}/wallboxes/{wb_id}/settings/solar-charge"

        APP_ABILITIES_BASE_URL      = "https://senec-app-abilities-proxy.prod.senec.dev"
        self.APP_ABILITIES_LIST     = APP_ABILITIES_BASE_URL + "/abilities/packages/{master_plant_id}"

        self.APP_MEASURE_BASE_URL       = "https://senec-app-measurements-proxy.prod.senec.dev"
        self.APP_MEASURE_DATA_AVAIL     = self.APP_MEASURE_BASE_URL + "/v1/systems/{master_plant_id}/data-availability/timespan?timezone={tz}"
        self.APP_MEASURE_DASHBOARD      = self.APP_MEASURE_BASE_URL + "/v1/systems/{master_plant_id}/dashboard"
        self.APP_MEASURE_TOTAL          = self.APP_MEASURE_BASE_URL + "/v1/systems/{master_plant_id}/measurements?resolution={res_type}&from={from_val}&to={to_val}"
        self.APP_MEASURE_TOTAL_WITH_WB  = self.APP_MEASURE_BASE_URL + "/v1/systems/{master_plant_id}/measurements?resolution={res_type}&from={from_val}&to={to_val}&wallboxIds={wb_ids}"
        self.APP_MEASURE_WB_TOTAL       = self.APP_MEASURE_BASE_URL + "/v1/systems/{master_plant_id}/wallboxes/measurements?wallboxIds={wb_id}&resolution={res_type}&from={from_val}&to={to_val}"

        # https://senec-app-systems-proxy.prod.senec.dev/systems/settings/user-energy-settings?systemId={master_plant_id}
        # -> http 204 NO-CONTENT

        # app-token related stuff…
        self._storage_path = storage_path
        if tokens_location is None:
            file_instance = ""
            if self._app_master_plant_number > 0:
                file_instance = f"_{self._app_master_plant_number}"

            if self._storage_path is not None:
                self._app_stored_tokens_location = str(self._storage_path.joinpath(DOMAIN, f"{user}@@@{file_instance}_access_token.txt"))
            else:
                self._app_stored_tokens_location = f".storage/{DOMAIN}/{user}@@@{file_instance}_access_token.txt"

        else:
            self._app_stored_tokens_location = tokens_location

        self._app_token_object = {}
        self._app_is_authenticated = False
        self._app_token = None
        # the '_app_master_plant_id' will be used in any further request to
        # the senec endpoints as part of the URL...
        self._app_master_plant_id = None
        self._app_serial_number = None
        self._app_wallbox_num_max = 4
        self._app_data_start_ts = -1
        self._app_data_end_ts = -1
        self._app_abilities = None # list of available features []

        # done…
        self._app_raw_now = None
        self._app_raw_battery_device_state = None
        self._app_raw_today = None
        self._app_raw_system_details = None
        self._app_raw_system_state_obj = None
        self._app_raw_total = None
        self._app_raw_wb_total = [None, None, None, None]
        # for our TOTAL values…
        self._static_TOTAL_SUMS_PREV_YEARS = None
        self._static_TOTAL_SUMS_PREV_MONTHS = None
        self._static_TOTAL_SUMS_PREV_DAYS = None
        self._static_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_YEARS = 1970
        self._static_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_MONTHS = 0
        self._static_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_DAYS = 0

        self._app_raw_wallbox = [None, None, None, None]
        self._static_A_WALLBOX_STORAGE = {
            "years":        self._static_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_YEARS,
            "years_data":   self._static_TOTAL_SUMS_PREV_YEARS,
            "months":       self._static_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_MONTHS,
            "months_data":  self._static_TOTAL_SUMS_PREV_MONTHS,
            "days":         self._static_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_DAYS,
            "days_data":    self._static_TOTAL_SUMS_PREV_DAYS}
        self._static_TOTAL_WALLBOX_DATA = [copy.deepcopy(self._static_A_WALLBOX_STORAGE) for _ in range(4)]
        self._SenecLocal = None

    def setSenecLocal(self, senecLocal):                
        if self.web_session is not None:
            _LOGGER.debug(f"SenecOnline initialized, establish bridge between SenecLocal and SenecOnline")
            self._SenecLocal = senecLocal
            # ok local-polling (lala.cgi) is already existing…
            if self._SenecLocal._QUERY_WALLBOX_APPAPI:
                self._QUERY_WALLBOX = True
                _LOGGER.debug("APP-API: will query WALLBOX data (cause 'lala_cgi._QUERY_WALLBOX_APPAPI' is True)")
        else:
            _LOGGER.debug(f"SenecOnline initialized [RAW - no websession]")

    async def _rename_token_file_if_needed(self, user:str):
        """Move a legacy token file to new _app_master_plant_number dependant if it exists"""
        if self._app_master_plant_number > 0:
            file_instance = f"_{self._app_master_plant_number}"

            # only if the _app_master_plant_number is > 0 ...
            if self._storage_path is not None:
                stored_tokens_location_legacy = str(self._storage_path.joinpath(DOMAIN, f"{user}_access_token.txt"))
            else:
                stored_tokens_location_legacy = f".storage/{DOMAIN}/{user}_access_token.txt"

            try:
                # Check if the legacy file exists
                if os.path.isfile(stored_tokens_location_legacy):
                    _LOGGER.debug(f"Found legacy token at {stored_tokens_location_legacy}, moving to {self._app_stored_tokens_location}")

                    # Move the file (in executor to avoid blocking)
                    await asyncio.get_running_loop().run_in_executor(None, lambda: os.rename(stored_tokens_location_legacy, self._app_stored_tokens_location))
                    _LOGGER.debug(f"Successfully moved token file to new location")
                else:
                    _LOGGER.debug(f"No legacy token file found at {stored_tokens_location_legacy}, nothing to move")

            except Exception as e:
                _LOGGER.warning(f"Failed to move token file: {type(e).__name__} - {e}")

    def _init_user_agents(self):
        self.DEFAULT_USER_AGENT= f"SENEC.Home V2.x/V3/V4 Integration/{self._integration_version} (+https://github.com/marq24/ha-senec-v3)"
        WEB_USER_AGENT: Final = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
        self._default_web_headers = {
            "User-Agent": self.DEFAULT_USER_AGENT if self.USE_DEFAULT_USER_AGENT else WEB_USER_AGENT,
            "Connection": "keep-alive",
            "Keep-Alive": "timeout=60, max=1000",
        }

        phone_model = random.choice(list(PHONE_BUILD_MAPPING.keys()))
        phone_data = PHONE_BUILD_MAPPING[phone_model]
        build_version = random.choice(phone_data["builds"])
        android_version = phone_data["android_version"]
        api_level = phone_data["api_level"]

        APP_WEB_USER_AGENT: Final = f"Mozilla/5.0 (Linux; Android {android_version}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Mobile Safari/537.36"
        APP_APP_USER_AGENT: Final = f"SENEC.App/4.8.1 (com.senecapp; build:1613; Android SDK {api_level}; Model:{phone_model}) okhttp/4.12.0"
        self.APP_SSO_USER_AGENT = f"Dalvik/2.1.0 (Linux; Android {android_version}; {phone_model} Build/{build_version})"

        self._default_app_web_headers = {
            "User-Agent": self.DEFAULT_USER_AGENT if self.USE_DEFAULT_USER_AGENT else APP_WEB_USER_AGENT,
            "Connection": "keep-alive",
            "Keep-Alive": "timeout=60, max=1000",
        }
        self._default_app_headers = {
            "User-Agent": self.DEFAULT_USER_AGENT if self.USE_DEFAULT_USER_AGENT else APP_APP_USER_AGENT,
            "Accept-Encoding": "gzip",
            "Connection": "keep-alive",
            "x-device-type": "mobile"
        }

    def dict_data(self) -> dict:
        # will be called by the UpdateCoordinator (to get the current data)
        return {
            "now": self._app_raw_now,
            "today": self._app_raw_today,
            "total": self._app_raw_total,
            "system_battery_state": self._app_raw_battery_device_state,
            "system_state_object": self._app_raw_system_state_obj,
            "system_details": self._app_raw_system_details,
            "wallbox": self._app_raw_wallbox,
            "wb_total": self._app_raw_wb_total,
            "mein-senec": {
                "raw": self._web_raw,
                "energy_entities": self._web_energy_entities,
                "power_entities": self._web_power_entities,
                "battery_entities": self._web_battery_entities,
                "peak_shaving_entities": self._web_peak_shaving_entities,
                "sgready_conf_data": self._web_sgready_conf_data
            }
        }

    def purge_senec_cookies(self):
        if hasattr(self.web_session, "_cookie_jar"):
            the_jar = getattr(self.web_session, "_cookie_jar")
            the_jar.clear_domain("mein-senec.de")
            the_jar.clear_domain("sso.senec.com")

    def clear_jar(self):
        if hasattr(self.web_session, "_cookie_jar"):
            self.web_session._cookie_jar.clear()

    """Make sure that app and web will be initialized and authenticated before any other calls will be made"""
    async def authenticate_all(self):
        web_login_required = False
        # if we request additionally to the APP-API some values from the mein-senec.de portal,
        # then we MUST first login via SSO to the API, then we can use also mein-senec.de without
        # any additional login (since the web session is already authenticated)
        # Since 2025/08/06 the mein-senec.de portal now force the user to configure/setup TOTP...
        if self._QUERY_SPARE_CAPACITY or self._QUERY_PEAK_SHAVING or self.SGREADY_SUPPORTED:
            web_login_required = True

        # SenecApp stuff…
        if not self._app_is_authenticated:
            # if the web_login is requeired, we ignore any existing tokens
            # and directly login into the API...
            await self.app_authenticate(check_for_existing_tokens = not web_login_required)

        if web_login_required:
            # mein-senec.de Web stuff…
            if not self._web_is_authenticated:
                await self.web_authenticate(do_update=False, throw401=False)
        else:
            # make sure that we do not male web calls by accident (yes 'web_totp_required' is not the correct
            # attribute - but it will work for sure (now)...
            self.web_totp_required = True


    def get_debug_login_data(self):
        return {"app":{
            "isAuth": self._app_is_authenticated,
            "MasterPlantID": self._app_master_plant_id,
            "MasterPlantNumber": self._app_master_plant_number,
            "SerialNumber": self._app_serial_number,
        }, "web":{
            "isAuth": self._web_is_authenticated,
            "MasterPlantNumber": self._web_master_plant_number,
            "SerialNumber": self._web_serial_number,
        }}

    # by default, we update as fast as possible
    _UPDATE_INTERVAL = NO_LIMIT
    _LAST_UPDATE_TS = 0

    async def update(self):
        if self._LAST_UPDATE_TS + UPDATE_INTERVALS[self._UPDATE_INTERVAL] < time():
            success = await self.app_update()
            if not success:
                await self.web_update()

            self._LAST_UPDATE_TS = time()
        else:
            _LOGGER.debug(f"update(): SKIPP UPDATE REQUEST - last update was at {strftime('%Y-%m-%d %H:%M:%S', localtime(self._LAST_UPDATE_TS))} and we are still within the update interval of '{self._UPDATE_INTERVAL}' [{UPDATE_INTERVALS[self._UPDATE_INTERVAL]} seconds]")

    async def app_update(self):
        try:
            if self._app_is_authenticated:
                _LOGGER.info("***** app_update(self) ********")
                if self._QUERY_SYSTEM_DETAILS:
                    # 60min * 60 sec = 3600 sec
                    if self._QUERY_SYSTEM_DETAILS_TS + 3595 < time():
                        # since we also get the case-temp & system-state from the system_details
                        # we call this monster object every time [I dislike this!]
                        await self.app_get_system_details()
                    else:
                        # if we do not query the system_details, we might want/must update the
                        # system_state every 10 minutes
                        if self._QUERY_SYSTEM_STATE_TS + 595 < time():
                            await self.app_get_system_status()

                await self.app_get_dashboard()

                if self._QUERY_TOTALS:
                    # only request the totals at min update of 15 minutes
                    # 15min * 60 sec = 900 sec - 5sec
                    if self._QUERY_TOTALS_TS + 895 < time():
                        the_wb_ids = None
                        if self._INCLUDE_WALLBOX_IN_HOUSE_CONSUMPTION and self._app_wallbox_num_max > 0:
                            the_wb_ids = ",".join(str(i) for i in range(1, self._app_wallbox_num_max + 1))
                        await self.app_update_total(wb_ids=the_wb_ids)
                        if self._QUERY_WALLBOX:
                            await self.app_update_total_all_wallboxes()

                if self._QUERY_WALLBOX:
                    await self.app_update_all_wallboxes()

                if self._QUERY_SPARE_CAPACITY:
                    # 1 day = 24 h = 24 * 60 min = 24 * 60 * 60 sec = 86400 sec
                    # 2025/06/19 - changed to 6h… = 86400/4 = 21600
                    if self._QUERY_SPARE_CAPACITY_TS + 21595 < time():
                        await self.web_update_spare_capacity()

                if self._QUERY_PEAK_SHAVING:
                    # 1 day = 24 h = 24 * 60 min = 24 * 60 * 60 sec = 86400 sec
                    if self._QUERY_PEAK_SHAVING_TS + 86395 < time():
                        await self.web_update_peak_shaving()

                if self.SGREADY_SUPPORTED:
                    # 6h = 6 * 60 min = 6 * 60 * 60 sec = 21600 sec
                    if self._QUERY_SGREADY_STATE_TS + 21595 < time():
                        await self.web_update_sgready_state()
                    # 1 day = 24 h = 24 * 60 min = 24 * 60 * 60 sec = 86400 sec
                    if self._QUERY_SGREADY_CONF_TS + 86395 < time():
                        await self.web_update_sgready_conf()

                return True
            else:
                # just brute-force getting a new login…
                await self._initial_token_request_01_start()
        except BaseException as exc:
            stack_trace = traceback.format_stack()
            stack_trace_str = ''.join(stack_trace[:-1])  # Exclude the call to this function
            _LOGGER.warning(f"app_update() - Exception: {type(exc).__name__} - {exc} -> stack trace:\n{stack_trace_str}")
        return False

    async def web_update(self):
        if self.web_totp_required:
            _LOGGER.info("***** web_update(self) ********")
            return

        try:
            if self._web_is_authenticated:
                _LOGGER.info("***** web_update(self) ********")
                await self.web_update_now()
                # update totals only every 20 minutes
                if self._QUERY_TOTALS_TS + 1200 < time():
                    await self.web_update_total()

                if hasattr(self, '_QUERY_SPARE_CAPACITY') and self._QUERY_SPARE_CAPACITY:
                    # 1 day = 24 h = 24 * 60 min = 24 * 60 * 60 sec = 86400 sec
                    # 2025/06/19 - changed to 6h… = 86400/4 = 21600
                    if self._QUERY_SPARE_CAPACITY_TS + 21600 < time():
                        await self.web_update_spare_capacity()

                if hasattr(self, '_QUERY_PEAK_SHAVING') and self._QUERY_PEAK_SHAVING:
                    # 1 day = 24 h = 24 * 60 min = 24 * 60 * 60 sec = 86400 sec
                    if self._QUERY_PEAK_SHAVING_TS + 86400 < time():
                        await self.web_update_peak_shaving()

                if self.SGREADY_SUPPORTED:
                    # 6h = 6 * 60 min = 6 * 60 * 60 sec = 21600 sec
                    if self._QUERY_SGREADY_STATE_TS + 21600 < time():
                        await self.web_update_sgready_state()
                    # 1 day = 24 h = 24 * 60 min = 24 * 60 * 60 sec = 86400 sec
                    if self._QUERY_SGREADY_CONF_TS + 86400 < time():
                        await self.web_update_sgready_conf()

            else:
                await self.web_authenticate(do_update=True, throw401=False)
        except BaseException as exc:
            stack_trace = traceback.format_stack()
            stack_trace_str = ''.join(stack_trace[:-1])  # Exclude the call to this function
            _LOGGER.warning(f"web_update() - Exception: {type(exc).__name__} - {exc} -> stack trace:\n{stack_trace_str}")


    """SENEC-APP from here"""
    async def app_authenticate(self, check_for_existing_tokens: bool = True):
        # SenecApp stuff…
        if check_for_existing_tokens:
            await self.app_verify_token()
        else:
            # even if we skip the check for existing tokens... we MUSt resore all existing
            # 'other' data from a possible existing token file...
            await self.app_has_token()

        if not self._app_is_authenticated:
            await self._initial_token_request_01_start()
        elif self._app_master_plant_id is None:
            _LOGGER.debug(f"authenticate_all(): 'app_master_plant_id' is None - calling app_get_master_plant_id()")
            await self.app_get_master_plant_id()
        else:
            _LOGGER.debug(f"authenticate_all(): app already authenticated [app_serial_number: {util.mask_string(self._app_serial_number)} - app_master_plant_id: {self._app_master_plant_id}]")

    @staticmethod
    def _format_timedelta(td):
        days = td.days
        hours, remainder = divmod(td.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        if seconds or not parts:
            parts.append(f"{seconds}s")
        return " ".join(parts)

    @staticmethod
    def _base64_url_encode(data):
        """Encode string to base64"""
        return urlsafe_b64encode(data).rstrip(b'=')

    def _generate_hash(self, code):
        """Generate hash for login"""
        hashengine = hashlib.sha256()
        hashengine.update(code.encode('utf-8'))
        return self._base64_url_encode(hashengine.digest()).decode('utf-8')

    """Check if we can write to the file system - should be called from the setup UI"""
    @staticmethod
    def check_general_fs_access(a_storage_path:Path) -> bool:
        _LOGGER.debug(f"check_general_fs_access(): storage_path is: '{a_storage_path}'")
        can_create_file = False
        if a_storage_path is not None:
            testfile = str(a_storage_path.joinpath(DOMAIN, "write_test@file.txt"))
        else:
            testfile = f".storage/{DOMAIN}/write_test@file.txt"
        # Check if the parent directory exists
        directory = os.path.dirname(testfile)
        if not os.path.exists(directory):
            try:
                os.makedirs(directory, exist_ok=True)
            except OSError as exc:
                _LOGGER.warning(f"check_general_fs_access(): could not create directory '{directory}': {type(exc).__name__} - {exc}")

        if os.path.exists(directory):
            try:
                with open(testfile, "w", encoding="utf-8") as outfile:
                    json.dump({"test": "file"}, outfile)
            except OSError as exc:
                _LOGGER.warning(f"check_general_fs_access(): could not create test file '{testfile}': {type(exc).__name__} - {exc}")

            if os.path.exists(testfile):
                can_create_file = True
                _LOGGER.debug(f"check_general_fs_access(): successfully created test file: '{testfile}'")
                os.remove(testfile)

        return can_create_file

    #####################
    # fetch/refresh access_token
    #####################
    def _parse_login_action_form_url(self, html_content):
        # that's quite evil - parsing HTML via RegEx
        form_match = re.search(r'<form[^>]*action="([^"]+)"[^>]*>(.*?)</form>', html_content, re.DOTALL | re.IGNORECASE)
        if form_match:
            form_content = form_match.group(2)
            # Check if the form contains both username and password inputs
            has_username = re.search(r'<input[^>]*(?:name|id)=["\']?(?:username|user|email)["\']?[^>]*>', form_content, re.IGNORECASE)
            has_password = re.search(r'<input[^>]*(?:name|id)=["\']?password["\']?[^>]*>', form_content, re.IGNORECASE)
            if has_username and has_password:
                # This is the login form we're looking for
                return form_match.group(1)

        return None

    def _parse_totp_action_form_url(self, html_content):
        # that's quite evil - parsing HTML via RegEx
        form_match = re.search(r'<form[^>]*action="([^"]+)"[^>]*>(.*?)</form>', html_content, re.DOTALL | re.IGNORECASE)
        if form_match:
            form_content = form_match.group(2)
            # Check if the form contains the otp-code input field
            has_otp = re.search(r'<input[^>]*(?:name|id)=["\']?(?:otp)["\']?[^>]*>', form_content, re.IGNORECASE)
            if has_otp:
                # This is the otp-code-input form we're looking for
                return form_match.group(1)

        return None

    async def _initial_token_request_01_start(self):
        # looks like that 'state' and 'nonce' does not really have a meaning in the OpenID impl from SENEC…
        # ok - state is anyhow an object for us - which we will get back in the redirect URL
        state = secrets.token_urlsafe(22)
        nonce = secrets.token_urlsafe(22)
        self._code_verifier = ''.join(random.choice(string.ascii_lowercase) for i in range(43))
        hashed_code_verifier = self._generate_hash(self._code_verifier)

        req_headers = self._default_app_web_headers.copy()
        req_headers["Accept"]   = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
        #not needed based on the feedback from @ledermann
        #req_headers["Host"]     = "sso.senec.com"
        #req_headers["Referer"]  = "android-app://com.senecapp/"

        a_url = self.LOGIN_URL.format(redirect_url=quote(self.APP_REDIRECT_KEYCLOAK_URI, safe=''),
                                      client_id=self.APP_OPENID_CLIENT_ID,
                                      scope=quote(self.APP_SCOPE, safe=''),
                                      state=state,
                                      nonce=nonce,
                                      code_challenge=hashed_code_verifier)

        async with self.web_session.get(a_url, headers=req_headers) as res:
            try:
                _LOGGER.debug(f"initial_token_request_01_start(): requesting: {a_url}")
                res.raise_for_status()
                if res.status in [200, 201, 202, 204, 205]:
                    html_content = await res.text()
                    the_form_action_url = self._parse_login_action_form_url(html_content)
                    if the_form_action_url:
                        login_data = {
                            "username": self._SENEC_USERNAME,
                            "password": self._SENEC_PASSWORD
                        }
                        await self._initial_token_request_02_post_login(accept_http_200=True, form_action_url=the_form_action_url, post_data=login_data)
                    else:
                        _LOGGER.info(f"initial_token_request_01_start(): did not find the expected form action URL in the response HTML! {html_content}")
                else:
                    _LOGGER.info(f"initial_token_request_01_start(): unexpected [200] response code: {res.status} - {res}")
            except BaseException as ex:
                _LOGGER.debug(f"initial_token_request_01_start(): {type(ex).__name__} - {ex}")


    async def _initial_token_request_02_post_login(self, accept_http_200:bool, form_action_url, post_data:dict):
        req_headers = self._default_app_web_headers.copy()
        req_headers["Accept"]           = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
        #req_headers["Host"]             = "sso.senec.com"
        req_headers["Content-Type"]     = "application/x-www-form-urlencoded"
        req_headers["Cache-Control"]    = "max-age=0"

        async with self.web_session.post(form_action_url, data=post_data, allow_redirects=False, headers=req_headers) as res:
            try:
                if accept_http_200:
                    _LOGGER.debug(f"_initial_token_request_02_post_login(): requesting: {form_action_url}")
                else:
                    _LOGGER.debug(f"_initial_token_request_02_post_login(): SEND OTP CODE requesting: {form_action_url}")

                res.raise_for_status()
                # checking if OTP code must be submitted
                if accept_http_200 and res.status in [200, 201, 202, 204, 205]:
                    html_content = await res.text()
                    the_form_action_url = self._parse_totp_action_form_url(html_content)
                    if the_form_action_url:
                        if self._SENEC_TOTP_SECRET is not None:
                            otp_data = {"otp": pyotp.TOTP(self._SENEC_TOTP_SECRET).now()}
                            await self._initial_token_request_02_post_login(accept_http_200=False, form_action_url=the_form_action_url, post_data=otp_data)
                        else:
                            _LOGGER.error(f"_initial_token_request_02_post_login(): TOTP Code required, but not configured/provided - need RECONFIG!")
                            raise ReConfigurationRequired("TOTP Code required, but not configured/provided - need RECONFIG")
                    else:
                        _LOGGER.info(f"_initial_token_request_02_post_login(): did not find the expected form action URL in the response HTML! {html_content}")

                elif res.status == 302:
                    location = res.headers.get("Location")
                    if location:
                        await self._initial_token_request_03_get_token(location)
                    else:
                        _LOGGER.info(f"_initial_token_request_02_post_login(): no 'Location' in response Header")
                else:
                    _LOGGER.info(f"_initial_token_request_02_post_login(): unexpected [302] response code: {res.status} - {res}")

            except BaseException as ex:
                _LOGGER.info(f"_initial_token_request_02_post_login(): {type(ex).__name__} - {ex}")


    async def _initial_token_request_03_get_token(self, redirect):
        if redirect.startswith(self.APP_REDIRECT_KEYCLOAK_URI):
            # from the incoming redirect location url we are parsing the url parameters…
            params = parse_qs(urlparse(redirect).query)

            # Extract individual parameters - but code is the only thing that we need…
            code = params.get('code', [None])[0]
            # state = params.get('state', [None])[0]
            # iss = params.get('iss', [None])[0]
            # session_state = params.get('session_state', [None])[0]

            _LOGGER.debug(f"_initial_token_request_03_get_token(): got final code: '{util.mask_string(code)}' in redirect URL - going to continue…")

            req_headers = self._default_app_web_headers.copy()
            req_headers["User-Agent"]   = self.DEFAULT_USER_AGENT if self.USE_DEFAULT_USER_AGENT else self.APP_SSO_USER_AGENT
            req_headers["Accept"]       = "application/json"
            #req_headers["Host"]         = "sso.senec.com"
            req_headers["Content-Type"] = "application/x-www-form-urlencoded"

            post_data = {
                "code":             code,
                "grant_type":       "authorization_code",
                "redirect_uri":     self.APP_REDIRECT_KEYCLOAK_URI,
                "code_verifier":    self._code_verifier,
                "client_id":        self.APP_OPENID_CLIENT_ID
            }
            # we have to follow the redirect…
            async with self.web_session.post(self.TOKEN_URL, data=post_data, headers=req_headers) as res:
                try:
                    _LOGGER.debug(f"_initial_token_request_03_get_token(): requesting: {self.TOKEN_URL} with {util.mask_map(post_data)}")
                    res.raise_for_status()
                    if res.status in [200, 201, 202, 204, 205]:
                        token_data = await res.json()
                        if "access_token" in token_data:
                            _LOGGER.debug(f"_initial_token_request_03_get_token(): received token data: {util.mask_map(token_data)}")
                            await self._app_on_new_token_data_received(token_data)
                        else:
                            _LOGGER.info(f"_initial_token_request_03_get_token(): NO access_token in {util.mask_map(token_data)}")
                    else:
                        _LOGGER.info(f"_initial_token_request_03_get_token(): unexpected [200] response code: {res.status} - {res}")

                except BaseException as ex:
                    _LOGGER.info(f"_initial_token_request_03_get_token(): {type(ex).__name__} - {ex}")
        else:
            _LOGGER.info(f"_initial_token_request_03_get_token(): redirect does not start with the expected schema '{self.APP_REDIRECT_KEYCLOAK_URI}' -> received: '{redirect}')")

    async def _refresh_token_request(self, refresh_token):
        req_headers = self._default_app_web_headers.copy()
        req_headers["User-Agent"]   = self.DEFAULT_USER_AGENT if self.USE_DEFAULT_USER_AGENT else self.APP_SSO_USER_AGENT
        req_headers["Accept"]       = "application/json"
        #req_headers["Host"]         = "sso.senec.com"
        req_headers["Content-Type"] = "application/x-www-form-urlencoded"

        post_data = {
            "refresh_token": refresh_token,
            "grant_type":   "refresh_token",
            "client_id":    self.APP_OPENID_CLIENT_ID
        }
        # we have to follow the redirect…
        async with self.web_session.post(self.TOKEN_URL, data=post_data, headers=req_headers) as res:
            try:
                _LOGGER.debug(f"_refresh_token_request(): requesting: {self.TOKEN_URL} with {util.mask_map(post_data)}")
                res.raise_for_status()
                if res.status in [200, 201, 202, 204, 205]:
                    token_data = await res.json()
                    if "access_token" in token_data:
                        _LOGGER.debug(f"_refresh_token_request(): received token data: {util.mask_map(token_data)}")
                        await self._app_on_new_token_data_received(token_data)
                    else:
                        _LOGGER.info(f"_refresh_token_request(): NO access_token in {util.mask_map(token_data)}")
                else:
                    _LOGGER.info(f"_refresh_token_request(): unexpected [200] response code: {res.status} - {res}")

            except BaseException as ex:
                _LOGGER.info(f"_refresh_token_request(): {type(ex).__name__} - {ex}")


    #####################
    # read/write token_dict from/to filesystem
    #####################
    async def _write_token_to_storage(self, token_dict):
        """Save token to file for reuse"""
        if token_dict is None:
            _LOGGER.debug(f"_write_token_to_storage() - DELETE")
        else:
            _LOGGER.debug(f"_write_token_to_storage() - SAVE")

        # Check if the parent directory exists
        directory = os.path.dirname(self._app_stored_tokens_location)
        if not os.path.exists(directory):
            try:
                await asyncio.get_running_loop().run_in_executor(None, lambda: os.makedirs(directory, exist_ok=True))
            except OSError as exc:
                _LOGGER.warning(f"_write_token_to_storage(): could not create directory '{directory}': {type(exc).__name__} - {exc}")

        # Write the file in executor
        if os.path.exists(directory):
            await asyncio.get_running_loop().run_in_executor(None, lambda: self.__write_token_int(token_dict))

    def __write_token_int(self, token_dict):
        """Synchronous method to write the token file, called from executor."""
        if token_dict is None:
            try:
                os.remove(self._app_stored_tokens_location)
                _LOGGER.debug(f"__write_token_int(): Token file deleted: {self._app_stored_tokens_location}")
            except FileNotFoundError:
                _LOGGER.debug(f"__write_token_int(): Token file not found, nothing to delete: {self._app_stored_tokens_location}")
            except OSError as exc:
                _LOGGER.info(f"__write_token_int(): Error deleting token file: {type(exc).__name__} - {exc}")
        else:
            try:
                with open(self._app_stored_tokens_location, "w", encoding="utf-8") as outfile:
                    json.dump(token_dict, outfile)
            except OSError as exc:
                _LOGGER.info(f"__write_token_int(): could not write token file: {type(exc).__name__} - {exc}")

    async def _read_token_from_storage(self):
        """Read saved token from a file"""
        _LOGGER.debug(f"read_token_from_storage()")
        try:
            # Run blocking file operation in executor
            token_data = await asyncio.get_running_loop().run_in_executor(None, self.__read_token_int)
            return token_data
        except ValueError:
            _LOGGER.warning(f"read_token_from_storage: 'ValueError' invalidate TOKEN FILE -> mark_re_auth_required()")
            #self.mark_re_auth_required()
        return None

    def __read_token_int(self):
        """Synchronous method to read the token file, called from executor."""
        if os.path.exists(self._app_stored_tokens_location):
            with open(self._app_stored_tokens_location, encoding="utf-8") as token_file:
                return json.load(token_file)
        else:
            return None


    #####################
    # helpers to make sure 'access_token' is ready to use
    #####################
    async def _app_on_new_token_data_received(self, token_data):
        # loaded_datetime = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        now = datetime.now(timezone.utc)
        if "expires_in" in token_data and "expires_at" not in token_data:
            token_data["expires_at"]        = int((now + timedelta(seconds=(token_data["expires_in"] - 5))).timestamp())
        if "refresh_expires_in" in token_data and "refresh_expires_at" not in token_data:
            token_data["refresh_expires_at"]= int((now + timedelta(seconds=(token_data["refresh_expires_in"] - 5))).timestamp())

        # we also persist our static data [we have fetched during the login]
        if self._app_master_plant_id is not None and self._app_serial_number is not None and self._app_data_start_ts != -1:
            token_data[CONF_APP_SYSTEMID]       = self._app_master_plant_id
            token_data[CONF_APP_SERIALNUM]      = self._app_serial_number
            token_data[CONF_APP_WALLBOX_COUNT]  = self._app_wallbox_num_max
            token_data[CONF_APP_DATA_START]     = self._app_data_start_ts
            token_data[CONF_APP_DATA_END]       = self._app_data_end_ts
        elif self._app_token_object is not None and CONF_APP_SYSTEMID in self._app_token_object and self._app_token_object[CONF_APP_SYSTEMID] is not None:
            token_data[CONF_APP_SYSTEMID]       = self._app_token_object[CONF_APP_SYSTEMID]
            token_data[CONF_APP_SERIALNUM]      = self._app_token_object[CONF_APP_SERIALNUM]
            token_data[CONF_APP_WALLBOX_COUNT]  = self._app_token_object[CONF_APP_WALLBOX_COUNT]
            token_data[CONF_APP_DATA_START]     = self._app_token_object[CONF_APP_DATA_START]
            token_data[CONF_APP_DATA_END]       = self._app_token_object[CONF_APP_DATA_END]

        # this is our storage for our total usage data (so that we do not query that only once)
        # if it's not included in the token_data that we want to save - then we check, if there
        # is an existing object in the 'current' _app_token_object
        if CONF_APP_TOTAL_DATA not in token_data and CONF_APP_TOTAL_DATA in self._app_token_object:
            token_data[CONF_APP_TOTAL_DATA] = self._app_token_object[CONF_APP_TOTAL_DATA]

        self._app_token_object = token_data
        await self._write_token_to_storage(self._app_token_object)

        # updating our internal state - and set the app_token value…
        self.app_ensure_token_is_set()

    async def app_has_token(self):
        stored_data = await self._read_token_from_storage()
        if stored_data is not None:
            self._app_token_object = stored_data
            if CONF_APP_TOTAL_DATA not in self._app_token_object:
                # creating an initalized storage…
                _LOGGER.debug(f"app_has_token(): no '{CONF_APP_TOTAL_DATA}' in _app_token_object: {util.mask_map(self._app_token_object)} - initializing it")
                self._app_token_object[CONF_APP_TOTAL_DATA] = {
                    "years":        self._static_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_YEARS,
                    "years_data":   self._static_TOTAL_SUMS_PREV_YEARS,
                    "months":       self._static_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_MONTHS,
                    "months_data":  self._static_TOTAL_SUMS_PREV_MONTHS,
                    "days":         self._static_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_DAYS,
                    "days_data":    self._static_TOTAL_SUMS_PREV_DAYS,
                    "wallbox":      self._static_TOTAL_WALLBOX_DATA
                }
            else:
                # JUST FOR THE UPDATE required...
                # ok we have 'CONF_APP_TOTAL_DATA' but is there also the wallbox data present?
                if "wallbox" not in self._app_token_object[CONF_APP_TOTAL_DATA]:
                    self._app_token_object[CONF_APP_TOTAL_DATA]["wallbox"] = self._static_TOTAL_WALLBOX_DATA

            return True

        return False

    async def app_verify_token(self):
        if self._app_token_object is not None:
            if "expires_at" in self._app_token_object:
                now = datetime.now(timezone.utc)
                valid_till = datetime.fromtimestamp(self._app_token_object["expires_at"], tz=timezone.utc)
                if now < valid_till:
                    _LOGGER.debug(f"app_verify_token(): access_token is VALID [expires in: {self._format_timedelta(valid_till-now)}]")
                    self.app_ensure_token_is_set()
                elif "refresh_expires_at" in self._app_token_object:
                    refresh_valid_till = datetime.fromtimestamp(self._app_token_object["refresh_expires_at"], tz=timezone.utc)
                    if now < refresh_valid_till and "refresh_token" in self._app_token_object:
                        _LOGGER.debug(f"app_verify_token(): access_token EXPIRED [{self._format_timedelta(now-valid_till)} ago] - refresh_token is VALID [expires in: {self._format_timedelta(refresh_valid_till-now)}]")
                        await self._refresh_token_request(self._app_token_object["refresh_token"])
                    else:
                        _LOGGER.info(f"app_verify_token(): refresh_token EXPIRED [{self._format_timedelta(now-refresh_valid_till)} ago] - need to re-authenticate")
                        await self._initial_token_request_01_start()
                else:
                    _LOGGER.info(f"app_verify_token(): access_token EXPIRED [{self._format_timedelta(now-valid_till)} ago] - no refresh_token available - need to re-authenticate")
                    await self._initial_token_request_01_start()
            else:
                can_token_be_restored = await self.app_has_token()
                if can_token_be_restored and "expires_at" in self._app_token_object:
                    await self.app_verify_token()
                else:
                    _LOGGER.info(f"app_verify_token(): no 'expires_at' in _app_token_object: '{self._app_token_object}' - need to re-authenticate")
                    await self._initial_token_request_01_start()
        else:
            can_token_be_restored = await self.app_has_token()
            if can_token_be_restored:
                await self.app_verify_token()
            else:
                _LOGGER.info("app_verify_token(): '_app_token_object' is None - need to re-authenticate")
                await self._initial_token_request_01_start()

    def app_ensure_token_is_set(self):
        if self._app_token_object is not None and "access_token" in self._app_token_object:
            self._app_token = f"Bearer {self._app_token_object['access_token']}"
            self._app_is_authenticated  = True
            if CONF_APP_SYSTEMID in self._app_token_object and self._app_token_object[CONF_APP_SYSTEMID] is not None:
                self._app_master_plant_id   = self._app_token_object[CONF_APP_SYSTEMID]
                self._app_serial_number     = self._app_token_object[CONF_APP_SERIALNUM]
                self._app_wallbox_num_max   = self._app_token_object[CONF_APP_WALLBOX_COUNT]
                self._app_data_start_ts     = self._app_token_object[CONF_APP_DATA_START]
                self._app_data_end_ts       = self._app_token_object[CONF_APP_DATA_END]
        else:
            _LOGGER.info(f"app_ensure_token(): no valid token data found - need to re-authenticate ?")
            self._app_token = None
            self._app_is_authenticated  = False
            self._app_master_plant_id   = None
            self._app_serial_number     = None
            self._app_wallbox_num_max   = 4
            self._app_data_start_ts     = -1
            self._app_data_end_ts       = -1

    #####################
    # backend requests from here
    # all token/login stuff should be fine…
    #####################
    async def _app_do_get_request(self, a_url:str, do_as_patch:bool = False):
        if do_as_patch:
            _LOGGER.debug(f"***** APP-API: _app_do_get(as_patch)_request(self) ********")
        else:
            _LOGGER.debug(f"***** APP-API: _app_do_get_request(self) ********")
        await self.app_verify_token()
        if self._app_is_authenticated:
            req_headers = self._default_app_headers.copy()
            req_headers["Authorization"] = self._app_token
            try:
                get_or_patch = getattr(self.web_session, "patch" if do_as_patch else "get")
                if do_as_patch:
                    _LOGGER.debug(f"_app_do_get_request(): PATCH: {a_url}")
                else:
                    _LOGGER.debug(f"_app_do_get_request(): requesting: {a_url}")
                async with get_or_patch(a_url, headers=req_headers) as res:
                    try:
                        res.raise_for_status()
                        if res.status in [200, 201, 202, 204, 205]:
                            try:
                                data = await res.json()
                                _LOGGER.debug(f"_app_do_get_request(): response: {util.mask_map(data)}")
                                return data

                            except JSONDecodeError as jexc:
                                _LOGGER.warning(f"_app_do_get_request(): JSONDecodeError while 'await res.json()' {jexc}")
                            except Exception as exc:
                                if data is not None:
                                    _LOGGER.error(f"_app_do_get_request(): Error when handling response '{res}' - Data: '{util.mask_map(data)}' - Exception:' {exc}'")
                                else:
                                    _LOGGER.error(f"_app_do_get_request(): Error when handling response '{res}' - Exception:' {exc}'")
                        else:
                            _LOGGER.error(f"_app_do_get_request(): unexpected status code [200-205] {res.status} - {res}'")

                    except Exception as exc:
                        if res is not None:
                            if res.status == 408:
                                _LOGGER.info(f"_app_do_get_request(): http status 408 while access {a_url}")
                            else:
                                _LOGGER.error(f"_app_do_get_request(): Error while access {a_url}: '{exc}' - Response is: '{res}'")
                        else:
                            _LOGGER.error(f"_app_do_get_request(): Error while access {a_url}: '{exc}'")
            except Exception as exc:
                _LOGGER.error(f"_app_do_get_request(): Error when try to call {a_url}: '{exc}'")
        else:
            _LOGGER.error(f"_app_do_get_request(): 'self._app_is_authenticated' is False")

    async def _app_do_post_request(self, a_url:str,  post_data: dict, read_response: bool = False):
        _LOGGER.debug("***** APP-API: _app_do_post_request(self) ********")
        await self.app_verify_token()
        if self._app_is_authenticated:
            req_headers = self._default_app_headers.copy()
            req_headers["Authorization"] = self._app_token
            try:
                _LOGGER.debug(f"_app_do_post_request(): requesting: {a_url} - with post_data: {util.mask_map(post_data)}")
                async with self.web_session.post(a_url, headers=req_headers, json=post_data) as res:
                    try:
                        res.raise_for_status()
                        if res.status in [200, 201, 202, 204, 205]:
                            if read_response:
                                try:
                                    data = await res.json()
                                    _LOGGER.debug(f"_app_do_post_request(): response: {util.mask_map(data)}")
                                    return data
                                except JSONDecodeError as jexc:
                                    _LOGGER.warning(f"_app_do_post_request(): JSONDecodeError while 'await res.json()' {jexc}")
                                except Exception as exc:
                                    if data is not None:
                                        _LOGGER.error(f"_app_do_post_request(): Error when handling response '{res}' - Data: '{util.mask_map(data)}' - Exception:' {exc}'")
                                    else:
                                        _LOGGER.error(f"_app_do_post_request(): Error when handling response '{res}' - Exception:' {exc}'")
                            else:
                                _LOGGER.debug(f"APP-API HTTP:200 for post {util.mask_map(post_data)} to {a_url}")
                                return True
                        else:
                            _LOGGER.error(f"_app_do_post_request(): unexpected status code [200-205] {res.status} - {res}'")

                    except Exception as exc:
                        if res is not None:
                            if res.status == 408:
                                _LOGGER.info(f"_app_do_post_request(): http status 408 while access {a_url}")
                            else:
                                _LOGGER.error(f"_app_do_post_request(): Error while access {a_url}: '{exc}' - Response is: '{res}'")
                        else:
                            _LOGGER.error(f"_app_do_post_request(): Error while access {a_url}: '{exc}'")
            except Exception as exc:
                _LOGGER.error(f"_app_do_post_request(): Error when try to call {a_url}: '{exc}'")
        else:
            _LOGGER.error(f"_app_do_post_request(): 'self._app_is_authenticated' is False")
        return False

    # async def app_post_data(self, a_url: str, post_data: dict, read_response: bool = False) -> bool:
    #     _LOGGER.debug("***** APP-API: app_post_data(self) ********")
    #     if self._app_token is not None:
    #         _LOGGER.debug(f"APP-API post {post_data} to {a_url}")
    #         try:
    #             headers = {"Authorization": self._app_token, "User-Agent": USER_AGENT}
    #             async with self.web_session.post(url=a_url, headers=headers, json=post_data, ssl=False) as res:
    #                 res.raise_for_status()
    #                 if res.status == 200:
    #                     if read_response:
    #                         try:
    #                             data = await res.json()
    #                             _LOGGER.debug(f"APP-API HTTP:200 for post {post_data} to {a_url} returned: {data}")
    #                             return True
    #                         except JSONDecodeError as exc:
    #                             _LOGGER.warning(f"APP-API: JSONDecodeError while 'await res.json()' {exc}")
    #                     else:
    #                         _LOGGER.debug(f"APP-API HTTP:200 for post {post_data} to {a_url}")
    #                         return True
    #
    #                 elif res.status == 500:
    #                     _LOGGER.info(f"APP-API: Not found {a_url} (http 500)")
    #
    #                 else:
    #                     self._app_is_authenticated = False
    #                     self._app_token = None
    #                     self._app_master_plant_id = None
    #                     return False
    #
    #         except Exception as exc:
    #             try:
    #                 if res.status == 500:
    #                     _LOGGER.info(f"APP-API: Not found {a_url} [HTTP 500]: {exc}")
    #                 elif res.status == 400:
    #                     _LOGGER.info(f"APP-API: Not found {a_url} [HTTP 400]: {exc}")
    #                 elif res.status == 401:
    #                     _LOGGER.info(f"APP-API: No permission {a_url} [HTTP 401]: {exc}")
    #                     self._app_is_authenticated = False
    #                     self._app_token = None
    #                     self._app_master_plant_id = None
    #                 else:
    #                     _LOGGER.warning(f"APP-API: Could not post to {a_url} data: {post_data} causing: {exc}")
    #             except NameError:
    #                 _LOGGER.warning(f"APP-API: NO RES - Could not post to {a_url} data: {post_data} causing: {exc}")
    #             return False
    #
    #     else:
    #         # somehow we should pass a "callable"…
    #         await self.app_authenticate()
    #         return False

    async def app_get_master_plant_id(self):
        _LOGGER.debug("***** APP-API: get_master_plant_id(self) ********")
        data = await self._app_do_get_request(self.APP_SYSTEM_LIST)
        if data is not None:
            if self._app_master_plant_number == -1:
                self._app_master_plant_number = 0
            idx = int(self._app_master_plant_number)

            # when SENEC API only return a single system in the 'v1/senec/anlagen' request (even if
            # there are multiple systems)…
            if len(data) == 1 and idx > 0:
                _LOGGER.debug(f"app_get_master_plant_id(): IGNORE requested 'master_plant_number' {idx} will use 0 instead!")
                idx = 0

            if len(data) > idx:
                if "id" in data[idx]:
                    self._app_master_plant_id = data[idx]["id"]
                    _LOGGER.debug(f"app_get_master_plant_id(): set _app_master_plant_id to {self._app_master_plant_id}")

                if "wallboxIds" in data[idx]:
                    self._app_wallbox_num_max = len(data[idx]["wallboxIds"])
                    _LOGGER.debug(f"app_get_master_plant_id(): set _app_wallbox_num_max to {self._app_wallbox_num_max}")
                else:
                    self._app_wallbox_num_max = 0

                if "controlUnitNumber" in data[idx]:
                    self._app_serial_number = data[idx]["controlUnitNumber"]
                    _LOGGER.debug(f"app_get_master_plant_id(): set _app_serial_number to {util.mask_string(self._app_serial_number)}")

            # when we have successfully collected our primary meta-data, then we should also capture the start-end date
            # timestamps for the total data
            if self._app_data_start_ts == -1:
                await self.app_get_data_start_and_end_ts()

            # we must update out token-object on the local storage [when we have a new master_plant_id]
            if CONF_APP_SYSTEMID not in self._app_token_object or self._app_token_object[CONF_APP_SYSTEMID] != self._app_master_plant_id:
                await self._app_on_new_token_data_received(self._app_token_object)

        return data

    async def app_get_system_details(self):
        # https://senec-app-systems-proxy.prod.senec.dev/systems/{master_plant_id}/details
        # sample_data = {
        #   "systemOverview": {
        #     "systemId": self.master_plant_id,
        #     "hid": None,
        #     "productName": "SENEC.HOME V3 hybrid duo LFP",
        #     "installationDateTime": "2022-08-09T22:00:00Z",
        #     "exchangedSystemId": None
        #   },
        #   "casing": {
        #     "serial": "DE-V3-HD-03LI10-XXXXX",
        #     "temperatureInCelsius": 31.388556
        #   },
        #   "mcu": {
        #     "mainControllerSerial": "XXXXXXXXXXXXXXXXXXXXXXXXXX",
        #     "mainControllerUnitState": {
        #         "name": "LADEN",
        #         "severity": "INFO",
        #         "operatingMode": "FULL_OPERATION"
        #     },
        #     "firmwareVersion": "833",
        #     "guiVersion": 970,
        #     "lastContact": {
        #       "timestamp": "2025-07-22T06:06:53.304Z",
        #       "severity": "INFO"
        #     },
        #     "ipAddress": None
        #   },
        #   "warranty": {
        #     "endDateTime": "20XX-XX-XXT22:00:00Z",
        #     "warrantyTermInMonths": 100
        #   },
        #   "batteryPack": {
        #     "numberOfBatteryModules": 2,
        #     "technology": "LITHIUM_IRON_PHOSPHATE",
        #     "currentChargingLevelInPercent": 62,
        #     "maxCapacityInKwh": 10
        #   },
        #   "batteryModules": [
        #     {
        #       "ordinal": 1,
        #       "serialNumber": "000nnnn",
        #       "state": {
        #         "state": "OK",
        #         "severity": "OK"
        #       },
        #       "lastContact": {
        #         "timestamp": "2025-07-22T06:06:51Z",
        #         "severity": "OK"
        #       },
        #       "firmwareVersion": None
        #     },
        #     {
        #       "ordinal": 2,
        #       "serialNumber": "000nnnn",
        #       "state": {
        #         "state": "OK",
        #         "severity": "OK"
        #       },
        #       "lastContact": {
        #         "timestamp": "2025-07-22T06:06:51Z",
        #         "severity": "OK"
        #       },
        #       "firmwareVersion": None
        #     }
        #   ],
        #   "installer": {
        #     "companyName": "XXX",
        #     "email": "XXX",
        #     "phoneNumber": "+XXX",
        #     "address": {
        #       "street": "XXX",
        #       "houseNumber": "XX",
        #       "postcode": "XXX",
        #       "city": "XXX",
        #       "countryCode": "XX",
        #       "region": "XXX",
        #       "timezone": "Europe/Berlin"
        #     },
        #     "onlineMonitoringAllowed": True,
        #     "website": "XXX"
        #   }
        # }
        if self._app_master_plant_id is None:
            await self.app_get_master_plant_id()

        _LOGGER.debug("***** APP-API: app_get_system_details(self) ********")
        a_url = self.APP_SYSTEM_DETAILS.format(master_plant_id=self._app_master_plant_id)
        data = await self._app_do_get_request(a_url)
        if data is not None:
            self._app_raw_system_details = data
            # see 'system_state' property for details! (why this is a hack)
            self._app_raw_system_state_obj = None
            _QUERY_SYSTEM_DETAILS_TS = time()
        else:
            self._app_raw_system_details = None

        return data

    async def app_get_abilities(self):
        # https://senec-app-abilities-proxy.prod.senec.dev/abilities/packages/{master_plant_id}
        # samle_data = {
        #   "warrantyPackage": null,
        #   "packageTypes": [
        #     "MOBILITY",
        #     "PEAK_SHAVING",
        #     "SG_READY",
        #     "HEATING_ROD"
        #   ]
        # }
        if self._app_master_plant_id is None:
            await self.app_get_master_plant_id()

        _LOGGER.debug("***** APP-API: app_get_abilities(self) ********")
        a_url = self.APP_ABILITIES_LIST.format(master_plant_id=self._app_master_plant_id)
        data = await self._app_do_get_request(a_url)
        if data is not None:
            if "packageTypes" in data:
                self._app_abilities = data["packageTypes"]
        return data

    async def app_get_data_start_and_end_ts(self):
        if self._app_master_plant_id is None:
            await self.app_get_master_plant_id()

        _LOGGER.debug("***** APP-API: app_get_data_start_and_end_ts(self) ********")
        a_url = self.APP_MEASURE_DATA_AVAIL.format(master_plant_id=self._app_master_plant_id, tz="UTC")
        data = await self._app_do_get_request(a_url)
        if data is not None:
            if "periodStartDateInMilliseconds" in data:
                self._app_data_start_ts = data["periodStartDateInMilliseconds"] / 1000
            if "periodEndDateInMilliseconds" in data:
                self._app_data_end_ts = data["periodEndDateInMilliseconds"] / 1000
        return data

    async def app_get_system_status(self):
        # https://senec-app-systems-proxy.prod.senec.dev/systems/status/{master_plant_id}
        # sample_data = {
        #   "name": "LADEN",
        #   "severity": "INFO",
        #   "firmwareVersion": "833",
        #   "guiVersion": 970,
        #   "lastContact": "2025-07-22T06:06:53.304Z",
        #   "operatingMode": "FULL_OPERATION"
        # }
        if self._app_master_plant_id is None:
            await self.app_get_master_plant_id()

        _LOGGER.debug("***** APP-API: app_get_system_status(self) ********")
        a_url = self.APP_SYSTEM_STATUS.format(master_plant_id=self._app_master_plant_id)
        data = await self._app_do_get_request(a_url)
        if data is not None:
            self._app_raw_system_state_obj = data
            self._QUERY_SYSTEM_STATE_TS = time()
        else:
            self._app_raw_system_state_obj = None
        return data

    async def app_get_dashboard(self):
        # https://senec-app-measurements-proxy.prod.senec.dev/v1/systems/{master_plant_id}/dashboard
        # sample_data = {
        #   "currently": {
        #     "powerGenerationInW": 1781.0947265625,
        #     "powerConsumptionInW": 520.94,
        #     "gridFeedInInW": 13.096284866333008,
        #     "gridDrawInW": 2.4555535316467285,
        #     "batteryChargeInW": 1246.693603515625,
        #     "batteryDischargeInW": 0,
        #     "batteryLevelInPercent": 62,
        #     "selfSufficiencyInPercent": 99.53,
        #     "wallboxInW": 0
        #   },
        #   "today": {
        #     "powerGenerationInWh": 916.50390625,
        #     "powerConsumptionInWh": 3205.93,
        #     "gridFeedInInWh": 87.158203125,
        #     "gridDrawInWh": 66.41387939453125,
        #     "batteryChargeInWh": 445.281982421875,
        #     "batteryDischargeInWh": 2755.92041015625,
        #     "batteryLevelInPercent": 62,
        #     "selfSufficiencyInPercent": 97.93,
        #     "wallboxInWh": 0
        #   },
        #   "timestamp": "2025-07-22T06:06:51Z",
        #   "electricVehicleConnected": False,
        #   "numberOfWallboxes": 0,
        #   "systemId": self.master_plant_id,
        #   "systemType": "V123",
        #   "storageDeviceState": "CHARGING"
        # }
        if self._app_master_plant_id is None:
            await self.app_get_master_plant_id()

        _LOGGER.debug("***** APP-API: app_get_dashboard(self) ********")
        a_url = self.APP_MEASURE_DASHBOARD.format(master_plant_id=self._app_master_plant_id)
        data = await self._app_do_get_request(a_url)
        if data is not None:
            if "currently" in data:
                self._app_raw_now = data["currently"]
            else:
                self._app_raw_now = None

            # even if there are no active 'today' sensors we want to capture already the data
            if data is not None and "today" in data:
                self._app_raw_today = data["today"]
            else:
                self._app_raw_today = None

            if "storageDeviceState" in data:
                self._app_raw_battery_device_state = data["storageDeviceState"]

        return data

    async def _app_get_total(self, type_value:str, from_value:str, to_value:str):
        # https://senec-app-measurements-proxy.prod.senec.dev/v1/systems/{master_plant_id}/measurements?resolution=FIVE_MINUTES&from=2025-07-18T22%3A00%3A00Z&to=2025-07-22T16%3A28%3A17.100Z
        # https://senec-app-measurements-proxy.prod.senec.dev/v1/systems/{master_plant_id}/measurements?resolution=MONTH&from=2023-12-31T23%3A00%3A00Z&to=2024-12-31T23%3A00%3A00Z
        # sample_data = {
        #     "timeSeries": [
        #         {
        #             "date": "2025-04-30T22:00:00Z",
        #             "measurements": {
        #                 "durationInSeconds": 2678400,
        #                 "values": [
        #                     453.727294921875,
        #                     275.7222595214844,
        #                     41.69596862792969,
        #                     218.02720642089844,
        #                     54.24029541015625,
        #                     49.47010803222656,
        #                     87.21552276611328,
        #                     84.88,
        #                     0
        #                 ]
        #             }
        #         },
        #         {
        #             "date": "2025-05-31T22:00:00Z",
        #             "measurements": {
        #                 "durationInSeconds": 2592000,
        #                 "values": [
        #                     2043.3262939453125,
        #                     840.2120361328125,
        #                     35.74931335449219,
        #                     1234.857177734375,
        #                     146.384521484375,
        #                     138.48309326171875,
        #                     87.75665283203125,
        #                     95.75,
        #                     0
        #                 ]
        #             }
        #         },
        #         {
        #             "date": "2025-06-30T22:00:00Z",
        #             "measurements": {
        #                 "durationInSeconds": 2678400,
        #                 "values": [
        #                     1253.9814453125,
        #                     698.794677734375,
        #                     13.055213928222656,
        #                     560.6070556640625,
        #                     123.37608337402344,
        #                     114.9639892578125,
        #                     88.3036880493164,
        #                     98.13,
        #                     0
        #                 ]
        #             }
        #         }
        #     ],
        #     "measurements": [
        #         "POWER_GENERATION",
        #         "POWER_CONSUMPTION",
        #         "GRID_IMPORT",
        #         "GRID_EXPORT",
        #         "BATTERY_IMPORT",
        #         "BATTERY_EXPORT",
        #         "BATTERY_LEVEL_IN_PERCENT",
        #         "AUTARKY_IN_PERCENT",
        #         "WALLBOX_CONSUMPTION"
        #     ],
        #     "electricVehicleConnected": False
        # }

        if self._app_master_plant_id is None:
            await self.app_get_master_plant_id()

        _LOGGER.debug("***** APP-API: app_get_total(self) ********")
        a_url = self.APP_MEASURE_TOTAL.format(master_plant_id=self._app_master_plant_id,
                                              res_type=type_value.upper(),
                                              from_val=quote(from_value, safe=''),
                                              to_val=quote(to_value, safe=''))
        data = await self._app_do_get_request(a_url)
        if data is not None:
            pass
        return data

    # async def app_get_total(self):
    #     if self._app_master_plant_id is None:
    #         await self.app_get_master_plant_id()
    #     _LOGGER.debug("***** APP-API: app_get_total(self) ********")
    #     a_url = self.APP_MEASURE_TOTAL.format(master_plant_id=self._app_master_plant_id,
    #                                           res_type=type.upper(),
    #                                           from_val=quote(from_value, safe=''),
    #                                           to_val=quote(to_value, safe=''))
    #     data = await self._app_do_get_request(a_url)
    #     if data is not None:
    #         pass
    #     return data

    async def app_update_total(self, wb_ids:str=None):
        if self._app_master_plant_id is None:
            await self.app_get_master_plant_id()

        _LOGGER.debug("***** APP-API: app_update_total(self) ********")
        now_utc = datetime.now(timezone.utc)
        now_local =  datetime.now()
        current_year_local = now_local.year
        current_month_local = now_local.month
        current_day_local = now_local.day
        do_persist = False

        # restore the data from our persistent storage
        if CONF_APP_TOTAL_DATA in self._app_token_object:
            storage = self._app_token_object[CONF_APP_TOTAL_DATA]
            self._static_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_YEARS  = storage.get("years",      self._static_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_YEARS)
            self._static_TOTAL_SUMS_PREV_YEARS                  = storage.get("years_data", self._static_TOTAL_SUMS_PREV_YEARS)
            self._static_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_MONTHS = storage.get("months",     self._static_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_MONTHS)
            self._static_TOTAL_SUMS_PREV_MONTHS                 = storage.get("months_data",self._static_TOTAL_SUMS_PREV_MONTHS)
            self._static_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_DAYS   = storage.get("days",       self._static_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_DAYS)
            self._static_TOTAL_SUMS_PREV_DAYS                   = storage.get("days_data",  self._static_TOTAL_SUMS_PREV_DAYS)

        # getting PREVIOUS_YEARS - only ONCE
        if self._static_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_YEARS != current_year_local:
            do_persist = True
            # Loop from the data-available-start to current year [there are no older systems than 2018]
            # we might like to store the first year, that actually has data?!
            start_year = 2018
            if self._app_data_start_ts > 0:
                start_year = datetime.fromtimestamp(self._app_data_start_ts, tz=timezone.utc).year
                _LOGGER.debug(f"app_update_total(): - data start year is set to {start_year}")

            for a_year in range(start_year, current_year_local):
                _LOGGER.debug(f"app_update_total(): - fetching data for year {a_year}")
                if wb_ids is not None:
                    a_url = self.APP_MEASURE_TOTAL_WITH_WB.format(master_plant_id=self._app_master_plant_id,
                                                                  wb_ids    =wb_ids,
                                                                  res_type  ="MONTH",
                                                                  from_val  =quote(app_get_utc_date_start(a_year, 1), safe=''),
                                                                  to_val    =quote(app_get_utc_date_end(a_year, 12), safe=''))

                else:
                    a_url = self.APP_MEASURE_TOTAL.format(master_plant_id=self._app_master_plant_id,
                                                          res_type  ="MONTH",
                                                          from_val  =quote(app_get_utc_date_start(a_year, 1), safe=''),
                                                          to_val    =quote(app_get_utc_date_end(a_year, 12), safe=''))

                data = await self._app_do_get_request(a_url=a_url)
                if data is not None and app_has_dict_timeseries_with_values(data):
                    data = app_aggregate_timeseries_data_if_needed(data)
                    _LOGGER.debug(f"app_update_total(): aggregated data for year {a_year} -> {data}")
                    if self._static_TOTAL_SUMS_PREV_YEARS is None:
                        self._static_TOTAL_SUMS_PREV_YEARS = data
                    else:
                        self._static_TOTAL_SUMS_PREV_YEARS = app_summ_total_dict_values(data, self._static_TOTAL_SUMS_PREV_YEARS)

            self._static_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_YEARS = current_year_local

        # getting PREVIOUS_MONTH - only ONCE
        if self._static_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_MONTHS != current_month_local:
            do_persist = True
            if current_month_local == 1:
                self._static_TOTAL_SUMS_PREV_MONTHS = None
            else:
                _LOGGER.debug(f"app_update_total(): - fetching data for year {current_year_local} month 01 - {(current_month_local-1):02d}")
                if wb_ids is not None:
                    a_url = self.APP_MEASURE_TOTAL_WITH_WB.format(master_plant_id=self._app_master_plant_id,
                                                                  wb_ids    =wb_ids,
                                                                  res_type  ="MONTH",
                                                                  from_val  =quote(app_get_utc_date_start(current_year_local, 1), safe=''),
                                                                  to_val    =quote(app_get_utc_date_end(current_year_local, current_month_local - 1), safe=''))

                else:
                    a_url = self.APP_MEASURE_TOTAL.format(master_plant_id=self._app_master_plant_id,
                                                          res_type  ="MONTH",
                                                          from_val  =quote(app_get_utc_date_start(current_year_local, 1), safe=''),
                                                          to_val    =quote(app_get_utc_date_end(current_year_local, current_month_local - 1), safe=''))

                data = await self._app_do_get_request(a_url=a_url)
                if data is not None and app_has_dict_timeseries_with_values(data):
                    self._static_TOTAL_SUMS_PREV_MONTHS = app_aggregate_timeseries_data_if_needed(data)
                    _LOGGER.debug(f"app_update_total(): aggregated data for year {current_year_local} month 01 - {(current_month_local-1):02d} -> {self._static_TOTAL_SUMS_PREV_MONTHS}")

            self._static_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_MONTHS = current_month_local

        # getting CURRENT_MONTH - only ONCE
        if self._static_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_DAYS != current_day_local:
            do_persist = True
            if current_day_local == 1:
                self._static_TOTAL_SUMS_PREV_DAYS = None
            else:
                _LOGGER.debug(f"***** APP-API: app_update_total() - fetching data for year {current_year_local} month {current_month_local} - till day: {(current_day_local-1):02d}")
                if wb_ids is not None:
                    a_url = self.APP_MEASURE_TOTAL_WITH_WB.format(master_plant_id=self._app_master_plant_id,
                                                                  wb_ids    =wb_ids,
                                                                  res_type  ="MONTH",
                                                                  from_val  =quote(app_get_utc_date_start(current_year_local, current_month_local, 1), safe=''),
                                                                  to_val    =quote(app_get_utc_date_end(current_year_local, current_month_local, current_day_local - 1), safe=''))

                else:
                    a_url = self.APP_MEASURE_TOTAL.format(master_plant_id=self._app_master_plant_id,
                                                          res_type  ="MONTH",
                                                          from_val  =quote(app_get_utc_date_start(current_year_local, current_month_local, 1), safe=''),
                                                          to_val    =quote(app_get_utc_date_end(current_year_local, current_month_local, current_day_local - 1), safe=''))

                data = await self._app_do_get_request(a_url=a_url)
                if data is not None and app_has_dict_timeseries_with_values(data):
                    self._static_TOTAL_SUMS_PREV_DAYS = app_aggregate_timeseries_data_if_needed(data)

            self._static_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_DAYS = current_day_local

        if do_persist:
            # persist the historic-data - so we just must fetch it once
            self._app_token_object[CONF_APP_TOTAL_DATA] = {
                "years":        self._static_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_YEARS,
                "years_data":   self._static_TOTAL_SUMS_PREV_YEARS,
                "months":       self._static_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_MONTHS,
                "months_data":  self._static_TOTAL_SUMS_PREV_MONTHS,
                "days":         self._static_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_DAYS,
                "days_data":    self._static_TOTAL_SUMS_PREV_DAYS
            }
            await self._app_on_new_token_data_received(self._app_token_object)

        # getting TODAY
        if wb_ids is not None:
            a_url = self.APP_MEASURE_TOTAL_WITH_WB.format(master_plant_id=self._app_master_plant_id,
                                                          wb_ids    =wb_ids,
                                                          res_type  ="DAY",
                                                          from_val  =quote(app_get_utc_date_start(current_year_local, current_month_local, current_day_local), safe=''),
                                                          to_val    =quote((now_utc + timedelta(hours=24)).strftime(STRFTIME_DATE_FORMAT), safe=''))

        else:
            a_url = self.APP_MEASURE_TOTAL.format(master_plant_id=self._app_master_plant_id,
                                                  res_type  ="DAY",
                                                  from_val  =quote(app_get_utc_date_start(current_year_local, current_month_local, current_day_local), safe=''),
                                                  to_val    =quote((now_utc + timedelta(hours=24)).strftime(STRFTIME_DATE_FORMAT), safe=''))

        data = await self._app_do_get_request(a_url=a_url)
        if app_has_dict_timeseries_with_values(data):
            data = app_aggregate_timeseries_data_if_needed(data)
            # adding all from the previous years (all till 01.01.THIS YEAR 'minus 1 second')
            if self._static_TOTAL_SUMS_PREV_YEARS is not None:
                data = app_summ_total_dict_values(self._static_TOTAL_SUMS_PREV_YEARS, data)
            # adding all from this year till this-month minus 1 (from 01.01 THIS YEAR)
            if self._static_TOTAL_SUMS_PREV_MONTHS is not None:
                data = app_summ_total_dict_values(self._static_TOTAL_SUMS_PREV_MONTHS, data)
            if self._static_TOTAL_SUMS_PREV_DAYS is not None:
                data = app_summ_total_dict_values(self._static_TOTAL_SUMS_PREV_DAYS, data)

            self._app_raw_total = data

            # filename = f"./{start}.json"
            # directory = os.path.dirname(filename)
            # if not os.path.exists(directory):
            #     os.makedirs(directory)
            #
            # #file_path = os.path.join(os.getcwd(), filename)
            # with open(filename, "w", encoding="utf-8") as outfile:
            #     json.dump(self._app_raw_total, outfile, indent=4)

        else:
            self._app_raw_total = None

        # ok - store the last successful query timestamp
        self._QUERY_TOTALS_TS = time()
        return data

    async def app_update_total_all_wallboxes(self):
        _LOGGER.debug(f"APP-API app_update_total_all_wallboxes for '{self._app_wallbox_num_max}' wallboxes")
        for idx in range(0, self._app_wallbox_num_max):
            if self._app_wallbox_num_max > idx:
                await self._app_update_single_wallbox_total(idx)

        return self.wallbox_consumption_total

    async def _app_update_single_wallbox_total(self, idx:int):
        if self._app_master_plant_id is None:
            await self.app_get_master_plant_id()

        _LOGGER.debug(f"***** APP-API: _app_update_single_wallbox_total(self) index: {idx} ********")
        now_utc = datetime.now(timezone.utc)
        now_local = datetime.now()
        current_year_local = now_local.year
        current_month_local = now_local.month
        current_day_local = now_local.day
        do_persist = False

        # restore the data from our persistent storage
        if CONF_APP_TOTAL_DATA in self._app_token_object and "wallbox" in self._app_token_object[CONF_APP_TOTAL_DATA]:
            storage = self._app_token_object[CONF_APP_TOTAL_DATA]["wallbox"][idx]
        else:
            storage = self._static_TOTAL_WALLBOX_DATA[idx]

        local_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_YEARS  = storage.get("years",      self._static_TOTAL_WALLBOX_DATA[idx].get("years"))
        local_TOTAL_SUMS_PREV_YEARS                  = storage.get("years_data", self._static_TOTAL_WALLBOX_DATA[idx].get("years_data"))
        local_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_MONTHS = storage.get("months",     self._static_TOTAL_WALLBOX_DATA[idx].get("months"))
        local_TOTAL_SUMS_PREV_MONTHS                 = storage.get("months_data",self._static_TOTAL_WALLBOX_DATA[idx].get("months_data"))
        local_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_DAYS   = storage.get("days",       self._static_TOTAL_WALLBOX_DATA[idx].get("days"))
        local_TOTAL_SUMS_PREV_DAYS                   = storage.get("days_data",  self._static_TOTAL_WALLBOX_DATA[idx].get("days_data"))

        # getting PREVIOUS_YEARS - only ONCE
        if local_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_YEARS != current_year_local:
            do_persist = True
            # Loop from the data-available-start to current year [there are no older systems than 2018]
            # we might like to store the first year, that actually has data?!
            start_year = 2018
            if self._app_data_start_ts > 0:
                start_year = datetime.fromtimestamp(self._app_data_start_ts, tz=timezone.utc).year
                _LOGGER.debug(f"_app_update_single_wallbox_total() - data start year is set to {start_year}")

            for a_year in range(start_year, current_year_local):
                _LOGGER.debug(f"_app_update_single_wallbox_total() - fetching data for year {a_year}")
                a_url = self.APP_MEASURE_WB_TOTAL.format(master_plant_id=self._app_master_plant_id,
                                                         wb_id=str((idx + 1)),
                                                         res_type="MONTH",
                                                         from_val=quote(app_get_utc_date_start(a_year, 1), safe=''),
                                                         to_val=quote(app_get_utc_date_end(a_year, 12), safe=''))

                data = await self._app_do_get_request(a_url=a_url)
                if data is not None and app_has_dict_timeseries_with_values(data, ts_key_name="timeseries"):
                    data = app_aggregate_timeseries_data_if_needed(data, ts_key_name="timeseries")
                    _LOGGER.debug(f"_app_update_single_wallbox_total(): aggregated data for year {a_year} -> {data}")
                    if local_TOTAL_SUMS_PREV_YEARS is None:
                        local_TOTAL_SUMS_PREV_YEARS = data
                    else:
                        local_TOTAL_SUMS_PREV_YEARS = app_summ_total_dict_values(data, local_TOTAL_SUMS_PREV_YEARS, ts_key_name="timeseries")

            local_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_YEARS = current_year_local

        # getting PREVIOUS_MONTH - only ONCE
        if local_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_MONTHS != current_month_local:
            do_persist = True
            if current_month_local == 1:
                local_TOTAL_SUMS_PREV_MONTHS = None
            else:
                _LOGGER.debug(f"***** APP-API: _app_update_single_wallbox_total() - fetching data for year {current_year_local} month 01 - {(current_month_local-1):02d}")
                a_url = self.APP_MEASURE_WB_TOTAL.format(master_plant_id=self._app_master_plant_id,
                                                      wb_id=str((idx + 1)),
                                                      res_type  ="MONTH",
                                                      from_val  =quote(app_get_utc_date_start(current_year_local, 1), safe=''),
                                                      to_val    =quote(app_get_utc_date_end(current_year_local, current_month_local - 1), safe=''))

                data = await self._app_do_get_request(a_url=a_url)
                if data is not None and app_has_dict_timeseries_with_values(data, ts_key_name="timeseries"):
                    local_TOTAL_SUMS_PREV_MONTHS = app_aggregate_timeseries_data_if_needed(data, ts_key_name="timeseries")
                    _LOGGER.debug(f"_app_update_single_wallbox_total(): aggregated data for year {current_year_local} month 01 - {(current_month_local-1):02d} -> {local_TOTAL_SUMS_PREV_MONTHS}")

            local_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_MONTHS = current_month_local

        # getting CURRENT_MONTH - only ONCE
        if local_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_DAYS != current_day_local:
            do_persist = True
            if current_day_local == 1:
                local_TOTAL_SUMS_PREV_DAYS = None
            else:
                _LOGGER.debug(f"***** APP-API: _app_update_single_wallbox_total() - fetching data for year {current_year_local} month {current_month_local} - till day: {(current_day_local-1):02d}")
                a_url = self.APP_MEASURE_WB_TOTAL.format(master_plant_id=self._app_master_plant_id,
                                                         wb_id     =str((idx + 1)),
                                                         res_type  ="MONTH",
                                                         from_val  =quote(app_get_utc_date_start(current_year_local, current_month_local, 1), safe=''),
                                                         to_val    =quote(app_get_utc_date_end(current_year_local, current_month_local, current_day_local - 1), safe=''))

                data = await self._app_do_get_request(a_url=a_url)
                if data is not None and app_has_dict_timeseries_with_values(data, ts_key_name="timeseries"):
                    local_TOTAL_SUMS_PREV_DAYS = app_aggregate_timeseries_data_if_needed(data, ts_key_name="timeseries")

            local_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_DAYS = current_day_local

        if do_persist:
            # persist the historic-data - so we just must fetch it once
            if "wallbox" not in self._app_token_object[CONF_APP_TOTAL_DATA]:
                self._app_token_object[CONF_APP_TOTAL_DATA]["wallbox"] = self._static_TOTAL_WALLBOX_DATA

            self._app_token_object[CONF_APP_TOTAL_DATA]["wallbox"][idx] = {
                "years":        local_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_YEARS,
                "years_data":   local_TOTAL_SUMS_PREV_YEARS,
                "months":       local_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_MONTHS,
                "months_data":  local_TOTAL_SUMS_PREV_MONTHS,
                "days":         local_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_DAYS,
                "days_data":    local_TOTAL_SUMS_PREV_DAYS
            }
            await self._app_on_new_token_data_received(self._app_token_object)

        # getting TODAY
        a_url = self.APP_MEASURE_WB_TOTAL.format(master_plant_id=self._app_master_plant_id,
                                                 wb_id      =str((idx + 1)),
                                                 res_type   ="DAY",
                                                 from_val   =quote(app_get_utc_date_start(current_year_local, current_month_local, current_day_local), safe=''),
                                                 to_val     =quote((now_utc + timedelta(hours=24)).strftime(STRFTIME_DATE_FORMAT), safe=''))

        data = await self._app_do_get_request(a_url=a_url)
        if app_has_dict_timeseries_with_values(data, ts_key_name="timeseries"):
            data = app_aggregate_timeseries_data_if_needed(data, ts_key_name="timeseries")
            # adding all from the previous years (all till 01.01.THIS YEAR 'minus 1 second')
            if local_TOTAL_SUMS_PREV_YEARS is not None:
                data = app_summ_total_dict_values(local_TOTAL_SUMS_PREV_YEARS, data, ts_key_name="timeseries")
            # adding all from this year till this-month minus 1 (from 01.01 THIS YEAR)
            if local_TOTAL_SUMS_PREV_MONTHS is not None:
                data = app_summ_total_dict_values(local_TOTAL_SUMS_PREV_MONTHS, data, ts_key_name="timeseries")
            if local_TOTAL_SUMS_PREV_DAYS is not None:
                data = app_summ_total_dict_values(local_TOTAL_SUMS_PREV_DAYS, data, ts_key_name="timeseries")

            self._app_raw_wb_total[idx] = data

        else:
            self._app_raw_wb_total[idx] = None

        return data


    #####################
    # all new WALLBOX stuff
    #
    #####################
    # NEW OBJECT
    # sample_data =[
    #     {
    #         "id": "1",
    #         "productFamily": None,
    #         "controllerId": "Sxxxxxxxxxxxxxxxxxxxxxxxxxx",
    #         "name": "Wallbox 1",
    #         "prohibitUsage": False,
    #         "isInterchargeAvailable": True,
    #         "isSolarChargingAvailable": True,
    #         "type": "V123",
    #         "state": {
    #             "electricVehicleConnected": False,
    #             "hasError": False,
    #             "temperatureInCelsius": 27.498,
    #             "isCharging": False,
    #             "statusCode": "WAITING_FOR_EV"
    #         },
    #         "chargingMode": {
    #             "type": "SOLAR",
    #             "allowIntercharge": True,
    #             "compatibilityMode": True,
    #             "fastChargingSettings": {
    #                 "allowIntercharge": True
    #             },
    #             "comfortChargeSettings": {
    #                 "allowIntercharge": False,
    #                 "compatibilityMode": True,
    #                 "configuredChargingCurrent": 9,
    #                 "activeWeekDays": [
    #                     "MON",
    #                     "THU",
    #                     "FRI"
    #                 ],
    #                 "useDynamicTariffs": None,
    #                 "chargingPeriodFromGridInH": None,
    #                 "priceLimitInCtPerKwh": None
    #             },
    #             "solarOptimizeSettings": {
    #                 "compatibilityMode": True,
    #                 "minChargingCurrentInA": 9,
    #                 "useDynamicTariffs": None,
    #                 "priceLimitInCtPerKwh": None
    #             }
    #         },
    #         "chargingCurrents": {
    #             "minPossibleCharging": 6,
    #             "configuredChargingCurrent": 9,
    #             "currentApparentChargingPowerInKw": 0
    #         },
    #         "chargingPowerStats": {
    #             "phase1": {
    #                 "min": 2.07,
    #                 "max": 3.685
    #             },
    #             "phase2": {
    #                 "min": 4.14,
    #                 "max": 7.369
    #             },
    #             "phase3": {
    #                 "min": 6.21,
    #                 "max": 11.054
    #             },
    #             "numberOfPhasesUsed": 0
    #         },
    #         "disconnected": False
    #     }
    # ]

    # OLD OBJECT
    # sample_data = {
    #     "id": 1,
    #     "configurable": True,
    #     "maxPossibleChargingCurrentInA": 16.02,
    #     "minPossibleChargingCurrentInA": 6,
    #     "chargingMode": "SMART_SELF_GENERATED_COMPATIBILITY_MODE",
    #     "currentApparentChargingPowerInVa": 4928,
    #     "electricVehicleConnected": True,
    #     "hasError": False,
    #     "statusText": "Lädt",
    #     "configuredMaxChargingCurrentInA": 16.02,
    #     "configuredMinChargingCurrentInA": 8,
    #     "temperatureInCelsius": 17.284,
    #     "numberOfElectricPowerPhasesUsed": 3,
    #     "allowIntercharge": None,
    #     "compatibilityMode": True
    # }

    def _app_get_wallbox_object_at_index(self, idx:int):
        if self._app_raw_wallbox is not None and len(self._app_raw_wallbox) > idx:
            a_wallbox_obj = self._app_raw_wallbox[idx]
            if a_wallbox_obj is not None and isinstance(a_wallbox_obj, dict):
                return a_wallbox_obj
        return {}

    def _app_set_wallbox_object_at_index(self, idx:int, data:dict):
        if self._app_raw_wallbox is not None and len(self._app_raw_wallbox) > idx and self._app_raw_wallbox[idx] is not None:
            self._app_raw_wallbox[idx] = data

    def _app_get_local_wallbox_mode_from_api_values(self, idx: int) -> str:
        a_wallbox_obj = self._app_get_wallbox_object_at_index(idx)

        # step 1 checking the LOCK/UNLOCK state…
        if "prohibitUsage" in a_wallbox_obj:
            if a_wallbox_obj["prohibitUsage"]:
                return LOCAL_WB_MODE_LOCKED
        elif len(a_wallbox_obj) > 0:
            _LOGGER.info(f"_app_get_local_wallbox_mode_from_api_values(): no 'prohibitUsage' in {a_wallbox_obj}")

        # step 2 checking the chargingMode…
        charging_mode_obj = a_wallbox_obj.get("chargingMode", {})
        if "type" in charging_mode_obj:
            a_type = charging_mode_obj.get("type", None)
            if a_type is not None:
                # FAST or SOLAR
                if a_type.upper() == APP_API_WB_MODE_2025_SOLAR:
                    if charging_mode_obj.get("compatibilityMode", False):
                        return LOCAL_WB_MODE_SSGCM_3
                    else:
                        return LOCAL_WB_MODE_SSGCM_4

                elif a_type.upper() == APP_API_WB_MODE_2025_FAST:
                    return LOCAL_WB_MODE_FASTEST
                else:
                    _LOGGER.info(f"_app_get_local_wallbox_mode_from_api_values(): UNKNOWN 'type' value: '{type}' in {charging_mode_obj}")
            else:
                _LOGGER.info(f"_app_get_local_wallbox_mode_from_api_values(): 'type' is None in {charging_mode_obj}")
        elif len(a_wallbox_obj) > 0:
            _LOGGER.info(f"_app_get_local_wallbox_mode_from_api_values(): no 'type' in {charging_mode_obj}")

        return LOCAL_WB_MODE_UNKNOWN

    async def app_update_all_wallboxes(self):
        _LOGGER.debug("***** APP-API: app_update_all_wallboxes(self) ********")
        data = await self._app_do_post_request(self.APP_WALLBOX_SEARCH, post_data={"systemIds":[self._app_master_plant_id]}, read_response=True)
        # the data should be an array… and this array should have the same length then
        # our known wallboxes… [but it's better to check that]

        # Check if data is valid and has content
        if not data or not isinstance(data, list):
            _LOGGER.warning(f"app_update_all_wallboxes(): No valid wallbox data received or data is not a list '{data}'")
            return

        # Check if we have enough data for all expected wallboxes
        if len(data) < self._app_wallbox_num_max:
            _LOGGER.info(f"app_update_all_wallboxes(): Expected {self._app_wallbox_num_max} wallboxes but only received {len(data)}")

        max_idx = min(len(data), self._app_wallbox_num_max)

        # python: 'range(x, y)' will not include 'y'
        for idx in range(0, max_idx):
            self._app_raw_wallbox[idx] = data[idx]

    async def app_set_wallbox_mode(self, local_mode_to_set: str, wallbox_num: int = 1, sync: bool = True):
        _LOGGER.debug("***** APP-API: app_set_wallbox_mode(self) ********")
        idx = wallbox_num - 1
        cur_local_mode = self._app_get_local_wallbox_mode_from_api_values(idx)
        if cur_local_mode == local_mode_to_set:
            _LOGGER.debug(f"app_set_wallbox_mode(): skipp mode change since '{local_mode_to_set}' already set")
        else:
            # first check if we are initialized…
            if self._app_master_plant_id is None:
                await self.app_get_master_plant_id()

            success = False
            if self._app_master_plant_id is not None:
                # check, if we switch to the LOCK mode
                if local_mode_to_set == LOCAL_WB_MODE_LOCKED:
                    wb_url = self.APP_SET_WALLBOX_LOCK.format(master_plant_id=str(self._app_master_plant_id),
                                                              wb_id=str(wallbox_num),
                                                              lc_lock_state="true")

                    data = await self._app_do_get_request(wb_url, do_as_patch=True)
                    if data is not None:
                        self._app_set_wallbox_object_at_index(idx, data)
                        _LOGGER.debug(f"app_set_wallbox_mode(): set wallbox {wallbox_num} to LOCK: {util.mask_map(data)}")
                        success = True
                    else:
                        _LOGGER.debug(f"app_set_wallbox_mode(): set wallbox {wallbox_num} LOCK FAILED")
                else:
                    # when we switch to any other mode, we must check
                    # if we are currently locked - and if we are locked, we
                    # must unlock first
                    if cur_local_mode == LOCAL_WB_MODE_LOCKED:
                        wb_url = self.APP_SET_WALLBOX_LOCK.format(master_plant_id=str(self._app_master_plant_id),
                                                                  wb_id=str(wallbox_num),
                                                                  lc_lock_state="false")

                        data = await self._app_do_get_request(wb_url, do_as_patch=True)
                        if data is not None:
                            self._app_set_wallbox_object_at_index(idx, data)
                            _LOGGER.debug(f"app_set_wallbox_mode(): set wallbox {wallbox_num} to UNLOCK: {util.mask_map(data)}")
                        else:
                            _LOGGER.debug(f"app_set_wallbox_mode(): set wallbox {wallbox_num} UNLOCK FAILED")

                    # now setting the final mode…
                    if local_mode_to_set == LOCAL_WB_MODE_FASTEST:
                        # setting FAST MODE
                        wb_url = self.APP_SET_WALLBOX_FC.format(master_plant_id=str(self._app_master_plant_id),
                                                                wb_id=str(wallbox_num))

                        # I just can guess, that 'allowIntercharge' means to use battery…
                        allow_intercharge = True  # default value
                        if self._SenecLocal is not None:
                            allow_intercharge = self._SenecLocal.wallbox_allow_intercharge

                        data = await self._app_do_post_request(wb_url, post_data={"allowIntercharge": allow_intercharge}, read_response=True)
                        if data is not None:
                            self._app_set_wallbox_object_at_index(idx, data)
                            _LOGGER.debug(f"app_set_wallbox_mode(): set wallbox {wallbox_num} to FAST: {util.mask_map(data)}")
                            success = True
                        else:
                            _LOGGER.debug(f"app_set_wallbox_mode(): set wallbox {wallbox_num} FAST FAILED")

                    elif local_mode_to_set == LOCAL_WB_MODE_SSGCM_3 or local_mode_to_set == LOCAL_WB_MODE_SSGCM_4:
                        # setting SOLAR mode (with or without compatibility)
                        the_post_data = {
                            "compatibilityMode": True if local_mode_to_set == LOCAL_WB_MODE_SSGCM_3 else False,
                        }

                        # try to copy over all other attributes from the current chargingMode:solarOptimizeSettings
                        a_wallbox_object = self._app_get_wallbox_object_at_index(idx)
                        solar_optimize_settings = a_wallbox_object.get("chargingMode", {}).get("solarOptimizeSettings", None)
                        if solar_optimize_settings is not None:
                            for a_field in ["minChargingCurrentInA", "useDynamicTariffs", "priceLimitInCtPerKwh"]:
                                a_value = solar_optimize_settings.get(a_field, None)
                                if a_value is not None:
                                    the_post_data[a_field] = a_value
                        else:
                            _LOGGER.debug(f"app_set_wallbox_mode(): wallbox {wallbox_num} - no 'solar_optimize_settings' - just using default 'compatibilityMode' - wallbox object: {a_wallbox_object}")

                        _LOGGER.debug(f"app_set_wallbox_mode(): set wallbox {wallbox_num} to SOLAR final post data: {the_post_data}")
                        wb_url = self.APP_SET_WALLBOX_SC.format(master_plant_id=str(self._app_master_plant_id),
                                                                wb_id=str(wallbox_num))

                        data = await self._app_do_post_request(wb_url, post_data=the_post_data, read_response=True)
                        if data is not None:
                            self._app_set_wallbox_object_at_index(idx, data)
                            _LOGGER.debug(f"app_set_wallbox_mode(): set wallbox {wallbox_num} to SOLAR: {util.mask_map(data)}")
                            success = True
                        else:
                            _LOGGER.debug(f"app_set_wallbox_mode(): set wallbox {wallbox_num} SOLAR FAILED")
                    else:
                        _LOGGER.info(f"app_set_wallbox_mode(): UNKNOWN mode to set: '{local_mode_to_set}' - skipping mode change")

                if success:
                    # do we need to sync the value back to the 'lala_cgi' integration?
                    if sync and self._SenecLocal is not None:
                        # since the '_set_wallbox_mode_post' method is not calling the APP-API again, there
                        # is no sync=False parameter here…
                        await self._SenecLocal.set_wallbox_mode_post_int(pos=idx, local_value=local_mode_to_set)

                    # when we changed the mode, the backend might have automatically adjusted the
                    # 'chargingMode:solarOptimizeSettings:minChargingCurrentInA' so we need to sync
                    # this possible change with the LaLa_cgi no matter, if the 'app_set_wallbox_mode'
                    # have been called with sync=False (or not)!!!
                    if local_mode_to_set == LOCAL_WB_MODE_SSGCM_3 or local_mode_to_set == LOCAL_WB_MODE_SSGCM_4:
                        await asyncio.sleep(2)
                        await self.app_update_all_wallboxes()

                        a_wallbox_obj = self._app_get_wallbox_object_at_index(idx)
                        a_charging_mode_obj = a_wallbox_obj.get("chargingMode", {})
                        a_charging_mode_type = a_charging_mode_obj.get("type", None)
                        if a_charging_mode_type is not None and a_charging_mode_type == APP_API_WB_MODE_2025_SOLAR:
                            a_solar_settings_obj = a_charging_mode_obj.get("solarOptimizeSettings", {})
                            min_charging_current_in_a_value = a_solar_settings_obj.get("minChargingCurrentInA", None)
                            if min_charging_current_in_a_value is not None:
                                new_min_current = str(round(float(min_charging_current_in_a_value), 2))
                                cur_min_current = str(round(self._SenecLocal.wallbox_set_icmax[idx], 2))

                                if cur_min_current != new_min_current:
                                    _LOGGER.debug(f"app_set_wallbox_mode(): 2sec after mode change: local set_ic_max {cur_min_current} will be updated to {new_min_current}")
                                    await self._SenecLocal.set_nva_wallbox_set_icmax(pos=idx,
                                                                                       value=float(new_min_current),
                                                                                       sync=False, verify_state=False)
                                else:
                                    _LOGGER.debug(f"app_set_wallbox_mode(): 2sec after mode change: NO CHANGE! - local set_ic_max: {cur_min_current} equals: {new_min_current}]")

                    # OLD-IMPLEMENTATION HERE (just as reference)
                    # # when we changed the mode, the backend might have automatically adjusted the
                    # # 'configuredMinChargingCurrentInA' so we need to sync this possible change with the LaLa_cgi
                    # # no matter, if the 'app_set_wallbox_mode' have been called with sync=False (or not)!!!
                    # await asyncio.sleep(2)
                    # await self.app_get_wallbox_data(wallbox_num=wallbox_num)
                    # if self._app_raw_wallbox[idx] is not None:
                    #     if local_mode_to_set == LOCAL_WB_MODE_FASTEST:
                    #         new_min_current_tmp = self._app_raw_wallbox[idx]["maxPossibleChargingCurrentInA"]
                    #     else:
                    #         new_min_current_tmp = self._app_raw_wallbox[idx]["configuredMinChargingCurrentInA"]
                    #
                    #     new_min_current = str(round(float(new_min_current_tmp), 2))
                    #     cur_min_current = str(round(self._SenecLocal.wallbox_set_icmax[idx], 2))
                    #
                    #     if cur_min_current != new_min_current:
                    #         _LOGGER.debug(f"APP-API 2sec after mode change: local set_ic_max {cur_min_current} will be updated to {new_min_current}")
                    #         await self._SenecLocal.set_nva_wallbox_set_icmax(pos=idx,
                    #                                                            value=float(new_min_current),
                    #                                                            sync=False, verify_state=False)
                    #     else:
                    #         _LOGGER.debug(f"APP-API 2sec after mode change: NO CHANGE! - local set_ic_max: {cur_min_current} equals: {new_min_current}]")
                    #
                    # else:
                    #     _LOGGER.debug(f"APP-API could not read wallbox data 2sec after mode change")

    async def app_set_wallbox_icmax(self, value_to_set: float, wallbox_num: int = 1, sync: bool = True):
        _LOGGER.debug("***** APP-API: app_set_wallbox_icmax(self) ********")
        if self._app_master_plant_id is None:
            await self.app_get_master_plant_id()

        if self._app_master_plant_id is not None:
            success = False
            idx = wallbox_num - 1
            a_wallbox_obj = self._app_get_wallbox_object_at_index(idx)
            a_charging_mode_obj = a_wallbox_obj.get("chargingMode", {})
            a_charging_mode_type = a_charging_mode_obj.get("type", None)

            # only if the current mode is the SOLAR, we can set the 'minChargingCurrentInA'
            if a_charging_mode_type is not None and a_charging_mode_type == APP_API_WB_MODE_2025_SOLAR:
                the_post_data = {
                    "minChargingCurrentInA": float(round(value_to_set, 2))
                }
                solar_optimize_settings = a_charging_mode_obj.get("solarOptimizeSettings", None)
                if solar_optimize_settings is not None:
                    for a_field in ["compatibilityMode", "useDynamicTariffs", "priceLimitInCtPerKwh"]:
                        a_value = solar_optimize_settings.get(a_field, None)
                        if a_value is not None:
                            the_post_data[a_field] = a_value
                else:
                    _LOGGER.debug(f"app_set_wallbox_icmax(): wallbox {wallbox_num} - no 'solar_optimize_settings' - just using default 'compatibilityMode' - wallbox object: {a_wallbox_obj}")

                # continue...
                wb_url = self.APP_SET_WALLBOX_SC.format(master_plant_id=str(self._app_master_plant_id), wb_id=str(wallbox_num))
                data = await self._app_do_post_request(a_url=wb_url, post_data=the_post_data, read_response=True)
                if data is not None:
                    self._app_set_wallbox_object_at_index(idx, data)
                    _LOGGER.debug(f"app_set_wallbox_icmax(): set wallbox {wallbox_num} SOLAR attributes: {util.mask_map(data)}")
                    success = True
                else:
                    _LOGGER.debug(f"app_set_wallbox_icmax(): set wallbox {wallbox_num} SOLAR FAILED")
            else:
                _LOGGER.debug(f"app_set_wallbox_icmax(): wallbox {wallbox_num} - current mode is not SOLAR, so we cannot set 'minChargingCurrentInA' - current mode: '{a_charging_mode_type}' - wallbox object: {a_wallbox_obj}")


            if success:
                # do we need to sync the value back to the 'lala_cgi' integration?
                if sync and self._SenecLocal is not None:
                    await self._SenecLocal.set_nva_wallbox_set_icmax(pos=idx, value=value_to_set, sync=False)

    async def app_set_allow_intercharge_all(self, value_to_set: bool, sync: bool = True):
        _LOGGER.debug(f"APP-API app_set_allow_intercharge_all for '{self._app_wallbox_num_max}' wallboxes")
        for idx in range(0, self._app_wallbox_num_max):
            if self._app_wallbox_num_max > idx:
                res = await self._app_set_allow_intercharge(value_to_set=value_to_set, wallbox_num=(idx + 1), sync=sync)

    async def _app_set_allow_intercharge(self, value_to_set: bool, wallbox_num: int = 1, sync: bool = True) -> bool:
        _LOGGER.debug("***** APP-API: _app_set_allow_intercharge(self) ********")
        if self._app_master_plant_id is None:
            await self.app_get_master_plant_id()

        if self._app_master_plant_id is not None:
            idx = wallbox_num - 1
            a_wallbox_obj = self._app_get_wallbox_object_at_index(idx)
            a_charging_mode_type = a_wallbox_obj.get("chargingMode", {}).get("type", None)

            # only if the current mode is the SOLAR, we can set the 'minChargingCurrentInA'
            if a_charging_mode_type is not None and a_charging_mode_type == APP_API_WB_MODE_2025_FAST:
                the_post_data = {
                    "allowIntercharge": value_to_set
                }
                wb_url = self.APP_SET_WALLBOX_FC.format(master_plant_id=str(self._app_master_plant_id), wb_id=str(wallbox_num))
                data = await self._app_do_post_request(a_url=wb_url, post_data=the_post_data, read_response=True)
                if data is not None:
                    # setting the internal storage value…
                    self._app_set_wallbox_object_at_index(idx, data)

                    # do we need to sync the value back to the 'lala_cgi' integration?
                    if sync and self._SenecLocal is not None:
                        await self._SenecLocal.switch_wallbox_allow_intercharge(value=value_to_set, sync=False)

                    return True
                else:
                    _LOGGER.debug(f"_app_set_allow_intercharge(): wallbox {wallbox_num} FAST allowIntercharge FAILED")
            else:
                _LOGGER.debug(f"_app_set_allow_intercharge(): wallbox {wallbox_num} - current mode is not FAST, so we cannot set 'allowIntercharge' - current mode: '{a_charging_mode_type}' - wallbox object: {a_wallbox_obj}")
        return False

    # def app_get_api_wallbox_mode_from_local_value(self, local_mode: str) -> str:
    #     if local_mode == LOCAL_WB_MODE_LOCKED:
    #         return APP_API_WB_MODE_LOCKED
    #     elif local_mode == LOCAL_WB_MODE_SSGCM_3:
    #         return APP_API_WB_MODE_SSGCM
    #     elif local_mode == LOCAL_WB_MODE_SSGCM_4:
    #         return APP_API_WB_MODE_SSGCM
    #     elif local_mode == LOCAL_WB_MODE_FASTEST:
    #         return APP_API_WB_MODE_FASTEST
    #     return local_mode


    """MEIN-SENEC.DE from here"""
    async def web_authenticate(self, do_update:bool=False, throw401:bool=False):
        if not self._web_is_authenticated:
            _LOGGER.debug("***** WEB-API: web_authenticate(self) ********")
            try:
                async with (self.web_session.get(self._WEB_BASE_URL, allow_redirects=True, max_redirects=20, headers=self._default_web_headers) as res):
                    res.raise_for_status()
                    if res.status in [200, 201, 202, 204, 205]:
                        html_content = await res.text()
                        # that's quite evil - parsing HTML via RegEx

                        # the simple variant, just take ANY form..
                        # match = re.search(r'<form[^>]*action="([^"]+)"', html_content)
                        # the_form_action_url = match.group(1) if match else None

                        # the complex one, search for username & password inputs
                        form_match = re.search(r'<form[^>]*action="([^"]+)"[^>]*>(.*?)</form>', html_content, re.DOTALL | re.IGNORECASE)
                        the_form_action_url = None
                        if form_match:
                            form_content = form_match.group(2)
                            # Check if the form contains both username and password inputs
                            has_username = re.search(r'<input[^>]*(?:name|id)=["\']?(?:username|user|email)["\']?[^>]*>', form_content, re.IGNORECASE)
                            has_password = re.search(r'<input[^>]*(?:name|id)=["\']?password["\']?[^>]*>', form_content, re.IGNORECASE)
                            if has_username and has_password:
                                # This is the login form we're looking for
                                the_form_action_url = form_match.group(1)

                        if the_form_action_url:
                            await self._web_authenticate_part_02(the_form_action_url.replace('&amp;', '&'), do_update, throw401)
                        else:
                            if (str(res.request_info.url).lower().startswith(self._WEB_BASE_URL.lower()) or
                                    self._web_validate_html_structure(html_content=html_content)):
                                _LOGGER.info(f"web_authenticate(): looks like are already authenticated")
                                await self._web_set_is_authenticated(do_update=do_update)
                            else:
                                _LOGGER.error(f"web_authenticate(): no form action url could be found {html_content}")
                    else:
                        _LOGGER.error(f"web_authenticate(): unexpected status code [200] {res.status} - {res}")
            except Exception as exc:
                if throw401:
                    raise exc
                else:
                    _LOGGER.error(f"web_authenticate(): Error when try to call {self._WEB_BASE_URL}: '{exc}'")

    def _web_validate_html_structure(self, html_content: str) -> bool:
        """Quick check for main Angular components in the HTML content"""
        required_components = [
            r'ng-controller="MainController"',
            r'<nav[^>]*id="header"',
            r'ng-include="\'static/templates/header\.html',
            r'ng-include="\'static/templates/navigation\.html',
            r'<div[^>]*ng-view[^>]*ng-if="endkunde"',
            r'ng-include="\'static/templates/footer\.html'
        ]
        missing_components = []
        for component in required_components:
            if not re.search(component, html_content, re.IGNORECASE):
                missing_components.append(component)

        if missing_components:
            _LOGGER.info(f"_web_validate_html_structure(): Missing HTML components: {missing_components}")
            return False

        _LOGGER.debug("_web_validate_html_structure(): All required HTML components found")
        return True

    async def _web_authenticate_part_02(self, form_action_url, do_update:bool=False, throw401:bool=False):
        req_headers = self._default_web_headers.copy()
        req_headers["Accept"]           = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
        req_headers["authority"]        = "sso.senec.com"
        req_headers["Dtn"]              = "1"
        req_headers["origin"]           = "null"
        req_headers["Content-Type"]     = "application/x-www-form-urlencoded"
        req_headers["Cache-Control"]    = "max-age=0"

        login_data= {
            "username": self._SENEC_USERNAME,
            "password": self._SENEC_PASSWORD
        }

        async with self.web_session.post(form_action_url, data=login_data, allow_redirects=True, max_redirects=20, headers=req_headers) as res:
            try:
                _LOGGER.debug(f"_web_authenticate_part_02(): requesting: {form_action_url}")
                res.raise_for_status()
                if res.status in [200, 201, 202, 204, 205]:
                    content = await res.text()
                    if "configure_totp" in str(res.request_info.url).lower():
                        self.web_totp_required = True
                        _LOGGER.warning(f"SENEC require TOTP configuration - currently not supported by the Integration - some features will not work! - {res.request_info.url}")
                    else:
                        _LOGGER.debug(f"finally reached: {res.request_info.url}")
                        await self._web_set_is_authenticated(do_update=do_update)
                else:
                    self.purge_senec_cookies()
                    _LOGGER.info(f"_web_authenticate_part_02(): unexpected [200] response code: {res.status} - {res}")

            except BaseException as exc:
                if throw401:
                    raise exc
                else:
                    _LOGGER.info(f"_web_authenticate_part_02(): status code: {res.status} [{type(exc).__name__} - {exc}]")
                    if exc.status == 401:
                        self.purge_senec_cookies()
                        self._web_is_authenticated = False
                    else:
                        self.purge_senec_cookies()

    async def _web_set_is_authenticated(self, do_update:bool=False):
        self._web_is_authenticated = True
        if self._web_master_plant_number is None:
            await self.web_update_context()

        if self._web_master_plant_number is not None:
            _LOGGER.info("Login successful")
            if do_update:
                await self.update()

    async def web_update_context(self, force_autodetect:bool = False):
        if self.web_totp_required:
            _LOGGER.info("***** skipped cause TOTP required - web_update_context(self) ********")
            return

        _LOGGER.debug("***** web_update_context(self) ********")
        if self._web_is_authenticated:
            await self.web_update_get_customer()

            # in autodetect-mode the initial self._web_master_plant_number = -1
            if self._web_master_plant_number is None or self._web_master_plant_number == -1 or force_autodetect:
                self._web_master_plant_number = 0
                is_autodetect = True
            else:
                is_autodetect = False

            # I must check if we still need this, since we have now code, that tries to compare
            # self._app_serial_number with the returned 'steuereinheitnummer' of the
            # web [but of course only when app-impl is back]
            if self._app_master_plant_number is not None and self._app_master_plant_number > 0:
                self._web_master_plant_number = self._app_master_plant_number

            await self.web_update_get_systems(a_plant_number=self._web_master_plant_number, autodetect_mode=is_autodetect)
        else:
            await self.web_authenticate(do_update=False, throw401=False)
            if self._web_is_authenticated:
                await self.web_update_context()

    async def web_update_get_customer(self):
        if self.web_totp_required:
            _LOGGER.info("***** skipped cause TOTP required - web_update_get_customer(self) ********")
            return

        _LOGGER.debug("***** web_update_get_customer(self) ********")

        # grab NOW and TODAY stats
        async with self.web_session.get(self._WEB_GET_CUSTOMER, headers=self._default_web_headers, ssl=False) as res:
            res.raise_for_status()
            if res.status in [200, 201, 202, 205]:
                try:
                    r_json = await res.json()
                    self._web_dev_number = r_json["devNumber"]
                except JSONDecodeError as exc:
                    _LOGGER.warning(f"JSONDecodeError while 'await res.json()' {exc}")
            else:
                self._web_is_authenticated = False
                await self.web_authenticate(do_update=False, throw401=False)

    async def web_update_get_systems(self, a_plant_number: int, autodetect_mode: bool):
        if self.web_totp_required:
            _LOGGER.info(f"***** skipped cause TOTP required - web_update_get_systems(self) - trying AnlagenNummer: {a_plant_number} ********")
            return

        _LOGGER.debug(f"***** web_update_get_systems(self) - trying AnlagenNummer: {a_plant_number} ********")

        a_url = self._WEB_GET_SYSTEM_INFO % str(a_plant_number)
        async with self.web_session.get(a_url, headers=self._default_web_headers, ssl=False) as res:
            res.raise_for_status()
            if res.status in [200, 201, 202, 205]:
                try:
                    r_json = await res.json()
                    #_LOGGER.debug(f"web_update_get_systems() - response: {r_json}")
                    if autodetect_mode:
                        if "master" in r_json and r_json["master"]:
                            # we are cool that's a master-system… so we store our counter…
                            self._web_serial_number = r_json["steuereinheitnummer"]
                            if self._app_serial_number is None or self._app_serial_number == r_json["steuereinheitnummer"]:
                                self._web_product_name = r_json["produktName"]
                                if "zoneId" in r_json:
                                    self._web_zone_id = r_json["zoneId"]
                                else:
                                    self._web_zone_id = "UNKNOWN"
                                self._web_master_plant_number = a_plant_number
                                _LOGGER.debug(f"set _web_master_plant_number to {a_plant_number} (Found a web master system with serial number: {util.mask_string(self._web_serial_number)} [{self._web_product_name}])")
                            else:
                                # ok it looks like the serial number does not match… let's request another system
                                _LOGGER.debug(f"Found a web master system with serial number: {util.mask_string(self._web_serial_number)} [{r_json['produktName']}] - but not matching the SenecApp serial number: {util.mask_string(self._app_serial_number)}")
                                a_plant_number += 1
                                await self.web_update_get_systems(a_plant_number, autodetect_mode)
                        else:
                            if not hasattr(self, "_serial_number_slave"):
                                self._serial_number_slave = []
                                self._product_name_slave = []
                            self._serial_number_slave.append(r_json["steuereinheitnummer"])
                            self._product_name_slave.append(r_json["produktName"])
                            a_plant_number += 1
                            await self.web_update_get_systems(a_plant_number, autodetect_mode)
                    else:
                        self._web_serial_number = r_json["steuereinheitnummer"]
                        self._web_product_name = r_json["produktName"]
                        if "zoneId" in r_json:
                            self._web_zone_id = r_json["zoneId"]
                        else:
                            self._web_zone_id = "UNKNOWN"
                        self._web_master_plant_number = a_plant_number

                    # let's check if the sytem support's SG-Read…
                    if "sgReadyVisible" in r_json and r_json["sgReadyVisible"]:
                        _LOGGER.debug("System is SGReady")
                        self.SGREADY_SUPPORTED = True

                except JSONDecodeError as exc:
                    _LOGGER.warning(f"JSONDecodeError while 'await res.json()' {exc}")
            else:
                self._web_is_authenticated = False
                await self.web_authenticate(do_update=False, throw401=False)

    async def web_update_now(self, retry:bool=True):
        if self.web_totp_required:
            _LOGGER.info("***** skipped cause TOTP required - web_update_now(self) ********")
            return

        _LOGGER.debug("***** web_update_now(self) ********")
        # grab NOW and TODAY stats
        a_url = self._WEB_GET_OVERVIEW_URL % str(self._web_master_plant_number)
        async with self.web_session.get(a_url, headers=self._default_web_headers, ssl=False) as res:
            try:
                _LOGGER.debug(f"web_update_now() requesting: {a_url}")
                res.raise_for_status()
                if res.status in [200, 201, 202, 204, 205]:
                    try:
                        r_json = await res.json()
                        _LOGGER.debug(f"web_update_now() response-received: {r_json}")
                        self._web_raw = parse(r_json)
                        for key in (self._WEB_REQUEST_KEYS + self._WEB_REQUEST_KEYS_EXTRA):
                            if key in r_json:
                                if key == "acculevel":
                                    if "now" in r_json[key]:
                                        value_now = r_json[key]["now"]
                                        entity_now_name = str(key + "_now")
                                        self._web_battery_entities[entity_now_name] = value_now
                                    else:
                                        _LOGGER.info(f"web_update_now() No 'now' for key: '{key}' in json: {r_json} when requesting: {a_url}")
                                else:
                                    if "now" in r_json[key]:
                                        value_now = r_json[key]["now"]
                                        entity_now_name = str(key + "_now")
                                        self._web_power_entities[entity_now_name] = value_now
                                    else:
                                        _LOGGER.info(f"web_update_now() No 'now' for key: '{key}' in json: {r_json} when requesting: {a_url}")

                                    if "today" in r_json[key]:
                                        value_today = r_json[key]["today"]
                                        entity_today_name = str(key + "_today")
                                        self._web_energy_entities[entity_today_name] = value_today
                                    else:
                                        _LOGGER.info(f"web_update_now() No 'today' for key: '{key}' in json: {r_json} when requesting: {a_url}")

                            else:
                                _LOGGER.info(f"web_update_now() No '{key}' in json: {r_json} when requesting: {a_url}")
                    except JSONDecodeError as exc:
                        _LOGGER.warning(f"web_update_now() JSONDecodeError while 'await res.json()' {exc}")

                else:
                    self._is_authenticated = False
                    if retry:
                        await self.web_update(retry=False)

            except ClientResponseError as exc:
                if exc.status == 401:
                    self.purge_senec_cookies()
                if exc.status != 408:
                    self._is_authenticated = False
                if retry:
                    await self.web_update_now(retry=False)

    async def web_update_total(self):
        if self.web_totp_required:
            _LOGGER.info("***** skipped cause TOTP required - web_update_total(self) ********")
            return

        # grab TOTAL stats
        if self._web_master_plant_number is None or self._web_master_plant_number == -1:
            _LOGGER.warning("web_update_total() called without valid web master plant number, skipping update.")
        else:
            _LOGGER.debug("***** web_update_total(self) ********")
            for key in self._WEB_REQUEST_KEYS:
                a_url = self._WEB_GET_STATUS % (key, str(self._web_master_plant_number))
                async with self.web_session.get(a_url, headers=self._default_web_headers, ssl=False) as res:
                    _LOGGER.debug(f"web_update_total() requesting: {a_url}")
                    try:
                        res.raise_for_status()
                        if res.status in [200, 201, 202, 204, 205]:
                            try:
                                r_json = await res.json()
                                _LOGGER.debug(f"web_update_total() response-recaived: {r_json}")
                                if "fullkwh" in r_json:
                                    value = r_json["fullkwh"]
                                    entity_name = str(key + "_total")
                                    self._web_energy_entities[entity_name] = value
                                else:
                                    _LOGGER.info(f"web_update_total(): No 'fullkwh' in json: {r_json} when requesting: {a_url}")
                            except JSONDecodeError as exc:
                                _LOGGER.warning(f"web_update_total(): JSONDecodeError while 'await res.json()' {exc}")

                        else:
                            _LOGGER.info(f"web_update_total(): while requesting data from {a_url}: {res.status} - {res}")
                            self._web_is_authenticated = False

                    except ClientResponseError as exc:
                        _LOGGER.info(f"web_update_total(): while requesting data from {a_url}: {type(exc).__name__} - {exc}")
                        if exc.status == 401:
                            self.purge_senec_cookies()
                        if exc.status != 408:
                            self._web_is_authenticated = False

            # ok - store the last successful query timestamp
            self._QUERY_TOTALS_TS = time()

    """This function will update peak shaving information"""
    async def web_update_peak_shaving(self):
        if self.web_totp_required:
            _LOGGER.info("***** skipped cause TOTP required - web_update_peak_shaving(self) ********")
            return

        _LOGGER.info("***** web_update_peak_shaving(self) ********")
        a_url = f"{self._WEB_GET_PEAK_SHAVING}{self._web_master_plant_number}"
        async with self.web_session.get(a_url, headers=self._default_web_headers, ssl=False) as res:
            try:
                res.raise_for_status()
                if res.status in [200, 201, 202, 204, 205]:
                    try:
                        r_json = await res.json()
                        # GET Data from JSON
                        self._web_peak_shaving_entities["einspeisebegrenzungKwpInPercent"] = r_json["einspeisebegrenzungKwpInPercent"]
                        self._web_peak_shaving_entities["peakShavingMode"] = r_json["peakShavingMode"].lower()
                        self._web_peak_shaving_entities["peakShavingCapacityLimitInPercent"] = r_json["peakShavingCapacityLimitInPercent"]
                        self._web_peak_shaving_entities["peakShavingEndDate"] = datetime.fromtimestamp(r_json["peakShavingEndDate"] / 1000,
                                                                                                       tz=timezone.utc)  # from miliseconds to seconds
                        self._QUERY_PEAK_SHAVING_TS = time()  # Update timer, that the next update takes place in 24 hours
                    except JSONDecodeError as exc:
                        _LOGGER.warning(f"JSONDecodeError while 'await res.json()' {exc}")
                else:
                    _LOGGER.info(f"web_update_peak_shaving(): while requesting data from {a_url}: {res.status} - {res}")
                    self._web_is_authenticated = False

            except ClientResponseError as exc:
                _LOGGER.info(f"web_update_peak_shaving(): while requesting data from {a_url}: {type(exc).__name__} - {exc}")
                if exc.status == 401:
                    self.purge_senec_cookies()
                if exc.status != 408:
                    self._web_is_authenticated = False

    """This function will set the peak shaving data over the web api"""
    async def set_peak_shaving(self, new_peak_shaving: dict, retry:bool=True):
        _LOGGER.debug("***** set_peak_shaving(self, new_peak_shaving) ********")

        # Senec self allways sends all get-parameter, even if not needed. So we will do it the same way
        a_url = f"{self._WEB_SET_PEAK_SHAVING}{self._web_master_plant_number}&mode={new_peak_shaving['mode'].upper()}&capacityLimit={new_peak_shaving['capacity']}&endzeit={new_peak_shaving['end_time']}"

        async with self.web_session.post(a_url, headers=self._default_web_headers, ssl=False) as res:
            try:
                res.raise_for_status()
                if res.status in [200, 201, 202, 204, 205]:
                    _LOGGER.debug("***** Set Peak Shaving successfully ********")
                    # Reset the timer in order that the Peak Shaving is updated immediately after the change
                    self._QUERY_PEAK_SHAVING_TS = 0

                else:
                    self._web_is_authenticated = False
                    await self.web_authenticate(do_update=False, throw401=False)
                    await self.set_peak_shaving(new_peak_shaving, False)

            except ClientResponseError as exc:
                if exc.status == 401:
                    self.purge_senec_cookies()
                if exc.status != 408:
                    self._web_is_authenticated = False
                    await self.web_authenticate(do_update=False, throw401=True)
                if retry:
                    await self.set_peak_shaving(new_peak_shaving, False)

    """This function will update the spare capacity over the web api"""
    async def web_update_spare_capacity(self):
        if self.web_totp_required:
            _LOGGER.info("***** skipped cause TOTP required - web_update_spare_capacity(self) ********")
            return

        _LOGGER.info("***** web_update_spare_capacity(self) ********")
        a_url = f"{self._WEB_SPARE_CAPACITY_BASE_URL}{self._web_master_plant_number}{self._WEB_GET_SPARE_CAPACITY}"
        async with self.web_session.get(a_url, headers=self._default_web_headers, ssl=False) as res:
            try:
                res.raise_for_status()
                if 200 <= res.status <= 205:
                    content = await res.text()
                    if content is not None and len(content) > 0:
                        try:
                            self._web_spare_capacity = int(content)
                            self._QUERY_SPARE_CAPACITY_TS = time()
                        except ValueError as vexc:
                            _LOGGER.info(f"spare_capacity can't be converted to a number - request to '{a_url}' returned: '{content}' caused {type(vexc).__name__} - {vexc}")
                            self._web_spare_capacity = 0
                    else:
                        _LOGGER.info(f"spare_capacity is not a number - request to '{a_url}' returned: '{content}'")
                        self._web_spare_capacity = 0
                else:
                    _LOGGER.info(f"web_update_spare_capacity(): while requesting data from {a_url}: {res.status} - {res}")
                    self._web_is_authenticated = False

            except ClientResponseError as exc:
                _LOGGER.info(f"web_update_spare_capacity(): while requesting data from {a_url}: {type(exc).__name__} - {exc}")
                if exc.status == 401:
                    self.purge_senec_cookies()
                if exc.status != 408:
                    self._web_is_authenticated = False

    """This function will set the spare capacity over the web api"""
    async def set_spare_capacity(self, new_spare_capacity: int, retry:bool=True):
        _LOGGER.debug("***** set_spare_capacity(self) ********")
        a_url = f"{self._WEB_SPARE_CAPACITY_BASE_URL}{self._web_master_plant_number}{self._WEB_SET_SPARE_CAPACITY}{new_spare_capacity}"

        async with self.web_session.post(a_url, headers=self._default_web_headers, ssl=False) as res:
            try:
                res.raise_for_status()
                if res.status in [200, 201, 202, 204, 205]:
                    _LOGGER.debug("***** Set Spare Capacity successfully ********")
                    # Reset the timer in order that the Spare Capacity is updated immediately after the change
                    self._QUERY_SPARE_CAPACITY_TS = 0
                else:
                    self._web_is_authenticated = False
                    await self.web_authenticate(do_update=False, throw401=False)
                    await self.set_spare_capacity(new_spare_capacity, False)

            except ClientResponseError as exc:
                if exc.status == 401:
                    self.purge_senec_cookies()
                if exc.status != 408:
                    self._web_is_authenticated = False
                    await self.web_authenticate(do_update=False, throw401=True)
                if retry:
                    await self.set_spare_capacity(new_spare_capacity, False)

    async def web_update_sgready_state(self):
        if self.SGREADY_SUPPORTED:
            if self.web_totp_required:
                _LOGGER.info("***** skipped cause TOTP required - web_update_sgready_state(self) ********")
                return

            _LOGGER.info("***** web_update_sgready_state(self) ********")
            a_url = self._WEB_GET_SGREADY_STATE % (str(self._web_master_plant_number))
            async with self.web_session.get(a_url, headers=self._default_web_headers, ssl=False) as res:
                try:
                    res.raise_for_status()
                    if res.status in [200, 201, 202, 204, 205]:
                        try:
                            r_json = await res.json()
                            plain = str(r_json)
                            if len(plain) > 4 and plain[0:4] == "MODE":
                                self._web_sgready_mode_code = int(plain[4:])
                                if self._web_sgready_mode_code > 0:
                                    if self._lang in SGREADY_MODES:
                                        self._web_sgready_mode = SGREADY_MODES[self._lang].get(self._web_sgready_mode_code,"UNKNOWN")
                                    else:
                                        self._web_sgready_mode = SGREADY_MODES["en"].get(self._web_sgready_mode_code, "UNKNOWN")

                                    # ok we have got our data…
                                    _QUERY_SGREADY_STATE_TS = time()

                        except JSONDecodeError as exc:
                            _LOGGER.warning(f"JSONDecodeError while 'await res.json()' {exc}")
                    else:
                        _LOGGER.info(f"web_update_sgready_state(): while requesting data from {a_url}: {res.status} - {res}")
                        self._web_is_authenticated = False

                except ClientResponseError as exc:
                    _LOGGER.info(f"web_update_sgready_state(): while requesting data from {a_url}: {type(exc).__name__} - {exc}")
                    if exc.status == 401:
                        self.purge_senec_cookies()
                    if exc.status != 408:
                        self._web_is_authenticated = False

    async def web_update_sgready_conf(self):
        if self.SGREADY_SUPPORTED:
            if self.web_totp_required:
                _LOGGER.info("***** skipped cause TOTP required - web_update_sgready_conf(self) ********")
                return

            _LOGGER.info("***** web_update_sgready_conf(self) ********")
            a_url = self._WEB_GET_SGREADY_CONF % (str(self._web_master_plant_number))
            async with self.web_session.get(a_url, headers=self._default_web_headers, ssl=False) as res:
                try:
                    res.raise_for_status()
                    if res.status in [200, 201, 202, 204, 205]:
                        try:
                            r_json = await res.json()
                            self._web_sgready_conf_data = r_json
                            self._QUERY_SGREADY_CONF_TS = time()

                        except JSONDecodeError as exc:
                            _LOGGER.warning(f"JSONDecodeError while 'await res.json()' {exc}")
                    else:
                        _LOGGER.info(f"web_update_sgready_conf(): while requesting data from {a_url}: {res.status} - {res}")
                        self._web_is_authenticated = False

                except ClientResponseError as exc:
                    _LOGGER.info(f"web_update_sgready_conf(): while requesting data from {a_url}: {type(exc).__name__} - {exc}")
                    if exc.status == 401:
                        self.purge_senec_cookies()
                    if exc.status != 408:
                        self._web_is_authenticated = False

    async def set_sgready_conf(self, new_sgready_data: dict, retry:bool=True):
        if self.SGREADY_SUPPORTED:
            _LOGGER.debug(f"***** set_sgready_conf(self, new_sgready_data {new_sgready_data}) ********")

            a_url = self._WEB_SET_SGREADY_CONF % (str(self._web_master_plant_number))

            post_data_to_backend = False
            post_data = {}
            for a_key in SGREADY_CONF_KEYS:
                if a_key in self._web_sgready_conf_data:
                    if a_key in new_sgready_data:
                        if self._web_sgready_conf_data[a_key] != new_sgready_data[a_key]:
                            post_data[a_key] = new_sgready_data[a_key]
                            post_data_to_backend = True
                    else:
                        post_data[a_key] = self._web_sgready_conf_data[a_key]

            if len(post_data) > 0 and post_data_to_backend:
                async with self.web_session.post(a_url, headers=self._default_web_headers, ssl=False, json=post_data) as res:
                    try:
                        res.raise_for_status()
                        if res.status in [200, 201, 202, 204, 205]:
                            _LOGGER.debug("***** Set SG-Ready CONF successfully ********")
                            # Reset the timer in order that the SGReady state is updated immediately after the change
                            self._QUERY_SGREADY_STATE_TS = 0
                            self._QUERY_SGREADY_CONF_TS = 0

                        else:
                            self._web_is_authenticated = False
                            await self.web_authenticate(do_update=False, throw401=False)
                            await self.set_sgready_conf(new_sgready_data, False)

                    except ClientResponseError as exc:
                        if exc.status == 401:
                            self.purge_senec_cookies()
                        if exc.status != 408:
                            self._web_is_authenticated = False
                            await self.web_authenticate(do_update=False, throw401=True)
                        if retry:
                            await self.set_sgready_conf(new_sgready_data, False)
            else:
                _LOGGER.debug(
                    f"no valid or new SGReady post data found in {new_sgready_data} current config: {self._web_sgready_conf_data}")

    ###################################
    # JUST VALUE FUNCTIONS
    ###################################
    @property
    def spare_capacity(self) -> int:
        if hasattr(self, '_web_spare_capacity'):
            return int(self._web_spare_capacity)

    @property
    def senec_num(self) -> str:
        if self._app_raw_system_details is not None and "casing" in self._app_raw_system_details:
            return self._app_raw_system_details["casing"]["serial"]
        elif hasattr(self, '_web_dev_number'):
            return str(self._web_dev_number)
        else:
            return "UNKNOWN_SENEC_NUM"

    @property
    def serial_number(self) -> str:
        if self._app_raw_system_details is not None and "mcu" in self._app_raw_system_details:
            return self._app_raw_system_details["mcu"]["mainControllerSerial"]
        elif hasattr(self, '_app_serial_number') and self._app_serial_number is not None:
            return str(self._app_serial_number)
        elif hasattr(self, '_web_serial_number'):
            return str(self._web_serial_number)
        else:
            return "UNKNOWN_SERIAL"

    @property
    def product_name(self) -> str:
        if self._app_raw_system_details is not None and "systemOverview" in self._app_raw_system_details:
            return self._app_raw_system_details["systemOverview"]["productName"]
        elif hasattr(self, '_web_product_name'):
            return str(self._web_product_name)
        else:
            return "UNKNOWN_PROD_NAME"

    @property
    def zone_id(self) -> str:
        if hasattr(self, '_web_zone_id'):
            return str(self._web_zone_id)

    @property
    def versions(self) -> str:
        a = None
        b = None
        c = None
        d = None
        e = None
        f = None
        if self._app_raw_system_details is not None and "mcu" in self._app_raw_system_details:
            a = self._app_raw_system_details["mcu"]["guiVersion"]
            b = self._app_raw_system_details["mcu"]["firmwareVersion"]

        if self._app_raw_system_details is not None and "batteryInverter" in self._app_raw_system_details:
            bat_inv_obj = self._app_raw_system_details["batteryInverter"]
            if "firmware" in bat_inv_obj:
                c = bat_inv_obj["firmware"]["firmwareVersion"]
                d = bat_inv_obj["firmware"]["firmwareVersionHumanMachineInterface"]
                e = bat_inv_obj["firmware"]["firmwareVersionPowerUnit"]
                f = bat_inv_obj["firmware"]["firmwareVersionBidirectionalDcConverter"]
        # _LOGGER.error(f"VERSION INFO **************** {a} {b} {c} {d} {e} {f} ")
        if a is not None and b is not None:
            if c is not None:
                return f"App:{a} FW:{b} Inverter: v{c}"
            elif d is not None:
                return f"App:{a} FW:{b} Inverter: v{d}"
            elif e is not None:
                return f"App:{a} FW:{b} Inverter: v{e}"
            elif f is not None:
                return f"App:{a} FW:{b} Inverter: v{f}"
        else:
            return None

    @property
    def appMasterPlantNumber(self) -> int:
        if hasattr(self, '_app_master_plant_number') and self._app_master_plant_number is not None:
            return int(self._app_master_plant_number)
        elif hasattr(self, '_web_master_plant_number') and self._web_master_plant_number is not None:
            return int(self._web_master_plant_number)


    ###################################
    # from here the "real" sensor data starts… #
    ###################################
    def _get_sum_for_index(self, index: int) -> float:
        if index > -1:
            return sum(entry["measurements"]["values"][index] for entry in self._app_raw_total["timeSeries"])

    def _get_sum_for_index_wb(self, index: int, a_dict) -> float:
        if index > -1:
            return sum(entry["measurements"]["values"][index] for entry in a_dict["timeseries"])

    @property
    def request_throttling(self) -> str:
        return self._UPDATE_INTERVAL

    async def set_string_value_request_throttling(self, value: str):
        if value in UPDATE_INTERVAL_OPTIONS:
            self._UPDATE_INTERVAL = value

    @property
    def accuimport_total(self) -> float:
        if self._app_raw_total is not None:
            # yes this sounds strange 'BATTERY_IMPORT' (but finally SENEC have inverted it's logic) - but we must keep
            # the inverted stuff here!
            return self._get_sum_for_index(self._app_raw_total["measurements"].index("BATTERY_EXPORT"))
        elif hasattr(self, '_web_energy_entities') and "accuimport_total" in self._web_energy_entities:
            return self._web_energy_entities["accuimport_total"]

    @property
    def accuexport_total(self) -> float:
        if self._app_raw_total is not None:
            # yes this sounds strange 'BATTERY_IMPORT' (but finally SENEC have inverted it's logic) - but we must keep
            # the inverted stuff here!
            return self._get_sum_for_index(self._app_raw_total["measurements"].index("BATTERY_IMPORT"))
        elif hasattr(self, '_web_energy_entities') and "accuexport_total" in self._web_energy_entities:
            return self._web_energy_entities["accuexport_total"]

    @property
    def gridimport_total(self) -> float:
        if self._app_raw_total is not None:
            return self._get_sum_for_index(self._app_raw_total["measurements"].index("GRID_IMPORT"))
        elif hasattr(self, '_web_energy_entities') and "gridimport_total" in self._web_energy_entities:
            return self._web_energy_entities["gridimport_total"]

    @property
    def gridexport_total(self) -> float:
        if self._app_raw_total is not None:
            return self._get_sum_for_index(self._app_raw_total["measurements"].index("GRID_EXPORT"))
        elif hasattr(self, '_web_energy_entities') and "gridexport_total" in self._web_energy_entities:
            return self._web_energy_entities["gridexport_total"]

    @property
    def powergenerated_total(self) -> float:
        if self._app_raw_total is not None:
            return self._get_sum_for_index(self._app_raw_total["measurements"].index("POWER_GENERATION"))
        elif hasattr(self, '_web_energy_entities') and "powergenerated_total" in self._web_energy_entities:
            return self._web_energy_entities["powergenerated_total"]

    @property
    def consumption_total(self) -> float:
        if self._app_raw_total is not None:
            return self._get_sum_for_index(self._app_raw_total["measurements"].index("POWER_CONSUMPTION"))
        elif hasattr(self, '_web_energy_entities') and "consumption_total" in self._web_energy_entities:
            return self._web_energy_entities["consumption_total"]

    @property
    def wallbox_1_consumption_total(self) -> float:
        if self._app_raw_wb_total is not None:
            if len(self._app_raw_wb_total) > 0:
                a_wallbox_measure = self._app_raw_wb_total[0]
                if a_wallbox_measure is not None and "measurements" in a_wallbox_measure:
                    return self._get_sum_for_index_wb(a_wallbox_measure["measurements"].index("WALLBOX_CONSUMPTION"), a_wallbox_measure)
        return None

    @property
    def wallbox_2_consumption_total(self) -> float:
        if self._app_raw_wb_total is not None:
            if len(self._app_raw_wb_total) > 1:
                a_wallbox_measure = self._app_raw_wb_total[1]
                if a_wallbox_measure is not None and "measurements" in a_wallbox_measure:
                    return self._get_sum_for_index_wb(a_wallbox_measure["measurements"].index("WALLBOX_CONSUMPTION"), a_wallbox_measure)
        return None

    @property
    def wallbox_3_consumption_total(self) -> float:
        if self._app_raw_wb_total is not None:
            if len(self._app_raw_wb_total) > 2:
                a_wallbox_measure = self._app_raw_wb_total[2]
                if a_wallbox_measure is not None and "measurements" in a_wallbox_measure:
                    return self._get_sum_for_index_wb(a_wallbox_measure["measurements"].index("WALLBOX_CONSUMPTION"), a_wallbox_measure)
        return None

    @property
    def wallbox_4_consumption_total(self) -> float:
        if self._app_raw_wb_total is not None:
            if len(self._app_raw_wb_total) > 3:
                a_wallbox_measure = self._app_raw_wb_total[3]
                if a_wallbox_measure is not None and "measurements" in a_wallbox_measure:
                    return self._get_sum_for_index_wb(a_wallbox_measure["measurements"].index("WALLBOX_CONSUMPTION"), a_wallbox_measure)
        return None

    @property
    def wallbox_consumption_total(self) -> float:
        if self._app_raw_wb_total is not None:
            sum = 0
            for idx in range(0, self._app_wallbox_num_max):
                if len(self._app_raw_wb_total) > idx:
                    a_wallbox_measure = self._app_raw_wb_total[idx]
                    if a_wallbox_measure is not None and "measurements" in a_wallbox_measure:
                        sum = sum + self._get_sum_for_index_wb(a_wallbox_measure["measurements"].index("WALLBOX_CONSUMPTION"), a_wallbox_measure)
            if sum > 0:
                return sum
        return None

    @property
    def accuimport_today(self) -> float:
        if self._app_raw_today is not None and "batteryDischargeInWh" in self._app_raw_today:
            return float(self._app_raw_today["batteryDischargeInWh"]) / 1000
        if hasattr(self, '_web_energy_entities') and "accuimport_today" in self._web_energy_entities:
            return self._web_energy_entities["accuimport_today"]

    @property
    def accuexport_today(self) -> float:
        if self._app_raw_today is not None and "batteryChargeInWh" in self._app_raw_today:
            return float(self._app_raw_today["batteryChargeInWh"]) / 1000
        elif hasattr(self, '_web_energy_entities') and "accuexport_today" in self._web_energy_entities:
            return self._web_energy_entities["accuexport_today"]

    @property
    def gridimport_today(self) -> float:
        if self._app_raw_today is not None and "gridDrawInWh" in self._app_raw_today:
            return float(self._app_raw_today["gridDrawInWh"]) / 1000
        elif hasattr(self, '_web_energy_entities') and "gridimport_today" in self._web_energy_entities:
            return self._web_energy_entities["gridimport_today"]

    @property
    def gridexport_today(self) -> float:
        if self._app_raw_today is not None and "gridFeedInInWh" in self._app_raw_today:
            return float(self._app_raw_today["gridFeedInInWh"]) / 1000
        elif hasattr(self, '_energy_entities') and "gridexport_today" in self._web_energy_entities:
            return self._web_energy_entities["gridexport_today"]

    @property
    def powergenerated_today(self) -> float:
        if self._app_raw_today is not None and "powerGenerationInWh" in self._app_raw_today:
            return float(self._app_raw_today["powerGenerationInWh"]) / 1000
        elif hasattr(self, '_web_energy_entities') and "powergenerated_today" in self._web_energy_entities:
            return self._web_energy_entities["powergenerated_today"]

    @property
    def consumption_today(self) -> float:
        if self._app_raw_today is not None and "powerConsumptionInWh" in self._app_raw_today:
            return float(self._app_raw_today["powerConsumptionInWh"]) / 1000
        elif hasattr(self, '_web_energy_entities') and "consumption_today" in self._web_energy_entities:
            return self._web_energy_entities["consumption_today"]

    @property
    def accuimport_now(self) -> float:
        if self._app_raw_now is not None and "batteryDischargeInW" in self._app_raw_now:
            return float(self._app_raw_now["batteryDischargeInW"]) / 1000
        elif hasattr(self, "_web_power_entities") and "accuimport_now" in self._web_power_entities:
            return self._web_power_entities["accuimport_now"]

    @property
    def accuexport_now(self) -> float:
        if self._app_raw_now is not None and "batteryChargeInW" in self._app_raw_now:
            return float(self._app_raw_now["batteryChargeInW"]) / 1000
        elif hasattr(self, "_web_power_entities") and "accuexport_now" in self._web_power_entities:
            return self._web_power_entities["accuexport_now"]

    @property
    def gridimport_now(self) -> float:
        if self._app_raw_now is not None and "gridDrawInW" in self._app_raw_now:
            return float(self._app_raw_now["gridDrawInW"]) / 1000
        if hasattr(self, "_web_power_entities") and "gridimport_now" in self._web_power_entities:
            return self._web_power_entities["gridimport_now"]

    @property
    def gridexport_now(self) -> float:
        if self._app_raw_now is not None and "gridFeedInInW" in self._app_raw_now:
            return float(self._app_raw_now["gridFeedInInW"]) / 1000
        elif hasattr(self, "_web_power_entities") and "gridexport_now" in self._web_power_entities:
            return self._web_power_entities["gridexport_now"]

    @property
    def powergenerated_now(self) -> float:
        if self._app_raw_now is not None and "powerGenerationInW" in self._app_raw_now:
            return float(self._app_raw_now["powerGenerationInW"]) / 1000
        elif hasattr(self, "_web_power_entities") and "powergenerated_now" in self._web_power_entities:
            return self._web_power_entities["powergenerated_now"]

    @property
    def consumption_now(self) -> float:
        if self._app_raw_now is not None and "powerConsumptionInW" in self._app_raw_now:
            return float(self._app_raw_now["powerConsumptionInW"]) / 1000
        elif hasattr(self, "_web_power_entities") and "consumption_now" in self._web_power_entities:
            return self._web_power_entities["consumption_now"]

    @property
    def acculevel_now(self) -> int:
        if self._app_raw_now is not None and "batteryLevelInPercent" in self._app_raw_now:
            return float(self._app_raw_now["batteryLevelInPercent"])
        elif hasattr(self, "_web_battery_entities") and "acculevel_now" in self._web_battery_entities:
            return self._web_battery_entities["acculevel_now"]

    @property
    def gridexport_limit(self) -> int:
        if hasattr(self, "_web_peak_shaving_entities") and "einspeisebegrenzungKwpInPercent" in self._web_peak_shaving_entities:
            return self._web_peak_shaving_entities["einspeisebegrenzungKwpInPercent"]

    @property
    def peakshaving_mode(self) -> int:
        if hasattr(self, "_web_peak_shaving_entities") and "peakShavingMode" in self._web_peak_shaving_entities:
            return self._web_peak_shaving_entities["peakShavingMode"]

    @property
    def peakshaving_capacitylimit(self) -> int:
        if hasattr(self, "_web_peak_shaving_entities") and "peakShavingCapacityLimitInPercent" in self._web_peak_shaving_entities:
            return self._web_peak_shaving_entities["peakShavingCapacityLimitInPercent"]

    @property
    def peakshaving_enddate(self) -> int:
        if hasattr(self, "_web_peak_shaving_entities") and "peakShavingEndDate" in self._web_peak_shaving_entities:
            return self._web_peak_shaving_entities["peakShavingEndDate"]

    ###################################
    # NEW APP-API SENSOR VALUES #
    ###################################
    @property
    def case_temp(self) -> float:
        # 'casing': {'serial': 'XXX', 'temperatureInCelsius': 28.95928382873535},
        if self._app_raw_system_details is not None and "casing" in self._app_raw_system_details:
            return self._app_raw_system_details["casing"]["temperatureInCelsius"]

    @property
    def system_state(self) -> str:
        # some sort of hack - when we set the '_app_raw_system_details', then we going to set
        # the '_app_raw_system_state_obj' to None ;-)
        state = self.system_state_from_state
        if state is not None:
            return state
        else:
            return self.system_state_from_details

    @property
    def system_state_from_state(self) -> str:
        if self._app_raw_system_state_obj is not None and "name" in self._app_raw_system_state_obj:
            return self._app_raw_system_state_obj["name"].replace('_', ' ')

    @property
    def system_state_from_details(self) -> str:
        # 'mcu': {'mainControllerSerial': 'XXX',
        #        'mainControllerState': {'name': 'EIGENVERBRAUCH', 'severity': 'INFO'}, 'firmwareVersion': '123',
        #        'guiVersion': 123}, 'warranty': {'endDate': 1700000000, 'warrantyTermInMonths': 123},
        if self._app_raw_system_details is not None and "mcu" in self._app_raw_system_details:
            if "mainControllerUnitState" in self._app_raw_system_details["mcu"]:
                return self._app_raw_system_details["mcu"]["mainControllerUnitState"]["name"].replace('_', ' ')
            # old response might contained 'mainControllerState'
            elif "mainControllerState" in self._app_raw_system_details["mcu"]:
                return self._app_raw_system_details["mcu"]["mainControllerState"]["name"].replace('_', ' ')

    @property
    def battery_state(self) -> str:
        if self._app_raw_battery_device_state is not None:
            return self._app_raw_battery_device_state.replace('_', ' ')

    ###################################
    # 'batteryInverter': {'state': {'name': 'RUN_GRID', 'severity': 'INFO'}, 'vendor': 'XXX',
    #                     'firmware': {'firmwareVersion': None,
    #                                  'firmwareVersionHumanMachineInterface': '0.01',
    #                                  'firmwareVersionPowerUnit': '0.01',
    #                                  'firmwareVersionBidirectionalDcConverter': '0.01'},
    #                     'temperatures': {'amb': 36.0, 'halfBridge1': None, 'halfBridge2': None,
    #                                     'throttle': None, 'max': 41.0},
    #                     'lastContact': {'time': 1700000000, 'severity': 'INFO'}, 'flags': []},
    ###################################
    @property
    def battery_inverter_state(self) -> str:
        if self._app_raw_system_details is not None:
            if "batteryInverter" in self._app_raw_system_details:
                bat_inv_obj = self._app_raw_system_details["batteryInverter"]
                if "state" in bat_inv_obj and "name" in bat_inv_obj["state"] and bat_inv_obj["state"][
                    "name"] is not None:
                    return bat_inv_obj["state"]["name"].replace('_', ' ')

            # just a fallback…
            if "mcu" in self._app_raw_system_details:
                mcu_obj = self._app_raw_system_details["mcu"]
                if "mainControllerState" in mcu_obj and "name" in mcu_obj["mainControllerState"] and mcu_obj["mainControllerState"]["name"] is not None:
                    return mcu_obj["mainControllerState"]["name"].replace('_', ' ')

    @property
    def battery_temp(self) -> float:
        if self._app_raw_system_details is not None:
            if "batteryInverter" in self._app_raw_system_details:
                bat_inv_obj = self._app_raw_system_details["batteryInverter"]
                if "temperatures" in bat_inv_obj and "amb" in bat_inv_obj["temperatures"] and bat_inv_obj["temperatures"]["amb"] is not None:
                    return bat_inv_obj["temperatures"]["amb"]

            # just a fallback…
            # if "casing" in self._app_raw_tech_data:
            #    casing_obj = self._app_raw_tech_data["casing"]
            #    if "temperatureInCelsius" in casing_obj and casing_obj["temperatureInCelsius"] is not None:
            #        return casing_obj["temperatureInCelsius"]

    @property
    def battery_temp_max(self) -> float:
        if self._app_raw_system_details is not None:
            if "batteryInverter" in self._app_raw_system_details:
                bat_inv_obj = self._app_raw_system_details["batteryInverter"]
                if "temperatures" in bat_inv_obj and "max" in bat_inv_obj["temperatures"] and bat_inv_obj["temperatures"]["max"] is not None:
                    return bat_inv_obj["temperatures"]["max"]

            # just a fallback…
            # if "batteryModules" in self._app_raw_tech_data:
            #    bat_modules_obj = self._app_raw_tech_data["batteryModules"]
            #    count = 0
            #    temp_sum = 0
            #    for a_mod in bat_modules_obj:
            #        if "maxTemperature" in a_mod:
            #            temp_sum = temp_sum + a_mod["maxTemperature"]
            #            count = count + 1
            #    return temp_sum/count

    ###################################
    # 'batteryPack': {'numberOfBatteryModules': 4, 'technology': 'XXX', 'maxCapacityInKwh': 10.0,
    #                 'maxChargingPowerInKw': 2.5, 'maxDischargingPowerInKw': 3.75,
    #                 'currentChargingLevelInPercent': 4.040403842926025,
    #                 'currentVoltageInV': 46.26100158691406, 'currentCurrentInA': -0.10999999940395355,
    #                 'remainingCapacityInPercent': 99.9},
    ###################################
    @property
    def _battery_module_count(self) -> int:
        # internal use only…
        if self._app_raw_system_details is not None and "batteryPack" in self._app_raw_system_details:
            if "numberOfBatteryModules" in self._app_raw_system_details["batteryPack"]:
                return self._app_raw_system_details["batteryPack"]["numberOfBatteryModules"]
        return 0

    @property
    def battery_state_voltage(self) -> float:
        if self._app_raw_system_details is not None and "batteryPack" in self._app_raw_system_details:
            if "currentVoltageInV" in self._app_raw_system_details["batteryPack"]:
                return self._app_raw_system_details["batteryPack"]["currentVoltageInV"]

    @property
    def battery_state_current(self) -> float:
        if self._app_raw_system_details is not None and "batteryPack" in self._app_raw_system_details:
            if "currentCurrentInA" in self._app_raw_system_details["batteryPack"]:
                return self._app_raw_system_details["batteryPack"]["currentCurrentInA"]

    @property
    def _not_used_currentChargingLevelInPercent(self) -> float:
        if self._app_raw_system_details is not None and "batteryPack" in self._app_raw_system_details:
            if "currentChargingLevelInPercent" in self._app_raw_system_details["batteryPack"]:
                return self._app_raw_system_details["batteryPack"]["currentChargingLevelInPercent"]

    @property
    def battery_soh_remaining_capacity(self) -> float:
        if self._app_raw_system_details is not None and "batteryPack" in self._app_raw_system_details:
            if "remainingCapacityInPercent" in self._app_raw_system_details["batteryPack"]:
                return self._app_raw_system_details["batteryPack"]["remainingCapacityInPercent"]

    ###################################
    # 'batteryModules': [{'ordinal': 1, 'state': {'state': 'OK', 'severity': 'INFO'}, 'vendor': 'XXX',
    #                     'serialNumber': '1231', 'firmwareVersion': '0.01',
    #                     'mainboardHardwareVersion': '0001', 'mainboardExtensionHardwareVersion': '0',
    #                     'minTemperature': 24.0, 'maxTemperature': 26.0,
    #                     'lastContact': {'time': 1700000000, 'severity': 'INFO'}, 'flags': []},
    #
    #                    {'ordinal': 2, 'state': {'state': 'OK', 'severity': 'INFO'}, 'vendor': 'XXX',
    #                     'serialNumber': '1232', 'firmwareVersion': '0.01',
    #                     'mainboardHardwareVersion': '0001', 'mainboardExtensionHardwareVersion': '0',
    #                     'minTemperature': 24.0, 'maxTemperature': 27.0,
    #                     'lastContact': {'time': 1700000000, 'severity': 'INFO'}, 'flags': []},
    #
    #                    {'ordinal': 3, 'state': {'state': 'OK', 'severity': 'INFO'}, 'vendor': 'XXX',
    #                     'serialNumber': '1233', 'firmwareVersion': '0.01',
    #                     'mainboardHardwareVersion': '0001', 'mainboardExtensionHardwareVersion': '0',
    #                     'minTemperature': 26.0, 'maxTemperature': 28.0,
    #                     'lastContact': {'time': 1700000000, 'severity': 'INFO'}, 'flags': []},
    #
    #                    {'ordinal': 4, 'state': {'state': 'OK', 'severity': 'INFO'}, 'vendor': 'XXX',
    #                     'serialNumber': '1234', 'firmwareVersion': '0.01',
    #                     'mainboardHardwareVersion': '0001', 'mainboardExtensionHardwareVersion': '0',
    #                     'minTemperature': 27.0, 'maxTemperature': 28.0,
    #                     'lastContact': {'time': 1700000000, 'severity': 'INFO'}, 'flags': []}],
    ###################################
    @property
    def battery_module_state(self) -> [str]:
        if self._app_raw_system_details is not None and "batteryModules" in self._app_raw_system_details:
            data = ["UNKNOWN"] * self._battery_module_count
            bat_obj = self._app_raw_system_details["batteryModules"]
            for idx in range(self._battery_module_count):
                data[idx] = bat_obj[idx]["state"]["state"].replace('_', ' ')
            return data

    @property
    def battery_module_temperature_avg(self) -> [float]:
        if self._app_raw_system_details is not None and "batteryModules" in self._app_raw_system_details:
            data = [None] * self._battery_module_count
            bat_obj = self._app_raw_system_details["batteryModules"]
            for idx in range(self._battery_module_count):
                if "minTemperature" in bat_obj[idx] and "maxTemperature" in bat_obj[idx]:
                    data[idx] = (bat_obj[idx]["minTemperature"] + bat_obj[idx]["maxTemperature"]) / 2
            return data

    @property
    def battery_module_temperature_min(self) -> [float]:
        if self._app_raw_system_details is not None and "batteryModules" in self._app_raw_system_details:
            data = [None] * self._battery_module_count
            bat_obj = self._app_raw_system_details["batteryModules"]
            for idx in range(self._battery_module_count):
                if "minTemperature" in bat_obj[idx]:
                    data[idx] = bat_obj[idx]["minTemperature"]
            return data

    @property
    def battery_module_temperature_max(self) -> [float]:
        if self._app_raw_system_details is not None and "batteryModules" in self._app_raw_system_details:
            data = [None] * self._battery_module_count
            bat_obj = self._app_raw_system_details["batteryModules"]
            for idx in range(self._battery_module_count):
                if "maxTemperature" in bat_obj[idx]:
                    data[idx] = bat_obj[idx]["maxTemperature"]
            return data

    @property
    def sgready_mode_code(self) -> int:
        if self.SGREADY_SUPPORTED and self._web_sgready_mode_code > 0:
            return self._web_sgready_mode_code

    @property
    def sgready_mode(self) -> str:
        if self.SGREADY_SUPPORTED and self._web_sgready_mode is not None:
            return self._web_sgready_mode

    @property
    def sgready_enabled(self) -> bool:
        if self.SGREADY_SUPPORTED and len(self._web_sgready_conf_data) > 0 and SGREADY_CONFKEY_ENABLED in self._web_sgready_conf_data:
            return self._web_sgready_conf_data[SGREADY_CONFKEY_ENABLED]

    async def switch_sgready_enabled(self, enabled: bool) -> bool:
        if self.SGREADY_SUPPORTED:
            await self.set_sgready_conf(new_sgready_data={SGREADY_CONFKEY_ENABLED: enabled})

    ##########################
    # WEB/API WALLBOX ENTITIES
    ##########################

    ## WALLBOX: 1
    @property
    def wallbox_1_temperature(self) -> str:
        a_wallbox_obj = self._app_get_wallbox_object_at_index(0)
        return a_wallbox_obj.get("state", {}).get("temperatureInCelsius", None)

    @property
    def wallbox_1_state(self) -> str:
        a_wallbox_obj = self._app_get_wallbox_object_at_index(0)
        return a_wallbox_obj.get("state", {}).get("statusCode", None)

    @property
    def wallbox_1_ev_connected(self) -> bool:
        a_wallbox_obj = self._app_get_wallbox_object_at_index(0)
        return a_wallbox_obj.get("state", {}).get("electricVehicleConnected", None)

    @property
    def wallbox_1_ev_charging(self) -> bool:
        a_wallbox_obj = self._app_get_wallbox_object_at_index(0)
        return a_wallbox_obj.get("state", {}).get("isCharging", None)

    @property
    def wallbox_1_ev_errors(self) -> bool:
        a_wallbox_obj = self._app_get_wallbox_object_at_index(0)
        return a_wallbox_obj.get("state", {}).get("hasError", None)

    @property
    def wallbox_1_mode(self) -> float:
        return self._app_get_local_wallbox_mode_from_api_values(idx=0)

    async def set_string_value_wallbox_1_mode(self, value: str) -> bool:
        return await self.app_set_wallbox_mode(local_mode_to_set=value, wallbox_num=1, sync=True)

    @property
    def wallbox_1_set_icmax(self) -> float:
        a_wallbox_obj = self._app_get_wallbox_object_at_index(0)
        return a_wallbox_obj.get("chargingMode", {}).get("solarOptimizeSettings", {}).get("minChargingCurrentInA", None)

    async def set_nv_wallbox_1_set_icmax(self, value: float) -> bool:
        return await self.app_set_wallbox_icmax(value_to_set=value, wallbox_num=1, sync=True)


    ## WALLBOX: 2
    @property
    def wallbox_2_temperature(self) -> str:
        a_wallbox_obj = self._app_get_wallbox_object_at_index(1)
        return a_wallbox_obj.get("state", {}).get("temperatureInCelsius", None)

    @property
    def wallbox_2_state(self) -> str:
        a_wallbox_obj = self._app_get_wallbox_object_at_index(1)
        return a_wallbox_obj.get("state", {}).get("statusCode", None)

    @property
    def wallbox_2_ev_connected(self) -> bool:
        a_wallbox_obj = self._app_get_wallbox_object_at_index(1)
        return a_wallbox_obj.get("state", {}).get("electricVehicleConnected", None)

    @property
    def wallbox_2_ev_charging(self) -> bool:
        a_wallbox_obj = self._app_get_wallbox_object_at_index(1)
        return a_wallbox_obj.get("state", {}).get("isCharging", None)

    @property
    def wallbox_2_ev_errors(self) -> bool:
        a_wallbox_obj = self._app_get_wallbox_object_at_index(1)
        return a_wallbox_obj.get("state", {}).get("hasError", None)

    @property
    def wallbox_2_mode(self) -> float:
        return self._app_get_local_wallbox_mode_from_api_values(idx=1)

    async def set_string_value_wallbox_2_mode(self, value: str) -> bool:
        return await self.app_set_wallbox_mode(local_mode_to_set=value, wallbox_num=2, sync=True)

    @property
    def wallbox_2_set_icmax(self) -> float:
        a_wallbox_obj = self._app_get_wallbox_object_at_index(1)
        return a_wallbox_obj.get("chargingMode", {}).get("solarOptimizeSettings", {}).get("minChargingCurrentInA", None)

    async def set_nv_wallbox_2_set_icmax(self, value: float) -> bool:
        return await self.app_set_wallbox_icmax(value_to_set=value, wallbox_num=2, sync=True)


    ## WALLBOX: 3
    @property
    def wallbox_3_temperature(self) -> str:
        a_wallbox_obj = self._app_get_wallbox_object_at_index(2)
        return a_wallbox_obj.get("state", {}).get("temperatureInCelsius", None)

    @property
    def wallbox_3_state(self) -> str:
        a_wallbox_obj = self._app_get_wallbox_object_at_index(2)
        return a_wallbox_obj.get("state", {}).get("statusCode", None)

    @property
    def wallbox_3_ev_connected(self) -> bool:
        a_wallbox_obj = self._app_get_wallbox_object_at_index(2)
        return a_wallbox_obj.get("state", {}).get("electricVehicleConnected", None)

    @property
    def wallbox_3_ev_charging(self) -> bool:
        a_wallbox_obj = self._app_get_wallbox_object_at_index(2)
        return a_wallbox_obj.get("state", {}).get("isCharging", None)

    @property
    def wallbox_3_ev_errors(self) -> bool:
        a_wallbox_obj = self._app_get_wallbox_object_at_index(2)
        return a_wallbox_obj.get("state", {}).get("hasError", None)

    @property
    def wallbox_3_mode(self) -> float:
        return self._app_get_local_wallbox_mode_from_api_values(idx=2)

    async def set_string_value_wallbox_3_mode(self, value: str) -> bool:
        return await self.app_set_wallbox_mode(local_mode_to_set=value, wallbox_num=3, sync=True)

    @property
    def wallbox_3_set_icmax(self) -> float:
        a_wallbox_obj = self._app_get_wallbox_object_at_index(2)
        return a_wallbox_obj.get("chargingMode", {}).get("solarOptimizeSettings", {}).get("minChargingCurrentInA", None)

    async def set_nv_wallbox_3_set_icmax(self, value: float) -> bool:
        return await self.app_set_wallbox_icmax(value_to_set=value, wallbox_num=3, sync=True)


    ## WALLBOX: 4
    @property
    def wallbox_4_temperature(self) -> str:
        a_wallbox_obj = self._app_get_wallbox_object_at_index(3)
        return a_wallbox_obj.get("state", {}).get("temperatureInCelsius", None)

    @property
    def wallbox_4_state(self) -> str:
        a_wallbox_obj = self._app_get_wallbox_object_at_index(3)
        return a_wallbox_obj.get("state", {}).get("statusCode", None)

    @property
    def wallbox_4_ev_connected(self) -> bool:
        a_wallbox_obj = self._app_get_wallbox_object_at_index(3)
        return a_wallbox_obj.get("state", {}).get("electricVehicleConnected", None)

    @property
    def wallbox_4_ev_charging(self) -> bool:
        a_wallbox_obj = self._app_get_wallbox_object_at_index(3)
        return a_wallbox_obj.get("state", {}).get("isCharging", None)

    @property
    def wallbox_4_ev_errors(self) -> bool:
        a_wallbox_obj = self._app_get_wallbox_object_at_index(3)
        return a_wallbox_obj.get("state", {}).get("hasError", None)

    @property
    def wallbox_4_mode(self) -> float:
        return self._app_get_local_wallbox_mode_from_api_values(idx=3)

    async def set_string_value_wallbox_4_mode(self, value: str) -> bool:
        return await self.app_set_wallbox_mode(local_mode_to_set=value, wallbox_num=4, sync=True)

    @property
    def wallbox_4_set_icmax(self) -> float:
        a_wallbox_obj = self._app_get_wallbox_object_at_index(3)
        return a_wallbox_obj.get("chargingMode", {}).get("solarOptimizeSettings", {}).get("minChargingCurrentInA", None)

    async def set_nv_wallbox_4_set_icmax(self, value: float) -> bool:
        return await self.app_set_wallbox_icmax(value_to_set=value, wallbox_num=4, sync=True)


    ########################################################
    # for wallbox_allow_intercharge we just have ONE FOR ALL
    ########################################################
    @property
    def wallbox_allow_intercharge(self) -> bool:
        # for backward compatibility we can only switch all wallboxes at once..
        a_wallbox_obj = self._app_get_wallbox_object_at_index(0)
        return a_wallbox_obj.get("chargingMode", {}).get("allowIntercharge", False)

    async def switch_wallbox_allow_intercharge(self, enabled: bool) -> bool:
        # for backward compatibility we can only switch all wallboxes at once..
        await self.app_set_allow_intercharge_all(value_to_set=enabled, sync=True)
        return True


    ###################################
    # SWITCH-STUFF
    ###################################
    async def switch(self, switch_key, value):
        return await getattr(self, 'switch_' + str(switch_key))(value)

    ###################################
    # BUTTON-STUFF
    ###################################
    async def _trigger_button(self, key: str, payload: str):
        return await getattr(self, 'trigger_' + key)(payload)

    ###################################
    # NUMBER-STUFF
    ###################################
    async def set_number_value(self, array_key: str, value: float):
        # this will cause a method not found exception…
        return await getattr(self, 'set_nv_' + str(array_key))(value)

    ###################################
    # SELECT-STUFF
    ###################################
    async def set_string_value(self, key: str, value: str):
        return await getattr(self, 'set_string_value_' + key)(value)


    async def trigger_delete_cache(self, payload:str):
        await self._write_token_to_storage(token_dict=None)
        # reset all our internal objects…
        self._LAST_UPDATE_TS = 0
        self._QUERY_TOTALS_TS = 0
        self._QUERY_SYSTEM_DETAILS_TS = 0
        self._QUERY_SYSTEM_STATE_TS = 0
        self._QUERY_SPARE_CAPACITY_TS = 0
        self._QUERY_PEAK_SHAVING_TS = 0
        self._QUERY_SGREADY_STATE_TS = 0
        self._QUERY_SGREADY_CONF_TS = 0

        self._app_token_object = {}
        self._app_is_authenticated = False
        self._app_token = None
        self._app_master_plant_id = None
        self._app_serial_number = None
        self._app_wallbox_num_max = 4
        self._app_data_start_ts = -1
        self._app_data_end_ts = -1
        self._app_abilities = None
        self._app_raw_now = None
        self._app_raw_battery_device_state = None
        self._app_raw_today = None
        self._app_raw_system_details = None
        self._app_raw_system_state_obj = None
        self._app_raw_total = None
        self._static_TOTAL_SUMS_PREV_YEARS = None
        self._static_TOTAL_SUMS_PREV_MONTHS = None
        self._static_TOTAL_SUMS_PREV_DAYS = None
        self._static_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_YEARS = 1970
        self._static_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_MONTHS = 0
        self._static_TOTAL_SUMS_WAS_FETCHED_FOR_PREV_DAYS = 0
        self._static_TOTAL_WALLBOX_DATA = [copy.deepcopy(self._static_A_WALLBOX_STORAGE) for _ in range(4)]
        await self.app_authenticate()
        return True
