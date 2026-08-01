"""Unit tests for the loginEncrypt path.

No network and no Home Assistant. The crypto is pinned against fixed key/IV
vectors because every way of getting it wrong -- PKCS7 instead of the app's
zero fill, the raw key bytes instead of their hex text, a rotated IV -- fails
identically at runtime, as "wrong username or password".
"""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("cryptography")  # ships with Home Assistant, not with bare python

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes  # noqa: E402

_MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "apsystems_ezhi_local"
    / "cloud.py"
)
_spec = importlib.util.spec_from_file_location("ezhi_cloud_login", _MODULE_PATH)
cloud = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cloud)

KEY = "0123456789abcdef0123456789abcdef"   # 32 chars, as the app's hex text
IV = "0000000000000042"                    # 16 chars, as the app's decimal text


class FakeResponse:
    def __init__(self, status: int, body: dict):
        self.status = status
        self._body = body

    async def json(self, content_type=None):
        return self._body


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls: list[dict] = []

    async def request(self, method, url, params=None, data=None, headers=None):
        await asyncio.sleep(0)
        self.calls.append({"method": method, "url": url, "data": data,
                           "headers": headers})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _decrypt(hex_text: str, key: str = KEY, iv: str = IV) -> bytes:
    decryptor = Cipher(algorithms.AES(key.encode()), modes.CBC(iv.encode())).decryptor()
    raw = bytes.fromhex(hex_text)
    return decryptor.update(raw) + decryptor.finalize()


# --- the crypto -------------------------------------------------------------

def test_aes_matches_the_app_for_fixed_vectors():
    assert cloud._aes_hex("user@example.invalid", KEY, IV) == (
        "2d2b2ac01699ee69f798cfbe603054dd54ad7af7f5fb6b9c2eaff9a1618f9b7d"
    )
    assert cloud._aes_hex("hunter2", KEY, IV) == "d6473094b52dc1e8b822ce7615e3d399"


def test_padding_is_zero_fill_and_adds_a_whole_block_on_an_exact_fit():
    """The app's rule, not PKCS7 -- and not "no padding when it already fits"."""
    exact = "sixteen-chars-16"
    assert len(exact) == 16
    cipher = cloud._aes_hex(exact, KEY, IV)
    assert len(bytes.fromhex(cipher)) == 32          # one block of payload, one of zeros
    assert _decrypt(cipher) == exact.encode() + b"\0" * 16

    short = "hunter2"
    assert _decrypt(cloud._aes_hex(short, KEY, IV)) == short.encode() + b"\0" * 9


def test_rsa_wraps_the_key_under_the_apps_public_key():
    import base64
    blob = base64.b64decode(cloud._rsa_b64(KEY))
    assert len(blob) == 256                          # RSA-2048 block


def test_login_params_carry_the_app_constants_and_no_plaintext():
    params = cloud.build_login_params("user@example.invalid", "hunter2",
                                      key=KEY, iv=IV)
    assert params["app_id"] == cloud.LOGIN_APP_ID
    assert params["app_secret"] == cloud.LOGIN_APP_SECRET
    assert set(params) == {"app_id", "app_secret", "key", "version",
                           "username", "password"}
    # The whole point: neither credential travels readable.
    blob = "".join(params.values())
    assert "hunter2" not in blob and "user@example.invalid" not in blob
    assert _decrypt(params["password"]).rstrip(b"\0") == b"hunter2"


def test_key_and_iv_are_drawn_fresh_per_login():
    a = cloud.build_login_params("u", "p")
    b = cloud.build_login_params("u", "p")
    # Same credentials, different ciphertext -- a fixed key would make the
    # captured request replayable.
    assert a["username"] != b["username"]
    assert a["key"] != b["key"]


# --- the request ------------------------------------------------------------

def test_login_returns_the_token_pair():
    session = FakeSession(FakeResponse(200, {"code": 0, "data": {
        "user_id": "u1", "access_token": "JWT", "refresh_token": "UUID"}}))
    # Long enough not to collide with random base64 -- a two-letter needle
    # matches by chance and makes this assertion flaky rather than meaningful.
    secret = "correct-horse-battery-staple"
    tokens = asyncio.run(cloud.async_login(session, "user@example.invalid", secret))

    assert tokens == {"access_token": "JWT", "refresh_token": "UUID"}
    call = session.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == cloud.LOGIN_URL
    assert call["data"]["language"] == "en"
    assert "Authorization" not in call["headers"]     # nothing to authorise with yet
    assert secret not in "".join(map(str, call["data"].values()))


def test_bad_credentials_raise_auth_not_a_generic_error():
    session = FakeSession(FakeResponse(200, {"code": 2006, "message": "nope"}))
    with pytest.raises(cloud.EzhiCloudAuthError) as err:
        asyncio.run(cloud.async_login(session, "u", "wrong"))
    assert "2006" in str(err.value)


def test_a_sick_cloud_is_not_reported_as_a_bad_password():
    """A 502 must not send the user off to reset a password that was fine."""
    session = FakeSession(FakeResponse(502, {}))
    with pytest.raises(cloud.EzhiCloudError) as err:
        asyncio.run(cloud.async_login(session, "u", "p"))
    assert not isinstance(err.value, cloud.EzhiCloudAuthError)
    assert "502" in str(err.value)


def test_a_success_without_tokens_is_still_a_failure():
    session = FakeSession(FakeResponse(200, {"code": 0, "data": {"user_id": "u1"}}))
    with pytest.raises(cloud.EzhiCloudAuthError):
        asyncio.run(cloud.async_login(session, "u", "p"))


def test_transport_failure_is_wrapped_with_the_url():
    session = FakeSession(OSError("connection reset"))
    with pytest.raises(cloud.EzhiCloudError) as err:
        asyncio.run(cloud.async_login(session, "u", "p"))
    assert "loginEncrypt" in str(err.value)
