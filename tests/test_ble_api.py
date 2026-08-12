"""The Bluetooth API must be interchangeable with the cloud one.

Entities call coordinator.api.async_set_*, so anything the cloud API offers and
the Bluetooth API does not is a crash waiting for the user to flip the option.

The config fixture is the inverter's real systemMode payload, read out of the
2026-08-05 capture -- a made-up one would not exercise the required-field rules
in build_system_mode_params.
"""
from __future__ import annotations

import asyncio

import pytest
from ezhi_component import ble_protocol as p
from ezhi_component.ble_api import EzhiBleApi
from ezhi_component.ble_link import EzhiBleError

DEVICE_ID = "D00000000000"

DEVICE_CONFIG = {
    "systemMode": "4", "userSetPower": "200", "socMax": "100", "socMin": "10",
    "isOPStrategy": "1", "outputPowerStrategy": [],
    "outputPowerStrategyWeekly": [],
    "EPS": "1", "ECO": "0", "acSwitch": "1", "noBattery": "0", "onOff": "0",
    "grid": "0", "thirdLink": "0", "singlePhase": "0",
    "dischargeProtection": "12", "stayOn": "0", "powerLimit": "1200",
    "config": {}, "winter": "1",
}


class FakeLink:
    def __init__(self, config=None, code=200):
        self.config = dict(DEVICE_CONFIG if config is None else config)
        self.code = code
        self.sent = []

    async def async_send(self, command: dict) -> dict:
        self.sent.append(command)
        data = self.config if command["method"] == "get" else command["params"]
        return {"data": data, "code": self.code,
                "message": "SUCCESS" if self.code == 200 else "FAIL",
                "identifier": command["identifier"]}


def api_with(link: FakeLink | None = None) -> EzhiBleApi:
    return EzhiBleApi(link or FakeLink(), DEVICE_ID)


# async_set_remote is the vendor's cloud-only control channel. The Bluetooth
# transport uses it -- to write btOnOff and open the radio window -- but cannot
# offer it: doing that over Bluetooth would mean switching the radio on through
# the radio. It is called on a cloud object the connect path holds, never on
# coordinator.api, so no entity can reach for it on the wrong transport.
CLOUD_ONLY = {"async_set_remote"}


def test_ble_api_offers_every_method_the_cloud_api_does():
    """Entities call coordinator.api.* -- the two must be interchangeable."""
    from ezhi_component.cloud import EzhiCloudApi

    required = {n for n in dir(EzhiCloudApi)
                if n.startswith("async_") and not n.startswith("async__")} - CLOUD_ONLY
    assert required, "the surface check found nothing to compare against"
    missing = required - set(dir(EzhiBleApi))
    assert not missing, f"BLE API is missing: {sorted(missing)}"


def test_get_config_unwraps_the_reply_envelope():
    async def scenario():
        api = api_with()
        config = await api.async_get_config()
        assert config["systemMode"] == "4"
        assert api._link.sent[-1]["identifier"] == "systemMode"
        assert api._link.sent[-1]["method"] == "get"

    asyncio.run(scenario())


def test_a_rejected_command_is_an_error_not_a_shrug():
    async def scenario():
        api = api_with(FakeLink(code=500))
        with pytest.raises(EzhiBleError):
            await api.async_get_config()

    asyncio.run(scenario())


def test_get_raw_sends_the_identifier_and_returns_the_whole_reply():
    """The diagnostic read must not unwrap or parse -- pcsOriginalData lives in
    the reply and the point is the bytes exactly as sent."""
    async def scenario():
        api = api_with()
        reply = await api.async_get_raw("outputData")
        assert api._link.sent[-1]["identifier"] == "outputData"
        assert api._link.sent[-1]["method"] == "get"
        assert reply["code"] == 200
        assert "data" in reply  # full envelope, not reply["data"]

    asyncio.run(scenario())


def test_get_raw_propagates_a_rejection():
    async def scenario():
        api = api_with(FakeLink(code=500))
        with pytest.raises(EzhiBleError):
            await api.async_get_raw("outputData")

    asyncio.run(scenario())


# The BLE outputData poll: unlike async_get_raw this is a first-class read,
# because the coordinator calls it every cycle -- the reply carries live DC
# and per-string values (batV, batC, pv1V..pv3C, devTemp2/3, ogV, gF) that
# the local HTTP API never returns.

def test_get_output_data_sends_the_identifier_and_unwraps_the_envelope():
    async def scenario():
        api = api_with()
        data = await api.async_get_output_data()
        assert api._link.sent[-1]["identifier"] == "outputData"
        assert api._link.sent[-1]["method"] == "get"
        # Unwrapped like async_get_config, not the raw envelope.
        assert data == api._link.config

    asyncio.run(scenario())


def test_get_output_data_propagates_a_rejection():
    async def scenario():
        api = api_with(FakeLink(code=500))
        with pytest.raises(EzhiBleError):
            await api.async_get_output_data()

    asyncio.run(scenario())


def test_get_output_data_turns_a_missing_data_field_into_an_empty_dict():
    """A code-200 reply without data must read as "nothing", not crash the
    poll -- the sensors go unavailable on an empty dict."""
    class NoDataLink(FakeLink):
        async def async_send(self, command: dict) -> dict:
            self.sent.append(command)
            return {"code": 200, "message": "SUCCESS",
                    "identifier": command["identifier"], "data": None}

    async def scenario():
        api = api_with(NoDataLink())
        assert await api.async_get_output_data() == {}

    asyncio.run(scenario())


