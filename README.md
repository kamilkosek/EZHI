# APsystems EZHI - Home Assistant Integration

## Overview

This Home Assistant integration allows you to monitor and control your APsystems EZHI inverter via the local API. It provides sensors for real-time data, alarm monitoring, and controls for power settings.

## Features

- **Monitor PV Power & Energy**: Track photovoltaic power generation and total energy production.
- **Battery Monitoring**: View battery state, charge/discharge rates, temperature, and status.
- **Grid Interaction**: Monitor power flow to and from the grid.
- **Alarm Monitoring**: Get notified about system errors and warnings via 20 binary sensors.
- **Power Control**: Set the maximum power output of your inverter.
- **Separate Scan Intervals**: Configure fast polling for power data and slower polling for alarms/device info.
- **Device Info Panel**: View firmware version, serial number, and direct link to inverter API.
- **Multi-language Support**: English and German translations included.
- **Cloud Control (optional)**: On/off, system mode, backup power (EPS), ECO, SOC limits and more — none of which exist in the local API.

## Prerequisites

Before installing this integration, you need to:

1. Ensure your APsystems EZHI inverter is connected to your local network
2. Activate local mode on the inverter through the APsystems app. The vendor
   manual ties this to the one write: *"This command only takes effect after
   enabling local mode in the APP"* — and only to that. Reading was measured to
   work in every system mode, so an inverter left in another scenario still
   feeds every sensor here. What is untested is a device that has never been put
   into Local mode at all
3. Set a static IP address for the inverter in your router (recommended)

## Installation

### HACS (Recommended)

1. Add this repository as a custom repository in HACS
2. Install the integration from HACS
3. Restart Home Assistant
4. Add the integration through the Home Assistant UI (Settings > Devices & Services)

### Manual

1. Download the latest release
2. Extract the `apsystems_ezhi_local` folder to your `custom_components` directory
3. Restart Home Assistant
4. Add the integration through the Home Assistant UI

## Configuration

1. Go to Settings > Devices & Services
2. Click "Add Integration" in the bottom right
3. Search for "APsystems EZHI Local API" and click on it
4. Enter the inverter's IP address and name
5. Click "Submit"

### Changing Update Interval

After initial setup, you can change the scan intervals without reconfiguring:

1. Go to Settings > Devices & Services
2. Find "APsystems EZHI Local API" and click "Configure"
3. Adjust the intervals:
   - **Power data interval**: Fast updates for ogP, pvP, batP etc. (default: 5s)
   - **Alarms & device info interval**: Slower updates for alarms and device info (default: 60s)
4. Click "Submit" - the integration will reload automatically

## Available Entities

### Sensors

| Entity | Description | Unit |
|--------|-------------|------|
| Battery Status | Current battery state (Idle/Charging/Discharging/Fault/Shutdown/No Communication) | - |
| Photovoltaic Power | Current power generation from solar panels | W |
| Photovoltaic Energy | Total energy generation from solar panels | kWh |
| Battery Power | Current battery charge/discharge rate | W |
| Battery State of Charge | Current battery charge percentage | % |
| Battery State of Health | Battery health percentage | % |
| Battery Temperature | Battery temperature | °C |
| Battery Total Charge Energy | Total energy charged to the battery | kWh |
| Battery Total Discharge Energy | Total energy discharged from the battery | kWh |
| Battery Capacity | Battery capacity | kWh |
| On-Grid Power | Current power flow to/from the grid | W |
| On-Grid Output Energy | Total energy output to the grid | kWh |
| On-Grid Input Energy | Total energy input from the grid | kWh |
| Off-Grid Power | Current power flow to/from off-grid loads | W |
| Off-Grid Output Energy | Total energy output to off-grid loads | kWh |
| Off-Grid Input Energy | Total energy input from off-grid sources | kWh |
| Device Temperature | Inverter temperature | °C |

### outputData sensors (Bluetooth and local MQTT)

On the **Bluetooth** and **local MQTT** control transports (see *Cloud Control
→ Control transport*) the inverter's `outputData` payload carries readings the
local HTTP API does not expose — the DC battery, grid quality, per-string PV,
the off-grid branch and the device's uptime. They are created only on those two
transports; the cloud transport has no read for the payload, so there they are
not created at all rather than sitting permanently unavailable.

| Entity | Description | Unit |
|--------|-------------|------|
| Battery Voltage | DC battery voltage | V |
| Battery Current | DC battery current, signed. The charge/discharge sign is unverified and taken raw, so history is not distorted by a guess | A |
| PV1–PV3 Voltage / Current | Per-string PV voltage and current | V / A |
| PV1 / PV2 Power | Per-string PV power — the reply has no `pv3P` | W |
| PV1–PV3 Total Energy | Per-string lifetime energy (`total_increasing`) | kWh |
| Device Temperature 2 / 3 | Two further internal temperatures beside `devTemp` | °C |
| Grid Voltage | On-grid voltage | V |
| Grid Frequency | On-grid frequency | Hz |
| Off-Grid Voltage / Current | The off-grid branch, which had only its power before | V / A |
| Uptime | Seconds since the inverter last restarted — the only way to notice that it did | s |

