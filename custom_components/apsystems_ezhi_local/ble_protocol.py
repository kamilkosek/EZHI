"""Frame builder for the EZHI's BluFi/AES control channel.

Verified against a real capture (``ezhi_directconnect_20260805.pklg``, 105
request/response pairs): identical inputs produce identical bytes for all 105
messages recorded on 2026-08-05, and all 105 notifications decrypt to valid
JSON. Do not "clean up" the oddities -- the zero padding with a full extra
block on an exact multiple, the fixed IV, the hex text in the send direction
only, and the field order that differs per command are what the device expects.

Pure: no I/O, no Home Assistant, no radio. Everything here can be checked
against the capture without touching the inverter.

Protocol reference: docs/ezhi-ble-protokoll.md (§ 4 message format,
§ 7 reference implementation).
"""
from __future__ import annotations

import json

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

KEY = b"E7MiPPrs9v6i3DY3"          # AES-128, hardcoded in the vendor app
IV = b"8914934610490056"           # fixed -> ciphertext is deterministic
COMPANY, COMPANY_KEY = "apsystems", "AmS4SV9oy3gk"
VERSION, PRODUCT_KEY = "1.0", "EZHI"

BLUFI_CUSTOM_DATA = 0x4D           # type 0b01 (data) | subtype 0x13 << 2
FC_FRAG = 0x10
# Empirical, not derived from the MTU: every write in the capture is 64 bytes,
# which leaves 58 bytes of fragment payload after the 4-byte header and the
# 2-byte length field.
PKG_LIMIT = 64
SERVICE_UUID = "0000fffe-0000-1000-8000-00805f9b34fb"
WRITE_UUID = "0000ff0a-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "0000ff0b-0000-1000-8000-00805f9b34fb"


def zero_pad(raw: bytes, bs: int = 16) -> bytes:
    """CryptoJS ZeroPadding: always pads, a whole extra block on an exact multiple.

    The two code paths in the vendor app disagree here -- the native one skips
    the extra block -- and no captured payload is an exact multiple, so the
    wire cannot settle it. CryptoJS is the path that produced the captured
    bytes, so CryptoJS is the rule. The device trims trailing zeros either way.
    """
    return raw + b"\0" * (bs - len(raw) % bs)


def _cipher() -> Cipher:
    return Cipher(algorithms.AES(KEY), modes.CBC(IV))


def build_payload(obj: dict) -> bytes:
    """App layer: append the four constants, compact JSON, AES-CBC, lowercase hex."""
    body = {**obj, "company": COMPANY, "companyKey": COMPANY_KEY,
            "version": VERSION, "productKey": PRODUCT_KEY}
    raw = zero_pad(json.dumps(body, separators=(",", ":"),
                              ensure_ascii=False).encode())
    enc = _cipher().encryptor()
    return (enc.update(raw) + enc.finalize()).hex().encode()


def decrypt_hex(payload: bytes) -> dict:
    """Device -> phone carries raw ciphertext; phone -> device carries hex."""
    blob = bytes.fromhex(payload.decode()) if _looks_hex(payload) else payload
    dec = _cipher().decryptor()
    return json.loads((dec.update(blob) + dec.finalize()).rstrip(b"\0"))


def _looks_hex(payload: bytes) -> bool:
    return len(payload) % 2 == 0 and all(
        c in b"0123456789abcdefABCDEF" for c in payload)


def build_frames(obj: dict, pkg_limit: int = PKG_LIMIT, seq0: int = 0) -> list[bytes]:
    """Fragment one command into BluFi Custom-Data frames.

    `seq0` is not cosmetic: the sequence counter runs across a whole BluFi
    session and only resets on reconnect, so the caller has to carry it
    forward between commands.
    """
    payload = build_payload(obj)
    frag_max = pkg_limit - 4 - 2       # 4 byte header + 2 byte length field
    # The final frame carries no length field, so it holds two bytes more than
    # a fragment does. Deciding against that larger figure is what keeps a
    # 1-2 byte scrap from ever being left over: fragmenting only starts when
    # more than one final frame's worth remains, so every remainder is at
    # least 3 bytes. The previous code fragmented first and then appended a
    # 1-2 byte tail to the fragment, which pushed that frame past pkg_limit --
    # 66 bytes on a 64 byte link, unsendable. Never fired for the commands in
    # the capture (payloads 416 and 736 bytes); one more field in a set would
    # have been enough.
    last_max = pkg_limit - 4
    out, seq, off = [], seq0, 0
    while True:
        remaining = len(payload) - off
        if remaining > last_max:
            chunk = payload[off:off + frag_max]
            off += frag_max
            # The length field names the bytes still to come *including* this
            # fragment, not the ones after it.
            body, fc = remaining.to_bytes(2, "little") + chunk, FC_FRAG
        else:
            body, fc = payload[off:], 0x00
            off = len(payload)
        out.append(bytes([BLUFI_CUSTOM_DATA, fc, seq & 0xFF, len(body)]) + body)
        seq += 1
        if off >= len(payload):
            return out


# --- commands ---------------------------------------------------------------
#
# Field order is part of the message. The app builds each object literally and
# the ciphertext is deterministic, so a reordered dict is a different frame.
# One observed command puts `identifier` ahead of `method`; the other eight put
# it after. Reproduced rather than tidied, because bit-identical frames are the
# only evidence available short of writing to the inverter.
_IDENTIFIER_BEFORE_METHOD = frozenset({"wifiStatus"})


def cmd_get(device_id: str, identifier: str, msg_id: str = "1") -> dict:
    head = {"id": msg_id, "deviceId": device_id, "type": "property"}
    if identifier in _IDENTIFIER_BEFORE_METHOD:
        return {**head, "identifier": identifier, "method": "get", "params": {}}
    return {**head, "method": "get", "identifier": identifier, "params": {}}


def cmd_set_system_mode(device_id: str, params: dict, msg_id: str = "32") -> dict:
    return {"id": msg_id, "deviceId": device_id, "type": "property",
            "method": "set", "identifier": "systemMode", "params": params}


def cmd_set_on_off(device_id: str, on: bool, msg_id: str = "35") -> dict:
    """Turn the inverter on or off. Its own identifier, not a systemMode field.

    Inverted like the cloud endpoint: status "0" is ON. Read out of the app's
    bundle (protocol doc § 5); unlike the scene change it never appeared in the
    capture, so the format is reproduced but the effect is unverified.
    """
    return {"id": msg_id, "deviceId": device_id, "type": "property",
            "method": "set", "identifier": "onOff",
            "params": {"status": "0" if on else "1"}}
