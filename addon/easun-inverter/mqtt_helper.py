#!/usr/bin/env python3
import json
import logging
import math
import time
from pathlib import Path
import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)
VERSION = Path(__file__).with_name('VERSION').read_text().strip()
SENSORS = [('ac_input_voltage_v', 'AC Input Voltage', 'V', 'voltage'),
 ('ac_input_frequency_hz', 'AC Input Frequency', 'Hz', 'frequency'),
 ('ac_output_voltage_v', 'AC Output Voltage', 'V', 'voltage'),
 ('ac_output_frequency_hz', 'AC Output Frequency', 'Hz', 'frequency'),
 ('ac_output_apparent_power_va', 'AC Output Apparent Power', 'VA', 'apparent_power'),
 ('ac_output_active_power_w', 'AC Output Active Power', 'W', 'power'),
 ('ac_output_load_percent', 'AC Output Load', '%', None),
 ('bus_voltage_v', 'BUS Voltage', 'V', 'voltage'),
 ('battery_voltage_v', 'Battery Voltage', 'V', 'voltage'),
 ('battery_charging_current_a', 'Battery Charging Current', 'A', 'current'),
 ('battery_capacity_percent', 'Battery State of Charge', '%', 'battery'),
 ('inverter_heatsink_temp_c', 'Inverter Heatsink Temp', '°C', 'temperature'),
 ('pv_input_current_a', 'PV Input Current', 'A', 'current'),
 ('pv_input_voltage_v', 'PV Input Voltage', 'V', 'voltage'),
 ('pv_input_power_w', 'PV Input Power', 'W', 'power'),
 ('battery_discharge_current_a', 'Battery Discharge Current', 'A', 'current'),
 ('pv2_input_current_a', 'PV2 Input Current', 'A', 'current'),
 ('pv2_input_voltage_v', 'PV2 Input Voltage', 'V', 'voltage'),
 ('pv2_input_power_w', 'PV2 Input Power', 'W', 'power'),
 ('scc_pwm_temp_c', 'SCC PWM Temperature', '°C', 'temperature'),
 ('inverter_temp_c', 'Inverter Temperature', '°C', 'temperature'),
 ('battery_temp_c', 'Battery Temperature', '°C', 'temperature'),
 ('transformer_temp_c', 'Transformer Temperature', '°C', 'temperature'),
 ('scc_charge_power_w', 'SCC Charge Power', 'W', 'power'),
 ('sync_frequency_hz', 'Sync Frequency', 'Hz', 'frequency'),
 ('inverter_mode', 'Inverter Mode', '', None),
 ('charge_stage', 'Charge Stage', '', None),
 ('qpiri_battery_recharge_voltage_v', 'Battery Recharge Voltage (QPIRI)', 'V', 'voltage'),
 ('qpiri_battery_under_voltage_v', 'Battery Under Voltage (QPIRI)', 'V', 'voltage'),
 ('qpiri_battery_bulk_charge_voltage_v', 'Battery Bulk Voltage (QPIRI)', 'V', 'voltage'),
 ('qpiri_battery_float_charge_voltage_v', 'Battery Float Voltage (QPIRI)', 'V', 'voltage'),
 ('firmware_version', 'Firmware Version', '', None),
 ('firmware2_version', 'Firmware2 Version', '', None),
 ('firmware3_version', 'Firmware3 Version', '', None),
 ('serial_number', 'Serial Number', '', None),
 ('last_success', 'Last Successful Read', '', 'timestamp'),
 ('measurement_age_s', 'Measurement Age', 's', 'duration'),
 ('read_errors', 'Read Errors', '', ''),
 ('consecutive_read_errors', 'Consecutive Read Errors', '', '')]
AGGREGATE = [
    ('total_active_power_w', 'Total AC Output Active Power', 'W', 'power'),
    ('total_apparent_power_va', 'Total AC Output Apparent Power', 'VA', 'apparent_power'),
    ('total_pv_power_w', 'Total PV Input Power', 'W', 'power'),
    ('phases', 'Configured Phases', '', None),
]
DIAGNOSTICS = {'last_success', 'measurement_age_s', 'read_errors', 'consecutive_read_errors',
               'firmware_version', 'firmware2_version', 'firmware3_version', 'serial_number'}


