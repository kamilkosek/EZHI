"""Unit tests for the EZHI cloud client.

No network, no Home Assistant: cloud.py is loaded by path and driven with a
scripted fake aiohttp session.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

_MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "apsystems_ezhi_local"
    / "cloud.py"
)
_spec = importlib.util.spec_from_file_location("ezhi_cloud", _MODULE_PATH)
cloud = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cloud)


class FakeResponse:
    def __init__(self, status: int, body: dict):
        self.status = status
        self._body = body

    async def json(self, content_type=None):
        return self._body


class FakeSession:
    """Scripted stand-in for aiohttp.ClientSession.

    `script` maps a URL substring to a list of FakeResponse. Each match pops the
    next response; the last one repeats forever.
    """

    def __init__(self, script: dict[str, list[FakeResponse]]):
        self.script = script
        self.calls: list[dict] = []

    async def request(self, method, url, params=None, data=None, headers=None):
        self.calls.append(
            {"method": method, "url": url, "params": params, "data": data,
             "headers": headers}
        )
        for key, queue in self.script.items():
            if key in url:
                return queue.pop(0) if len(queue) > 1 else queue[0]
        raise AssertionError(f"unscripted call: {method} {url}")

    def calls_to(self, needle: str) -> list[dict]:
        return [c for c in self.calls if needle in c["url"]]


def ok(data: dict) -> FakeResponse:
    return FakeResponse(200, {"code": 0, "data": data})


def make_api(session, **kwargs):
    defaults = dict(
        device_id="D02000000577",
        access_token="BOOTSTRAP",
        refresh_token="RT-UUID",
    )
    defaults.update(kwargs)
    return cloud.EzhiCloudApi(session=session, **defaults)


CONFIG = {
    "systemMode": "2", "EPS": "1", "ECO": "0", "userSetPower": "200",
    "socMin": "10", "socMax": "100", "onOff": "0", "powerLimit": "1200",
}


def test_bootstrap_refresh_precedes_first_call():
    """The very first API call must fetch a token, using the bootstrap bearer."""
    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"})],
        "systemMode": [ok(CONFIG)],
    })
    api = make_api(session)

    result = asyncio.run(api.async_get_config())

    assert result == CONFIG
    refreshes = session.calls_to("refreshToken")
    assert len(refreshes) == 1
    # The refresh authenticates with the (possibly expired) bootstrap token...
    assert refreshes[0]["headers"]["Authorization"] == "Bearer BOOTSTRAP"
    assert refreshes[0]["data"]["refresh_token"] == "RT-UUID"
    # ...and the actual call uses the fresh one.
    assert session.calls_to("systemMode")[0]["headers"]["Authorization"] == "Bearer JWT-1"


def test_401_triggers_exactly_one_refresh_and_retry():
    """A rejected token is refreshed once and the call retried once."""
    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"}), ok({"access_token": "JWT-2"})],
        "systemMode": [FakeResponse(401, {}), ok(CONFIG)],
    })
    api = make_api(session)

    result = asyncio.run(api.async_get_config())

    assert result == CONFIG
    assert len(session.calls_to("refreshToken")) == 2   # bootstrap + after the 401
    gets = session.calls_to("systemMode")
    assert len(gets) == 2                                # original + one retry
    assert gets[1]["headers"]["Authorization"] == "Bearer JWT-2"


def test_second_401_is_not_retried_again():
    """One retry, not a loop."""
    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"})],
        "systemMode": [FakeResponse(401, {})],
    })
    api = make_api(session)

    with pytest.raises(cloud.EzhiCloudError):
        asyncio.run(api.async_get_config())

    assert len(session.calls_to("systemMode")) == 2


def test_dead_refresh_token_raises_auth_error():
    """Codes 3000-3004 mean the refresh_token itself is gone."""
    session = FakeSession({
        "refreshToken": [FakeResponse(200, {"code": 3001, "message": "token expired"})],
    })
    api = make_api(session)

    with pytest.raises(cloud.EzhiCloudAuthError):
        asyncio.run(api.async_get_config())


def test_cached_token_is_reused():
    """A second call inside the TTL must not refresh again."""
    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"})],
        "systemMode": [ok(CONFIG)],
    })
    api = make_api(session)

    async def two_calls():
        # One event loop for both: the api holds an asyncio.Lock, which must not
        # be carried across loops.
        await api.async_get_config()
        await api.async_get_config()

    asyncio.run(two_calls())

    assert len(session.calls_to("refreshToken")) == 1
    assert len(session.calls_to("systemMode")) == 2
