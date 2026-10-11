# EASUN Inverter Add-on

Reads PI30 QPIGS telemetry over an explicitly configured RS232/USB serial path and publishes Home Assistant MQTT sensors. Requires Home Assistant 2025.10 or later.

## Configuration and recovery

```yaml
port: "/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_EXAMPLE-if00-port0"
baudrate: 2400
timeout: 3
prefer_by_id: true
mqtt_host: "core-mosquitto"
mqtt_port: 1883
mqtt_username: ""
mqtt_password: ""
read_interval: 10
log_level: warning
```

Use the inverter adapter's exact stable by-id path. The reader retries that identity after failed opens, transport errors, timeouts or invalid required frames. It never chooses another adapter. Replacing an adapter with a different serial number requires changing the configured path. `prefer_by_id` only resolves a configured tty to a matching symlink; it does not select a fallback device.

Blank manual credentials use the MQTT service credentials exported by `run.sh`. A nonempty manual username selects the manual username/password pair. The broker reconnects automatically, including when unavailable at startup. The standalone probe requires `--port`; do not run it while the add-on owns the same serial device.

Each response must have the PI start marker, CR terminator and escaped CRC. Supported QPIGS layouts have 21 fields (or an additional numeric extension). All required fields and binary flags are validated; corrupt or partial snapshots are not published. Optional NAK commands are skipped until process restart. Other invalid optional responses are omitted and retried on their schedule. QMOD/PV2 run each healthy poll; Q1 runs at most once per minute; firmware/settings are queried once per day and validated static values replay on healthy polls. Optional I/O errors also close the handle for the next poll.

## Home Assistant sensors and history

Entity names describe only the measurement; HA adds the device name. Single-inverter mode uses `easun_inverter` as the canonical device identity. The existing `unique_id`, canonical discovery topics and default entity IDs are retained, so existing entity-registry references need no rename. `default_entity_id` replaces the removed `object_id` discovery option.

| Quantity | Unit | device_class | state_class |
| --- | --- | --- | --- |
| AC/DC voltage | V | voltage | measurement |
| Charging / discharging / reported PV current | A | current | measurement |
| AC active and PV power | W | power | measurement |
| AC apparent power | VA | apparent_power | measurement |
| Frequency | Hz | frequency | measurement |
| Battery state of charge | % | battery | measurement |
| Output load | % | — | measurement |
| Temperature | °C | temperature | measurement |
| QPIRI settings | V | voltage | —, diagnostic |
| Firmware, serial, errors | — | — | —, diagnostic |
| Last successful required read | — | timestamp | —, diagnostic |
| Measurement age | s | duration | —, diagnostic |

`battery_capacity_percent` means state of charge, not capacity in Ah and not humidity. Charging and discharging currents are separate nonnegative quantities reported by PI30; no sign inversion or inferred correction is applied. PV current is the reported protocol field; its precise measurement point can vary by firmware and it is not used to derive power. Zero is published only when actually reported in a validated response. Missing measurements are omitted. Texts and error counters do not claim measurement/total statistics.

Availability requires both the process MQTT connection and a successful required inverter read. Health diagnostics remain visible while that inverter is offline. Measurements have `expire_after`, with a minimum of 90 seconds and an allowance for configured poll times and sequential reads. Q1/text/static-info expiry has a minimum of 300 seconds; firmware/settings replay does not re-read the serial port. States are nonretained; only discovery and availability are retained. Unsupported firmware sensors therefore become unavailable instead of retaining NAK text as a valid version.

Instantaneous numeric sensors enable Recorder's long-term min/max/mean statistics. They are not energy counters and cannot be used directly as kWh sources in the Energy dashboard. This add-on does not invent integrated energy, reset semantics or persistence. Existing history remains unchanged; missing statistics from before correct metadata cannot be reconstructed.

### Multi-inverter identity and migration from 0.2.2

Use distinct, stable ASCII names for configured inverters; names are normalized to lowercase letters/digits/underscores. Without a name, the ID uses a SHA-256 prefix of the exact configured port. Duplicate normalized identities are rejected. A configured name remains stable when its adapter path changes; renaming that identity creates new entities. Three-phase totals require all enabled configured inverters to have a valid current snapshot. PV totals additionally require a valid second-channel reading or an explicit QPIGS2 NAK from every contributor; missing PV2 readings are not converted to zero.

Version 0.2.2 additionally advertised malformed duplicate device topics derived from serial paths and aggregator entities on physical inverters. Version 0.2.3 stops advertising those duplicates in single mode. It does **not** automatically delete retained discovery or edit HA's registry/history. Before cleanup, export old EASUN discovery definitions and inventory references in dashboards, automations and statistics. Keep canonical `homeassistant/sensor/easun_inverter/<key>/config` entries in single mode. After confirming healthy canonical entities, remove only backed-up obsolete duplicate definitions by publishing empty retained configs to their exact topics. If duplicate entities were used, migrate their references deliberately; history under a changed unique_id is not merged. No cleanup should erase canonical history. In multi mode, map old path-derived IDs to the chosen stable names before removing their obsolete definitions.

## Verification

Install `requirements.txt` and pytest in a test environment, then run `pytest`. Serial tests use Linux pseudo-terminals and require no inverter. Broker tests skip unless `EASUN_TEST_BROKER_CONTAINER` names a disposable local `easun-audit-*` Mosquitto container listening on `127.0.0.1:18884`; these tests intentionally restart/stop/start that container. Never point them at production.

## References

- [Home Assistant MQTT sensor discovery, expiry and naming](https://www.home-assistant.io/integrations/sensor.mqtt/)
- [Home Assistant sensor classes and statistics](https://developers.home-assistant.io/docs/core/entity/sensor/)
- [PI30 field definitions and reference response](https://github.com/jblance/mpp-solar/blob/master/mppsolar/protocols/pi30.py)
- [Escaped PI CRC reference](https://github.com/jblance/mpp-solar/blob/master/mppsolar/protocols/protocol_helpers.py)

The legacy `inverter_map.json` is not used to reinterpret QPIGS field order; parsing uses the explicit PI30 schema in `inverter.py`.
