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
        self.json_calls = 0

    async def json(self, content_type=None):
        self.json_calls += 1
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
        # Yield to the event loop so concurrent callers actually interleave --
        # without this a "concurrent" test runs strictly sequentially and would
        # pass even with the double-checked locking removed.
        await asyncio.sleep(0)
        self.calls.append(
            {"method": method, "url": url, "params": params, "data": data,
             "headers": headers}
        )
        for key, queue in self.script.items():
            if key in url:
                item = queue.pop(0) if len(queue) > 1 else queue[0]
                # A scripted Exception simulates a transport failure (e.g. a
                # dropped connection) instead of an HTTP response.
                if isinstance(item, Exception):
                    raise item
                return item
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
    gets = session.calls_to("systemMode")
    assert len(gets) == 1
    assert gets[0]["headers"]["Authorization"] == "Bearer JWT-1"


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
    """One retry, not a loop. A 401 that survives the retry means the stored
    credentials are dead, not transient -- that must surface as an auth error
    so the caller can offer reauth instead of retrying forever."""
    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"})],
        "systemMode": [FakeResponse(401, {})],
    })
    api = make_api(session)

    with pytest.raises(cloud.EzhiCloudAuthError):
        asyncio.run(api.async_get_config())

    assert len(session.calls_to("systemMode")) == 2
    assert len(session.calls_to("refreshToken")) == 2


def test_dead_refresh_token_raises_auth_error():
    """Codes 3000-3004 mean the refresh_token itself is gone."""
    session = FakeSession({
        "refreshToken": [FakeResponse(200, {"code": 3001, "message": "token expired"})],
    })
    api = make_api(session)

    with pytest.raises(cloud.EzhiCloudAuthError):
        asyncio.run(api.async_get_config())

    # A dead refresh_token must short-circuit before ever touching the
    # actual endpoint.
    assert session.calls_to("systemMode") == []


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


def test_non_200_response_still_reads_body_to_release_connection():
    """response.json() must be awaited even on failure. In real aiohttp that
    is what releases the connection back to the pool; it also means the
    server's error message is available instead of silently discarded."""
    response = FakeResponse(400, {"message": "bad request"})
    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"})],
        "systemMode": [response],
    })
    api = make_api(session)

    with pytest.raises(cloud.EzhiCloudError):
        asyncio.run(api.async_get_config())

    assert response.json_calls == 1


def test_transport_error_is_wrapped_as_cloud_error():
    """Nothing coming out of session.request may escape the exception
    hierarchy raw -- every caller downstream only knows about EzhiCloudError
    and its subclasses."""
    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"})],
        "systemMode": [OSError("boom")],
    })
    api = make_api(session)

    with pytest.raises(cloud.EzhiCloudError):
        asyncio.run(api.async_get_config())


def test_build_params_carries_untouched_fields_forward():
    """A mode switch must not silently drop the EPS/backup release."""
    params = cloud.build_system_mode_params(CONFIG, systemMode="4")

    assert params == {
        "systemMode": "4", "EPS": "1", "ECO": "0", "userSetPower": "200",
    }


def test_build_params_stringifies_and_ignores_extra_config_keys():
    config = {"systemMode": 2, "EPS": 1, "ECO": 0, "userSetPower": 200,
              "socMin": 10, "powerLimit": 1200}

    params = cloud.build_system_mode_params(config)

    assert params == {
        "systemMode": "2", "EPS": "1", "ECO": "0", "userSetPower": "200",
    }


def test_build_params_fails_loud_on_incomplete_config():
    """Never guess a default for a field that drives real hardware."""
    with pytest.raises(cloud.EzhiCloudError, match="EPS"):
        cloud.build_system_mode_params({"systemMode": "2", "ECO": "0",
                                        "userSetPower": "200"})


def test_build_params_rejects_unknown_kwargs():
    """A typo like `systemmode=` must not sail through as a silent no-op."""
    with pytest.raises(cloud.EzhiCloudError, match="systemmode"):
        cloud.build_system_mode_params(CONFIG, systemmode="4")


def test_build_params_normalises_bool_to_wire_string():
    """str(True) is "True" -- the cloud expects "1"/"0"."""
    config = {"systemMode": "2", "EPS": True, "ECO": "0", "userSetPower": "200"}

    params = cloud.build_system_mode_params(config)

    assert params["EPS"] == "1"


def test_turn_on_sends_status_zero():
    """status=0 turns the inverter ON. Inverted, and verified in the capture."""
    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"})],
        "onOff": [ok({"flag": True})],
    })
    api = make_api(session)

    asyncio.run(api.async_set_on_off(True))

    calls = session.calls_to("onOff")
    assert len(calls) == 1
    call = calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith("/remote/ezInverter/onOff/D02000000577")
    assert call["data"]["status"] == "0"


