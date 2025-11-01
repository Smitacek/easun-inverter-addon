#!/usr/bin/env python3
import glob
import json
import os
from pathlib import Path


class InverterConfig:
    def __init__(self, port: str, baudrate: int = 2400, name: str | None = None,
                 enabled: bool = True, phase: str | None = None, timeout: float = 3.0):
        self.port = port
        self.baudrate = baudrate
        self.name = name or port
        self.enabled = enabled
        self.phase = phase  # 'L1'|'L2'|'L3' or None
        self.timeout = timeout


class Config:
    def __init__(self):
        self.load()

    def load(self):
        options = self._load_options()

        # Multi-inverter support
        self.multi_inverter_mode = bool(options.get('multi_inverter_mode', False))
        self.inverters: list[InverterConfig] = []

        if self.multi_inverter_mode:
            for inv in options.get('inverters', []):
                port = str(inv.get('port', '/dev/ttyUSB0'))
                baud = int(inv.get('baudrate', 2400))
                name = inv.get('name')
                enabled = bool(inv.get('enabled', True))
                phase = inv.get('phase')  # optional: L1/L2/L3
                timeout = float(inv.get('timeout', options.get('timeout', 3)))
                self.inverters.append(InverterConfig(port, baud, name, enabled, phase, timeout))
        else:
            # Single inverter fallback
            port = options.get('port', os.getenv('PORT', '/dev/ttyUSB0'))
            baud = int(options.get('baudrate', os.getenv('BAUDRATE', 2400)))
            timeout = float(options.get('timeout', os.getenv('TIMEOUT', 3)))
            self.inverters = [InverterConfig(port, baud, timeout=timeout)]

        # Prefer /dev/serial/by-id where possible
        self.prefer_by_id = bool(str(options.get('prefer_by_id', True)).lower() in ('1','true','yes'))
        if self.prefer_by_id:
            for inv in self.inverters:
                inv.port = self._prefer_by_id(inv.port)

        # 3-phase grouping
        self.group_3phase = bool(options.get('group_3phase', False))
        # Backward compatibility: also publish base topics for first inverter
        self.legacy_base_topics = bool(options.get('legacy_base_topics', True))

        # MQTT
        self.mqtt_host = options.get('mqtt_host', os.getenv('MQTT_HOST', 'core-mosquitto'))
        self.mqtt_port = int(options.get('mqtt_port', os.getenv('MQTT_PORT', 1883)))
        self.mqtt_username = options.get('mqtt_username', os.getenv('MQTT_USERNAME', ''))
        self.mqtt_password = options.get('mqtt_password', os.getenv('MQTT_PASSWORD', ''))
        self.read_interval = int(options.get('read_interval', os.getenv('READ_INTERVAL', 30)))
        self.log_level = str(options.get('log_level', os.getenv('LOG_LEVEL', 'WARNING'))).upper()
        self.device_id = 'easun_inverter'

    def _prefer_by_id(self, current: str) -> str:
        try:
            if current.startswith('/dev/serial/by-id/'):
                return current
            candidates = glob.glob('/dev/serial/by-id/*')
            real = os.path.realpath(current)
            for link in candidates:
                if os.path.realpath(link) == real:
                    return link
        except Exception:
            pass
        return current

    def _load_options(self):
        p = Path('/data/options.json')
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception:
                return {}
        return {}


def get_config() -> Config:
    return Config()

def get_enabled_inverters(cfg: Config) -> list[InverterConfig]:
    return [inv for inv in cfg.inverters if inv.enabled]
