import asyncio
import copy
import json
import logging
from collections import deque
from json import JSONDecodeError
from typing import Final

import aiohttp
from aiohttp import ClientResponseError, ClientConnectionError, RequestInfo

from custom_components.senec.pysenec_ha import ServiceUnavailableException

_LOGGER = logging.getLogger(__name__)


class SenecLocalOpenApi:
    """Client for the local SENEC OpenAPI on port 4424."""

    _REGISTER_PATH: Final = "/v1/register"
    _BATTERY_PATH: Final = "/v1/battery"
    _METER_PATH: Final = "/v1/meter"
    _BESS_PATH: Final = "/v1/bess"
    _BESS_NAMEPLATE_PATH: Final = "/v1/bess/nameplate"
    _EVSE_PATH: Final = "/v1/evse"
    _BATTERY_LIMITS_PATH: Final = "/v1/battery/limits"
    _BESS_SETPOINT_PATH: Final = "/v1/bess/setpoint"

    def __init__(self, host: str, web_session, token: str = None, port: int = 4424, use_https: bool = True):
        scheme = "https" if use_https else "http"
        self._base_url = f"{scheme}://{host}:{port}"
        self.web_session: aiohttp.websession = web_session
        self.token = token
        self.last_status = None
        self._raw_battery = None
        self._raw_meter = None
        self._raw_evse = None
        self._timeout = aiohttp.ClientTimeout(
            total=10,
            connect=None,
            sock_connect=None,
            sock_read=None,
            ceil_threshold=5,
        )
        self._source:deque = deque(maxlen=50)
        _LOGGER.debug(f"initialized SUCCESSFULLY")

    def dump_response_data(self, payload_data, req:RequestInfo):
        self._source.append({
            "req": str(req.real_url),
            "headers": dict(req.headers),
            "resp": copy.deepcopy(payload_data)
        })

    def dict_data(self) -> dict:
        return {
            "battery": self._raw_battery,
            "meter": self._raw_meter,
            "evse": self._raw_evse,
        }

    async def update(self):
        """Update the OpenAPI data used by Home Assistant entities."""
        self._raw_battery = await self.battery()
        self._raw_meter = await self.meter()
        self._raw_evse = await self.evse()

    async def register(self, device_name: str, manufacturer_name: str) -> str:
        """Register a local client and return the token awaiting portal approval."""
        # sample_data = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
        if not device_name or not manufacturer_name:
            raise ServiceUnavailableException("SENEC OpenAPI registration requires device_name and/or manufacturer_name")

        payload = json.dumps({
                "deviceName": device_name,
                "manufacturerName": manufacturer_name,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        status, body = await self._request(
            "POST",
            self._REGISTER_PATH,
            data=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        self._raise_for_status(status, body, self._REGISTER_PATH)

        token = body.decode("utf-8")
        if len(token) == 0:
            raise ServiceUnavailableException("SENEC OpenAPI registration returned an empty access token")

        self.token = token
        return token

    async def battery(self) -> dict:
        """Return battery state, charge, power, voltage and current."""
        # sample_data = {
        #     "state":1,
        #     "stateOfCharge":0,
        #     "power":160.218,
        #     "voltage":46.44,
        #     "current":3.45
        # }
        return await self._authenticated_get(self._BATTERY_PATH)

    async def meter(self) -> dict:
        """Return grid, consumption, production and surplus power."""
        # sample_data = {
        #     "gridPower":-8,
        #     "consumption":231,
        #     "production":403,
        #     "powerSurplus":0,
        #     "fullRangePowerSurplus":15
        # }
        return await self._authenticated_get(self._METER_PATH)

    async def bess(self) -> dict:
        """ Unclear what this data means. Usually all fields are zero."""
        # sample_data = {
        #     "apparentPower": 0,
        #     "activePower": 0,
        #     "reactivePower": 0,
        #     "voltage": 0,
        #     "current": 0,
        #     "acRelayConnected": false
        # }
        return await self._authenticated_get(self._BESS_PATH)

    async def bess_nameplate(self) -> dict:
        """Return manufacturer, model, serial, capacity and rated power (Usually zero)."""
        # sample_data = {
        #     "manufacturer": "SENEC GmbH",
        #     "model": "SENEC.Home V3 hybrid duo",
        #     "serialNumber": "<serial number>",
        #     "designCapacity": 10000,
        #     "ratedPower": {
        #         "activeChargePower": 0,
        #         "activeDischargePower": 0,
        #         "reactiveChargePower": 0,
        #         "reactiveDischargePower": 0
        #     }
        # }
        return await self._authenticated_get(self._BESS_NAMEPLATE_PATH)

    async def evse(self) -> dict:
        """Return discovered EV charging devices and their current states."""
        # sample_data = {
        #     "devices": [
        #         {
        #             "id": 1,
        #             "evConnected": true,
        #             "evCharging": false,
        #             "limitationStatus": 0,
        #             "chargingPower": 0
        #         }
        #     ]
        # }
        return await self._authenticated_get(self._EVSE_PATH)

    async def battery_limits(self) -> dict:
        """Request battery limits.

        Ordinary portal-approved OpenAPI tokens returned HTTP 403 for every
        tested verb. The required privilege and any response schema are not
        known; this GET method exists to aid further investigations.
        """
        return await self._authenticated_get(self._BATTERY_LIMITS_PATH)

    async def bess_setpoint(self) -> dict:
        """Request the BESS setpoint.

        Ordinary portal-approved OpenAPI tokens returned HTTP 403 for every
        tested verb. The required privilege and any response schema are not
        known; this GET method exists to aid further investigations.
        """
        return await self._authenticated_get(self._BESS_SETPOINT_PATH)

    @property
    def battery_state_power(self) -> float:
        if self._raw_battery is not None:
            return self._raw_battery.get("power", None)

    @property
    def battery_state_voltage(self) -> float:
        if self._raw_battery is not None:
            return self._raw_battery.get("voltage", None)

    @property
    def battery_state_current(self) -> float:
        if self._raw_battery is not None:
            return self._raw_battery.get("current", None)

    @property
    def battery_charge_percent(self) -> float:
        if self._raw_battery is not None:
            return self._raw_battery.get("stateOfCharge", None)

    @property
    def grid_state_power(self) -> float:
        """Grid power: positive from grid, negative to grid."""
        if self._raw_meter is not None:
            return self._raw_meter.get("gridPower", None)

    @property
    def solar_generated_power(self) -> float:
        if self._raw_meter is not None:
            return self._raw_meter.get("production", None)

    @property
    def house_power(self) -> float:
        if self._raw_meter is not None:
            return self._raw_meter.get("consumption", None)

    def _first_wallbox(self) -> dict | None:
        if self._raw_evse is not None:
            devices = self._raw_evse.get("devices", [])
            if len(devices) > 0:
                return devices[0]
        return None

    @property
    def wallbox_1_power_alt(self) -> float:
        wallbox = self._first_wallbox()
        if wallbox is not None:
            return wallbox.get("chargingPower", None)

    @property
    def wallbox_1_ev_connected(self) -> bool:
        wallbox = self._first_wallbox()
        if wallbox is not None:
            return wallbox.get("evConnected", None)

    @property
    def wallbox_1_ev_charging(self) -> bool:
        wallbox = self._first_wallbox()
        if wallbox is not None:
            return wallbox.get("evCharging", None)

    async def _authenticated_get(self, path: str) -> dict:
        self._require_token()
        status, body = await self._request("GET", path, headers=self._authenticated_headers())
        self._raise_for_status(status, body, path)

        try:
            return json.loads(body) if len(body) > 0 else {}
        except JSONDecodeError as exc:
            msg = f"_authenticated_get(): returned invalid JSON for {path}: {exc}"
            _LOGGER.warning(msg)
            raise ServiceUnavailableException(msg) from exc

    def _require_token(self):
        if self.token is None or len(str(self.token)) == 0:
            raise ValueError("register first or provide a SENEC OpenAPI token")

    def _authenticated_headers(self) -> dict:
        return {"X-Auth-Token": self.token}

    async def _request(self, method: str, path: str, *, data=None, headers: dict = None) -> tuple[int, bytes]:
        url = f"{self._base_url}{path}"
        try:
            async with self.web_session.request(
                    method,
                    url,
                    data=data,
                    headers=headers,
                    timeout=self._timeout,
                    ssl=False,
            ) as res:
                self.last_status = res.status
                r_data = await res.read()
                self.dump_response_data(r_data, res.request_info)
                return res.status, r_data
        except (ClientResponseError, ClientConnectionError, asyncio.TimeoutError) as exc:
            msg = f"_request(): error for {path}: [Exception: {exc}]"
            _LOGGER.warning(msg)
            raise ServiceUnavailableException(msg) from exc
        except Exception as exc:
            msg = f"_request(): unexpected error for {path}: [Exception: {exc}]"
            _LOGGER.warning(msg)
            raise ServiceUnavailableException(msg) from exc

    @staticmethod
    def _raise_for_status(status: int, body: bytes, path: str):
        if 200 <= status < 300:
            return

        response_text = body.decode("utf-8", errors="replace")
        msg = f"_raise_for_status(): request failed [{status}] for {path}"
        if len(response_text) > 0:
            msg += f" - {response_text}"

        _LOGGER.warning(msg)
        raise ServiceUnavailableException(msg)


