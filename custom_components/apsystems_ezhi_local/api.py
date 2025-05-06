"""API client for APSystems EZHI Inverter."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Optional

import aiohttp

_LOGGER = logging.getLogger(__name__)


@dataclass
class ReturnOutputData:
    """Class for return output data."""
    # Battery status
    batS: str
    # Battery state of charge (%)
    batSoc: str
    # Battery state of health (%)
    batSoh: str
    # Battery temperature (℃)
    batTemp: str
    # Device temperature (℃)
    devTemp: str
    # Photovoltaic input power (W)
    pvP: str
    # Total photovoltaic input energy (kWh)
    pvTE: str
    # Battery power (W)
    batP: str
    # Total battery charge energy (kWh)
    batCTE: str
    # Total battery discharge energy (kWh)
    batDTE: str
    # On-grid power (W)
    ogP: str
    # Total on-grid output energy (kWh)
    ogOTE: str
    # Total on-grid input energy (kWh)
    ogITE: str
    # Off-grid power (W)
    ofgP: str
    # Total off-grid output energy (kWh)
    ofgOTE: str
    # Total off-grid input energy (kWh)
    ofgITE: str


@dataclass
class ReturnAlarmData:
    """Class for return alarm data."""
    BatHTP: str  # Battery high temperature protection
    BatLTP: str  # Battery low temperature protection
    BatCE: str   # Battery communication error
    BatHV: str   # Battery overvoltage
    BatLV: str   # Battery undervoltage
    BatHI: str   # Battery overcurrent
    BatE: str    # Battery error
    DTP: str     # Device temperature protection
    EE: str      # Device error
    SBS: str     # Battery shutdown
    ACA: str     # AC abnormal
    OfOI: str    # Off grid over current alarm
    PvHV: str    # PV high voltage
    PvOC: str    # PV over current
    IRDE: str    # IRD error
    PVWE: str    # PV wiring error
    OfGS: str    # Off grid short circuit


class APsystemsEZHI:
    """API client for APSystems EZHI Inverter."""

    def __init__(self, ip_address: str, timeout: int = 10):
        """Initialize the APsystems EZHI API client."""
        self.ip_address = ip_address
        self.timeout = timeout
        self.session = None

    async def _request(self, endpoint: str, params: Optional[dict[str, Any]] = None) -> dict:
        """Make a request to the API."""
        if self.session is None:
            self.session = aiohttp.ClientSession()
            
        url = f"http://{self.ip_address}/{endpoint}"
        try:
            async with asyncio.timeout(self.timeout):
                response = await self.session.get(url, params=params)
                response.raise_for_status()
                return await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as error:
            _LOGGER.error("Error requesting data from %s: %s", url, error)
            raise

    async def get_device_info(self) -> dict:
        """Get device information of EZHI."""
        return await self._request("getDeviceInfo")

    async def get_output_data(self) -> ReturnOutputData:
        """Get current output data of EZHI."""
        response = await self._request("getOutputData")
        data = response.get("data", {})
        return ReturnOutputData(
            batS=data.get("batS", "0"),
            batSoc=data.get("batSoc", "0"),
            batSoh=data.get("batSoh", "0"),
            batTemp=data.get("batTemp", "0"),
            devTemp=data.get("devTemp", "0"),
            pvP=data.get("pvP", "0"),
            pvTE=data.get("pvTE", "0"),
            batP=data.get("batP", "0"),
            batCTE=data.get("batCTE", "0"),
            batDTE=data.get("batDTE", "0"),
            ogP=data.get("ogP", "0"),
            ogOTE=data.get("ogOTE", "0"),
            ogITE=data.get("ogITE", "0"),
            ofgP=data.get("ofgP", "0"),
            ofgOTE=data.get("ofgOTE", "0"),
            ofgITE=data.get("ofgITE", "0"),
        )

    async def get_alarm(self) -> ReturnAlarmData:
        """Get alarm information of EZHI."""
        response = await self._request("getAlarm")
        data = response.get("data", {})
        return ReturnAlarmData(
            BatHTP=data.get("BatHTP", "0"),
            BatLTP=data.get("BatLTP", "0"),
            BatCE=data.get("BatCE", "0"),
            BatHV=data.get("BatHV", "0"),
            BatLV=data.get("BatLV", "0"),
            BatHI=data.get("BatHI", "0"),
            BatE=data.get("BatE", "0"),
            DTP=data.get("DTP", "0"),
            EE=data.get("EE", "0"),
            SBS=data.get("SBS", "0"),
            ACA=data.get("ACA", "0"),
            OfOI=data.get("OfOI", "0"),
            PvHV=data.get("PvHV", "0"),
            PvOC=data.get("PvOC", "0"),
            IRDE=data.get("IRDE", "0"),
            PVWE=data.get("PVWE", "0"),
            OfGS=data.get("OfGS", "0"),
        )

    async def get_power(self) -> int:
        """Get on-grid power setting value of EZHI."""
        response = await self._request("getPower")
        return int(response.get("data", {}).get("power", 0))

    async def set_power(self, power: int) -> bool:
        """Set on-grid power setting value of EZHI."""
        try:
            response = await self._request("setPower", params={"p": power})
            return response.get("message") == "SUCCESS"
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return False
