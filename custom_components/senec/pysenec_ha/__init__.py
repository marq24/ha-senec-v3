import asyncio
import base64
# required to patch the CookieJar of aiohttp - thanks for nothing!
import contextlib
import logging
from datetime import datetime
from http.cookies import BaseCookie, SimpleCookie, Morsel
from time import time
from typing import Union, cast

import aiohttp
import xmltodict
from aiohttp import ClientResponseError, ClientConnectorError
from aiohttp.helpers import is_ip_address
from dateutil.relativedelta import relativedelta
from orjson import JSONDecodeError
from packaging import version
from yarl import URL

from custom_components.senec.const import (
    QUERY_BMS_KEY,
    QUERY_FANDATA_KEY,
    QUERY_WALLBOX_KEY,
    QUERY_WALLBOX_APPAPI_KEY,
    QUERY_SOCKETS_KEY,
    QUERY_SPARE_CAPACITY_KEY,
    QUERY_PEAK_SHAVING_KEY,
    IGNORE_SYSTEM_STATE_KEY,
    CONF_APP_TOKEN,
    CONF_APP_SYSTEMID,
    CONF_APP_WALLBOX_COUNT,
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

    LOCAL_WB_MODE_LOCKED,
    LOCAL_WB_MODE_SSGCM_3,
    LOCAL_WB_MODE_SSGCM_4,
    LOCAL_WB_MODE_FASTEST,
    LOCAL_WB_MODE_UNKNOWN,

    SGREADY_CONF_KEYS,
    SGREADY_MODES,
    SGREADY_CONFKEY_ENABLED,
    SENEC_ENERGY_FIELDS,
    SENEC_ENERGY_FIELDS_2408
)
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


