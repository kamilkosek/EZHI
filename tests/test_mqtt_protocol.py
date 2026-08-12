"""The MQTT wire format, checked against what the device actually answered.

Every expectation here comes from a capture of the real inverter on a local
broker (2026-08-10). The serial is scrubbed; nothing else is.
"""
from __future__ import annotations

import json

import pytest
from ezhi_component import mqtt_protocol as p

DEVICE_ID = "D00000000000"


def test_topics_match_the_ones_the_device_subscribes_to():
    """Wrong topic, no answer -- and the device tells nobody."""
    assert p.topic_get(DEVICE_ID) == f"/properties/EZHI/{DEVICE_ID}/get"
    assert p.topic_set(DEVICE_ID) == f"/properties/EZHI/{DEVICE_ID}/set"
    assert p.topic_get_reply(DEVICE_ID) == f"/properties/EZHI/{DEVICE_ID}/get_reply"
    assert p.topic_set_reply(DEVICE_ID) == f"/properties/EZHI/{DEVICE_ID}/set_reply"
    assert p.topic_event(DEVICE_ID) == f"/event/EZHI/{DEVICE_ID}/post"


def test_reply_topics_are_the_two_a_controller_must_listen_on():
    assert p.reply_topics(DEVICE_ID) == (
        p.topic_get_reply(DEVICE_ID), p.topic_set_reply(DEVICE_ID))


def test_get_carries_company_key():
    """The field that decides whether the device answers at all.

    A get without companyKey reaches the device and is never answered -- the
    broker logs the delivery, the device stays silent. Measured 2026-08-10.
    """
    body = json.loads(p.build_get(DEVICE_ID, "systemMode", "1"))
    assert body["companyKey"] == "AmS4SV9oy3gk"


def test_get_has_no_params_field():
    """The vendor app sends none on a read, so neither do we."""
    body = json.loads(p.build_get(DEVICE_ID, "systemMode", "1"))
    assert "params" not in body


def test_get_envelope_is_complete():
    body = json.loads(p.build_get(DEVICE_ID, "deviceInfo", "42"))
    assert body["identifier"] == "deviceInfo"
    assert body["method"] == "get"
    assert body["id"] == "42"
    assert body["deviceId"] == DEVICE_ID
    assert body["type"] == "property"
    assert body["productKey"] == "EZHI"
    assert body["company"] == "apsystems"
    assert body["version"] == "1.0"


def test_set_carries_params_and_company_key():
    body = json.loads(
        p.build_set(DEVICE_ID, "systemMode", {"socMin": "15"}, "7"))
    assert body["method"] == "set"
    assert body["params"] == {"socMin": "15"}
    assert body["companyKey"] == "AmS4SV9oy3gk"
    assert body["id"] == "7"


def test_payloads_are_compact_json():
    """Whitespace is not wrong, but the app sends none and neither do we."""
    assert " " not in p.build_get(DEVICE_ID, "systemMode", "1")


def test_correlation_ids_are_numeric():
    """A non-numeric id has never been on the wire; ids stay digits-only."""
    for _ in range(20):
        assert p.new_corr_id().isdigit()


def test_correlation_ids_do_not_repeat():
    assert len({p.new_corr_id() for _ in range(500)}) == 500


def test_correlation_ids_are_process_unique():
    """The prefix is what keeps a reply that outlived a restart from
    resolving a fresh request with the same counter value."""
    assert p.new_corr_id().startswith(p._ID_PREFIX)


def test_parse_reply_returns_id_code_and_data():
    corr_id, code, data = p.parse_reply(json.dumps({
        "data": {"systemMode": "4", "dischargeProtection": "13"},
        "code": 200, "message": "SUCCESS", "id": "9990011",
        "deviceId": DEVICE_ID, "identifier": "systemMode",
    }))
    assert corr_id == "9990011"
    assert code == 200
    assert data["dischargeProtection"] == "13"


def test_parse_reply_accepts_bytes():
    """What a broker client hands over is not always str."""
    corr_id, code, _ = p.parse_reply(b'{"id":"5","code":200,"data":{}}')
    assert (corr_id, code) == ("5", 200)


def test_parse_reply_reports_a_failure_code_rather_than_raising():
    """The caller knows which command it was and writes the better message."""
    _, code, _ = p.parse_reply('{"id":"5","code":400,"data":{}}')
    assert code == 400


def test_parse_reply_survives_a_reply_without_data():
    _, _, data = p.parse_reply('{"id":"5","code":200}')
    assert data == {}


def test_parse_reply_rejects_junk():
    """Anyone can publish to a topic. Junk must be droppable, not fatal."""
    for junk in ("", "not json", "[1,2,3]", '"a string"', b"\x00\x01"):
        with pytest.raises(ValueError):
            p.parse_reply(junk)


def test_parse_reply_rejects_a_reply_that_cannot_be_correlated():
    with pytest.raises(ValueError):
        p.parse_reply('{"code":200,"data":{}}')


def test_parse_reply_reports_an_unreadable_code_as_none():
    """None, never a guessed 200 -- this decides whether a write counted."""
    _, code, _ = p.parse_reply('{"id":"5","code":"weird","data":{}}')
    assert code is None