def test_set_system_mode_merges_into_the_current_config():
    """Mirrors the cloud: a partial write must not wipe the other fields."""
    async def scenario():
        api = api_with()
        await api.async_set_system_mode(systemMode="2")
        sent = api._link.sent[-1]["params"]
        assert sent["systemMode"] == "2"
        # The four required fields plus the optional ones travel along.
        assert sent["EPS"] == "1", "unrelated fields were dropped"
        assert sent["ECO"] == "0"
        assert sent["userSetPower"] == "200"
        assert sent["dischargeProtection"] == "12"

    asyncio.run(scenario())


def test_set_system_mode_reads_the_config_first():
    """A cached config can be a minute old; a stale EPS written back would undo
    a change made from the vendor app in the meantime."""
    async def scenario():
        api = api_with()
        await api.async_set_system_mode(systemMode="2")
        assert [c["method"] for c in api._link.sent] == ["get", "set"]

    asyncio.run(scenario())


def test_a_typo_in_a_field_name_is_refused_rather_than_sent():
    async def scenario():
        api = api_with()
        with pytest.raises(Exception):
            await api.async_set_system_mode(sytemMode="2")
        assert all(c["method"] != "set" for c in api._link.sent)

    asyncio.run(scenario())


class FakeCloudApi:
    def __init__(self):
        self.on_off_calls = []

    async def async_set_on_off(self, on: bool) -> None:
        self.on_off_calls.append(on)


def test_on_off_is_routed_over_the_cloud_not_the_radio():
    """The BLE onOff frame never appeared in the capture (format reproduced
    from the app bundle, effect unverified), and an "off" might take the
    radio's own ESP32 down with it -- the WLAN and BLE MACs are neighbours.
    Until that is measured, the verified wire wins (spec: not in scope)."""
    async def scenario():
        cloud = FakeCloudApi()
        api = EzhiBleApi(FakeLink(), DEVICE_ID, cloud=cloud)
        await api.async_set_on_off(True)
        await api.async_set_on_off(False)
        assert cloud.on_off_calls == [True, False]
        assert api._link.sent == [], "onOff went over the unverified BLE frame"

    asyncio.run(scenario())


def test_on_off_without_a_cloud_object_is_refused_not_guessed():
    async def scenario():
        api = api_with()
        with pytest.raises(EzhiBleError, match="onOff"):
            await api.async_set_on_off(True)
        assert api._link.sent == []

    asyncio.run(scenario())


def test_backup_power_and_eco_always_travel_as_a_pair():
    """The firmware treats them as mutually exclusive; sending one alone would
    leave a state the device corrects behind our back."""
    async def scenario():
        api = api_with()
        await api.async_set_backup_power(True)
        assert (api._link.sent[-1]["params"]["EPS"],
                api._link.sent[-1]["params"]["ECO"]) == ("1", "0")
        await api.async_set_eco(True)
        assert (api._link.sent[-1]["params"]["EPS"],
                api._link.sent[-1]["params"]["ECO"]) == ("0", "1")
        # Off is off, not "switch to the other one".
        await api.async_set_backup_power(False)
        assert api._link.sent[-1]["params"]["EPS"] == "0"
        assert api._link.sent[-1]["params"]["ECO"] == "0"

    asyncio.run(scenario())


def test_high_power_switches_the_ceiling_between_800_and_1200():
    async def scenario():
        api = api_with()
        await api.async_set_high_power(True)
        assert api._link.sent[-1]["params"]["powerLimit"] == "1200"
        await api.async_set_high_power(False)
        assert api._link.sent[-1]["params"]["powerLimit"] == "800"

    asyncio.run(scenario())


def test_soc_limit_sends_both_bounds_through_the_system_mode_setter():
    """There is no socLimit command over Bluetooth: the app's own setSocLimit()
    posts socMax/socMin/dischargeProtection through systemMode."""
    async def scenario():
        api = api_with()
        await api.async_set_soc_limit(soc_min=8)
        sent = api._link.sent[-1]
        assert sent["identifier"] == "systemMode"
        assert sent["params"]["socMin"] == "8"
        assert sent["params"]["dischargeProtection"] == "12"
        assert sent["params"]["socMax"] == "100", "the untouched bound was dropped"

    asyncio.run(scenario())


def test_soc_limit_rides_the_full_field_set_not_the_apps_subset():
    """Measured 2026-08-07 00:32 on the real device: the app-JS subset
    {socMax, socMin, dischargeProtection} is never answered (2x reproduced,
    the write does not land), while the full merged field set -- the shape
    every verified write uses -- answers in ~8-10 s. The reconstructed app
    path never appeared in the capture; the device's behaviour wins."""
    async def scenario():
        api = api_with()
        await api.async_set_soc_limit(soc_min=8)
        sent = api._link.sent[-1]["params"]
        assert sent["systemMode"] == "4", "the full merge must carry systemMode"
        assert sent["userSetPower"] == "200", "the full merge was dropped"
        assert sent["EPS"] == "1"

    asyncio.run(scenario())


def test_soc_limit_refuses_a_floor_it_would_fight_with():
    """The discharge protection guard must not be bypassable by picking the
    Bluetooth transport."""
    async def scenario():
        api = api_with()
        with pytest.raises(Exception):
            await api.async_set_soc_limit(soc_min=11)   # floor is 12%
        assert all(c["method"] != "set" for c in api._link.sent)

    asyncio.run(scenario())


def test_the_commands_that_go_out_are_the_ones_the_capture_pinned():
    """End of the chain: what the API produces has to survive the frame builder."""
    async def scenario():
        api = api_with()
        await api.async_set_system_mode(systemMode="2")
        frames = p.build_frames(api._link.sent[-1])
        assert frames[0][:4].hex().startswith("4d10003c")
        assert p.decrypt_hex(
            b"".join(f[6:] if f[1] & p.FC_FRAG else f[4:] for f in frames)
        )["params"]["systemMode"] == "2"

    asyncio.run(scenario())
