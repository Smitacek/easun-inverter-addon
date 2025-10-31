# EASUN Inverter Add-on

Simple Home Assistant add-on to read data from an EASUN/Voltronic inverter (PI protocol over RS232/USB) and publish metrics to MQTT with Home Assistant discovery.

## Features
- Serial RS232/USB access to inverter (default 2400 baud)
- Periodic QPIGS snapshot publishing
- MQTT Discovery for common sensors (grid, AC output, battery, PV)
- Auto MQTT credentials via Supervisor (Mosquitto), manual override
- 3-decimal voltage display precision in HA UI

## Configuration

```yaml
port: "/dev/ttyUSB0"       # Prefer /dev/serial/by-id/... if available
baudrate: 2400
timeout: 3
prefer_by_id: true

mqtt_host: "core-mosquitto"
mqtt_port: 1883
mqtt_username: ""
mqtt_password: ""
read_interval: 30
log_level: warning
```

## Security
- `apparmor: true`, `uart: true` only; no privileged or host networking.

## Notes
- Mapping for QPIGS fields is in `inverter_map.json` (ordered list). Adjust as needed for your inverter model.
- This is an initial version; additional queries (QDI, etc.) can be added.

