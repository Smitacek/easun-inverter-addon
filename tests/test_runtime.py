from pathlib import Path
import sys, json
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'addon/easun-inverter'))
import main
from mqtt_helper import InverterMQTT

class Broker:
    def __init__(self): self.messages=[]
    def publish(self, topic, payload=None, **kwargs): self.messages.append((topic,payload,kwargs)); return SimpleNamespace(rc=0)
    def subscribe(self, *args, **kwargs): pass


def test_failed_reader_closes_then_reopens_configured_device():
    assert hasattr(main, 'DeviceReader'), 'missing per-device recovery'
    inv=Mock(); inv.is_open=False
    inv.read_snapshot.side_effect=[OSError('USB removed'), {'ac_output_active_power_w': 100}]
    reader=main.DeviceReader(SimpleNamespace(name='inv', phase=None),inv,'inv')
    assert reader.read(now=1) == {}
    assert reader.errors == 1 and reader.last_success is None
    assert reader.read(now=11)['ac_output_active_power_w'] == 100
    assert reader.last_success == 11 and reader.consecutive_errors == 0
    assert inv.open.call_count == 2 and inv.close.call_count == 1


def test_discovery_tracks_inverter_and_connection_and_expires():
    m=InverterMQTT('localhost',1883); m.client=Broker()
    m.publish_discovery()
    configs={t:json.loads(p) for t,p,k in m.client.messages if t.endswith('/config')}
    cfg=configs['homeassistant/sensor/easun_inverter/battery_capacity_percent/config']
    assert cfg['device_class']=='battery' and cfg['unit_of_measurement']=='%'
    assert cfg['state_class']=='measurement' and cfg['expire_after'] > 0
    assert cfg['availability_mode']=='all' and len(cfg['availability'])==2
    assert cfg['unique_id']=='easun_inverter_battery_capacity_percent'
    assert 'Charge' in cfg['name']
    power=configs['homeassistant/sensor/easun_inverter/ac_output_active_power_w/config']
    assert power['device_class']=='power' and power['unit_of_measurement']=='W'
    text=configs['homeassistant/sensor/easun_inverter/inverter_mode/config']
    assert 'state_class' not in text and 'unit_of_measurement' not in text
    assert not any(p=='online' for t,p,k in m.client.messages if t.endswith('/availability'))


def test_none_never_published_as_numeric_state():
    m=InverterMQTT('localhost',1883); m.client=Broker()
    m.publish_state({'battery_voltage_v':None, 'battery_charging_current_a':0})
    assert [(t,p) for t,p,k in m.client.messages] == [('easun/easun_inverter/battery_charging_current_a','0')]

def test_static_data_replayed_without_daily_serial_queries():
    inv=Mock()
    inv.query_qmod.return_value={}; inv.query_pv2.return_value={}; inv.query_q1.return_value={}
    inv.query_fw_sn.return_value={'firmware_version':'VERFW:1.2'}
    inv.query_qpiri.return_value={'qpiri_battery_float_charge_voltage_v':54.0}
    reader=main.DeviceReader(SimpleNamespace(name='inv'),inv,'inv')
    assert reader.optional()['firmware_version']=='VERFW:1.2'
    assert reader.optional()['firmware_version']=='VERFW:1.2'
    assert inv.query_fw_sn.call_count==1


def test_pv_total_omitted_when_second_channel_missing():
    assert hasattr(main,'aggregate_data')
    data=[{'ac_output_active_power_w':100,'ac_output_apparent_power_va':150,'pv_input_power_w':200}]
    configs=[SimpleNamespace(phase='L1')]
    total=main.aggregate_data(data,configs,[set()])
    assert total['total_active_power_w']==100
    assert 'total_pv_power_w' not in total
    total=main.aggregate_data(data,configs,[{'QPIGS2'}])
    assert total['total_pv_power_w']==200

def test_metadata_units_statistics_and_unprefixed_names():
    m=InverterMQTT('localhost',1883); m.client=Broker(); m.publish_discovery()
    configs={t.split('/')[-2]:json.loads(p) for t,p,k in m.client.messages if t.endswith('/config')}
    expected={'battery_voltage_v':('V','voltage'), 'battery_charging_current_a':('A','current'), 'battery_discharge_current_a':('A','current'), 'inverter_heatsink_temp_c':('°C','temperature'), 'ac_output_frequency_hz':('Hz','frequency'), 'ac_output_apparent_power_va':('VA','apparent_power')}
    for key,(unit,device_class) in expected.items():
        cfg=configs[key]
        assert cfg['unit_of_measurement']==unit and cfg['device_class']==device_class
        assert cfg['state_class']=='measurement'
        assert cfg['default_entity_id']==f'sensor.easun_inverter_{key}'
        assert not cfg['name'].startswith('EASUN')
    for key in ['inverter_mode','charge_stage','firmware_version','firmware2_version','last_success','read_errors']:
        assert 'state_class' not in configs[key]
    assert configs['firmware2_version']['expire_after'] > 0
    assert configs['last_success']['entity_category']=='diagnostic'
    assert configs['last_success']['device_class']=='timestamp'
    assert 'state_class' not in configs['qpiri_battery_float_charge_voltage_v']
