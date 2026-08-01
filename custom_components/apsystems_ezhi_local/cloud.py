"""Cloud control client for the APsystems EZHI (EMA cloud).

Control commands are cloud-only: the local HTTP API exposes five read endpoints
plus setPower and nothing else. Verified exhaustively 2026-07-30/31.

Endpoint paths and the systemMode field vocabulary come from the vendor
app's own bundled API client, read out of the decompiled APK, not from a
packet capture. Where a capture and the app source disagreed, the app source
won -- an early transcription of the base URL dropped the /api/v2 segment,
which every endpoint answers with a misleading "Internal Server Error".

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
# The /api/v2 segment is mandatory and measured, not inferred: without it every
# remote/ezInverter endpoint answers HTTP 200 with body code 4 "Internal Server
# Error" -- which reads like a cloud outage, not a wrong path. Probed 2026-08-01
# across six read endpoints, all six code 4 -> code 0 with the segment. The
# reference doc contradicted itself here; test_api_url_carries_the_v2_segment
# pins it so a future edit cannot quietly drop it again.
API_URL = f"{BASE_URL}/aps-api-web/api/v2"
# The token endpoint is NOT under /aps-api-web and NOT versioned. Verified live.
TOKEN_URL = f"{BASE_URL}/api/token/refreshToken"
LOGIN_URL = f"{BASE_URL}/api/token/generateToken/user/loginEncrypt"

# Login credentials from the vendor app, recovered from the decompiled APK
# (S0/c.java, called from com/apsystems/apeasypower/http/d.java). They are
# constants of the app, identical for every user, and trivially extractable
# from the APK by anyone -- but see the README: shipping them is what removes
# the HTTPS-proxy capture from the setup instructions.
LOGIN_APP_ID = "4029817264d4821d0164d4821dd80015"
LOGIN_APP_SECRET = "EZAd2023"
# RSA-2048 public key the app wraps the per-login AES key and IV in.
LOGIN_PUBLIC_KEY_DER_B64 = (
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAgdwBhVodMQ84lYZhDSGOUDQAks+NMa7WQ83mR1OyHiIW"
    "tZ1wWAh4H7fclkdNS3lWCmDH9ldF7Kf6JlEvZTc0Textv+YMLXO2gdDIoBvg7vlhY4HxOjXUIFQ+s7cWRrmEIgVV"
    "nTBLZU1GMC8zld7WH9v9EYCAqK7rvGJP0STZ/g6BP8RGJKhdpY6b+ndMXRUBYwkqy8m1SDJHm1FeHSLQWTaWbP5p"
    "z1yrGkkwvx+pib6wli+WE70/uPHp0zXZK5iUwmRQfOkTjDOGJyEE1dqkfHDTqne5ED81M4fCIEFYhyvnr1rifVJK"
    "HCDRGYQpJ0CiffjjH1ZOGSIN4JPG1EEIjQIDAQAB"
)

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


# The systemMode POST MERGES into the cloud's existing params, it does not
# replace the blob. Settled 2026-08-01 from two independent directions: the
# vendor app sends a different, partial field set per mode (mode 4 sends only
# systemMode/stayOn/thirdLink, mode 3 sometimes only systemMode/tax), which
# under replace semantics would wipe SOC bounds and EPS on every mode switch
# in the app itself; and a live mode-4 write from the app left EPS,
# dischargeProtection, socMin/socMax and powerLimit all untouched.
#
# Carrying these forward is therefore belt-and-braces rather than load-
# bearing. It stays because re-writing a just-read value costs nothing --
# but see SYSTEM_MODE_SETTABLE_KEYS for the case where it costs plenty.
#
# Required: a config that doesn't have these yet is refused rather than
# guessed at, since a wrong guess drives real hardware and all four always
# exist once the cloud has answered even once.
SYSTEM_MODE_KEYS = ("systemMode", "EPS", "ECO", "userSetPower")
# Carried forward when present, never required: dischargeProtection is a real
# battery deep-discharge floor (live value seen: 12%), and a config lacking
# any of these must not block a mode write.
#
# The full write vocabulary comes from the vendor app's own payload builders.
# Deliberately NOT included:
# outputPowerStrategy and outputPowerStrategyWeekly. Those are lists, and
# every value here goes through wire_str -- carrying a schedule forward as
# str(list) would corrupt it.
SYSTEM_MODE_OPTIONAL_KEYS = ("dischargeProtection", "stayOn", "governmentLevies", "area")

# Accepted in `changes`, but deliberately NOT carried forward on their own.
#
# powerLimit is why this third category exists. It is the high-power setting
# (800 vs 1200 W), and 1200 W is the one the app gates behind a disclaimer
# about exceeding regulatory feed-in limits. Carrying it forward would re-
# assert that value on every unrelated mode switch or SOC edit -- turning a
# deliberate, acknowledged choice into something the integration keeps
# re-asserting on the user's behalf, and putting it on the wire during writes
# that have nothing to do with it. Under the merge semantics the cloud actually
# has, carrying it buys nothing anyway: the cloud keeps the value regardless.
#
# Set it only through async_set_high_power, which is what the acknowledgement
# gate in the service handler guards.
#
# singlePhase and thirdLink are topology, not preferences: re-writing them
# from a poll is pointless and their coupling to the rest is unverified.
SYSTEM_MODE_SETTABLE_KEYS = ("powerLimit", "singlePhase", "thirdLink", "socMin")

# The firmware treats ECO and EPS as mutually exclusive: ECO=1 forces EPS=0
# (verified 2026-07-31). Both always travel in one write so the pair can never
# be observed, even briefly, in a state the device would not accept.
ECO_EPS_EXCLUSIVE = True

# The app's own rule for the deep-discharge floor: "the effective discharge
# protection threshold must be at least 2% above the configured minimum SOC".
DISCHARGE_PROTECTION_MARGIN = 2

# "High power mode" in the vendor app is nothing but these two values of
# powerLimit -- currentPower is only ever assigned minPower or maxPower, never
# anything between. maxPowerFlag stays "0" either way; the app never sets it to
# "1" anywhere in its bundle, and remote/ezInverter/maxPower/{userId} is a GET
# that asks what ceiling this account is allowed, not a write.
#
# 1200 is the app's built-in maxPower default. It can in principle be lowered
# per account by that GET, so a device that clamps 1200 to something else is
# possible -- the post-write re-read is what tells the truth.
STANDARD_POWER_LIMIT = 800
HIGH_POWER_LIMIT = 1200


def weekly_schedule_powers(config: dict) -> list[int]:
    """The watt values encoded in the weekly output schedule.

    Format decoded from the app's own strategy handling: HHMMSS start, HHMMSS
    end, one mode digit, then four digits of watts --
    "07000021000020050" is 07:00:00-21:00:00, mode 2, 50 W. Only the trailing
    power is needed here, so nothing else is parsed and a string that does not
    fit the shape is skipped rather than guessed at.
    """
    powers = []
    # Only the weekly schedule. The daily outputPowerStrategy is deliberately
    # not parsed here: its entries were empty on every config seen, so the watt
    # encoding is unverified, and guessing at it would either miss entries or
    # invent them. A daily entry above a newly lowered ceiling would therefore
    # slip past _check_power_limit_vs_schedule -- worth a capture before anyone
    # relies on that guard being exhaustive.
    for block in config.get("outputPowerStrategyWeekly") or []:
        if not isinstance(block, dict):
            continue
        for entry in block.get("strategy") or []:
            text = str(entry)
            if len(text) >= 4 and text[-4:].isdigit():
                powers.append(int(text[-4:]))
    return powers


def _check_power_limit_vs_schedule(config: dict, changes: dict) -> None:
    """Refuse a power limit that would leave schedule entries above the ceiling.

    The vendor app handles this by silently rewriting every schedule entry
    above the new limit down to it. This refuses instead. Two reasons: a
    schedule the user built is not ours to rewrite as a side effect of a
    different setting, and we have never written an outputPowerStrategyWeekly
    to this cloud -- doing it for the first time inside an unrelated call, on
    a format decoded by inspection, is how schedules get corrupted.
    """
    if "powerLimit" not in changes:
        return
    limit = _as_int(changes["powerLimit"])
    if limit is None:
        return
    over = sorted({p for p in weekly_schedule_powers(config) if p > limit})
    if over:
        raise EzhiCloudError(
            f"refusing to set the power limit to {limit} W: the weekly output "
            f"schedule still has entries at {', '.join(f'{p} W' for p in over)}. "
            "Lower those in the APsystems app first -- this integration will not "
            "rewrite a schedule as a side effect of a power-limit change"
        )


def _as_int(value: Any) -> int | None:
    """Best-effort int from a cloud field, which is a string more often than not."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _check_soc_window(soc_min: int, soc_max: int) -> None:
    """Refuse an impossible SOC window. This writes real hardware config."""
    if not 0 <= soc_min < soc_max <= 100:
        raise EzhiCloudError(
            f"refusing an implausible SOC window {soc_min}..{soc_max}"
        )


