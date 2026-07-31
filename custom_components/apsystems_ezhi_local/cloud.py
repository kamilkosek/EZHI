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
# the 401 path stays as the backstop. This is our refresh cadence, not the
# token's actual lifetime.
TOKEN_REFRESH_AFTER_SECONDS = 6000

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


def _wire_str(value: Any) -> str:
    """Format a value the way the cloud expects it: "1"/"0", never "True"."""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _is_truthy(value: Any) -> bool:
    """Accept a JSON bool or its string spelling: the cloud sends both.

    Write responses are unverified by the Task 5 live probe (it only checks
    the GET), and every field of the GET payload turned out to be a string --
    that is precisely why _wire_str exists. bool("false") is True in plain
    Python, so a naive truthy check would silently count a rejected write as
    a success.
    """
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "null")
    return bool(value)


def build_system_mode_params(config: dict, **changes: Any) -> dict[str, str]:
    """Read-modify-write: carry the current config forward, override `changes`.

    `config` is the payload of a systemMode GET. Raises rather than defaulting a
    missing field — a wrong guess here would reconfigure real hardware. Also
    raises on an unknown field name in `changes`, e.g. a typo, which would
    otherwise sail through as a silent no-op.
    """
    unknown = set(changes) - set(SYSTEM_MODE_KEYS)
    if unknown:
        raise EzhiCloudError(f"unknown systemMode field(s) {sorted(unknown)}")

    params = {
        key: _wire_str(config[key])
        for key in SYSTEM_MODE_KEYS
        if config.get(key) is not None
    }
    params.update({key: _wire_str(value) for key, value in changes.items()})

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
    ) -> None:
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

    # --- HTTP plumbing ------------------------------------------------------

    async def _http(
        self,
        method: str,
        url: str,
        *,
        params: dict | None = None,
        data: dict | None = None,
        headers: dict[str, str],
    ) -> tuple[int, dict]:
        """One HTTP round trip: timeout, transport-error wrapping, tolerant parse.

        Both the token endpoint and the API endpoints go through here. They
        used to carry their own copies of this error handling, and a fix
        applied to one copy but not the other cost us two separate bugs.
        """
        try:
            async with asyncio.timeout(self._timeout):
                response = await self._session.request(
                    method, url, params=params, data=data, headers=headers,
                )
                # A non-JSON body (e.g. an HTML error page from a
                # gateway/WAF, common on 401/403/502) must not stop the
                # caller from seeing the HTTP status.
                try:
                    body = await response.json(content_type=None)
                except ValueError:
                    body = {}
                return response.status, body
        except EzhiCloudError:
            raise
        except (TypeError, AttributeError, NameError, KeyError, IndexError):
            raise                      # our bug, not the network's
        except TimeoutError as err:
            raise EzhiCloudError(
                f"the EZHI cloud did not respond within {self._timeout}s "
                f"({method} {url}): {err!r}"
            ) from err
        except Exception as err:
            # Everything else coming out of session.request/response.json is
            # a transport failure by definition -- we cannot import aiohttp
            # here to catch its ClientError family by name, so this catches
            # broadly and re-wraps. The URL is included so a token-endpoint
            # failure and an API-endpoint failure don't read identically in
            # the HA log.
            raise EzhiCloudError(
                f"transport failure talking to the EZHI cloud ({method} {url}): {err!r}"
            ) from err

    # --- token handling ---------------------------------------------------

    async def _fetch_access_token(self) -> None:
        """Exchange the refresh_token for a new access_token.

        The refresh_token does not rotate, so it is never overwritten here.
        """
        status, body = await self._http(
            "POST",
            TOKEN_URL,
            data={"refresh_token": self._refresh_token,
                  "language": self._language},
            headers={"Authorization": f"Bearer {self._token}",
                     "Accept-Language": self._language},
        )

        code = body.get("code")
        if status in (401, 403) or code in AUTH_ERROR_CODES:
            raise EzhiCloudAuthError(
                f"refreshToken rejected (HTTP {status}, code {code}): the stored "
                "refresh_token is no longer valid — capture a new one from the app"
            )
        if status != 200:
            # 5xx/429 means the cloud is unwell, not that our credentials are.
            # Escalating here would stop HA polling and send the user on a
            # pointless token re-capture that cannot fix anything.
            raise EzhiCloudError(f"refreshToken -> HTTP {status}")
        if code != 0:
            raise EzhiCloudError(
                f"refreshToken failed: code={code} msg={body.get('message')}"
            )

        token = (body.get("data") or {}).get("access_token")
        if not token:
            raise EzhiCloudAuthError("refreshToken returned no access_token")

        self._token = token
        self._token_expires = time.monotonic() + TOKEN_REFRESH_AFTER_SECONDS
        _LOGGER.debug("EZHI cloud: access token refreshed")

    async def _ensure_token(self) -> None:
        if time.monotonic() < self._token_expires:
            return
        async with self._lock:
            # Another task may have refreshed while we waited for the lock.
            if time.monotonic() < self._token_expires:
                return
            await self._fetch_access_token()

    # --- request plumbing -------------------------------------------------

    async def _send_once(
        self, method: str, path: str, params: dict | None, data: dict | None,
        token: str,
    ) -> tuple[int, dict]:
        # Takes the bearer token as an explicit parameter rather than reading
        # self._token: the caller (_call) decides which token a given attempt
        # uses. That keeps the "first attempt uses the pre-refresh token,
        # the retry uses the fresh one" invariant structural instead of
        # relying on nothing suspending between the two reads of self._token.
        url = f"{API_URL}/{path.lstrip('/')}"
        return await self._http(
            method,
            url,
            params=params,
            data=data,
            headers={"Authorization": f"Bearer {token}",
                     "Accept-Language": self._language},
        )

    async def _call(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        data: dict | None = None,
    ) -> dict:
        """One authenticated call. A 401 buys exactly one refresh + retry."""
        # ponytail: worst case here is ~4x self._timeout (ensure_token, first
        # send, ensure_token again, retry send) with no wrapping deadline.
        # HA's DataUpdateCoordinator won't start an overlapping refresh, so
        # this can't compound -- add a wrapping deadline only if it ever does.
        await self._ensure_token()
        token_used = self._token
        status, body = await self._send_once(method, path, params, data, token_used)

        if status == 401:
            # ponytail: this capture-then-invalidate dance is untested -- no
            # dedicated test drives two concurrent callers into a 401 at the
            # same time. Left uncovered deliberately: the failure mode if it
            # regressed is a couple of wasted refresh calls, not a loop or a
            # correctness bug, and building the interleaving needed to hit
            # this window on purpose wasn't judged worth the ceremony.
            async with self._lock:
                # Only invalidate if nobody else refreshed while we waited --
                # otherwise a concurrent caller's fresh token gets discarded.
                if self._token == token_used:
                    self._token_expires = 0.0
            await self._ensure_token()
            # The retry must use the freshly refreshed token, not the one
            # captured above -- reusing token_used here would defeat the
            # refresh that was just forced.
            status, body = await self._send_once(method, path, params, data, self._token)

        if status == 401:
            raise EzhiCloudAuthError(
                f"{method} {path} -> HTTP 401 even with a freshly refreshed "
                "token; the stored credentials are no longer accepted"
            )

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

    async def async_set_on_off(self, on: bool) -> None:
        """Turn the inverter on or off.

        The wire format is inverted: status=0 is ON, status=1 is OFF.

        Turning ON only works while the inverter still answers over MQTT. Once it
        is really powered down the cloud cannot wake it — that needs PV/DC input
        or a 3 s press on the battery button. Verified 2026-07-31.
        """
        data = await self._call(
            "POST",
            f"remote/ezInverter/onOff/{self._device_id}",
            data={"status": "0" if on else "1", "type": "EZHI",
                  "language": self._language},
        )
        if not _is_truthy(data.get("flag")):
            if str(data.get("reason")) == "1":
                # reason:1 is an offline condition regardless of direction --
                # only the concrete recovery advice is ON-specific.
                if on:
                    raise EzhiCloudOfflineError(
                        f"the inverter rejected the on/off command (reason "
                        f"{data.get('reason')}) — it is powered down and the cloud "
                        "cannot wake it. Use PV/DC input or hold the battery button 3 s."
                    )
                raise EzhiCloudOfflineError(
                    f"the inverter is not reachable by the cloud (reason 1); "
                    f"the off command was not delivered: {data}"
                )
            raise EzhiCloudError(
                f"the inverter rejected the on/off command (on={on}): {data}"
            )

    async def async_set_system_mode(self, **changes: Any) -> None:
        """Write systemMode, carrying every untouched field forward.

        Reads the current config first rather than trusting a cached one: a
        poll can be up to a minute old, and writing a stale EPS/ECO back would
        undo a change made from the vendor app in the meantime.
        """
        config = await self.async_get_config()
        params = build_system_mode_params(config, **changes)
        data = await self._call(
            "POST",
            "remote/ezInverter/systemMode",
            data={
                "deviceId": self._device_id,
                "type": "EZHI",
                "identifierType": "1",
                "maxPowerFlag": "0",
                "language": self._language,
                "params": json.dumps(params),
            },
        )
        if not _is_truthy(data.get("flag")):
            raise EzhiCloudError(f"the inverter rejected systemMode={params}: {data}")

    async def async_set_soc_limit(self, soc_min: int, soc_max: int) -> None:
        """Write both SOC bounds. The endpoint takes them as a pair."""
        if not 0 <= soc_min < soc_max <= 100:
            raise EzhiCloudError(
                f"refusing an implausible SOC window {soc_min}..{soc_max}"
            )
        data = await self._call(
            "POST",
            "remote/ezInverter/socLimit",
            data={
                "deviceId": self._device_id,
                "type": "EZHI",
                "language": self._language,
                "socMin": str(int(soc_min)),
                "socMax": str(int(soc_max)),
            },
        )
        if not _is_truthy(data.get("flag")):
            raise EzhiCloudError(
                f"the inverter rejected socLimit {soc_min}..{soc_max}: {data}"
            )
