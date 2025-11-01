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
        """Parse QPIGS line using PI30 field order (21 tokens)."""
        if not line:
            return {}
        # Extract payload inside parentheses (ignore trailing CRC bytes)
        if line.startswith('('):
            line = line[1:]
        if ')' in line:
            line = line.split(')')[0]
        # Tokenize and sanitize numeric tokens
        raw_parts = [p for p in line.strip().split(' ') if p]
        parts: List[str] = []
        for tok in raw_parts:
            cleaned = re.sub(r"[^0-9+\-.]", "", tok)
            parts.append(cleaned)

        # PI30 QPIGS mapping (indices 0..20)
        field_keys: List[str] = [
            'ac_input_voltage_v',            # 0
            'ac_input_frequency_hz',         # 1
            'ac_output_voltage_v',           # 2
            'ac_output_frequency_hz',        # 3
            'ac_output_apparent_power_va',   # 4
            'ac_output_active_power_w',      # 5
            'ac_output_load_percent',        # 6
            'bus_voltage_v',                 # 7
            'battery_voltage_v',             # 8
            'battery_charging_current_a',    # 9
            'battery_capacity_percent',      # 10
            'inverter_heatsink_temp_c',      # 11
            'pv_input_current_a',            # 12
            'pv_input_voltage_v',            # 13
            'battery_voltage_scc_v',         # 14
            'battery_discharge_current_a',   # 15
            'device_status_bits',            # 16 (8-bit ascii flags)
            'rsv1',                          # 17
            'rsv2',                          # 18
            'pv_input_power_w',              # 19
            'device_status2_bits',           # 20 (3-bit ascii flags)
        ]

        data: Dict[str, float] = {}
        for i, key in enumerate(field_keys):
            if i >= len(parts):
                break
            val_s = parts[i]
            if key in ('device_status_bits', 'device_status2_bits'):
                data[key] = val_s
                continue
            try:
                if key in ('ac_output_apparent_power_va', 'ac_output_active_power_w', 'ac_output_load_percent',
                           'battery_charging_current_a', 'battery_capacity_percent', 'inverter_heatsink_temp_c',
                           'battery_discharge_current_a', 'rsv1', 'rsv2', 'pv_input_power_w', 'bus_voltage_v'):
                    data[key] = int(val_s)
                else:
                    data[key] = float(val_s)
            except Exception:
                continue

        # Derive useful boolean flags from device_status_bits
        bits = str(data.get('device_status_bits', ''))
        if len(bits) == 8 and bits.isdigit():
            try:
                data['status_sbu_priority_added'] = bits[0] == '1'
                data['status_configuration_changed'] = bits[1] == '1'
                data['status_scc_fw_updated'] = bits[2] == '1'
                data['status_load_on'] = bits[3] == '1'
                data['status_batt_steady_while_charging'] = bits[4] == '1'
                data['status_charging_on'] = bits[5] == '1'
                data['status_scc_charging_on'] = bits[6] == '1'
                data['status_ac_charging_on'] = bits[7] == '1'
            except Exception:
                pass
        bits2 = str(data.get('device_status2_bits', ''))
        if len(bits2) == 3 and bits2.isdigit():
            data['status_charging_to_float'] = bits2[0] == '1'
            data['status_switched_on'] = bits2[1] == '1'

        return data

    def read_snapshot(self) -> Dict[str, float]:
        """Read a single snapshot using QPIGS."""
        line = self.query('QPIGS')
        if not line:
            return {}
        return self.parse_qpigs(line)