class InverterMQTT:
    def __init__(self, host, port, username='', password='', device_id='easun_inverter', expire_after=90):
        self.host, self.port, self.device_id = host, port, device_id
        self.expire_after = expire_after
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if username:
            self.client.username_pw_set(username, password)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.connected = False
        self.discovery_needed = False
        self._loop_running = False
        self._devices = set()
        self._availability_topic = f"easun/{device_id}/availability"
        self._connection_topic = f"easun/{device_id}/connection"
        self.client.will_set(self._connection_topic, payload='offline', qos=1, retain=True)
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        self.connected = reason_code == 0
        if self.connected:
            logger.info('MQTT connected; waiting for fresh inverter measurements')
            for device_id in self._devices:
                self.set_available(device_id, False)
            self.client.publish(self._connection_topic, 'online', qos=1, retain=True)
            self.client.subscribe('homeassistant/status', qos=1)
            self.discovery_needed = True
        else:
            logger.warning('MQTT connection rejected: %s', reason_code)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.connected = False
        logger.warning('MQTT disconnected; reconnecting automatically')

    def _on_message(self, client, userdata, message):
        if message.topic == 'homeassistant/status' and message.payload == b'online':
            self.discovery_needed = True

    def connect(self, timeout=10):
        self.client.connect_async(self.host, self.port, 60)
        if not self._loop_running:
            self.client.loop_start()
            self._loop_running = True
        deadline = time.monotonic() + timeout
        while not self.connected and time.monotonic() < deadline:
            time.sleep(0.1)
        return self.connected

    def disconnect(self):
        if self.connected:
            info = self.client.publish(self._connection_topic, 'offline', qos=1, retain=True)
            info.wait_for_publish(timeout=2)
        self.client.disconnect()
        if self._loop_running:
            self.client.loop_stop()
            self._loop_running = False

    def register_device(self, device_id):
        self._devices.add(device_id)

    def set_available(self, device_id, available):
        self.client.publish(f'easun/{device_id}/availability', 'online' if available else 'offline', qos=1, retain=True)

    def publish_discovery(self):
        self.publish_discovery_for_device(self.device_id, 'EASUN Inverter')

    def publish_discovery_for_device(self, device_id, device_name, aggregate=False):
        self.register_device(device_id)
        self.set_available(device_id, False)
        for key, name, unit, dclass in AGGREGATE if aggregate else SENSORS:
            cfg = {
                'name': name,
                'unique_id': f'{device_id}_{key}',
                'default_entity_id': f'sensor.{device_id}_{key}',
                'state_topic': f'easun/{device_id}/{key}',
                'device': {'identifiers': [device_id], 'name': device_name, 'manufacturer': 'EASUN',
                           'model': 'Inverter', 'sw_version': VERSION},
                'availability': [{'topic': self._connection_topic}],
                'availability_mode': 'all',
            }
            # Diagnostic health remains visible when the inverter itself is offline.
            if key not in {'last_success', 'measurement_age_s', 'read_errors', 'consecutive_read_errors'}:
                cfg['availability'].append({'topic': f'easun/{device_id}/availability'})
            if unit:
                cfg['unit_of_measurement'] = unit
            if dclass:
                cfg['device_class'] = dclass
            if key in DIAGNOSTICS or key.startswith('qpiri_'):
                cfg['entity_category'] = 'diagnostic'
            if unit and key not in DIAGNOSTICS and not key.startswith('qpiri_'):
                cfg['state_class'] = 'measurement'
            if unit and not key.startswith('qpiri_'):
                cfg['expire_after'] = max(self.expire_after, 300) if key in {'scc_pwm_temp_c', 'inverter_temp_c', 'battery_temp_c', 'transformer_temp_c', 'scc_charge_power_w', 'sync_frequency_hz'} else self.expire_after
            elif key in {'inverter_mode', 'charge_stage', 'phases', 'firmware_version', 'firmware2_version', 'firmware3_version', 'serial_number'}:
                cfg['expire_after'] = max(self.expire_after, 300)
            if dclass == 'voltage':
                cfg['suggested_display_precision'] = 3
            self.client.publish(f'homeassistant/sensor/{device_id}/{key}/config', json.dumps(cfg), qos=1, retain=True)

    def publish_state_for_device(self, device_id, data):
        for key, value in data.items():
            if value is None or isinstance(value, float) and not math.isfinite(value):
                continue
            if isinstance(value, float):
                value = round(value, 3)
            self.client.publish(f'easun/{device_id}/{key}', str(value), retain=False)

    def publish_state(self, data):
        self.publish_state_for_device(self.device_id, data)
