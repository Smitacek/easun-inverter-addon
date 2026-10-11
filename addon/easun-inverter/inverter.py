#!/usr/bin/env python3
import json
import logging
import os
import time
from typing import Dict, List, Optional

import serial
import re
import math

from protocol_helpers import build_command, decode_response


logger = logging.getLogger(__name__)


class Inverter:
    """EASUN/Voltronic inverter client using PI protocol over serial/USB."""

    def __init__(self, port: str, baudrate: int = 2400, timeout: float = 3.0, map_path: str = '/app/inverter_map.json'):
        self.port_path = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._ser: Optional[serial.Serial] = None
        self._map = self._load_map(map_path)
        self.unsupported_commands = set()

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
        self.close()
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
        ser, self._ser = self._ser, None
        if ser is not None:
            try:
                ser.close()
            except (OSError, serial.SerialException):
                pass

    @property
    def is_open(self):
        return self._ser is not None and self._ser.is_open

    def query(self, cmd: str, retries: int = 2, delay: float = 0.1) -> Optional[str]:
        if cmd in self.unsupported_commands:
            return None
        if not self.is_open:
            raise serial.SerialException("Configured serial port is not open")
        for attempt in range(retries + 1):
            # Discard late/partial responses before a new request. Never change port identity.
            self._ser.reset_input_buffer()
            packet = build_command(cmd)
            if self._ser.write(packet) != len(packet):
                raise serial.SerialTimeoutException("Incomplete command write")
            time.sleep(delay)
            raw = self._ser.read_until(expected=b"\r", size=1024)
            try:
                response = decode_response(raw)
            except ValueError:
                if attempt == retries:
                    raise
                continue
            if response == '(NAK':
                if cmd == 'QPIGS':
                    raise ValueError("QPIGS rejected by inverter")
                self.unsupported_commands.add(cmd)
                logger.info("Optional command %s unsupported; skipping until process restart", cmd)
                return None
            return response
        raise ValueError("No valid response")

    def optional_query(self, cmd, **kwargs):
        try:
            return self.query(cmd, retries=0, **kwargs)
        except ValueError as exc:
            logger.debug("Optional %s response ignored: %s", cmd, exc)
            return None

    def query_qmod(self) -> Dict[str, str]:
        """Query inverter mode (QMOD) and map code to text."""
        out: Dict[str, str] = {}
        line = self.optional_query('QMOD')
        if not line:
            return out
        # Response typically like: (L) or (B) etc.
        if line.startswith('(') and ')' in line:
            code = line[1:line.find(')')]
        else:
            code = line.removeprefix('(')
        mode_map = {
            'P': 'Power On',
            'S': 'Standby',
            'L': 'Line',
            'B': 'Battery',
            'F': 'Fault',
            'H': 'Power Saving',
            'D': 'Shutdown',
            'Y': 'Bypass',
        }
        if code not in mode_map:
            return {}
        out['inverter_mode_code'] = code
        out['inverter_mode'] = mode_map.get(code, code)
        return out

    def query_q1(self) -> Dict[str, float | str]:
        """Query extended status (Q1) for temps, SCC charge power, sync frequency, charge stage."""
        out: Dict[str, float | str] = {}
        line = self.optional_query('Q1', delay=0.15)
        if not line:
            return out
        # Extract payload inside parentheses
        if line.startswith('('):
            payload = line[1:line.find(')')] if ')' in line else line[1:]
        else:
            payload = line
        tokens = [t for t in payload.strip().split(' ') if t]
        if len(tokens) != 17 or not all(re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', t) for t in tokens):
            return {}
        # Helper to safe-int/float
        def as_int(idx: int) -> Optional[int]:
            if idx < len(tokens):
                t = tokens[idx]
                try:
                    return int(t)
                except Exception:
                    try:
                        return int(float(t))
                    except Exception:
                        return None
            return None
        def as_float(idx: int) -> Optional[float]:
            if idx < len(tokens):
                t = tokens[idx]
                try:
                    return float(t)
                except Exception:
                    return None
            return None
        # According to PI30 mapping (1-based in docs), approximate indices (0-based here)
        value = as_int(5)
        if value is not None:
            out['scc_pwm_temp_c'] = value
        value = as_int(6)
        if value is not None:
            out['inverter_temp_c'] = value
        value = as_int(7)
        if value is not None:
            out['battery_temp_c'] = value
        value = as_int(8)
        if value is not None:
            out['transformer_temp_c'] = value
        value = as_int(13)
        if value is not None:
            out['scc_charge_power_w'] = value
        sf = as_float(15)
        if sf is not None:
            out['sync_frequency_hz'] = sf
        # Charge status (index 16 usually string like '10','11','12','13')
        if 16 < len(tokens):
            status_code = tokens[16]
            charge_map = {
                '10': 'nocharging',
                '11': 'bulk',
                '12': 'absorb',
                '13': 'float',
            }
            out['charge_stage'] = charge_map.get(status_code, status_code)
        return out

    def query_qpiri(self) -> Dict[str, float | int | str]:
        """Query current settings (QPIRI) and parse primary fields."""
        out: Dict[str, float | int | str] = {}
        line = self.optional_query('QPIRI', delay=0.15)
        if not line:
            return out
        if line.startswith('('):
            payload = line[1:line.find(')')] if ')' in line else line[1:]
        else:
            payload = line
        tokens = [t for t in payload.strip().split(' ') if t]
        def f(i):
            try:
                return float(tokens[i])
            except Exception:
                return None
        def iv(i):
            try:
                return int(float(tokens[i]))
            except Exception:
                return None
        # Map first dozen fields commonly present
        if len(tokens) >= 12:
            out['qpiri_ac_input_voltage_v'] = f(0)
            out['qpiri_ac_input_current_a'] = f(1)
            out['qpiri_ac_output_voltage_v'] = f(2)
            out['qpiri_ac_output_frequency_hz'] = f(3)
            out['qpiri_ac_output_current_a'] = f(4)
            out['qpiri_ac_output_apparent_power_va'] = iv(5)
            out['qpiri_ac_output_active_power_w'] = iv(6)
            out['qpiri_battery_voltage_v'] = f(7)
            out['qpiri_battery_recharge_voltage_v'] = f(8)
            out['qpiri_battery_under_voltage_v'] = f(9)
            out['qpiri_battery_bulk_charge_voltage_v'] = f(10)
            out['qpiri_battery_float_charge_voltage_v'] = f(11)
        return out

    def query_fw_sn(self) -> Dict[str, str]:
        """Query firmware versions (QVFW, QVFW2, QVFW3) and serial (QID/QSID)."""
        out: Dict[str, str] = {}
        def parse_simple(resp: Optional[str]) -> Optional[str]:
            if not resp:
                return None
            if resp.startswith('(') and ')' in resp:
                return resp[1:resp.find(')')].strip()
            return resp.removeprefix('(').strip()
        outv = parse_simple(self.optional_query('QVFW'))
        if outv:
            out['firmware_version'] = outv
        outv2 = parse_simple(self.optional_query('QVFW2'))
        if outv2:
            out['firmware2_version'] = outv2
        outv3 = parse_simple(self.optional_query('QVFW3'))
        if outv3:
            out['firmware3_version'] = outv3
        sid = parse_simple(self.optional_query('QSID'))
        if sid:
            out['serial_number'] = sid
        else:
            qid = parse_simple(self.optional_query('QID'))
            if qid:
                out['serial_number'] = qid
        return out

    def parse_qpigs(self, line: str) -> Dict[str, float]:
        """Parse QPIGS line using PI30 field order (21 tokens)."""
        if not line or not line.startswith('('):
            raise ValueError("QPIGS missing start marker")
        parts = line[1:].split()
        if len(parts) not in (21, 22):
            raise ValueError(f"QPIGS expected 21 or 22 fields, got {len(parts)}")
        for index, token in enumerate(parts):
            if index in (16, 20):
                width = 8 if index == 16 else 3
                if not re.fullmatch(r"[01]{%d}" % width, token):
                    raise ValueError(f"QPIGS invalid status bits at field {index}")
            elif not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", token) or not math.isfinite(float(token)):
                raise ValueError(f"QPIGS invalid numeric field {index}")
        if float(parts[10]) > 100:
            raise ValueError("QPIGS battery state of charge exceeds 100%")

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
            except ValueError as exc:
                raise ValueError(f"QPIGS invalid integer field {i}") from exc

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
        """Required telemetry: only a complete, CRC-validated QPIGS is success."""
        return self.parse_qpigs(self.query('QPIGS'))

    def query_pv2(self):
        line = self.optional_query('QPIGS2')
        if not line:
            return {}
        parts = line.removeprefix('(').split()
        if len(parts) != 3 or not all(re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", p) for p in parts):
            return {}
        return dict(zip(('pv2_input_current_a', 'pv2_input_voltage_v', 'pv2_input_power_w'), map(float, parts)))