All three strings are exposed. A string with no module wired reads 0 — a real
value, not "missing" — as PV2/PV3 do on the development install; hiding those
rows is a per-dashboard choice, not baked into the integration.

`outputData` has 50 fields in all. Ten more of them are exposed as **diagnostic
sensors** under their wire names: `batCT`, `cMode`, `rS`, `mode`, `reUpdate`,
`metL1`, `metL2`, `metL3`, `metDC`, `freeRam`. Nine are disabled by default;
`freeRam` is on, because free heap is the only one of them that moves and a
falling trend across days is the early warning for a firmware memory leak. They
carry
no unit, no device class and no state class, because what they mean has not
been established — and a sensor called "Battery Cycles" would be a guess
wearing the clothes of a fact, while `batCT` claims nothing at all. Enable one
in the entity settings if you want to watch it. If you work out what it is, it
belongs in the measured table above, and the field table in `ble_api.py` is
where that change goes.

`apsystems_ezhi_local.ble_raw_get` is a diagnostics action: it fetches one raw
block (default `outputData`) and logs the full reply at WARNING, for reading
fields that are not sensors and for reverse-engineering the raw frames. Works on
Bluetooth and on local MQTT.

### Device diagnostics (local transports)

`deviceInfo` is read on every control poll anyway — the WiFi signal sensor needs
it — and twenty-four of its fields had no entity until v0.9.0. They are now
**diagnostic entities**: firmware versions (`devVer`, `dspVer`, `dcmVer`,
`batFwVer`, `batHwVer`), the network address, the locale, the vendor codes under
their wire names, and four link flags.

Six of them are enabled by default: **Firmware Version**, **Battery Firmware
Version**, **IP Address**, **Cloud Connected**, **WiFi Connected** and
**Bluetooth Enabled**. The last two answer the question that costs the most time
when a transport stops working — *is the radio even on?* — in one look.

The rest are off by default, and four of them deliberately so: `deviceId`,
`ssid`, `bluetoothMac` and `wifiMac` identify your device and your network, and
an update should not put them into your recorder without you asking.

### Extra diagnostic reads (local MQTT only)

Six identifiers answer a `get` and are read nowhere else. All twenty-one of the
entities they produce are **disabled by default** — they explain exceptional
cases, and nobody should gain twenty-one entities from an update.

| Read | What it carries |
|---|---|
| `light` | the four LED state codes (`sys`, `ofg`, `bat`, `wifi`) |
| `alarm` | the raw `dsp` / `battery` / `pv` bitmasks |
| `supportFunction` | which features the firmware admits to (`AIMode`, `acProtect`, `weeklyStrategy`, `pvForcedCharging`, `noBattery`) |
| `meterStatus` | the external meter: power, signal, channel, connection counters |
| `btLock` | whether the Bluetooth pairing lock is set |
| `bindDevice` | how many devices are paired |

These are MQTT-only by design, not by omission. The MQTT transport correlates
replies by id, so all nine reads of a poll cycle — `systemMode`, `outputData`,
`deviceInfo` and these six — go out **together** and are answered inside one
firmware tick. Measured against the device: ten identifiers fired at once are
answered in 2.5–3.0 s, while a single sequential read takes 5.05 s. Bluetooth is
a serial link, where the same set would be six more round trips per poll, so
there these entities are not created at all.

That is what makes three times the reads cost no more wall clock than before:
one gather is one tick, however many identifiers are in it.

The `alarm` bitmasks are kept even though the twenty decoded protection flags
already have their own binary sensors. The masks carry more: `pv` reads
`…01100000…` while `PvHV` and `PVWE` are both 0 at the same moment. Which bit
means what is not established, so the raw string is what you get.

**Not exposed, and each for a checked reason:** `si` (all twenty flags already
have binary sensors), `wifiStatus`, `caTz` and `combineVersion` (every field is
already in `deviceInfo`), and `batteryCellData` — which does not answer a `get`
on either transport, and whose push payload is empty (`{"cell": [],
"cellStatus": 0}`). There are no per-cell voltages behind it to find.

### Binary Sensors (Alarms)

