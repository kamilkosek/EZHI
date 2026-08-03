"""The alarm texts and the sensors that show them must not drift apart.

alarm_texts.py is generated from the vendor app's translation bundles, and
binary_sensor.py names the code each entity reads. Nothing enforces that those
two lists match, so a sensor added with a typo'd code would ship with an empty
tooltip and look fine until someone had a real fault.

No Home Assistant here: the texts are plain data, and the sensor table is read
out of the source rather than imported.
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_COMPONENT = _ROOT / "custom_components" / "apsystems_ezhi_local"

_spec = importlib.util.spec_from_file_location(
    "ezhi_alarm_texts", _COMPONENT / "alarm_texts.py")
alarm_texts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(alarm_texts)

# The 20 fields getAlarm returns on firmware 1.9.0.16.
LIVE_FIELDS = {
    "ACA", "BCC", "BCI", "BatCE", "BatE", "BatHI", "BatHTP", "BatHV", "BatLTP",
    "BatLV", "DTP", "EE", "IRDE", "OfGS", "OfOI", "PVWE", "PvHV", "PvOC",
    "SBS", "VRP",
}


def _sensor_codes() -> list[str]:
    source = (_COMPONENT / "binary_sensor.py").read_text()
    return re.findall(r'alarm_code="(\w+)"', source)


def test_every_sensor_has_texts():
    missing = [c for c in _sensor_codes() if not alarm_texts.ALARM_TEXTS.get(c)]
    assert not missing, f"sensors without vendor text: {missing}"


def test_sensors_and_texts_cover_exactly_the_live_fields():
    assert set(_sensor_codes()) == LIVE_FIELDS
    assert set(alarm_texts.ALARM_TEXTS) == LIVE_FIELDS


def test_no_duplicate_sensor_codes():
    codes = _sensor_codes()
    assert len(codes) == len(set(codes))


def test_german_is_actually_german():
    """Guards the extractor's real failure mode.

    The app packs all twelve languages into one bundle, so a naive extraction
    silently returns Italian, and cutting the bundle on a fixed key shifts
    blocks by one language. Both produced output that looked complete. These
    two strings are the vendor's German for codes that sit at opposite ends of
    the block, so a shift of even one language breaks the test.
    """
    assert alarm_texts.ALARM_TEXTS["BCC"]["de"]["name"] == "SOC-Kalibrierung"
    assert "Spannungsrücksetz" in alarm_texts.ALARM_TEXTS["VRP"]["de"]["name"]


def test_language_falls_back_to_english_not_to_nothing():
    assert alarm_texts.alarm_text("ACA", "th")["name"]        # no Thai shipped
    assert alarm_texts.alarm_text("ACA", None)["name"]
    assert alarm_texts.alarm_text("ACA", "de-DE")["reason"].startswith("1. Das Netz")
    assert alarm_texts.alarm_text("nonsense", "de") == {}


def test_docs_and_module_agree():
    """docs/alarms.json is the published copy of the same extraction."""
    published = json.loads((_ROOT / "docs" / "alarms.json").read_text())["alarms"]
    for code, texts in alarm_texts.ALARM_TEXTS.items():
        for lang in ("en", "de"):
            for kind, value in texts[lang].items():
                assert published[code][lang][kind] == value, f"{code}/{lang}/{kind}"