def _check_discharge_protection(config: dict, changes: dict) -> None:
    """Refuse a deep-discharge floor the device would silently clamp.

    The vendor app enforces `dischargeProtection >= socMin + 2`. Both write
    paths that can move either value call this: async_set_system_mode and
    async_set_soc_limit. It used to be only the first, and this docstring
    claimed that was the only way in -- while the shipped SOC Minimum entity
    went through the second and skipped the check entirely. Checked against
    the config that was just re-read, so a socMin changed from the app a
    minute ago still counts.

    Only checks when the caller is actually moving one of the two -- a mode
    switch that merely carries an already-out-of-range pair forward must not
    be blocked by a value it did not set.
    """
    if "dischargeProtection" not in changes and "socMin" not in changes:
        return
    floor = _as_int(changes.get("dischargeProtection", config.get("dischargeProtection")))
    soc_min = _as_int(changes.get("socMin", config.get("socMin")))
    if floor is None or soc_min is None:
        return
    if floor < soc_min + DISCHARGE_PROTECTION_MARGIN:
        raise EzhiCloudError(
            f"discharge protection {floor}% must be at least "
            f"{DISCHARGE_PROTECTION_MARGIN}% above the minimum SOC ({soc_min}%) "
            f"-- use {soc_min + DISCHARGE_PROTECTION_MARGIN}% or higher, or lower "
            "the minimum SOC first"
        )


