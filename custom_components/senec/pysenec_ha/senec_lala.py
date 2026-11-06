import asyncio
import base64
import copy
import json
import logging
from collections import deque
from dataclasses import replace
from json import JSONDecodeError
from time import time
from typing import Final

import aiohttp
from aiohttp import ClientConnectionError, RequestInfo

from custom_components.senec.const import (
    QUERY_PV1_KEY,
    QUERY_PM1OBJ1_KEY,
    QUERY_PM1OBJ2_KEY,
    QUERY_BMS_KEY,
    QUERY_BMS_CELLS_KEY,
    QUERY_FANDATA_KEY,
    QUERY_WALLBOX_KEY,
    QUERY_SOCKETS_KEY,
    IGNORE_SYSTEM_STATE_KEY,
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
    SENEC_SECTION_BAT1OBJ1,

    SENEC_SECTION_FACTORY,
    SENEC_SECTION_SYS_UPDATE,
    SENEC_SECTION_BAT1,
    SENEC_SECTION_WIZARD,
    SENEC_SECTION_LOG,

    APP_API_WB_MODE_LOCKED,
    APP_API_WB_MODE_2025_SOLAR,
    APP_API_WB_MODE_2025_FAST,
    APP_API_WB_MODE_2025_COMFORT,

    LOCAL_WB_MODE_LEGACY_LOCKED,
    LOCAL_WB_MODE_LEGACY_SSGCM_3,
    LOCAL_WB_MODE_LEGACY_SSGCM_4,
    LOCAL_WB_MODE_LEGACY_FAST,
    LOCAL_WB_MODE_LEGACY_FAST_WITHBATTERY,
    LOCAL_WB_MODE_LEGACY_COMFORT_NIGHT_ON_DAY_ON,
    LOCAL_WB_MODE_LEGACY_COMFORT_NIGHT_ON_DAY_OFF,
    LOCAL_WB_MODE_LEGACY_COMFORT_NIGHT_OFF_DAY_ON,
    LOCAL_WB_MODE_LEGACY_COMFORT_NIGHT_OFF_DAY_OFF,
    LOCAL_WB_MODE_LEGACY_UNKNOWN,

    LOCAL_WB_MODE_2026_LOCKED,
    LOCAL_WB_MODE_2026_SSGCM,
    LOCAL_WB_MODE_2026_FAST,
    LOCAL_WB_MODE_2026_COMFORT,
    LOCAL_WB_MODE_2026_UNKNOWN,

    SGREADY_CONF_KEYS,
    SGREADY_MODES,
    SGREADY_CONFKEY_ENABLED,
    SENEC_ENERGY_FIELDS,
    SENEC_ENERGY_FIELDS_2408_MIN,

    NO_LIMIT,
    UPDATE_INTERVALS,
    UPDATE_INTERVAL_OPTIONS,
)
from custom_components.senec.pysenec_ha import ServiceUnavailableException, util

_LOGGER = logging.getLogger(__name__)

SET_COOKIE: Final = "Set-Cookie"

# 4: "INITIAL CHARGE",
# 5: "MAINTENANCE CHARGE",
# 8: "MAN. SAFETY CHARGE",
# 10: "FULL CHARGE",
# 11: "EQUALIZATION: CHARGE",
# 12: "DESULFATATION: CHARGE",
# 14: "CHARGE",
# 43: "CAPACITY TEST: CHARGE",
# 71: "OFFPEAK-CHARGE",
SYSTEM_STATUS_CHARGE: Final = {4, 5, 8, 10, 11, 12, 14, 23, 24, 25, 33, 43, 71}

# 16: "DISCHARGE",
# 17: "PV + DISCHARGE",
# 18: "GRID + DISCHARGE"
# 21: "OWN CONSUMPTION"
# 44: "CAPACITY TEST: DISCHARGE",
# 97: "SAFETY DISCHARGE",
SYSTEM_STATUS_DISCHARGE: Final = {16, 17, 18, 21, 29, 44, 97}

DEFAULT_HEADERS: Final = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Encoding": "gzip, deflate, br, zstd",
}
LALA_HEADERS: Final = {
    **DEFAULT_HEADERS,
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Connection": "keep-alive"
}

