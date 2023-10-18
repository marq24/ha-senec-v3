import aiohttp
import logging

import xmltodict
from time import time
from datetime import datetime

# required to patch the CookieJar of aiohttp - thanks for nothing!
import contextlib
from http.cookies import BaseCookie, SimpleCookie, Morsel
from aiohttp import ClientResponseError
from aiohttp.helpers import is_ip_address
from yarl import URL
from typing import Union, cast

from custom_components.senec.const import (
    QUERY_BMS_KEY,
    QUERY_FANDATA_KEY,
    QUERY_WALLBOX_KEY,
    QUERY_SPARE_CAPACITY_KEY,
    QUERY_PEAK_SHAVING_KEY,
)

from custom_components.senec.pysenec_ha.util import parse
from custom_components.senec.pysenec_ha.constants import (
    SYSTEM_STATE_NAME,
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
    SENEC_SECTION_WALLBOX,

    SENEC_SECTION_FACTORY,
    SENEC_SECTION_SYS_UPDATE,
    SENEC_SECTION_BAT1,
    SENEC_SECTION_WIZARD,
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
BAT_STATUS_CHARGE = {4, 5, 8, 10, 11, 12, 14, 43, 71}

# 16: "DISCHARGE",
# 17: "PV + DISCHARGE",
# 18: "GRID + DISCHARGE"
# 21: "OWN CONSUMPTION"
# 44: "CAPACITY TEST: DISCHARGE",
# 97: "SAFETY DISCHARGE",
BAT_STATUS_DISCHARGE = {16, 17, 18, 21, 44, 97}

_LOGGER = logging.getLogger(__name__)


class Senec:
    """Senec Home Battery Sensor"""

    def __init__(self, host, use_https, websession, lang: str = "en", options: dict = None):
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

        if options is not None and QUERY_FANDATA_KEY in options:
            self._QUERY_FANDATA = options[QUERY_FANDATA_KEY]
        else:
            self._QUERY_FANDATA = False

        self.host = host
        self.websession: aiohttp.websession = websession
        if use_https:
            self.url = f"https://{host}/lala.cgi"
        else:
            self.url = f"http://{host}/lala.cgi"

        # evil HACK - since SENEC does not switch the property fast enough...
        # so for five seconds after the switch take place we will return
        # the 'faked' value
        self._LI_STORAGE_MODE_RUNNING_OVERWRITE_TS = 0
        self._SAFE_CHARGE_RUNNING_OVERWRITE_TS = 0

    @property
    def device_id(self) -> str:
        return self._rawVer[SENEC_SECTION_FACTORY]["DEVICE_ID"]

    @property
    def versions(self) -> str:
        a = self._rawVer[SENEC_SECTION_WIZARD]["APPLICATION_VERSION"]
        b = self._rawVer[SENEC_SECTION_WIZARD]["FIRMWARE_VERSION"]
        c = self._rawVer[SENEC_SECTION_WIZARD]["INTERFACE_VERSION"]
        d = str(self._rawVer[SENEC_SECTION_SYS_UPDATE]["NPU_VER"])
        e = str(self._rawVer[SENEC_SECTION_SYS_UPDATE]["NPU_IMAGE_VERSION"])
        return f"App:{a} FW:{b} NPU-Image:{e}(v{d})"

    @property
    def device_type(self) -> str:
        value = self._rawVer[SENEC_SECTION_FACTORY]["SYS_TYPE"]
        return SYSTEM_TYPE_NAME.get(value, "UNKNOWN")

    @property
    def device_type_internal(self) -> str:
        return self._rawVer[SENEC_SECTION_FACTORY]["SYS_TYPE"]

    @property
    def batt_type(self) -> str:
        value = self._rawVer[SENEC_SECTION_BAT1]["TYPE"]
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

        async with self.websession.post(self.url, json=form, ssl=False) as res:
            res.raise_for_status()
            self._rawVer = parse(await res.json())

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
            if self.is_battery_state_charging():
                return value
        return 0

    @property
    def battery_discharge_power(self) -> float:
        """
        Current battery discharging power (W)
        """
        value = self._raw[SENEC_SECTION_ENERGY]["GUI_BAT_DATA_POWER"]
        if value < 0:
            if self.is_battery_state_discharging():
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

    def is_battery_state_charging(self) -> bool:
        return self._raw[SENEC_SECTION_ENERGY]["STAT_STATE"] in BAT_STATUS_CHARGE

    def is_battery_state_discharging(self) -> bool:
        return self._raw[SENEC_SECTION_ENERGY]["STAT_STATE"] in BAT_STATUS_DISCHARGE

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
    def wallbox_power(self) -> float:
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
    def wallbox_ev_connected(self) -> bool:
        """
        Wallbox EV Connected
        """
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "EV_CONNECTED" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["EV_CONNECTED"][0]

    @property
    def wallbox_energy(self) -> float:
        """
        Wallbox Total Energy
        """
        if hasattr(self, '_raw') and SENEC_SECTION_STATISTIC in self._raw and "LIVE_WB_ENERGY" in self._raw[
            SENEC_SECTION_STATISTIC]:
            return self._raw[SENEC_SECTION_STATISTIC]["LIVE_WB_ENERGY"][0]

    @property
    def wallbox_l1_used(self) -> bool:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L1_USED"][0] == 1

    @property
    def wallbox_l2_used(self) -> bool:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L2_USED"][0] == 1

    @property
    def wallbox_l3_used(self) -> bool:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "L1_USED" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L3_USED"][0] == 1

    @property
    def wallbox_l1_charging_current(self) -> float:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "L1_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L1_CHARGING_CURRENT"][0]

    @property
    def wallbox_l2_charging_current(self) -> float:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "L2_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L2_CHARGING_CURRENT"][0]

    @property
    def wallbox_l3_charging_current(self) -> float:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "L3_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["L3_CHARGING_CURRENT"][0]

    @property
    def wallbox_min_charging_current(self) -> float:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "MIN_CHARGING_CURRENT" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["MIN_CHARGING_CURRENT"][0]

    @property
    def wallbox_set_icmax(self) -> float:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "SET_ICMAX" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["SET_ICMAX"][0]

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
    def wallbox_2_set_icmax(self) -> float:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "SET_ICMAX" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["SET_ICMAX"][1]

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
    def wallbox_3_set_icmax(self) -> float:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "SET_ICMAX" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["SET_ICMAX"][2]

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
    def wallbox_4_set_icmax(self) -> float:
        if hasattr(self, '_raw') and SENEC_SECTION_WALLBOX in self._raw and "SET_ICMAX" in self._raw[
            SENEC_SECTION_WALLBOX]:
            return self._raw[SENEC_SECTION_WALLBOX]["SET_ICMAX"][3]

    @property
    def fan_inv_lv(self) -> bool:
        if hasattr(self, '_raw') and SENEC_SECTION_FAN_SPEED in self._raw and "INV_LV" in self._raw[
            SENEC_SECTION_FAN_SPEED]:
            return self._raw[SENEC_SECTION_FAN_SPEED]["INV_LV"] == 1

    @property
    def fan_inv_hv(self) -> bool:
        if hasattr(self, '_raw') and SENEC_SECTION_FAN_SPEED in self._raw and "INV_HV" in self._raw[
            SENEC_SECTION_FAN_SPEED]:
            return self._raw[SENEC_SECTION_FAN_SPEED]["INV_HV"] == 1

    async def update(self):
        await self.read_senec_lala()

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
                "SET_ICMAX": ""}
            })

        async with self.websession.post(self.url, json=form, ssl=False) as res:
            res.raise_for_status()
            self._raw = parse(await res.json())

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

        async with self.websession.post(self.url, json=form, ssl=False) as res:
            res.raise_for_status()
            self._energy_raw = parse(await res.json())

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
            if self._SAFE_CHARGE_RUNNING_OVERWRITE_TS + 5 > time():
                return self._SAFE_CHARGE_RUNNING_OVERWRITE_VALUE
            else:
                return self._raw[SENEC_SECTION_ENERGY]["SAFE_CHARGE_RUNNING"] == 1

    async def switch_safe_charge(self, value: bool):
        self._SAFE_CHARGE_RUNNING_OVERWRITE_VALUE = value
        self._SAFE_CHARGE_RUNNING_OVERWRITE_TS = time()
        postdata = {}
        if (value):
            self._raw[SENEC_SECTION_ENERGY]["SAFE_CHARGE_RUNNING"] = 1
            postdata = {SENEC_SECTION_ENERGY: {"SAFE_CHARGE_FORCE": "u8_01", "SAFE_CHARGE_PROHIBIT": "",
                                               "SAFE_CHARGE_RUNNING": "",
                                               "LI_STORAGE_MODE_START": "", "LI_STORAGE_MODE_STOP": "",
                                               "LI_STORAGE_MODE_RUNNING": ""}}
        else:
            self._raw[SENEC_SECTION_ENERGY]["SAFE_CHARGE_RUNNING"] = 0
            postdata = {SENEC_SECTION_ENERGY: {"SAFE_CHARGE_FORCE": "", "SAFE_CHARGE_PROHIBIT": "u8_01",
                                               "SAFE_CHARGE_RUNNING": "",
                                               "LI_STORAGE_MODE_START": "", "LI_STORAGE_MODE_STOP": "",
                                               "LI_STORAGE_MODE_RUNNING": ""}}

        await self.write(postdata)

    @property
    def li_storage_mode(self) -> bool:
        if hasattr(self, '_raw'):
            # if it just has been switched on/off we provide a FAKE value for 5 sec...
            # since senec unit do not react 'instant' on some requests...
            if self._LI_STORAGE_MODE_RUNNING_OVERWRITE_TS + 5 > time():
                return self._LI_STORAGE_MODE_RUNNING_OVERWRITE_VALUE
            else:
                return self._raw[SENEC_SECTION_ENERGY]["LI_STORAGE_MODE_RUNNING"] == 1

    async def switch_li_storage_mode(self, value: bool):
        self._LI_STORAGE_MODE_RUNNING_OVERWRITE_VALUE = value
        self._LI_STORAGE_MODE_RUNNING_OVERWRITE_TS = time()
        postdata = {}
        if (value):
            self._raw[SENEC_SECTION_ENERGY]["LI_STORAGE_MODE_RUNNING"] = 1
            postdata = {
                SENEC_SECTION_ENERGY: {"SAFE_CHARGE_FORCE": "", "SAFE_CHARGE_PROHIBIT": "", "SAFE_CHARGE_RUNNING": "",
                                       "LI_STORAGE_MODE_START": "u8_01", "LI_STORAGE_MODE_STOP": "",
                                       "LI_STORAGE_MODE_RUNNING": ""}}
        else:
            self._raw[SENEC_SECTION_ENERGY]["LI_STORAGE_MODE_RUNNING"] = 0
            postdata = {
                SENEC_SECTION_ENERGY: {"SAFE_CHARGE_FORCE": "", "SAFE_CHARGE_PROHIBIT": "", "SAFE_CHARGE_RUNNING": "",
                                       "LI_STORAGE_MODE_START": "", "LI_STORAGE_MODE_STOP": "u8_01",
                                       "LI_STORAGE_MODE_RUNNING": ""}}

        await self.write(postdata)

    async def switch(self, switch_key, value):
        return await getattr(self, 'switch_' + str(switch_key))(value)

    async def write(self, data):
        await self.write_senec_v31(data)

    async def write_senec_v31(self, data):
        async with self.websession.post(self.url, json=data, ssl=False) as res:
            res.raise_for_status()
            self._rawPost = parse(await res.json())


