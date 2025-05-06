#!/usr/bin/env python3
"""Test script for APsystems EZHI API."""
import asyncio
import json
import sys
from typing import Optional

import aiohttp


class APsystemsEZHI:
    """API client for APsystems EZHI Inverter."""

    def __init__(self, ip_address: str, timeout: int = 10):
        """Initialize the APsystems EZHI API client."""
        self.ip_address = ip_address
        self.timeout = timeout
        self.session = None

    async def _request(self, endpoint: str, params: Optional[dict] = None) -> dict:
        """Make a request to the API."""
        if self.session is None:
            self.session = aiohttp.ClientSession()
            
        url = f"http://{self.ip_address}/{endpoint}"
        try:
            async with asyncio.timeout(self.timeout):
                response = await self.session.get(url, params=params)
                response.raise_for_status()
                return await response.json()
        except Exception as error:
            print(f"Error requesting data from {url}: {error}")
            raise
        
    async def close(self):
        """Close the session."""
        if self.session:
            await self.session.close()
            self.session = None

    async def get_device_info(self) -> dict:
        """Get device information of EZHI."""
        return await self._request("getDeviceInfo")

    async def get_output_data(self) -> dict:
        """Get current output data of EZHI."""
        return await self._request("getOutputData")

    async def get_alarm(self) -> dict:
        """Get alarm information of EZHI."""
        return await self._request("getAlarm")

    async def get_power(self) -> int:
        """Get on-grid power setting value of EZHI."""
        response = await self._request("getPower")
        return int(response.get("data", {}).get("power", 0))

    async def set_power(self, power: int) -> dict:
        """Set on-grid power setting value of EZHI."""
        return await self._request("setPower", params={"p": power})


async def main():
    """Run main function."""
    if len(sys.argv) < 2:
        print("Usage: python test_api.py <inverter_ip> [command] [param]")
        print("Commands: info, output, alarm, get_power, set_power")
        print("Example: python test_api.py 192.168.1.100 info")
        print("Example: python test_api.py 192.168.1.100 set_power 600")
        return

    ip = sys.argv[1]
    command = sys.argv[2] if len(sys.argv) > 2 else "info"
    param = sys.argv[3] if len(sys.argv) > 3 else None
    
    api = APsystemsEZHI(ip_address=ip)
    
    try:
        if command == "info":
            result = await api.get_device_info()
            print(json.dumps(result, indent=2))
        elif command == "output":
            result = await api.get_output_data()
            print(json.dumps(result, indent=2))
        elif command == "alarm":
            result = await api.get_alarm()
            print(json.dumps(result, indent=2))
        elif command == "get_power":
            result = await api.get_power()
            print(f"Current power setting: {result}W")
        elif command == "set_power" and param:
            result = await api.set_power(int(param))
            print(json.dumps(result, indent=2))
        else:
            print(f"Unknown command: {command}")
    finally:
        await api.close()


if __name__ == "__main__":
    asyncio.run(main())