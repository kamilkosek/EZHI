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


class UnparsableResponse(FakeResponse):
    """A response whose body isn't JSON -- e.g. an HTML error page from a
    gateway/WAF in front of the API, which routinely happens on 401/403/502."""

    def __init__(self, status: int):
        super().__init__(status, body={})

    async def json(self, content_type=None):
        self.json_calls += 1
        raise ValueError("not JSON")


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


def test_dead_refresh_token_with_unparsable_body_raises_auth_error():
    """Gateways/WAFs routinely return an HTML error page, not JSON, for a 401
    or 403. The status check must still run even when the body can't be
    parsed -- otherwise the ValueError gets swallowed by the broad transport
    catch and the caller never learns the credentials are dead."""
    session = FakeSession({
        "refreshToken": [UnparsableResponse(401)],
    })
    api = make_api(session)

    with pytest.raises(cloud.EzhiCloudAuthError):
        asyncio.run(api.async_get_config())


def test_refresh_token_401_raises_auth_error():
    """401 on the token endpoint means the credentials themselves are
    rejected."""
    session = FakeSession({
        "refreshToken": [FakeResponse(401, {})],
    })
    api = make_api(session)

    with pytest.raises(cloud.EzhiCloudAuthError):
        asyncio.run(api.async_get_config())


def test_refresh_token_403_raises_auth_error():
    """403, like 401, means the credentials are rejected."""
    session = FakeSession({
        "refreshToken": [FakeResponse(403, {})],
    })
    api = make_api(session)

    with pytest.raises(cloud.EzhiCloudAuthError):
        asyncio.run(api.async_get_config())


def test_refresh_token_502_is_retryable_not_auth_error():
    """A transient 5xx from the cloud is not a dead credential. Escalating
    this to EzhiCloudAuthError would (via the coordinator) stop HA polling
    and send the user on a pointless token re-capture that cannot fix a
    server-side outage -- and it would never recover on its own."""
    session = FakeSession({
        "refreshToken": [FakeResponse(502, {})],
    })
    api = make_api(session)

    with pytest.raises(cloud.EzhiCloudError) as exc_info:
        asyncio.run(api.async_get_config())

    assert not isinstance(exc_info.value, cloud.EzhiCloudAuthError)


def test_refresh_token_429_is_retryable_not_auth_error():
    """429 (rate limited) is the cloud being unwell, not the credentials
    being dead -- same reasoning as the 502 case."""
    session = FakeSession({
        "refreshToken": [FakeResponse(429, {})],
    })
    api = make_api(session)

    with pytest.raises(cloud.EzhiCloudError) as exc_info:
        asyncio.run(api.async_get_config())

    assert not isinstance(exc_info.value, cloud.EzhiCloudAuthError)


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


def test_non_200_status_raises_even_when_body_code_is_zero():
    """A 5xx with a body that (oddly) claims code:0 must still raise on the
    HTTP status. Without this, test_non_200_response_still_reads_body_to_-
    release_connection is caught by two guards at once (status!=200, and the
    code!=0 fallback since its body has no "code" key) and pins neither --
    this isolates the status!=200 guard specifically."""
    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"})],
        "systemMode": [FakeResponse(500, {"code": 0})],
    })
    api = make_api(session)

    with pytest.raises(cloud.EzhiCloudError):
        asyncio.run(api.async_get_config())


def test_api_call_with_auth_error_code_raises_auth_error():
    """The body-code route is exactly how dead credentials get reported --
    covered on the token endpoint, but this pins it on an API endpoint too.
    Without a test, `if code in AUTH_ERROR_CODES` can be deleted from _call
    and every test still passes: it silently falls through to the generic
    code!=0 branch instead of the specific auth one."""
    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"})],
        "systemMode": [FakeResponse(200, {"code": 3001, "message": "bad"})],
    })
    api = make_api(session)

    with pytest.raises(cloud.EzhiCloudAuthError):
        asyncio.run(api.async_get_config())


def test_api_call_with_offline_code_raises_offline_error():
    """Same gap as above, for `if code == DEVICE_OFFLINE_CODE`."""
    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"})],
        "systemMode": [FakeResponse(200, {"code": 1001, "message": "offline"})],
    })
    api = make_api(session)

    with pytest.raises(cloud.EzhiCloudOfflineError):
        asyncio.run(api.async_get_config())


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


class FakeClientError(Exception):
    """Stands in for aiohttp.ClientError, which cloud.py cannot import to
    catch by name. An OSError-only test would miss a narrowed `except
    OSError` that still wraps every real-world transport failure it needs
    to; this is not an OSError, so it forces the catch to stay broad."""


