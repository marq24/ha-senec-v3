import asyncio
import copy
import logging
from collections import deque
from json import JSONDecodeError
from typing import Final, Iterable
from aiohttp import ClientResponseError, ClientConnectionError, RequestInfo

from custom_components.senec.pysenec_ha import ServiceUnavailableException, util

_LOGGER = logging.getLogger(__name__)


class SenecConnect:
    _SENEC_CONNECT_BASE_URL: Final = "https://apim-eds-gwc-prod.azure-api.net/senec-connect"
    _GENERAL_DEVICE_DATA_PATH: Final = "/v1/systems/device-data/general"

    def __str__(self):
        return f"SenecConnect [{self._logger_key}]"

    def __init__(self, subscription_key: str, web_session, use_key_header: bool = True, use_key_query: bool = False):
        self._subscription_key = subscription_key
        self._logger_key = f"{(subscription_key[:5]).upper()}XXXXXXX"
        self.web_session = web_session
        self._use_key_header = use_key_header
        self._use_key_query = use_key_query
        self._raw_senec_connect = None
        self._raw_senec_connect_grouped = None
        self._source:deque = deque(maxlen=50)
        _LOGGER.debug(f"initialized SUCCESSFULLY")

    def dump_response_data(self, payload_data, req:RequestInfo):
        self._source.append({
            "req": str(req.real_url),
            "headers": dict(req.headers),
            "resp": copy.deepcopy(payload_data)
        })

    def dict_data(self):
        return {"data": self._raw_senec_connect_grouped, "raw_data": self._raw_senec_connect, "version": {}}

    async def update(self):
        await self._request_connect_api()

    async def get_all_live_systems(self):
        if self._raw_senec_connect is None:
            await self._request_connect_api()

        if self._raw_senec_connect is not None and len(self._raw_senec_connect) > 0:
            ret = {}
            for a_system in self._raw_senec_connect:
                # we must check if there are any 'stall' systems...
                battery = a_system.get("battery", None)
                bess = a_system.get("bessNameplate", None)
                # looks like that a stale system does not provide meter:consumption and meter:production
                # data [but who knows]
                # 2026/08/12 base on https://github.com/marq24/ha-senec-v3/issues/233 it looks like that
                # a stale system is better identified by the presence of 'voltage' or 'current' in the
                # battery object
                if battery and bess:
                    if "system_id" in bess and ("voltage" in battery or "current" in battery):
                        a_system_id = bess.get("system_id", "unknown").lower()

                        # we must insert also the ev-wallbox data dict
                        if self._raw_senec_connect_grouped is not None:
                            a_possible_evse_dict = self._raw_senec_connect_grouped[a_system_id].get("evse", None)
                            if a_possible_evse_dict is not None:
                                bess["evse"] = list(a_possible_evse_dict.keys())

                        ret[a_system_id] = bess
            return ret

        _LOGGER.info(f"get_all_live_systems(): could not get any live systems for given key {self._logger_key}")
        return None

    @staticmethod
    def _normalize_include(include: str | Iterable[str] | None) -> str | None:
        if include is None:
            return None

        if isinstance(include, str):
            return include.strip() or None

        values = [str(value).strip() for value in include if str(value).strip()]
        if len(values) > 0:
            return ",".join(values)

        return None

    # async def _request_connect_api_fake(self, include: str | Iterable[str] | None = None):
    #     static_data = [{
    #         "battery": {
    #             "state": 0,
    #             "state_of_charge": 24,
    #             "power": 0.0
    #         },
    #         "bessNameplate": {
    #             "manufacturer": "SENEC GmbH",
    #             "model": "SENEC.Home 4 hybrid / 11.8",
    #             "serial_number": "v4-serial_004",
    #             "system_id": "S4H1-XXXX12345-0000-04",
    #             "design_capacity": 17640,
    #             "active_charge_power": 10080,
    #             "active_discharge_power": 12600
    #         },
    #         "meter": {
    #             "grid_power": 0.0
    #         },
    #         "evse": []
    #     }, {
    #         "battery": {
    #             "state": 0,
    #             "state_of_charge": 66,
    #             "power": 5771.4844,
    #             "voltage": 609.0,
    #             "current": 9.5
    #         },
    #         "bessNameplate": {
    #             "manufacturer": "SENEC GmbH",
    #             "model": "SENEC.Home P4 hybrid / 11.8",
    #             "serial_number": "v4-serial_003",
    #             "system_id": "P4H1-XXXX12345-0000-03",
    #             "design_capacity": 17750,
    #             "active_charge_power": 12600,
    #             "active_discharge_power": 11800
    #         },
    #         "meter": {
    #             "grid_power": 0.0,
    #             "consumption": 468.75,
    #             "production": 6210.9375
    #         },
    #         "evse": []
    #     }, {
    #         "battery": {
    #             "state": 0,
    #             "state_of_charge": 1,
    #             "power": 0.0
    #         },
    #         "bessNameplate": {
    #             "manufacturer": "SENEC GmbH",
    #             "model": "SENEC.Home 4 hybrid / 11.8",
    #             "serial_number": "v4-serial_002",
    #             "system_id": "S4H1-XXXX12345-0000-02",
    #             "design_capacity": 2940,
    #             "active_charge_power": 1680,
    #             "active_discharge_power": 2100
    #         },
    #         "meter": {
    #             "grid_power": 439.45312,
    #             "consumption": 439.45312,
    #             "production": 0.0
    #         },
    #         "evse": [{
    #             "id": "wb_id_001",
    #             "ev_connected": True,
    #             "ev_charging": True,
    #             "charging_power": 6900.0
    #         }]
    #     }, {
    #         "battery": {
    #             "state": 0,
    #             "state_of_charge": 5,
    #             "power": 1142.5781,
    #             "voltage": 234.0,
    #             "current": 4.6
    #         },
    #         "bessNameplate": {
    #             "manufacturer": "SENEC GmbH",
    #             "model": "SENEC.Home P4 hybrid / 11.8",
    #             "serial_number": "v4-serial_001",
    #             "system_id": "P4H1-XXXX12345-0000-01",
    #             "design_capacity": 7100,
    #             "active_charge_power": 6680,
    #             "active_discharge_power": 6680
    #         },
    #         "meter": {
    #             "grid_power": 14.6484375,
    #             "consumption": 410.15625,
    #             "production": 1523.4375
    #         },
    #         "evse": [{
    #             "id": "wb_id_002",
    #             "ev_connected": False,
    #             "ev_charging": False,
    #             "charging_power": 0.0
    #         }]
    #     }]
    #     _LOGGER.debug(f"FAKE response: {util.mask_map(static_data)}")
    #     return self._handle_json_response(static_data)

    async def _request_connect_api(self, include: str | Iterable[str] | None = None):
        if self._subscription_key is None or len(str(self._subscription_key).strip()) == 0:
            raise ValueError("subscription_key must not be empty")

        req_headers = {}
        req_params = {}

        if self._use_key_header:
            req_headers["Ocp-Apim-Subscription-Key"] = self._subscription_key
        if self._use_key_query:
            req_params["subscription-key"] = self._subscription_key

        include_value = self._normalize_include(include=include)
        if include_value is not None:
            req_params["include"] = include_value

        a_url = f"{self._SENEC_CONNECT_BASE_URL}{self._GENERAL_DEVICE_DATA_PATH}"

        try:
            _LOGGER.debug(f"requesting: {a_url} params={req_params}")
            async with self.web_session.get(
                    a_url,
                    headers=req_headers if len(req_headers) > 0 else None,
                    params=req_params if len(req_params) > 0 else None,
            ) as res:
                if res.status in [200, 201, 202]:
                    try:
                        data = await res.json()
                        self.dump_response_data(data, res.request_info)
                        _LOGGER.debug(f"response: {util.mask_map(data)}")
                        return self._handle_json_response(data)

                    except JSONDecodeError as jexc:
                        msg = f"returned invalid JSON for {a_url}: [Exception: {jexc}]"
                        _LOGGER.warning(msg)
                        raise ServiceUnavailableException(msg) from jexc

                response_text = None
                try:
                    response_text = await res.text()
                except Exception:
                    response_text = None

                msg = f"request failed [{res.status}] for {a_url}"
                if response_text is not None:
                    msg += f" - {response_text}"

                _LOGGER.warning(msg)
                raise ServiceUnavailableException(msg)

        except ServiceUnavailableException:
            raise
        except (ClientResponseError, ClientConnectionError, asyncio.TimeoutError) as exc:
            msg = f"request error for {a_url}: [Exception: {exc}]"
            _LOGGER.warning(msg)
            raise ServiceUnavailableException(msg) from exc
        except Exception as exc:
            msg = f"unexpected error for {a_url}: [Exception: {exc}]"
            _LOGGER.warning(msg)
            raise ServiceUnavailableException(msg) from exc

    def _handle_json_response(self, data):
        self._raw_senec_connect = data

        # generate from the plain list a dict with the system_id as key
        # so we can access each system directly (without the need to
        # guess each time what index is what)
        grouped_data = {}
        if self._raw_senec_connect is not None and len(self._raw_senec_connect) > 0:
            for a_system_dict in self._raw_senec_connect:
                # the fucking wallbox data is also just a plain list... how we can be sure
                # that the order is always the same -> well we can't!
                evse_list = a_system_dict.get("evse", None)
                if evse_list is not None and isinstance(evse_list, list) and len(evse_list) > 0:
                    grouped_evse = {}
                    for a_evse_obj in evse_list:
                        grouped_evse[a_evse_obj.get("id", "unknown").lower()] = a_evse_obj

                    a_system_dict["evse"] = grouped_evse
                else:
                    a_system_dict.pop("evse")

                bess = a_system_dict.get("bessNameplate", None)
                if bess and "system_id" in bess:
                    grouped_data[bess.get("system_id", "unknown").lower()] = a_system_dict

            self._raw_senec_connect_grouped = grouped_data

        return grouped_data if len(grouped_data) > 0 else data

    def battery_state_power(self, system_id, wallbox_id) -> float:
        if self._raw_senec_connect_grouped is not None and system_id in self._raw_senec_connect_grouped:
            return self._raw_senec_connect_grouped[system_id].get("battery", {}).get("power", None)

    def battery_state_current(self, system_id, wallbox_id) -> float:
        if self._raw_senec_connect_grouped is not None and system_id in self._raw_senec_connect_grouped:
            return self._raw_senec_connect_grouped[system_id].get("battery", {}).get("current", None)

    def battery_state_voltage(self, system_id, wallbox_id) -> float:
        if self._raw_senec_connect_grouped is not None and system_id in self._raw_senec_connect_grouped:
            return self._raw_senec_connect_grouped[system_id].get("battery", {}).get("voltage", None)

    def battery_charge_percent(self, system_id, wallbox_id) -> float:
        if self._raw_senec_connect_grouped is not None and system_id in self._raw_senec_connect_grouped:
            return self._raw_senec_connect_grouped[system_id].get("battery", {}).get("state_of_charge", None)

    def grid_state_power(self, system_id, wallbox_id) -> float:
        """Grid power (+ from grid, − to grid) in watt (W)"""
        if self._raw_senec_connect_grouped is not None and system_id in self._raw_senec_connect_grouped:
            return self._raw_senec_connect_grouped[system_id].get("meter", {}).get("grid_power", None)

    def house_total_consumption(self, system_id, wallbox_id) -> float:
        """Total energy used by house (W) - Does not include Wallbox."""
        if self._raw_senec_connect_grouped is not None and system_id in self._raw_senec_connect_grouped:
            return self._raw_senec_connect_grouped[system_id].get("meter", {}).get("consumption", None)

    def solar_total_generated(self, system_id, wallbox_id) -> float:
        """Current power generated by solar panels (W)"""
        if self._raw_senec_connect_grouped is not None and system_id in self._raw_senec_connect_grouped:
            return self._raw_senec_connect_grouped[system_id].get("meter", {}).get("production", None)

    def wallbox_charging_power(self, system_id, wallbox_id) -> float:
        if self._raw_senec_connect_grouped is not None and system_id in self._raw_senec_connect_grouped:
            return self._raw_senec_connect_grouped[system_id].get("evse", {}).get(wallbox_id, {}).get("charging_power", None)

    def wallbox_ev_connected(self, system_id, wallbox_id) -> bool:
        if self._raw_senec_connect_grouped is not None and system_id in self._raw_senec_connect_grouped:
            return self._raw_senec_connect_grouped[system_id].get("evse", {}).get(wallbox_id, {}).get("ev_connected", None)

    def wallbox_ev_charging(self, system_id, wallbox_id) -> bool:
        if self._raw_senec_connect_grouped is not None and system_id in self._raw_senec_connect_grouped:
            return self._raw_senec_connect_grouped[system_id].get("evse", {}).get(wallbox_id, {}).get("ev_charging", None)