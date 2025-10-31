#!/usr/bin/env python3
import logging
import sys
import time

from addon_config import get_config
from inverter import Inverter
from mqtt_helper import InverterMQTT


def setup_logging(level: str = 'INFO'):
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(level=log_level, format='[%(levelname)s] %(message)s', stream=sys.stdout)


def main():
    cfg = get_config()
    setup_logging(cfg.log_level)
    logging.info('🔌 EASUN Inverter Add-on v0.1.0')
    logging.info(f'Port: {cfg.port} @ {cfg.baudrate} baud, interval: {cfg.read_interval}s')

    inv = Inverter(cfg.port, baudrate=cfg.baudrate, timeout=cfg.timeout)

    mqtt = InverterMQTT(cfg.mqtt_host, cfg.mqtt_port, cfg.mqtt_username, cfg.mqtt_password, device_id=cfg.device_id)
    connected = mqtt.connect(timeout=10)
    if connected:
        mqtt.publish_discovery()
    else:
        logging.warning('MQTT not connected; will run without publishing')

    try:
        inv.open()
    except Exception as e:
        logging.error(f'Failed to open inverter port: {e}')
        return 1

    try:
        while True:
            data = {}
            try:
                data = inv.read_snapshot()
            except Exception as e:
                logging.error(f'Read error: {e}')
            if data:
                logging.info('QPIGS snapshot: ' + ', '.join(f'{k}={v}' for k, v in list(data.items())[:8]) + ' ...')
                if connected:
                    try:
                        mqtt.publish_state(data)
                    except Exception as e:
                        logging.error(f'MQTT publish error: {e}')
            else:
                logging.warning('No data received')
            time.sleep(cfg.read_interval)
    except KeyboardInterrupt:
        logging.info('Interrupted by user')
    finally:
        try:
            inv.close()
        except Exception:
            pass
        try:
            mqtt.disconnect()
        except Exception:
            pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