| Entity | Description | API Field |
|--------|-------------|-----------|
| Battery Overtemperature | Battery high temperature protection active | BatHTP |
| Battery Undertemperature | Battery low temperature protection active | BatLTP |
| Battery Communication Error | Battery communication error detected | BatCE |
| Battery Overvoltage | Battery overvoltage protection active | BatHV |
| Battery Undervoltage | Battery undervoltage protection active | BatLV |
| Battery Overcurrent | Battery overcurrent protection active | BatHI |
| Battery Error | General battery error detected | BatE |
| Battery Shutdown | Battery shutdown state | SBS |
| Device Overtemperature | Device high temperature protection active | DTP |
| Device Error | General device error detected | EE |
| AC Abnormal | AC grid abnormality detected | ACA |
| Off-Grid Overcurrent | Off-grid overcurrent protection active | OfOI |
| Off-Grid Short Circuit | Off-grid short circuit protection active | OfGS |
| PV Overvoltage | PV overvoltage protection active | PvHV |
| PV Overcurrent | PV overcurrent protection active | PvOC |
| PV Wiring Error | PV wiring error detected | PVWE |
| IRD Error | IRD (Insulation Resistance Detection) error | IRDE |
| SOC Calibration Needed | Battery SOC reading is off — charge to 100% to recalibrate | BCC |
| Battery Access Conflict | A battery is connected while the inverter runs in battery-free mode | BCI |
| Voltage Reset Protection | PV input too low, or protection after a grid anomaly/overload — a restart is needed and can take several minutes | VRP |

The last three are reported by `getAlarm` on current firmware. On firmware that
does not send them they read `unknown` rather than "no problem".

> **Some alarms are transients, and the poll will miss them.** `ACA` was
> measured lasting about two seconds after a grid outage — it marks the moment
> the grid goes away and clears again once the inverter has settled into island
> operation. The alarm endpoint is polled every 60 s by default, so a sensor
> here catches an event like that roughly one time in thirty. Do not build an
> outage detector on `AC Abnormal`; use `On-Grid Power` at zero together with a
> negative `Battery Power`, which means the battery is carrying the off-grid
> load alone. Shortening the alarm interval helps a little and costs a request
> per second — it does not make a two-second event reliable.
>
> How much of this generalises to the other nineteen codes is untested. `ACA`
> hangs off the grid monitor, which can only run while the inverter is
> grid-following, so it may well be the exception rather than the rule.

> **And some expected alarms simply never appear.** A user polled `getAlarm`
> once a second from Node-RED — fast enough that the two-second `ACA` above
> should have been caught — and ran three deliberate provocations on his own
> inverter:
>
> | What was done | Alarm expected | Alarm seen |
> |---|---|---|
> | Charged the battery to 100 % (APsystems support says an overvoltage warning is raised at 99 %) | `BatHV`, `BatE` | none |
> | Cut the on-grid supply all-poles at a smart plug — the app showed the outage in its own chart | `ACA` | none |
> | Battery whose SOC reading is visibly off | `BCC` | none |
>
> So a flag staying clear is not evidence that the condition did not occur.
> Treat these sensors as "the inverter said something", never as "nothing is
> wrong" — the same measurements that reach the app do not necessarily reach
> `getAlarm`. One user, one device, firmware of early August 2026; if your
> inverter does raise one of these, that is worth reporting.

Each alarm sensor carries that text as attributes — `cause` and
`suggested_action`, plus the vendor's own `vendor_name` and the `alarm_code` —
so a sensor that goes to *Problem* also tells you what the app would have told
you. German if Home Assistant is set to German, otherwise English. They are
excluded from the recorder, being static.

**[docs/alarms.md](docs/alarms.md)** has the same for all twenty in one place.
[docs/alarms.json](docs/alarms.json) is the machine-readable copy, for anyone
reading `getAlarm` from Node-RED or a script instead of from this integration.

