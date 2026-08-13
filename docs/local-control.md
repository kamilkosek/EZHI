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

The routing approach has one property none of the DNS approaches have: the DNAT
rule is bound to the inverter's own address, so **the vendor app keeps working on
your home network**. A network-wide DNS rewrite redirects the app along with the
inverter, which is the risk listed against it above.

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
certificate for the vendor's MQTT hostname. Self-signed is fine (the device
checks nothing), and it must serve exactly the device's own topics — a `#`
wildcard is rejected by the vendor's ACL if you also bridge to the cloud.
Home Assistant's MQTT integration then has to be pointed at that broker.

What you give up while the device is redirected: the vendor app, OTA updates,
and any remote wake — the cloud can no longer reach the inverter. It keeps
running on its own settings regardless; a dead broker means "I cannot change
anything", not "the battery stops".

Every command goes over MQTT, `onOff` included. It has to: a redirected inverter
is not connected to the vendor cloud, so a cloud `onOff` cannot reach it — it
answers 200 and nothing happens. **Turning the inverter off takes its radio down
with it** (WLAN, BLE and the local HTTP API all die); only a 3 s press on the
battery button brings it back.

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

