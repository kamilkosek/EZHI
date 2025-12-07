# APsystems EZHI - Home Assistant Integration

## Overview

This Home Assistant integration allows you to monitor and control your APsystems EZHI inverter via the local API. It provides sensors for real-time data, alarm monitoring, and controls for power settings.

## Features

- **Monitor PV Power & Energy**: Track photovoltaic power generation and total energy production.
- **Battery Monitoring**: View battery state, charge/discharge rates, temperature, and status.
- **Grid Interaction**: Monitor power flow to and from the grid.
- **Alarm Monitoring**: Get notified about system errors and warnings via 17 binary sensors.
- **Power Control**: Set the maximum power output of your inverter.
- **Separate Scan Intervals**: Configure fast polling for power data and slower polling for alarms/device info.
- **Device Info Panel**: View firmware version, serial number, and direct link to inverter API.
- **Multi-language Support**: English and German translations included.

## Prerequisites

Before installing this integration, you need to:

1. Ensure your APsystems EZHI inverter is connected to your local network
2. Activate local mode on the inverter through the APsystems app
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

### Controls

- **Max Output Power**: Set the maximum power output of the inverter (-1200W to +1200W)

## API Endpoints

The integration uses the following local API endpoints:

| Endpoint | Description |
|----------|-------------|
| `/getDeviceInfo` | Device information (ID, type, battery info) |
| `/getOutputData` | Real-time power and energy data |
| `/getAlarm` | Alarm/error status |
| `/getPower` | Current power limit setting |
| `/setPower?p=XXX` | Set power limit |

Bruno API collection files are included for testing.

## Troubleshooting

- **Cannot connect**: Ensure the inverter is connected to your network and local mode is enabled
- **Entities unavailable**: Check if the inverter is powered on and operating
- **Stale data**: Try reducing the update interval in the integration options

## Changelog

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