class SenecLocal:
    """Senec Home Battery Sensor"""

    def __str__(self) -> str:
        return f"SenecLocal [{util.mask_string(self._host_and_schema)}, Serial: S{util.mask_string(self.device_id)}]"

    def __init__(self, host, use_https, lala_session, lang: str = "en", options: dict = None, integ_version: str = None):
        self._integration_version = integ_version if integ_version is not None else "UNKNOWN"
        _LOGGER.info(f"__init__() -> (re)starting SenecLocal (lala.cgi) integration v{self._integration_version} for host: '{host}' with options: {options}")
        self._lang = lang

        # this property will be finally set on config_read
        self._QUERY_STATS = True
        self._QUERY_USER_LEVEL = False

        # all other query fields depends on the config
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
                _LOGGER.debug(f"WEB_SESSION cookie_jar accept cookies for IP's")


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
        self._last_version_attempt = 0
        self._last_system_reset = 0
        self._timeout = aiohttp.ClientTimeout(total=20, connect=None, sock_connect=None, sock_read=None,
                                              ceil_threshold=5)

        # an list for number entities, that must be patched, once we have set the
        # 'self._bridge_to_senec_online' to something...
        self._number_entities_to_patch_later = []
        self._bridge_to_senec_online = None
        self._source:deque = deque(maxlen=50)
        _LOGGER.debug(f"initialized SUCCESSFULLY")

    def dump_response_data(self, payload_data, req:RequestInfo):
        self._source.append({
            "req": str(req.real_url),
            "headers": dict(req.headers),
            "resp": copy.deepcopy(payload_data)
        })

    def dict_data(self) -> dict:
        # will be called by the UpdateCoordinator (to get the current data)
        # self._raw = None
        # self._raw_version = None
        return {"data": self._raw, "version": self._raw_version}

    def set_senec_online_instance(self, a_senec_online):
        if a_senec_online is not None:
            _LOGGER.info(f"set_senec_online_instance(): SIBLING: SenecLocal: bound a instance of SenecOnline - BRIDGE from LOCAL to ONLINE is establish!")
            self._bridge_to_senec_online = a_senec_online
            if self._QUERY_WALLBOX_APPAPI:
                self._bridge_to_senec_online._QUERY_WALLBOX = True
                # ok let's force an UPDATE of the WEB-API
                _LOGGER.info(f"set_senec_online_instance(): force refresh of wallbox-data via app-api…")
                try:
                    asyncio.create_task(self._bridge_to_senec_online.update())
                except Exception as exc:
                    _LOGGER.debug(f"set_senec_online_instance(): Exception while try to call 'self._bridge_to_senec_online.update': {exc}")

            # ok after we have set the new SenecOnline Object (to our SenecLocal instance) we can/should patch the remaining
            # min/max values...
            try:
                for a_obj in self._number_entities_to_patch_later:
                    the_number_entity_to_adjust = a_obj["entity"]
                    the_method_to_call = a_obj["method"]
                    min_max_range = getattr(self, the_method_to_call)
                    if min_max_range is not None and len(min_max_range) > 1:
                        _LOGGER.debug(f"set_senec_online_instance(): LOCAL: Going to adjust min/max values for '{the_number_entity_to_adjust.entity_description.key}' with min: {min_max_range[0]} and max: {min_max_range[1]}")
                        the_min_val = round(float(min_max_range[0]), 1)
                        the_max_val = round(float(min_max_range[1]), 1)

                        try:
                            the_number_entity_to_adjust._attr_native_min_value = the_min_val
                            the_number_entity_to_adjust._attr_native_max_value = the_max_val
                        except:
                            pass

                        the_number_entity_to_adjust.entity_description = replace(
                            the_number_entity_to_adjust.entity_description,
                            native_min_value=the_min_val,
                            native_max_value=the_max_val
                        )
                    else:
                        _LOGGER.debug(f"set_senec_online_instance(): LOCAL: No min/max values found for '{the_number_entity_to_adjust.entity_description.key}' - tried to called '{the_method_to_call}', did method exist? {hasattr(self, the_method_to_call)} - DEBUG self: {self}")
            except BaseException as exc:
                _LOGGER.debug(f"set_senec_online_instance(): LOCAL: Error while adjusting min/max values: {type(exc).__name__} - {exc}")
        else:
            _LOGGER.info(f"set_senec_online_instance(): SIBLING: SenecLocal: remove reference to SenecOnline - BRIDGE from LOCAL to ONLINE is destroyed!")
            self._bridge_to_senec_online = None

    async def update(self):
        if self._raw_version is None or len(self._raw_version) == 0:
            await self.update_version()
            if self._raw_version is None or len(self._raw_version) == 0:
                # if we could not read any version data, we should cancel any possible
                # startup...
                raise ServiceUnavailableException(f"Could not read version information from lala.cgi @ {self._host}")

        await self._read_senec_lala_with_retry(retry=True)

    async def update_version(self):
        # we do not expect that the version info will update in the next 60 minutes…
        if self._last_version_update + 3600 < time():
            # do not hammer the lala cgi with too many requests...
            if self._last_version_attempt + 120 < time():
                self._last_version_attempt = time()
                await self._init_gui_cookies(retry=True)
                await self._read_version()

    async def _init_gui_cookies(self, retry:bool):
        # with NPU 2411 we must start the communication with the backend with this single call…
        # no clue what type of special SENEC-Style security this is?!…
        form = {SENEC_SECTION_FACTORY:{"SYS_TYPE":"","COUNTRY":"","DEVICE_ID":""}}
        try:
            async with self.lala_session.post(self.url, json=form, ssl=False, headers=LALA_HEADERS, timeout=self._timeout) as res:
                _LOGGER.debug(f"_init_gui_cookies(): {util.mask_map(form)} from '{self.url}' - with headers: {res.request_info.headers}")
                try:
                    res.raise_for_status()
                    r_data = await res.json()
                    self.dump_response_data(r_data, res.request_info)
                    data = util.parse(r_data)

                    if SET_COOKIE in res.headers:
                        _LOGGER.debug(f"_init_gui_cookies(): response {util.mask_map(data)} - {res.headers[SET_COOKIE]}")
                    else:
                        if(retry):
                            _LOGGER.debug(f"_init_gui_cookies(): response {util.mask_map(data)} - NO COOKIES in RESPONSE (try to logout)")
                            await asyncio.sleep(2)
                            await self._senec_local_access_stop_no_checks()
                            await asyncio.sleep(5)
                            await self._init_gui_cookies(retry=False)
                        else:
                            _LOGGER.debug(f"_init_gui_cookies(): response {util.mask_map(data)} - NO COOKIES in RESPONSE")

                except JSONDecodeError as exc:
                    _LOGGER.warning(f"_init_gui_cookies(): JSONDecodeError while 'await res.json()' {exc}")

        except asyncio.TimeoutError:
            _LOGGER.info(f"_init_gui_cookies(): TimeoutError (20sec) while posting '{form}'")
        except BaseException as exe:
            _LOGGER.warning(f"_init_gui_cookies caused {type(exe).__name__} - {exe}")

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

        try:
            async with self.lala_session.post(self.url, json=form, ssl=False, headers=LALA_HEADERS, timeout=self._timeout) as res:
                _LOGGER.debug(f"_read_version() {util.mask_map(form)} from '{self.url}' - with headers: {res.request_info.headers}")
                try:
                    res.raise_for_status()
                    r_data = await res.json()
                    self.dump_response_data(r_data, res.request_info)
                    self._raw_version = util.parse(r_data)
                    self._last_version_update = time()
                except JSONDecodeError as exc:
                    _LOGGER.warning(f"_read_version(): JSONDecodeError while 'await res.json()' {exc}")
        except asyncio.TimeoutError:
            _LOGGER.info(f"_read_version(): TimeoutError (20sec) while posting '{form}'")
        except BaseException as exe:
            _LOGGER.warning(f"_read_version(): caused {type(exe).__name__} - {exe}")

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
        except ClientConnectionError as exc:
            _LOGGER.info(f"{exc}")
            if retry:
                await asyncio.sleep(5)
                await self._read_senec_lala_with_retry(retry=False)
            else:
                _LOGGER.info(f"_read_senec_lala_with_retry() failed with {type(exc).__name__} - {exc}")

    async def _read_senec_lala(self):
        # captured 2026/08
        # form_lala_captured = {
        #     "PM1OBJ1": {
        #         "FREQ": "",
        #         "U_AC": "",
        #         "I_AC": "",
        #         "P_AC": "",
        #         "P_TOTAL": ""
        #     },
        #     "PM1OBJ2": {
        #         "FREQ": "",
        #         "U_AC": "",
        #         "I_AC": "",
        #         "P_AC": "",
        #         "P_TOTAL": ""
        #     },
        #     "ENERGY": {
        #         "STAT_STATE": "",
        #         "STAT_HOURS_OF_OPERATION": "",
        #         "GUI_BAT_DATA_POWER": "",
        #         "GUI_BAT_DATA_VOLTAGE": "",
        #         "GUI_BAT_DATA_CURRENT": "",
        #         "GUI_BAT_DATA_FUEL_CHARGE": "",
        #         "GUI_HOUSE_POW": "",
        #         "GUI_INVERTER_POWER": "",
        #         "STAT_LIMITED_NET_SKEW": ""
        #     },
        #     "SYS_UPDATE": {
        #         "NPU_VER": "",
        #         "NPU_IMAGE_VERSION": ""
        #     },
        #     "PV1": {
        #         "POWER_RATIO": "",
        #         "POWER_RATIO_L1": "",
        #         "POWER_RATIO_L2": "",
        #         "POWER_RATIO_L3": "",
        #         "MPP_VOL": "",
        #         "MPP_CUR": "",
        #         "MPP_POWER": "",
        #         "MPP_AVAIL": "",
        #         "INTERNAL_MD_AVAIL": "",
        #         "INTERNAL_MD_MODEL": "",
        #         "INTERNAL_MD_VERSION": ""
        #     },
        #     "WIZARD": {
        #         "MAC_ADDRESS_BYTES": ""
        #     },
        #     "BAT1OBJ1": {
        #         "TEMP1": "",
        #         "TEMP2": "",
        #         "TEMP3": "",
        #         "TEMP4": "",
        #         "TEMP5": "",
        #         "S": "",
        #         "P": "",
        #         "Q": "",
        #         "SW_VERSION": "",
        #         "SW_VERSION2": "",
        #         "SW_VERSION3": "",
        #         "I_DC": ""
        #     },
        #     "PWR_UNIT": {
        #         "POWER_L1": "",
        #         "POWER_L2": "",
        #         "POWER_L3": ""
        #     },
        #     "BAT1": {
        #         "SPARE_CAPACITY": ""
        #     },
        #     "BMS": {
        #         "NR_INSTALLED": ""
        #     },
        #     "WALLBOX": {},
        #     "GRIDCONFIG": {}
        # }
        # form_lala_captured_second = {
        #     "WIZARD": {
        #         "GUI_LANG": "",
        #         "FEATURECODE_ENTERED": "",
        #         "ZEROMODULE": "",
        #         "SETUP_NUMBER_WALLBOXES": "",
        #         "CONFIG_LOADED": ""
        #     },
        #     "LOG": {
        #         "USER_LEVEL": "",
        #         "USERNAME": "",
        #         "LOG_IN_NOK_COUNT": ""
        #     },
        #     "RTC": {
        #         "WEB_TIME": ""
        #     },
        #     "FEATURES": {},
        #     "BMS": {
        #         "WIZARD_STARTDETECTION": "",
        #         "WIZARD_CONFDETECTION": "",
        #         "WIZARD_RESDETECTION": "",
        #         "WIZARD_TIMEOUTDETECTION": "",
        #         "WIZARD_FINISHEDDETECTION": ""
        #     },
        #     "IPU": {
        #         "VERSION": ""
        #     }
        # }

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

            # 2026/08 - let's see what we will get...
            # well actually not really valuable data ?!
            # 'BAT1OBJ1': {'TEMP1': 29, 'TEMP2': 29, 'TEMP3': 0, 'TEMP4': 0, 'TEMP5': 0, 'S': 0, 'P': 0, 'Q': 0, 'SW_VERSION': 51445854, 'SW_VERSION2': 67502419, 'SW_VERSION3': 84213770, 'I_DC': 0.004000000189989805}
            # form[SENEC_SECTION_BAT1OBJ1] = { "TEMP1": "", "TEMP2": "", "TEMP3": "", "TEMP4": "", "TEMP5": "", "S": "", "P": "", "Q": "", "SW_VERSION": "", "SW_VERSION2": "", "SW_VERSION3": "", "I_DC": ""}
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
            # requested by web FE
            # data = {"WALLBOX": {"HW_TYPE": "",
            #                     "APPARENT_CHARGING_POWER": "",
            #                     "L1_CHARGING_CURRENT": "",
            #                     "L2_CHARGING_CURRENT": "",
            #                     "L3_CHARGING_CURRENT": "",
            #                     "MAX_CHARGING_CURRENT_IC": "",
            #                     "MAX_CHARGING_CURRENT_RATED": "",
            #                     "MAX_CHARGING_CURRENT_DEFAULT": "",
            #                     "MAX_CHARGING_CURRENT_ICMAX": "",
            #                     "PROHIBIT_USAGE": "",
            #                     "STATE": "",
            #                     "BUS_ADR": ""},
            #         "WIZARD": {"SETUP_NUMBER_WALLBOXES": ""}}

            form[SENEC_SECTION_WALLBOX] = {
                "APPARENT_CHARGING_POWER": "",
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

        await self._request_senec_lala_chunked(form)

    async def _request_senec_lala_chunked(self, payload: dict, max_len: int = 600) -> dict:
        _LOGGER.debug(f"_request_senec_lala_chunked(): request {util.mask_map(payload)} from '{self.url}'")
        req_min_wait = 0.2
        def compact_json(data: dict) -> str:
            # Replicates JS JSON.stringify() character formatting (no spaces)
            return json.dumps(data, separators=(',', ':'))

        chunk_form_data = {}
        responses = {}
        part_count = 0

        # Process key-value pairs and chunk if length limit is reached
        must_pause = False
        for key, value in payload.items():
            # Check if serialized item + current chunk exceeds character limit
            if len(compact_json(value)) + len(compact_json(chunk_form_data)) >= max_len:
                if chunk_form_data:
                    if must_pause:
                        await asyncio.sleep(req_min_wait)
                    must_pause = True

                    # Send full chunk
                    a_chunk_response = await self._request_senec_lala(chunk_form_data, part_count)
                    part_count += 1
                    if a_chunk_response is not None:
                        responses.update(a_chunk_response)
                    chunk_form_data = {}

            chunk_form_data[key] = value

        # Send remaining payload buffer
        if chunk_form_data:
            if must_pause:
                await asyncio.sleep(req_min_wait)
            a_chunk_response = await self._request_senec_lala(chunk_form_data, part_count)
            if a_chunk_response is not None:
                responses.update(a_chunk_response)

        # finally processing the complete response object (after the requests had been chuncked to max of 600 bytes)
        self._raw = util.parse(responses)

    async def _request_senec_lala(self, form:dict, part_count:int):
        try:
            async with self.lala_session.post(self.url, json=form, ssl=False, headers=LALA_HEADERS, timeout=self._timeout) as res:
                _LOGGER.debug(f"_request_senec_lala() form-part[{part_count}] with len: {len(json.dumps(form, separators=(',', ':')))} from '{self.url}' - with headers: {res.request_info.headers}")
                try:
                    res.raise_for_status()
                    r_data = await res.json()
                    self.dump_response_data(r_data, res.request_info)
                    return r_data
                except JSONDecodeError as exc:
                    _LOGGER.warning(f"_request_senec_lala(): JSONDecodeError while 'await res.json()' {exc}")
                except Exception as err:
                    _LOGGER.warning(f"_request_senec_lala(): read_senec_lala caused: {err}")

        except asyncio.TimeoutError:
            _LOGGER.info(f"_request_senec_lala(): TimeoutError (20sec) while posting '{form}'")
        except BaseException as e:
            _LOGGER.info(f"_request_senec_lala() caused: {type(e).__name__} - {e}")

    async def _read_all_fields(self) -> []:
        form = {}
        try:
            post_data = {"DEBUG": {"SECTIONS": ""}}
            async with self.lala_session.post(self.url, json=post_data, ssl=False, headers=LALA_HEADERS, timeout=self._timeout) as res:
                try:
                    res.raise_for_status()
                    r_data = await res.json()
                    self.dump_response_data(r_data, res.request_info)
                    obj = util.parse(r_data)
                    for section in obj["DEBUG"]["SECTIONS"]:
                        form[section] = {}
                except JSONDecodeError as exc:
                    _LOGGER.warning(f"_read_all_fields(): P1 JSONDecodeError while 'await res.json()' {exc}")
        except asyncio.TimeoutError:
            _LOGGER.info(f"_read_all_fields(): P1 TimeoutError (20sec) while posting '{post_data}'")
        except BaseException as exe:
            _LOGGER.warning(f"_read_all_fields P1 caused {type(exe).__name__} - {exe}")

        if len(form) > 0:
            try:
                async with self.lala_session.post(self.url, json=form, ssl=False, headers=LALA_HEADERS, timeout=self._timeout) as res:
                    try:
                        res.raise_for_status()
                        r_data = await res.json()
                        self.dump_response_data(r_data, res.request_info)
                        return util.parse(r_data)
                    except JSONDecodeError as exc:
                        _LOGGER.warning(f"_read_all_fields(): P2 JSONDecodeError while 'await res.json()' {exc}")
            except asyncio.TimeoutError:
                _LOGGER.info(f"_read_all_fields(): P2 TimeoutError (20sec) while posting '{form}'")
            except BaseException as exe:
                _LOGGER.warning(f"_read_all_fields P2 caused {type(exe).__name__} - {exe}")

        return None

    ###################################
    # LOCAL-WRITE
    ###################################
    async def _write(self, data):
        await self._write_senec_v31(data)

    async def _write_senec_v31(self, data):
        _LOGGER.debug(f"_write_senec_v31(): posting data (raw): {util.mask_map(data)}")
        try:
            async with self.lala_session.post(self.url, json=data, ssl=False, headers=LALA_HEADERS, timeout=self._timeout) as res:
                try:
                    res.raise_for_status()
                    r_data = await res.json()
                    self.dump_response_data(r_data, res.request_info)
                    self._raw_post = util.parse(r_data)
                    _LOGGER.debug(f"_write_senec_v31(): post result (already parsed): {util.mask_map(self._raw_post)}")
                    return self._raw_post
                except Exception as err:
                    _LOGGER.warning(f"_write_senec_v31(): Error while 'posting data' {err}")
        except asyncio.TimeoutError:
            _LOGGER.info(f"_write_senec_v31(): TimeoutError (20sec) while posting '{util.mask_map(data)}'")
        except BaseException as e:
            _LOGGER.info(f"_write_senec_v31() caused: {type(e).__name__} - {e}")

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
            "Connection": "keep-alive"
        }

        try:
            async with self.lala_session.post(self.url, data=form_data_str, headers=special_hdrs, ssl=False, chunked=None, timeout=self._timeout) as res:
                _LOGGER.debug(f"senec_v31_post_plain_form_data() '{self.url}' with headers: {res.request_info.headers}")
                try:
                    res.raise_for_status()
                    r_data = await res.json()
                    self.dump_response_data(r_data, res.request_info)
                    self._raw_post = util.parse(r_data)
                    _LOGGER.debug(f"senec_v31_post_plain_form_data(): post result (already parsed): {util.mask_map(self._raw_post)}")
                    return self._raw_post
                except Exception as err:
                    _LOGGER.warning(f"senec_v31_post_plain_form_data(): Error while 'posting data' {err}")
        except asyncio.TimeoutError:
            _LOGGER.info(f"senec_v31_post_plain_form_data(): TimeoutError (20sec) while posting '{form_data_str}'")
        except BaseException as e:
            _LOGGER.info(f"senec_v31_post_plain_form_data() caused: {type(e).__name__} - {e}")


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
        if self._raw is not None and SENEC_SECTION_ENERGY in self._raw:
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
        if self._raw is not None and SENEC_SECTION_ENERGY in self._raw:
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
        if self._raw is not None and SENEC_SECTION_STATISTIC in self._raw and "LIVE_HOUSE_CONS" in self._raw[SENEC_SECTION_STATISTIC]:
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
        if self._raw is not None and SENEC_SECTION_STATISTIC in self._raw and "LIVE_PV_GEN" in self._raw[SENEC_SECTION_STATISTIC]:
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
    def wallbox_1_power_alt(self) -> float:
        """
        Wallbox Total Charging Power (W)
        """
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "APPARENT_CHARGING_POWER" in self._raw[SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["APPARENT_CHARGING_POWER"][0]

    @property
    def wallbox_1_ev_connected(self) -> bool:
        """
        Wallbox EV Connected
        """
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "EV_CONNECTED" in self._raw[SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["EV_CONNECTED"][0]

    @property
    def wallbox_1_energy(self) -> float:
        """
        Wallbox Total Energy
        """
        if self._raw is not None and SENEC_SECTION_STATISTIC in self._raw and "LIVE_WB_ENERGY" in self._raw[SENEC_SECTION_STATISTIC]:
            return self._raw[SENEC_SECTION_STATISTIC]["LIVE_WB_ENERGY"][0]

    @property
    def wallbox_1_l1_used(self) -> bool:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L1_USED"][0] == 1

    @property
    def wallbox_1_l2_used(self) -> bool:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L2_USED"][0] == 1

    @property
    def wallbox_1_l3_used(self) -> bool:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L3_USED"][0] == 1

    @property
    def wallbox_1_l1_charging_current(self) -> float:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L1_CHARGING_CURRENT" in self._raw[SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L1_CHARGING_CURRENT"][0]

    @property
    def wallbox_1_l2_charging_current(self) -> float:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L2_CHARGING_CURRENT" in self._raw[SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L2_CHARGING_CURRENT"][0]

    @property
    def wallbox_1_l3_charging_current(self) -> float:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L3_CHARGING_CURRENT" in self._raw[SENEC_SECTION_WALLBOX]:
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
    def wallbox_2_power_alt(self) -> float:
        """
        Wallbox Total Charging Power (W)
        """
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "APPARENT_CHARGING_POWER" in self._raw[SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["APPARENT_CHARGING_POWER"][1]

    @property
    def wallbox_2_ev_connected(self) -> bool:
        """
        Wallbox EV Connected
        """
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "EV_CONNECTED" in self._raw[SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["EV_CONNECTED"][1]

    @property
    def wallbox_2_energy(self) -> float:
        """
        Wallbox Total Energy
        """
        if self._raw is not None and SENEC_SECTION_STATISTIC in self._raw and "LIVE_WB_ENERGY" in self._raw[SENEC_SECTION_STATISTIC]:
            return self._raw[SENEC_SECTION_STATISTIC]["LIVE_WB_ENERGY"][1]

    @property
    def wallbox_2_l1_used(self) -> bool:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L1_USED"][1] == 1

    @property
    def wallbox_2_l2_used(self) -> bool:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L2_USED"][1] == 1

    @property
    def wallbox_2_l3_used(self) -> bool:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L3_USED"][1] == 1

    @property
    def wallbox_2_l1_charging_current(self) -> float:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L1_CHARGING_CURRENT" in self._raw[SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L1_CHARGING_CURRENT"][1]

    @property
    def wallbox_2_l2_charging_current(self) -> float:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L2_CHARGING_CURRENT" in self._raw[SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L2_CHARGING_CURRENT"][1]

    @property
    def wallbox_2_l3_charging_current(self) -> float:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L3_CHARGING_CURRENT" in self._raw[SENEC_SECTION_WALLBOX]:
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
    def wallbox_3_power_alt(self) -> float:
        """
        Wallbox Total Charging Power (W)
        """
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "APPARENT_CHARGING_POWER" in self._raw[SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["APPARENT_CHARGING_POWER"][2]

    @property
    def wallbox_3_ev_connected(self) -> bool:
        """
        Wallbox EV Connected
        """
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "EV_CONNECTED" in self._raw[SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["EV_CONNECTED"][2]

    @property
    def wallbox_3_energy(self) -> float:
        """
        Wallbox Total Energy
        """
        if self._raw is not None and SENEC_SECTION_STATISTIC in self._raw and "LIVE_WB_ENERGY" in self._raw[SENEC_SECTION_STATISTIC]:
            return self._raw[SENEC_SECTION_STATISTIC]["LIVE_WB_ENERGY"][2]

    @property
    def wallbox_3_l1_used(self) -> bool:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L1_USED"][2] == 1

    @property
    def wallbox_3_l2_used(self) -> bool:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L2_USED"][2] == 1

    @property
    def wallbox_3_l3_used(self) -> bool:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L3_USED"][2] == 1

    @property
    def wallbox_3_l1_charging_current(self) -> float:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L1_CHARGING_CURRENT" in self._raw[SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L1_CHARGING_CURRENT"][2]

    @property
    def wallbox_3_l2_charging_current(self) -> float:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L2_CHARGING_CURRENT" in self._raw[SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L2_CHARGING_CURRENT"][2]

    @property
    def wallbox_3_l3_charging_current(self) -> float:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L3_CHARGING_CURRENT" in self._raw[SENEC_SECTION_WALLBOX]:
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
    def wallbox_4_power_alt(self) -> float:
        """
        Wallbox Total Charging Power (W)
        """
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "APPARENT_CHARGING_POWER" in self._raw[SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["APPARENT_CHARGING_POWER"][3]

    @property
    def wallbox_4_ev_connected(self) -> bool:
        """
        Wallbox EV Connected
        """
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "EV_CONNECTED" in self._raw[SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["EV_CONNECTED"][3]

    @property
    def wallbox_4_energy(self) -> float:
        """
        Wallbox Total Energy
        """
        if self._raw is not None and SENEC_SECTION_STATISTIC in self._raw and "LIVE_WB_ENERGY" in self._raw[SENEC_SECTION_STATISTIC]:
            return self._raw[SENEC_SECTION_STATISTIC]["LIVE_WB_ENERGY"][3]

    @property
    def wallbox_4_l1_used(self) -> bool:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L1_USED"][3] == 1

    @property
    def wallbox_4_l2_used(self) -> bool:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L2_USED"][3] == 1

    @property
    def wallbox_4_l3_used(self) -> bool:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L3_USED"][3] == 1

    @property
    def wallbox_4_l1_charging_current(self) -> float:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L1_CHARGING_CURRENT" in self._raw[SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L1_CHARGING_CURRENT"][3]

    @property
    def wallbox_4_l2_charging_current(self) -> float:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L2_CHARGING_CURRENT" in self._raw[SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L2_CHARGING_CURRENT"][3]

    @property
    def wallbox_4_l3_charging_current(self) -> float:
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L3_CHARGING_CURRENT" in self._raw[SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L3_CHARGING_CURRENT"][3]

    @property
    def wallbox_4_min_charging_current(self) -> float:
        return self.read_array_data(SENEC_SECTION_WALLBOX, "MIN_CHARGING_CURRENT")[3]

    @property
    def fan_inv_lv(self) -> bool:
        if self._raw is not None and SENEC_SECTION_FAN_SPEED in self._raw and "INV_LV" in self._raw[SENEC_SECTION_FAN_SPEED]:
            return self._raw[SENEC_SECTION_FAN_SPEED]["INV_LV"] > 0

    @property
    def fan_inv_hv(self) -> bool:
        if self._raw is not None and SENEC_SECTION_FAN_SPEED in self._raw and "INV_HV" in self._raw[SENEC_SECTION_FAN_SPEED]:
            return self._raw[SENEC_SECTION_FAN_SPEED]["INV_HV"] > 0

    @property
    def spare_capacity(self) -> int:
        if self._raw is not None and SENEC_SECTION_BAT1 in self._raw and "SPARE_CAPACITY" in self._raw[SENEC_SECTION_BAT1]:
            return self._raw[SENEC_SECTION_BAT1]["SPARE_CAPACITY"]

    @property
    def sockets_already_switched(self) -> [int]:
        if self._raw is not None and SENEC_SECTION_SOCKETS in self._raw and "ALREADY_SWITCHED" in self._raw[SENEC_SECTION_SOCKETS]:
            return self._raw[SENEC_SECTION_SOCKETS]["ALREADY_SWITCHED"]

    @property
    def sockets_power_on(self) -> [float]:
        if self._raw is not None and SENEC_SECTION_SOCKETS in self._raw and "POWER_ON" in self._raw[SENEC_SECTION_SOCKETS]:
            return self._raw[SENEC_SECTION_SOCKETS]["POWER_ON"]

    @property
    def sockets_priority(self) -> [float]:
        if self._raw is not None and SENEC_SECTION_SOCKETS in self._raw and "PRIORITY" in self._raw[SENEC_SECTION_SOCKETS]:
            return self._raw[SENEC_SECTION_SOCKETS]["PRIORITY"]

    @property
    def sockets_time_rem(self) -> [float]:
        if self._raw is not None and SENEC_SECTION_SOCKETS in self._raw and "TIME_REM" in self._raw[SENEC_SECTION_SOCKETS]:
            return self._raw[SENEC_SECTION_SOCKETS]["TIME_REM"]

    @property
    def wallbox_allow_intercharge(self) -> bool:
        # please note this is not ARRAY data - so we code it here again…
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "ALLOW_INTERCHARGE" in self._raw[SENEC_SECTION_WALLBOX]:
            # if it just has been switched on/off we provide a FAKE value for 5 sec…
            # since senec unit do not react 'instant' on some requests…
            if self._OVERWRITES[SENEC_SECTION_WALLBOX + "_ALLOW_INTERCHARGE"]["TS"] + 5 > time():
                return self._OVERWRITES[SENEC_SECTION_WALLBOX + "_ALLOW_INTERCHARGE"]["VALUE"]
            else:
                return self._raw[SENEC_SECTION_WALLBOX]["ALLOW_INTERCHARGE"] == 1

    async def switch_wallbox_allow_intercharge(self, value: bool, sync: bool = True):
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw:
            # WE must check if the lala ALLOW_INTERCHARGE is already in the state,
            # that will be requested to set!!!
            if value and self._raw[SENEC_SECTION_WALLBOX]["ALLOW_INTERCHARGE"] == 1:
                _LOGGER.debug(f"switch_wallbox_allow_intercharge(): skipp TURN ON, since it's already ON")
            elif not value and self._raw[SENEC_SECTION_WALLBOX]["ALLOW_INTERCHARGE"] == 0:
                _LOGGER.debug(f"switch_wallbox_allow_intercharge(): skipp TURN OFF, since it's already OFF")
            else:
                # BEFORE we can/should switch 'allow_intercharge' we MUST check
                # if ONE of the active WB's are set to the MODE FAST/FASTWITHBATTERY?!
                if sync and self._bridge_to_senec_online is not None:
                    if not self._bridge_to_senec_online.app_only_for_local_is_any_wallbox_in_fast_or_fastwithbattery_mode():
                        _LOGGER.warning(f"switch_wallbox_allow_intercharge(): can NOT switch 'allow_intercharge' {value}, since no WB's is in FAST mode!")
                        return False

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

                # 2026/01/17: WHEN we set the allow_intercharge flag locally ON at the senec system, then IMHO
                # we must ALSO adjust ALL wallbox-modes to FAST! ?!
                await self._write(post_data)

            if sync and self._bridge_to_senec_online is not None:
                # ALLOW_INTERCHARGE seams to be a wallbox-number independent setting… so we need to push
                # this to all 4 possible wallboxes…
                await self._bridge_to_senec_online.app_only_for_local_adjust_mode_on_local_allow_intercharge_switch(value_to_set=value)

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
    #         await self._SenecOnline.app_set_wallbox_mode_legacy(local_mode_to_set=mode, wallbox_num=(pos + 1), sync=False)

    def read_array_data(self, section_key: str, array_values_key) -> []:
        if self._raw is not None and section_key in self._raw and array_values_key in self._raw[section_key]:
            if self._OVERWRITES[section_key + "_" + array_values_key]["TS"] + 5 > time():
                return self._OVERWRITES[section_key + "_" + array_values_key]["VALUE"]
            else:
                return self._raw[section_key][array_values_key]
        else:
            return None

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
        if self._bridge_to_senec_online is not None:
            wb_data = self._bridge_to_senec_online._app_get_wallbox_object_at_index(0)
            return self._wallbox_set_icmax_extrema(wb_data)
        return None

    @property
    def wallbox_2_set_icmax_extrema(self) -> [float]:
        if self._bridge_to_senec_online is not None:
            wb_data = self._bridge_to_senec_online._app_get_wallbox_object_at_index(1)
            return self._wallbox_set_icmax_extrema(wb_data)
        return None

    @property
    def wallbox_3_set_icmax_extrema(self) -> [float]:
        if self._bridge_to_senec_online is not None:
            wb_data = self._bridge_to_senec_online._app_get_wallbox_object_at_index(2)
            return self._wallbox_set_icmax_extrema(wb_data)
        return None

    @property
    def wallbox_4_set_icmax_extrema(self) -> [float]:
        if self._bridge_to_senec_online is not None:
            wb_data = self._bridge_to_senec_online._app_get_wallbox_object_at_index(3)
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
            if self._bridge_to_senec_online is not None:
                local_mode = self._bridge_to_senec_online._app_get_local_wallbox_mode_from_api_values_legacy(pos)
            else:
                local_mode = "no-bridge-avail"
        else:
            local_mode = LOCAL_WB_MODE_LEGACY_SSGCM_3

        if local_mode == LOCAL_WB_MODE_LEGACY_SSGCM_3 or local_mode == LOCAL_WB_MODE_LEGACY_SSGCM_4:
            if SENEC_SECTION_WALLBOX in self._raw and (
                    "SET_ICMAX" in self._raw[SENEC_SECTION_WALLBOX] and
                    "MIN_CHARGING_CURRENT" in self._raw[SENEC_SECTION_WALLBOX]):

                await self.set_multi_post(4, pos,
                                          SENEC_SECTION_WALLBOX, "SET_ICMAX", "fl", value,
                                          SENEC_SECTION_WALLBOX, "MIN_CHARGING_CURRENT", "fl", value)

                if sync and self._bridge_to_senec_online is not None:
                    # DEACTIVATED SYNC CAUSE OF
                    # https://github.com/marq24/ha-senec-v3/issues/234
                    # await self._bridge_to_senec_online.app_set_wallbox_icmax(value_to_set=value, wallbox_num=(pos + 1), sync=False)
                    _LOGGER.info(f"set_nva_wallbox_set_icmax(): SKIP OnlineSYNC for value: {value} - {(pos + 1)} DEACTIVATED SYNC CAUSE OF https://github.com/marq24/ha-senec-v3/issues/234")
            else:
                _LOGGER.warning(f"No data for '{SENEC_SECTION_WALLBOX}': 'SET_ICMAX' and/or 'MIN_CHARGING_CURRENT' in self._raw!"
                                f" -> {self._raw.keys()} -> {"NO 'SENEC_SECTION_WALLBOX' PRESENT" if SENEC_SECTION_WALLBOX not in self._raw else self._raw[SENEC_SECTION_WALLBOX].keys()}")
        else:
            _LOGGER.debug(f"Ignoring 'set_wallbox_{(pos + 1)}_set_icmax' to '{value}' since current mode is: {local_mode}")

    @property
    def wallbox_set_idefault(self) -> [float]:
        return self.read_array_data(SENEC_SECTION_WALLBOX, "SET_IDEFAULT")

    async def set_nva_wallbox_set_idefault(self, pos: int, value: float):
        await self.set_nva_post(SENEC_SECTION_WALLBOX, "SET_IDEFAULT", pos, 4, "fl", value)

    async def set_number_value_array(self, array_key: str, array_pos: int, value: float):
        return await getattr(self, 'set_nva_' + str(array_key))(array_pos, value)

    def _local_wallbox_mode_from_lala(self, pos: int) -> str:
        prohibit_usage = self.read_array_data(SENEC_SECTION_WALLBOX, "PROHIBIT_USAGE")
        smart_charge_active = self.read_array_data(SENEC_SECTION_WALLBOX, "SMART_CHARGE_ACTIVE")
        allow_intercharge = self.read_array_data(SENEC_SECTION_WALLBOX, "ALLOW_INTERCHARGE")

        try:
            if prohibit_usage is not None and int(float(prohibit_usage[pos])) == 1:
                return LOCAL_WB_MODE_LEGACY_LOCKED

            if smart_charge_active is not None:
                sca_val = int(float(smart_charge_active[pos]))
                if sca_val == 3:
                    return LOCAL_WB_MODE_LEGACY_SSGCM_3
                if sca_val == 4:
                    return LOCAL_WB_MODE_LEGACY_SSGCM_4
                if sca_val == 0:
                    # "ALLOW_INTERCHARGE" is not an array! - it's just "0" or "1"
                    if allow_intercharge is not None and int(float(allow_intercharge)) == 1:
                        return LOCAL_WB_MODE_LEGACY_FAST_WITHBATTERY
                    else:
                        return LOCAL_WB_MODE_LEGACY_FAST
        except (IndexError, TypeError, ValueError):
            pass
        return LOCAL_WB_MODE_LEGACY_UNKNOWN

    @property
    def wallbox_1_mode_legacy(self) -> str:
        if self._bridge_to_senec_online is not None:
            return self._bridge_to_senec_online._app_get_local_wallbox_mode_from_api_values_legacy(0)
        return self._local_wallbox_mode_from_lala(0)

    async def set_string_value_wallbox_1_mode_legacy(self, value: str):
        await self.set_wallbox_mode_post_int(0, value)
        if self._bridge_to_senec_online is not None:
            await self._bridge_to_senec_online.app_set_wallbox_mode_legacy(local_mode_to_set=value, wallbox_num=1, sync=False)

    @property
    def wallbox_2_mode_legacy(self) -> str:
        if self._bridge_to_senec_online is not None:
            return self._bridge_to_senec_online._app_get_local_wallbox_mode_from_api_values_legacy(1)
        return self._local_wallbox_mode_from_lala(1)

    async def set_string_value_wallbox_2_mode_legacy(self, value: str):
        await self.set_wallbox_mode_post_int(1, value)
        if self._bridge_to_senec_online is not None:
            await self._bridge_to_senec_online.app_set_wallbox_mode_legacy(local_mode_to_set=value, wallbox_num=2, sync=False)

    @property
    def wallbox_3_mode_legacy(self) -> str:
        if self._bridge_to_senec_online is not None:
            return self._bridge_to_senec_online._app_get_local_wallbox_mode_from_api_values_legacy(2)
        return self._local_wallbox_mode_from_lala(2)

    async def set_string_value_wallbox_3_mode_legacy(self, value: str):
        await self.set_wallbox_mode_post_int(2, value)
        if self._bridge_to_senec_online is not None:
            await self._bridge_to_senec_online.app_set_wallbox_mode_legacy(local_mode_to_set=value, wallbox_num=3, sync=False)

    @property
    def wallbox_4_mode_legacy(self) -> str:
        if self._bridge_to_senec_online is not None:
            return self._bridge_to_senec_online._app_get_local_wallbox_mode_from_api_values_legacy(3)
        return self._local_wallbox_mode_from_lala(3)

    async def set_string_value_wallbox_4_mode_legacy(self, value: str):
        await self.set_wallbox_mode_post_int(3, value)
        if self._bridge_to_senec_online is not None:
            await self._bridge_to_senec_online.app_set_wallbox_mode_legacy(local_mode_to_set=value, wallbox_num=4, sync=False)

    async def set_wallbox_mode_post_int(self, pos: int, local_value: str):
        if local_value == LOCAL_WB_MODE_LEGACY_LOCKED:
            await self.set_multi_post(4, pos,
                                      SENEC_SECTION_WALLBOX, "PROHIBIT_USAGE", "u8", 1,
                                      SENEC_SECTION_WALLBOX, "SMART_CHARGE_ACTIVE", "u8", 0)
        elif local_value == LOCAL_WB_MODE_LEGACY_SSGCM_3:
            await self.set_multi_post(4, pos,
                                      SENEC_SECTION_WALLBOX, "PROHIBIT_USAGE", "u8", 0,
                                      SENEC_SECTION_WALLBOX, "SMART_CHARGE_ACTIVE", "u8", 3)
        elif local_value == LOCAL_WB_MODE_LEGACY_SSGCM_4:
            await self.set_multi_post(4, pos,
                                      SENEC_SECTION_WALLBOX, "PROHIBIT_USAGE", "u8", 0,
                                      SENEC_SECTION_WALLBOX, "SMART_CHARGE_ACTIVE", "u8", 4)
        elif local_value == LOCAL_WB_MODE_LEGACY_FAST or local_value == LOCAL_WB_MODE_LEGACY_FAST_WITHBATTERY:
            await self.set_multi_post(4, pos,
                                      SENEC_SECTION_WALLBOX, "PROHIBIT_USAGE", "u8", 0,
                                      SENEC_SECTION_WALLBOX, "SMART_CHARGE_ACTIVE", "u8", 0)

    async def set_string_value(self, key: str, value: str):
        return await getattr(self, 'set_string_value_' + key)(value)

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
        if len(post_data) > 0:
            await self._write(post_data)
        else:
            _LOGGER.warning(f"No data to write for '{section_key1}': '{value_key1}' and/or '{section_key2}': '{value_key2}'")

    def prepare_post_data(self, post_data: dict, array_length: int, pos: int, section_key: str, value_key: str, data_type: str, value):
        if section_key not in self._raw or value_key not in self._raw[section_key]:
            _LOGGER.warning(f"Section '{section_key}' or value key '{value_key}' not found in raw data: {self._raw.keys()}")
        else:
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