def wire_str(value: Any) -> str:
    """Format a value the way the cloud expects it: "1"/"0", never "True".

    Public (no leading underscore): select.py's current_option reads the same
    systemMode payload this normalises for writes, and needs to agree with it
    -- a raw `str(2.0)` gives "2.0", not the "2" this produces.
    """
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _is_truthy(value: Any) -> bool:
    """Accept a JSON bool or its string spelling: the cloud sends both.

    Write responses are unverified by the Task 5 live probe (it only checks
    the GET), and every field of the GET payload turned out to be a string --
    that is precisely why wire_str exists. bool("false") is True in plain
    Python, so a naive truthy check would silently count a rejected write as
    a success.
    """
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "null")
    return bool(value)


def _to_int(value: Any, field: str) -> int:
    """Parse a cloud-config field to int.

    int(float(value)), not int(value): the read side (number.py's
    _safe_float) is fine with a value like "100.0", and the write side must
    accept exactly what the read side just displayed -- otherwise editing one
    SOC bound legitimately fails because the *other*, untouched bound came
    back from the cloud as "100.0" and int() alone rejects it outright.

    Wraps a malformed value in EzhiCloudError instead of letting a bare
    ValueError escape: this runs on data read back from the cloud (untrusted),
    not on a value we constructed ourselves, so it belongs with the other
    "the cloud sent something we didn't expect" cases, not the programming-
    error list _http() deliberately leaves unwrapped.
    """
    try:
        return int(float(value))
    except (TypeError, ValueError) as err:
        raise EzhiCloudError(
            f"cloud config field {field!r} is not numeric: {value!r}"
        ) from err


