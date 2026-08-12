# API endpoints of the local HTTP API

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

