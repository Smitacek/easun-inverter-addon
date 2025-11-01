#!/usr/bin/env python3
import json
import logging
import os
import time
from typing import Dict, List, Optional

import serial
import re

from protocol_helpers import build_command


logger = logging.getLogger(__name__)


class Inverter:
    """EASUN/Voltronic inverter client using PI protocol over serial/USB."""

    def __init__(self, port: str, baudrate: int = 2400, timeout: float = 3.0, map_path: str = '/app/inverter_map.json'):
        self.port_path = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._ser: Optional[serial.Serial] = None
        self._map = self._load_map(map_path)

    def _load_map(self, path: str) -> Dict[str, List[str]]:
        try:
            if os.path.exists(path):
                with open(path, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return {k: list(v) for k, v in data.items()}
        except Exception as e:
            logger.warning(f"Map load failed: {e}")
        # minimal default mapping
        return {"QPIGS": [
            "grid_voltage", "grid_power", "grid_frequency", "grid_current",
            "ac_output_voltage", "ac_output_power", "ac_output_frequency", "ac_output_current",
            "output_load_percent",
            "p_bus_voltage", "s_bus_voltage",
            "p_battery_voltage", "n_battery_voltage",
            "battery_capacity",
            "pv_input_power_1", "pv_input_power_2", "pv_input_power_3",
            "pv_input_voltage_1", "pv_input_voltage_2", "pv_input_voltage_3",
            "max_temperature_of_detecting_pointers"
        ]}

    def open(self) -> None:
        self._ser = serial.Serial(self.port_path, baudrate=self.baudrate, timeout=self.timeout)
        logger.info(f"Opened serial port {self.port_path} @ {self.baudrate} baud")
        try:
            # Some adapters/inverters need DTR/RTS toggle to wake
            self._ser.dtr = False
            self._ser.rts = False
            time.sleep(0.05)
            self._ser.dtr = True
            self._ser.rts = True
        except Exception:
            pass

    def close(self) -> None:
        try:
            if self._ser and self._ser.is_open:
                self._ser.close()
        except Exception:
            pass

    def _write(self, cmd: str) -> None:
        assert self._ser
        data = build_command(cmd)
        self._ser.write(data)

    def _readline(self) -> str:
        assert self._ser
        line = self._ser.readline()
        try:
            return line.decode('utf-8', errors='ignore').strip()
        except Exception:
            return ''

    def query(self, cmd: str, retries: int = 2, delay: float = 0.1) -> Optional[str]:
        for attempt in range(retries + 1):
            try:
                self._write(cmd)
                time.sleep(delay)
                resp = self._readline()
                if resp:
                    return resp
            except Exception as e:
                logger.debug(f"Query {cmd} error: {e}")
                time.sleep(0.2)
        return None

    def parse_qpigs(self, line: str) -> Dict[str, float]:
        """Parse QPIGS line -> dict of values; ignores CRC and parentheses."""
        # Typical response may look like: (xxx xxx ... )<CRC>
        if not line:
            return {}
        # Strip leading '(' and trailing sequence before checksum
        if line[0] == '(':
            line = line[1:]
        # Remove everything after and including ')'
        if ')' in line:
            line = line.split(')')[0]
        # Split and sanitize tokens: keep digits, sign and decimal point
        raw_parts = [p for p in line.strip().split(' ') if p]
        parts: List[str] = []
        for tok in raw_parts:
            cleaned = re.sub(r"[^0-9+\-.]", "", tok)
            parts.append(cleaned)
        keys = self._map.get('QPIGS', [])
        data: Dict[str, float] = {}
        for i, key in enumerate(keys):
            if i < len(parts):
                try:
                    val = float(parts[i])
                except ValueError:
                    try:
                        val = int(parts[i])
                    except Exception:
                        continue
                data[key] = val
        return data

    def read_snapshot(self) -> Dict[str, float]:
        """Read a single snapshot using QPIGS."""
        line = self.query('QPIGS')
        if not line:
            return {}
        return self.parse_qpigs(line)
