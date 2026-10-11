#!/usr/bin/env python3
import hashlib
import logging
import re
import signal
import sys
import termios
import time
from datetime import datetime, timezone

from addon_config import get_config, get_enabled_inverters
from inverter import Inverter
from mqtt_helper import InverterMQTT, VERSION


def setup_logging(level='INFO'):
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO),
                        format='[%(levelname)s] %(message)s', stream=sys.stdout)


def device_id(base, config, single):
    if single:
        return base
    # Names are user-assigned stable device identities. A port-derived fallback
    # uses the exact configured path; no serial-device enumeration or guessing.
    if config.name and config.name != config.port:
        suffix = re.sub(r'[^a-z0-9_]+', '_', config.name.lower()).strip('_')
        if not suffix:
            raise ValueError('Inverter name must contain ASCII letters or digits')
    else:
        suffix = hashlib.sha256(config.port.encode()).hexdigest()[:12]
    return f'{base}_{suffix}'


class DeviceReader:
    def __init__(self, config, inverter, device_id):
        self.config, self.inverter, self.device_id = config, inverter, device_id
        self.last_success = None
        self.errors = self.consecutive_errors = 0
        self._last_error_log = None
        self._next_extended = self._next_static = 0
        self._static_data = {}

    def failed(self, exc, now):
        self.inverter.close()
        self.errors += 1
        self.consecutive_errors += 1
        if self._last_error_log is None or now - self._last_error_log >= 60:
            logging.warning('%s read failed (%s); reopening configured port next poll; consecutive errors=%s',
                            self.config.name, exc, self.consecutive_errors)
            self._last_error_log = now

    def read(self, now=None):
        try:
            if not self.inverter.is_open:
                self.inverter.open()
            data = self.inverter.read_snapshot()
            if not data:
                raise ValueError('Empty QPIGS snapshot')
        except (OSError, ValueError, termios.error) as exc:
            self.failed(exc, time.time() if now is None else now)
            return {}
        self.last_success = time.time() if now is None else now
        if self.consecutive_errors:
            logging.info('%s recovered after %s failed polls', self.config.name, self.consecutive_errors)
        self.consecutive_errors = 0
        logging.debug('%s QPIGS: %s', self.config.name, data)
        return data

    def optional(self):
        now = time.time()
        data = {}
        try:
            data.update(self.inverter.query_qmod())
            data.update(self.inverter.query_pv2())
            if now >= self._next_extended:
                self._next_extended = now + 60
                data.update(self.inverter.query_q1())
            if now >= self._next_static:
                self._next_static = now + 24 * 3600
                self._static_data.update(self.inverter.query_fw_sn())
                self._static_data.update(self.inverter.query_qpiri())
        except (OSError, ValueError, termios.error) as exc:
            self.failed(exc, now)
        data.update(self._static_data)
        return data

    def diagnostics(self):
        now = time.time()
        return {
            'last_success': datetime.fromtimestamp(self.last_success, timezone.utc).isoformat() if self.last_success is not None else None,
            'measurement_age_s': max(0, now - self.last_success) if self.last_success is not None else None,
            'read_errors': self.errors,
            'consecutive_read_errors': self.consecutive_errors,
        }


def aggregate_data(snapshots, configs, unsupported):
    totals = {
        'total_active_power_w': sum(d['ac_output_active_power_w'] for d in snapshots),
        'total_apparent_power_va': sum(d['ac_output_apparent_power_va'] for d in snapshots),
        'phases': ','.join(sorted({ic.phase for ic in configs if ic.phase})),
    }
    if all('pv2_input_power_w' in d or 'QPIGS2' in absent for d, absent in zip(snapshots, unsupported)):
        totals['total_pv_power_w'] = sum(d['pv_input_power_w'] + (d['pv2_input_power_w'] if 'pv2_input_power_w' in d else 0) for d in snapshots)
    return totals


def main():
    cfg = get_config()
    setup_logging(cfg.log_level)
    logging.info('EASUN Inverter Add-on v%s', VERSION)
    configs = get_enabled_inverters(cfg)
    if not configs:
        raise ValueError('No enabled inverters configured')
    single = not cfg.multi_inverter_mode
    ids = [device_id(cfg.device_id, ic, single) for ic in configs]
    if len(set(ids)) != len(ids):
        raise ValueError('Inverter names must identify distinct devices')
    readers = [DeviceReader(ic, Inverter(ic.port, baudrate=ic.baudrate, timeout=ic.timeout), did)
               for ic, did in zip(configs, ids)]
    # Includes worst-case sequential required retries and initial optional queries.
    expiry = max(90, 3 * cfg.read_interval + int(sum(12 * (ic.timeout + 0.2) for ic in configs)))
    mqtt = InverterMQTT(cfg.mqtt_host, cfg.mqtt_port, cfg.mqtt_username, cfg.mqtt_password,
                        device_id=cfg.device_id, expire_after=expiry)
    aliases = {ids[0]: cfg.device_id} if not single and cfg.legacy_base_topics else {}
    aggregate_id = f'{cfg.device_id}_3phase' if cfg.group_3phase and {ic.phase for ic in configs} >= {'L1','L2','L3'} else None
    for did in set(ids) | set(aliases.values()) | ({aggregate_id} if aggregate_id else set()):
        mqtt.register_device(did)
    stopped = False

    def stop(signum, frame):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    mqtt.connect(timeout=10)
    try:
        while not stopped:
            if mqtt.connected and mqtt.discovery_needed:
                mqtt.discovery_needed = False
                for reader in readers:
                    mqtt.publish_discovery_for_device(reader.device_id, reader.config.name if not single else 'EASUN Inverter')
                if aliases:
                    mqtt.publish_discovery()
                if aggregate_id:
                    mqtt.publish_discovery_for_device(aggregate_id, 'EASUN 3-Phase System', aggregate=True)
            snapshots = []
            for reader in readers:
                data = reader.read()
                targets = [reader.device_id] + ([aliases[reader.device_id]] if reader.device_id in aliases else [])
                if data:
                    # Optional unsupported commands cannot manufacture measurements.
                    optional = reader.optional()
                    data.update(optional)
                healthy = bool(data) and reader.consecutive_errors == 0
                snapshots.append(data if healthy else {})
                if mqtt.connected:
                    for did in targets:
                        if data:
                            mqtt.publish_state_for_device(did, data)
                        mqtt.publish_state_for_device(did, reader.diagnostics())
                        mqtt.set_available(did, healthy)
            if aggregate_id and mqtt.connected:
                healthy = all(snapshots)
                if healthy:
                    totals = aggregate_data(snapshots, configs, [r.inverter.unsupported_commands for r in readers])
                    mqtt.publish_state_for_device(aggregate_id, totals)
                mqtt.set_available(aggregate_id, healthy)
            deadline = time.monotonic() + cfg.read_interval
            while not stopped and time.monotonic() < deadline:
                time.sleep(0.2)
    finally:
        for reader in readers:
            reader.inverter.close()
        mqtt.disconnect()
    return 0


if __name__ == '__main__':
    sys.exit(main())
