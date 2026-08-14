# Local control: getting the inverter off the vendor cloud

The integration's short version is in the [README](../README.md#control-transport-cloud-bluetooth-or-local-mqtt).
This is the long one: how the redirect actually works, which shape of it you can
undo while away from home, what the broker has to look like, and the option that
keeps the vendor app alive alongside it.

## Choosing a transport

**Configure → Control transport** decides which wire the control commands take.
The default is **Cloud**, and an existing installation keeps that on upgrade.

**Bluetooth** sends the same commands straight to the inverter over its BluFi
channel, so a scene change or a SOC limit no longer travels to a vendor server
and back. The entities, the polling and the safety rules are identical — only
the transport differs.

It is **not** a cloud-free mode. The inverter's radio switches itself off after
15 minutes of idleness and then does not advertise at all; the only unattended
way to open that window again is the cloud call `btOnOff`, so the cloud
credentials stay in use. Without them the alternative is physical: battery
button, 3 s off, back on. Once a connection is open it is held, which keeps the
window from closing.

Requirements: Home Assistant's Bluetooth integration, with an adapter or an
ESPHome Bluetooth proxy in range of the inverter. The device is found by its
BLE name (`EZHI_<deviceId>`), so there is nothing else to configure.

**Local MQTT** is the only transport that needs no vendor account at all. The
inverter's link to its cloud *is* MQTT, and it validates nothing about the
broker it lands on — no certificate pinning, no mutual TLS. Point its DNS at a
broker on your own network and you have the vendor's own control channel:
identical identifiers, params and replies, with no vendor server in the path.

It is also the most invasive to set up, and the reason is worth stating plainly
because it cannot be engineered away:

