from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'addon/easun-inverter'))
from addon_config import Config


def test_blank_manual_credentials_use_supervisor_environment(monkeypatch):
    monkeypatch.setattr(Config,'_load_options',lambda self:{'mqtt_username':'','mqtt_password':''})
    monkeypatch.setenv('MQTT_USERNAME','test-service-user')
    monkeypatch.setenv('MQTT_PASSWORD','test-only-secret')
    cfg=Config()
    assert cfg.mqtt_username=='test-service-user'
    assert cfg.mqtt_password=='test-only-secret'


def test_explicit_manual_credentials_override_supervisor(monkeypatch):
    monkeypatch.setattr(Config,'_load_options',lambda self:{'mqtt_username':'manual','mqtt_password':'manual-test'})
    monkeypatch.setenv('MQTT_USERNAME','service')
    monkeypatch.setenv('MQTT_PASSWORD','service-test')
    cfg=Config()
    assert cfg.mqtt_username=='manual' and cfg.mqtt_password=='manual-test'


def test_missing_configured_by_id_never_selects_another_adapter(monkeypatch):
    monkeypatch.setattr(Config,'_load_options',lambda self:{'port':'/dev/serial/by-id/chosen'})
    monkeypatch.setattr('addon_config.glob.glob',lambda pattern:['/dev/serial/by-id/bms'])
    assert Config().inverters[0].port=='/dev/serial/by-id/chosen'