class Senec:
    """Senec Home Battery Sensor"""
    _senec_a = base64.b64decode("c3RfaW5zdGFsbGF0ZXVy".encode('utf-8')).decode('utf-8')
    _senec_b = base64.b64decode("c3RfU2VuZWNJbnN0YWxs".encode('utf-8')).decode('utf-8')

    def __init__(self, host, use_https, web_session, lang: str = "en", options: dict = None):
        _LOGGER.info(f"restarting Senec lala.cgi integration... for host: '{host}' with options: {options}")
        self._lang = lang
        self._QUERY_STATS = True
        if options is not None and QUERY_BMS_KEY in options:
            self._QUERY_BMS = options[QUERY_BMS_KEY]
        else:
            self._QUERY_BMS = False

        if options is not None and QUERY_WALLBOX_KEY in options:
            self._QUERY_WALLBOX = options[QUERY_WALLBOX_KEY]
        else:
            self._QUERY_WALLBOX = False

        # do we need some additional information for our wallbox (that are only available via the app-api!
        if options is not None and QUERY_WALLBOX_APPAPI_KEY in options:
            self._QUERY_WALLBOX_APPAPI = options[QUERY_WALLBOX_APPAPI_KEY]
        else:
            self._QUERY_WALLBOX_APPAPI = False

        if options is not None and QUERY_FANDATA_KEY in options:
            self._QUERY_FANDATA = options[QUERY_FANDATA_KEY]
        else:
            self._QUERY_FANDATA = False

        if options is not None and QUERY_SOCKETS_KEY in options:
            self._QUERY_SOCKETSDATA = options[QUERY_SOCKETS_KEY]
        else:
            self._QUERY_SOCKETSDATA = False

        if options is not None and IGNORE_SYSTEM_STATE_KEY in options:
            self._IGNORE_SYSTEM_STATUS = options[IGNORE_SYSTEM_STATE_KEY]
        else:
            self._IGNORE_SYSTEM_STATUS = False

        self.host = host
        self.web_session: aiohttp.websession = web_session

        if use_https:
            self.url = f"https://{host}/lala.cgi"
        else:
            self.url = f"http://{host}/lala.cgi"

        # evil HACK - since SENEC does not switch the property fast enough...
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

        try:
            asyncio.create_task(self.update_version())
        except Exception as exc:
            _LOGGER.debug(f"Exception while try to call 'self.update_version()': {exc}")

        IntBridge.lala_cgi = self
        if IntBridge.avail():
            # ok mein-senec-web is already existing...
            if self._QUERY_WALLBOX_APPAPI:
                IntBridge.app_api._QUERY_WALLBOX = True
                # ok let's force an UPDATE of the WEB-API
                _LOGGER.debug("force refresh of wallbox-data via app-api...")
                try:
                    asyncio.create_task(IntBridge.app_api.update())
                except Exception as exc:
                    _LOGGER.debug(f"Exception while try to call 'IntBridge.app_api.update': {exc}")

    @property
    def device_id(self) -> str:
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
        value = self._raw_version[SENEC_SECTION_FACTORY]["SYS_TYPE"]
        return SYSTEM_TYPE_NAME.get(value, "UNKNOWN")

    @property
    def device_type_internal(self) -> str:
        return self._raw_version[SENEC_SECTION_FACTORY]["SYS_TYPE"]

    @property
    def batt_type(self) -> str:
        value = self._raw_version[SENEC_SECTION_BAT1]["TYPE"]
        return BATT_TYPE_NAME.get(value, "UNKNOWN")

    async def update_version(self):
        # we do not expect that the version info will update in the next 60 minutes...
        if self._last_version_update + 3600 < time():
            await  self.read_version()

    async def read_version(self):
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
            SENEC_SECTION_STATISTIC: {}
        }

        async with self.web_session.post(self.url, json=form, ssl=False) as res:
            try:
                res.raise_for_status()
                self._raw_version = parse(await res.json())
                self._last_version_update = time()
            except JSONDecodeError as exc:
                _LOGGER.warning(f"JSONDecodeError while 'await res.json()' {exc}")

    @property
    def system_state(self) -> str:
        """
        Textual descritpion of energy status

        """
        value = self._raw[SENEC_SECTION_ENERGY]["STAT_STATE"]
        if self._lang in SYSTEM_STATE_NAME:
            return SYSTEM_STATE_NAME[self._lang].get(value, "UNKNOWN")
        else:
            return SYSTEM_STATE_NAME["en"].get(value, "UNKNOWN")

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
        return self._raw[SENEC_SECTION_ENERGY]["GUI_BAT_DATA_FUEL_CHARGE"]

    @property
    def battery_charge_power(self) -> float:
        """
        Current battery charging power (W)
        """
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
        return self._raw[SENEC_SECTION_ENERGY]["GUI_BAT_DATA_POWER"]

    @property
    def battery_state_current(self) -> float:
        return self._raw[SENEC_SECTION_ENERGY]["GUI_BAT_DATA_CURRENT"]

    @property
    def battery_state_voltage(self) -> float:
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
        value = self._raw[SENEC_SECTION_ENERGY]["GUI_GRID_POW"]
        if value > 0:
            return value
        return 0

    @property
    def grid_exported_power(self) -> float:
        """
        Current power exported to grid (W)
        """
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
        return self._raw[SENEC_SECTION_TEMPMEASURE]["BATTERY_TEMP"]

    @property
    def case_temp(self) -> float:
        """
        Current case temperature
        """
        return self._raw[SENEC_SECTION_TEMPMEASURE]["CASE_TEMP"]

    @property
    def mcu_temp(self) -> float:
        """
        Current controller temperature
        """
        return self._raw[SENEC_SECTION_TEMPMEASURE]["MCU_TEMP"]

    @property
    def solar_mpp1_potential(self) -> float:
        return self._raw[SENEC_SECTION_PV1]["MPP_VOL"][0]

    @property
    def solar_mpp1_current(self) -> float:
        return self._raw[SENEC_SECTION_PV1]["MPP_CUR"][0]

    @property
    def solar_mpp1_power(self) -> float:
        return self._raw[SENEC_SECTION_PV1]["MPP_POWER"][0]

    @property
    def solar_mpp2_potential(self) -> float:
        return self._raw[SENEC_SECTION_PV1]["MPP_VOL"][1]

    @property
    def solar_mpp2_current(self) -> float:
        return self._raw[SENEC_SECTION_PV1]["MPP_CUR"][1]

    @property
    def solar_mpp2_power(self) -> float:
        return self._raw[SENEC_SECTION_PV1]["MPP_POWER"][1]

    @property
    def solar_mpp3_potential(self) -> float:
        return self._raw[SENEC_SECTION_PV1]["MPP_VOL"][2]

    @property
    def solar_mpp3_current(self) -> float:
        return self._raw[SENEC_SECTION_PV1]["MPP_CUR"][2]

    @property
    def solar_mpp3_power(self) -> float:
        return self._raw[SENEC_SECTION_PV1]["MPP_POWER"][2]

    @property
    def enfluri_net_freq(self) -> float:
        return self._raw[SENEC_SECTION_PM1OBJ1]["FREQ"]

    @property
    def enfluri_net_potential_p1(self) -> float:
        return self._raw[SENEC_SECTION_PM1OBJ1]["U_AC"][0]

    @property
    def enfluri_net_potential_p2(self) -> float:
        return self._raw[SENEC_SECTION_PM1OBJ1]["U_AC"][1]

    @property
    def enfluri_net_potential_p3(self) -> float:
        return self._raw[SENEC_SECTION_PM1OBJ1]["U_AC"][2]

    @property
    def enfluri_net_current_p1(self) -> float:
        return self._raw[SENEC_SECTION_PM1OBJ1]["I_AC"][0]

    @property
    def enfluri_net_current_p2(self) -> float:
        return self._raw[SENEC_SECTION_PM1OBJ1]["I_AC"][1]

    @property
    def enfluri_net_current_p3(self) -> float:
        return self._raw[SENEC_SECTION_PM1OBJ1]["I_AC"][2]

    @property
    def enfluri_net_power_p1(self) -> float:
        return self._raw[SENEC_SECTION_PM1OBJ1]["P_AC"][0]

    @property
    def enfluri_net_power_p2(self) -> float:
        return self._raw[SENEC_SECTION_PM1OBJ1]["P_AC"][1]

    @property
    def enfluri_net_power_p3(self) -> float:
        return self._raw[SENEC_SECTION_PM1OBJ1]["P_AC"][2]

    @property
    def enfluri_net_power_total(self) -> float:
        return self._raw[SENEC_SECTION_PM1OBJ1]["P_TOTAL"]

    @property
    def enfluri_usage_freq(self) -> float:
        return self._raw[SENEC_SECTION_PM1OBJ2]["FREQ"]

    @property
    def enfluri_usage_potential_p1(self) -> float:
        return self._raw[SENEC_SECTION_PM1OBJ2]["U_AC"][0]

    @property
    def enfluri_usage_potential_p2(self) -> float:
        return self._raw[SENEC_SECTION_PM1OBJ2]["U_AC"][1]

    @property
    def enfluri_usage_potential_p3(self) -> float:
        return self._raw[SENEC_SECTION_PM1OBJ2]["U_AC"][2]

    @property
    def enfluri_usage_current_p1(self) -> float:
        return self._raw[SENEC_SECTION_PM1OBJ2]["I_AC"][0]

    @property
    def enfluri_usage_current_p2(self) -> float:
        return self._raw[SENEC_SECTION_PM1OBJ2]["I_AC"][1]

    @property
    def enfluri_usage_current_p3(self) -> float:
        return self._raw[SENEC_SECTION_PM1OBJ2]["I_AC"][2]

    @property
    def enfluri_usage_power_p1(self) -> float:
        return self._raw[SENEC_SECTION_PM1OBJ2]["P_AC"][0]

    @property
    def enfluri_usage_power_p2(self) -> float:
        return self._raw[SENEC_SECTION_PM1OBJ2]["P_AC"][1]

    @property
    def enfluri_usage_power_p3(self) -> float:
        return self._raw[SENEC_SECTION_PM1OBJ2]["P_AC"][2]

    @property
    def enfluri_usage_power_total(self) -> float:
        return self._raw[SENEC_SECTION_PM1OBJ2]["P_TOTAL"]

    def is_battery_empty(self) -> bool:
        # 15: "BATTERY EMPTY",
        bat_state_is_empty = self._raw[SENEC_SECTION_ENERGY]["STAT_STATE"] == 15
        bat_percent_is_zero = self._raw[SENEC_SECTION_ENERGY]["GUI_BAT_DATA_FUEL_CHARGE"] == 0
        return bat_state_is_empty or bat_percent_is_zero

    def is_system_state_charging(self) -> bool:
        return self._raw[SENEC_SECTION_ENERGY]["STAT_STATE"] in SYSTEM_STATUS_CHARGE

    def is_system_state_discharging(self) -> bool:
        return self._raw[SENEC_SECTION_ENERGY]["STAT_STATE"] in SYSTEM_STATUS_DISCHARGE

    @property
    def bms_cell_temp_a1(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_A"][0]

    @property
    def bms_cell_temp_a2(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_A"][1]

    @property
    def bms_cell_temp_a3(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_A"][2]

    @property
    def bms_cell_temp_a4(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_A"][3]

    @property
    def bms_cell_temp_a5(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_A"][4]

    @property
    def bms_cell_temp_a6(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_A"][5]

    @property
    def bms_cell_temp_b1(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_B"][0]

    @property
    def bms_cell_temp_b2(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_B"][1]

    @property
    def bms_cell_temp_b3(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_B"][2]

    @property
    def bms_cell_temp_b4(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_B"][3]

    @property
    def bms_cell_temp_b5(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_B"][4]

    @property
    def bms_cell_temp_b6(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_B"][5]

    @property
    def bms_cell_temp_c1(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_C"][0]

    @property
    def bms_cell_temp_c2(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_C"][1]

    @property
    def bms_cell_temp_c3(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_C"][2]

    @property
    def bms_cell_temp_c4(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_C"][3]

    @property
    def bms_cell_temp_c5(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_C"][4]

    @property
    def bms_cell_temp_c6(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_C"][5]

    @property
    def bms_cell_temp_d1(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_D"][0]

    @property
    def bms_cell_temp_d2(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_D"][1]

    @property
    def bms_cell_temp_d3(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_D"][2]

    @property
    def bms_cell_temp_d4(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_D"][3]

    @property
    def bms_cell_temp_d5(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_D"][4]

    @property
    def bms_cell_temp_d6(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_D" in self._raw["BMS"]:
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
    def _bms_modules_configured(self) -> int:
        if self._raw is not None and "BMS" in self._raw and "MODULES_CONFIGURED" in self._raw["BMS"]:
            return int(self._raw["BMS"]["MODULES_CONFIGURED"])
        else:
            return 0

    @property
    def bms_soc_a(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "SOC" in self._raw["BMS"] and (
                self._bms_modules_configured > 0 or len(self._raw["BMS"]["SOC"]) > 0):
            return self._raw["BMS"]["SOC"][0]

    @property
    def bms_soc_b(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "SOC" in self._raw["BMS"] and (
                self._bms_modules_configured > 1 or len(self._raw["BMS"]["SOC"]) > 1):
            return self._raw["BMS"]["SOC"][1]

    @property
    def bms_soc_c(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "SOC" in self._raw["BMS"] and (
                self._bms_modules_configured > 2 or len(self._raw["BMS"]["SOC"]) > 2):
            return self._raw["BMS"]["SOC"][2]

    @property
    def bms_soc_d(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "SOC" in self._raw["BMS"] and (
                self._bms_modules_configured > 3 or len(self._raw["BMS"]["SOC"]) > 3):
            return self._raw["BMS"]["SOC"][3]

    @property
    def bms_soh_a(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "SOH" in self._raw["BMS"] and (
                self._bms_modules_configured > 0 or len(self._raw["BMS"]["SOH"]) > 0):
            return self._raw["BMS"]["SOH"][0]

    @property
    def bms_soh_b(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "SOH" in self._raw["BMS"] and (
                self._bms_modules_configured > 1 or len(self._raw["BMS"]["SOH"]) > 1):
            return self._raw["BMS"]["SOH"][1]

    @property
    def bms_soh_c(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "SOH" in self._raw["BMS"] and (
                self._bms_modules_configured > 2 or len(self._raw["BMS"]["SOH"]) > 2):
            return self._raw["BMS"]["SOH"][2]

    @property
    def bms_soh_d(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "SOH" in self._raw["BMS"] and (
                self._bms_modules_configured > 3 or len(self._raw["BMS"]["SOH"]) > 3):
            return self._raw["BMS"]["SOH"][3]

    @property
    def bms_voltage_a(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "VOLTAGE" in self._raw["BMS"] and (
                self._bms_modules_configured > 0 or len(self._raw["BMS"]["VOLTAGE"]) > 0):
            return self._raw["BMS"]["VOLTAGE"][0]

    @property
    def bms_voltage_b(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "VOLTAGE" in self._raw["BMS"] and (
                self._bms_modules_configured > 1 or len(self._raw["BMS"]["VOLTAGE"]) > 1):
            return self._raw["BMS"]["VOLTAGE"][1]

    @property
    def bms_voltage_c(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "VOLTAGE" in self._raw["BMS"] and (
                self._bms_modules_configured > 2 or len(self._raw["BMS"]["VOLTAGE"]) > 2):
            return self._raw["BMS"]["VOLTAGE"][2]

    @property
    def bms_voltage_d(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "VOLTAGE" in self._raw["BMS"] and (
                self._bms_modules_configured > 3 or len(self._raw["BMS"]["VOLTAGE"]) > 3):
            return self._raw["BMS"]["VOLTAGE"][3]

    @property
    def bms_current_a(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CURRENT" in self._raw["BMS"] and (
                self._bms_modules_configured > 0 or len(self._raw["BMS"]["CURRENT"]) > 0):
            return self._raw["BMS"]["CURRENT"][0]

    @property
    def bms_current_b(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CURRENT" in self._raw["BMS"] and (
                self._bms_modules_configured > 1 or len(self._raw["BMS"]["CURRENT"]) > 1):
            return self._raw["BMS"]["CURRENT"][1]

    @property
    def bms_current_c(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CURRENT" in self._raw["BMS"] and (
                self._bms_modules_configured > 2 or len(self._raw["BMS"]["CURRENT"]) > 2):
            return self._raw["BMS"]["CURRENT"][2]

    @property
    def bms_current_d(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CURRENT" in self._raw["BMS"] and (
                self._bms_modules_configured > 3 or len(self._raw["BMS"]["CURRENT"]) > 3):
            return self._raw["BMS"]["CURRENT"][3]

    @property
    def bms_cycles_a(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CYCLES" in self._raw["BMS"] and (
                self._bms_modules_configured > 0 or len(self._raw["BMS"]["CYCLES"]) > 0):
            return self._raw["BMS"]["CYCLES"][0]

    @property
    def bms_cycles_b(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CYCLES" in self._raw["BMS"] and (
                self._bms_modules_configured > 1 or len(self._raw["BMS"]["CYCLES"]) > 1):
            return self._raw["BMS"]["CYCLES"][1]

    @property
    def bms_cycles_c(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CYCLES" in self._raw["BMS"] and (
                self._bms_modules_configured > 2 or len(self._raw["BMS"]["CYCLES"]) > 2):
            return self._raw["BMS"]["CYCLES"][2]

    @property
    def bms_cycles_d(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "CYCLES" in self._raw["BMS"] and (
                self._bms_modules_configured > 3 or len(self._raw["BMS"]["CYCLES"]) > 3):
            return self._raw["BMS"]["CYCLES"][3]

    @property
    def bms_fw_a(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "FW" in self._raw["BMS"] and (
                self._bms_modules_configured > 0 or len(self._raw["BMS"]["FW"]) > 0):
            return self._raw["BMS"]["FW"][0]

    @property
    def bms_fw_b(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "FW" in self._raw["BMS"] and (
                self._bms_modules_configured > 1 or len(self._raw["BMS"]["FW"]) > 1):
            return self._raw["BMS"]["FW"][1]

    @property
    def bms_fw_c(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "FW" in self._raw["BMS"] and (
                self._bms_modules_configured > 2 or len(self._raw["BMS"]["FW"]) > 2):
            return self._raw["BMS"]["FW"][2]

    @property
    def bms_fw_d(self) -> float:
        if self._raw is not None and "BMS" in self._raw and "FW" in self._raw["BMS"] and (
                self._bms_modules_configured > 3 or len(self._raw["BMS"]["FW"]) > 3):
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
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L1_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX] and "L2_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX] and "L3_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX]:
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
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L1_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX] and "L2_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX] and "L3_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX]:
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
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L1_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX] and "L2_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX] and "L3_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX]:
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
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "L1_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX] and "L2_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX] and "L3_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX]:
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

    async def update(self):
        await self.read_senec_lala_with_retry(retry=True)

    async def read_senec_lala_with_retry(self, retry: bool = False):
        try:
            await self.read_senec_lala()
        except ClientConnectorError as exc:
            _LOGGER.info(f"{exc}")
            if retry:
                await asyncio.sleep(5)
                await self.read_senec_lala_with_retry(retry=False)

    async def read_senec_lala(self):
        form = {
            SENEC_SECTION_TEMPMEASURE: {
                "BATTERY_TEMP": "",
                "CASE_TEMP": "",
                "MCU_TEMP": "",
            },
            SENEC_SECTION_PV1: {
                "POWER_RATIO": "",
                "POWER_RATIO_L1": "",
                "POWER_RATIO_L2": "",
                "POWER_RATIO_L3": "",
                "MPP_VOL": "",
                "MPP_CUR": "",
                "MPP_POWER": ""},
            SENEC_SECTION_PWR_UNIT: {"POWER_L1": "", "POWER_L2": "", "POWER_L3": ""},
            SENEC_SECTION_PM1OBJ1: {"FREQ": "", "U_AC": "", "I_AC": "", "P_AC": "", "P_TOTAL": ""},
            SENEC_SECTION_PM1OBJ2: {"FREQ": "", "U_AC": "", "I_AC": "", "P_AC": "", "P_TOTAL": ""},
        }

        if self.is_2408_or_higher():
            form.update({SENEC_SECTION_ENERGY: SENEC_ENERGY_FIELDS_2408})
            form.update({SENEC_SECTION_LOG: {"USER_LEVEL": ""}})
        else:
            form.update({SENEC_SECTION_ENERGY: SENEC_ENERGY_FIELDS})

        if self._QUERY_STATS:
            form.update({SENEC_SECTION_STATISTIC: {}})

        if self._QUERY_FANDATA:
            form.update({SENEC_SECTION_FAN_SPEED: {}})

        if self._QUERY_SOCKETSDATA:
            form.update({SENEC_SECTION_SOCKETS: {}})

        if self._QUERY_BMS:
            form.update({SENEC_SECTION_BMS: {
                "CELL_TEMPERATURES_MODULE_A": "",
                "CELL_TEMPERATURES_MODULE_B": "",
                "CELL_TEMPERATURES_MODULE_C": "",
                "CELL_TEMPERATURES_MODULE_D": "",
                "CELL_VOLTAGES_MODULE_A": "",
                "CELL_VOLTAGES_MODULE_B": "",
                "CELL_VOLTAGES_MODULE_C": "",
                "CELL_VOLTAGES_MODULE_D": "",
                "CURRENT": "",
                "VOLTAGE": "",
                "SOC": "",
                "SOH": "",
                "CYCLES": "",
                "MODULES_CONFIGURED": ""}
            })

        if self._QUERY_WALLBOX:
            form.update({SENEC_SECTION_WALLBOX: {
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
                "PROHIBIT_USAGE": ""}
            })

        async with self.web_session.post(self.url, json=form, ssl=False) as res:
            try:
                res.raise_for_status()
                data = await res.json()
                self._raw = parse(data)
            except JSONDecodeError as exc:
                _LOGGER.warning(f"JSONDecodeError while 'await res.json()' {exc}")

    async def read_all_fields(self) -> []:
        async with self.web_session.post(self.url, json={"DEBUG": {"SECTIONS": ""}}, ssl=False) as res:
            try:
                res.raise_for_status()
                data = await res.json()
                obj = parse(data)
                form = {}
                for section in obj["DEBUG"]["SECTIONS"]:
                    form[section] = {}
            except JSONDecodeError as exc:
                _LOGGER.warning(f"JSONDecodeError while 'await res.json()' {exc}")

        async with self.web_session.post(self.url, json=form, ssl=False) as res:
            try:
                res.raise_for_status()
                data = await res.json()
                return parse(data)
            except JSONDecodeError as exc:
                _LOGGER.warning(f"JSONDecodeError while 'await res.json()' {exc}")

        return None


    ## LADEN...
    ## {"ENERGY":{"SAFE_CHARGE_FORCE":"u8_01","SAFE_CHARGE_PROHIBIT":"","SAFE_CHARGE_RUNNING":"","LI_STORAGE_MODE_START":"","LI_STORAGE_MODE_STOP":"","LI_STORAGE_MODE_RUNNING":""}}

    ## Freigeben...
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
            # if it just has been switched on/off we provide a FAKE value for 5 sec...
            # since senec unit do not react 'instant' on some requests...
            if self._OVERWRITES["SAFE_CHARGE_RUNNING"]["TS"] + 5 > time():
                return self._OVERWRITES["SAFE_CHARGE_RUNNING"]["VALUE"]
            else:
                return self._raw[SENEC_SECTION_ENERGY]["SAFE_CHARGE_RUNNING"] == 1

    async def switch_safe_charge(self, value: bool):
        self._OVERWRITES["SAFE_CHARGE_RUNNING"].update({"VALUE": value})
        self._OVERWRITES["SAFE_CHARGE_RUNNING"].update({"TS": time()})
        post_data = {}
        if (value):
            self._raw[SENEC_SECTION_ENERGY]["SAFE_CHARGE_RUNNING"] = 1
            post_data = {SENEC_SECTION_ENERGY: {"SAFE_CHARGE_FORCE": "u8_01", "SAFE_CHARGE_PROHIBIT": "",
                                                "SAFE_CHARGE_RUNNING": "",
                                                "LI_STORAGE_MODE_START": "", "LI_STORAGE_MODE_STOP": "",
                                                "LI_STORAGE_MODE_RUNNING": ""}}
        else:
            self._raw[SENEC_SECTION_ENERGY]["SAFE_CHARGE_RUNNING"] = 0
            post_data = {SENEC_SECTION_ENERGY: {"SAFE_CHARGE_FORCE": "", "SAFE_CHARGE_PROHIBIT": "u8_01",
                                                "SAFE_CHARGE_RUNNING": "",
                                                "LI_STORAGE_MODE_START": "", "LI_STORAGE_MODE_STOP": "",
                                                "LI_STORAGE_MODE_RUNNING": ""}}

        await self.write(post_data)

    @property
    def li_storage_mode(self) -> bool:
        if self._raw is not None:
            # if it just has been switched on/off we provide a FAKE value for 5 sec...
            # since senec unit do not react 'instant' on some requests...
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

        await self.write(post_data)


    async def _trigger_button(self, key: str, payload: str):
        return await getattr(self, 'trigger_' + key)(payload)

    async def is_2408_or_higher_async(self) -> bool:
        if self._last_version_update == 0:
            await self.read_version()
        return self.is_2408_or_higher()

    def is_2408_or_higher(self) -> bool:
        if self._raw_version is not None and \
                SENEC_SECTION_SYS_UPDATE in self._raw_version and \
                "NPU_IMAGE_VERSION" in self._raw_version[SENEC_SECTION_SYS_UPDATE]:
            return int(self._raw_version[SENEC_SECTION_SYS_UPDATE]["NPU_IMAGE_VERSION"]) >= 2408
        return False

    async def _senec_local_access_start(self):
        if await self.is_2408_or_higher_async():
            if (self._raw is not None and
                    SENEC_SECTION_LOG in self._raw and
                    "USER_LEVEL" in self._raw[SENEC_SECTION_LOG] and
                    self._raw[SENEC_SECTION_LOG]["USER_LEVEL"] < 2):
                login_data = {SENEC_SECTION_LOG: {"USER_LEVEL": "", "USERNAME": self._senec_a, "PASSWORD": self._senec_b, "LOG_IN_BUTT": "u8_01"}}
                await self.write_senec_v31(login_data)
                await asyncio.sleep(2)
                await self.update()

    async def _senec_local_access_stop(self):
        if await self.is_2408_or_higher_async():
            if (self._raw is not None and
                    SENEC_SECTION_LOG in self._raw and
                    "USER_LEVEL" in self._raw[SENEC_SECTION_LOG] and
                    self._raw[SENEC_SECTION_LOG]["USER_LEVEL"] > 1):
                login_data = {SENEC_SECTION_LOG: {"LOG_OUT_BUTT": "u8_01"}}
                await self.write_senec_v31(login_data)
                await asyncio.sleep(2)
                await self.update()

    async def trigger_system_reboot(self, payload:str):
        if await self.is_2408_or_higher_async():
            if self._last_system_reset + 300 < time():
                data = {"SYS_UPDATE": {"BOOT_REPORT_SUCCESS": "", "USER_REBOOT_DEVICE": "u8_01"}}
                await self.write_senec_v31(data)
                self._last_system_reset = time()
            else:
                _LOGGER.debug(f"Last Reset too recent...")

    async def trigger_cap_test_start(self):
        if await self.is_2408_or_higher_async():
            if (self._raw is not None and "GUI_CAP_TEST_STATE" in self._raw[SENEC_SECTION_ENERGY] and
                    self._raw[SENEC_SECTION_ENERGY]["GUI_CAP_TEST_STATE"] == 0):
                await self._senec_local_access_start()
                # ok we set the new state...
                data = {SENEC_SECTION_ENERGY: { "GUI_CAP_TEST_START": "u8_01"}}
                await self.write_senec_v31(data)
                await self._senec_local_access_stop()
            else:
                _LOGGER.debug(f"ENERGY GUI_CAP_TEST_STATE unknown or not OFF")

    async def trigger_cap_test_stop(self):
        if await self.is_2408_or_higher_async():
            if (self._raw is not None and "GUI_CAP_TEST_STATE" in self._raw[SENEC_SECTION_ENERGY] and
                self._raw[SENEC_SECTION_ENERGY]["GUI_CAP_TEST_STATE"] == 1):
                await self._senec_local_access_start()
                # ok we set the new state...
                data = {SENEC_SECTION_ENERGY: { "GUI_CAP_TEST_STOP": "u8_01"}}
                await self.write_senec_v31(data)
                await self._senec_local_access_stop()
            else:
                _LOGGER.debug(f"ENERGY GUI_CAP_TEST_STATE unknown or not ON")

    # trigger_load_test_start & trigger_load_test_stop
    # are not really working...
    async def trigger_load_test_start(self, requested_watts: int):
        if await self.is_2408_or_higher_async():
            if (self._raw is not None and "GUI_TEST_CHARGE_STAT" in self._raw[SENEC_SECTION_ENERGY] and
                    self._raw[SENEC_SECTION_ENERGY]["GUI_TEST_CHARGE_STAT"] == 0):
                await self._senec_local_access_start()
                # ok we set the new state...
                wat_val = f"fl_{util.get_float_as_IEEE754_hex(float(float(requested_watts)/-3))}"
                data = {SENEC_SECTION_ENERGY: { "GUI_TEST_CHARGE_STAT": "",
                                                "GRID_POWER_OFFSET": [wat_val, wat_val, wat_val],
                                                "TEST_CHARGE_ENABLE": "u8_01"} }
                await self.write_senec_v31(data)
                # as soon as we will logout, the test_load will be cancled...
                #await self.senec_local_access_stop()
            else:
                _LOGGER.debug(f"ENERGY GUI_TEST_CHARGE_STAT unknown or not OFF")

    async def trigger_load_test_stop(self):
        if await self.is_2408_or_higher_async():
            if (self._raw is not None and "GUI_TEST_CHARGE_STAT" in self._raw[SENEC_SECTION_ENERGY] and
                    self._raw[SENEC_SECTION_ENERGY]["GUI_TEST_CHARGE_STAT"] == 1):
                await self._senec_local_access_start()
                # ok we set the new state...
                wat_val = f"fl_{util.get_float_as_IEEE754_hex(float(0))}"
                data = {SENEC_SECTION_ENERGY: { "GUI_TEST_CHARGE_STAT": "",
                                                "GRID_POWER_OFFSET": [wat_val, wat_val, wat_val],
                                                "TEST_CHARGE_ENABLE": "u8_00"} }
                await self.write_senec_v31(data)
                # as soon as we will logout, the test_load will be cancled...
                #await self.senec_local_access_stop()
            else:
                _LOGGER.debug(f"ENERGY GUI_TEST_CHARGE_STAT unknown or not OFF")







    @property
    def wallbox_allow_intercharge(self) -> bool:
        # please note this is not ARRAY data - so we code it here again...
        if self._raw is not None and SENEC_SECTION_WALLBOX in self._raw and "ALLOW_INTERCHARGE" in self._raw[
            SENEC_SECTION_WALLBOX]:
            # if it just has been switched on/off we provide a FAKE value for 5 sec...
            # since senec unit do not react 'instant' on some requests...
            if self._OVERWRITES[SENEC_SECTION_WALLBOX + "_ALLOW_INTERCHARGE"]["TS"] + 5 > time():
                return self._OVERWRITES[SENEC_SECTION_WALLBOX + "_ALLOW_INTERCHARGE"]["VALUE"]
            else:
                return self._raw[SENEC_SECTION_WALLBOX]["ALLOW_INTERCHARGE"] == 1

    async def switch_wallbox_allow_intercharge(self, value: bool, sync: bool = True):
        # please note this is not ARRAY data - so we code it here again...
        self._OVERWRITES[SENEC_SECTION_WALLBOX + "_ALLOW_INTERCHARGE"].update({"VALUE": value})
        self._OVERWRITES[SENEC_SECTION_WALLBOX + "_ALLOW_INTERCHARGE"].update({"TS": time()})
        post_data = {}
        if (value):
            self._raw[SENEC_SECTION_WALLBOX]["ALLOW_INTERCHARGE"] = 1
            post_data = {SENEC_SECTION_WALLBOX: {"ALLOW_INTERCHARGE": "u8_01"}}
        else:
            self._raw[SENEC_SECTION_WALLBOX]["ALLOW_INTERCHARGE"] = 0
            post_data = {SENEC_SECTION_WALLBOX: {"ALLOW_INTERCHARGE": "u8_00"}}

        await self.write(post_data)

        if sync and IntBridge.avail():
            # ALLOW_INTERCHARGE seams to be a wallbox-number independent setting... so we need to push
            # this to all 4 possible wallboxes...
            await IntBridge.app_api.app_set_allow_intercharge_all(value_to_set=value, sync=False)

    async def switch(self, switch_key, value):
        return await getattr(self, 'switch_' + str(switch_key))(value)

    """SWITCH ARRAY FROM HERE..."""

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
    # ever reason 03)...
    # async def switch_array_smart_charge_active(self, pos: int, value: int):
    #    await self.set_nva_post(SENEC_SECTION_WALLBOX, "SMART_CHARGE_ACTIVE", pos, 4, "u8", value)

    @property
    def wallbox_prohibit_usage(self) -> [int]:
        return self.read_array_data(SENEC_SECTION_WALLBOX, "PROHIBIT_USAGE")

    # async def switch_array_wallbox_prohibit_usage(self, pos: int, value: bool, sync: bool = True):
    #     mode = None
    #     if value:
    #         mode = APP_API_WEB_MODE_LOCKED
    #     else:
    #         mode = APP_API_WEB_MODE_SSGCM
    #         if IntBridge.app_api._app_last_wallbox_modes_lc[pos] is not None:
    #             mode = IntBridge.app_api._app_last_wallbox_modes_lc[pos]
    #         elif IntBridge.app_api._app_raw_wallbox[pos] is not None:
    #             pass
    #
    #     await self._set_wallbox_mode_post(pos=pos, mode_to_set_in_lc=mode)
    #     if sync and IntBridge.avail():
    #         await IntBridge.app_api.app_set_wallbox_mode(mode_to_set_in_lc=mode, wallbox_num=(pos + 1), sync=False)

    def read_array_data(self, section_key: str, array_values_key) -> []:
        if self._raw is not None and section_key in self._raw and array_values_key in self._raw[section_key]:
            if self._OVERWRITES[section_key + "_" + array_values_key]["TS"] + 5 > time():
                return self._OVERWRITES[section_key + "_" + array_values_key]["VALUE"]
            else:
                return self._raw[section_key][array_values_key]

    async def switch_array(self, switch_array_key, array_pos, value):
        return await getattr(self, 'switch_array_' + str(switch_array_key))(array_pos, value)

    """NUMBER ARRAY VALUES FROM HERE..."""

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
        if IntBridge.avail() and IntBridge.app_api._app_raw_wallbox[0] is not None:
            wb_data = IntBridge.app_api._app_raw_wallbox[0]
            if "maxPossibleChargingCurrentInA" in wb_data:
                if "minPossibleChargingCurrentInA" in wb_data:
                    return [float(wb_data["minPossibleChargingCurrentInA"]),
                            float(wb_data["maxPossibleChargingCurrentInA"])]
        return None

    @property
    def wallbox_2_set_icmax_extrema(self) -> [float]:
        if IntBridge.avail() and IntBridge.app_api._app_raw_wallbox[1] is not None:
            wb_data = IntBridge.app_api._app_raw_wallbox[1]
            if "maxPossibleChargingCurrentInA" in wb_data:
                if "minPossibleChargingCurrentInA" in wb_data:
                    return [float(wb_data["minPossibleChargingCurrentInA"]),
                            float(wb_data["maxPossibleChargingCurrentInA"])]
        return None

    @property
    def wallbox_3_set_icmax_extrema(self) -> [float]:
        if IntBridge.avail() and IntBridge.app_api._app_raw_wallbox[2] is not None:
            wb_data = IntBridge.app_api._app_raw_wallbox[2]
            if "maxPossibleChargingCurrentInA" in wb_data:
                if "minPossibleChargingCurrentInA" in wb_data:
                    return [float(wb_data["minPossibleChargingCurrentInA"]),
                            float(wb_data["maxPossibleChargingCurrentInA"])]
        return None

    @property
    def wallbox_4_set_icmax_extrema(self) -> [float]:
        if IntBridge.avail() and IntBridge.app_api._app_raw_wallbox[3] is not None:
            wb_data = IntBridge.app_api._app_raw_wallbox[3]
            if "maxPossibleChargingCurrentInA" in wb_data:
                if "minPossibleChargingCurrentInA" in wb_data:
                    return [float(wb_data["minPossibleChargingCurrentInA"]),
                            float(wb_data["maxPossibleChargingCurrentInA"])]
        return None

    @property
    def wallbox_set_icmax(self) -> [float]:
        return self.read_array_data(SENEC_SECTION_WALLBOX, "SET_ICMAX")

    async def set_nva_wallbox_set_icmax(self, pos: int, value: float, sync: bool = True, verify_state: bool = True):
        if verify_state:
            if IntBridge.avail():
                local_mode = IntBridge.app_api.app_get_local_wallbox_mode_from_api_values(pos)
            else:
                local_mode = "no-bridge-avail"
        else:
            local_mode = LOCAL_WB_MODE_SSGCM_3

        if local_mode == LOCAL_WB_MODE_SSGCM_3:  # or local_mode == LOCAL_WB_MODE_SSGCM_4:
            await self.set_multi_post(4, pos,
                                      SENEC_SECTION_WALLBOX, "SET_ICMAX", "fl", value,
                                      SENEC_SECTION_WALLBOX, "MIN_CHARGING_CURRENT", "fl", value)

            if sync and IntBridge.avail():
                await IntBridge.app_api.app_set_wallbox_icmax(value_to_set=value, wallbox_num=(pos + 1), sync=False)
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
        if IntBridge.avail():
            return IntBridge.app_api.app_get_local_wallbox_mode_from_api_values(0)
        return LOCAL_WB_MODE_UNKNOWN

    async def set_string_value_wallbox_1_mode(self, value: str):
        await self._set_wallbox_mode_post(0, value)
        if IntBridge.avail():
            await IntBridge.app_api.app_set_wallbox_mode(local_mode_to_set=value, wallbox_num=1, sync=False)

    @property
    def wallbox_2_mode(self) -> str:
        if IntBridge.avail():
            return IntBridge.app_api.app_get_local_wallbox_mode_from_api_values(1)
        return LOCAL_WB_MODE_UNKNOWN

    async def set_string_value_wallbox_2_mode(self, value: str):
        await self._set_wallbox_mode_post(1, value)
        if IntBridge.avail():
            await IntBridge.app_api.app_set_wallbox_mode(local_mode_to_set=value, wallbox_num=2, sync=False)

    @property
    def wallbox_3_mode(self) -> str:
        if IntBridge.avail():
            return IntBridge.app_api.app_get_local_wallbox_mode_from_api_values(2)
        return LOCAL_WB_MODE_UNKNOWN

    async def set_string_value_wallbox_3_mode(self, value: str):
        await self._set_wallbox_mode_post(2, value)
        if IntBridge.avail():
            await IntBridge.app_api.app_set_wallbox_mode(local_mode_to_set=value, wallbox_num=3, sync=False)

    @property
    def wallbox_4_mode(self) -> str:
        if IntBridge.avail():
            return IntBridge.app_api.app_get_local_wallbox_mode_from_api_values(3)
        return LOCAL_WB_MODE_UNKNOWN

    async def set_string_value_wallbox_4_mode(self, value: str):
        await self._set_wallbox_mode_post(3, value)
        if IntBridge.avail():
            await IntBridge.app_api.app_set_wallbox_mode(local_mode_to_set=value, wallbox_num=4, sync=False)

    async def _set_wallbox_mode_post(self, pos: int, local_value: str):
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

    """NORMAL NUMBER HANDLING... currently no 'none-array' entities are implemented"""

    async def set_number_value(self, array_key: str, value: float):
        # this will cause a method not found exception...
        return await getattr(self, 'set_nv_' + str(array_key))(value)

    async def switch_array_post(self, section_key: str, value_key: str, pos: int, array_length: int, value: bool):
        post_data = {}
        self.prepare_post_data(post_data, array_length, pos, section_key, value_key, "u8", value=(1 if value else 0))
        await self.write(post_data)

    async def set_nva_post(self, section_key: str, value_key: str, pos: int, array_length: int, data_type: str, value):
        post_data = {}
        self.prepare_post_data(post_data, array_length, pos, section_key, value_key, data_type, value)
        await self.write(post_data)

    async def set_multi_post(self, array_length: int, pos: int,
                             section_key1: str, value_key1: str, data_type1: str, value1,
                             section_key2: str, value_key2: str, data_type2: str, value2
                             ):
        post_data = {}
        self.prepare_post_data(post_data, array_length, pos, section_key1, value_key1, data_type1, value1)
        self.prepare_post_data(post_data, array_length, pos, section_key2, value_key2, data_type2, value2)
        await self.write(post_data)

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

    async def write(self, data):
        await self.write_senec_v31(data)

    async def write_senec_v31(self, data):
        _LOGGER.debug(f"posting data (raw): {util.mask_map(data)}")
        async with self.web_session.post(self.url, json=data, ssl=False) as res:
            try:
                res.raise_for_status()
                self._raw_post = parse(await res.json())
                _LOGGER.debug(f"post result (already parsed): {util.mask_map(self._raw_post)}")
                return self._raw_post
            except Exception as exc:
                _LOGGER.warning(f"JSONDecodeError while 'await res.json()' {exc}")

class Inverter:
    """Senec Home Inverter addon"""

    def __init__(self, host, web_session):
        self.host = host
        self.web_session: aiohttp.websession = web_session
        self.url1 = f"http://{host}/all.xml"
        self.url2 = f"http://{host}/measurements.xml"
        self.url3 = f"http://{host}/versions.xml"
        self._version_infos = ''
        self._has_bdc = False

    async def update_version(self):
        await self.read_inverter_version()

    async def read_inverter_version(self):
        async with self.web_session.get(self.url3) as res:
            res.raise_for_status()
            txt = await res.text()
            self._raw_version = xmltodict.parse(txt, force_list=('Software',))
            last_dev = ''
            if self._raw_version is not None:
                if "root" in self._raw_version:
                    if "Device" in self._raw_version["root"]:
                        if "Versions" in self._raw_version["root"]["Device"]:
                            if "Software" in self._raw_version["root"]["Device"]["Versions"]:
                                a_dict = self._raw_version["root"]["Device"]["Versions"]["Software"]
                                if isinstance(a_dict, list):
                                    for a_entry in a_dict:
                                        if '@Name' in a_entry:
                                            a_dev = a_entry["@Device"]
                                            if (not self._has_bdc):
                                                self._has_bdc = a_dev == 'BDC'
                                            if (a_dev != last_dev):
                                                if (len(self._version_infos) > 0):
                                                    self._version_infos = self._version_infos + '\n'
                                                self._version_infos = self._version_infos + "[" + a_dev + "]:\t"
                                            else:
                                                if (len(self._version_infos) > 0):
                                                    self._version_infos = self._version_infos + '|'
                                            self._version_infos = self._version_infos + a_entry["@Name"] + ' v' + a_entry["@Version"]
                                            last_dev = a_dev
                                elif isinstance(a_dict, dict):
                                    for a_entry in a_dict.keys():
                                        if '@Name' in a_entry:
                                            a_dev = a_dict["@Device"]
                                            if (not self._has_bdc):
                                                self._has_bdc = a_dev == 'BDC'
                                            if (a_dev != last_dev):
                                                if (len(self._version_infos) > 0):
                                                    self._version_infos = self._version_infos + '\n'
                                                self._version_infos = self._version_infos + "[" + a_dev + "]:\t"
                                            else:
                                                if (len(self._version_infos) > 0):
                                                    self._version_infos = self._version_infos + '|'
                                            self._version_infos = self._version_infos + a_dict["@Name"] + ' v' + a_dict["@Version"]
                                            last_dev = a_dev

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
        async with self.web_session.get(f"{self.url2}?{datetime.now()}") as res:
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

    @property
    def ac_current(self) -> float:
        if (hasattr(self, '_ac_current')):
            return self._ac_current

    @property
    def ac_power(self) -> float:
        if (hasattr(self, '_ac_power')):
            return self._ac_power

    @property
    def ac_power_fast(self) -> float:
        if (hasattr(self, '_ac_power_fast')):
            return self._ac_power_fast

    @property
    def ac_frequency(self) -> float:
        if (hasattr(self, '_ac_frequency')):
            return self._ac_frequency

    @property
    def dc_voltage1(self) -> float:
        if (hasattr(self, '_dc_voltage1')):
            return self._dc_voltage1

    @property
    def dc_voltage2(self) -> float:
        if (hasattr(self, '_dc_voltage2')):
            return self._dc_voltage2

    @property
    def dc_current1(self) -> float:
        if (hasattr(self, '_dc_current1')):
            return self._dc_current1

    @property
    def bdc_bat_voltage(self) -> float:
        if (hasattr(self, '_bdc_bat_voltage')):
            return self._bdc_bat_voltage

    @property
    def bdc_bat_current(self) -> float:
        if (hasattr(self, '_bdc_bat_current')):
            return self._bdc_bat_current

    @property
    def bdc_bat_power(self) -> float:
        if (hasattr(self, '_bdc_bat_power')):
            return self._bdc_bat_power

    @property
    def bdc_link_voltage(self) -> float:
        if (hasattr(self, '_bdc_link_voltage')):
            return self._bdc_link_voltage

    @property
    def bdc_link_current(self) -> float:
        if (hasattr(self, '_bdc_link_current')):
            return self._bdc_link_current

    @property
    def bdc_link_power(self) -> float:
        if (hasattr(self, '_bdc_link_power')):
            return self._bdc_link_power

    @property
    def dc_current1(self) -> float:
        if (hasattr(self, '_dc_current1')):
            return self._dc_current1

    @property
    def dc_current2(self) -> float:
        if (hasattr(self, '_dc_current2')):
            return self._dc_current2

    @property
    def link_voltage(self) -> float:
        if (hasattr(self, '_link_voltage')):
            return self._link_voltage

    @property
    def gridpower(self) -> float:
        if (hasattr(self, '_gridpower')):
            return self._gridpower

    @property
    def gridconsumedpower(self) -> float:
        if (hasattr(self, '_gridconsumedpower')):
            return self._gridconsumedpower

    @property
    def gridinjectedpower(self) -> float:
        if (hasattr(self, '_gridinjectedpower')):
            return self._gridinjectedpower

    @property
    def ownconsumedpower(self) -> float:
        if (hasattr(self, '_ownconsumedpower')):
            return self._ownconsumedpower

    @property
    def derating(self) -> float:
        if (hasattr(self, '_derating')):
            return self._derating


class MySenecWebPortal:
    def __init__(self, user, pwd, web_session, master_plant_number: int = 0, lang: str = "en", options: dict = None):
        self._lang = lang
        if options is not None:
            logging_options = dict(options)
            if CONF_APP_TOKEN in options:
                del logging_options[CONF_APP_TOKEN]
                logging_options[CONF_APP_TOKEN] = "<MASKED>"
            if CONF_APP_SYSTEMID in options:
                del logging_options[CONF_APP_SYSTEMID]
                logging_options[CONF_APP_SYSTEMID] = "<MASKED>"
            _LOGGER.info(f"restarting MySenecWebPortal... for user: '{user}' with options: {logging_options}")
        else:
            _LOGGER.info(f"restarting MySenecWebPortal... for user: '{user}' without options")

        # check if peak shaving is in options
        if options is not None and QUERY_WALLBOX_KEY in options:
            self._QUERY_WALLBOX = options[QUERY_WALLBOX_KEY]

        # Check if spare capacity is in options
        if options is not None and QUERY_SPARE_CAPACITY_KEY in options:
            self._QUERY_SPARE_CAPACITY = options[QUERY_SPARE_CAPACITY_KEY]

        # check if peak shaving is in options
        if options is not None and QUERY_PEAK_SHAVING_KEY in options:
            self._QUERY_PEAK_SHAVING = options[QUERY_PEAK_SHAVING_KEY]

        # Variable to save latest update time for spare capacity
        self._QUERY_SPARE_CAPACITY_TS = 0

        # Variable to save latest update time for peak shaving
        self._QUERY_PEAK_SHAVING_TS = 0

        # Variable to save latest update time for SG-Ready configuration
        self._QUERY_SGREADY_CONF_TS = 0

        self.web_session: aiohttp.websession = web_session

        if _require_lib_patch():
            if hasattr(aiohttp.helpers, "get_running_loop"):
                loop = aiohttp.helpers.get_running_loop(web_session.loop)
            elif hasattr(asyncio, "get_running_loop"):
                loop = asyncio.get_running_loop()
            else:
                loop = None

            if loop is not None:
                senec_jar = MySenecCookieJar(loop=loop)
                if hasattr(web_session, "_cookie_jar"):
                    old_jar = getattr(web_session, "_cookie_jar")
                    senec_jar.update_cookies(old_jar._host_only_cookies)
                setattr(self.web_session, "_cookie_jar", senec_jar)
            else:
                _LOGGER.warning("_require_lib_patch is True, but we could not get access to a loop object")

        self._master_plant_number = master_plant_number

        # SENEC API
        self._SENEC_USERNAME = user
        self._SENEC_PASSWORD = pwd

        # https://documenter.getpostman.com/view/10329335/UVCB9ihW#17e2c6c6-fe5e-4ca9-bc2f-dca997adaf90
        # https://documenter.getpostman.com/view/10329335/UVCB9ihW#3e5a4286-c7d2-49d1-8856-12bba9fb5c6e
        # https://documenter.getpostman.com/view/932140/2s9YXib2td#4d0f84ac-f573-42e3-b155-9a17cef309ec
        APP_BASE_URL = "https://app-gateway-prod.senecops.com/"
        self._SENEC_APP_AUTH = APP_BASE_URL + "v1/senec/login"
        self._SENEC_APP_GET_SYSTEMS = APP_BASE_URL + "v1/senec/anlagen"
        self._SENEC_APP_GET_ABILITIES = APP_BASE_URL + "v1/senec/anlagen/%s/abilities"
        self._SENEC_APP_SET_WALLBOX = APP_BASE_URL + "v1/senec/anlagen/%s/wallboxes/%s"
        # "https://app-gateway-prod.senecops.com/v1/senec/anlagen/%s/technical-data"
        # "https://app-gateway-prod.senecops.com/v1/senec/anlagen/%s/statistik?periode=JAHR&datum=2024-01-13&locale=de_DE&timezone=Europe/Berlin"
        # "https://app-gateway-prod.senecops.com/v1/senec/anlagen/%s/zeitverlauf?periode=STUNDE&after=2024-01-14T12:00:00Z&locale=de_DE&timezone=Europe/Berlin"

        APP_BASE_URL2 = "https://app-gateway.prod.senec.dev/"
        self._SENEC_APP_NOW = APP_BASE_URL2 + "v2/senec/systems/%s/dashboard"
        self._SENEC_APP_TOTAL_V1_OUTDATED = APP_BASE_URL2 + "v1/senec/monitor/%s/data/custom?startDate=2018-01-01&endDate=%s-%s-01&locale=de_DE&timezone=GMT"
        # 1514764800 = 2018-01-01 as UNIX epoche timestamp
        self._SENEC_APP_TOTAL_V2 = APP_BASE_URL2 + "v2/senec/systems/%s/measurements?resolution=YEAR&from=1514764800&to=%s"
        self._SENEC_APP_TECHDATA = APP_BASE_URL2 + "v1/senec/systems/%s/technical-data"

        # https://app-gateway.prod.senec.dev/v1/senec/systems/%s/abilities
        # https://app-gateway.prod.senec.dev/v1/senec/systems/%s/operational-mode -> "COM70"

        self._SENEC_WEB_AUTH = "https://mein-senec.de/auth/login"
        self._SENEC_WEB_GET_CUSTOMER = "https://mein-senec.de/endkunde/api/context/getEndkunde"
        self._SENEC_WEB_GET_SYSTEM_INFO = "https://mein-senec.de/endkunde/api/context/getAnlageBasedNavigationViewModel?anlageNummer=%s"

        self._SENEC_WEB_GET_OVERVIEW_URL = "https://mein-senec.de/endkunde/api/status/getstatusoverview.php?anlageNummer=%s"
        self._SENEC_WEB_GET_STATUS = "https://mein-senec.de/endkunde/api/status/getstatus.php?type=%s&period=all&anlageNummer=%s"

        # Calls for spare capacity - Base URL has to be followed by master plant number
        self._SENEC_API_SPARE_CAPACITY_BASE_URL = "https://mein-senec.de/endkunde/api/senec/"
        # Call the following URL (GET-Request) in order to get the spare capacity as int in the response body
        self._SENEC_API_GET_SPARE_CAPACITY = "/emergencypower/reserve-in-percent"
        # Call the following URL (Post Request) in order to set the spare capacity
        self._SENEC_API_SET_SPARE_CAPACITY = "/emergencypower?reserve-in-percent="

        # Call for export limit and current peak shaving information - to be followed by master plant number
        self._SENEC_API_GET_PEAK_SHAVING = "https://mein-senec.de/endkunde/api/peakshaving/getSettings?anlageNummer="
        # Call to set spare capacity information - Base URL
        self._SENEC_API_SET_PEAK_SHAVING_BASE_URL = "https://mein-senec.de/endkunde/api/peakshaving/saveSettings?anlageNummer="
        #
        self._SENEC_API_GET_SGREADY_STATE = "https://mein-senec.de/endkunde/api/senec/%s/sgready/state"
        self._SENEC_API_GET_SGREADY_CONF = "https://mein-senec.de/endkunde/api/senec/%s/sgready/config"
        # {"enabled":false,"modeChangeDelayInMinutes":20,"powerOnProposalThresholdInWatt":2000,"powerOnCommandThresholdInWatt":2500}
        self._SENEC_API_SET_SGREADY_CONF = "https://mein-senec.de/endkunde/api/senec/%s/sgready"

        # can be used in all api calls, names come from senec website
        self._API_KEYS = [
            "accuimport",  # what comes OUT OF the accu
            "accuexport",  # what goes INTO the accu
            "gridimport",  # what comes OUT OF the grid
            "gridexport",  # what goes INTO the grid
            "powergenerated",  # power produced
            "consumption"  # power used
        ]

        # can only be used in some api calls, names come from senec website
        self._API_KEYS_EXTRA = [
            "acculevel"  # accu level
        ]

        # WEBDATA STORAGE
        self._is_authenticated = False
        self._energy_entities = {}
        self._power_entities = {}
        self._battery_entities = {}
        self._spare_capacity = 0  # initialize the spare_capacity with 0
        self._peak_shaving_entities = {}
        self._sgready_conf_data = {}
        self._sgready_mode_code = 0
        self._sgready_mode = None

        # APP-API...
        if options is not None and CONF_APP_TOKEN in options and CONF_APP_SYSTEMID in options and CONF_APP_WALLBOX_COUNT in options:
            self._app_is_authenticated = True
            self._app_token = options[CONF_APP_TOKEN]
            self._app_master_plant_id = options[CONF_APP_SYSTEMID]
            self._app_wallbox_num_max = options[CONF_APP_WALLBOX_COUNT]
        else:
            self._app_is_authenticated = False
            self._app_token = None
            self._app_master_plant_id = None
            self._app_wallbox_num_max = 4

        self._app_raw_now = None
        self._app_raw_today = None
        self._app_raw_total_v1_outdated = None
        self._app_raw_total_v2 = None
        self._app_raw_tech_data = None
        self._app_raw_wallbox = [None, None, None, None]

        self.SGREADY_SUPPORTED = False

        # self._QUERY_TECH_DATA_TS = 0

        IntBridge.app_api = self
        if IntBridge.avail():
            # ok local-polling (lala.cgi) is already existing...
            if IntBridge.lala_cgi._QUERY_WALLBOX_APPAPI:
                self._QUERY_WALLBOX = True
                _LOGGER.debug("APP-API: will query WALLBOX data (cause 'lala_cgi._QUERY_WALLBOX_APPAPI' is True)")

    def check_cookie_jar_type(self):
        if _require_lib_patch():
            if hasattr(self.web_session, "_cookie_jar"):
                old_jar = getattr(self.web_session, "_cookie_jar")
                if type(old_jar) is not MySenecCookieJar:
                    _LOGGER.warning('CookieJar is not of type MySenecCookie JAR any longer... forcing CookieJAR update')
                    loop = aiohttp.helpers.get_running_loop(self.web_session.loop)
                    new_senec_jar = MySenecCookieJar(loop=loop);
                    new_senec_jar.update_cookies(old_jar._host_only_cookies)
                    setattr(self.web_session, "_cookie_jar", new_senec_jar)

    def purge_senec_cookies(self):
        if hasattr(self.web_session, "_cookie_jar"):
            the_jar = getattr(self.web_session, "_cookie_jar")
            the_jar.clear_domain("mein-senec.de")

    async def app_authenticate(self, retry: bool = True, do_update: bool = False):
        _LOGGER.debug("***** APP-API: app_authenticate(self) ********")
        auth_payload = {
            "username": self._SENEC_USERNAME,
            "password": self._SENEC_PASSWORD
        }
        async with self.web_session.post(self._SENEC_APP_AUTH, json=auth_payload, ssl=False) as res:
            try:
                res.raise_for_status()
                if res.status == 200:
                    try:
                        r_json = await res.json()
                        _LOGGER.debug(f"APP-API: response:{r_json}")
                        if "token" in r_json:
                            self._app_token = r_json["token"]
                            self._app_is_authenticated = True
                            await self.app_get_master_plant_id(retry)
                            if self._app_master_plant_id is not None:
                                _LOGGER.info("APP-API: Login successful")
                                if do_update:
                                    await self.update()
                            else:
                                _LOGGER.error("APP-API: could not fetch master plant id (aka 'anlagen:id')")
                    except JSONDecodeError as jsonexc:
                        _LOGGER.warning(f"APP-API: JSONDecodeError while 'await res.json(): {jsonexc}")

                    except ClientResponseError as ioexc:
                        _LOGGER.warning(f"APP-API: ClientResponseError while 'await res.json(): {ioexc}")

                else:
                    _LOGGER.warning(f"APP-API: Login failed with Code {res.status}")

            except ClientResponseError as ioexc:
                _LOGGER.warning(f"APP-API: Could not login to APP-API: {ioexc}")

    async def app_update_context(self, retry: bool = True):
        _LOGGER.debug("***** app_update_context(self) ********")
        if self._app_is_authenticated:
            await self.app_update_tech_data(retry=True)
        else:
            await self.app_authenticate()
            if retry:
                await self.app_update_context(retry=False)

    async def app_get_master_plant_id(self, retry: bool = True):
        _LOGGER.debug("***** APP-API: get_master_plant_id(self) ********")
        if self._app_is_authenticated:
            headers = {"Authorization": self._app_token}
            try:
                async with self.web_session.get(self._SENEC_APP_GET_SYSTEMS, headers=headers, ssl=False) as res:
                    try:
                        res.raise_for_status()
                        if res.status == 200:
                            data = None
                            try:
                                data = await res.json();
                                _LOGGER.debug(f"APP-API response: {data}")
                                if self._master_plant_number == -1:
                                    self._master_plant_number = 0
                                idx = int(self._master_plant_number)

                                # when SENEC API only return a single system in the 'v1/senec/anlagen' request (even if
                                # there are multiple systems)...
                                if len(data) == 1 and idx > 0:
                                    _LOGGER.debug(
                                        f"APP-API IGNORE requested 'master_plant_number' {idx} will use 0 instead!")
                                    idx = 0

                                if len(data) > idx:
                                    if "id" in data[idx]:
                                        self._app_master_plant_id = data[idx]["id"]
                                        _LOGGER.debug(
                                            f"APP-API set _app_master_plant_id to {self._app_master_plant_id}")

                                    if "wallboxIds" in data[idx]:
                                        self._app_wallbox_num_max = len(data[idx]["wallboxIds"])
                                        _LOGGER.debug(
                                            f"APP-API set _app_wallbox_num_max to {self._app_wallbox_num_max}")
                                else:
                                    _LOGGER.warning(f"Index: {idx} not available in array data: '{data}'")
                            except JSONDecodeError as jexc:
                                _LOGGER.warning(f"JSONDecodeError while 'await res.json()' {jexc}")
                            except Exception as exc:
                                if data is not None:
                                    _LOGGER.error(
                                        f"APP-API: Error when handling response '{res}' - Data: '{data}' - Exception:' {exc}' [retry={retry}]")
                                else:
                                    _LOGGER.error(
                                        f"APP-API: Error when handling response '{res}' - Exception:' {exc}' [retry={retry}]")
                        else:
                            if retry:
                                self._app_is_authenticated = False
                                self._app_token = None
                                self._app_master_plant_id = None
                                await self.app_authenticate(retry=False)
                    except Exception as exc:
                        if res is not None:
                            _LOGGER.error(
                                f"APP-API: Error while access {self._SENEC_APP_GET_SYSTEMS}: '{exc}' - Response is: '{res}' [retry={retry}]")
                        else:
                            _LOGGER.error(
                                f"APP-API: Error while access {self._SENEC_APP_GET_SYSTEMS}: '{exc}' [retry={retry}]")
            except Exception as exc:
                _LOGGER.error(
                    f"APP-API: Error when try to call 'self.web_session.get()' for {self._SENEC_APP_GET_SYSTEMS}: '{exc}' [retry={retry}]")
        else:
            if retry:
                await self.app_authenticate(retry=False)

    async def app_get_data(self, a_url: str) -> dict:
        _LOGGER.debug("***** APP-API: app_get_data(self) ********")
        if self._app_token is not None:
            _LOGGER.debug(f"APP-API get {a_url}")
            try:
                headers = {"Authorization": self._app_token}
                async with self.web_session.get(url=a_url, headers=headers, ssl=False) as res:
                    res.raise_for_status()
                    if res.status == 200:
                        try:
                            data = await res.json()
                            _LOGGER.debug(f"APP-API response: {data}")
                            return data
                        except JSONDecodeError as exc:
                            _LOGGER.warning(f"APP-API: JSONDecodeError while 'await res.json()' {exc}")

                    elif res.status == 500:
                        _LOGGER.warning(f"APP-API: Not found {a_url} (http 500)")

                    else:
                        self._app_is_authenticated = False
                        self._app_token = None
                        self._app_master_plant_id = None

                    return None

            except Exception as exc:
                try:
                    if res.status == 500:
                        _LOGGER.warning(f"APP-API: Not found {a_url} [HTTP 500]: {exc}")
                    elif res.status == 400:
                        # please note, we do this 'shit' ONLY on GET (and not when POST data) - since when we reach
                        # any post command to the API, we expect that the TOKEN is valid (because we did previously
                        # already at least one GET call)
                        _LOGGER.warning(
                            f"APP-API: Calling {a_url} caused [HTTP 400]: {exc} this is SO RIDICULOUS Senec - returning 400 without error code when TOKEN is invalid")
                        self._app_is_authenticated = False
                        self._app_token = None
                        self._app_master_plant_id = None
                    elif res.status == 401:
                        _LOGGER.warning(f"APP-API: No permission {a_url} [HTTP 401]: {exc}")
                        self._app_is_authenticated = False
                        self._app_token = None
                        self._app_master_plant_id = None
                    else:
                        _LOGGER.warning(f"APP-API: Could not get data from {a_url} causing: {exc}")
                except NameError:
                    _LOGGER.warning(f"APP-API: NO RES - Could not get data from {a_url} causing: {exc}")

                return None
        else:
            # somehow we should pass a "callable"...
            await self.app_authenticate()

    async def app_update_total(self, retry: bool = True):
        _LOGGER.debug("***** APP-API: app_update_total(self) ********")
        if self._app_master_plant_id is not None:
            today = datetime.today() + relativedelta(months=+1)
            # status_url = f"{self._SENEC_APP_TOTAL}" % (
            #    str(self._app_master_plant_id), today.strftime('%Y'), today.strftime('%m'))
            status_url = f"{self._SENEC_APP_TOTAL_V2}" % (str(self._app_master_plant_id), str(int(today.timestamp())))
            data = await self.app_get_data(a_url=status_url)
            if data is not None and "measurements" in data and "timeseries" in data:
                self._app_raw_total_v2 = data
            else:
                self._app_raw_total_v2 = None
        else:
            if retry:
                await self.app_authenticate()
                await self.app_update_total(retry=False)

    async def app_update_now(self, retry: bool = True):
        _LOGGER.debug("***** APP-API: app_update_now(self) ********")
        if self._app_master_plant_id is not None:
            status_url = f"{self._SENEC_APP_NOW}" % (str(self._app_master_plant_id))
            data = await self.app_get_data(a_url=status_url)
            if data is not None and "currently" in data:
                self._app_raw_now = data["currently"]
            else:
                self._app_raw_now = None

            # even if there are no active 'today' sensors we want to capture already the data
            if data is not None and "today" in data:
                self._app_raw_today = data["today"]
            else:
                self._app_raw_today = None

        else:
            if retry:
                await self.app_authenticate()
                await self.app_update_now(retry=False)

    async def app_update_tech_data(self, retry: bool = True):
        _LOGGER.debug("***** APP-API: app_update_tech_data(self) ********")
        if self._app_master_plant_id is not None:
            status_url = f"{self._SENEC_APP_TECHDATA}" % (str(self._app_master_plant_id))
            data = await self.app_get_data(a_url=status_url)
            if data is not None:
                self._app_raw_tech_data = data
                # self._QUERY_TECH_DATA_TS = time()
            else:
                self._app_raw_tech_data = None
                # self._QUERY_TECH_DATA_TS = 0
        else:
            if retry:
                await self.app_authenticate()
                await self.app_update_tech_data(retry=False)

    async def app_get_wallbox_data(self, wallbox_num: int = 1, retry: bool = True):
        _LOGGER.debug("***** APP-API: app_get_wallbox_data(self) ********")
        if self._app_master_plant_id is not None:
            idx = wallbox_num - 1
            wb_url = f"{self._SENEC_APP_SET_WALLBOX}" % (str(self._app_master_plant_id), str(wallbox_num))
            data = await self.app_get_data(a_url=wb_url)
            if data is not None:
                self._app_raw_wallbox[idx] = data
            else:
                self._app_raw_wallbox[idx] = None

            # {
            #     "id": 1,
            #     "configurable": true,
            #     "maxPossibleChargingCurrentInA": 16.02,
            #     "minPossibleChargingCurrentInA": 6,
            #     "chargingMode": "SMART_SELF_GENERATED_COMPATIBILITY_MODE",
            #     "currentApparentChargingPowerInVa": 4928,
            #     "electricVehicleConnected": true,
            #     "hasError": false,
            #     "statusText": "Lädt",
            #     "configuredMaxChargingCurrentInA": 16.02,
            #     "configuredMinChargingCurrentInA": 8,
            #     "temperatureInCelsius": 17.284,
            #     "numberOfElectricPowerPhasesUsed": 3,
            #     "allowIntercharge": null,
            #     "compatibilityMode": true
            # }

        else:
            if retry:
                await self.app_authenticate()
                if self._app_wallbox_num_max >= wallbox_num:
                    await self.app_get_wallbox_data(wallbox_num=wallbox_num, retry=False)
                else:
                    _LOGGER.debug(
                        f"APP-API cancel 'app_get_wallbox_data' since after login the max '{self._app_wallbox_num_max}' is < then '{wallbox_num}' (wallbox number to request)")

    async def app_update_all_wallboxes(self):
        _LOGGER.debug(f"APP-API app_update_wallboxes for '{self._app_wallbox_num_max}' wallboxes")
        # ok we go through all possible wallboxes [1-4] and check, if we can receive some
        # data - if there is no data, then we make sure, that next time we do not query
        # this wallbox again...
        # python: 'range(x, y)' will not include 'y'
        for idx in range(0, self._app_wallbox_num_max):
            if self._app_wallbox_num_max > idx:
                await self.app_get_wallbox_data(wallbox_num=(idx + 1))
                if self._app_raw_wallbox[idx] is None and self._app_wallbox_num_max > idx:
                    _LOGGER.debug(f"APP-API set _app_wallbox_num_max to {idx}")
                    self._app_wallbox_num_max = idx

    async def app_post_data(self, a_url: str, post_data: dict, read_response: bool = False) -> bool:
        _LOGGER.debug("***** APP-API: app_post_data(self) ********")
        if self._app_token is not None:
            _LOGGER.debug(f"APP-API post {post_data} to {a_url}")
            try:
                headers = {"Authorization": self._app_token}
                async with self.web_session.post(url=a_url, headers=headers, json=post_data, ssl=False) as res:
                    res.raise_for_status()
                    if res.status == 200:
                        if read_response:
                            try:
                                data = await res.json()
                                _LOGGER.debug(f"APP-API HTTP:200 for post {post_data} to {a_url} returned: {data}")
                                return True
                            except JSONDecodeError as exc:
                                _LOGGER.warning(f"APP-API: JSONDecodeError while 'await res.json()' {exc}")
                        else:
                            _LOGGER.debug(f"APP-API HTTP:200 for post {post_data} to {a_url}")
                            return True

                    elif res.status == 500:
                        _LOGGER.info(f"APP-API: Not found {a_url} (http 500)")

                    else:
                        self._app_is_authenticated = False
                        self._app_token = None
                        self._app_master_plant_id = None
                        return False

            except Exception as exc:
                try:
                    if res.status == 500:
                        _LOGGER.info(f"APP-API: Not found {a_url} [HTTP 500]: {exc}")
                    elif res.status == 400:
                        _LOGGER.info(f"APP-API: Not found {a_url} [HTTP 400]: {exc}")
                    elif res.status == 401:
                        _LOGGER.info(f"APP-API: No permission {a_url} [HTTP 401]: {exc}")
                        self._app_is_authenticated = False
                        self._app_token = None
                        self._app_master_plant_id = None
                    else:
                        _LOGGER.warning(f"APP-API: Could not post to {a_url} data: {post_data} causing: {exc}")
                except NameError:
                    _LOGGER.warning(f"APP-API: NO RES - Could not post to {a_url} data: {post_data} causing: {exc}")
                return False

        else:
            # somehow we should pass a "callable"...
            await self.app_authenticate()
            return False

    async def app_set_wallbox_mode(self, local_mode_to_set: str, wallbox_num: int = 1, sync: bool = True,
                                   retry: bool = True):
        _LOGGER.debug("***** APP-API: app_set_wallbox_mode(self) ********")
        idx = wallbox_num - 1
        cur_local_mode = self.app_get_local_wallbox_mode_from_api_values(idx)
        if cur_local_mode == local_mode_to_set:
            _LOGGER.debug(f"APP-API skipp mode change since '{local_mode_to_set}' already set")
        else:
            if self._app_master_plant_id is not None:
                data = None
                api_mode_to_set = None
                compatibility_mode_to_set = None

                if local_mode_to_set == LOCAL_WB_MODE_LOCKED:
                    data = {
                        "mode": APP_API_WB_MODE_LOCKED
                    }
                    api_mode_to_set = APP_API_WB_MODE_LOCKED
                elif local_mode_to_set == LOCAL_WB_MODE_SSGCM_3:
                    data = {
                        "mode": APP_API_WB_MODE_SSGCM,
                        "compatibilityMode": True
                    }
                    api_mode_to_set = APP_API_WB_MODE_SSGCM
                    compatibility_mode_to_set = True
                elif local_mode_to_set == LOCAL_WB_MODE_SSGCM_4:
                    data = {
                        "mode": APP_API_WB_MODE_SSGCM,
                        "compatibilityMode": False
                    }
                    api_mode_to_set = APP_API_WB_MODE_SSGCM
                    compatibility_mode_to_set = False
                elif local_mode_to_set == LOCAL_WB_MODE_FASTEST:
                    data = {
                        "mode": APP_API_WB_MODE_FASTEST
                    }
                    api_mode_to_set = APP_API_WB_MODE_FASTEST

                if data is not None:
                    wb_url = f"{self._SENEC_APP_SET_WALLBOX}" % (str(self._app_master_plant_id), str(wallbox_num))
                    success: bool = await self.app_post_data(a_url=wb_url, post_data=data)

                    if success:
                        # setting the internal storage value...
                        if self._app_raw_wallbox[idx] is not None:
                            self._app_raw_wallbox[idx]["chargingMode"] = api_mode_to_set
                            if compatibility_mode_to_set is not None:
                                self._app_raw_wallbox[idx]["compatibilityMode"] = compatibility_mode_to_set

                        # do we need to sync the value back to the 'lala_cgi' integration?
                        if sync and IntBridge.avail():
                            # since the '_set_wallbox_mode_post' method is not calling the APP-API again, there
                            # is no sync=False parameter here...
                            await IntBridge.lala_cgi._set_wallbox_mode_post(pos=idx, local_value=local_mode_to_set)

                        # when we changed the mode, the backend might have automatically adjusted the
                        # 'configuredMinChargingCurrentInA' so we need to sync this possible change with the LaLa_cgi
                        # no matter, if the 'app_set_wallbox_mode' have been called with sync=False (or not)!!!
                        await asyncio.sleep(2)
                        await self.app_get_wallbox_data(wallbox_num=wallbox_num)
                        if self._app_raw_wallbox[idx] is not None:
                            if local_mode_to_set == LOCAL_WB_MODE_FASTEST:
                                new_min_current_tmp = self._app_raw_wallbox[idx]["maxPossibleChargingCurrentInA"]
                            else:
                                new_min_current_tmp = self._app_raw_wallbox[idx]["configuredMinChargingCurrentInA"]

                            new_min_current = str(round(float(new_min_current_tmp), 2))
                            cur_min_current = str(round(IntBridge.lala_cgi.wallbox_set_icmax[idx], 2))

                            if cur_min_current != new_min_current:
                                _LOGGER.debug(
                                    f"APP-API 2sec after mode change: local set_ic_max {cur_min_current} will be updated to {new_min_current}")
                                await IntBridge.lala_cgi.set_nva_wallbox_set_icmax(pos=idx,
                                                                                   value=float(new_min_current),
                                                                                   sync=False, verify_state=False)
                            else:
                                _LOGGER.debug(
                                    f"APP-API 2sec after mode change: NO CHANGE! - local set_ic_max: {cur_min_current} equals: {new_min_current}]")

                        else:
                            _LOGGER.debug(f"APP-API could not read wallbox data 2sec after mode change")

            else:
                if retry:
                    await self.app_authenticate()
                    if self._app_wallbox_num_max >= wallbox_num:
                        await self.app_set_wallbox_mode(local_mode_to_set=local_mode_to_set, wallbox_num=wallbox_num,
                                                        sync=sync, retry=False)
                    else:
                        _LOGGER.debug(
                            f"APP-API cancel 'set_wallbox_mode' since after login the max '{self._app_wallbox_num_max}' is < then '{wallbox_num}' (wallbox number to request)")

    async def app_set_wallbox_icmax(self, value_to_set: float, wallbox_num: int = 1, sync: bool = True,
                                    retry: bool = True):
        _LOGGER.debug("***** APP-API: app_set_wallbox_icmax(self) ********")
        if self._app_master_plant_id is not None:
            idx = wallbox_num - 1
            current_mode = APP_API_WB_MODE_SSGCM

            if self._app_raw_wallbox[idx] is not None and "chargingMode" in self._app_raw_wallbox[idx]:
                current_mode = self._app_raw_wallbox[idx]["chargingMode"]

            data = {
                "mode": current_mode,
                "minChargingCurrentInA": float(round(value_to_set, 2))
            }

            wb_url = f"{self._SENEC_APP_SET_WALLBOX}" % (str(self._app_master_plant_id), str(wallbox_num))
            success: bool = await self.app_post_data(a_url=wb_url, post_data=data)
            if success:
                # setting the internal storage value...
                if self._app_raw_wallbox[idx] is not None:
                    self._app_raw_wallbox[idx]["configuredMinChargingCurrentInA"] = value_to_set

                # do we need to sync the value back to the 'lala_cgi' integration?
                if sync and IntBridge.avail():
                    await IntBridge.lala_cgi.set_nva_wallbox_set_icmax(pos=idx, value=value_to_set, sync=False)
        else:
            if retry:
                await self.app_authenticate()
                if self._app_wallbox_num_max >= wallbox_num:
                    await self.app_set_wallbox_icmax(value_to_set=value_to_set, wallbox_num=wallbox_num,
                                                     sync=sync, retry=False)
                else:
                    _LOGGER.debug(
                        f"APP-API cancel 'app_set_wallbox_icmax' since after login the max '{self._app_wallbox_num_max}' is < then '{wallbox_num}' (wallbox number to request)")

    async def app_set_allow_intercharge(self, value_to_set: bool, wallbox_num: int = 1, sync: bool = True,
                                        retry: bool = True) -> bool:
        _LOGGER.debug("***** APP-API: app_set_allow_intercharge(self) ********")
        if self._app_master_plant_id is not None:
            idx = wallbox_num - 1

            current_mode = APP_API_WB_MODE_LOCKED
            if self._app_raw_wallbox[idx] is not None and "chargingMode" in self._app_raw_wallbox[idx]:
                current_mode = self._app_raw_wallbox[idx]["chargingMode"]

            data = {
                "mode": current_mode,
                "allowIntercharge": value_to_set
            }

            wb_url = f"{self._SENEC_APP_SET_WALLBOX}" % (str(self._app_master_plant_id), str(wallbox_num))
            success: bool = await self.app_post_data(a_url=wb_url, post_data=data)
            if success:
                # setting the internal storage value...
                if self._app_raw_wallbox[idx] is not None:
                    self._app_raw_wallbox[idx]["allowIntercharge"] = value_to_set

                # do we need to sync the value back to the 'lala_cgi' integration?
                if sync and IntBridge.avail():
                    await IntBridge.lala_cgi.switch_wallbox_allow_intercharge(value=value_to_set, sync=False)
            return success
        else:
            if retry:
                await self.app_authenticate()
                if self._app_wallbox_num_max >= wallbox_num:
                    return await self.app_set_allow_intercharge(value_to_set=value_to_set, wallbox_num=wallbox_num,
                                                                sync=sync, retry=False)
                else:
                    _LOGGER.debug(
                        f"APP-API cancel 'set_wallbox_mode' since after login the max '{self._app_wallbox_num_max}' is < then '{wallbox_num}' (wallbox number to request)")
                    return False
            else:
                return False

    async def app_set_allow_intercharge_all(self, value_to_set: bool, sync: bool = True):
        _LOGGER.debug(f"APP-API app_set_allow_intercharge_all for '{self._app_wallbox_num_max}' wallboxes")
        for idx in range(0, self._app_wallbox_num_max):
            if self._app_wallbox_num_max > idx:
                res = await self.app_set_allow_intercharge(value_to_set=value_to_set, wallbox_num=(idx + 1), sync=sync)
                if not res and self._app_wallbox_num_max > idx:
                    _LOGGER.debug(f"APP-API set _app_wallbox_num_max to {idx}")
                    self._app_wallbox_num_max = idx

    async def app_get_system_abilities(self):
        # 'app_get_system_abilities' not used (yet)
        if self._app_master_plant_id is not None and self._app_token is not None:
            headers = {"Authorization": self._app_token}
            a_url = f"{self._SENEC_APP_GET_ABILITIES}" % str(self._app_master_plant_id)
            async with self.web_session.get(url=a_url, headers=headers, ssl=False) as res:
                res.raise_for_status()
                if res.status == 200:
                    try:
                        data = await res.json()
                        _LOGGER.debug(f"APP-API response: {data}")
                    except JSONDecodeError as exc:
                        _LOGGER.warning(f"JSONDecodeError while 'await res.json()' {exc}")
                else:
                    self._app_is_authenticated = False
                    # somehow we should pass a "callable"...
                    await self.app_get_master_plant_id()
        else:
            # somehow we should pass a "callable"...
            await self.app_get_master_plant_id()

    def app_get_local_wallbox_mode_from_api_values(self, idx: int) -> str:
        if self._app_raw_wallbox[idx] is not None and len(self._app_raw_wallbox) > idx:
            if "chargingMode" in self._app_raw_wallbox[idx]:
                api_mode = self._app_raw_wallbox[idx]["chargingMode"]
                if api_mode == APP_API_WB_MODE_SSGCM:
                    if self.app_is_wallbox_compatibility_mode_on(idx=idx):
                        return LOCAL_WB_MODE_SSGCM_3
                    else:
                        return LOCAL_WB_MODE_SSGCM_4
                elif api_mode == APP_API_WB_MODE_FASTEST:
                    return LOCAL_WB_MODE_FASTEST
                elif api_mode == APP_API_WB_MODE_LOCKED:
                    return LOCAL_WB_MODE_LOCKED
        return LOCAL_WB_MODE_UNKNOWN

    def app_get_api_wallbox_mode_from_local_value(self, local_mode: str) -> str:
        if local_mode == LOCAL_WB_MODE_LOCKED:
            return APP_API_WB_MODE_LOCKED
        elif local_mode == LOCAL_WB_MODE_SSGCM_3:
            return APP_API_WB_MODE_SSGCM
        elif local_mode == LOCAL_WB_MODE_SSGCM_4:
            return APP_API_WB_MODE_SSGCM
        elif local_mode == LOCAL_WB_MODE_FASTEST:
            return APP_API_WB_MODE_FASTEST
        return local_mode

    def app_is_wallbox_compatibility_mode_on(self, idx: int):
        if self._app_raw_wallbox is not None and len(self._app_raw_wallbox) > idx:
            if "compatibilityMode" in self._app_raw_wallbox[idx]:
                val = self._app_raw_wallbox[idx]["compatibilityMode"]
                if isinstance(val, bool):
                    return val
                else:
                    return str(val).lower() == 'true'
        return False

    """MEIN-SENEC.DE from here"""

    async def web_authenticate(self, do_update: bool, throw401: bool):
        _LOGGER.info("***** authenticate(self) ********")
        self.check_cookie_jar_type()
        auth_payload = {
            "username": self._SENEC_USERNAME,
            "password": self._SENEC_PASSWORD
        }
        async with self.web_session.post(self._SENEC_WEB_AUTH, data=auth_payload, max_redirects=20, ssl=False) as res:
            try:
                res.raise_for_status()
                if res.status == 200:
                    # be gentle reading the complete response...
                    r_json = await res.text()
                    self._is_authenticated = True
                    _LOGGER.info("Login successful")
                    if do_update:
                        await self.update()
                else:
                    _LOGGER.warning(f"Login failed with Code {res.status}")
                    self.purge_senec_cookies()
            except ClientResponseError as exc:
                # _LOGGER.error(str(exc))
                if throw401:
                    raise exc
                else:
                    if exc.status == 401:
                        self.purge_senec_cookies()
                        self._is_authenticated = False
                    else:
                        _LOGGER.warning(f"Login exception with Code {res.status}")
                        self.purge_senec_cookies()

    async def update(self):
        if self._app_is_authenticated:
            _LOGGER.info("***** update(self) ********")
            await self.app_update_now()
            await self.app_update_total()
            # 30 min = 30 * 60 sec = 1800 sec
            # if self._QUERY_TECH_DATA_TS + 1800 < time():
            # well since we also get the system-state from the tech_data we call this
            # monster object every time [I dislike this!]
            await self.app_update_tech_data()

            if hasattr(self, '_QUERY_WALLBOX') and self._QUERY_WALLBOX:
                await self.app_update_all_wallboxes()

            # not used any longer... [going to use the App-API]
            # await self.update_now_kW_stats()
            # await self.update_full_kWh_stats()

            if hasattr(self, '_QUERY_SPARE_CAPACITY') and self._QUERY_SPARE_CAPACITY:
                # 1 day = 24 h = 24 * 60 min = 24 * 60 * 60 sec = 86400 sec
                if self._QUERY_SPARE_CAPACITY_TS + 86400 < time():
                    self.check_cookie_jar_type()
                    if self._is_authenticated:
                        await self.update_spare_capacity()
                    else:
                        await self.web_authenticate(do_update=True, throw401=False)

            if hasattr(self, '_QUERY_PEAK_SHAVING') and self._QUERY_PEAK_SHAVING:
                # 1 day = 24 h = 24 * 60 min = 24 * 60 * 60 sec = 86400 sec
                if self._QUERY_PEAK_SHAVING_TS + 86400 < time():
                    self.check_cookie_jar_type()
                    if self._is_authenticated:
                        await self.update_peak_shaving()
                    else:
                        await self.web_authenticate(do_update=True, throw401=False)

            if self.SGREADY_SUPPORTED:
                self.check_cookie_jar_type()
                if self._is_authenticated:
                    await self.update_sgready_state()
                else:
                    await self.web_authenticate(do_update=True, throw401=False)

                # 1 day = 24 h = 24 * 60 min = 24 * 60 * 60 sec = 86400 sec
                if self._QUERY_SGREADY_CONF_TS + 86400 < time():
                    self.check_cookie_jar_type()
                    if self._is_authenticated:
                        await self.update_sgready_conf()
                    else:
                        await self.web_authenticate(do_update=True, throw401=False)


        else:
            await self.app_authenticate(do_update=True)

    """This function will update peak shaving information"""

    async def update_peak_shaving(self):
        _LOGGER.info("***** update_peak_shaving(self) ********")
        a_url = f"{self._SENEC_API_GET_PEAK_SHAVING}{self._master_plant_number}"
        async with self.web_session.get(a_url, ssl=False) as res:
            try:
                res.raise_for_status()
                if res.status == 200:
                    try:
                        r_json = await res.json()
                        # GET Data from JSON
                        self._peak_shaving_entities["einspeisebegrenzungKwpInPercent"] = r_json[
                            "einspeisebegrenzungKwpInPercent"]
                        self._peak_shaving_entities["peakShavingMode"] = r_json["peakShavingMode"].lower()
                        self._peak_shaving_entities["peakShavingCapacityLimitInPercent"] = r_json[
                            "peakShavingCapacityLimitInPercent"]
                        self._peak_shaving_entities["peakShavingEndDate"] = datetime.fromtimestamp(
                            r_json["peakShavingEndDate"] / 1000)  # from miliseconds to seconds
                        self._QUERY_PEAK_SHAVING_TS = time()  # Update timer, that the next update takes place in 24 hours
                    except JSONDecodeError as exc:
                        _LOGGER.warning(f"JSONDecodeError while 'await res.json()' {exc}")
                else:
                    self._is_authenticated = False
                    await self.update()

            except ClientResponseError as exc:
                if exc.status == 401:
                    self.purge_senec_cookies()

                self._is_authenticated = False
                await self.update()

    """This function will set the peak shaving data over the web api"""

    async def set_peak_shaving(self, new_peak_shaving: dict):
        _LOGGER.debug("***** set_peak_shaving(self, new_peak_shaving) ********")

        # Senec self allways sends all get-parameter, even if not needed. So we will do it the same way
        a_url = f"{self._SENEC_API_SET_PEAK_SHAVING_BASE_URL}{self._master_plant_number}&mode={new_peak_shaving['mode'].upper()}&capacityLimit={new_peak_shaving['capacity']}&endzeit={new_peak_shaving['end_time']}"

        async with self.web_session.post(a_url, ssl=False) as res:
            try:
                res.raise_for_status()
                if res.status == 200:
                    _LOGGER.debug("***** Set Peak Shaving successfully ********")
                    # Reset the timer in order that the Peak Shaving is updated immediately after the change
                    self._QUERY_PEAK_SHAVING_TS = 0

                else:
                    self._is_authenticated = False
                    await self.web_authenticate(do_update=False, throw401=False)
                    await self.set_peak_shaving(new_peak_shaving)

            except ClientResponseError as exc:
                if exc.status == 401:
                    self.purge_senec_cookies()

                self._is_authenticated = False
                await self.web_authenticate(do_update=False, throw401=True)
                await self.set_peak_shaving(new_peak_shaving)

    """This function will update the spare capacity over the web api"""

    async def update_spare_capacity(self):
        _LOGGER.info("***** update_spare_capacity(self) ********")
        a_url = f"{self._SENEC_API_SPARE_CAPACITY_BASE_URL}{self._master_plant_number}{self._SENEC_API_GET_SPARE_CAPACITY}"
        async with self.web_session.get(a_url, ssl=False) as res:
            try:
                res.raise_for_status()
                if res.status == 200:
                    self._spare_capacity = await res.text()
                    self._QUERY_SPARE_CAPACITY_TS = time()
                else:
                    self._is_authenticated = False
                    await self.update()

            except ClientResponseError as exc:
                if exc.status == 401:
                    self.purge_senec_cookies()

                self._is_authenticated = False
                await self.update()

    """This function will set the spare capacity over the web api"""

    async def set_spare_capacity(self, new_spare_capacity: int):
        _LOGGER.debug("***** set_spare_capacity(self) ********")
        a_url = f"{self._SENEC_API_SPARE_CAPACITY_BASE_URL}{self._master_plant_number}{self._SENEC_API_SET_SPARE_CAPACITY}{new_spare_capacity}"

        async with self.web_session.post(a_url, ssl=False) as res:
            try:
                res.raise_for_status()
                if res.status == 200:
                    _LOGGER.debug("***** Set Spare Capacity successfully ********")
                    # Reset the timer in order that the Spare Capacity is updated immediately after the change
                    self._QUERY_SPARE_CAPACITY_TS = 0
                else:
                    self._is_authenticated = False
                    await self.web_authenticate(do_update=False, throw401=False)
                    await self.set_spare_capacity(new_spare_capacity)

            except ClientResponseError as exc:
                if exc.status == 401:
                    self.purge_senec_cookies()

                self._is_authenticated = False
                await self.web_authenticate(do_update=False, throw401=True)
                await self.set_spare_capacity(new_spare_capacity)

    # async def update_now_kW_stats(self):
    #     _LOGGER.debug("***** update_now_kW_stats(self) ********")
    #     # grab NOW and TODAY stats
    #     a_url = f"{self._SENEC_WEB_GET_OVERVIEW_URL}" % str(self._master_plant_number)
    #     async with self.web_session.get(a_url, ssl=False) as res:
    #         try:
    #             res.raise_for_status()
    #             if res.status == 200:
    #                 try:
    #                     r_json = await res.json()
    #                     self._raw = parse(r_json)
    #                     for key in (self._API_KEYS + self._API_KEYS_EXTRA):
    #                         if key in r_json:
    #                             if key == "acculevel":
    #                                 if "now" in r_json[key]:
    #                                     value_now = r_json[key]["now"]
    #                                     entity_now_name = str(key + "_now")
    #                                     self._battery_entities[entity_now_name] = value_now
    #                                 else:
    #                                     _LOGGER.info(
    #                                         f"No 'now' for key: '{key}' in json: {r_json} when requesting: {a_url}")
    #                             else:
    #                                 if "now" in r_json[key]:
    #                                     value_now = r_json[key]["now"]
    #                                     entity_now_name = str(key + "_now")
    #                                     self._power_entities[entity_now_name] = value_now
    #                                 else:
    #                                     _LOGGER.info(
    #                                         f"No 'now' for key: '{key}' in json: {r_json} when requesting: {a_url}")
    #
    #                                 if "today" in r_json[key]:
    #                                     value_today = r_json[key]["today"]
    #                                     entity_today_name = str(key + "_today")
    #                                     self._energy_entities[entity_today_name] = value_today
    #                                 else:
    #                                     _LOGGER.info(
    #                                         f"No 'today' for key: '{key}' in json: {r_json} when requesting: {a_url}")
    #
    #                         else:
    #                             _LOGGER.info(f"No '{key}' in json: {r_json} when requesting: {a_url}")
    #                 except JSONDecodeError as exc:
    #                     _LOGGER.warning(f"JSONDecodeError while 'await res.json()' {exc}")
    #
    #             else:
    #                 self._is_authenticated = False
    #                 await self.update()
    #
    #         except ClientResponseError as exc:
    #             if exc.status == 401:
    #                 self.purge_senec_cookies()
    #
    #             self._is_authenticated = False
    #             await self.update()
    #
    # async def update_full_kWh_stats(self):
    #     # grab TOTAL stats
    #
    #     for key in self._API_KEYS:
    #         api_url = f"{self._SENEC_WEB_GET_STATUS}" % (key, str(self._master_plant_number))
    #         async with self.web_session.get(api_url, ssl=False) as res:
    #             try:
    #                 res.raise_for_status()
    #                 if res.status == 200:
    #                     try:
    #                         r_json = await res.json()
    #                         if "fullkwh" in r_json:
    #                             value = r_json["fullkwh"]
    #                             entity_name = str(key + "_total")
    #                             self._energy_entities[entity_name] = value
    #                         else:
    #                             _LOGGER.info(f"No 'fullkwh' in json: {r_json} when requesting: {api_url}")
    #                     except JSONDecodeError as exc:
    #                         _LOGGER.warning(f"JSONDecodeError while 'await res.json()' {exc}")
    #
    #                 else:
    #                     self._is_authenticated = False
    #                     await self.update()
    #
    #             except ClientResponseError as exc:
    #                 if exc.status == 401:
    #                     self.purge_senec_cookies()
    #
    #                 self._is_authenticated = False
    #                 await self.update()

    async def update_sgready_state(self):
        if self.SGREADY_SUPPORTED:
            _LOGGER.info("***** update_update_sgready_state(self) ********")
            a_url = f"{self._SENEC_API_GET_SGREADY_STATE}" % (str(self._master_plant_number))
            async with self.web_session.get(a_url, ssl=False) as res:
                try:
                    res.raise_for_status()
                    if res.status == 200:
                        try:
                            r_json = await res.json()
                            plain = str(r_json)
                            if len(plain) > 4 and plain[0:4] == "MODE":
                                self._sgready_mode_code = int(plain[4:])
                                if self._sgready_mode_code > 0:
                                    if self._lang in SGREADY_MODES:
                                        self._sgready_mode = SGREADY_MODES[self._lang].get(self._sgready_mode_code,
                                                                                           "UNKNOWN")
                                    else:
                                        self._sgready_mode = SGREADY_MODES["en"].get(self._sgready_mode_code, "UNKNOWN")

                        except JSONDecodeError as exc:
                            _LOGGER.warning(f"JSONDecodeError while 'await res.json()' {exc}")
                    else:
                        self._is_authenticated = False
                        await self.update()

                except ClientResponseError as exc:
                    if exc.status == 401:
                        self.purge_senec_cookies()

                    self._is_authenticated = False
                    await self.update()

    async def update_sgready_conf(self):
        if self.SGREADY_SUPPORTED:
            _LOGGER.info("***** update_update_sgready_conf(self) ********")
            a_url = f"{self._SENEC_API_GET_SGREADY_CONF}" % (str(self._master_plant_number))
            async with self.web_session.get(a_url, ssl=False) as res:
                try:
                    res.raise_for_status()
                    if res.status == 200:
                        try:
                            r_json = await res.json()
                            self._sgready_conf_data = r_json
                            self._QUERY_SGREADY_CONF_TS = time()

                        except JSONDecodeError as exc:
                            _LOGGER.warning(f"JSONDecodeError while 'await res.json()' {exc}")
                    else:
                        self._is_authenticated = False
                        await self.update()

                except ClientResponseError as exc:
                    if exc.status == 401:
                        self.purge_senec_cookies()

                    self._is_authenticated = False
                    await self.update()

    async def set_sgready_conf(self, new_sgready_data: dict):
        if self.SGREADY_SUPPORTED:
            _LOGGER.debug(f"***** set_sgready_conf(self, new_sgready_data {new_sgready_data}) ********")

            a_url = f"{self._SENEC_API_SET_SGREADY_CONF}" % (str(self._master_plant_number))

            post_data_to_backend = False
            post_data = {}
            for a_key in SGREADY_CONF_KEYS:
                if a_key in self._sgready_conf_data:
                    if a_key in new_sgready_data:
                        if self._sgready_conf_data[a_key] != new_sgready_data[a_key]:
                            post_data[a_key] = new_sgready_data[a_key]
                            post_data_to_backend = True
                    else:
                        post_data[a_key] = self._sgready_conf_data[a_key]

            if len(post_data) > 0 and post_data_to_backend:
                async with self.web_session.post(a_url, ssl=False, json=post_data) as res:
                    try:
                        res.raise_for_status()
                        if res.status == 200:
                            _LOGGER.debug("***** Set SG-Ready CONF successfully ********")
                            # Reset the timer in order that the Peak Shaving is updated immediately after the change
                            self._QUERY_SGREADY_CONF_TS = 0

                        else:
                            self._is_authenticated = False
                            await self.web_authenticate(do_update=False, throw401=False)
                            await self.set_sgready_conf(new_sgready_data)

                    except ClientResponseError as exc:
                        if exc.status == 401:
                            self.purge_senec_cookies()

                        self._is_authenticated = False
                        await self.web_authenticate(do_update=False, throw401=True)
                        await self.set_sgready_conf(new_sgready_data)
            else:
                _LOGGER.debug(
                    f"no valid or new SGReady post data found in {new_sgready_data} current config: {self._sgready_conf_data}")

    async def update_context(self):
        _LOGGER.debug("***** update_context(self) ********")
        if self._is_authenticated:
            await self.update_get_customer()

            # in autodetect-mode the initial self._master_plant_number = -1
            if self._master_plant_number == -1:
                self._master_plant_number = 0
                is_autodetect = True
            else:
                is_autodetect = False

            await self.update_get_systems(a_plant_number=self._master_plant_number, autodetect_mode=is_autodetect)
        else:
            await self.web_authenticate(do_update=False, throw401=False)
            if self._is_authenticated:
                await self.update_context()

    async def update_get_customer(self):
        _LOGGER.debug("***** update_get_customer(self) ********")

        # grab NOW and TODAY stats
        async with self.web_session.get(self._SENEC_WEB_GET_CUSTOMER, ssl=False) as res:
            res.raise_for_status()
            if res.status == 200:
                try:
                    r_json = await res.json()
                    # self._raw = parse(r_json)
                    self._dev_number = r_json["devNumber"]
                    # anzahlAnlagen
                    # language
                    # emailAdresse
                    # meterReadingVisible
                    # vorname
                    # nachname
                except JSONDecodeError as exc:
                    _LOGGER.warning(f"JSONDecodeError while 'await res.json()' {exc}")
            else:
                self._is_authenticated = False
                await self.web_authenticate(do_update=False, throw401=False)

    async def update_get_systems(self, a_plant_number: int, autodetect_mode: bool):
        _LOGGER.debug("***** update_get_systems(self) ********")

        a_url = f"{self._SENEC_WEB_GET_SYSTEM_INFO}" % str(a_plant_number)
        async with self.web_session.get(a_url, ssl=False) as res:
            res.raise_for_status()
            if res.status == 200:
                try:
                    r_json = await res.json()
                    if autodetect_mode:
                        if "master" in r_json and r_json["master"]:
                            # we are cool that's a master-system... so we store our counter...
                            self._serial_number = r_json["steuereinheitnummer"]
                            self._product_name = r_json["produktName"]
                            if "zoneId" in r_json:
                                self._zone_id = r_json["zoneId"]
                            else:
                                self._zone_id = "UNKNOWN"
                            self._master_plant_number = a_plant_number
                        else:
                            if not hasattr(self, "_serial_number_slave"):
                                self._serial_number_slave = []
                                self._product_name_slave = []
                            self._serial_number_slave.append(r_json["steuereinheitnummer"])
                            self._product_name_slave.append(r_json["produktName"])
                            a_plant_number += 1
                            await self.update_get_systems(a_plant_number, autodetect_mode)
                    else:
                        self._serial_number = r_json["steuereinheitnummer"]
                        self._product_name = r_json["produktName"]
                        if "zoneId" in r_json:
                            self._zone_id = r_json["zoneId"]
                        else:
                            self._zone_id = "UNKNOWN"
                        self._master_plant_number = a_plant_number

                    # let's check if the sytem support's SG-Read...
                    if "sgReadyVisible" in r_json and r_json["sgReadyVisible"]:
                        _LOGGER.debug("System is SGReady")
                        self.SGREADY_SUPPORTED = True

                except JSONDecodeError as exc:
                    _LOGGER.warning(f"JSONDecodeError while 'await res.json()' {exc}")
            else:
                self._is_authenticated = False
                await self.web_authenticate(do_update=False, throw401=False)

    @property
    def spare_capacity(self) -> int:
        if hasattr(self, '_spare_capacity'):
            return int(self._spare_capacity)

    @property
    def senec_num(self) -> str:
        if self._app_raw_tech_data is not None and "casing" in self._app_raw_tech_data:
            return self._app_raw_tech_data["casing"]["serial"]
        elif hasattr(self, '_dev_number'):
            return str(self._dev_number)

    @property
    def serial_number(self) -> str:
        if self._app_raw_tech_data is not None and "mcu" in self._app_raw_tech_data:
            return self._app_raw_tech_data["mcu"]["mainControllerSerial"]
        elif hasattr(self, '_serial_number'):
            return str(self._serial_number)

    @property
    def product_name(self) -> str:
        if self._app_raw_tech_data is not None and "systemOverview" in self._app_raw_tech_data:
            return self._app_raw_tech_data["systemOverview"]["productName"]
        elif hasattr(self, '_product_name'):
            return str(self._product_name)

    @property
    def zone_id(self) -> str:
        if hasattr(self, '_zone_id'):
            return str(self._zone_id)

    @property
    def versions(self) -> str:
        a = None
        b = None
        c = None
        d = None
        e = None
        f = None
        if self._app_raw_tech_data is not None and "mcu" in self._app_raw_tech_data:
            a = self._app_raw_tech_data["mcu"]["guiVersion"]
            b = self._app_raw_tech_data["mcu"]["firmwareVersion"]

        if self._app_raw_tech_data is not None and "batteryInverter" in self._app_raw_tech_data:
            bat_inv_obj = self._app_raw_tech_data["batteryInverter"]
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
    def masterPlantNumber(self) -> int:
        if hasattr(self, '_master_plant_number'):
            return int(self._master_plant_number)

    ##############################################
    # from here the "real" sensor data starts... #
    ##############################################
    def _get_sum_for_index(self, index: int) -> float:
        return sum(entry["measurements"]["values"][index] for entry in self._app_raw_total_v2["timeseries"])

    @property
    def accuimport_total(self) -> float:
        if self._app_raw_total_v2 is not None:
            # yes this sounds strange 'BATTERY_IMPORT' (but finally SENEC have inverted it's logic) - but we must keep
            # the inverted stuff here!
            return self._get_sum_for_index(self._app_raw_total_v2["measurements"].index("BATTERY_EXPORT"))
        elif self._app_raw_total_v1_outdated is not None and "storageConsumption" in self._app_raw_total_v1_outdated:
            return float(self._app_raw_total_v1_outdated["storageConsumption"]["value"])
        elif hasattr(self, '_energy_entities') and "accuimport_total" in self._energy_entities:
            return self._energy_entities["accuimport_total"]

    @property
    def accuexport_total(self) -> float:
        if self._app_raw_total_v2 is not None:
            # yes this sounds strange 'BATTERY_IMPORT' (but finally SENEC have inverted it's logic) - but we must keep
            # the inverted stuff here!
            return self._get_sum_for_index(self._app_raw_total_v2["measurements"].index("BATTERY_IMPORT"))
        elif self._app_raw_total_v1_outdated is not None and "storageLoad" in self._app_raw_total_v1_outdated:
            return float(self._app_raw_total_v1_outdated["storageLoad"]["value"])
        elif hasattr(self, '_energy_entities') and "accuexport_total" in self._energy_entities:
            return self._energy_entities["accuexport_total"]

    @property
    def gridimport_total(self) -> float:
        if self._app_raw_total_v2 is not None:
            return self._get_sum_for_index(self._app_raw_total_v2["measurements"].index("GRID_IMPORT"))
        elif self._app_raw_total_v1_outdated is not None and "gridConsumption" in self._app_raw_total_v1_outdated:
            return float(self._app_raw_total_v1_outdated["gridConsumption"]["value"])
        elif hasattr(self, '_energy_entities') and "gridimport_total" in self._energy_entities:
            return self._energy_entities["gridimport_total"]

    @property
    def gridexport_total(self) -> float:
        if self._app_raw_total_v2 is not None:
            return self._get_sum_for_index(self._app_raw_total_v2["measurements"].index("GRID_EXPORT"))
        elif self._app_raw_total_v1_outdated is not None and "gridFeedIn" in self._app_raw_total_v1_outdated:
            return float(self._app_raw_total_v1_outdated["gridFeedIn"]["value"])
        elif hasattr(self, '_energy_entities') and "gridexport_total" in self._energy_entities:
            return self._energy_entities["gridexport_total"]

    @property
    def powergenerated_total(self) -> float:
        if self._app_raw_total_v2 is not None:
            return self._get_sum_for_index(self._app_raw_total_v2["measurements"].index("POWER_GENERATION"))
        elif self._app_raw_total_v1_outdated is not None and "generation" in self._app_raw_total_v1_outdated:
            return float(self._app_raw_total_v1_outdated["generation"]["value"])
        elif hasattr(self, '_energy_entities') and "powergenerated_total" in self._energy_entities:
            return self._energy_entities["powergenerated_total"]

    @property
    def consumption_total(self) -> float:
        if self._app_raw_total_v2 is not None:
            return self._get_sum_for_index(self._app_raw_total_v2["measurements"].index("POWER_CONSUMPTION"))
        elif self._app_raw_total_v1_outdated is not None and "totalUsage" in self._app_raw_total_v1_outdated:
            return float(self._app_raw_total_v1_outdated["totalUsage"]["value"])
        elif hasattr(self, '_energy_entities') and "consumption_total" in self._energy_entities:
            return self._energy_entities["consumption_total"]

    @property
    def accuimport_today(self) -> float:
        if self._app_raw_today is not None and "batteryDischargeInWh" in self._app_raw_today:
            return float(self._app_raw_today["batteryDischargeInWh"]) / 1000
        if hasattr(self, '_energy_entities') and "accuimport_today" in self._energy_entities:
            return self._energy_entities["accuimport_today"]

    @property
    def accuexport_today(self) -> float:
        if self._app_raw_today is not None and "batteryChargeInWh" in self._app_raw_today:
            return float(self._app_raw_today["batteryChargeInWh"]) / 1000
        elif hasattr(self, '_energy_entities') and "accuexport_today" in self._energy_entities:
            return self._energy_entities["accuexport_today"]

    @property
    def gridimport_today(self) -> float:
        if self._app_raw_today is not None and "gridDrawInWh" in self._app_raw_today:
            return float(self._app_raw_today["gridDrawInWh"]) / 1000
        elif hasattr(self, '_energy_entities') and "gridimport_today" in self._energy_entities:
            return self._energy_entities["gridimport_today"]

    @property
    def gridexport_today(self) -> float:
        if self._app_raw_today is not None and "gridFeedInInWh" in self._app_raw_today:
            return float(self._app_raw_today["gridFeedInInWh"]) / 1000
        elif hasattr(self, '_energy_entities') and "gridexport_today" in self._energy_entities:
            return self._energy_entities["gridexport_today"]

    @property
    def powergenerated_today(self) -> float:
        if self._app_raw_today is not None and "powerGenerationInWh" in self._app_raw_today:
            return float(self._app_raw_today["powerGenerationInWh"]) / 1000
        elif hasattr(self, '_energy_entities') and "powergenerated_today" in self._energy_entities:
            return self._energy_entities["powergenerated_today"]

    @property
    def consumption_today(self) -> float:
        if self._app_raw_today is not None and "powerConsumptionInWh" in self._app_raw_today:
            return float(self._app_raw_today["powerConsumptionInWh"]) / 1000
        elif hasattr(self, '_energy_entities') and "consumption_today" in self._energy_entities:
            return self._energy_entities["consumption_today"]

    @property
    def accuimport_now(self) -> float:
        if self._app_raw_now is not None and "batteryDischargeInW" in self._app_raw_now:
            return float(self._app_raw_now["batteryDischargeInW"]) / 1000
        elif hasattr(self, "_power_entities") and "accuimport_now" in self._power_entities:
            return self._power_entities["accuimport_now"]

    @property
    def accuexport_now(self) -> float:
        if self._app_raw_now is not None and "batteryChargeInW" in self._app_raw_now:
            return float(self._app_raw_now["batteryChargeInW"]) / 1000
        elif hasattr(self, "_power_entities") and "accuexport_now" in self._power_entities:
            return self._power_entities["accuexport_now"]

    @property
    def gridimport_now(self) -> float:
        if self._app_raw_now is not None and "gridDrawInW" in self._app_raw_now:
            return float(self._app_raw_now["gridDrawInW"]) / 1000
        if hasattr(self, "_power_entities") and "gridimport_now" in self._power_entities:
            return self._power_entities["gridimport_now"]

    @property
    def gridexport_now(self) -> float:
        if self._app_raw_now is not None and "gridFeedInInW" in self._app_raw_now:
            return float(self._app_raw_now["gridFeedInInW"]) / 1000
        elif hasattr(self, "_power_entities") and "gridexport_now" in self._power_entities:
            return self._power_entities["gridexport_now"]

    @property
    def powergenerated_now(self) -> float:
        if self._app_raw_now is not None and "powerGenerationInW" in self._app_raw_now:
            return float(self._app_raw_now["powerGenerationInW"]) / 1000
        elif hasattr(self, "_power_entities") and "powergenerated_now" in self._power_entities:
            return self._power_entities["powergenerated_now"]

    @property
    def consumption_now(self) -> float:
        if self._app_raw_now is not None and "powerConsumptionInW" in self._app_raw_now:
            return float(self._app_raw_now["powerConsumptionInW"]) / 1000
        elif hasattr(self, "_power_entities") and "consumption_now" in self._power_entities:
            return self._power_entities["consumption_now"]

    @property
    def acculevel_now(self) -> int:
        if self._app_raw_now is not None and "batteryLevelInPercent" in self._app_raw_now:
            return float(self._app_raw_now["batteryLevelInPercent"])
        elif hasattr(self, "_battery_entities") and "acculevel_now" in self._battery_entities:
            return self._battery_entities["acculevel_now"]

    @property
    def gridexport_limit(self) -> int:
        if hasattr(self, "_peak_shaving_entities") and "einspeisebegrenzungKwpInPercent" in self._peak_shaving_entities:
            return self._peak_shaving_entities["einspeisebegrenzungKwpInPercent"]

    @property
    def peakshaving_mode(self) -> int:
        if hasattr(self, "_peak_shaving_entities") and "peakShavingMode" in self._peak_shaving_entities:
            return self._peak_shaving_entities["peakShavingMode"]

    @property
    def peakshaving_capacitylimit(self) -> int:
        if hasattr(self,
                   "_peak_shaving_entities") and "peakShavingCapacityLimitInPercent" in self._peak_shaving_entities:
            return self._peak_shaving_entities["peakShavingCapacityLimitInPercent"]

    @property
    def peakshaving_enddate(self) -> int:
        if hasattr(self, "_peak_shaving_entities") and "peakShavingEndDate" in self._peak_shaving_entities:
            return self._peak_shaving_entities["peakShavingEndDate"]

    #############################
    # NEW APP-API SENSOR VALUES #
    #############################
    @property
    def case_temp(self) -> float:
        # 'casing': {'serial': 'XXX', 'temperatureInCelsius': 28.95928382873535},
        if self._app_raw_tech_data is not None and "casing" in self._app_raw_tech_data:
            return self._app_raw_tech_data["casing"]["temperatureInCelsius"]

    @property
    def system_state(self) -> str:
        # 'mcu': {'mainControllerSerial': 'XXX',
        #        'mainControllerState': {'name': 'EIGENVERBRAUCH', 'severity': 'INFO'}, 'firmwareVersion': '123',
        #        'guiVersion': 123}, 'warranty': {'endDate': 1700000000, 'warrantyTermInMonths': 123},
        if self._app_raw_tech_data is not None and "mcu" in self._app_raw_tech_data:
            return self._app_raw_tech_data["mcu"]["mainControllerState"]["name"].replace('_', ' ')

    #######################################################################################################
    # 'batteryInverter': {'state': {'name': 'RUN_GRID', 'severity': 'INFO'}, 'vendor': 'XXX',
    #                     'firmware': {'firmwareVersion': None,
    #                                  'firmwareVersionHumanMachineInterface': '0.01',
    #                                  'firmwareVersionPowerUnit': '0.01',
    #                                  'firmwareVersionBidirectionalDcConverter': '0.01'},
    #                     'temperatures': {'amb': 36.0, 'halfBridge1': None, 'halfBridge2': None,
    #                                     'throttle': None, 'max': 41.0},
    #                     'lastContact': {'time': 1700000000, 'severity': 'INFO'}, 'flags': []},
    #######################################################################################################
    @property
    def battery_inverter_state(self) -> str:
        if self._app_raw_tech_data is not None:
            if "batteryInverter" in self._app_raw_tech_data:
                bat_inv_obj = self._app_raw_tech_data["batteryInverter"]
                if "state" in bat_inv_obj and "name" in bat_inv_obj["state"] and bat_inv_obj["state"][
                    "name"] is not None:
                    return bat_inv_obj["state"]["name"].replace('_', ' ')

            # just a fallback...
            if "mcu" in self._app_raw_tech_data:
                mcu_obj = self._app_raw_tech_data["mcu"]
                if "mainControllerState" in mcu_obj and "name" in mcu_obj["mainControllerState"] and mcu_obj["mainControllerState"]["name"] is not None:
                    return mcu_obj["mainControllerState"]["name"].replace('_', ' ')

    @property
    def battery_temp(self) -> float:
        if self._app_raw_tech_data is not None:
            if "batteryInverter" in self._app_raw_tech_data:
                bat_inv_obj = self._app_raw_tech_data["batteryInverter"]
                if "temperatures" in bat_inv_obj and "amb" in bat_inv_obj["temperatures"] and bat_inv_obj["temperatures"]["amb"] is not None:
                    return bat_inv_obj["temperatures"]["amb"]

            # just a fallback...
            # if "casing" in self._app_raw_tech_data:
            #    casing_obj = self._app_raw_tech_data["casing"]
            #    if "temperatureInCelsius" in casing_obj and casing_obj["temperatureInCelsius"] is not None:
            #        return casing_obj["temperatureInCelsius"]

    @property
    def battery_temp_max(self) -> float:
        if self._app_raw_tech_data is not None:
            if "batteryInverter" in self._app_raw_tech_data:
                bat_inv_obj = self._app_raw_tech_data["batteryInverter"]
                if "temperatures" in bat_inv_obj and "max" in bat_inv_obj["temperatures"] and bat_inv_obj["temperatures"]["max"] is not None:
                    return bat_inv_obj["temperatures"]["max"]

            # just a fallback...
            # if "batteryModules" in self._app_raw_tech_data:
            #    bat_modules_obj = self._app_raw_tech_data["batteryModules"]
            #    count = 0
            #    temp_sum = 0
            #    for a_mod in bat_modules_obj:
            #        if "maxTemperature" in a_mod:
            #            temp_sum = temp_sum + a_mod["maxTemperature"]
            #            count = count + 1
            #    return temp_sum/count

    #######################################################################################################
    # 'batteryPack': {'numberOfBatteryModules': 4, 'technology': 'XXX', 'maxCapacityInKwh': 10.0,
    #                 'maxChargingPowerInKw': 2.5, 'maxDischargingPowerInKw': 3.75,
    #                 'currentChargingLevelInPercent': 4.040403842926025,
    #                 'currentVoltageInV': 46.26100158691406, 'currentCurrentInA': -0.10999999940395355,
    #                 'remainingCapacityInPercent': 99.9},
    #######################################################################################################
    @property
    def _battery_module_count(self) -> int:
        # internal use only...
        if self._app_raw_tech_data is not None and "batteryPack" in self._app_raw_tech_data:
            return self._app_raw_tech_data["batteryPack"]["numberOfBatteryModules"]
        return 0

    @property
    def battery_state_voltage(self) -> float:
        if self._app_raw_tech_data is not None and "batteryPack" in self._app_raw_tech_data:
            return self._app_raw_tech_data["batteryPack"]["currentVoltageInV"]

    @property
    def battery_state_current(self) -> float:
        if self._app_raw_tech_data is not None and "batteryPack" in self._app_raw_tech_data:
            return self._app_raw_tech_data["batteryPack"]["currentCurrentInA"]

    @property
    def _not_used_currentChargingLevelInPercent(self) -> float:
        if self._app_raw_tech_data is not None and "batteryPack" in self._app_raw_tech_data:
            return self._app_raw_tech_data["batteryPack"]["currentChargingLevelInPercent"]

    @property
    def battery_soh_remaining_capacity(self) -> float:
        if self._app_raw_tech_data is not None and "batteryPack" in self._app_raw_tech_data:
            return self._app_raw_tech_data["batteryPack"]["remainingCapacityInPercent"]

    #######################################################################################################
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
    #######################################################################################################
    @property
    def battery_module_state(self) -> [str]:
        if self._app_raw_tech_data is not None and "batteryModules" in self._app_raw_tech_data:
            data = ["UNKNOWN"] * self._battery_module_count
            bat_obj = self._app_raw_tech_data["batteryModules"]
            for idx in range(self._battery_module_count):
                data[idx] = bat_obj[idx]["state"]["state"].replace('_', ' ')
            return data

    @property
    def battery_module_temperature_avg(self) -> [float]:
        if self._app_raw_tech_data is not None and "batteryModules" in self._app_raw_tech_data:
            data = [-1] * self._battery_module_count
            bat_obj = self._app_raw_tech_data["batteryModules"]
            for idx in range(self._battery_module_count):
                data[idx] = (bat_obj[idx]["minTemperature"] + bat_obj[idx]["maxTemperature"]) / 2
            return data

    @property
    def battery_module_temperature_min(self) -> [float]:
        if self._app_raw_tech_data is not None and "batteryModules" in self._app_raw_tech_data:
            data = [-1] * self._battery_module_count
            bat_obj = self._app_raw_tech_data["batteryModules"]
            for idx in range(self._battery_module_count):
                data[idx] = bat_obj[idx]["minTemperature"]
            return data

    @property
    def battery_module_temperature_max(self) -> [float]:
        if self._app_raw_tech_data is not None and "batteryModules" in self._app_raw_tech_data:
            data = [-1] * self._battery_module_count
            bat_obj = self._app_raw_tech_data["batteryModules"]
            for idx in range(self._battery_module_count):
                data[idx] = bat_obj[idx]["maxTemperature"]
            return data

    @property
    def sgready_mode_code(self) -> int:
        if self.SGREADY_SUPPORTED and self._sgready_mode_code > 0:
            return self._sgready_mode_code

    @property
    def sgready_mode(self) -> str:
        if self.SGREADY_SUPPORTED and self._sgready_mode is not None:
            return self._sgready_mode

    @property
    def sgready_enabled(self) -> bool:
        if self.SGREADY_SUPPORTED and len(
                self._sgready_conf_data) > 0 and SGREADY_CONFKEY_ENABLED in self._sgready_conf_data:
            return self._sgready_conf_data[SGREADY_CONFKEY_ENABLED]

    async def switch_sgready_enabled(self, enabled: bool) -> bool:
        if self.SGREADY_SUPPORTED:
            await self.set_sgready_conf(new_sgready_data={SGREADY_CONFKEY_ENABLED: enabled})

    async def switch(self, switch_key, value):
        return await getattr(self, 'switch_' + str(switch_key))(value)

    def clear_jar(self):
        self.web_session._cookie_jar.clear()


need_patch: bool = None


@staticmethod
def _require_lib_patch() -> bool:
    global need_patch
    if need_patch is None:
        need_patch = version.parse(aiohttp.__version__) < version.parse("3.9.0")
        if need_patch:
            _LOGGER.info(
                f"aiohttp version is below 3.9.0 (current version is: {aiohttp.__version__}) - CookieJar.filter_cookies(...) need to be patched")
    return need_patch


class MySenecCookieJar(aiohttp.CookieJar):

    # Overwriting the default 'filter_cookies' impl - since the original will always return the last stored
    # matching path... [but we need the 'best' path-matching cookie of our jar!]
    def filter_cookies(self, request_url: URL = URL()) -> Union["BaseCookie[str]", "SimpleCookie[str]"]:
        """Returns this jar's cookies filtered by their attributes."""
        self._do_expiration()
        request_url = URL(request_url)
        filtered: Union["SimpleCookie[str]", "BaseCookie[str]"] = (
            SimpleCookie() if self._quote_cookie else BaseCookie()
        )
        hostname = request_url.raw_host or ""
        request_origin = URL()
        with contextlib.suppress(ValueError):
            request_origin = request_url.origin()

        is_not_secure = (
                request_url.scheme not in ("https", "wss")
                and request_origin not in self._treat_as_secure_origin
        )

        for cookie in sorted(self, key=lambda c: len(c["path"])):
            name = cookie.key
            domain = cookie["domain"]

            # Send shared cookies
            if not domain:
                filtered[name] = cookie.value
                continue

            if not self._unsafe and is_ip_address(hostname):
                continue

            if (domain, name) in self._host_only_cookies:
                if domain != hostname:
                    continue
            elif not self._is_domain_match(domain, hostname):
                continue

            if not self._is_path_match(request_url.path, cookie["path"]):
                continue

            if is_not_secure and cookie["secure"]:
                continue

            mrsl_val = cast("Morsel[str]", cookie.get(cookie.key, Morsel()))
            mrsl_val.set(cookie.key, cookie.value, cookie.coded_value)
            filtered[name] = mrsl_val

        return filtered


class IntBridge:
    app_api: MySenecWebPortal = None
    lala_cgi: Senec = None

    @staticmethod
    def avail() -> bool:
        return IntBridge.app_api is not None and IntBridge.lala_cgi is not None
