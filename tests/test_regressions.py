import sys
from pathlib import Path
from unittest.mock import patch
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'addon/easun-inverter'))
from inverter import Inverter
from protocol_helpers import crc_pi

PAYLOAD = '(230.0 50.0 230.0 50.0 1800 1694 028 400 54.60 000 095 055 18.0 060.0 54.60 00000 00010110 00 00 00987 010'
def frame(payload=PAYLOAD):
    b = payload.encode('ascii')
    return b + bytes(crc_pi(b)) + b'\r'

class Wire:
    is_open=True
    def __init__(self, reply): self.reply=reply
    def write(self, data): return len(data)
    def reset_input_buffer(self): pass
    def read_until(self, expected, size):
        assert expected == b'\r'
        return self.reply
    def readline(self): return self.reply
    def close(self): self.is_open=False

def inv(reply):
    i=Inverter('/dev/serial/by-id/chosen')
    i._ser=Wire(reply)
    return i

def test_query_strips_crc_and_reads_cr():
    assert inv(frame()).query('QPIGS', delay=0) == PAYLOAD

def test_invalid_crc_rejected():
    with pytest.raises(ValueError): inv(frame()[:-3] + b'xx\r').query('QPIGS', retries=0, delay=0)

def test_timeout_is_failure():
    with pytest.raises(ValueError): inv(b'').read_snapshot()

def test_usb_read_error_propagates():
    i=inv(b'')
    with patch.object(i._ser, 'read_until', side_effect=OSError('USB removed')), patch.object(i._ser, 'readline', side_effect=OSError('USB removed')):
        with pytest.raises(OSError): i.query('QPIGS', delay=0)

@pytest.mark.parametrize('bad', [PAYLOAD.replace('230.0','23x0.0',1), PAYLOAD.replace('095','195'), PAYLOAD.replace('00010110','00010210'), '(230.0 50.0', PAYLOAD.replace('54.60','nan',1)])
def test_qpigs_rejects_whole_corrupt_payload(bad):
    with pytest.raises(ValueError): inv(b'').parse_qpigs(bad)

def test_optional_nak_omitted_and_cached():
    i=inv(frame('(NAK'))
    assert i.query_fw_sn() == {}
    i._ser.reply=frame('(VERFW:1.2')
    assert i.query('QVFW2', delay=0) is None

def test_close_clears_handle():
    i=inv(b''); i.close(); assert i._ser is None

def test_reference_qpigs_vector():
    raw=b'(000.0 00.0 230.0 49.9 0161 0119 003 460 57.50 012 100 0069 0014 103.8 57.45 00000 00110110 00 00 00856 010\x24\x8c\r'
    i=inv(raw)
    assert i.parse_qpigs(i.query('QPIGS',delay=0))['pv_input_power_w'] == 856


def test_optional_q1_does_not_publish_partial_payload():
    i=inv(frame('(1 2 3 4 5 6'))
    assert i.query_q1() == {}


def test_probe_requires_explicit_port():
    import importlib.util
    spec=importlib.util.spec_from_file_location('probe', Path(__file__).resolve().parents[1] / 'probe_inverter.py')
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    with patch.object(module,'run_probe',return_value=1):
        with pytest.raises(SystemExit): module.main([])