`BCI` and `VRP` were added to the vendor's Local API manual in V1.3 (2026-02-04).
`BCC` is in none of its versions, so do not expect to find it there: it is
undocumented but present in the `getAlarm` response (verified on firmware
1.9.0.16, 20 fields) and carried by the app, which builds its alarm screen from
whatever keys the response contains — for every field set to `"1"` it looks up
`<FIELD>_name` and `<FIELD>_reason` in its translations, and those exist for
`BCC` in all twelve shipped languages ("SOC Calibration" / "There is an error in
the battery SOC. Please charge the battery to 100%."). The integration maps it
for the same reason: the device sends the field, whether or not the manual
lists it.

### Controls

- **Max Output Power**: the on-grid setpoint, -1200 W to +1200 W. **Positive
  discharges to the grid, negative charges from it** — measured, and the
  opposite of what this file and `services.yaml` said before v0.5.2

> **This only does anything in the Local system mode.** The vendor manual says
> so in one line under `setPower` — *"This command only takes effect after
> enabling local mode in the APP"* — and it is easy to miss, so: measured across
> all four modes, with the setpoint written to -300 W, the inverter followed it
> in Local (grid flow went from -146 W to +272 W) and ignored it in Balcony
> Storage, Portable and AI, where it kept running its own strategy. `setPower`
> answers `SUCCESS` in every mode, so a write that changes nothing looks exactly
> like one that works — writing it outside Local logs a warning here for that
> reason. The app matches: it only sends a power target (`userSetPower`) in the
> Balcony Storage and Portable scenarios, and its Local mode screen offers no
> power control at all — that is the slot the local API writes into.

## Cloud Control (optional)

The local API is read-only apart from `setPower`. On/off, the system mode and
**backup power (EPS)** are not in it at all — they exist only in the APsystems
EMA cloud. This integration can talk to that cloud as a second, fully separate
layer.

**The local side never depends on it.** The cloud runs on its own coordinator:
dead credentials, an unreachable cloud or a hanging request take out the cloud
entities only. Every local sensor keeps updating, and Home Assistant offers a
reauth prompt instead of failing the whole entry. Verified against a live
install: with a deliberately broken token, all four cloud entities went
`unavailable` and all 130 local entities kept their values.

Leave the token fields empty and nothing about the integration changes.

### Setup

Go to **Settings → Devices & Services → APsystems EZHI → Configure** and enter
the **username** and password of your APsystems EMA account. The integration
performs the same login the app does and stores the resulting token pair.

> The account **username**, not the e-mail address you may also log in with —
> `loginEncrypt` rejects the address. Verified against a live account.

**The password is used once and never stored** — only the tokens are written to
the config entry, and the `refresh_token` does not rotate, so the login only has
to succeed once. The account fields stay empty afterwards for that reason; to
switch accounts, fill them in again.

There is no documented API for this. The login endpoint
(`POST /api/token/generateToken/user/loginEncrypt`) encrypts the credentials
client-side: a fresh AES-256 key and IV per login, both RSA-wrapped under a
public key baked into the app. That scheme is reproduced in `cloud.py` from the
app's own implementation, so no HTTPS proxy capture is needed. If you already
have a captured token pair, the two token fields still accept it directly.

### Control transport: cloud, Bluetooth or local MQTT

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
> firmware, so **a DNS redirect is the only way in.**

That redirect is infrastructure you run, not something this integration
configures. Three shapes, roughly in order of effort:

| Approach | What it costs | What it risks |
|---|---|---|
| **Network-wide DNS** (AdGuard Home or Pi-hole with one rewrite rule, your router pointed at it) | One add-on, one rule, undone in a click | All name resolution now depends on that host. The rewrite also applies to the vendor app while it is on your home WiFi. |
| **Separate segment** (a second router or AP running its own subnet and DNS, with only the inverter on it) | A spare router, a new SSID, re-provisioning the inverter's WiFi, and a port forward so Home Assistant can still reach the local HTTP API | Nothing outside that segment. This is the clean one. |
| **DHCP with per-device DNS** (hand the inverter a different resolver by MAC) | Your router's DHCP has to move to the host doing this | If that host dies, no device gets a lease. |

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
anything", not "the battery stops". The `onOff` command still routes over the
cloud on this transport, and is refused rather than guessed at when no cloud
credentials are configured.

#### Keeping the vendor app: the bridging broker

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

### Entities

| Entity | Type | Notes |
|--------|------|-------|
| Inverter On | `switch` | **One-way from HA.** Once off, the inverter drops off the cloud's MQTT link and cannot be turned back on remotely — it needs PV/DC input or a 3 s press on the battery button. |
| System Mode | `select` | Balcony Storage, Portable, AI, Local, No Battery. These are operating scenarios, not the Local API toggle: the local API answered in every one of them when tested, and a user on the vendor forum polls it while running Portable. ~~Per APsystems support, what Portable switches off is the alarms.~~ **Measured false:** pulling the grid plug in Portable raised `ACA` on the local API. It only stood for about two seconds, which is the likelier reason nobody sees these alarms. See the alarm note above. |
| Backup Power (EPS) | `switch` | Mutually exclusive with ECO — enabling one clears the other in a single write. |
| ECO Mode | `switch` | The opposite policy to EPS for the same output stage, which is why the firmware treats them as exclusive: EPS keeps the off-grid output armed, ECO drops it after an hour with no load. Recovery is via the AC output switch. An A/B here measured ~17 W of standby either way — but see below. |
| Smart Linking | `switch` | The `thirdLink` master switch a smart meter hangs off — see below. Refused while the inverter is in Local mode, because turning it on moves the device to Balcony and would silently disable the local power setpoint. |
| SOC Minimum / Maximum | `number` | Percent. |
| Discharge Protection | `number` | Refused below *SOC minimum + 2 %*, the same rule the app enforces. |
| Preset Output Power | `number` | Watts. |
| Power Limit | `sensor` | Read-only — see below. |

### Smart linking (`thirdLink`)

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

### High power mode

The output ceiling is 800 W by default and can be raised to 1200 W. The
APsystems app puts a disclaimer in front of that: it "may cause the device
output to exceed regulatory limits for grid connection", with the legal risk
on the operator.

Home Assistant has no confirmation dialog for an entity — a switch is always
one tap — so this is an action instead:

```yaml
action: apsystems_ezhi_local.set_high_power_mode
data:
  enable: true
  acknowledge_regulatory_risk: true   # required only when enabling
```

Lowering the ceiling is refused while the weekly output schedule still has
entries above it. The vendor app silently rewrites those; this integration
tells you which ones are in the way and leaves your schedule alone.

### Safety behaviour

Two writes are refused rather than passed on:

- **"No Battery" mode while a battery is connected** — the "battery access
  conflict" the app warns about. The refusal lifts by itself once the cloud
  stops reporting a battery.
- **Discharge protection below SOC minimum + 2 %** — otherwise the device
  clamps it silently.

### Known limitations

**What ECO actually saves is unmeasured.** Its documented job is shutting down the
off-grid output stage when nothing has drawn from it for an hour — the opposite of
what EPS does with the same stage, which is why the firmware treats the two as
exclusive. An A/B on the development install showed ~17 W of total standby in both
positions, but that does not settle it: a saving can only appear with the off-grid
output up, nothing drawing from it, and the hour elapsed — and since toggling ECO
moves EPS with it, the two positions are not otherwise identical. Measuring the
off-grid stage on its own would settle it.

Two further device-side settings are readable in the cloud config but have no known
write path, and both can make an entity above look more authoritative than it
is:

- **`winter`** — a field in the cloud config whose effect is unclear, and
  which nothing here writes. The app ships translations for a "Winter Adaptive
  Button" saying it would raise the SOC floor to 50 % and discharge protection
  to 65 %, but **no screen in the app uses them**: the key appears in the
  twelve language bundles and in no component, and the field itself is never
  read or written by the app. On the development install `winter` reads "1"
  while the battery has gone down to 52 % — well below the 65 % that text
  describes. So the flag is either inert or unimplemented in this firmware.
  Documented so nobody re-derives it and, as I first did, mistakes a battery
  that simply stopped being discharged for a floor being enforced.
- **The weekly output schedule** (`outputPowerStrategyWeekly`) is read to
  guard the power limit, and never written. `isOPStrategy: 1` does not mean it
  is in effect — in Local mode it is inert: measured at 1125 W output inside a
  window the schedule caps at 50 W.

## Example dashboard

The integration creates 47 entities. `examples/` has a dashboard that sorts
them into something usable — power right now, battery, controls, energy
totals, alarms, history:

| File | Needs |
|------|-------|
| [`examples/dashboard.yaml`](examples/dashboard.yaml) | [Mushroom](https://github.com/piitaya/lovelace-mushroom) and [fold-entity-row](https://github.com/thomasloven/lovelace-fold-entity-row) from HACS |
| [`examples/dashboard-core.yaml`](examples/dashboard-core.yaml) | nothing — built only from cards Home Assistant ships with |

Same layout either way. Without the two custom cards installed, the first file
renders "Custom element doesn't exist" where they would be, so take the second
one if you would rather not install anything.

Settings → Dashboards → Add dashboard → New dashboard from scratch, then paste
the file into the raw configuration editor (pencil → three dots → Raw
configuration editor).

**Both files assume the integration was added with the name `ezhi`.** Replace
that throughout if you used something else. Upgrading from 0.4.0 or earlier?
Entity ids are handed out once, at first registration, so an existing install
keeps the ones it already has — and there the cloud entities and the local
power number carry an extra `apsystems_` (`switch.apsystems_ezhi_backup_power`).
The exact ids for your install are on the device page.

The control section is marked for deletion if you do not use cloud control. It
is not hidden by a conditional card on purpose: the frontend's condition check
reads `hass.states[entity]?.state`, so for an entity that does not exist at all
a `state_not: unavailable` condition evaluates true — the card would appear
exactly when it should not.

## API Endpoints

The integration uses the following local API endpoints:

| Endpoint | Description |
|----------|-------------|
| `/getDeviceInfo` | Device information (ID, type, battery info) |
| `/getOutputData` | Real-time power and energy data |
| `/getAlarm` | Alarm/error status |
| `/getPower` | Current power limit setting |
| `/setPower?p=XXX` | Set the on-grid setpoint. Positive discharges to the grid, negative charges from it. Local system mode only |

Bruno API collection files are included for testing.

Cloud endpoints live under `https://app.api.apsystemsema.com:9223/aps-api-web/api/v2/`.
The `/api/v2` segment is not optional: without it every endpoint answers HTTP
200 with body code 4 "Internal Server Error", which looks like a cloud outage
rather than a wrong path.

## Troubleshooting

- **Cannot connect**: Ensure the inverter is connected to your network. Note that
  the system mode is not the cause: the local API answered in all four modes when
  tested, so a mode other than Local does not explain missing sensor data
- **The setpoint does nothing**: check the system mode. `setPower` is accepted
  and answered with `SUCCESS` in every mode but only acted on in Local
- **During a grid outage** the inverter keeps answering: it runs on the battery,
  stays on Wi-Fi and serves all four endpoints, `getAlarm` included. Measured
  across three outages with no dropped request. So sensors going unavailable is
  not what a power cut looks like — that is a network problem
- **Entities unavailable**: Check if the inverter is powered on and operating
- **Stale data**: Try reducing the update interval in the integration options

## Changelog

### v0.9.0

- **Added:** twenty-four diagnostic entities from `deviceInfo`, which was
  already being read on every poll and had exactly three of its twenty-seven
  fields exposed. Firmware versions, network address, locale, vendor codes, and
  four link flags — including **Cloud Connected** and **Bluetooth Enabled**, the
  two that explain most "why is this transport not working" questions. Six are
  enabled by default; the four identifying ones (`deviceId`, `ssid`, and both
  MAC addresses) are off, because an update should not add those to your
  recorder unasked.
- **Added:** twenty-one diagnostic entities from six identifiers that answer a
  `get` over MQTT and were read nowhere — `light`, `alarm`, `supportFunction`,
  `meterStatus`, `btLock`, `bindDevice`. All disabled by default.
- **Changed:** on local MQTT the whole poll cycle now goes out in **one** round
  of requests instead of three sequential ones. The transport correlates replies
  by id, so any number of reads can be open at once, and the device answers on a
  ~5 s tick — ten identifiers fired together come back in 2.5–3.0 s, where a
  single read takes 5.05 s. Three times the reads therefore cost no more wall
  clock than v0.8.0 did, and the first refresh after startup stays well inside
  its 20 s budget instead of growing towards it. Bluetooth keeps
  the sequential path: it is a serial link, and a parallel gather there would
  push nine requests into one wire.
- **Changed:** `freeRam` is now enabled by default. It is the only diagnostic
  value that moves, which makes a falling trend the early warning for a firmware
  memory leak.
- **Investigated and closed:** `batteryCellData`. The identifier is real — the
  device pushes it — but it does not answer a `get` on either transport, and the
  push payload is empty (`{"cell": [], "cellStatus": 0}`). The name does not
  appear anywhere in the vendor app either (0 hits across 6928 decompiled files,
  against 26–110 for identifiers that do exist). There are no per-cell voltages
  to expose.

### v0.8.0

- **Fixed:** on the local MQTT transport, the seventeen `outputData` sensors
  (DC battery voltage and current, per-string PV, the two extra device
  temperatures, grid voltage and frequency, per-string lifetime energy) were
  never created and would have had no data if they had been. They were gated
  on Bluetooth, on the belief that the inverter only ever *pushes* `outputData`
  and never answers a read for it. That belief was wrong: a `get` with
  identifier `outputData` is answered exactly like `systemMode` is — verified
  against a real device, code 200, 50 fields. Asking also turned out to be the
  more reliable half: the device was not observed pushing at all in two
  captures (150 s, and 190 s on a connection it had just made), and the push
  is known to arrive with five bytes of `pvOriginalData` missing.
- **New:** `Off-Grid Voltage` and `Off-Grid Current`. The off-grid branch had
  only its power until now; these are the exact counterparts of the on-grid
  voltage and battery current sensors.
- **New:** `Uptime` — seconds since the inverter last restarted. Measured, not
  inferred: two reads 75 s apart differed by exactly 75. It is the only way to
  notice that the inverter rebooted, which otherwise leaves the integration
  quietly stranded. Not a `total_increasing` counter on purpose — the drop back
  to zero is the signal, and long-term statistics would smooth it away as a
  counter wrap.
- **New:** ten raw fields from the same reply, exposed under their wire names —
  `batCT`, `cMode`, `rS`, `mode`, `reUpdate`, `metL1`, `metL2`, `metL3`,
  `metDC`, `freeRam`. They are **diagnostic and disabled by default**, and they
  carry no unit, device class or state class. That is deliberate: what these
  fields mean has not been established, and a sensor named "Battery Cycles"
  would be a guess wearing the clothes of a fact, while `batCT` claims nothing.
  Enable one, watch it, and if you work out what it is, it belongs in the
  measured half of the table in `ble_api.py`.
- **Dev:** `requirements-test.txt`. The suite needs `cryptography` (it ships
  with Home Assistant, so it is not a manifest requirement) and could not be
  collected at all without it.

### v0.7.1

- **New:** a **Smart Linking** switch for `thirdLink`, the master switch a
  smart meter hangs off. It exists because the vendor app couples linking to
  zero export — with linking on there, surplus feed-in with demand-driven
  discharge is not offered. The switch refuses while the inverter is in Local
  mode: turning linking on moves the device to Balcony, which would silently
  disable the local power setpoint.
- **Documented:** `thirdLink` is not a boolean. `0` is off, `1` is on with a
  device coupled, `2` is on with nothing coupled — measured on two inverters,
  which is what made the field readable at all. Anything that is not `0` reads
  as on.
- **Documented:** expected alarms that never fire. A user polling `getAlarm`
  once a second saw no flag change when charging to 100 % (`BatHV`/`BatE`
  expected — APsystems support says a warning is raised at 99 %), when cutting
  the on-grid supply all-poles (`ACA`, which the app showed in its own chart),
  or on a battery whose SOC reading is visibly off (`BCC`). A clear flag is
  not evidence that the condition did not occur.

### v0.7.0

- **New:** a third control transport, **local MQTT**. The inverter reaches its
  vendor cloud over MQTT and validates nothing about the broker it lands on, so
  pointing its DNS at a broker on your own network hands over the vendor's own
  control channel — same identifiers, same params, same replies. Selectable in
  the options dialog next to Cloud and Bluetooth. It is the only transport that
  needs no vendor account at all; the trade is that the device has to be
  redirected at the broker, and Home Assistant's MQTT integration has to be
  configured. **The wire format is verified end to end against the device** —
  read the config, change a field, read it back, restore it, with the vendor
  cloud disconnected — but that round trip was driven by hand against a
  mosquitto broker, not by this integration. The protocol is proven; this code
  path has not yet driven the device. Treat it as the newest transport, not the
  most tested one.
- **New:** the WiFi signal sensor now also works on the local MQTT transport —
  `deviceInfo` is answered there on request. The `outputData` sensors stay
  Bluetooth-only: over MQTT that data is only ever pushed, never answered on
  request, so there is no verified read to build them on.
- **Note:** `onOff` still goes over the cloud on this transport. Its MQTT
  payload has not been captured, and that is the one command that takes the
  radio down with it — it is refused rather than guessed at when no cloud
  credentials are configured.

### v0.6.0

- **New:** Bluetooth-only sensors read from the inverter's `outputData` — DC
  battery voltage and current, per-string PV (voltage, current and lifetime
  energy for all three strings, power for the two the reply carries), two extra
  device temperatures, and on-grid voltage and frequency. None of these are in
  the local HTTP API, and they exist only on the Bluetooth transport. A string
  with no module wired reads 0, a real value; hiding it is a dashboard choice,
  not done in the integration. The coordinator data was reshaped to `{config,
  output}` for this, and an `outputData` fetch that fails degrades to an empty
  block instead of taking the control side down.
- **Fixed:** cloud on/off returned code 4001 from the dedicated
  `remote/ezInverter/onOff` endpoint. It now goes over the generic `setRemote`
  channel (`identifier: onOff`), verified on the device — `status: 1` turns it
  off and the radio then goes fully dark. Reactivation is physical only: with
  no PV/DC input, only the battery button wakes it, not a cloud call.
- **New:** `ble_raw_get` diagnostics action — fetches one raw BLE block and
  logs it, for reading fields that are not sensors.
- **Fixed (internal):** the local API client now shares Home Assistant's HTTP
  session instead of opening one per instance and never closing it; a rejected
  `setPower` surfaces (the service raises, the number logs) instead of being
  swallowed; the energy sensors survive an explicit JSON `null` rather than
  aborting the update; Battery Capacity uses the `energy_storage` device class.
- **New:** the control commands can go over Bluetooth instead of the cloud —
  **Configure → Control transport**. Same entities, same safety rules; the
  frames are byte-identical to the vendor app's, pinned against a capture of
  105 messages. The default stays Cloud, so nothing changes without being
  asked for. The cloud credentials are still needed on the Bluetooth path:
  the inverter's radio switches off after 15 minutes idle, and `btOnOff` over
  the cloud is the only unattended way to open that window (edge-triggered —
  0, then 1; writing 1 while it already reads 1 does nothing).

- **Fixed:** the documented sign of the on-grid setpoint was inverted. Positive
  discharges to the grid, negative charges from it — measured, and confirmed
  against the device's own `ogP`/`batP` signs, which the vendor manual does
  define. The wrong version was in `services.yaml` (so it showed in the service
  picker), in both example dashboards and in this file. Anyone who followed it
  charged when they meant to discharge.
- **New:** writing the on-grid power setpoint while the inverter is in any mode
  other than Local now logs a warning. Measured across all four selectable
  modes: the device follows the setpoint only in Local and answers `SUCCESS`
  everywhere, so until now an ignored write was indistinguishable from a
  working one. The write still goes out — the mode reading can be a poll
  interval stale, and blocking on that would be worse than the silence it
  replaces. Needs cloud control configured; without it the mode is unknown and
  nothing is logged.
- **Corrected:** leaving Local mode does not stop the local API. All four
  endpoints answered `SUCCESS` in every mode, so the sensors keep updating.
  What Local mode gates is the one write, not the reads. The old claim was in
  the README, the select entity's docstring and its `local_mode_note`
  attribute.
- **Corrected:** `BCC` is undocumented rather than absent — the vendor manual
  lists 19 alarm fields as of V1.3 (2026-02-04), the device sends 20. The
  README now names the evidence instead of asserting the mapping.

### v0.5.1

Documentation only — no code changes, nothing to reconfigure.

- **Corrected:** the `winter` flag does not raise the effective SOC floor. That
  claim came from correlating a battery that had not gone below 53 % with a flag
  set to 1. The daily minima actually scatter from 52 % to 83 %, which is a
  battery that stopped being discharged, not one hitting a floor — and the flag's
  own text promises discharge protection at 65 %, which the same install went
  below. The strings exist in all twelve language bundles but no screen uses them,
  and the app never reads or writes the field.
- **ECO** now says what it is for: the opposite policy to EPS for the same output
  stage, which is why the firmware treats them as exclusive. The earlier claim
  that it does not reduce standby draw was more than one A/B supports, and is now
  stated as unresolved.

### v0.5.0

- **Fixed:** every entity set `has_entity_name`, so the device name is no
  longer baked into the entity name as well — the frontend showed
  "EZHI APsystems EZHI Backup Power" where it puts device and entity side by
  side
- New installs get uniform entity ids: the cloud entities and the local power
  number lose their extra `apsystems_` prefix (`switch.ezhi_backup_power`, not
  `switch.apsystems_ezhi_backup_power`)
- **Existing installs are unaffected.** Entity ids are assigned once, at first
  registration; a later name change only updates the registry's stored name.
  Automations, dashboards and history keep working — the example dashboards
  now match a fresh install, so check the device page for your own ids

### v0.4.0

- **New: optional cloud control** — on/off, system mode, backup power (EPS),
  ECO, SOC limits, discharge protection and preset output power, none of which
  exist in the local API
- **New:** `set_high_power_mode` action, gated behind an explicit
  acknowledgement of the vendor's regulatory disclaimer
- Cloud runs on its own coordinator: a cloud failure cannot take the local
  sensors down, and dead credentials trigger a reauth prompt
- 88 unit tests for the cloud client, no network and no Home Assistant needed
- Cloud login with the EMA account username and password — no HTTPS proxy
  capture needed
- Example dashboard in `examples/`, in a HACS and a built-in-cards variant
- Both actions take an optional `device_id`; with several inverters set up they
  refuse rather than silently pick one
- Minimum Home Assistant version raised to 2024.11

### v0.3.0

- **New:** three alarm sensors the local `getAlarm` endpoint reports but the
  integration ignored — SOC Calibration Needed (`BCC`), Battery Access Conflict
  (`BCI`) and Voltage Reset Protection (`VRP`)
- On firmware that does not send them they read `unknown` rather than "no
  problem", so an absent field is never reported as an all-clear
- Manifest version corrected: it still said 0.2.0 while the changelog below
  claimed 0.2.1, so HACS never saw that release

### v0.2.1

- **New:** Added brand folder with icon.png and logo.png
- Support for Home Assistant 2026.3+

### v0.2.0
- **New: Battery Status sensor** - Shows Idle/Charging/Discharging/Fault/Shutdown/No Communication
- **New: 17 binary alarm sensors** - Monitor all inverter alarms and errors
- **New: Separate scan intervals** - Fast polling for power data (default: 5s), slow polling for alarms/device info (default: 60s)
- **New: Device Info Panel** - Shows firmware version, serial number, and configuration URL in HA device panel
- **New: Options Flow** - Change scan intervals after setup without reconfiguring
- **New: German translations** - Full German language support
- **Fixed:** `batS` (Battery Status) was read from wrong JSON level in API response
- **Fixed:** Device info now updates periodically (not just once at startup)

### v0.1.2
- Initial release with basic sensor and power control functionality

## License

This project is released under the MIT License.

---

*This integration is based on the [APsystems EZ1 API Home Assistant integration](https://github.com/SonnenladenGmbH/APsystems-EZ1-API-HomeAssistant) by Sonnenladen GmbH.*