def test_turn_off_sends_status_one():
    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"})],
        "onOff": [ok({"flag": True})],
    })
    api = make_api(session)

    asyncio.run(api.async_set_on_off(False))

    calls = session.calls_to("onOff")
    assert len(calls) == 1
    assert calls[0]["data"]["status"] == "1"


def test_turn_on_while_offline_raises_offline_error():
    """flag:false + reason:1 -> the cloud cannot wake a powered-down inverter."""
    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"})],
        "onOff": [ok({"flag": False, "reason": 1})],
    })
    api = make_api(session)

    with pytest.raises(cloud.EzhiCloudOfflineError):
        asyncio.run(api.async_set_on_off(True))

    assert len(session.calls_to("onOff")) == 1


def test_turn_off_rejection_raises_plain_error_not_offline():
    """The offline diagnosis (with its concrete, possibly wrong battery-button
    advice) is only valid for a failed ON attempt with reason:1. A rejected
    OFF must not be misdiagnosed as the device being offline."""
    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"})],
        "onOff": [ok({"flag": False, "reason": 7})],
    })
    api = make_api(session)

    with pytest.raises(cloud.EzhiCloudError) as exc_info:
        asyncio.run(api.async_set_on_off(False))

    assert not isinstance(exc_info.value, cloud.EzhiCloudOfflineError)


def test_set_system_mode_posts_full_params_json():
    """async_set_system_mode fetches its own fresh config rather than trusting
    a cached one -- a poll can be up to a minute old, and writing a stale
    EPS/ECO back would undo a change made from the vendor app meanwhile."""
    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"})],
        # GET (fresh config) then POST (the write), same URL substring.
        "systemMode": [ok(CONFIG), ok({"flag": True})],
    })
    api = make_api(session)

    asyncio.run(api.async_set_system_mode(systemMode="4"))

    calls = session.calls_to("systemMode")
    assert len(calls) == 2
    get_call, post_call = calls
    assert get_call["method"] == "GET"
    assert post_call["method"] == "POST"
    assert post_call["data"]["deviceId"] == "D02000000577"
    assert post_call["data"]["identifierType"] == "1"
    assert post_call["data"]["maxPowerFlag"] == "0"
    assert json.loads(post_call["data"]["params"]) == {
        "systemMode": "4", "EPS": "1", "ECO": "0", "userSetPower": "200",
    }


def test_set_soc_limit_sends_both_bounds():
    """The socLimit endpoint takes both bounds, so both always travel."""
    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"})],
        "socLimit": [ok({"flag": True})],
    })
    api = make_api(session)

    asyncio.run(api.async_set_soc_limit(20, 95))

    calls = session.calls_to("socLimit")
    assert len(calls) == 1
    assert calls[0]["data"]["socMin"] == "20"
    assert calls[0]["data"]["socMax"] == "95"


def test_rejected_write_raises():
    """flag:false is a failure, never a success."""
    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"})],
        "socLimit": [ok({"flag": False})],
    })
    api = make_api(session)

    with pytest.raises(cloud.EzhiCloudError):
        asyncio.run(api.async_set_soc_limit(20, 95))

    assert len(session.calls_to("socLimit")) == 1


def test_set_soc_limit_rejects_implausible_bounds():
    """This writes real hardware config -- validate at the boundary even
    though the number entity will validate too. Must fail before any network
    call, not after."""
    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"})],
        "socLimit": [ok({"flag": True})],
    })
    api = make_api(session)

    with pytest.raises(cloud.EzhiCloudError):
        asyncio.run(api.async_set_soc_limit(95, 20))

    assert session.calls == []


def test_concurrent_first_calls_trigger_exactly_one_refresh():
    """Two callers racing on an unrefreshed token must not both refresh --
    this is the declared risk area for the double-checked locking in
    _ensure_token, and was previously only exercised sequentially."""
    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"})],
        "systemMode": [ok(CONFIG)],
    })
    api = make_api(session)

    async def both():
        return await asyncio.gather(
            api.async_get_config(), api.async_get_config()
        )

    results = asyncio.run(both())

    assert results == [CONFIG, CONFIG]
    assert len(session.calls_to("refreshToken")) == 1
    assert len(session.calls_to("systemMode")) == 2


def test_get_config_uses_deviceId_type_language_params():
    """Pin the systemMode GET parameter shape -- the plan's one declared open
    guess (docs/ezhi-cloud-api-map.md doesn't capture the query params). If
    Task 5's live probe finds a different shape, this test must be the thing
    that changes, deliberately."""
    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"})],
        "systemMode": [ok(CONFIG)],
    })
    api = make_api(session)

    asyncio.run(api.async_get_config())

    call = session.calls_to("systemMode")[0]
    assert call["params"] == {
        "deviceId": "D02000000577", "type": "EZHI", "language": "en",
    }