def is_running(on_off_value: Any) -> bool | None:
    """Read the inverted onOff field: "0" means the inverter is running.

    Tolerates the spellings the cloud might use for the same value -- the
    payload types are not verified until the live probe runs, and
    tests/test_cloud.py already disagrees with itself about whether socMin
    (a sibling field of the same GET payload) is a string or an int. Routed
    through wire_str rather than a bare `str(...) == "0"` comparison so a
    bool or float value normalises the same way async_set_on_off's own
    request body does.

    Returns None -- not a guess -- for a value that normalises to neither "0"
    nor "1". A default of False here would report "off" with full confidence
    while the inverter might be running, and an is_state(..., 'off') ->
    turn_on automation would then fire a hardware write on bad information.
    select.py's current_option and number.py's _safe_float already refuse to
    guess the same way for their own unmapped/unparsable values.
    """
    if on_off_value is None:
        return None
    wire = wire_str(on_off_value)
    if wire == "0":
        return True
    if wire == "1":
        return False
    return None


def build_system_mode_params(config: dict, **changes: Any) -> dict[str, str]:
    """Read-modify-write: carry the current config forward, override `changes`.

    `config` is the payload of a systemMode GET. Raises rather than defaulting a
    required field that's missing — a wrong guess here would reconfigure real
    hardware. Also raises on an unknown field name in `changes`, e.g. a typo,
    which would otherwise sail through as a silent no-op.

    The four SYSTEM_MODE_OPTIONAL_KEYS travel along too when the config has
    them, but their absence is never an error: see the module comment above
    SYSTEM_MODE_KEYS for why both required-and-strict and optional-and-best-
    effort are correct for the same unresolved merge-vs-replace question.
    """
    known_fields = (set(SYSTEM_MODE_KEYS) | set(SYSTEM_MODE_OPTIONAL_KEYS)
                    | set(SYSTEM_MODE_SETTABLE_KEYS))
    unknown = set(changes) - known_fields
    if unknown:
        raise EzhiCloudError(f"unknown systemMode field(s) {sorted(unknown)}")

    params = {
        key: wire_str(config[key])
        for key in SYSTEM_MODE_KEYS
        if config.get(key) is not None
    }
    params.update({
        key: wire_str(config[key])
        for key in SYSTEM_MODE_OPTIONAL_KEYS
        if config.get(key) is not None
    })
    params.update({key: wire_str(value) for key, value in changes.items()})

    missing = [key for key in SYSTEM_MODE_KEYS if key not in params]
    if missing:
        raise EzhiCloudError(
            f"cannot build a systemMode payload, the cloud config is missing "
            f"{missing} — refusing to write a partial configuration"
        )
    return params


async def _http_request(
    session: Any,
    timeout: int,
    method: str,
    url: str,
    *,
    params: dict | None = None,
    data: dict | None = None,
    headers: dict[str, str],
) -> tuple[int, dict]:
    """One HTTP round trip: timeout, transport-error wrapping, tolerant parse.

    The token endpoint, the API endpoints and the login all go through here.
    They used to carry their own copies of this error handling, and a fix
    applied to one copy but not the other cost us two separate bugs. Module
    level rather than a method because login runs before there is a client.
    """
    try:
        async with asyncio.timeout(timeout):
            response = await session.request(
                method, url, params=params, data=data, headers=headers,
            )
            # A non-JSON body (e.g. an HTML error page from a gateway/WAF,
            # common on 401/403/502) must not stop the caller from seeing
            # the HTTP status.
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
            f"the EZHI cloud did not respond within {timeout}s "
            f"({method} {url}): {err!r}"
        ) from err
    except Exception as err:
        # Everything else coming out of session.request/response.json is a
        # transport failure by definition -- we cannot import aiohttp here to
        # catch its ClientError family by name, so this catches broadly and
        # re-wraps. The URL is included so a token-endpoint failure and an
        # API-endpoint failure don't read identically in the HA log.
        raise EzhiCloudError(
            f"transport failure talking to the EZHI cloud ({method} {url}): {err!r}"
        ) from err


# --- login ------------------------------------------------------------------
#
# The app does not send the password in the clear. Per login it draws a random
# AES-256 key and IV, RSA-wraps both under a public key baked into the APK, and
# sends the credentials AES-CBC encrypted. Reproduced from S0/c.java; the odd
# parts are faithful to the app and not cleanups waiting to happen:
#
#   * the AES key is the *hex text* of 16 random bytes (32 chars -> AES-256),
#     not the bytes themselves; the IV is a 16-digit decimal string
#   * padding is manual zero-fill, and on an exact block multiple the app adds
#     a whole extra block of zeros. PKCS7 here would be rejected.
#
# A wrong reproduction of either fails as "wrong password", so both are pinned
# by tests against fixed key/IV vectors.