> **The inverter has no setting for its broker address.** The vendor app's
> entire command vocabulary — 24 identifiers, read out of the app itself — has
> no field for a server, broker or host. (`httpServer` sounds like one and is
> not: it toggles the device's local HTTP server.) The hostname is fixed in the
> firmware, so **the redirect has to happen in your network** — either at the
> name (DNS) or at the packet (routing).

If you have never done anything of the sort, the whole idea fits in two
sentences. The inverter asks your network for the address of the vendor's broker
and then connects to whatever address it is handed — so you can either **change
the answer**, having a DNS server of your own hand back your broker's address
instead of the vendor's, or **leave the answer alone and intercept the packets**,
telling your router that anything bound for the vendor's address goes to a
machine of yours, which rewrites the destination as it arrives. Either way the
inverter ends up connected to you while believing it reached the vendor, and it
cannot tell the difference, because it checks nothing.

Changing the answer is one entry in a DNS server you run: a *DNS rewrite* in
AdGuard Home, a *local DNS record* in Pi-hole — both are Home Assistant add-ons,
and both want nothing but the name and the address to answer with. Intercepting
the packets is a static route in your router plus something to hold the rewriting
rule, which is what [ezhi-reroute](https://github.com/Glenbeulah/ezhi-reroute)
exists to be.

That redirect is infrastructure you run, not something this integration
configures. Four shapes. They differ in effort, and in something less obvious
that is easy to discover too late: **whether you can undo it when you are not at
home.** If you ever want the vendor app while away — or need to back the whole
thing out in a hurry — that last column decides for you, not the first two.

| Approach | What it costs | What it risks | Undo it remotely? |
|---|---|---|---|
| **Network-wide DNS** (AdGuard Home or Pi-hole with one rewrite rule, your router pointed at it) | One add-on, one rule, undone in a click | All name resolution now depends on that host. The rewrite also applies to the vendor app while it is on your home WiFi. | **Yes, for anyone** — both have REST APIs, so Home Assistant can flip the rule |
| **Routing** (a static host route for the vendor address, plus a DNAT rule on the machine it points at) | A router that can do static routes, and something to hold the rule — see [ezhi-reroute](https://github.com/Glenbeulah/ezhi-reroute) | The switch lives in your router rather than with you. Route active with no rule installed is a blackhole: the inverter reaches neither your broker nor the vendor. | **Only if your router has an API.** A FRITZ!Box can do it over TR-064; most ISP boxes cannot |
| **Separate segment** (a second router or AP running its own subnet and DNS, with only the inverter on it) | A spare router, a new SSID, re-provisioning the inverter's WiFi, and a port forward so Home Assistant can still reach the local HTTP API | Nothing outside that segment. This is the clean one. | Usually, if the segment runs on a machine you can reach |
| **DHCP with per-device DNS** (hand the inverter a different resolver by MAC) | Your router's DHCP has to move to the host doing this | If that host dies, no device gets a lease. | Yes, if you can reach that host |

### If your router is a FRITZ!Box

Measured on a 7530 AX, and worth reading before you start, because four of these
five cost an evening each. AVM's box is the common case in the countries this
inverter sells in, and it is unusually opinionated about exactly this.

1. **It cannot hold its own host records.** There is no "map this name to this
   address" anywhere in it, so the DNS approach needs a resolver of your own on
   the network — AdGuard Home, Pi-hole or a plain dnsmasq.
2. **Do not enter that resolver under *Internet → Zugangsdaten → DNS-Server*.**
   The box treats a private address coming back from what it considers an
   internet resolver as DNS rebinding and throws the answer away — even with a
   rebind exception configured. Foreign names resolve, the one you care about
   stays stubbornly correct, and nothing anywhere says why.
3. **Enter it under *Heimnetz → Netzwerk → Netzwerkeinstellungen → IPv4* as the
   local DNS server** instead. That address is then handed to clients over DHCP,
   and the rebind exception applies on the client side, where it works.
4. **Add the rebind exception for the hostname**, and **turn off "fall back to
   public DNS servers on faults"** while you are testing. Left on, the real
   address leaks through the moment your resolver hesitates, and the inverter
   quietly reconnects to the vendor.
5. **Clients take the new resolver only with a fresh DHCP lease**, and the box
   caches the vendor's CNAME for minutes. Reboot the inverter rather than waiting
   — and note that pulling its AC plug does not reboot it, since it runs from the
   battery DC. Use the integration's Inverter On switch, or the battery.

The routing approach has one property none of the DNS approaches have: the DNAT
rule is bound to the inverter's own address, so the vendor app is never
redirected. It reaches the vendor as usual, while a network-wide DNS rewrite
would send the app's own MQTT to your broker too — the risk listed against it
above.

Do not read that as "the app still works". **It will show your inverter as
offline**, measured 2026-08-15, and so will every other mechanism here: the
device has left the vendor cloud, so the cloud knows nothing about it and the app
reports what the cloud knows. What routing preserves is the app itself, not the
view of your inverter. For that there is only the bridging broker below.

Two recommendations that follow from that last column:

- **If your router cannot be automated, prefer DNS over routing.** Then the
  switch sits on a machine you reach through Home Assistant, rather than behind a
  router login you cannot get to from outside.
- **If what you actually want is the app while away, consider not switching at
  all** — bridge your broker to the vendor cloud instead (below). It has real
  downsides, but it needs no switch.

If you take the separate-segment route: **re-provision the inverter's WiFi
before you redirect DNS.** Provisioning goes through the vendor app, and the
app needs the cloud — redirect first and you cannot move the device any more.

The broker itself must listen on **port 9005 with TLS 1.2** and present a
certificate for the vendor's MQTT hostname. It does **not** have to be a new
broker, and your MQTT integration does not have to be repointed — see
[The broker](#the-broker-use-the-one-you-already-have) below.

What you give up while the device is redirected: the vendor app, OTA updates,
and any remote wake — the cloud can no longer reach the inverter. It keeps
running on its own settings regardless; a dead broker means "I cannot change
anything", not "the battery stops".

Every command goes over MQTT, `onOff` included. It has to: a redirected inverter
is not connected to the vendor cloud, so a cloud `onOff` cannot reach it — it
answers 200 and nothing happens. **Turning the inverter off takes its radio down
with it** (WLAN, BLE and the local HTTP API all die); only a 3 s press on the
battery button brings it back.

## The broker: use the one you already have

The inverter needs a broker listening on **port 9005 with TLS 1.2**, presenting a
certificate for the vendor's MQTT hostname. Self-signed is fine — the device
validates nothing — and it asks for no client certificate.

**None of that calls for a second broker, and you should not stand one up.** Home
Assistant's MQTT integration accepts exactly one broker at a time
(`single_config_entry` in its manifest), so pointing it somewhere new would
disconnect every other MQTT device you own. Put the listener on the broker Home
Assistant already talks to instead. The inverter arrives on 9005 over TLS, Home
Assistant stays on 1883 exactly as before, and because that is one broker rather
than two, both sides see the same topics. **Nothing about your MQTT integration
changes — there is no setting in it for any of this.**

The order is not the intuitive one, so before the details, the shape of it:

1. **Make the certificate and key**, and put them in `/ssl/`.
2. **Capture the inverter's password.** It is the one value you cannot look up.
   Doing it by hand has to happen *before* the broker is finished, because a
   broker already listening on 9005 swallows it — but if you redirect with
   [ezhi-reroute](https://github.com/Glenbeulah/ezhi-reroute) this is one toggle
   and the order stops mattering.
3. **Configure the broker**: the four settings below, with the password from
   step 2 in `logins`.
4. **Point the redirect back at the broker** and switch the integration's control
   transport to Local MQTT.

With the official Mosquitto broker add-on step 3 is four settings and no config
file editing:

| Where | What |
|---|---|
| `/ssl/` | `ezhi_broker.crt` and `ezhi_broker.key` — self-signed for the vendor's MQTT hostname, [one openssl command](#making-the-certificate) |
| Add-on **Configuration** | `certfile: ezhi_broker.crt`, `keyfile: ezhi_broker.key`, `require_certificate: false` |
| Add-on **Configuration** → `logins` | one entry: username = the inverter's serial, password = the one it presents to the cloud |
| Add-on **Network** | publish container port **8883** on host port **9005** |

The add-on raises a TLS listener on 8883 by itself as soon as a certificate is
configured; the port mapping is the whole trick, putting that listener on the
port the inverter dials. Plain 1883 is never touched, so Zigbee2MQTT, ESPHome and
everything else keep running through the same broker.

Two things worth knowing before copying that table:

- **`certfile` and `keyfile` are global to the add-on**, so 8883 and 8884 will
  both present the inverter's certificate. If you already serve TLS clients of
  your own on those ports, give the inverter a listener of its own through the
  add-on's `customize` folder rather than repurposing that one.
- **The password is not printed on the device, and you cannot look it up.** Client
  id and username are both the serial from the label, but the password is 25
  characters out of firmware — and Mosquitto will not reveal it either, since a
  rejected client is logged by name and never by password. It has to be read off
  the wire once; there is a tool for that, below.

If you also bridge to the vendor cloud, the broker has to serve exactly the
device's own topics — a `#` wildcard is silently rejected by the vendor's ACL.

### Making the certificate

Self-signed, one command, no CA and nothing to renew:

```bash
openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes \
  -keyout ezhi_broker.key -out ezhi_broker.crt \
  -subj "/CN=data.mqtt.apsystemsema.com" \
  -addext "subjectAltName=DNS:data.mqtt.apsystemsema.com"
```

Run that wherever you have openssl; a laptop is fine, since it talks to nothing
and only writes two files. It is normal for it to print a screenful of dots and
plus signs while it looks for primes — that is the key being generated, not an
error.

The two files then go into Home Assistant's `/ssl/` directory — the Samba add-on
shares it as `ssl`, and the SSH or File Editor add-ons reach it as well — and
their names go into the broker add-on's `certfile` and `keyfile`. They are the same
two files the credential tool below wants for `--cert` and `--key`.

**Put the vendor's hostname in the subject and the SAN.** The inverter does not
validate the certificate, which is the entire reason any of this works — but what
is known to work is a certificate carrying the name it dialled. Whether it would
accept some other name has not been tested, and there is nothing to gain by
finding out.

### Reading the password off the device

[`tools/ezhi_mqtt_credentials.py`](../tools/ezhi_mqtt_credentials.py) stands in
for the broker exactly long enough for the inverter to say hello. It answers on
the broker's port with the broker's certificate, prints the `CONNECT` it
receives, and exits. Nothing is stored and nothing is forwarded: the attempt
simply fails, and the inverter retries about every ten seconds none the wiser.

**If you redirect with [ezhi-reroute](https://github.com/Glenbeulah/ezhi-reroute),
skip all of this.** The add-on has a `capture_credentials` option that does the
same thing from inside, on a port of its own: set `certfile` and `keyfile`, turn
it on, restart it, and the credentials are in its log about ten seconds later.
Nothing has to move to another machine, the broker never stops, and the order
above stops mattering. Measured against a real inverter on 2026-08-15 — the
password it printed matched the one captured by hand months earlier.

What follows is for everyone else: a DNS rewrite, a segment of your own, or no
Home Assistant add-on at all.

**Do it before the broker is finished, not after.** The `logins` entry above
wants a password you do not have yet, and a broker that is already listening on
9005 will turn the inverter away without ever showing you what it presented.
Either send the redirect somewhere else for a minute (step 3 says where that can
be) or stop the broker while the tool runs.

1. Make the certificate and key first — the broker needs them anyway.
2. Run it on a machine with Python 3 and nothing else holding the port. Step 3
   decides which machines qualify:

   ```bash
   ./tools/ezhi_mqtt_credentials.py listen --cert ezhi_broker.crt --key ezhi_broker.key
   ```

3. Send the inverter's traffic to that machine. **Which machines are available to
   you depends on the redirect you chose**, and this is the part that wastes an
   evening if you get it wrong:

   - **DNS rewrite** — any machine. Point the name at it and the inverter dials
     that address itself; no address translation is involved, so the replies come
     from where the inverter expects them.
   - **Routing** — the machine the route already points at, and only that one.
     Sending `broker_ip` somewhere else does not work: the rule rewrites the
     destination and nothing else, so the third machine would answer under its
     own address and the inverter would drop the reply. Stop the broker there
     while the tool runs; only one of them can hold port 9005. If that machine is
     running ezhi-reroute, its `capture_credentials` option is the same thing
     without any of this — use that instead.
4. Wait about ten seconds. The inverter connects, the tool prints the client id,
   the username and the password, and exits.
5. Put the username and password into the broker's `logins`, then point the
   redirect back at the broker.

It needs nothing outside the standard library, and `./tools/ezhi_mqtt_credentials.py
selftest` exercises its parser without a device if you would rather see it work
before wiring anything up.

Whether that password is unique to your inverter is not known — exactly one has
ever been looked at. Read your own rather than borrowing one.

## Keeping the vendor app: the bridging broker

There is a way to have both — local control *and* a working app. Configure the
local broker to **bridge** to the vendor cloud, so the chain becomes
`inverter → your broker → bridge → vendor cloud`. The integration cannot tell
the difference: the transport is still `local_mqtt`, and only the broker
configuration changes. There is deliberately no separate option for it.

It is not the recommended path, and the reasons are not squeamishness:

- **Your broker becomes a permanent man-in-the-middle.** It holds the device
  credentials around the clock and impersonates the vendor to the inverter.
- **It becomes a single point of failure for the cloud as well.** The device now
  reaches the vendor only through your broker — if it dies, the app dies with
  it. For the cloud path specifically this is strictly *less* reliable than
  simply staying on the cloud transport.
- **The bridge has to reach the real cloud while DNS is poisoned.** The clean
  way is a hosts entry on the broker machine itself, which takes precedence over
  your own DNS override. That pins an IP — and the vendor's endpoint sits behind
  a load balancer whose address can rotate, so the pin is a maintenance item,
  not a one-off.

Two things that cost real time if you find them yourself, both measured:

- **Do not bridge with a `#` wildcard.** The vendor's ACL for device credentials
  silently rejects it: nothing comes through, and the app just shows the device
  as offline with no error anywhere. List the device's own topics explicitly —
  its seven subscribe topics plus the ones it publishes.
- **Client-id collision.** The device authenticates as its serial number, and so
  does the bridge. Two connections claiming one identity will fight.


## Smart linking (`thirdLink`), in full

The master switch for the vendor app's "smart linking" — what a smart meter
(Shelly, EcoTracker) hangs off. With it on, the app offers zero export, relay
control and phase detection.

The reason it is worth having here: **the app couples the two.** Turn linking on
there and it will only let you run zero export — never surplus feed-in with
demand-driven discharge. Toggling the master from Home Assistant leaves that
choice to you.

The field is not a boolean, which matters if you read it yourself:

| Value | Meaning |
|---|---|
| `"0"` | off |
| `"1"` | on, with a device actually coupled |
| `"2"` | on, with nothing coupled |

Both `1` and `2` mean on. `2` was measured on an inverter where linking was
enabled but no meter existed to pair with; `1` on one with a meter bound
(`bindList` non-empty, `meterDeviceNum: 1`). The switch writes `1` to turn it
on and `0` to turn it off, and reports on for anything that is not `0`.

Two limits, stated plainly:

- **It cannot be combined with Local mode.** Turning linking on moves the
  inverter to Balcony mode (measured 2026-08-07), and Local is the only mode
  where a local `setPower` setpoint is obeyed. The switch refuses rather than
  letting that happen quietly; change the system mode first if you want it.
- **Nobody has driven this against a coupled meter yet.** The values above are
  verified on two devices and the write goes through the same path as every
  other `systemMode` field, but neither device could exercise what linking
  actually does. If you own a smart meter, you are the first — reports welcome.

