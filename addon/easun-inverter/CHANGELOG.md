# Changelog

## [0.1.1] - 2025-11-01
### Fixed
- Keep the add-on running: retry opening the serial port on failure and continue on read errors.
- Toggle DTR/RTS on port open to improve wake-up on some adapters.

## [0.1.2] - 2025-11-01
### Added
- New SVG icon for the add-on UI.

### Fixed
- QPIGS parsing aligned with PI30 protocol (21 tokens). Correct field order and types; publish standard AC input/output, battery, PV and status metrics.

## [0.1.0] - 2025-10-31
### Added
- Initial add-on: EASUN/Voltronic inverter over RS232/USB.
- QPIGS polling and MQTT discovery/state publishing.
- Auto MQTT credentials via Supervisor discovery.
- AppArmor enabled; UART-only permissions.
