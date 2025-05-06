# APsystems EZHI - Home Assistant Integration

## Overview

This Home Assistant integration allows you to monitor and control your APsystems EZHI inverter via the local API. It provides sensors for real-time data and controls for power settings.

## Features

- **Monitor PV Power & Energy**: Track photovoltaic power generation and total energy production.
- **Battery Monitoring**: View battery state, charge/discharge rates, and temperature.
- **Grid Interaction**: Monitor power flow to and from the grid.
- **Power Control**: Set the maximum power output of your inverter.

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

## Available Entities

### Sensors

- **Photovoltaic Power**: Current power generation from solar panels (W)
- **Photovoltaic Energy**: Total energy generation from solar panels (kWh)
- **Battery Power**: Current battery charge/discharge rate (W)
- **Battery State of Charge**: Current battery charge percentage (%)
- **Battery State of Health**: Battery health percentage (%)
- **Battery Temperature**: Battery temperature (°C)
- **Battery Total Charge Energy**: Total energy charged to the battery (kWh)
- **Battery Total Discharge Energy**: Total energy discharged from the battery (kWh)
- **On-Grid Power**: Current power flow to/from the grid (W)
- **On-Grid Output Energy**: Total energy output to the grid (kWh)
- **On-Grid Input Energy**: Total energy input from the grid (kWh)
- **Off-Grid Power**: Current power flow to/from off-grid loads (W)
- **Off-Grid Output Energy**: Total energy output to off-grid loads (kWh)
- **Off-Grid Input Energy**: Total energy input from off-grid sources (kWh)
- **Device Temperature**: Inverter temperature (°C)

### Controls

- **Max Output Power**: Set the maximum power output of the inverter (W)

## Troubleshooting

- Ensure the inverter is connected to your network
- Verify that local mode is enabled in the APsystems app
- Check that the IP address is correct
- Ensure the inverter is powered on and operating normally

## License

This project is released under the MIT License.

---

*This integration is based on the [APsystems EZ1 API Home Assistant integration](https://github.com/SonnenladenGmbH/APsystems-EZ1-API-HomeAssistant) by Sonnenladen GmbH.*
