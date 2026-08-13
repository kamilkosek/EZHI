# Changelog

### v1.1.0

- **Fixed:** `onOff` was handed to the cloud client on the local MQTT transport
  and could therefore never arrive. A redirected inverter is not connected to
  the vendor cloud: the call answered HTTP 200 and the switch never moved,
  measured on a live install. It now goes out over MQTT like every other
  command, using the frame the vendor app sends over Bluetooth — captured off
  an iOS HCI snoop and byte-verified in August. **Turning the inverter off
  takes its radio down with it; only a 3 s press on the battery button returns
  it.** Verified end to end: off, network dead 25 s later, one button press,
  back within three minutes.
- **Changed:** this transport now needs no cloud client for anything. `onOff`
  was the last thing it borrowed one for, and the parameter is gone from the
  constructor.
- **Fixed:** a failure to build the transport fell back to the cloud on an entry
  that had credentials — silently, while the warning said the control layer had
  been skipped. That fallback could never work, for the same reason `onOff`
  could not.
- **Fixed:** a broker that comes up after Home Assistant left the transport
  unsubscribed for good, and every poll failed until the entry was reloaded.
  Both on the same host is the ordinary case. A request now subscribes itself,
  still before it publishes, and stops doing so once the entry has unloaded.
- **New:** choosing local MQTT asks the inverter a question before saving and
  refuses with a reason if it does not answer. That precondition — the device
  having been redirected at your broker — is the one setting Home Assistant
  cannot see, and getting it wrong used to save cleanly and then time out on
  every poll. A real read, not a broker ping: a broker with no inverter behind
  it looks perfectly healthy from this side.
- **New:** a diagnostics download. It redacts the tokens, the account name, the
  device id and serial, both MAC addresses, the SSID and the local address —
  recursively, because the fields worth having sit one and two levels down in
  the device's replies.
- **Fixed:** the local sensors wrote `0` on a parse error — power, temperature,
  SoC, SoH, capacity. A fabricated 0 W is indistinguishable from an inverter
  standing still and lands in the recorder as a measurement. They report
  unknown now, as the energy sensors in the same file always have.
- **Fixed:** write timeouts said "the EZHI cloud did not answer" whatever the
  transport, and a timeout waiting for Home Assistant's MQTT integration read
  as "the inverter did not answer over MQTT" — a broker problem, with the
  device blamed.
- **Changed:** the local coordinator no longer carries a copy of
  `DataUpdateCoordinator._async_refresh`. Fifty-nine lines of Home Assistant
  internals, for one behaviour `UpdateFailed` already provides — and a silent
  break waiting for the next Home Assistant release.
- **New:** CI, so the whole suite runs. One module needs Home Assistant
  installed and therefore never ran locally.

### v1.0.0

- **Changed:** the redirect section no longer claims a DNS rewrite is the only
  way to reach the inverter's MQTT link. It is not — a static host route plus a
  DNAT rule redirects at the packet rather than at the name, and that approach
  binds the rule to the inverter's own address, so the vendor app keeps working
  on your home network. The table now lists four mechanisms and, for each,
  whether you can undo it while away from home. That last column is a selection
  criterion, not a detail: a router you cannot automate puts the switch behind a
  login you cannot reach from outside.
- **New:** [ezhi-reroute](https://github.com/Glenbeulah/ezhi-reroute), a Home
  Assistant add-on that holds the DNAT rule for the routing approach. It detects
  the inverter, resolves the vendor endpoint itself — the address is regional,
  so a hardcoded one is right in exactly one part of the world — and reports at
  its packet counter whether your router is actually forwarding.
- **New:** a LICENSE file. The MIT grant was in this README from the first
  commit but never carried as a file, so GitHub reported the project as
  unlicensed.
- **Fixed:** the test fixtures carried a real device serial, MAC addresses, a LAN
  address and a WiFi SSID. Replaced with placeholders — only their shape matters
  to the tests.
- **New:** a German README ([README.de.md](README.de.md)). The integration has
  shipped German translations since before this fork; the documentation had
  not caught up.
- **Changed:** the README was 914 lines and nobody read it. Split to 468: the
  alarm prose, the redirect mechanics, the example dashboard, the API endpoints
  and this changelog now live in their own files, each linked from where it used
  to be. The entity tables, the limitations and the transport summary stay in the
  README, because those are what a reader needs before deciding anything.
- **Documented and pinned:** what an installation *without* vendor credentials
  gets. The control layer is skipped whole — no cloud, Bluetooth or MQTT
  entities are created at all — and the full local HTTP API set remains. This
  always held, but the README said only "nothing about the integration changes",
  which no longer answers the question now that three transports exist. The
  condition now lives in `const.wants_control_layer()` where it can be tested
  without Home Assistant, and nine tests cover it, including that Bluetooth
  without credentials stays off and that local MQTT is the one deliberate
  exception.

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
