"""API client for APSystems EZHI Inverter."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Optional

import aiohttp

_LOGGER = logging.getLogger(__name__)


@dataclass
class ReturnDeviceInfo:
    """Class for return device information."""
    # Device ID
    deviceId: str
    # Device type
    type: str
    # Device version
    devVer: str
    # Battery company
    batteryCompany: str
    # Battery model
    batteryModel: str
    # Battery capacity (kWh)
    batteryCapacity: str
    # WiFi SSID
    ssid: str
    # IP address
    ip: str


@dataclass
class ReturnOutputData:
    """Class for return output data."""
    # Battery status
    batS: str | None
    # Battery state of charge (%)
    batSoc: str | None
    # Battery state of health (%)
    batSoh: str | None
    # Battery temperature (℃)
    batTemp: str | None
    # Device temperature (℃)
    devTemp: str | None
    # Photovoltaic input power (W)
    pvP: str | None
    # Total photovoltaic input energy (kWh)
    pvTE: str | None
    # Battery power (W)
    batP: str | None
    # Total battery charge energy (kWh)
    batCTE: str | None
    # Total battery discharge energy (kWh)
    batDTE: str | None
    # On-grid power (W)
    ogP: str | None
    # Total on-grid output energy (kWh)
    ogOTE: str | None
    # Total on-grid input energy (kWh)
    ogITE: str | None
    # Off-grid power (W)
    ofgP: str | None
    # Total off-grid output energy (kWh)
    ofgOTE: str | None
    # Total off-grid input energy (kWh)
    ofgITE: str | None


# getOutputData's fields inside "data"; batS sits at the root.
OUTPUT_KEYS = (
    "batSoc", "batSoh", "batTemp", "devTemp", "pvP", "pvTE", "batP", "batCTE",
    "batDTE", "ogP", "ogOTE", "ogITE", "ofgP", "ofgOTE", "ofgITE",
)
LIFETIME_KEYS = ("pvTE", "batCTE", "batDTE", "ogOTE", "ogITE", "ofgOTE", "ofgITE")


def _is_zero(value: Any) -> bool:
    try:
        return float(value) == 0
    except (TypeError, ValueError):
        return False


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
    # Reported by getAlarm but previously unmapped. Default to "" rather than
    # "0": firmware that does not send them should read as "unknown", not as a
    # confident "no problem". BCI in particular is a safety-relevant claim.
    BCC: str = ""   # SOC calibration needed
    BCI: str = ""   # Battery access conflict
    VRP: str = ""   # Voltage reset protection


class APsystemsEZHI:
    """API client for APSystems EZHI Inverter."""

    def __init__(self, ip_address: str, timeout: int = 10,
                 session: aiohttp.ClientSession | None = None):
        """Initialize the APsystems EZHI API client."""
        self.ip_address = ip_address
        self.timeout = timeout
        # A caller-owned session (HA passes its shared one) is never
        # closed here; without one, a lazy own session is created.
        self.session = session
        self._missing: list[str] = []

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

    async def get_device_info(self) -> ReturnDeviceInfo:
        """Get device information of EZHI."""
        response = await self._request("getDeviceInfo")
        data = response.get("data", {})
        return ReturnDeviceInfo(
            deviceId=data.get("deviceId", ""),
            type=data.get("type", ""),
            devVer=data.get("devVer", ""),
            batteryCompany=data.get("batteryCompany", ""),
            batteryModel=data.get("batteryModel", ""),
            batteryCapacity=data.get("batteryCapacity", "0"),
            ssid=data.get("ssid", ""),
            ip=data.get("ip", "")
        )

    async def get_output_data(self) -> ReturnOutputData:
        """Get current output data of EZHI.

        A field the reply lacks is None, not "0": a made-up 0 % SoC or 0 kWh
        reads downstream exactly like a real one.
        """
        response = await self._request("getOutputData")
        data = response.get("data") or {}
        missing = [key for key in OUTPUT_KEYS if key not in data]
        # Once per change, not every poll: firmware that never sends a field
        # would otherwise log it every few seconds.
        if missing != self._missing:
            if missing:
                _LOGGER.warning("getOutputData came without %s: %s",
                                ", ".join(missing), response)
            self._missing = missing
        # About every 10 h the counters read 0 for one poll. Sent as 0 or left
        # out? A lacking field is logged above; this catches the other case.
        if not missing and all(_is_zero(data[key]) for key in LIFETIME_KEYS):
            _LOGGER.debug("getOutputData with every lifetime counter at 0: %s",
                          response)
        return ReturnOutputData(
            # batS is on root level, not inside data!
            batS=response.get("batS"),
            **{key: data.get(key) for key in OUTPUT_KEYS},
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
            BCC=data.get("BCC", ""),
            BCI=data.get("BCI", ""),
            VRP=data.get("VRP", ""),
        )

    async def get_power(self) -> int:
        """Get on-grid power setting value of EZHI."""
        response = await self._request("getPower")
        power_str = response.get("data", {}).get("power", "0")
        try:
            # Convert to float first, then to int
            return int(float(power_str))
        except (ValueError, TypeError):
            return 0

    async def set_power(self, power: int) -> bool:
        """Set on-grid power setting value of EZHI.

        Network errors propagate (they are logged in _request); False
        means the device answered and rejected the write.
        """
        response = await self._request("setPower", params={"p": power})
        return response.get("message") == "SUCCESS"
