import asyncio
import traceback

import aiohttp
import logging

import xmltodict
from time import time
from datetime import datetime

from orjson import JSONDecodeError
from packaging import version

# required to patch the CookieJar of aiohttp - thanks for nothing!
import contextlib
from http.cookies import BaseCookie, SimpleCookie, Morsel
from aiohttp import ClientResponseError, ClientConnectorError
from aiohttp.helpers import is_ip_address
from yarl import URL
from typing import Union, cast, Optional

from custom_components.senec.const import (
    QUERY_BMS_KEY,
    QUERY_FANDATA_KEY,
    QUERY_WALLBOX_KEY,
    QUERY_WALLBOX_APPAPI_KEY,
    QUERY_SOCKETS_KEY,
    QUERY_SPARE_CAPACITY_KEY,
    QUERY_PEAK_SHAVING_KEY,
    IGNORE_SYSTEM_STATE_KEY,
)

from custom_components.senec.pysenec_ha.util import parse
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

    APP_API_WEB_MODE_LOCKED,
    APP_API_WEB_MODE_FASTEST,
    APP_API_WEB_MODE_SSGCM,
)

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
            SENEC_SECTION_WALLBOX + "_SET_IDEFAULT": {"TS": 0, "VALUE": [0, 0, 0, 0]},
            SENEC_SECTION_WALLBOX + "_SMART_CHARGE_ACTIVE": {"TS": 0, "VALUE": [0, 0, 0, 0]},
        }

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
        if hasattr(self, '_raw') and SENEC_SECTION_STATISTIC in self._raw and "LIVE_HOUSE_CONS" in self._raw[
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
        if hasattr(self, '_raw') and SENEC_SECTION_STATISTIC in self._raw and "LIVE_PV_GEN" in self._raw[
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
        if hasattr(self, '_raw') and SENEC_SECTION_STATISTIC in self._raw and "LIVE_BAT_CHARGE" in self._raw[
            SENEC_SECTION_STATISTIC]:
            return self._raw[SENEC_SECTION_STATISTIC]["LIVE_BAT_CHARGE"]

    @property
    def battery_total_discharged(self) -> float:
        """
        Total energy discharged from battery (kWh)
        """
        if hasattr(self, '_raw') and SENEC_SECTION_STATISTIC in self._raw and "LIVE_BAT_DISCHARGE" in self._raw[
            SENEC_SECTION_STATISTIC]:
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
        if hasattr(self, '_raw') and SENEC_SECTION_STATISTIC in self._raw and "LIVE_GRID_EXPORT" in self._raw[
            SENEC_SECTION_STATISTIC] and \
                self._raw[SENEC_SECTION_STATISTIC]["LIVE_GRID_EXPORT"] != "VARIABLE_NOT_FOUND":
            return self._raw[SENEC_SECTION_STATISTIC]["LIVE_GRID_EXPORT"]

    @property
    def grid_total_import(self) -> float:
        """
        Total energy imported from grid (kWh)
        """
        if hasattr(self, '_raw') and SENEC_SECTION_STATISTIC in self._raw and "LIVE_GRID_IMPORT" in self._raw[
            SENEC_SECTION_STATISTIC]:
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
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_A"][0]

    @property
    def bms_cell_temp_a2(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_A"][1]

    @property
    def bms_cell_temp_a3(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_A"][2]

    @property
    def bms_cell_temp_a4(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_A"][3]

    @property
    def bms_cell_temp_a5(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_A"][4]

    @property
    def bms_cell_temp_a6(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_A"][5]

    @property
    def bms_cell_temp_b1(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_B"][0]

    @property
    def bms_cell_temp_b2(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_B"][1]

    @property
    def bms_cell_temp_b3(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_B"][2]

    @property
    def bms_cell_temp_b4(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_B"][3]

    @property
    def bms_cell_temp_b5(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_B"][4]

    @property
    def bms_cell_temp_b6(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_B"][5]

    @property
    def bms_cell_temp_c1(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_C"][0]

    @property
    def bms_cell_temp_c2(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_C"][1]

    @property
    def bms_cell_temp_c3(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_C"][2]

    @property
    def bms_cell_temp_c4(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_C"][3]

    @property
    def bms_cell_temp_c5(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_C"][4]

    @property
    def bms_cell_temp_c6(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_C"][5]

    @property
    def bms_cell_temp_d1(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_D"][0]

    @property
    def bms_cell_temp_d2(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_D"][1]

    @property
    def bms_cell_temp_d3(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_D"][2]

    @property
    def bms_cell_temp_d4(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_D"][3]

    @property
    def bms_cell_temp_d5(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_D"][4]

    @property
    def bms_cell_temp_d6(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_TEMPERATURES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_TEMPERATURES_MODULE_D"][5]

    @property
    def bms_cell_volt_a1(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_A"][0]

    @property
    def bms_cell_volt_a2(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_A"][1]

    @property
    def bms_cell_volt_a3(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_A"][2]

    @property
    def bms_cell_volt_a4(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_A"][3]

    @property
    def bms_cell_volt_a5(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_A"][4]

    @property
    def bms_cell_volt_a6(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_A"][5]

    @property
    def bms_cell_volt_a7(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_A"][6]

    @property
    def bms_cell_volt_a8(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_A"][7]

    @property
    def bms_cell_volt_a9(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_A"][8]

    @property
    def bms_cell_volt_a10(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_A"][9]

    @property
    def bms_cell_volt_a11(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_A"][10]

    @property
    def bms_cell_volt_a12(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_A"][11]

    @property
    def bms_cell_volt_a13(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_A"][12]

    @property
    def bms_cell_volt_a14(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_A" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_A"][13]

    @property
    def bms_cell_volt_b1(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_B"][0]

    @property
    def bms_cell_volt_b2(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_B"][1]

    @property
    def bms_cell_volt_b3(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_B"][2]

    @property
    def bms_cell_volt_b4(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_B"][3]

    @property
    def bms_cell_volt_b5(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_B"][4]

    @property
    def bms_cell_volt_b6(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_B"][5]

    @property
    def bms_cell_volt_b7(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_B"][6]

    @property
    def bms_cell_volt_b8(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_B"][7]

    @property
    def bms_cell_volt_b9(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_B"][8]

    @property
    def bms_cell_volt_b10(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_B"][9]

    @property
    def bms_cell_volt_b11(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_B"][10]

    @property
    def bms_cell_volt_b12(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_B"][11]

    @property
    def bms_cell_volt_b13(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_B"][12]

    @property
    def bms_cell_volt_b14(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_B" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_B"][13]

    @property
    def bms_cell_volt_c1(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_C"][0]

    @property
    def bms_cell_volt_c2(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_C"][1]

    @property
    def bms_cell_volt_c3(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_C"][2]

    @property
    def bms_cell_volt_c4(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_C"][3]

    @property
    def bms_cell_volt_c5(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_C"][4]

    @property
    def bms_cell_volt_c6(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_C"][5]

    @property
    def bms_cell_volt_c7(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_C"][6]

    @property
    def bms_cell_volt_c8(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_C"][7]

    @property
    def bms_cell_volt_c9(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_C"][8]

    @property
    def bms_cell_volt_c10(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_C"][9]

    @property
    def bms_cell_volt_c11(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_C"][10]

    @property
    def bms_cell_volt_c12(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_C"][11]

    @property
    def bms_cell_volt_c13(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_C"][12]

    @property
    def bms_cell_volt_c14(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_C" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_C"][13]

    @property
    def bms_cell_volt_d1(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_D"][0]

    @property
    def bms_cell_volt_d2(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_D"][1]

    @property
    def bms_cell_volt_d3(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_D"][2]

    @property
    def bms_cell_volt_d4(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_D"][3]

    @property
    def bms_cell_volt_d5(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_D"][4]

    @property
    def bms_cell_volt_d6(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_D"][5]

    @property
    def bms_cell_volt_d7(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_D"][6]

    @property
    def bms_cell_volt_d8(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_D"][7]

    @property
    def bms_cell_volt_d9(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_D"][8]

    @property
    def bms_cell_volt_d10(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_D"][9]

    @property
    def bms_cell_volt_d11(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_D"][10]

    @property
    def bms_cell_volt_d12(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_D"][11]

    @property
    def bms_cell_volt_d13(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_D"][12]

    @property
    def bms_cell_volt_d14(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CELL_VOLTAGES_MODULE_D" in self._raw["BMS"]:
            return self._raw["BMS"]["CELL_VOLTAGES_MODULE_D"][13]

    @property
    def bms_soc_a(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "SOC" in self._raw["BMS"]:
            return self._raw["BMS"]["SOC"][0]

    @property
    def bms_soc_b(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "SOC" in self._raw["BMS"]:
            return self._raw["BMS"]["SOC"][1]

    @property
    def bms_soc_c(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "SOC" in self._raw["BMS"]:
            return self._raw["BMS"]["SOC"][2]

    @property
    def bms_soc_d(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "SOC" in self._raw["BMS"]:
            return self._raw["BMS"]["SOC"][3]

    @property
    def bms_soh_a(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "SOH" in self._raw["BMS"]:
            return self._raw["BMS"]["SOH"][0]

    @property
    def bms_soh_b(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "SOH" in self._raw["BMS"]:
            return self._raw["BMS"]["SOH"][1]

    @property
    def bms_soh_c(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "SOH" in self._raw["BMS"]:
            return self._raw["BMS"]["SOH"][2]

    @property
    def bms_soh_d(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "SOH" in self._raw["BMS"]:
            return self._raw["BMS"]["SOH"][3]

    @property
    def bms_voltage_a(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "VOLTAGE" in self._raw["BMS"]:
            return self._raw["BMS"]["VOLTAGE"][0]

    @property
    def bms_voltage_b(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "VOLTAGE" in self._raw["BMS"]:
            return self._raw["BMS"]["VOLTAGE"][1]

    @property
    def bms_voltage_c(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "VOLTAGE" in self._raw["BMS"]:
            return self._raw["BMS"]["VOLTAGE"][2]

    @property
    def bms_voltage_d(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "VOLTAGE" in self._raw["BMS"]:
            return self._raw["BMS"]["VOLTAGE"][3]

    @property
    def bms_current_a(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CURRENT" in self._raw["BMS"]:
            return self._raw["BMS"]["CURRENT"][0]

    @property
    def bms_current_b(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CURRENT" in self._raw["BMS"]:
            return self._raw["BMS"]["CURRENT"][1]

    @property
    def bms_current_c(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CURRENT" in self._raw["BMS"]:
            return self._raw["BMS"]["CURRENT"][2]

    @property
    def bms_current_d(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CURRENT" in self._raw["BMS"]:
            return self._raw["BMS"]["CURRENT"][3]

    @property
    def bms_cycles_a(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CYCLES" in self._raw["BMS"]:
            return self._raw["BMS"]["CYCLES"][0]

    @property
    def bms_cycles_b(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CYCLES" in self._raw["BMS"]:
            return self._raw["BMS"]["CYCLES"][1]

    @property
    def bms_cycles_c(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CYCLES" in self._raw["BMS"]:
            return self._raw["BMS"]["CYCLES"][2]

    @property
    def bms_cycles_d(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "CYCLES" in self._raw["BMS"]:
            return self._raw["BMS"]["CYCLES"][3]

    @property
    def bms_fw_a(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "FW" in self._raw["BMS"]:
            return self._raw["BMS"]["FW"][0]

    @property
    def bms_fw_b(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "FW" in self._raw["BMS"]:
            return self._raw["BMS"]["FW"][1]

    @property
    def bms_fw_c(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "FW" in self._raw["BMS"]:
            return self._raw["BMS"]["FW"][2]

    @property
    def bms_fw_d(self) -> float:
        if hasattr(self, '_raw') and "BMS" in self._raw and "FW" in self._raw["BMS"]:
            return self._raw["BMS"]["FW"][3]

    @property
    def wallbox_1_state(self) -> str:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "STATE" in self._raw[SENEC_SECTION_WALLBOX]:
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
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "L1_CHARGING_CURRENT" in self._raw[
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
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "EV_CONNECTED" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["EV_CONNECTED"][0]

    @property
    def wallbox_1_energy(self) -> float:
        """
        Wallbox Total Energy
        """
        if hasattr(self, '_raw') and SENEC_SECTION_STATISTIC in self._raw and "LIVE_WB_ENERGY" in self._raw[
            SENEC_SECTION_STATISTIC]:
            return self._raw[SENEC_SECTION_STATISTIC]["LIVE_WB_ENERGY"][0]

    @property
    def wallbox_1_l1_used(self) -> bool:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L1_USED"][0] == 1

    @property
    def wallbox_1_l2_used(self) -> bool:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L2_USED"][0] == 1

    @property
    def wallbox_1_l3_used(self) -> bool:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L3_USED"][0] == 1

    @property
    def wallbox_1_l1_charging_current(self) -> float:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "L1_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L1_CHARGING_CURRENT"][0]

    @property
    def wallbox_1_l2_charging_current(self) -> float:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "L2_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L2_CHARGING_CURRENT"][0]

    @property
    def wallbox_1_l3_charging_current(self) -> float:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "L3_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L3_CHARGING_CURRENT"][0]

    @property
    def wallbox_1_min_charging_current(self) -> float:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "MIN_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["MIN_CHARGING_CURRENT"][0]

    @property
    def wallbox_2_state(self) -> str:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "STATE" in self._raw[SENEC_SECTION_WALLBOX]:
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
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "L1_CHARGING_CURRENT" in self._raw[
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
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "EV_CONNECTED" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["EV_CONNECTED"][1]

    @property
    def wallbox_2_energy(self) -> float:
        """
        Wallbox Total Energy
        """
        if hasattr(self, '_raw') and SENEC_SECTION_STATISTIC in self._raw and "LIVE_WB_ENERGY" in self._raw[
            SENEC_SECTION_STATISTIC]:
            return self._raw[SENEC_SECTION_STATISTIC]["LIVE_WB_ENERGY"][1]

    @property
    def wallbox_2_l1_used(self) -> bool:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L1_USED"][1] == 1

    @property
    def wallbox_2_l2_used(self) -> bool:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L2_USED"][1] == 1

    @property
    def wallbox_2_l3_used(self) -> bool:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L3_USED"][1] == 1

    @property
    def wallbox_2_l1_charging_current(self) -> float:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "L1_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L1_CHARGING_CURRENT"][1]

    @property
    def wallbox_2_l2_charging_current(self) -> float:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "L2_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L2_CHARGING_CURRENT"][1]

    @property
    def wallbox_2_l3_charging_current(self) -> float:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "L3_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L3_CHARGING_CURRENT"][1]

    @property
    def wallbox_2_min_charging_current(self) -> float:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "MIN_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["MIN_CHARGING_CURRENT"][1]

    @property
    def wallbox_3_state(self) -> str:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "STATE" in self._raw[SENEC_SECTION_WALLBOX]:
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
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "L1_CHARGING_CURRENT" in self._raw[
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
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "EV_CONNECTED" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["EV_CONNECTED"][2]

    @property
    def wallbox_3_energy(self) -> float:
        """
        Wallbox Total Energy
        """
        if hasattr(self, '_raw') and SENEC_SECTION_STATISTIC in self._raw and "LIVE_WB_ENERGY" in self._raw[
            SENEC_SECTION_STATISTIC]:
            return self._raw[SENEC_SECTION_STATISTIC]["LIVE_WB_ENERGY"][2]

    @property
    def wallbox_3_l1_used(self) -> bool:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L1_USED"][2] == 1

    @property
    def wallbox_3_l2_used(self) -> bool:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L2_USED"][2] == 1

    @property
    def wallbox_3_l3_used(self) -> bool:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L3_USED"][2] == 1

    @property
    def wallbox_3_l1_charging_current(self) -> float:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "L1_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L1_CHARGING_CURRENT"][2]

    @property
    def wallbox_3_l2_charging_current(self) -> float:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "L2_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L2_CHARGING_CURRENT"][2]

    @property
    def wallbox_3_l3_charging_current(self) -> float:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "L3_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L3_CHARGING_CURRENT"][2]

    @property
    def wallbox_3_min_charging_current(self) -> float:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "MIN_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["MIN_CHARGING_CURRENT"][2]

    @property
    def wallbox_4_state(self) -> str:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "STATE" in self._raw[SENEC_SECTION_WALLBOX]:
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
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "L1_CHARGING_CURRENT" in self._raw[
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
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "EV_CONNECTED" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["EV_CONNECTED"][3]

    @property
    def wallbox_4_energy(self) -> float:
        """
        Wallbox Total Energy
        """
        if hasattr(self, '_raw') and SENEC_SECTION_STATISTIC in self._raw and "LIVE_WB_ENERGY" in self._raw[
            SENEC_SECTION_STATISTIC]:
            return self._raw[SENEC_SECTION_STATISTIC]["LIVE_WB_ENERGY"][3]

    @property
    def wallbox_4_l1_used(self) -> bool:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L1_USED"][3] == 1

    @property
    def wallbox_4_l2_used(self) -> bool:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L2_USED"][3] == 1

    @property
    def wallbox_4_l3_used(self) -> bool:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L3_USED"][3] == 1

    @property
    def wallbox_4_l1_charging_current(self) -> float:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "L1_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L1_CHARGING_CURRENT"][3]

    @property
    def wallbox_4_l2_charging_current(self) -> float:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "L2_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L2_CHARGING_CURRENT"][3]

    @property
    def wallbox_4_l3_charging_current(self) -> float:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "L3_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L3_CHARGING_CURRENT"][3]

    @property
    def wallbox_4_min_charging_current(self) -> float:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "MIN_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["MIN_CHARGING_CURRENT"][3]

    @property
    def fan_inv_lv(self) -> bool:
        if hasattr(self, '_raw') and SENEC_SECTION_FAN_SPEED in self._raw and "INV_LV" in self._raw[
            SENEC_SECTION_FAN_SPEED]:
            return self._raw[SENEC_SECTION_FAN_SPEED]["INV_LV"] > 0

    @property
    def fan_inv_hv(self) -> bool:
        if hasattr(self, '_raw') and SENEC_SECTION_FAN_SPEED in self._raw and "INV_HV" in self._raw[
            SENEC_SECTION_FAN_SPEED]:
            return self._raw[SENEC_SECTION_FAN_SPEED]["INV_HV"] > 0

    @property
    def sockets_already_switched(self) -> [int]:
        if hasattr(self, '_raw') and SENEC_SECTION_SOCKETS in self._raw and "ALREADY_SWITCHED" in self._raw[
            SENEC_SECTION_SOCKETS]:
            return self._raw[SENEC_SECTION_SOCKETS]["ALREADY_SWITCHED"]

    @property
    def sockets_power_on(self) -> [float]:
        if hasattr(self, '_raw') and SENEC_SECTION_SOCKETS in self._raw and "POWER_ON" in self._raw[
            SENEC_SECTION_SOCKETS]:
            return self._raw[SENEC_SECTION_SOCKETS]["POWER_ON"]

    @property
    def sockets_priority(self) -> [float]:
        if hasattr(self, '_raw') and SENEC_SECTION_SOCKETS in self._raw and "PRIORITY" in self._raw[
            SENEC_SECTION_SOCKETS]:
            return self._raw[SENEC_SECTION_SOCKETS]["PRIORITY"]

    @property
    def sockets_time_rem(self) -> [float]:
        if hasattr(self, '_raw') and SENEC_SECTION_SOCKETS in self._raw and "TIME_REM" in self._raw[
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
            SENEC_SECTION_ENERGY: {
                "STAT_STATE": "",
                "GUI_GRID_POW": "",
                "GUI_HOUSE_POW": "",
                "GUI_INVERTER_POWER": "",
                "GUI_BAT_DATA_FUEL_CHARGE": "",
                "GUI_BAT_DATA_POWER": "",
                "GUI_BAT_DATA_VOLTAGE": "",
                "GUI_BAT_DATA_CURRENT": "",
                "SAFE_CHARGE_RUNNING": "",
                "LI_STORAGE_MODE_RUNNING": ""
            },
            # SENEC_SECTION_STATISTIC: {
            #    "LIVE_BAT_CHARGE": "",
            #    "LIVE_BAT_DISCHARGE": "",
            #    "LIVE_GRID_EXPORT": "",
            #    "LIVE_GRID_IMPORT": "",
            #    "LIVE_HOUSE_CONS": "",
            #    "LIVE_PV_GEN": "",
            #    "LIVE_WB_ENERGY": "",
            # },
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
            # "BMS": {
            #    "CELL_TEMPERATURES_MODULE_A": "",
            #    "CELL_TEMPERATURES_MODULE_B": "",
            #    "CELL_TEMPERATURES_MODULE_C": "",
            #    "CELL_TEMPERATURES_MODULE_D": "",
            #    "CELL_VOLTAGES_MODULE_A": "",
            #    "CELL_VOLTAGES_MODULE_B": "",
            #    "CELL_VOLTAGES_MODULE_C": "",
            #    "CELL_VOLTAGES_MODULE_D": "",
            #    "CURRENT": "",
            #    "VOLTAGE": "",
            #    "SOC": "",
            #    "SOH": "",
            #    "CYCLES": "",
            # },
            # SENEC_SECTION_WALLBOX: {
            #    "L1_CHARGING_CURRENT": "",
            #    "L2_CHARGING_CURRENT": "",
            #    "L3_CHARGING_CURRENT": "",
            #    "EV_CONNECTED": ""
            # },
            # SENEC_SECTION_FAN_SPEED: {},
        }
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
                "CYCLES": ""}
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
                self._raw = parse(await res.json())
            except JSONDecodeError as exc:
                _LOGGER.warning(f"JSONDecodeError while 'await res.json()' {exc}")

    async def read_senec_energy(self):
        form = {
            SENEC_SECTION_ENERGY: {
                "STAT_STATE": "",
                "GUI_GRID_POW": "",
                "GUI_HOUSE_POW": "",
                "GUI_INVERTER_POWER": "",
                "GUI_BAT_DATA_POWER": "",
                "GUI_BAT_DATA_VOLTAGE": "",
                "GUI_BAT_DATA_CURRENT": ""
            }
        }

        async with self.web_session.post(self.url, json=form, ssl=False) as res:
            try:
                res.raise_for_status()
                self._energy_raw = parse(await res.json())
            except JSONDecodeError as exc:
                _LOGGER.warning(f"JSONDecodeError while 'await res.json()' {exc}")

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
        if hasattr(self, '_raw'):
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
        if hasattr(self, '_raw'):
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

    @property
    def wallbox_allow_intercharge(self) -> bool:
        # please note this is not ARRAY data - so we code it here again...
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "ALLOW_INTERCHARGE" in self._raw[
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
        await self.switch_array_post(SENEC_SECTION_SOCKETS, "ENABLE", pos, 2, value);

    @property
    def sockets_force_on(self) -> [int]:
        return self.read_array_data(SENEC_SECTION_SOCKETS, "FORCE_ON")

    async def switch_array_sockets_force_on(self, pos: int, value: bool):
        await self.switch_array_post(SENEC_SECTION_SOCKETS, "FORCE_ON", pos, 2, value);

    @property
    def sockets_use_time(self) -> [int]:
        return self.read_array_data(SENEC_SECTION_SOCKETS, "USE_TIME")

    async def switch_array_sockets_use_time(self, pos: int, value: bool):
        await self.switch_array_post(SENEC_SECTION_SOCKETS, "USE_TIME", pos, 2, value);

    @property
    def wallbox_smart_charge_active(self) -> [int]:
        return self.read_array_data(SENEC_SECTION_WALLBOX, "SMART_CHARGE_ACTIVE")

    # SET the "switch" SMART_CHARGE_ACTIVE is a bit different, since the ON value is not 01 - it's (for what
    # ever reason 03)...
    async def switch_array_smart_charge_active(self, pos: int, value: int):
        await self.set_nva_post(SENEC_SECTION_WALLBOX, "SMART_CHARGE_ACTIVE", pos, 4, "u8", value)

    @property
    def wallbox_prohibit_usage(self) -> [int]:
        return self.read_array_data(SENEC_SECTION_WALLBOX, "PROHIBIT_USAGE")

    async def switch_array_wallbox_prohibit_usage(self, pos: int, value: bool, sync: bool = True):
        await self.switch_array_post(SENEC_SECTION_WALLBOX, "PROHIBIT_USAGE", pos, 4, value);
        if sync and IntBridge.avail():
            mode = None
            if value:
                mode = APP_API_WEB_MODE_LOCKED
            else:
                mode = APP_API_WEB_MODE_SSGCM
                if IntBridge.app_api._app_last_wallbox_modes[pos] is not None:
                    mode = IntBridge.app_api._app_last_wallbox_modes[pos]

            await IntBridge.app_api.app_set_wallbox_mode(mode_to_set_in_lc=mode, wallbox_num=(pos + 1), sync=False)

    def read_array_data(self, section_key: str, array_values_key) -> []:
        if hasattr(self, '_raw') and section_key in self._raw and array_values_key in self._raw[section_key]:
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

    async def set_nva_sockets_lower_limit(self, pos: int, value: int):
        await self.set_nva_post(SENEC_SECTION_SOCKETS, "LOWER_LIMIT", pos, 2, "u1", value)

    @property
    def sockets_upper_limit(self) -> [int]:
        return self.read_array_data(SENEC_SECTION_SOCKETS, "UPPER_LIMIT")

    async def set_nva_sockets_upper_limit(self, pos: int, value: int):
        await self.set_nva_post(SENEC_SECTION_SOCKETS, "UPPER_LIMIT", pos, 2, "u1", value)

    @property
    def sockets_power_on_time(self) -> [int]:
        return self.read_array_data(SENEC_SECTION_SOCKETS, "POWER_ON_TIME")

    async def set_nva_sockets_power_on_time(self, pos: int, value: int):
        await self.set_nva_post(SENEC_SECTION_SOCKETS, "POWER_ON_TIME", pos, 2, "u1", value)

    @property
    def sockets_switch_on_hour(self) -> [int]:
        return self.read_array_data(SENEC_SECTION_SOCKETS, "SWITCH_ON_HOUR")

    async def set_nva_sockets_switch_on_hour(self, pos: int, value: int):
        await self.set_nva_post(SENEC_SECTION_SOCKETS, "SWITCH_ON_HOUR", pos, 2, "u8", value)

    @property
    def sockets_switch_on_minute(self) -> [int]:
        return self.read_array_data(SENEC_SECTION_SOCKETS, "SWITCH_ON_MINUTE")

    async def set_nva_sockets_switch_on_minute(self, pos: int, value: int):
        await self.set_nva_post(SENEC_SECTION_SOCKETS, "SWITCH_ON_MINUTE", pos, 2, "u8", value)

    @property
    def sockets_time_limit(self) -> [int]:
        return self.read_array_data(SENEC_SECTION_SOCKETS, "TIME_LIMIT")

    async def set_nva_sockets_time_limit(self, pos: int, value: int):
        await self.set_nva_post(SENEC_SECTION_SOCKETS, "TIME_LIMIT", pos, 2, "u1", value)

    @property
    def wallbox_set_icmax(self) -> [float]:
        return self.read_array_data(SENEC_SECTION_WALLBOX, "SET_ICMAX")

    async def set_nva_wallbox_set_icmax(self, pos: int, value: float, sync: bool = True):
        await self.set_nva_post(SENEC_SECTION_WALLBOX, "SET_ICMAX", pos, 4, "fl", value)
        if sync and IntBridge.avail():
            await IntBridge.app_api.app_set_wallbox_icmax(value_to_set=value, wallbox_num=(pos + 1), sync=False)

    @property
    def wallbox_set_idefault(self) -> [int]:
        return self.read_array_data(SENEC_SECTION_WALLBOX, "SET_IDEFAULT")

    async def set_nva_wallbox_set_idefault(self, pos: int, value: int):
        await self.set_nva_post(SENEC_SECTION_WALLBOX, "SET_IDEFAULT", pos, 4, "fl", value)

    async def set_number_value_array(self, array_key: str, array_pos: int, value: int):
        return await getattr(self, 'set_nva_' + str(array_key))(array_pos, value)

    @property
    def wallbox_1_mode(self) -> str:
        if IntBridge.avail() and IntBridge.app_api._app_raw_wallbox[0] is not None:
            if "chargingMode" in IntBridge.app_api._app_raw_wallbox[0]:
                return IntBridge.app_api._app_raw_wallbox[0]["chargingMode"].lower()

    async def set_string_value_wallbox_1_mode(self, value: str):
        await self._set_wallbox_mode_post(0, value)
        if IntBridge.avail():
            await IntBridge.app_api.app_set_wallbox_mode(mode_to_set_in_lc=value, wallbox_num=1, sync=False)

    @property
    def wallbox_2_mode(self) -> str:
        if IntBridge.avail() and IntBridge.app_api._app_raw_wallbox[1] is not None:
            if "chargingMode" in IntBridge.app_api._app_raw_wallbox[1]:
                return IntBridge.app_api._app_raw_wallbox[1]["chargingMode"].lower()

    async def set_string_value_wallbox_2_mode(self, value: str):
        await self._set_wallbox_mode_post(1, value)
        if IntBridge.avail():
            await IntBridge.app_api.app_set_wallbox_mode(mode_to_set_in_lc=value, wallbox_num=2, sync=False)

    @property
    def wallbox_3_mode(self) -> str:
        if IntBridge.avail() and IntBridge.app_api._app_raw_wallbox[2] is not None:
            if "chargingMode" in IntBridge.app_api._app_raw_wallbox[2]:
                return IntBridge.app_api._app_raw_wallbox[2]["chargingMode"].lower()

    async def set_string_value_wallbox_3_mode(self, value: str):
        await self._set_wallbox_mode_post(2, value)
        if IntBridge.avail():
            await IntBridge.app_api.app_set_wallbox_mode(mode_to_set_in_lc=value, wallbox_num=3, sync=False)

    @property
    def wallbox_4_mode(self) -> str:
        if IntBridge.avail() and IntBridge.app_api._app_raw_wallbox[3] is not None:
            if "chargingMode" in IntBridge.app_api._app_raw_wallbox[3]:
                return IntBridge.app_api._app_raw_wallbox[3]["chargingMode"].lower()

    async def set_string_value_wallbox_4_mode(self, value: str):
        await self._set_wallbox_mode_post(3, value)
        if IntBridge.avail():
            await IntBridge.app_api.app_set_wallbox_mode(mode_to_set_in_lc=value, wallbox_num=4, sync=False)

    async def _set_wallbox_mode_post(self, pos:int, value: str):
        if value == APP_API_WEB_MODE_LOCKED:
            await self.set_multi_post(4, pos,
                                      SENEC_SECTION_WALLBOX, "PROHIBIT_USAGE", "u8", 1,
                                      SENEC_SECTION_WALLBOX, "SMART_CHARGE_ACTIVE", "u8", 0)
        elif value == APP_API_WEB_MODE_SSGCM:
            await self.set_multi_post(4, pos,
                                      SENEC_SECTION_WALLBOX, "PROHIBIT_USAGE", "u8", 0,
                                      SENEC_SECTION_WALLBOX, "SMART_CHARGE_ACTIVE", "u8", 3)
        else:
            await self.set_multi_post(4, pos,
                                      SENEC_SECTION_WALLBOX, "PROHIBIT_USAGE", "u8", 0,
                                      SENEC_SECTION_WALLBOX, "SMART_CHARGE_ACTIVE", "u8", 0)


    async def set_string_value(self, key: str, value: str):
        return await getattr(self, 'set_string_value_' + key)(value)

    """NORMAL NUMBER HANDLING... currently no 'none-array' entities are implemented"""

    async def set_number_value(self, array_key: str, value: int):
        # this will cause a method not found exception...
        return await getattr(self, 'set_nv_' + str(array_key))(value)

    async def switch_array_post(self, section_key: str, value_key: str, pos: int, array_length: int, value: bool):
        post_data = {}
        post_data = self.prepare_post_data(post_data, array_length, pos, section_key, value_key, "u8",
                                           value=(1 if value else 0))
        await self.write(post_data)

    async def set_nva_post(self, section_key: str, value_key: str, pos: int, array_length: int, data_type: str, value):
        post_data = {}
        post_data = self.prepare_post_data(post_data, array_length, pos, section_key, value_key, data_type, value)
        await self.write(post_data)

    async def set_multi_post(self, array_length: int, pos: int,
                             section_key1: str, value_key1: str, data_type1: str, value1,
                             section_key2: str, value_key2: str, data_type2: str, value2
                             ):
        post_data = {}
        post_data = self.prepare_post_data(post_data, array_length, pos, section_key1, value_key1, data_type1, value1)
        post_data = self.prepare_post_data(post_data, array_length, pos, section_key2, value_key2, data_type2, value2)
        await self.write(post_data)

    def prepare_post_data(self, post_data: dict, array_length: int, pos: int, section_key: str, value_key: str,
                          data_type: str, value) -> dict:
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
        return post_data

    async def write(self, data):
        await self.write_senec_v31(data)

    async def write_senec_v31(self, data):
        _LOGGER.debug(f"posting data: {data}")
        async with self.web_session.post(self.url, json=data, ssl=False) as res:
            try:
                res.raise_for_status()
                self._raw_post = parse(await res.json())
                _LOGGER.debug(f"post result: {self._raw_post}")
            except JSONDecodeError as exc:
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
            self._raw_version = xmltodict.parse(txt)
            last_dev = ''
            for a_entry in self._raw_version["root"]["Device"]["Versions"]["Software"]:
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
            for a_entry in self._raw["root"]["Device"]["Measurements"]["Measurement"]:
                if '@Type' in a_entry:
                    if a_entry["@Type"] == 'AC_Voltage':
                        if '@Value' in a_entry:
                            self._ac_voltage = a_entry["@Value"]
                    if a_entry["@Type"] == 'AC_Current':
                        if '@Value' in a_entry:
                            self._ac_current = a_entry["@Value"]
                    if a_entry["@Type"] == 'AC_Power':
                        if '@Value' in a_entry:
                            self._ac_power = a_entry["@Value"]
                    if a_entry["@Type"] == 'AC_Power_fast':
                        if '@Value' in a_entry:
                            self._ac_power_fast = a_entry["@Value"]
                    if a_entry["@Type"] == 'AC_Frequency':
                        if '@Value' in a_entry:
                            self._ac_frequency = a_entry["@Value"]

                    if a_entry["@Type"] == 'BDC_BAT_Voltage':
                        if '@Value' in a_entry:
                            self._bdc_bat_voltage = a_entry["@Value"]
                    if a_entry["@Type"] == 'BDC_BAT_Current':
                        if '@Value' in a_entry:
                            self._bdc_bat_current = a_entry["@Value"]
                    if a_entry["@Type"] == 'BDC_BAT_Power':
                        if '@Value' in a_entry:
                            self._bdc_bat_power = a_entry["@Value"]
                    if a_entry["@Type"] == 'BDC_LINK_Voltage':
                        if '@Value' in a_entry:
                            self._bdc_link_voltage = a_entry["@Value"]
                    if a_entry["@Type"] == 'BDC_LINK_Current':
                        if '@Value' in a_entry:
                            self._bdc_link_current = a_entry["@Value"]
                    if a_entry["@Type"] == 'BDC_LINK_Power':
                        if '@Value' in a_entry:
                            self._bdc_link_power = a_entry["@Value"]

                    if a_entry["@Type"] == 'DC_Voltage1':
                        if '@Value' in a_entry:
                            self._dc_voltage1 = a_entry["@Value"]
                    if a_entry["@Type"] == 'DC_Voltage2':
                        if '@Value' in a_entry:
                            self._dc_voltage2 = a_entry["@Value"]
                    if a_entry["@Type"] == 'DC_Current1':
                        if '@Value' in a_entry:
                            self._dc_current1 = a_entry["@Value"]
                    if a_entry["@Type"] == 'DC_Current2':
                        if '@Value' in a_entry:
                            self._dc_current2 = a_entry["@Value"]
                    if a_entry["@Type"] == 'LINK_Voltage':
                        if '@Value' in a_entry:
                            self._link_voltage = a_entry["@Value"]

                    if a_entry["@Type"] == 'GridPower':
                        if '@Value' in a_entry:
                            self._gridpower = a_entry["@Value"]
                    if a_entry["@Type"] == 'GridConsumedPower':
                        if '@Value' in a_entry:
                            self._gridconsumedpower = a_entry["@Value"]
                    if a_entry["@Type"] == 'GridInjectedPower':
                        if '@Value' in a_entry:
                            self._gridinjectedpower = a_entry["@Value"]
                    if a_entry["@Type"] == 'OwnConsumedPower':
                        if '@Value' in a_entry:
                            self._ownconsumedpower = a_entry["@Value"]

                    if a_entry["@Type"] == 'Derating':
                        if '@Value' in a_entry:
                            self._derating = float(100.0 - float(a_entry["@Value"]))

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

    def __init__(self, user, pwd, web_session, master_plant_number: int = 0, options: dict = None):
        _LOGGER.info(f"restarting MySenecWebPortal... for user: '{user}' with options: {options}")
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

        self.web_session: aiohttp.websession = web_session

        loop = aiohttp.helpers.get_running_loop(web_session.loop)
        if _require_lib_patch:
            senec_jar = MySenecCookieJar(loop=loop)
            if hasattr(web_session, "_cookie_jar"):
                old_jar = getattr(web_session, "_cookie_jar")
                senec_jar.update_cookies(old_jar._host_only_cookies)
            setattr(self.web_session, "_cookie_jar", senec_jar)

        self._master_plant_number = master_plant_number

        # SENEC API
        self._SENEC_USERNAME = user
        self._SENEC_PASSWORD = pwd

        # https://documenter.getpostman.com/view/10329335/UVCB9ihW#17e2c6c6-fe5e-4ca9-bc2f-dca997adaf90
        # https://documenter.getpostman.com/view/10329335/UVCB9ihW#3e5a4286-c7d2-49d1-8856-12bba9fb5c6e
        self._SENEC_APP_AUTH = "https://app-gateway-prod.senecops.com/v1/senec/login"
        self._SENEC_APP_GET_SYSTEMS = "https://app-gateway-prod.senecops.com/v1/senec/anlagen"
        self._SENEC_APP_GET_ABILITIES = "https://app-gateway-prod.senecops.com/v1/senec/anlagen/%s/abilities"
        self._SENEC_APP_SET_WALLBOX = "https://app-gateway-prod.senecops.com/v1/senec/anlagen/%s/wallboxes/%s"

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
        self._energy_entities = {}
        self._power_entities = {}
        self._battery_entities = {}
        self._spare_capacity = 0  # initialize the spare_capacity with 0
        self._is_authenticated = False
        self._peak_shaving_entities = {}

        # APP-API...
        self._app_is_authenticated = False
        self._app_token = None
        self._app_master_plant_id = None
        self._app_raw_wallbox = [None, None, None, None]
        self._app_last_wallbox_modes = [None, None, None, None]
        self._app_wallbox_num_max = 4

        IntBridge.app_api = self
        if IntBridge.avail():
            # ok mein-senec-web is already existing...
            if IntBridge.lala_cgi._QUERY_WALLBOX_APPAPI:
                self._QUERY_WALLBOX = True
                _LOGGER.debug("APP-API: will query WALLBOX data (cause 'lala_cgi._QUERY_WALLBOX_APPAPI' is True)")

    def check_cookie_jar_type(self):
        if _require_lib_patch:
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

    async def app_authenticate(self, retry: bool = True):
        _LOGGER.debug("***** APP-API: app_authenticate(self) ********")
        auth_payload = {
            "username": self._SENEC_USERNAME,
            "password": self._SENEC_PASSWORD
        }
        async with self.web_session.post(self._SENEC_APP_AUTH, json=auth_payload) as res:
            try:
                res.raise_for_status()
                if res.status == 200:
                    try:
                        r_json = await res.json()
                        if "token" in r_json:
                            self._app_token = r_json["token"]
                            self._app_is_authenticated = True
                            await self.app_get_master_plant_id(retry)
                            if self._app_master_plant_id is not None:
                                _LOGGER.info("APP-API: Login successful")
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

    async def app_get_master_plant_id(self, retry: bool = True):
        _LOGGER.debug("***** APP-API: get_master_plant_id(self) ********")
        if self._app_is_authenticated:
            headers = {"Authorization": self._app_token}
            async with self.web_session.get(self._SENEC_APP_GET_SYSTEMS, headers=headers) as res:
                res.raise_for_status()
                if res.status == 200:
                    try:
                        data = await res.json();
                        idx = self._master_plant_number
                        if len(data) >= idx:
                            if "id" in data[idx]:
                                self._app_master_plant_id = data[idx]["id"]
                                _LOGGER.debug(f"APP-API set _app_master_plant_id to {self._app_master_plant_id}")

                            if "wallboxIds" in data[idx]:
                                self._app_wallbox_num_max = len(data[idx]["wallboxIds"])
                                _LOGGER.debug(f"APP-API set _app_wallbox_num_max to {self._app_wallbox_num_max}")

                    except JSONDecodeError as exc:
                        _LOGGER.warning(f"JSONDecodeError while 'await res.json()' {exc}")
                else:
                    if retry:
                        self._app_is_authenticated = False
                        self._app_token = None
                        self._app_master_plant_id = None
                        await self.app_authenticate(retry=False)
        else:
            if retry:
                await self.app_authenticate(retry=False)

    async def app_get_data(self, a_url: str) -> dict:
        _LOGGER.debug("***** APP-API: app_get_data(self) ********")
        if self._app_token is not None:
            _LOGGER.debug(f"APP-API get {a_url}")
            try:
                headers = {"Authorization": self._app_token}
                async with self.web_session.get(url=a_url, headers=headers) as res:
                    res.raise_for_status()
                    if res.status == 200:
                        try:
                            data = await res.json()
                            return data
                        except JSONDecodeError as exc:
                            _LOGGER.warning(f"APP-API: JSONDecodeError while 'await res.json()' {exc}")

                    elif res.status == 500:
                        _LOGGER.info(f"APP-API: Wallbox Not found {a_url} (http 500)")

                    else:
                        self._app_is_authenticated = False
                        self._app_token = None
                        self._app_master_plant_id = None

                    return None

            except Exception as exc:
                if res.status == 500:
                    _LOGGER.info(f"APP-API: Wallbox Not found {a_url} [HTTP 500]: {exc}")
                if res.status == 400:
                    _LOGGER.info(f"APP-API: Wallbox Not found {a_url} [HTTP 400]: {exc}")
                if res.status == 401:
                    _LOGGER.info(f"APP-API: Wallbox No permission {a_url} [HTTP 401]: {exc}")
                    self._app_is_authenticated = False
                    self._app_token = None
                    self._app_master_plant_id = None
                else:
                    _LOGGER.warning(f"APP-API: Could not get data from {a_url} causing: {exc}")

                return None
        else:
            # somehow we should pass a "callable"...
            await self.app_authenticate()

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

    async def app_update_wallboxes(self):
        _LOGGER.debug(f"APP-API app_update_wallboxes for '{self._app_wallbox_num_max}' wallboxes")
        # ok we go through all possible wallboxes [1-4] and check, if we can receive some
        # data - if there is no data, then we make sure, that next time we do not query
        # this wallbox again...
        if self._app_wallbox_num_max > 0:
            await self.app_get_wallbox_data(wallbox_num=1)
            if self._app_raw_wallbox[0] is None and self._app_wallbox_num_max > 0:
                _LOGGER.debug("APP-API set _app_wallbox_num_max to 0")
                self._app_wallbox_num_max = 0

        if self._app_wallbox_num_max > 1:
            await self.app_get_wallbox_data(wallbox_num=2)
            if self._app_raw_wallbox[1] is None and self._app_wallbox_num_max > 1:
                _LOGGER.debug("APP-API set _app_wallbox_num_max to 1")
                self._app_wallbox_num_max = 1

        if self._app_wallbox_num_max > 2:
            await self.app_get_wallbox_data(wallbox_num=3)
            if self._app_raw_wallbox[2] is None and self._app_wallbox_num_max > 2:
                _LOGGER.debug("APP-API set _app_wallbox_num_max to 2")
                self._app_wallbox_num_max = 2

        if self._app_wallbox_num_max > 3:
            await self.app_get_wallbox_data(wallbox_num=4)
            if self._app_raw_wallbox[3] is None and self._app_wallbox_num_max > 3:
                _LOGGER.debug("APP-API set _app_wallbox_num_max to 3")
                self._app_wallbox_num_max = 3

    async def app_post_data(self, a_url: str, post_data: dict, read_response: bool = False) -> bool:
        _LOGGER.debug("***** APP-API: app_post_data(self) ********")
        if self._app_token is not None:
            _LOGGER.debug(f"APP-API post {post_data} to {a_url}")
            try:
                headers = {"Authorization": self._app_token}
                async with self.web_session.post(url=a_url, headers=headers, json=post_data) as res:
                    res.raise_for_status()
                    if res.status == 200:
                        if read_response:
                            try:
                                data = await res.json()
                                _LOGGER.debug(data)
                                return True
                            except JSONDecodeError as exc:
                                _LOGGER.warning(f"APP-API: JSONDecodeError while 'await res.json()' {exc}")
                        else:
                            _LOGGER.debug(f"OK - {a_url} with '{post_data}'")
                            return True

                    elif res.status == 500:
                        _LOGGER.info(f"APP-API: Not found {a_url} (http 500)")

                    else:
                        self._app_is_authenticated = False
                        self._app_token = None
                        self._app_master_plant_id = None
                        return False

            except Exception as exc:
                if res.status == 500:
                    _LOGGER.info(f"APP-API: Not found {a_url} [HTTP 500]: {exc}")
                if res.status == 400:
                    _LOGGER.info(f"APP-API: Not found {a_url} [HTTP 400]: {exc}")
                if res.status == 401:
                    _LOGGER.info(f"APP-API: No permission {a_url} [HTTP 401]: {exc}")
                    self._app_is_authenticated = False
                    self._app_token = None
                    self._app_master_plant_id = None
                else:
                    _LOGGER.warning(f"APP-API: Could not post to {a_url} data: {post_data} causing: {exc}")

                return False

        else:
            # somehow we should pass a "callable"...
            await self.app_authenticate()
            return False

    async def app_set_wallbox_mode(self, mode_to_set_in_lc: str, wallbox_num: int = 1, sync: bool = True,
                                   retry: bool = True):
        _LOGGER.debug("***** APP-API: app_set_wallbox_mode(self) ********")
        idx = wallbox_num - 1
        if mode_to_set_in_lc == APP_API_WEB_MODE_LOCKED and self._app_raw_wallbox[idx] is not None:
            self._app_last_wallbox_modes[idx] = self._app_raw_wallbox[idx]["chargingMode"].lower()
        else:
            self._app_last_wallbox_modes[idx] = None

        if self._app_master_plant_id is not None:
            data = {
                "mode": mode_to_set_in_lc.upper()
            }
            wb_url = f"{self._SENEC_APP_SET_WALLBOX}" % (str(self._app_master_plant_id), str(wallbox_num))
            success: bool = await self.app_post_data(a_url=wb_url, post_data=data)
            if success:
                # setting the internal storage value...
                if self._app_raw_wallbox[idx] is not None:
                    self._app_raw_wallbox[idx]["chargingMode"] = mode_to_set_in_lc

                # do we need to sync the value back to the 'lala_cgi' integration?
                if sync and IntBridge.avail():
                    if mode_to_set_in_lc == APP_API_WEB_MODE_LOCKED:
                        await IntBridge.lala_cgi.switch_array_wallbox_prohibit_usage(pos=idx, value=True, sync=False)
                    else:
                        await IntBridge.lala_cgi.switch_array_wallbox_prohibit_usage(pos=idx, value=False, sync=False)
        else:
            if retry:
                await self.app_authenticate()
                if self._app_wallbox_num_max >= wallbox_num:
                    await self.app_set_wallbox_mode(mode_to_set_in_lc=mode_to_set_in_lc, wallbox_num=wallbox_num,
                                                    sync=sync, retry=False)
                else:
                    _LOGGER.debug(
                        f"APP-API cancel 'set_wallbox_mode' since after login the max '{self._app_wallbox_num_max}' is < then '{wallbox_num}' (wallbox number to request)")

    async def app_set_wallbox_icmax(self, value_to_set: float, wallbox_num: int = 1, sync: bool = True,
                                    retry: bool = True):
        _LOGGER.debug("***** APP-API: app_set_wallbox_icmax(self) ********")
        if self._app_master_plant_id is not None:
            idx = wallbox_num - 1
            current_mode = APP_API_WEB_MODE_SSGCM
            if self._app_raw_wallbox[idx] is not None and "chargingMode" in self._app_raw_wallbox[idx]:
                current_mode = self._app_raw_wallbox[idx]["chargingMode"]

            data = {
                "mode": current_mode.upper(),
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
            current_mode = APP_API_WEB_MODE_LOCKED
            if self._app_raw_wallbox[idx] is not None and "chargingMode" in self._app_raw_wallbox[idx]:
                current_mode = self._app_raw_wallbox[idx]["chargingMode"]

            data = {
                "mode": current_mode.upper(),
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

        if self._app_wallbox_num_max > 0:
            res = await self.app_set_allow_intercharge(value_to_set=value_to_set, wallbox_num=1, sync=sync)
            if not res and self._app_wallbox_num_max > 0:
                _LOGGER.debug("APP-API set _app_wallbox_num_max to 0")
                self._app_wallbox_num_max = 0

        if self._app_wallbox_num_max > 1:
            res = await self.app_set_allow_intercharge(value_to_set=value_to_set, wallbox_num=2, sync=sync)
            if not res and self._app_wallbox_num_max > 1:
                _LOGGER.debug("APP-API set _app_wallbox_num_max to 2")
                self._app_wallbox_num_max = 1

        if self._app_wallbox_num_max > 2:
            res = await self.app_set_allow_intercharge(value_to_set=value_to_set, wallbox_num=3, sync=sync)
            if not res and self._app_wallbox_num_max > 2:
                _LOGGER.debug("APP-API set _app_wallbox_num_max to 2")
                self._app_wallbox_num_max = 2

        if self._app_wallbox_num_max > 3:
            res = await self.app_set_allow_intercharge(value_to_set=value_to_set, wallbox_num=4, sync=sync)
            if not res and self._app_wallbox_num_max > 3:
                _LOGGER.debug("APP-API set _app_wallbox_num_max to 3")
                self._app_wallbox_num_max = 3

    async def app_get_system_abilities(self):
        if self._app_master_plant_id is not None and self._app_token is not None:
            headers = {"Authorization": self._app_token}
            a_url = f"{self._SENEC_APP_GET_ABILITIES}" % str(self._app_master_plant_id)
            async with self.web_session.get(url=a_url, headers=headers) as res:
                res.raise_for_status()
                if res.status == 200:
                    try:
                        data = await res.json()
                        _LOGGER.info(data)
                    except JSONDecodeError as exc:
                        _LOGGER.warning(f"JSONDecodeError while 'await res.json()' {exc}")
                else:
                    self._app_is_authenticated = False
                    # somehow we should pass a "callable"...
                    await self.app_get_master_plant_id()
        else:
            # somehow we should pass a "callable"...
            await self.app_get_master_plant_id()

    """MEIN-SENEC.DE from here"""

    async def authenticate(self, do_update: bool, throw401: bool):
        _LOGGER.info("***** authenticate(self) ********")
        self.check_cookie_jar_type()
        auth_payload = {
            "username": self._SENEC_USERNAME,
            "password": self._SENEC_PASSWORD
        }
        async with self.web_session.post(self._SENEC_WEB_AUTH, data=auth_payload, max_redirects=20) as res:
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
        if self._is_authenticated:
            _LOGGER.info("***** update(self) ********")
            self.check_cookie_jar_type()
            await self.update_now_kW_stats()
            await self.update_full_kWh_stats()
            if hasattr(self, '_QUERY_SPARE_CAPACITY') and self._QUERY_SPARE_CAPACITY:
                # 1 day = 24 h = 24 * 60 min = 24 * 60 * 60 sec = 86400 sec
                if self._QUERY_SPARE_CAPACITY_TS + 86400 < time():
                    await self.update_spare_capacity()
            #
            if hasattr(self, '_QUERY_PEAK_SHAVING') and self._QUERY_PEAK_SHAVING:
                # 1 day = 24 h = 24 * 60 min = 24 * 60 * 60 sec = 86400 sec
                if self._QUERY_PEAK_SHAVING_TS + 86400 < time():
                    await self.update_peak_shaving()

            if hasattr(self, '_QUERY_WALLBOX') and self._QUERY_WALLBOX:
                await self.app_update_wallboxes()

        else:
            await self.authenticate(do_update=True, throw401=False)

    """This function will update peak shaving information"""

    async def update_peak_shaving(self):
        _LOGGER.info("***** update_peak_shaving(self) ********")
        a_url = f"{self._SENEC_API_GET_PEAK_SHAVING}{self._master_plant_number}"
        async with self.web_session.get(a_url) as res:
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
                    await self.authenticate(do_update=False, throw401=False)
                    await self.set_peak_shaving(new_peak_shaving)

            except ClientResponseError as exc:
                if exc.status == 401:
                    self.purge_senec_cookies()

                self._is_authenticated = False
                await self.authenticate(do_update=False, throw401=True)
                await self.set_peak_shaving(new_peak_shaving)

    """This function will update the spare capacity over the web api"""

    async def update_spare_capacity(self):
        _LOGGER.info("***** update_spare_capacity(self) ********")
        a_url = f"{self._SENEC_API_SPARE_CAPACITY_BASE_URL}{self._master_plant_number}{self._SENEC_API_GET_SPARE_CAPACITY}"
        async with self.web_session.get(a_url) as res:
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
                    await self.authenticate(do_update=False, throw401=False)
                    await self.set_spare_capacity(new_spare_capacity)

            except ClientResponseError as exc:
                if exc.status == 401:
                    self.purge_senec_cookies()

                self._is_authenticated = False
                await self.authenticate(do_update=False, throw401=True)
                await self.set_spare_capacity(new_spare_capacity)

    async def update_now_kW_stats(self):
        _LOGGER.debug("***** update_now_kW_stats(self) ********")
        # grab NOW and TODAY stats
        a_url = f"{self._SENEC_WEB_GET_OVERVIEW_URL}" % str(self._master_plant_number)
        async with self.web_session.get(a_url) as res:
            try:
                res.raise_for_status()
                if res.status == 200:
                    try:
                        r_json = await res.json()
                        self._raw = parse(r_json)
                        for key in (self._API_KEYS + self._API_KEYS_EXTRA):
                            if key in r_json:
                                if key == "acculevel":
                                    if "now" in r_json[key]:
                                        value_now = r_json[key]["now"]
                                        entity_now_name = str(key + "_now")
                                        self._battery_entities[entity_now_name] = value_now
                                    else:
                                        _LOGGER.info(
                                            f"No 'now' for key: '{key}' in json: {r_json} when requesting: {a_url}")
                                else:
                                    if "now" in r_json[key]:
                                        value_now = r_json[key]["now"]
                                        entity_now_name = str(key + "_now")
                                        self._power_entities[entity_now_name] = value_now
                                    else:
                                        _LOGGER.info(
                                            f"No 'now' for key: '{key}' in json: {r_json} when requesting: {a_url}")

                                    if "today" in r_json[key]:
                                        value_today = r_json[key]["today"]
                                        entity_today_name = str(key + "_today")
                                        self._energy_entities[entity_today_name] = value_today
                                    else:
                                        _LOGGER.info(
                                            f"No 'today' for key: '{key}' in json: {r_json} when requesting: {a_url}")

                            else:
                                _LOGGER.info(f"No '{key}' in json: {r_json} when requesting: {a_url}")
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

    async def update_full_kWh_stats(self):
        # grab TOTAL stats

        for key in self._API_KEYS:
            api_url = f"{self._SENEC_WEB_GET_STATUS}" % (key, str(self._master_plant_number))
            async with self.web_session.get(api_url) as res:
                try:
                    res.raise_for_status()
                    if res.status == 200:
                        try:
                            r_json = await res.json()
                            if "fullkwh" in r_json:
                                value = r_json["fullkwh"]
                                entity_name = str(key + "_total")
                                self._energy_entities[entity_name] = value
                            else:
                                _LOGGER.info(f"No 'fullkwh' in json: {r_json} when requesting: {api_url}")
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
            await self.authenticate(do_update=False, throw401=False)

    async def update_get_customer(self):
        _LOGGER.debug("***** update_get_customer(self) ********")

        # grab NOW and TODAY stats
        async with self.web_session.get(self._SENEC_WEB_GET_CUSTOMER) as res:
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
                await self.authenticate(do_update=False, throw401=False)

    async def update_get_systems(self, a_plant_number: int, autodetect_mode: bool):
        _LOGGER.debug("***** update_get_systems(self) ********")

        a_url = f"{self._SENEC_WEB_GET_SYSTEM_INFO}" % str(a_plant_number)
        async with self.web_session.get(a_url) as res:
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
                except JSONDecodeError as exc:
                    _LOGGER.warning(f"JSONDecodeError while 'await res.json()' {exc}")
            else:
                self._is_authenticated = False
                await self.authenticate(do_update=False, throw401=False)

    @property
    def spare_capacity(self) -> int:
        if hasattr(self, '_spare_capacity'):
            return int(self._spare_capacity)

    @property
    def senec_num(self) -> str:
        if hasattr(self, '_dev_number'):
            return str(self._dev_number)

    @property
    def serial_number(self) -> str:
        if hasattr(self, '_serial_number'):
            return str(self._serial_number)

    @property
    def product_name(self) -> str:
        if hasattr(self, '_product_name'):
            return str(self._product_name)

    @property
    def zone_id(self) -> str:
        if hasattr(self, '_zone_id'):
            return str(self._zone_id)

    # @property
    # def firmwareVersion(self) -> str:
    #    if hasattr(self, '_raw') and "firmwareVersion" in self._raw:
    #        return str(self._raw["firmwareVersion"])

    @property
    def masterPlantNumber(self) -> int:
        if hasattr(self, '_master_plant_number'):
            return int(self._master_plant_number)

    @property
    def accuimport_today(self) -> float:
        if hasattr(self, '_energy_entities') and "accuimport_today" in self._energy_entities:
            return self._energy_entities["accuimport_today"]

    @property
    def accuexport_today(self) -> float:
        if hasattr(self, '_energy_entities') and "accuexport_today" in self._energy_entities:
            return self._energy_entities["accuexport_today"]

    @property
    def gridimport_today(self) -> float:
        if hasattr(self, '_energy_entities') and "gridimport_today" in self._energy_entities:
            return self._energy_entities["gridimport_today"]

    @property
    def gridexport_today(self) -> float:
        if hasattr(self, '_energy_entities') and "gridexport_today" in self._energy_entities:
            return self._energy_entities["gridexport_today"]

    @property
    def powergenerated_today(self) -> float:
        if hasattr(self, '_energy_entities') and "powergenerated_today" in self._energy_entities:
            return self._energy_entities["powergenerated_today"]

    @property
    def consumption_today(self) -> float:
        if hasattr(self, '_energy_entities') and "consumption_today" in self._energy_entities:
            return self._energy_entities["consumption_today"]

    @property
    def accuimport_total(self) -> float:
        if hasattr(self, '_energy_entities') and "accuimport_total" in self._energy_entities:
            return self._energy_entities["accuimport_total"]

    @property
    def accuexport_total(self) -> float:
        if hasattr(self, '_energy_entities') and "accuexport_total" in self._energy_entities:
            return self._energy_entities["accuexport_total"]

    @property
    def gridimport_total(self) -> float:
        if hasattr(self, '_energy_entities') and "gridimport_total" in self._energy_entities:
            return self._energy_entities["gridimport_total"]

    @property
    def gridexport_total(self) -> float:
        if hasattr(self, '_energy_entities') and "gridexport_total" in self._energy_entities:
            return self._energy_entities["gridexport_total"]

    @property
    def powergenerated_total(self) -> float:
        if hasattr(self, '_energy_entities') and "powergenerated_total" in self._energy_entities:
            return self._energy_entities["powergenerated_total"]

    @property
    def consumption_total(self) -> float:
        if hasattr(self, '_energy_entities') and "consumption_total" in self._energy_entities:
            return self._energy_entities["consumption_total"]

    @property
    def accuimport_now(self) -> float:
        if hasattr(self, "_power_entities") and "accuimport_now" in self._power_entities:
            return self._power_entities["accuimport_now"]

    @property
    def accuexport_now(self) -> float:
        if hasattr(self, "_power_entities") and "accuexport_now" in self._power_entities:
            return self._power_entities["accuexport_now"]

    @property
    def gridimport_now(self) -> float:
        if hasattr(self, "_power_entities") and "gridimport_now" in self._power_entities:
            return self._power_entities["gridimport_now"]

    @property
    def gridexport_now(self) -> float:
        if hasattr(self, "_power_entities") and "gridexport_now" in self._power_entities:
            return self._power_entities["gridexport_now"]

    @property
    def powergenerated_now(self) -> float:
        if hasattr(self, "_power_entities") and "powergenerated_now" in self._power_entities:
            return self._power_entities["powergenerated_now"]

    @property
    def consumption_now(self) -> float:
        if hasattr(self, "_power_entities") and "consumption_now" in self._power_entities:
            return self._power_entities["consumption_now"]

    @property
    def acculevel_now(self) -> int:
        if hasattr(self, "_battery_entities") and "acculevel_now" in self._battery_entities:
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

    def clear_jar(self):
        self.web_session._cookie_jar.clear()


@staticmethod
@property
def _require_lib_patch() -> bool:
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