def test_non_os_transport_error_is_also_wrapped():
    """A genuine aiohttp.ClientError (modelled here, since we cannot import
    it) must be wrapped exactly like an OSError is -- the transport catch
    must not be narrowly OSError-shaped."""
    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"})],
        "systemMode": [FakeClientError("connection reset")],
    })
    api = make_api(session)

    with pytest.raises(cloud.EzhiCloudError):
        asyncio.run(api.async_get_config())


def test_programming_error_propagates_unwrapped():
    """A bug in our own code (e.g. a malformed data payload raising
    TypeError) must surface as itself, not get misdiagnosed as a network
    problem -- the coordinator maps EzhiCloudError to a silent forever-retry,
    which would bury the traceback that shows the actual bug."""
    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"})],
        "systemMode": [TypeError("boom")],
    })
    api = make_api(session)

    with pytest.raises(TypeError):
        asyncio.run(api.async_get_config())


def test_timeout_error_message_names_the_budget():
    """A bare 'transport failure talking to the EZHI cloud: TimeoutError()'
    doesn't tell the user we gave up after N seconds -- name the configured
    timeout budget specifically for this case."""
    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"})],
        "systemMode": [TimeoutError("timed out")],
    })
    api = make_api(session)

    with pytest.raises(cloud.EzhiCloudError, match="15"):
        asyncio.run(api.async_get_config())


def test_transport_failure_message_includes_the_url():
    """Token and API failures must not read identically in the HA log --
    include the URL so a transport failure on the token endpoint is
    distinguishable from one on an API endpoint."""
    session = FakeSession({
        "refreshToken": [OSError("boom")],
    })
    api = make_api(session)

    with pytest.raises(cloud.EzhiCloudError, match="refreshToken"):
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


def test_build_params_carries_optional_fields_when_present():
    """dischargeProtection (a real battery deep-discharge floor, live value
    seen: 12%), stayOn, governmentLevies and area are carried forward when
    the config has them. Merge-vs-replace is unresolved for this endpoint --
    carrying these is harmless if the cloud merges and essential if it
    replaces."""
    config = {**CONFIG, "dischargeProtection": "12", "stayOn": "0",
              "governmentLevies": "1", "area": "DE"}

    params = cloud.build_system_mode_params(config, systemMode="4")

    assert params["dischargeProtection"] == "12"
    assert params["stayOn"] == "0"
    assert params["governmentLevies"] == "1"
    assert params["area"] == "DE"


def test_build_params_optional_fields_absence_does_not_raise():
    """Unlike the required four, a config lacking the optional four must not
    block a mode write."""
    params = cloud.build_system_mode_params(CONFIG, systemMode="4")

    assert "dischargeProtection" not in params
    assert "stayOn" not in params
    assert "governmentLevies" not in params
    assert "area" not in params


def test_is_truthy_accepts_json_bool_and_string_spelling():
    """The capture suggests real JSON booleans for write responses, but every
    field of the GET payload is a string -- the cloud plausibly sends both
    spellings, and bool("false") is True in plain Python."""
    assert cloud._is_truthy(True) is True
    assert cloud._is_truthy(False) is False
    assert cloud._is_truthy("true") is True
    assert cloud._is_truthy("1") is True
    assert cloud._is_truthy("false") is False
    assert cloud._is_truthy("0") is False
    assert cloud._is_truthy("") is False
    assert cloud._is_truthy(None) is False


def test_is_running_true_for_the_zero_spellings():
    """"0" (the capture), 0, False and 0.0 all mean "the inverter is
    running" -- switch.py's is_on and this must agree on what onOff's payload
    type actually is, and the test fixtures in this very file disagree with
    each other about it (line ~98 has a string socMin, line ~410 an int).
    Routed through wire_str, the same normalisation async_set_on_off's
    request body already relies on."""
    assert cloud.is_running("0") is True
    assert cloud.is_running(0) is True
    assert cloud.is_running(False) is True
    assert cloud.is_running(0.0) is True


def test_is_running_false_for_the_one_spellings():
    assert cloud.is_running("1") is False
    assert cloud.is_running(1) is False
    assert cloud.is_running(True) is False


def test_is_running_none_when_unknown():
    """No data yet -- not "off", which would tell an is_state('off')
    automation the wrong thing before the first poll has landed."""
    assert cloud.is_running(None) is None


def test_is_running_none_for_an_unmapped_value():
    """A value that normalises to neither "0" nor "1" must not be reported as
    "off" with false confidence -- the previous implementation's implicit
    `else False` would fail on the dangerous side: is_state(..., 'off') ->
    turn_on firing a hardware write while the inverter might be running."""
    assert cloud.is_running("2") is None
    assert cloud.is_running("") is None


