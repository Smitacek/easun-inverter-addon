# Changelog

## [0.2.1] - 2025-11-01
### Fixed
- Logging and startup: handle single vs. multi-inverter configs without referencing deprecated cfg.port/cfg.baudrate.
- Minor discovery/version string updates.

## [0.2.2] - 2025-11-01
### Added
- Legacy base topics publishing for first inverter (backward compatibility with earlier entity names).
- icon.png added for Add-on Store (in addition to SVG).

### Fixed
- Avoid UnboundLocalError when MQTT is disconnected (define device id per inverter before use).

## [0.2.0] - 2025-11-01
### Added
- Multi-inverter mode: per-inverter MQTT discovery/state and per-device availability.
- Optional 3-phase aggregator (sum of active/apparent/PV power) when phases L1/L2/L3 present.
- Firmware/Serial publishing: QVFW/QVFW2/QVFW3 and QSID/QID as info sensors per inverter.

### Changed
- Stage set to stable.

## [0.1.1] - 2025-11-01
### Fixed
- Keep the add-on running: retry opening the serial port on failure and continue on read errors.
- Toggle DTR/RTS on port open to improve wake-up on some adapters.

## [0.1.2] - 2025-11-01
### Added
- New SVG icon for the add-on UI.

### Fixed
- QPIGS parsing aligned with PI30 protocol (21 tokens). Correct field order and types; publish standard AC input/output, battery, PV and status metrics.

## [0.1.3] - 2025-11-01
### Changed
- Align displayed and discovery software version strings to 0.1.3.

## [0.1.4] - 2025-11-01
### Added
- QMOD: publish inverter mode (code + human-readable).
- Q1: publish SCC/inverter/battery/transformer temperatures, SCC charge power, sync frequency, and charge stage.
- QPIRI: publish selected battery settings (recharge/under/bulk/float voltages).
- PV2 (if supported): publish PV2 current/voltage/power via QPIGS2.

### Changed
- Schedule periodic polling: Q1 every ~30s (or 2× read interval), QPIRI at start and then daily.

## [0.1.0] - 2025-10-31
### Added
- Initial add-on: EASUN/Voltronic inverter over RS232/USB.
- QPIGS polling and MQTT discovery/state publishing.
- Auto MQTT credentials via Supervisor discovery.
- AppArmor enabled; UART-only permissions.
