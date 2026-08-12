"""Topics and envelope for the EZHI's own MQTT channel.

The inverter speaks MQTT to the vendor cloud, and it carries the same JSON
envelope the Bluetooth channel does -- identifier/method/params out, a `code`
and a `data` block back, correlated by `id`. Pointing the device at a local
broker therefore turns the vendor's own control channel into a local one, with
no reverse engineering left to do: this module is that wire format.

Verified against a capture of the real device on a local broker (2026-08-10,
`docs/ezhi-mqtt-topics-2026-08-10.md` in the config repo -- kept out of this
repository, it contains a serial and a password). What the capture settled:

* the device subscribes to seven topics, of which `/properties/<p>/<s>/get`
  and `.../set` are the ones a controller publishes on;
* it answers on `.../get_reply` and `.../set_reply`, `code` 200 for success;
* telemetry is a *push* on `/event/<p>/<s>/post`, not something to poll --
  `systemMode` on the other hand is never pushed and has to be asked for;
* **companyKey is required**. A `get` without it reaches the device (the
  broker logs the delivery) and is simply never answered. That silence cost
  an evening; it is the one field that looks like decoration and is not.

Pure: no I/O, no Home Assistant, no broker client. Everything here can be
checked without a device.
"""
from __future__ import annotations

import json
import uuid
from itertools import count
from typing import Any

# One truth for the vendor's four envelope constants, which both transports
# need and neither owns. ble_protocol.py had them first.
from .ble_protocol import COMPANY, COMPANY_KEY, PRODUCT_KEY, VERSION

# The device answers a command it accepted with this. As on the other
# transports, it means "parsed and accepted", never "and it took effect".
SUCCESS_CODE = 200

# Every id in the capture is numeric -- the vendor app sends 9-10 digit
# numbers, and the ids we put on the wire ourselves were numeric too and were
# answered. A non-numeric id has never been tried against real firmware, so
# the ids built below stay digits-only rather than finding out during a write.
_ID_PREFIX = str(uuid.uuid4().int % 1_000_000)
_ID_COUNTER = count()


def topic_get(device_id: str) -> str:
    """Where a controller asks for a property."""
    return f"/properties/{PRODUCT_KEY}/{device_id}/get"


def topic_set(device_id: str) -> str:
    """Where a controller writes a property."""
    return f"/properties/{PRODUCT_KEY}/{device_id}/set"


def topic_get_reply(device_id: str) -> str:
    """Where the device answers a get."""
    return f"/properties/{PRODUCT_KEY}/{device_id}/get_reply"


def topic_set_reply(device_id: str) -> str:
    """Where the device answers a set."""
    return f"/properties/{PRODUCT_KEY}/{device_id}/set_reply"


def topic_event(device_id: str) -> str:
    """Where the device pushes telemetry (outputData, si, light, alarm, ...)."""
    return f"/event/{PRODUCT_KEY}/{device_id}/post"


def reply_topics(device_id: str) -> tuple[str, str]:
    """The two topics a controller has to be listening on before it asks."""
    return topic_get_reply(device_id), topic_set_reply(device_id)


def new_corr_id() -> str:
    """A correlation id: numeric, unique in this process and across restarts.

    The random per-process prefix is not decoration either. A reply that
    outlives its request -- a retained message, a device answering after a
    restart -- must not resolve a fresh request that happens to have reached
    the same counter value again. The counter alone, restarting at 0 with the
    process, would allow exactly that.
    """
    return f"{_ID_PREFIX}{next(_ID_COUNTER):04d}"


def build_get(device_id: str, identifier: str, corr_id: str) -> str:
    """JSON to publish on topic_get() -- deliberately without `params`.

    The vendor app sends no params on a read and that is what was verified;
    an empty `params: {}` was on the wire once, in the same message that was
    missing companyKey, so it has never been cleanly tested on its own.
    """
    return _envelope(device_id, identifier, "get", corr_id)


def build_set(
    device_id: str, identifier: str, params: dict, corr_id: str
) -> str:
    """JSON to publish on topic_set()."""
    return _envelope(device_id, identifier, "set", corr_id, params)


def _envelope(
    device_id: str,
    identifier: str,
    method: str,
    corr_id: str,
    params: dict | None = None,
) -> str:
    body = {
        "identifier": identifier,
        "method": method,
        "company": COMPANY,
        "companyKey": COMPANY_KEY,
        "id": corr_id,
        "type": "property",
        "productKey": PRODUCT_KEY,
        "version": VERSION,
        "deviceId": device_id,
    }
    if params is not None:
        body["params"] = params
    return json.dumps(body, separators=(",", ":"), ensure_ascii=False)


def parse_reply(payload: str | bytes) -> tuple[str, int | None, dict]:
    """(correlation id, code, data) from a *_reply payload.

    Raises ValueError on anything that is not a JSON object with an `id`.
    The subscriber logs and drops those rather than failing: a broker will
    hand over whatever a third party published to the topic, and one stray
    message must not take the transport down.

    `code` is returned as-is rather than checked here -- the caller knows
    which command it belongs to and can say so in the error.
    """
    try:
        body = json.loads(payload)
    except (TypeError, ValueError) as err:
        raise ValueError(f"reply is not JSON: {err}") from err
    if not isinstance(body, dict):
        raise ValueError(f"reply is not a JSON object: {type(body).__name__}")
    corr_id = body.get("id")
    if corr_id is None:
        raise ValueError("reply has no id, cannot be correlated")
    data = body.get("data")
    return str(corr_id), _as_code(body.get("code")), data if isinstance(data, dict) else {}


def _as_code(value: Any) -> int | None:
    """The code as an int. None when it is missing or unreadable, never a guess."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
