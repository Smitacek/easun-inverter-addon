#!/usr/bin/env python3
import json
import logging
import time
from typing import Dict, Any

import paho.mqtt.client as mqtt


logger = logging.getLogger(__name__)


class InverterMQTT:
    def __init__(self, host: str, port: int, username: str = '', password: str = '', device_id: str = 'easun_inverter'):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.device_id = device_id
        self.client = mqtt.Client()
        if username:
            self.client.username_pw_set(username, password)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.connected = False
        self._loop_running = False
        self._availability_topic = f"easun/{self.device_id}/availability"
        try:
            self.client.will_set(self._availability_topic, payload="offline", qos=1, retain=True)
        except Exception:
            pass

    def _on_connect(self, client, userdata, flags, rc):
        self.connected = (rc == 0)
        if self.connected:
            logger.info("✅ MQTT connected")
            try:
                self.client.publish(self._availability_topic, payload="online", qos=1, retain=True)
            except Exception:
                pass
        else:
            logger.error(f"❌ MQTT connect rc={rc}")

    def _on_disconnect(self, client, userdata, rc):
        self.connected = False
        logger.info("MQTT disconnected")

    def connect(self, timeout: int = 10) -> bool:
        try:
            self.client.connect(self.host, self.port, 60)
            if not self._loop_running:
                self.client.loop_start()
                self._loop_running = True
            waited = 0.0
            while waited < timeout and not self.connected:
                time.sleep(0.2)
                waited += 0.2
            return self.connected
        except Exception as e:
            logger.error(f"MQTT connect error: {e}")
            return False

    def disconnect(self):
        try:
            self.client.publish(self._availability_topic, payload="offline", qos=1, retain=True)
        except Exception:
            pass
        if self._loop_running:
            self.client.loop_stop()
            self._loop_running = False
        try:
            self.client.disconnect()
        except Exception:
            pass

    def publish_discovery(self):
        """Publish HA discovery for common PI30 QPIGS sensors."""
        base = {
            'manufacturer': 'EASUN',
            'model': 'Inverter',
            'sw_version': '0.1.3',
        }
        sensors = [
            ('ac_input_voltage_v', 'AC Input Voltage', 'V', 'voltage'),
            ('ac_input_frequency_hz', 'AC Input Frequency', 'Hz', None),
            ('ac_output_voltage_v', 'AC Output Voltage', 'V', 'voltage'),
            ('ac_output_frequency_hz', 'AC Output Frequency', 'Hz', None),
            ('ac_output_apparent_power_va', 'AC Output Apparent Power', 'VA', None),
            ('ac_output_active_power_w', 'AC Output Active Power', 'W', 'power'),
            ('ac_output_load_percent', 'AC Output Load', '%', None),
            ('bus_voltage_v', 'BUS Voltage', 'V', 'voltage'),
            ('battery_voltage_v', 'Battery Voltage', 'V', 'voltage'),
            ('battery_charging_current_a', 'Battery Charging Current', 'A', 'current'),
            ('battery_capacity_percent', 'Battery Capacity', '%', 'battery'),
            ('inverter_heatsink_temp_c', 'Inverter Heatsink Temp', '°C', 'temperature'),
            ('pv_input_current_a', 'PV Input Current', 'A', 'current'),
            ('pv_input_voltage_v', 'PV Input Voltage', 'V', 'voltage'),
            ('pv_input_power_w', 'PV Input Power', 'W', 'power'),
            ('battery_discharge_current_a', 'Battery Discharge Current', 'A', 'current'),
            # Optional PV2 (if device supports QPIGS2)
            ('pv2_input_current_a', 'PV2 Input Current', 'A', 'current'),
            ('pv2_input_voltage_v', 'PV2 Input Voltage', 'V', 'voltage'),
            ('pv2_input_power_w', 'PV2 Input Power', 'W', 'power'),
        ]
        for key, name, unit, dclass in sensors:
            self._publish_sensor_config(key, name, unit, dclass, base)

    def _publish_sensor_config(self, key: str, name: str, unit: str, device_class: str | None, base: Dict[str, Any]):
        device_id = self.device_id
        object_id = key
        discovery_topic = f"homeassistant/sensor/{device_id}/{object_id}/config"
        state_topic = f"easun/{device_id}/{object_id}"
        cfg = {
            'name': f"EASUN {name}",
            'unique_id': f"{device_id}_{object_id}",
            'object_id': f"{device_id}_{object_id}",
            'state_topic': state_topic,
            'unit_of_measurement': unit,
            'device': {
                'identifiers': [device_id],
                'name': 'EASUN Inverter',
                'manufacturer': base.get('manufacturer'),
                'model': base.get('model'),
                'sw_version': base.get('sw_version'),
            },
            'availability': [{
                'topic': self._availability_topic,
                'payload_available': 'online',
                'payload_not_available': 'offline'
            }]
        }
        if device_class:
            cfg['device_class'] = device_class
        # Suggest 3 decimals for voltages
        if device_class == 'voltage':
            cfg['suggested_display_precision'] = 3
        self.client.publish(discovery_topic, json.dumps(cfg), retain=True)

    def publish_state(self, data: Dict[str, Any]):
        device_id = self.device_id
        for key, value in data.items():
            topic = f"easun/{device_id}/{key}"
            if isinstance(value, float):
                value = round(value, 3)
            self.client.publish(topic, str(value))
