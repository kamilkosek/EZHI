"""getOutputData over local HTTP: a field the reply lacks is None, not "0".

aiohttp is not a test dependency; api.py only touches it inside methods these
tests never reach, so an empty stand-in module is enough to import it.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import types

sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))

from ezhi_component.api import APsystemsEZHI  # noqa: E402

# jwende's reply from issue #14, counters made sane again.
FULL = {
    "data": {
        "batSoc": "91.0", "batSoh": "100", "batTemp": "26.1", "devTemp": "34.7",
        "pvP": "0", "pvTE": "0.0000", "batP": "-6", "batCTE": "1500.1234",
        "batDTE": "1465.3311", "ogP": "0", "ogOTE": "1342.8452",
        "ogITE": "1498.0000", "ofgP": "-6", "ofgOTE": "35.0829",
        "ofgITE": "51.8116",
    },
    "batS": "3", "deviceId": "xxx", "message": "SUCCESS",
}


def _read(*replies):
    api = APsystemsEZHI("192.0.2.1", session=object())
    queue = list(replies)

    async def _request(endpoint, params=None):
        return queue.pop(0)

    api._request = _request
    return api, [asyncio.run(api.get_output_data()) for _ in replies]


def test_a_full_reply_passes_through():
    _, (out,) = _read(FULL)
    assert out.batSoc == "91.0" and out.batCTE == "1500.1234" and out.batS == "3"


def test_a_missing_field_is_none_and_logged_once_per_change(caplog):
    lacking = {"data": {k: v for k, v in FULL["data"].items()
                        if k not in ("batSoc", "batCTE")}, "batS": "3"}
    with caplog.at_level(logging.WARNING):
        _, (first, second, third) = _read(lacking, lacking, FULL)
    assert first.batSoc is None and first.batCTE is None
    assert first.batTemp == "26.1"
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "batSoc, batCTE" in warnings[0].getMessage()
    assert third.batSoc == "91.0"


def test_no_data_at_all_is_every_field_none():
    _, (out,) = _read({"data": None, "message": "FAILED"})
    assert out.batSoc is None and out.pvTE is None and out.batS is None


def test_every_counter_at_zero_is_logged_with_the_raw_reply(caplog):
    zeroed = {"data": {**FULL["data"], **{k: "0" for k in (
        "pvTE", "batCTE", "batDTE", "ogOTE", "ogITE", "ofgOTE", "ofgITE")}},
        "batS": "3"}
    with caplog.at_level(logging.DEBUG):
        _read(FULL, zeroed)
    debug = [r.getMessage() for r in caplog.records
             if r.levelno == logging.DEBUG and r.name.endswith(".api")]
    assert len(debug) == 1 and "'batCTE': '0'" in debug[0]
