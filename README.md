# EASUN Inverter Add-on Repository

This repository provides a Home Assistant add-on to read data from EASUN/Voltronic inverters via serial (RS232/USB) and publish metrics to MQTT with Home Assistant discovery.

## Add-ons

- EASUN Inverter (`addon/easun-inverter`) – v0.1.0

## Quick Start

1. Add this repository to Home Assistant Add-on Store:
   https://github.com/Smitacek/easun-inverter-addon
2. Install "EASUN Inverter" and configure:
   ```yaml
   port: "/dev/serial/by-id/…"
   baudrate: 2400
   timeout: 3
   read_interval: 30
   ```
3. Start the add-on and check logs; entities will appear via MQTT discovery.

## License

MIT