class Inverter:
    """Senec Home Inverter addon"""

    def __init__(self, host, websession):
        self.host = host
        self.websession: aiohttp.websession = websession
        self.url1 = f"http://{host}/all.xml"
        self.url2 = f"http://{host}/measurements.xml"
        self.url3 = f"http://{host}/versions.xml"
        self._version_infos = ''
        self._has_bdc = False

    async def update_version(self):
        await self.read_inverter_version()

    async def read_inverter_version(self):
        async with self.websession.get(self.url3) as res:
            res.raise_for_status()
            txt = await res.text()
            self._rawVer = xmltodict.parse(txt)
            lastDev = ''
            for aEntry in self._rawVer["root"]["Device"]["Versions"]["Software"]:
                if '@Name' in aEntry:
                    aDev = aEntry["@Device"]
                    if (not self._has_bdc):
                        self._has_bdc = aDev == 'BDC'
                    if (aDev != lastDev):
                        if (len(self._version_infos) > 0):
                            self._version_infos = self._version_infos + '\n'
                        self._version_infos = self._version_infos + "[" + aDev + "]:\t"
                    else:
                        if (len(self._version_infos) > 0):
                            self._version_infos = self._version_infos + '|'
                    self._version_infos = self._version_infos + aEntry["@Name"] + ' v' + aEntry["@Version"]
                    lastDev = aDev

    async def update(self):
        await self.read_inverter()

    async def read_inverter(self):
        async with self.websession.get(f"{self.url2}?{datetime.now()}") as res:
            res.raise_for_status()
            txt = await res.text()
            self._raw = xmltodict.parse(txt)
            for aEntry in self._raw["root"]["Device"]["Measurements"]["Measurement"]:
                if '@Type' in aEntry:
                    if aEntry["@Type"] == 'AC_Voltage':
                        if '@Value' in aEntry:
                            self._ac_voltage = aEntry["@Value"]
                    if aEntry["@Type"] == 'AC_Current':
                        if '@Value' in aEntry:
                            self._ac_current = aEntry["@Value"]
                    if aEntry["@Type"] == 'AC_Power':
                        if '@Value' in aEntry:
                            self._ac_power = aEntry["@Value"]
                    if aEntry["@Type"] == 'AC_Power_fast':
                        if '@Value' in aEntry:
                            self._ac_power_fast = aEntry["@Value"]
                    if aEntry["@Type"] == 'AC_Frequency':
                        if '@Value' in aEntry:
                            self._ac_frequency = aEntry["@Value"]

                    if aEntry["@Type"] == 'BDC_BAT_Voltage':
                        if '@Value' in aEntry:
                            self._bdc_bat_voltage = aEntry["@Value"]
                    if aEntry["@Type"] == 'BDC_BAT_Current':
                        if '@Value' in aEntry:
                            self._bdc_bat_current = aEntry["@Value"]
                    if aEntry["@Type"] == 'BDC_BAT_Power':
                        if '@Value' in aEntry:
                            self._bdc_bat_power = aEntry["@Value"]
                    if aEntry["@Type"] == 'BDC_LINK_Voltage':
                        if '@Value' in aEntry:
                            self._bdc_link_voltage = aEntry["@Value"]
                    if aEntry["@Type"] == 'BDC_LINK_Current':
                        if '@Value' in aEntry:
                            self._bdc_link_current = aEntry["@Value"]
                    if aEntry["@Type"] == 'BDC_LINK_Power':
                        if '@Value' in aEntry:
                            self._bdc_link_power = aEntry["@Value"]

                    if aEntry["@Type"] == 'DC_Voltage1':
                        if '@Value' in aEntry:
                            self._dc_voltage1 = aEntry["@Value"]
                    if aEntry["@Type"] == 'DC_Voltage2':
                        if '@Value' in aEntry:
                            self._dc_voltage2 = aEntry["@Value"]
                    if aEntry["@Type"] == 'DC_Current1':
                        if '@Value' in aEntry:
                            self._dc_current1 = aEntry["@Value"]
                    if aEntry["@Type"] == 'DC_Current2':
                        if '@Value' in aEntry:
                            self._dc_current2 = aEntry["@Value"]
                    if aEntry["@Type"] == 'LINK_Voltage':
                        if '@Value' in aEntry:
                            self._link_voltage = aEntry["@Value"]

                    if aEntry["@Type"] == 'GridPower':
                        if '@Value' in aEntry:
                            self._gridpower = aEntry["@Value"]
                    if aEntry["@Type"] == 'GridConsumedPower':
                        if '@Value' in aEntry:
                            self._gridconsumedpower = aEntry["@Value"]
                    if aEntry["@Type"] == 'GridInjectedPower':
                        if '@Value' in aEntry:
                            self._gridinjectedpower = aEntry["@Value"]
                    if aEntry["@Type"] == 'OwnConsumedPower':
                        if '@Value' in aEntry:
                            self._ownconsumedpower = aEntry["@Value"]

                    if aEntry["@Type"] == 'Derating':
                        if '@Value' in aEntry:
                            self._derating = float(100.0 - float(aEntry["@Value"]))

    @property
    def device_versions(self) -> str:
        return self._version_infos

    @property
    def has_bdc(self) -> bool:
        return self._has_bdc

    @property
    def device_name(self) -> str:
        return self._rawVer["root"]["Device"]["@Name"]

    @property
    def device_serial(self) -> str:
        return self._rawVer["root"]["Device"]["@Serial"]

    @property
    def device_netbiosname(self) -> str:
        return self._rawVer["root"]["Device"]["@NetBiosName"]

    # @property
    # def measurements(self) -> dict:
    #    if ('Measurements' in self._raw["root"]["Device"] and "Measurement" in self._raw["root"]["Device"][
    #        "Measurements"]):
    #        return self._raw["root"]["Device"]["Measurements"]["Measurement"]

    # @property
    # def versions(self) -> dict:
    #    if ('Versions' in self._rawVer["root"]["Device"] and 'Software' in self._rawVer["root"]["Device"]["Versions"]):
    #        return self._rawVer["root"]["Device"]["Versions"]["Software"]

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

    def __init__(self, user, pwd, websession, master_plant_number: int = 0, options: dict = None):
        _LOGGER.info(f"restarting MySenecWebPortal... for user: '{user}' with options: {options}")
        #Check if spare capacity is in options
        if options is not None and QUERY_SPARE_CAPACITY_KEY in options:
            self._QUERY_SPARE_CAPACITY = options[QUERY_SPARE_CAPACITY_KEY]

        #check if peak shaving is in options
        if options is not None and QUERY_PEAK_SHAVING_KEY in options:
            self._QUERY_PEAK_SHAVING = options[QUERY_PEAK_SHAVING_KEY]

        #Variable to save latest update time for spare capacity
        self._QUERY_SPARE_CAPACITY_TS = 0

        #Variable to save latest update time for peak shaving
        self._QUERY_PEAK_SHAVING_TS = 0


        loop = aiohttp.helpers.get_running_loop(websession.loop)
        senec_jar = MySenecCookieJar(loop=loop);
        if hasattr(websession, "_cookie_jar"):
            oldJar = getattr(websession, "_cookie_jar")
            senec_jar.update_cookies(oldJar._host_only_cookies)

        self.websession: aiohttp.websession = websession
        setattr(self.websession, "_cookie_jar", senec_jar)

        self._master_plant_number = master_plant_number

        # SENEC API
        self._SENEC_USERNAME = user
        self._SENEC_PASSWORD = pwd

        # https://documenter.getpostman.com/view/10329335/UVCB9ihW#17e2c6c6-fe5e-4ca9-bc2f-dca997adaf90
        self._SENEC_CLASSIC_AUTH_URL = "https://app-gateway-prod.senecops.com/v1/senec/login"
        self._SENEC_CLASSIC_API_OVERVIEW_URL = "https://app-gateway-prod.senecops.com/v1/senec/anlagen"

        self._SENEC_AUTH_URL = "https://mein-senec.de/auth/login"
        self._SENEC_API_GET_CUSTOMER_URL = "https://mein-senec.de/endkunde/api/context/getEndkunde"
        self._SENEC_API_GET_SYSTEM_URL = "https://mein-senec.de/endkunde/api/context/getAnlageBasedNavigationViewModel?anlageNummer=%s"

        self._SENEC_API_OVERVIEW_URL = "https://mein-senec.de/endkunde/api/status/getstatusoverview.php?anlageNummer=%s"
        self._SENEC_API_URL_START = "https://mein-senec.de/endkunde/api/status/getstatus.php?type="
        self._SENEC_API_URL_END = "&period=all&anlageNummer=%s"

        # Calls for spare capacity - Base URL has to be followed by master plant number
        self._SENEC_API_SPARE_CAPACITY_BASE_URL = "https://mein-senec.de/endkunde/api/senec/"
        # Call the following URL (GET-Request) in order to get the spare capacity as int in the response body
        self._SENEC_API_GET_SPARE_CAPACITY = "/emergencypower/reserve-in-percent"
        # Call the following URL (Post Request) in order to set the spare capacity
        self._SENEC_API_SET_SPARE_CAPACITY = "/emergencypower?reserve-in-percent="

        # Call for export limit and current peak shaving information - to be followed by master plant number
        self._SENEC_API_GET_PEAK_SHAVING = "https://mein-senec.de/endkunde/api/peakshaving/getSettings?anlageNummer="

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
        self._isAuthenticated = False
        self._peakShaving_entities = {} 

    def checkCookieJarType(self):
        if hasattr(self.websession, "_cookie_jar"):
            oldJar = getattr(self.websession, "_cookie_jar")
            if type(oldJar) is not MySenecCookieJar:
                _LOGGER.warning('CookieJar is not of type MySenecCookie JAR any longer... forcing CookieJAR update')
                loop = aiohttp.helpers.get_running_loop(self.websession.loop)
                new_senec_jar = MySenecCookieJar(loop=loop);
                new_senec_jar.update_cookies(oldJar._host_only_cookies)
                setattr(self.websession, "_cookie_jar", new_senec_jar)

    def purgeSenecCookies(self):
        if hasattr(self.websession, "_cookie_jar"):
            theJar = getattr(self.websession, "_cookie_jar")
            theJar.clear_domain("mein-senec.de")

    async def authenticateClassic(self, doUpdate: bool):
        auth_payload = {
            "username": self._SENEC_USERNAME,
            "password": self._SENEC_PASSWORD
        }
        async with self.websession.post(self._SENEC_CLASSIC_AUTH_URL, json=auth_payload) as res:
            res.raise_for_status()
            if res.status == 200:
                r_json = await res.json()
                if "token" in r_json:
                    self._token = r_json["token"]
                    self._isAuthenticated = True
                    _LOGGER.info("Login successful")
                    if doUpdate:
                        self.updateClassic()
            else:
                _LOGGER.warning(f"Login failed with Code {res.status}")

    async def updateClassic(self):
        _LOGGER.debug("***** updateClassic(self) ********")
        if self._isAuthenticated:
            await self.getSystemOverviewClassic()
        else:
            await self.authenticateClassic(True)

    async def getSystemOverviewClassic(self):
        headers = {"Authorization": self._token}
        async with self.websession.get(self._SENEC_CLASSIC_API_OVERVIEW_URL, headers=headers) as res:
            res.raise_for_status()
            if res.status == 200:
                r_json = await res.json()
            else:
                self._isAuthenticated = False
                await self.update()

    async def authenticate(self, doUpdate: bool, throw401: bool):
        _LOGGER.info("***** authenticate(self) ********")
        self.checkCookieJarType()
        auth_payload = {
            "username": self._SENEC_USERNAME,
            "password": self._SENEC_PASSWORD
        }
        async with self.websession.post(self._SENEC_AUTH_URL, data=auth_payload, max_redirects=20) as res:
            try:
                res.raise_for_status()
                if res.status == 200:
                    # be gentle reading the complete response...
                    r_json = await res.text()
                    self._isAuthenticated = True
                    _LOGGER.info("Login successful")
                    if doUpdate:
                        await self.update()
                else:
                    _LOGGER.warning(f"Login failed with Code {res.status}")
                    self.purgeSenecCookies()
            except ClientResponseError as exc:
                # _LOGGER.error(str(exc))
                if throw401:
                    raise exc
                else:
                    if exc.status == 401:
                        self.purgeSenecCookies()
                        self._isAuthenticated = False
                    else:
                        _LOGGER.warning(f"Login exception with Code {res.status}")
                        self.purgeSenecCookies()

    async def update(self):
        if self._isAuthenticated:
            _LOGGER.info("***** update(self) ********")
            self.checkCookieJarType()
            await self.update_now_kW_stats()
            await self.update_full_kWh_stats()
            if self._QUERY_SPARE_CAPACITY:
                # 1 day = 24 h = 24 * 60 min = 24 * 60 * 60 sec = 86400 sec
                if self._QUERY_SPARE_CAPACITY_TS + 86400 < time():
                    await self.update_spare_capacity()
            #
            if self._QUERY_PEAK_SHAVING:
                # 1 day = 24 h = 24 * 60 min = 24 * 60 * 60 sec = 86400 sec
                if self._QUERY_PEAK_SHAVING_TS + 86400 < time():
                    await self.update_peak_shaving()
        else:
            await self.authenticate(doUpdate=True, throw401=False)


    """This function will update peak shaving information"""
    async def update_peak_shaving(self):
        _LOGGER.info("***** update_peak_shaving(self) ********")
        a_url = f"{self._SENEC_API_GET_PEAK_SHAVING}{self._master_plant_number}"
        async with self.websession.get(a_url) as res:
            try:
                res.raise_for_status()
                if res.status == 200:
                    r_json = await res.json()

                    #GET Data from JSON
                    self._peakShaving_entities["einspeisebegrenzungKwpInPercent"] = r_json["einspeisebegrenzungKwpInPercent"]
                    self._peakShaving_entities["peakShavingMode"] = r_json["peakShavingMode"]
                    self._peakShaving_entities["peakShavingCapacityLimitInPercent"] = r_json["peakShavingCapacityLimitInPercent"]
                    self._peakShaving_entities["peakShavingEndDate"] = datetime.fromtimestamp(r_json["peakShavingEndDate"]/1000) #from miliseconds to seconds

                    self._QUERY_PEAK_SHAVING_TS= time() #Update timer, that the next update takes place in 24 hours
                else:
                    self._isAuthenticated = False
                    await self.update()

            except ClientResponseError as exc:
                if exc.status == 401:
                    self.purgeSenecCookies()

                self._isAuthenticated = False
                await self.update()

    """This function will set the peak shaving data over the web api"""
    async def set_peak_shaving(self, new_peak_shaving: dict):
        _LOGGER.debug("***** set_spare_capacity(self) ********")
        
        #TODO Prepare data for URL
        #TODO SET URL
        a_url = f"{self._SENEC_API_SPARE_CAPACITY_BASE_URL}{self._master_plant_number}{self._SENEC_API_SET_SPARE_CAPACITY}{new_spare_capacity}"

        async with self.websession.post(a_url, ssl=False) as res:
            try:
                res.raise_for_status()
                if res.status == 200:
                    _LOGGER.debug("***** Set Peak Shaving successfully ********")
                    # Reset the timer in order that the Spare Capacity is updated immediately after the change
                    self._QUERY_PEAK_SHAVING_TS = 0
                else:
                    self._isAuthenticated = False
                    await self.authenticate(doUpdate=False, throw401=False)
                    await self.set_peak_shaving(new_peak_shaving)

            except ClientResponseError as exc:
                if exc.status == 401:
                    self.purgeSenecCookies()

                self._isAuthenticated = False
                await self.authenticate(doUpdate=False, throw401=True)
                await self.set_peak_shaving(new_peak_shaving)


    """This function will update the spare capacity over the web api"""
    async def update_spare_capacity(self):
        _LOGGER.info("***** update_spare_capacity(self) ********")
        a_url = f"{self._SENEC_API_SPARE_CAPACITY_BASE_URL}{self._master_plant_number}{self._SENEC_API_GET_SPARE_CAPACITY}"
        async with self.websession.get(a_url) as res:
            try:
                res.raise_for_status()
                if res.status == 200:
                    self._spare_capacity = await res.text()
                    self._QUERY_SPARE_CAPACITY_TS = time()
                else:
                    self._isAuthenticated = False
                    await self.update()

            except ClientResponseError as exc:
                if exc.status == 401:
                    self.purgeSenecCookies()

                self._isAuthenticated = False
                await self.update()

    """This function will set the spare capacity over the web api"""
    async def set_spare_capacity(self, new_spare_capacity: int):
        _LOGGER.debug("***** set_spare_capacity(self) ********")
        a_url = f"{self._SENEC_API_SPARE_CAPACITY_BASE_URL}{self._master_plant_number}{self._SENEC_API_SET_SPARE_CAPACITY}{new_spare_capacity}"

        async with self.websession.post(a_url, ssl=False) as res:
            try:
                res.raise_for_status()
                if res.status == 200:
                    _LOGGER.debug("***** Set Spare Capacity successfully ********")
                    # Reset the timer in order that the Spare Capacity is updated immediately after the change
                    self._QUERY_SPARE_CAPACITY_TS = 0
                else:
                    self._isAuthenticated = False
                    await self.authenticate(doUpdate=False, throw401=False)
                    await self.set_spare_capacity(new_spare_capacity)

            except ClientResponseError as exc:
                if exc.status == 401:
                    self.purgeSenecCookies()

                self._isAuthenticated = False
                await self.authenticate(doUpdate=False, throw401=True)
                await self.set_spare_capacity(new_spare_capacity)

    async def update_now_kW_stats(self):
        _LOGGER.debug("***** update_now_kW_stats(self) ********")
        # grab NOW and TODAY stats
        a_url = f"{self._SENEC_API_OVERVIEW_URL}" % str(self._master_plant_number)
        async with self.websession.get(a_url) as res:
            try:
                res.raise_for_status()
                if res.status == 200:
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

                else:
                    self._isAuthenticated = False
                    await self.update()

            except ClientResponseError as exc:
                if exc.status == 401:
                    self.purgeSenecCookies()

                self._isAuthenticated = False
                await self.update()

    async def update_full_kWh_stats(self):
        # grab TOTAL stats
        a_url = f"{self._SENEC_API_URL_END}" % str(self._master_plant_number)
        for key in self._API_KEYS:
            api_url = self._SENEC_API_URL_START + key + a_url
            async with self.websession.get(api_url) as res:
                try:
                    res.raise_for_status()
                    if res.status == 200:
                        r_json = await res.json()
                        if "fullkwh" in r_json:
                            value = r_json["fullkwh"]
                            entity_name = str(key + "_total")
                            self._energy_entities[entity_name] = value
                        else:
                            _LOGGER.info(f"No 'fullkwh' in json: {r_json} when requesting: {api_url}")
                    else:
                        self._isAuthenticated = False
                        await self.update()

                except ClientResponseError as exc:
                    if exc.status == 401:
                        self.purgeSenecCookies()

                    self._isAuthenticated = False
                    await self.update()

    async def update_context(self):
        _LOGGER.debug("***** update_context(self) ********")
        if self._isAuthenticated:
            await self.update_get_customer()

            # in autodetect-mode the initial self._master_plant_number = -1
            if self._master_plant_number == -1:
                self._master_plant_number = 0
                is_autodetect = True
            else:
                is_autodetect = False

            await self.update_get_systems(a_plant_number=self._master_plant_number, autodetect_mode=is_autodetect)
        else:
            await self.authenticate(doUpdate=False, throw401=False)

    async def update_get_customer(self):
        _LOGGER.debug("***** update_get_customer(self) ********")

        # grab NOW and TODAY stats
        async with self.websession.get(self._SENEC_API_GET_CUSTOMER_URL) as res:
            res.raise_for_status()
            if res.status == 200:
                r_json = await res.json()
                # self._raw = parse(r_json)
                self._dev_number = r_json["devNumber"]
                # anzahlAnlagen
                # language
                # emailAdresse
                # meterReadingVisible
                # vorname
                # nachname
            else:
                self._isAuthenticated = False
                await self.authenticate(doUpdate=False, throw401=False)

    async def update_get_systems(self, a_plant_number: int, autodetect_mode: bool):
        _LOGGER.debug("***** update_get_systems(self) ********")

        a_url = f"{self._SENEC_API_GET_SYSTEM_URL}" % str(a_plant_number)
        async with self.websession.get(a_url) as res:
            res.raise_for_status()
            if res.status == 200:
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

            else:
                self._isAuthenticated = False
                await self.authenticate(doUpdate=False, throw401=False)

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
        if hasattr(self, "_peakShaving_entities") and "einspeisebegrenzungKwpInPercent" in self._peakShaving_entities:
            return self._peakShaving_entities["einspeisebegrenzungKwpInPercent"]
        
    @property
    def peakshaving_mode(self) -> int:
        if hasattr(self, "_peakShaving_entities") and "peakShavingMode" in self._peakShaving_entities:
            return self._peakShaving_entities["peakShavingMode"]
        
    @property
    def peakshaving_capacitylimit(self) -> int:
        if hasattr(self, "_peakShaving_entities") and "peakShavingCapacityLimitInPercent" in self._peakShaving_entities:
            return self._peakShaving_entities["peakShavingCapacityLimitInPercent"]

    @property
    def peakshaving_enddate(self) -> int:
        if hasattr(self, "_peakShaving_entities") and "peakShavingEndDate" in self._peakShaving_entities:
            return self._peakShaving_entities["peakShavingEndDate"]


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
