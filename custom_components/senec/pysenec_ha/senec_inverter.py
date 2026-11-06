import asyncio
import logging
from datetime import datetime
from time import time
from typing import Final

import aiohttp
import xmltodict
from aiohttp import ClientConnectionError

_LOGGER = logging.getLogger(__name__)

KEEPALIVE_HEADERS: Final = {
    "Connection": "keep-alive",
}

class InverterLocal:
    def __str__(self):
        return f"Inverter [{self._logger_key}]"

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
        _LOGGER.debug(f"Inverter initialized SUCCESSFULLY")

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
        async with self.inv_session.get(self.url3, headers=KEEPALIVE_HEADERS) as res:
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
        except ClientConnectionError as exc:
            _LOGGER.info(f"{exc}")
            if retry:
                await asyncio.sleep(5)
                await self.read_inverter_with_retry(retry=False)

    async def read_inverter(self):
        async with self.inv_session.get(url=f"{self.url2}?{datetime.now()}", headers=KEEPALIVE_HEADERS, timeout=self._timeout) as res:
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
            async with self.inv_session.get(url=f"{self.url_yield}&_={time()}", headers=KEEPALIVE_HEADERS, timeout=self._timeout) as res:
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