import os
import sys
import threading
import time
import subprocess
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'addon/easun-inverter'))
from inverter import Inverter
from protocol_helpers import build_command


def test_real_serial_cr_response_without_waiting_for_lf():
    import pty
    master, slave = pty.openpty()
    i = Inverter(os.ttyname(slave), timeout=2)
    response = b'(000.0 00.0 230.0 49.9 0161 0119 003 460 57.50 012 100 0069 0014 103.8 57.45 00000 00110110 00 00 00856 010\x24\x8c\r'
    requests=[]
    def device():
        packet=b''
        while not packet.endswith(b'\r'):
            packet+=os.read(master,1024)
        requests.append(packet)
        os.write(master,response)
    worker=threading.Thread(target=device,daemon=True)
    try:
        i.open(); worker.start()
        start=time.monotonic(); data=i.read_snapshot()
        assert time.monotonic()-start < 1
        assert data['battery_charging_current_a']==12
        worker.join(timeout=1)
        assert requests == [build_command('QPIGS')]
    finally:
        i.close(); os.close(master); os.close(slave)


def eventually(predicate, timeout=12):
    end=time.monotonic()+timeout
    while not predicate():
        assert time.monotonic()<end, 'MQTT event timed out'
        time.sleep(0.05)


@pytest.mark.skipif(not os.environ.get('EASUN_TEST_BROKER_CONTAINER'),reason='requires disposable local MQTT broker')
def test_real_broker_restart_and_ha_birth():
    import paho.mqtt.client as paho
    from mqtt_helper import InverterMQTT
    container=os.environ['EASUN_TEST_BROKER_CONTAINER']
    assert container.startswith('easun-audit-')
    m=InverterMQTT('127.0.0.1',18884,device_id='audit')
    m.register_device('audit_inv')
    assert m.connect(timeout=5)
    assert m.discovery_needed
    m.discovery_needed=False
    probe=paho.Client(paho.CallbackAPIVersion.VERSION2)
    probe.connect('127.0.0.1',18884)
    probe.loop_start()
    try:
        probe.publish('homeassistant/status','online',qos=1).wait_for_publish(timeout=3)
        eventually(lambda:m.discovery_needed)
        m.discovery_needed=False
        subprocess.run(['docker','restart',container],check=True,stdout=subprocess.DEVNULL)
        eventually(lambda:m.connected and m.discovery_needed)
        messages=[]
        probe.on_message=lambda c,u,msg:messages.append((msg.topic,msg.payload))
        probe.subscribe('easun/audit_inv/availability',qos=1)
        eventually(lambda:('easun/audit_inv/availability',b'offline') in messages)
        assert not any(p==b'online' for t,p in messages)
        m.set_available('audit_inv',True)
        eventually(lambda:('easun/audit_inv/availability',b'online') in messages)
    finally:
        probe.disconnect(); probe.loop_stop(); m.disconnect()

def test_same_by_id_path_recovers_after_usb_disconnect(tmp_path):
    import pty
    import main
    from types import SimpleNamespace
    master,slave=pty.openpty()
    path=tmp_path/'chosen-by-id'; path.symlink_to(os.ttyname(slave))
    cfg=SimpleNamespace(name='inverter',phase=None)
    i=Inverter(str(path),timeout=0.1)
    reader=main.DeviceReader(cfg,i,'inv')
    i.open(); os.close(master)
    assert reader.read(now=1)=={} and not i.is_open
    os.close(slave)
    master,slave=pty.openpty(); path.unlink(); path.symlink_to(os.ttyname(slave))
    requests=[]
    def respond():
        data=b''
        while not data.endswith(b'\r'): data+=os.read(master,1024)
        requests.append(data)
        os.write(master,b'(000.0 00.0 230.0 49.9 0161 0119 003 460 57.50 012 100 0069 0014 103.8 57.45 00000 00110110 00 00 00856 010\x24\x8c\r')
    worker=threading.Thread(target=respond,daemon=True); worker.start()
    try:
        assert reader.read(now=10)['battery_voltage_v']==57.5
        assert reader.last_success==10 and reader.errors==1 and reader.consecutive_errors==0
        assert i.port_path==str(path)
    finally:
        i.close(); worker.join(timeout=1); os.close(master); os.close(slave)


@pytest.mark.skipif(not os.environ.get('EASUN_TEST_BROKER_CONTAINER'),reason='requires disposable local MQTT broker')
def test_initial_broker_outage_retries_automatically():
    from mqtt_helper import InverterMQTT
    container=os.environ['EASUN_TEST_BROKER_CONTAINER']
    assert container.startswith('easun-audit-')
    subprocess.run(['docker','stop',container],check=True,stdout=subprocess.DEVNULL)
    m=InverterMQTT('127.0.0.1',18884,device_id='startup_audit')
    try:
        assert not m.connect(timeout=0.2)
        subprocess.run(['docker','start',container],check=True,stdout=subprocess.DEVNULL)
        eventually(lambda:m.connected)
        assert m.discovery_needed
    finally:
        subprocess.run(['docker','start',container],check=True,stdout=subprocess.DEVNULL)
        m.disconnect()