def _aes_hex(plain: str, key: str, iv: str) -> str:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    raw = plain.encode()
    raw += b"\0" * (16 - len(raw) % 16)
    encryptor = Cipher(algorithms.AES(key.encode()), modes.CBC(iv.encode())).encryptor()
    return (encryptor.update(raw) + encryptor.finalize()).hex()


def _rsa_b64(text: str) -> str:
    import base64

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    public_key = serialization.load_der_public_key(
        base64.b64decode(LOGIN_PUBLIC_KEY_DER_B64)
    )
    return base64.b64encode(
        public_key.encrypt(text.encode(), padding.PKCS1v15())
    ).decode()


def build_login_params(
    username: str, password: str, *, key: str | None = None, iv: str | None = None,
) -> dict[str, str]:
    """The form body for loginEncrypt.

    key/iv are injectable so the crypto can be tested against fixed vectors;
    production always draws them fresh.
    """
    import os
    import secrets

    if key is None:
        key = os.urandom(16).hex()                       # 32 chars -> AES-256
    if iv is None:
        iv = f"{secrets.randbelow(10 ** 16):016d}"       # 16 chars -> CBC IV
    return {
        "app_id": LOGIN_APP_ID,
        "app_secret": LOGIN_APP_SECRET,
        "key": _rsa_b64(key),
        "version": _rsa_b64(iv),
        "username": _aes_hex(username, key, iv),
        "password": _aes_hex(password, key, iv),
    }


