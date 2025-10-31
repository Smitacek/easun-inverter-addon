#!/usr/bin/env python3
import glob
import json
import os
from pathlib import Path


class Config:
    def __init__(self):
        self.load()

    def load(self):
        options = self._load_options()
        self.port = options.get('port', os.getenv('PORT', '/dev/ttyUSB0'))
        self.baudrate = int(options.get('baudrate', os.getenv('BAUDRATE', 2400)))
        self.timeout = float(options.get('timeout', os.getenv('TIMEOUT', 3)))
        self.prefer_by_id = bool(str(options.get('prefer_by_id', True)).lower() in ('1','true','yes'))
        if self.prefer_by_id:
            self.port = self._prefer_by_id(self.port)
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