def test_api_url_carries_the_v2_segment():
    """Every endpoint hangs off /aps-api-web/api/v2 -- measured, not inferred.

    Drop the segment and the cloud answers HTTP 200 with body code 4 "Internal
    Server Error" on every call: it looks like an outage, so the wrong path
    would be blamed on APsystems rather than on us. `endswith` assertions on the
    endpoint alone cannot catch that, hence this one pins the prefix.
    """
    assert cloud.API_URL == "https://app.api.apsystemsema.com:9223/aps-api-web/api/v2"
    # The token endpoint sits outside both the app path and the versioning.
    assert cloud.TOKEN_URL == "https://app.api.apsystemsema.com:9223/api/token/refreshToken"

    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"})],
        "systemMode": [ok(CONFIG)],
    })
    api = make_api(session)
    asyncio.run(api.async_get_config())

    assert session.calls_to("systemMode")[0]["url"] == (
        "https://app.api.apsystemsema.com:9223"
        "/aps-api-web/api/v2/remote/ezInverter/systemMode"
    )


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


def test_turn_on_with_reason_1_raises_offline_error():
    """on=True, reason:1 -> the cloud cannot wake a powered-down inverter.
    reason:1 means offline regardless of direction; the ON case also gets
    the concrete battery-button advice. Asserting on the message content
    (not just the exception type) is what kills a mutant that drops the
    `if on:` branch and puts this advice on the OFF case too."""
    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"})],
        "onOff": [ok({"flag": False, "reason": 1})],
    })
    api = make_api(session)

    with pytest.raises(cloud.EzhiCloudOfflineError) as exc_info:
        asyncio.run(api.async_set_on_off(True))

    assert "battery button" in str(exc_info.value)
    assert len(session.calls_to("onOff")) == 1


def test_turn_on_with_other_reason_raises_plain_error():
    """on=True, reason:7 (not 1) -> a rejection for some other reason is not
    an offline diagnosis."""
    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"})],
        "onOff": [ok({"flag": False, "reason": 7})],
    })
    api = make_api(session)

    with pytest.raises(cloud.EzhiCloudError) as exc_info:
        asyncio.run(api.async_set_on_off(True))

    assert not isinstance(exc_info.value, cloud.EzhiCloudOfflineError)


def test_turn_off_with_reason_1_raises_offline_error():
    """on=False, reason:1 -> offline is about reachability, not direction. If
    the inverter is offline and OFF is sent, it will likely also answer
    reason:1 -- a caller that handles offline specially must still see it,
    just without the ON-specific battery-button advice. Asserting the advice
    is ABSENT here is what pairs with the ON test's assertion that it IS
    present, together killing a mutant that drops the `if on:` branch."""
    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"})],
        "onOff": [ok({"flag": False, "reason": 1})],
    })
    api = make_api(session)

    with pytest.raises(cloud.EzhiCloudOfflineError) as exc_info:
        asyncio.run(api.async_set_on_off(False))

    assert "battery button" not in str(exc_info.value)
    assert len(session.calls_to("onOff")) == 1


def test_turn_on_with_string_reason_1_still_raises_offline_error():
    """reason:"1" (string) must be recognised the same as reason:1 (int) --
    Task 5 only probes the GET, never a write response, so the write
    response's field types are unverified. A bare `== 1` comparison would
    silently miss the string spelling."""
    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"})],
        "onOff": [ok({"flag": False, "reason": "1"})],
    })
    api = make_api(session)

    with pytest.raises(cloud.EzhiCloudOfflineError):
        asyncio.run(api.async_set_on_off(True))


def test_turn_off_with_other_reason_raises_plain_error():
    """on=False, reason:7 (not 1) -> a rejected OFF for some other reason
    must not be misdiagnosed as the device being offline."""
    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"})],
        "onOff": [ok({"flag": False, "reason": 7})],
    })
    api = make_api(session)

    with pytest.raises(cloud.EzhiCloudError) as exc_info:
        asyncio.run(api.async_set_on_off(False))

    assert not isinstance(exc_info.value, cloud.EzhiCloudOfflineError)


def test_turn_on_with_float_or_bool_reason_1_still_raises_offline_error():
    """reason:1.0 or reason:True must land on the offline branch too -- a
    bare str() comparison (str(1.0) == "1.0", str(True) == "True") would
    silently fall through to the generic error and the user loses the
    battery-button recovery advice. Same fix as is_running, applied to the
    write response's reason field."""
    for reason in (1.0, True):
        session = FakeSession({
            "refreshToken": [ok({"access_token": "JWT-1"})],
            "onOff": [ok({"flag": False, "reason": reason})],
        })
        api = make_api(session)

        with pytest.raises(cloud.EzhiCloudOfflineError):
            asyncio.run(api.async_set_on_off(True))


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


