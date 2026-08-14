#!/usr/bin/env python3
"""Print the MQTT credentials an EZHI inverter presents, so your broker can let it in.

Local MQTT needs the broker to accept the inverter, and the inverter
authenticates with a password held in firmware: 25 characters, printed nowhere
on the device and not derivable from anything you can read off it. Mosquitto
will not tell you what it is either -- a rejected client is logged by name,
never by password. So it has to be read off the wire once, and this is the
thing that reads it.

It stands in for the broker exactly long enough for the inverter to say hello:
it answers on the broker's port with the broker's certificate, reads the MQTT
CONNECT, prints what was in it, and exits. Nothing is stored and nothing is
forwarded. The inverter's attempt simply fails, it retries about every ten
seconds, and it is none the wiser.

    ./ezhi_mqtt_credentials.py listen --cert ezhi_broker.crt --key ezhi_broker.key

Run it where the inverter's traffic already lands, with nothing else holding port
9005. With a DNS rewrite that is any machine you point the name at. With a static
route it is the machine the route points at and no other -- the rule rewrites the
destination and not the source, so a third machine would answer under its own
address and the inverter would drop the reply. Then put what it prints into your
broker's logins and send the redirect back.

Needs: nothing outside the standard library.  Self-check: ./ezhi_mqtt_credentials.py selftest
"""
import argparse
import socket
import ssl
import sys


def parse_connect(packet: bytes) -> dict:
    """Pull client id, username and password out of an MQTT 3.1.1 CONNECT."""
    if not packet:
        raise ValueError("nothing received")
    if packet[0] != 0x10:
        raise ValueError(f"not a CONNECT packet (first byte {packet[0]:#04x})")

    position, multiplier, remaining = 1, 1, 0
    while True:                                  # remaining length is a varint
        if position >= len(packet):
            raise ValueError("truncated remaining-length field")
        byte = packet[position]
        position += 1
        remaining += (byte & 0x7F) * multiplier
        if not byte & 0x80:
            break
        multiplier *= 128
        if multiplier > 128 ** 3:
            raise ValueError("malformed remaining-length field")
    if len(packet) - position < remaining:
        raise ValueError(
            f"truncated packet: {remaining} bytes announced, {len(packet) - position} arrived"
        )

    def field(at):
        length = int.from_bytes(packet[at:at + 2], "big")
        start, end = at + 2, at + 2 + length
        if end > len(packet):
            raise ValueError("truncated field")
        return packet[start:end], end

    name, position = field(position)
    if name != b"MQTT":
        raise ValueError(f"unexpected protocol name {name!r}")
    flags = packet[position + 1]
    position += 4                                # protocol level, flags, keep-alive
    client_id, position = field(position)
    if flags & 0x04:                             # a will we ignore, but must step over
        _, position = field(position)
        _, position = field(position)
    username = password = None
    if flags & 0x80:
        username, position = field(position)
    if flags & 0x40:
        password, position = field(position)
    return {"client_id": client_id, "username": username, "password": password}


def show(value) -> str:
    """Credentials are arbitrary bytes on the wire; the EZHI's happen to be text."""
    if value is None:
        return "(not sent)"
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return f"0x{value.hex()}"


def listen(host: str, port: int, certfile: str, keyfile: str, timeout: float) -> dict:
    """Answer one connection with the broker's certificate and read its CONNECT."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile, keyfile)
    context.minimum_version = ssl.TLSVersion.TLSv1_2   # the inverter speaks 1.2

    with socket.create_server((host, port)) as server:
        server.settimeout(timeout)
        print(f"listening on {host}:{port} -- the inverter retries about every 10 s",
              file=sys.stderr)
        raw, peer = server.accept()
        print(f"connection from {peer[0]}", file=sys.stderr)
        with raw, context.wrap_socket(raw, server_side=True) as tls:
            tls.settimeout(timeout)
            packet = b""
            for _ in range(4):
                chunk = tls.recv(4096)
                if not chunk:
                    break
                packet += chunk
                try:
                    return parse_connect(packet)
                except ValueError as exc:
                    if not str(exc).startswith("truncated"):
                        raise
    raise ValueError("no complete CONNECT arrived")


def _encode_length(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value % 128
        value //= 128
        out.append(byte | 0x80 if value else byte)
        if not value:
            return bytes(out)


def build_connect(client_id, username=None, password=None, will=None) -> bytes:
    """Build a CONNECT the way a client does -- for the self-check only."""
    def field(value):
        return len(value).to_bytes(2, "big") + value

    flags, tail = 0x02, field(client_id)
    if will:
        flags |= 0x04
        tail += field(will[0]) + field(will[1])
    if username is not None:
        flags |= 0x80
        tail += field(username)
    if password is not None:
        flags |= 0x40
        tail += field(password)
    body = field(b"MQTT") + bytes([4, flags]) + (30).to_bytes(2, "big") + tail
    return b"\x10" + _encode_length(len(body)) + body


def selftest() -> None:
    # The shape actually seen on the wire: 12-character serial as both client id
    # and username, 25-character password, 65 bytes after the fixed header.
    packet = build_connect(b"D00000000000", b"D00000000000", b"0123456789abcdefghijklmno")
    assert packet[1] == 0x41, hex(packet[1])
    parsed = parse_connect(packet)
    assert parsed["client_id"] == b"D00000000000", parsed
    assert parsed["username"] == b"D00000000000", parsed
    assert parsed["password"] == b"0123456789abcdefghijklmno", parsed

    # A will has to be stepped over, or it is read as the credentials.
    parsed = parse_connect(build_connect(b"id", b"user", b"pw", will=(b"t/opic", b"bye")))
    assert (parsed["username"], parsed["password"]) == (b"user", b"pw"), parsed

    # Past 127 bytes the remaining length needs a second varint byte.
    parsed = parse_connect(build_connect(b"id", b"u", b"p" * 200))
    assert parsed["password"] == b"p" * 200, len(parsed["password"] or b"")

    # A client that sends neither must not come back as empty strings.
    parsed = parse_connect(build_connect(b"anon"))
    assert parsed["username"] is None and parsed["password"] is None, parsed

    for bad, what in ((b"\x30\x02ab", "a PUBLISH"), (b"", "an empty read"),
                      (b"\x10\x7f\x00\x04MQTT", "a half-arrived CONNECT")):
        try:
            parse_connect(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{what} was accepted as a CONNECT")
    print("selftest ok")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    listener = commands.add_parser("listen", help="stand in for the broker once")
    listener.add_argument("--cert", required=True, help="the certificate your broker serves")
    listener.add_argument("--key", required=True)
    listener.add_argument("--host", default="0.0.0.0")
    listener.add_argument("--port", type=int, default=9005)
    listener.add_argument("--timeout", type=float, default=120.0)
    commands.add_parser("selftest", help="check the parser without a device")

    args = parser.parse_args()
    if args.command == "selftest":
        return selftest()

    try:
        parsed = listen(args.host, args.port, args.cert, args.key, args.timeout)
    except TimeoutError:
        sys.exit(f"nothing connected within {args.timeout:.0f} s -- is the redirect "
                 f"pointed at this machine, and is port {args.port} free?")
    except OSError as exc:
        sys.exit(f"could not listen on {args.host}:{args.port}: {exc}")

    print(f"client id : {show(parsed['client_id'])}")
    print(f"username  : {show(parsed['username'])}")
    print(f"password  : {show(parsed['password'])}")
    print("\nput username and password into your broker's logins, then point the "
          "redirect back at the broker.", file=sys.stderr)


if __name__ == "__main__":
    main()
