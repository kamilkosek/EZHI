# APsystems EZHI - Home Assistant Integration

*[Deutsche Fassung](README.de.md)*

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
- **Cloud Control (optional)**: On/off, system mode, backup power (EPS), ECO, SOC limits and more — none of which exist in the local API. Genuinely optional: with no credentials the control layer is skipped whole and you keep the full local feature set, which is also what an existing installation gets on upgrade without changing anything.

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

Each alarm sensor carries the vendor's own text as attributes — `cause` and
`suggested_action`, plus `vendor_name` and `alarm_code` — so a sensor that goes
to *Problem* also tells you what the app would have told you. German if Home
Assistant is set to German, otherwise English. They are excluded from the
recorder, being static.

→ **[docs/alarms.md](docs/alarms.md)** has all twenty codes in full, plus two
things to know before building an automation on them: some alarms are transients
that the 60 s poll will miss, and some expected alarms never fire at all.
[docs/alarms.json](docs/alarms.json) is the machine-readable copy for anyone
reading `getAlarm` from a script.

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

### Without credentials

**Leave the credential fields empty and you get the integration as it was before
any of this existed.** The entire control layer is skipped, so none of the cloud,
Bluetooth or MQTT entities are created — absent, not sitting permanently
unavailable. What remains is the complete local HTTP API set: every sensor in the
table above, the twenty alarm binary sensors, and `setPower`.

That is also what happens by default. An entry that never chose a transport
resolves to **cloud**, and cloud without credentials means no control layer at
all — so an installation upgrading into this version keeps behaving exactly as it
did, without touching a single setting.

Two consequences worth stating, because neither is obvious:

- **Bluetooth without credentials also stays off.** It is not a cloud-free mode:
  the radio switches itself off after 15 minutes of idleness, and the only
  unattended way to reopen it is the cloud call `btOnOff`. A Bluetooth transport
  with no account would be one that cannot recover on its own.
- **Local MQTT is the exception, deliberately.** It is the one transport that
  needs no vendor account, so choosing it opens the control layer on its own.
  Choosing it is an explicit act — nothing falls back to it.

This is pinned by tests (`tests/test_transport_choice.py`) rather than left to
care: it is the majority installation, and the kind of thing a later refactor
breaks without anyone noticing until somebody's entities disappear.

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

| Transport | What it needs | What you get |
|---|---|---|
| **Cloud** | A vendor account | On/off, system mode, backup power, ECO, SOC limits |
| **Bluetooth** | An adapter or ESPHome proxy in range — **and** the cloud credentials, which stay in use to reopen the radio window | The same commands without a round trip to a vendor server, plus the `outputData` sensors |
| **Local MQTT** | No vendor account at all — but the inverter has to be redirected at a broker you run | Everything Bluetooth gives and more: the whole poll in one round trip, and the diagnostic reads |

**Local MQTT is the only transport that needs no vendor account.** The inverter's
link to its cloud *is* MQTT, and it validates nothing about the broker it lands
on — no certificate pinning, no mutual TLS. Point its traffic at a broker on your
own network and you have the vendor's own control channel, with no vendor server
in the path.

The catch cannot be engineered away: **the inverter has no setting for its broker
address.** The hostname is fixed in the firmware, so the redirect has to happen in
your network — at the name (DNS) or at the packet (routing).

> **[ezhi-reroute](https://github.com/Glenbeulah/ezhi-reroute)** is a Home
> Assistant add-on that does the routing variant for you. It detects the
> inverter, resolves the vendor endpoint itself — the address is regional, so a
> hardcoded one is right in exactly one part of the world — prints the exact
> static route to enter in your router, and then tells you at its packet counter
> whether your router is actually forwarding. Installable as an add-on
> repository; see its DOCS for the blackhole to avoid.

→ **[docs/local-control.md](docs/local-control.md)** covers the four redirect
mechanisms and, for each, whether you can undo it while away from home — which is
a selection criterion, not a detail. It also has the broker's requirements and
the bridging-broker option that keeps the vendor app working alongside.

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
(Shelly, EcoTracker) hangs off. Worth having here because **the app couples the
two**: turn linking on there and it will only let you run zero export, never
surplus feed-in with demand-driven discharge. Toggling the master from Home
Assistant leaves that choice to you.

**It cannot be combined with Local mode.** Turning linking on moves the inverter
to Balcony mode, and Local is the only mode where a local `setPower` setpoint is
obeyed — so the switch refuses rather than letting that happen quietly.

→ **[docs/local-control.md](docs/local-control.md#smart-linking-thirdlink-in-full)**
for the field's three values (it is not a boolean) and what is still untested.

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

→ **[docs/dashboard.md](docs/dashboard.md)** — a Lovelace view covering the
common entities, ready to paste.

## API Endpoints

→ **[docs/api.md](docs/api.md)** — the local HTTP API's endpoints, for reading
the inverter from something other than this integration.

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

→ **[CHANGELOG.md](CHANGELOG.md)** — every release since v0.1.2, with what was
measured and why each change was made.

## License

This project is released under the MIT License.

---

*This integration is based on the [APsystems EZ1 API Home Assistant integration](https://github.com/SonnenladenGmbH/APsystems-EZ1-API-HomeAssistant) by Sonnenladen GmbH.*