def test_set_system_mode_raises_on_rejection():
    """flag:false is a failure, never a success -- a rejected mode change
    must not silently count as one. The flag check already exists in the
    code but, before this test, deleting it left the suite green: the only
    existing test scripted flag:True and only asserted the payload."""
    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"})],
        "systemMode": [ok(CONFIG), ok({"flag": False})],
    })
    api = make_api(session)

    with pytest.raises(cloud.EzhiCloudError):
        asyncio.run(api.async_set_system_mode(systemMode="4"))


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


def test_rejected_write_with_string_flag_still_raises():
    """Task 5 only probes the GET, never a write response -- the capture
    suggests real JSON booleans for `flag`, but every field of the GET
    payload is a string, so a write response plausibly sends "false" too.
    bool("false") is True in plain Python: a rejected write would silently
    count as success without a spelling-tolerant check."""
    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"})],
        "socLimit": [ok({"flag": "false"})],
    })
    api = make_api(session)

    with pytest.raises(cloud.EzhiCloudError):
        asyncio.run(api.async_set_soc_limit(20, 95))


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


def test_set_soc_limit_with_both_bounds_does_not_re_read():
    """Both bounds supplied -- nothing stale to protect against, so no GET."""
    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"})],
        "socLimit": [ok({"flag": True})],
    })
    api = make_api(session)

    asyncio.run(api.async_set_soc_limit(20, 95))

    assert session.calls_to("systemMode") == []


def test_set_soc_limit_fetches_the_omitted_bound():
    """Setting only socMax must not trust a cached socMin -- a poll can be up
    to a minute old, and writing a stale bound back would revert a change
    made from the vendor app meanwhile. Same freshness rule as
    async_set_system_mode, now applied to its twin endpoint too."""
    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"})],
        # The socLimit-fetch GET reuses the systemMode endpoint (async_get_config).
        "systemMode": [ok(CONFIG)],
        "socLimit": [ok({"flag": True})],
    })
    api = make_api(session)

    asyncio.run(api.async_set_soc_limit(soc_max=90))

    assert len(session.calls_to("systemMode")) == 1
    post_call = session.calls_to("socLimit")[0]
    assert post_call["data"]["socMin"] == "10"  # CONFIG's socMin, freshly read
    assert post_call["data"]["socMax"] == "90"


def test_set_soc_limit_fetches_the_omitted_min_bound():
    """The mirror of test_set_soc_limit_fetches_the_omitted_bound, and the
    exact path number.EzhiCloudSocNumber's async_set_native_value takes on
    every single write of *_soc_minimum: only soc_min supplied, soc_max
    fetched fresh."""
    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"})],
        "systemMode": [ok(CONFIG)],
        "socLimit": [ok({"flag": True})],
    })
    api = make_api(session)

    asyncio.run(api.async_set_soc_limit(soc_min=15))

    assert len(session.calls_to("systemMode")) == 1
    post_call = session.calls_to("socLimit")[0]
    assert post_call["data"]["socMin"] == "15"
    assert post_call["data"]["socMax"] == "100"  # CONFIG's socMax, freshly read


def test_set_soc_limit_accepts_a_float_style_string_bound():
    """The read side (number.py's _safe_float) is fine with "100.0"; the
    write side must accept exactly what the read side just displayed. Before
    this, editing only socMin failed whenever the untouched socMax came back
    from the cloud as "100.0", because _to_int's plain int() rejects it."""
    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"})],
        "systemMode": [ok({**CONFIG, "socMax": "100.0"})],
        "socLimit": [ok({"flag": True})],
    })
    api = make_api(session)

    asyncio.run(api.async_set_soc_limit(soc_min=15))

    post_call = session.calls_to("socLimit")[0]
    assert post_call["data"]["socMax"] == "100"


def test_set_soc_limit_raises_when_fetched_config_lacks_the_bound():
    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"})],
        "systemMode": [ok({"onOff": "0"})],  # no socMin/socMax in this payload
    })
    api = make_api(session)

    with pytest.raises(cloud.EzhiCloudError, match="socMin/socMax"):
        asyncio.run(api.async_set_soc_limit(soc_max=90))


def test_set_soc_limit_rejects_non_numeric_config_field():
    """A malformed cloud value must surface as EzhiCloudError, not a bare
    ValueError escaping past the client's documented exception contract."""
    session = FakeSession({
        "refreshToken": [ok({"access_token": "JWT-1"})],
        "systemMode": [ok({**CONFIG, "socMin": "not-a-number"})],
    })
    api = make_api(session)

    with pytest.raises(cloud.EzhiCloudError, match="socMin"):
        asyncio.run(api.async_set_soc_limit(soc_max=90))


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
