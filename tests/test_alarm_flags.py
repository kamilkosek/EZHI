"""Unit tests for the alarm fields getAlarm reports but the integration
did not map.

No network and no Home Assistant: the two modules are loaded by path, and
binary_sensor.py's helper is pulled out of the source so importing the whole
Home Assistant entity stack is not needed.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

_COMPONENT = (
    Path(__file__).resolve().parents[1] / "custom_components" / "apsystems_ezhi_local"
)

# api.py imports aiohttp at module level, but nothing here makes an HTTP call --
# only the alarm dataclass is under test. A stub keeps this suite runnable with
# a bare `python3 -m pytest`, no virtualenv and no third-party install. The
# names below are the ones api.py touches in its except clauses; they are only
# evaluated if a request path runs, which these tests never take.
if "aiohttp" not in sys.modules:
    _aiohttp = types.ModuleType("aiohttp")
    _aiohttp.ClientError = type("ClientError", (Exception,), {})
    _aiohttp.ClientSession = object
    sys.modules["aiohttp"] = _aiohttp

_spec = importlib.util.spec_from_file_location("ezhi_api", _COMPONENT / "api.py")
api = importlib.util.module_from_spec(_spec)
# @dataclass looks its own module up in sys.modules while building the class.
sys.modules["ezhi_api"] = api
_spec.loader.exec_module(api)

_source = (_COMPONENT / "binary_sensor.py").read_text()
_namespace: dict = {}
exec(  # noqa: S102 - the alternative is importing all of homeassistant
    _source[_source.index("def _alarm_flag") : _source.index("ALARM_SENSORS")],
    _namespace,
)
alarm_flag = _namespace["_alarm_flag"]


# The full payload of a live EZHI 1.9.0.16, captured 2026-08-01.
LIVE_PAYLOAD = {
    "BatLTP": "0", "BatHTP": "0", "BatCE": "0", "BatHV": "0", "BatLV": "0",
    "BatHI": "0", "BatE": "0", "DTP": "0", "EE": "0", "SBS": "0", "ACA": "0",
    "OfOI": "0", "PvHV": "0", "PvOC": "0", "IRDE": "0", "PVWE": "0",
    "OfGS": "0", "BCC": "0", "BCI": "0", "VRP": "0",
}


def _parse(payload: dict) -> api.ReturnAlarmData:
    """What get_alarm does to a response body, without the HTTP round trip."""
    return api.ReturnAlarmData(
        **{
            name: payload.get(name, "" if name in ("BCC", "BCI", "VRP") else "0")
            for name in api.ReturnAlarmData.__dataclass_fields__
        }
    )


def test_the_device_reports_twenty_alarm_fields():
    """17 were mapped; getAlarm sends 20."""
    assert len(api.ReturnAlarmData.__dataclass_fields__) == 20
    for field in ("BCC", "BCI", "VRP"):
        assert field in api.ReturnAlarmData.__dataclass_fields__


def test_live_payload_parses_with_no_alarm_active():
    alarms = _parse(LIVE_PAYLOAD)
    assert (alarms.BCC, alarms.BCI, alarms.VRP) == ("0", "0", "0")
    assert not any(
        str(getattr(alarms, f)) == "1" for f in api.ReturnAlarmData.__dataclass_fields__
    )


def test_a_raised_alarm_reads_as_on():
    alarms = _parse({**LIVE_PAYLOAD, "BCI": "1"})
    assert alarm_flag(alarms.BCI) is True


def test_firmware_without_the_field_reads_as_unknown_not_as_no_fault():
    """The point of the "" default.

    Older firmware simply does not send these. Reporting "off" would assert
    the absence of a fault the device never denied -- and for BCI, a battery
    access conflict, that assertion has consequences.
    """
    older_firmware = {k: v for k, v in LIVE_PAYLOAD.items() if k not in ("BCC", "BCI", "VRP")}
    alarms = _parse(older_firmware)

    assert (alarms.BCC, alarms.BCI, alarms.VRP) == ("", "", "")
    assert alarm_flag(alarms.BCI) is None
    assert alarm_flag(alarms.BCC) is None
    assert alarm_flag(alarms.VRP) is None


def test_alarm_flag_edge_cases():
    assert alarm_flag("1") is True
    assert alarm_flag("0") is False
    assert alarm_flag(1) is True
    assert alarm_flag(0) is False
    assert alarm_flag("") is None
    assert alarm_flag(None) is None
    # Anything the device could send that is neither "1" nor absent is not an
    # alarm -- guessing "on" here would be a false problem report.
    assert alarm_flag("unexpected") is False
