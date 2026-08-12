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

### Bluetooth-only sensors (outputData)

On the **Bluetooth** control transport (see *Cloud Control → Control
transport*) the inverter's `outputData` payload carries readings the local
HTTP API does not expose — the DC battery, grid quality and per-string PV.
They are created only on that transport and read `unavailable` on the cloud
transport, where the payload is not fetched.

| Entity | Description | Unit |
|--------|-------------|------|
| Battery Voltage | DC battery voltage | V |
| Battery Current | DC battery current, signed. The charge/discharge sign is unverified and taken raw, so history is not distorted by a guess | A |
| PV1 Voltage / Current / Power | First PV string | V / A / W |
| PV1 Total Energy | First PV string, lifetime (`total_increasing`) | kWh |
| Device Temperature 2 / 3 | Two further internal temperatures beside `devTemp` | °C |
| Grid Voltage | On-grid voltage | V |
| Grid Frequency | On-grid frequency | Hz |

PV2 and PV3 are in the payload but **not** exposed: on the development install
no module is wired to those DC inputs, so they read 0. PV1 is kept as it may
be the off-grid input — to be confirmed in daylight. `outputData` has about 35
fields in all; the rest (`batCT`, `cMode`, SmartMeter phases, housekeeping)
have unclear or install-specific meaning and stay reachable through
`ble_raw_get` rather than being turned into sensors on a guess.

`apsystems_ezhi_local.ble_raw_get` is a diagnostics action: it fetches one raw
BLE block (default `outputData`) and logs the full reply at WARNING, for
reading fields that are not sensors and for reverse-engineering the raw frames.
Bluetooth transport only.

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

### Control transport: cloud or Bluetooth

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

### Entities

| Entity | Type | Notes |
|--------|------|-------|
| Inverter On | `switch` | **One-way from HA.** Once off, the inverter drops off the cloud's MQTT link and cannot be turned back on remotely — it needs PV/DC input or a 3 s press on the battery button. |
| System Mode | `select` | Balcony Storage, Portable, AI, Local, No Battery. These are operating scenarios, not the Local API toggle: the local API answered in every one of them when tested, and a user on the vendor forum polls it while running Portable. ~~Per APsystems support, what Portable switches off is the alarms.~~ **Measured false:** pulling the grid plug in Portable raised `ACA` on the local API. It only stood for about two seconds, which is the likelier reason nobody sees these alarms. See the alarm note above. |
| Backup Power (EPS) | `switch` | Mutually exclusive with ECO — enabling one clears the other in a single write. |
| ECO Mode | `switch` | The opposite policy to EPS for the same output stage, which is why the firmware treats them as exclusive: EPS keeps the off-grid output armed, ECO drops it after an hour with no load. Recovery is via the AC output switch. An A/B here measured ~17 W of standby either way — but see below. |
| SOC Minimum / Maximum | `number` | Percent. |
| Discharge Protection | `number` | Refused below *SOC minimum + 2 %*, the same rule the app enforces. |
| Preset Output Power | `number` | Watts. |
| Power Limit | `sensor` | Read-only — see below. |

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

### v0.6.0

- **New:** Bluetooth-only sensors read from the inverter's `outputData` — DC
  battery voltage and current, PV1 voltage/current/power and lifetime energy,
  two extra device temperatures, and on-grid voltage and frequency. None of
  these are in the local HTTP API. They exist only on the Bluetooth transport.
  PV2/PV3 are in the payload but not exposed (no module wired on the
  development install); PV1 is kept as a possible off-grid input, to be
  confirmed in daylight. The coordinator data was reshaped to `{config,
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
