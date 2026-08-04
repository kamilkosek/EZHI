#!/usr/bin/env python3
"""Stand-alone EMA cloud login + settings read, for people not running Home Assistant.

The integration's cloud.py is a module, not a script: it takes the credentials
as function arguments and gets them from the HA config flow. There is no line
in it where a username is "stored", which is a fair thing to be confused about
when you open the file looking for one. This is the same protocol as a CLI, so
Node-RED (or cron, or anything else) can shell out to it and read JSON back.

    export EZHI_USER='you@example.com' EZHI_PASS='...'
    ./ezhi_cloud_login.py login                  -> {"access_token":..., "refresh_token":...}
    ./ezhi_cloud_login.py settings <refresh_token> <device_id>

The refresh_token does not rotate, so login runs once and settings runs
forever after. deviceId is the one your local getDeviceInfo already reports.

Needs: pip install cryptography          Self-check: ./ezhi_cloud_login.py selftest
"""
import base64
import json
import os
import secrets
import sys
import urllib.parse
import urllib.request

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

BASE = "https://app.api.apsystemsema.com:9223"
LOGIN_URL = f"{BASE}/api/token/generateToken/user/loginEncrypt"
TOKEN_URL = f"{BASE}/api/token/refreshToken"
API = f"{BASE}/aps-api-web/api/v2"        # the /api/v2 segment is mandatory

# Constants of the app, identical for every user, extracted from the APK.
# These -- not the key/IV below -- are what a new app version could change.
APP_ID = "4029817264d4821d0164d4821dd80015"
APP_SECRET = "EZAd2023"
PUBLIC_KEY_DER_B64 = (
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAgdwBhVodMQ84lYZhDSGOUDQAks+NMa7WQ83mR1OyHiIW"
    "tZ1wWAh4H7fclkdNS3lWCmDH9ldF7Kf6JlEvZTc0Textv+YMLXO2gdDIoBvg7vlhY4HxOjXUIFQ+s7cWRrmEIgVV"
    "nTBLZU1GMC8zld7WH9v9EYCAqK7rvGJP0STZ/g6BP8RGJKhdpY6b+ndMXRUBYwkqy8m1SDJHm1FeHSLQWTaWbP5p"
    "z1yrGkkwvx+pib6wli+WE70/uPHp0zXZK5iUwmRQfOkTjDOGJyEE1dqkfHDTqne5ED81M4fCIEFYhyvnr1rifVJK"
    "HCDRGYQpJ0CiffjjH1ZOGSIN4JPG1EEIjQIDAQAB"
)


def aes_hex(plain: str, key: str, iv: str) -> str:
    """AES-CBC, zero-filled. Faithful to the app, warts included.

    The key is the *hex text* of 16 random bytes, so 32 characters go into
    AES and it runs as AES-256. Padding is zero-fill, and an exact block
    multiple still gets a whole extra block. PKCS7 here is rejected.
    """
    raw = plain.encode()
    raw += b"\0" * (16 - len(raw) % 16)
    enc = Cipher(algorithms.AES(key.encode()), modes.CBC(iv.encode())).encryptor()
    return (enc.update(raw) + enc.finalize()).hex()


def rsa_b64(text: str) -> str:
    pub = serialization.load_der_public_key(base64.b64decode(PUBLIC_KEY_DER_B64))
    return base64.b64encode(pub.encrypt(text.encode(), padding.PKCS1v15())).decode()


def post_form(url: str, fields: dict) -> dict:
    req = urllib.request.Request(
        url, data=urllib.parse.urlencode(fields).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def login(user: str, password: str, language: str = "de") -> dict:
    key = os.urandom(16).hex()                      # 32 chars -> AES-256
    iv = f"{secrets.randbelow(10 ** 16):016d}"      # 16 digits, fresh per login
    body = post_form(LOGIN_URL, {
        "app_id": APP_ID,
        "app_secret": APP_SECRET,
        "key": rsa_b64(key),
        "version": rsa_b64(iv),                     # yes: "version" carries the IV
        "username": aes_hex(user, key, iv),
        "password": aes_hex(password, key, iv),
        "language": language,
    })
    if body.get("code") != 0:
        raise SystemExit(f"login abgelehnt (code={body.get('code')}): {body.get('message')}")
    d = body["data"]
    return {"access_token": d["access_token"], "refresh_token": d["refresh_token"]}


def access_token(refresh_token: str) -> str:
    body = post_form(TOKEN_URL, {"refresh_token": refresh_token})
    if body.get("code") != 0:
        raise SystemExit(f"refresh abgelehnt (code={body.get('code')}): {body.get('message')}")
    return body["data"]["access_token"]


def settings(refresh_token: str, device_id: str, language: str = "de") -> dict:
    """systemMode, EPS, ECO, onOff, socMin/socMax, dischargeProtection, powerLimit."""
    url = (f"{API}/remote/ezInverter/systemMode?"
           + urllib.parse.urlencode({"deviceId": device_id, "type": "EZHI",
                                     "language": language}))
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {access_token(refresh_token)}"})
    with urllib.request.urlopen(req, timeout=15) as r:
        body = json.loads(r.read())
    if body.get("code") != 0:
        raise SystemExit(f"Abfrage abgelehnt (code={body.get('code')}): {body.get('message')}")
    return body.get("data", body)


def selftest() -> None:
    """The three crypto details all fail as 'wrong password'. Check them here instead."""
    k, iv = "0" * 32, "1" * 16
    dec = lambda h: Cipher(algorithms.AES(k.encode()), modes.CBC(iv.encode())
                           ).decryptor().update(bytes.fromhex(h))
    assert len(k) == 32, "key must be 32 chars of hex text -> AES-256"
    assert dec(aes_hex("hunter2", k, iv)) == b"hunter2" + b"\0" * 9
    exact = "0123456789abcdef"                       # exactly one block
    assert dec(aes_hex(exact, k, iv)) == exact.encode() + b"\0" * 16, "extra block missing"
    assert len(base64.b64decode(rsa_b64(k))) == 256, "RSA-2048 block expected"
    print("selftest ok")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "login":
        user = os.environ.get("EZHI_USER") or (sys.argv[2] if len(sys.argv) > 2 else "")
        pw = os.environ.get("EZHI_PASS") or (sys.argv[3] if len(sys.argv) > 3 else "")
        if not user or not pw:
            raise SystemExit("EZHI_USER/EZHI_PASS setzen (oder als Argumente uebergeben)")
        print(json.dumps(login(user, pw)))
    elif cmd == "settings":
        print(json.dumps(settings(sys.argv[2], sys.argv[3])))
    elif cmd == "selftest":
        selftest()
    else:
        raise SystemExit(__doc__)
