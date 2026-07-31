"""Cloud control client for the APsystems EZHI (EMA cloud).

Control commands are cloud-only: the local HTTP API exposes five read endpoints
plus setPower and nothing else. Verified exhaustively 2026-07-30/31, see
docs/ezhi-cloud-api-map.md for every endpoint and payload used here.

Deliberately free of homeassistant imports so it can be unit-tested standalone.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://app.api.apsystemsema.com:9223"
API_URL = f"{BASE_URL}/aps-api-web"
TOKEN_URL = f"{BASE_URL}/api/token/refreshToken"

# The JWT lives 2 h. Refresh well before that rather than waiting for a 401 —
# the 401 path stays as the backstop.
TOKEN_TTL_SECONDS = 6000

# The cloud reports a dead refresh_token as one of these.
AUTH_ERROR_CODES = {3000, 3001, 3002, 3003, 3004}
# The device is not reachable over MQTT.
DEVICE_OFFLINE_CODE = 1001


class EzhiCloudError(Exception):
    """A cloud call failed: transport, HTTP status or a non-zero body code."""


class EzhiCloudAuthError(EzhiCloudError):
    """The refresh_token is dead — the user has to capture a new one."""


class EzhiCloudOfflineError(EzhiCloudError):
    """The inverter is not reachable by the cloud (MQTT disconnected)."""


# The systemMode POST replaces the whole params blob. Anything left out risks
# being defaulted away by the cloud — so every field we know about travels along.
SYSTEM_MODE_KEYS = ("systemMode", "EPS", "ECO", "userSetPower")


def build_system_mode_params(config: dict, **changes: Any) -> dict[str, str]:
    """Read-modify-write: carry the current config forward, override `changes`.

    `config` is the payload of a systemMode GET. Raises rather than defaulting a
    missing field — a wrong guess here would reconfigure real hardware.
    """
    params = {
        key: str(config[key])
        for key in SYSTEM_MODE_KEYS
        if config.get(key) is not None
    }
    params.update({key: str(value) for key, value in changes.items()})

    missing = [key for key in SYSTEM_MODE_KEYS if key not in params]
    if missing:
        raise EzhiCloudError(
            f"cannot build a systemMode payload, the cloud config is missing "
            f"{missing} — refusing to write a partial configuration"
        )
    return params


class EzhiCloudApi:
    """Authenticated client for the EMA cloud control endpoints."""

    def __init__(
        self,
        session: Any,
        device_id: str,
        access_token: str,
        refresh_token: str,
        language: str = "en",
        timeout: int = 15,
    ):
        self._session = session
        self._device_id = device_id
        # Bootstrap bearer from the capture. refreshToken accepts an expired one,
        # which is the only reason a single capture keeps working forever.
        self._token = access_token
        self._refresh_token = refresh_token
        self._language = language
        self._timeout = timeout
        self._token_expires = 0.0  # forces a refresh on the first call
        self._lock = asyncio.Lock()

    # --- token handling ---------------------------------------------------

    async def _refresh_token_now(self) -> None:
        """Exchange the refresh_token for a new access_token.

        The refresh_token does not rotate, so it is never overwritten here.
        """
        async with asyncio.timeout(self._timeout):
            response = await self._session.request(
                "POST",
                TOKEN_URL,
                data={"refresh_token": self._refresh_token,
                      "language": self._language},
                headers={"Authorization": f"Bearer {self._token}",
                         "Accept-Language": self._language},
            )
            status = response.status
            body = await response.json(content_type=None)

        code = body.get("code")
        if status != 200 or code in AUTH_ERROR_CODES:
            raise EzhiCloudAuthError(
                f"refreshToken rejected (HTTP {status}, code {code}): the stored "
                "refresh_token is no longer valid — capture a new one from the app"
            )
        if code != 0:
            raise EzhiCloudError(
                f"refreshToken failed: code={code} msg={body.get('message')}"
            )

        token = (body.get("data") or {}).get("access_token")
        if not token:
            raise EzhiCloudAuthError("refreshToken returned no access_token")

        self._token = token
        self._token_expires = time.monotonic() + TOKEN_TTL_SECONDS
        _LOGGER.debug("EZHI cloud: access token refreshed")

    async def _ensure_token(self) -> None:
        if time.monotonic() < self._token_expires:
            return
        async with self._lock:
            # Another task may have refreshed while we waited for the lock.
            if time.monotonic() < self._token_expires:
                return
            await self._refresh_token_now()

    # --- request plumbing -------------------------------------------------

    async def _raw(self, method, path, params, data) -> tuple[int, dict]:
        url = f"{API_URL}/{path.lstrip('/')}"
        async with asyncio.timeout(self._timeout):
            response = await self._session.request(
                method,
                url,
                params=params,
                data=data,
                headers={"Authorization": f"Bearer {self._token}",
                         "Accept-Language": self._language},
            )
            if response.status != 200:
                return response.status, {}
            return response.status, await response.json(content_type=None)

    async def _call(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        data: dict | None = None,
    ) -> dict:
        """One authenticated call. A 401 buys exactly one refresh + retry."""
        await self._ensure_token()
        status, body = await self._raw(method, path, params, data)

        if status == 401:
            self._token_expires = 0.0
            await self._ensure_token()
            status, body = await self._raw(method, path, params, data)

        if status != 200:
            raise EzhiCloudError(f"{method} {path} -> HTTP {status}")

        code = body.get("code")
        if code == DEVICE_OFFLINE_CODE:
            raise EzhiCloudOfflineError(
                f"{method} {path} -> the inverter is offline (code {code})"
            )
        if code in AUTH_ERROR_CODES:
            raise EzhiCloudAuthError(f"{method} {path} -> auth code {code}")
        if code != 0:
            raise EzhiCloudError(
                f"{method} {path} -> code={code} msg={body.get('message')}"
            )

        return body.get("data") or {}

    # --- public API -------------------------------------------------------

    async def async_get_config(self) -> dict:
        """The full controllable config.

        One GET covers everything v1 needs: onOff, systemMode, EPS, ECO,
        socMin, socMax. There is a separate socLimit GET, but it is a subset.
        """
        return await self._call(
            "GET",
            "remote/ezInverter/systemMode",
            params={"deviceId": self._device_id, "type": "EZHI",
                    "language": self._language},
        )