async def async_login(
    session: Any,
    username: str,
    password: str,
    language: str = "en",
    timeout: int = 15,
) -> dict[str, str]:
    """Trade EMA account credentials for a token pair.

    Returns ``{"access_token": ..., "refresh_token": ...}``. The refresh_token
    does not rotate, so this only has to succeed once -- but doing it here
    rather than telling the user to run an HTTPS proxy is the difference
    between a setup a person can complete and one they cannot.

    The password is used to build the request and is never stored or logged.
    """
    status, body = await _http_request(
        session,
        timeout,
        "POST",
        LOGIN_URL,
        data={**build_login_params(username, password), "language": language},
        headers={"Accept-Language": language},
    )

    if status != 200:
        # 5xx/429 is the cloud being unwell, not a bad password. Saying
        # "wrong credentials" here would send the user to change a password
        # that was fine.
        raise EzhiCloudError(f"loginEncrypt -> HTTP {status}")

    code = body.get("code")
    if code != 0:
        raise EzhiCloudAuthError(
            f"login rejected by the EZHI cloud (code={code}): "
            f"{body.get('message') or 'check the username -- the account username, '
                                     'not the e-mail address -- and the password'}"
        )

    data = body.get("data") or {}
    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")
    if not access_token or not refresh_token:
        raise EzhiCloudAuthError(
            "login succeeded but the response carried no token pair"
        )
    _LOGGER.debug("EZHI cloud: login succeeded, token pair obtained")
    return {"access_token": access_token, "refresh_token": refresh_token}


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
        # Separate from the token lock, and held across a whole read-modify-
        # write. Both write paths GET the config, change a field and POST the
        # result; two of them interleaving means the second POST carries the
        # first one's pre-change read, and both report success. Setting SOC
        # minimum and maximum in quick succession is enough to hit it.
        self._write_lock = asyncio.Lock()

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
        return await _http_request(
            self._session, self._timeout, method, url,
            params=params, data=data, headers=headers,
        )

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
            # wire_str, not a bare str(): reason=1.0 or reason=True must land
            # on the offline branch too, the same normalisation is_running
            # was moved onto for the same reason -- a bare comparison here
            # would silently fall through to the generic error and the user
            # loses the battery-button recovery instructions.
            if wire_str(data.get("reason")) == "1":
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
        async with self._write_lock:
            config = await self.async_get_config()
            _check_discharge_protection(config, changes)
            _check_power_limit_vs_schedule(config, changes)
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

    async def async_set_backup_power(self, on: bool) -> None:
        """Turn EPS (backup / emergency power) on or off.

        Enabling backup also clears ECO in the same write: the firmware treats
        them as mutually exclusive, so sending EPS alone would leave the pair
        in a state the device rejects or silently corrects. Disabling backup
        does NOT set ECO -- off is off, not "switch to the other one".

        The vendor app only exposes this in modes 1, 2 and 5, but the write
        does land in Local mode (4) too: measured 2026-08-01, EPS went 1 -> 0
        -> 1 from Home Assistant while the device stayed in mode 4, with no
        change to any other config field. The app hiding the switch is a UI
        decision, not an API restriction.
        """
        changes = {"EPS": "1", "ECO": "0"} if on else {"EPS": "0"}
        await self.async_set_system_mode(**changes)

    async def async_set_eco(self, on: bool) -> None:
        """Turn ECO mode on or off, clearing EPS when enabling it.

        Mirror image of async_set_backup_power -- see there for why the pair
        travels together.
        """
        changes = {"ECO": "1", "EPS": "0"} if on else {"ECO": "0"}
        await self.async_set_system_mode(**changes)

    async def async_set_high_power(self, enable: bool) -> None:
        """Switch the output ceiling between 800 W and 1200 W.

        This is the app's "high power mode", which is not a mode at all -- just
        these two values of powerLimit. Enabling it carries the app's own
        disclaimer: 1200 W "may cause the device output to exceed regulatory
        limits for grid connection", with the legal risk on the operator. The
        acknowledgement gate lives in the service handler, not here, so any
        other caller has to make that decision explicitly too.

        Lowering back to 800 W is refused while the weekly schedule still has
        entries above it -- see _check_power_limit_vs_schedule.
        """
        await self.async_set_system_mode(
            powerLimit=HIGH_POWER_LIMIT if enable else STANDARD_POWER_LIMIT
        )

    async def async_set_soc_limit(
        self, soc_min: int | None = None, soc_max: int | None = None
    ) -> None:
        """Write the SOC bounds. The endpoint takes them as a pair.

        Re-reads the current config rather than trusting a cached one: a poll
        can be up to a minute old, and writing a stale bound back would undo a
        change made from the vendor app in the meantime -- the same freshness
        rule async_set_system_mode already applies to systemMode/EPS/ECO/
        userSetPower. The re-read is unconditional, because the discharge
        protection check needs the current floor even when the caller supplied
        both bounds.
        """
        # What the caller is actually moving, as opposed to what the payload
        # carries: this endpoint always sends both bounds, but a bound that is
        # only being carried forward must not trip a guard it did not move.
        requested = {
            key: value
            for key, value in (("socMin", soc_min), ("socMax", soc_max))
            if value is not None
        }
        if soc_min is not None and soc_max is not None:
            # The caller already gave us everything needed to judge the window,
            # so an impossible one is refused without touching the network.
            _check_soc_window(_to_int(soc_min, "socMin"), _to_int(soc_max, "socMax"))
        async with self._write_lock:
            config = await self.async_get_config()
            if soc_min is None:
                soc_min = config.get("socMin")
            if soc_max is None:
                soc_max = config.get("socMax")
            if soc_min is None or soc_max is None:
                raise EzhiCloudError(
                    "cannot build a socLimit payload, the cloud config is missing "
                    "socMin/socMax -- refusing to write a partial configuration"
                )
            soc_min = _to_int(soc_min, "socMin")
            soc_max = _to_int(soc_max, "socMax")
            _check_soc_window(soc_min, soc_max)
            # Same rule as on the systemMode path. Raising socMin above
            # dischargeProtection - 2 is refused here too, otherwise the shipped
            # SOC Minimum entity would be a way around the guard.
            _check_discharge_protection(config, requested)
            data = await self._call(
                "POST",
                "remote/ezInverter/socLimit",
                data={
                    "deviceId": self._device_id,
                    "type": "EZHI",
                    "language": self._language,
                    "socMin": str(soc_min),
                    "socMax": str(soc_max),
                },
            )
        if not _is_truthy(data.get("flag")):
            raise EzhiCloudError(
                f"the inverter rejected socLimit {soc_min}..{soc_max}: {data}"
            )
