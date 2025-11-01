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
    logging.info('🔌 EASUN Inverter Add-on v0.1.3')
    logging.info(f'Port: {cfg.port} @ {cfg.baudrate} baud, interval: {cfg.read_interval}s')

    mqtt = InverterMQTT(cfg.mqtt_host, cfg.mqtt_port, cfg.mqtt_username, cfg.mqtt_password, device_id=cfg.device_id)
    connected = mqtt.connect(timeout=10)
    if connected:
        mqtt.publish_discovery()
    else:
        logging.warning('MQTT not connected; will run without publishing')

    # Keep process alive; retry on open/read errors
    while True:
        inv = Inverter(cfg.port, baudrate=cfg.baudrate, timeout=cfg.timeout)
        try:
            inv.open()
        except Exception as e:
            logging.error(f'Failed to open inverter port: {e}')
            time.sleep(5)
            continue

        try:
            # Periodic counters
            last_qpiri = 0.0
            q1_every = max(30, cfg.read_interval * 2)
            loop_count = 0
            while True:
                loop_count += 1
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
                    # QMOD each loop
                    try:
                        mod = inv.query_qmod()
                        if mod and connected:
                            mqtt.publish_state(mod)
                    except Exception:
                        pass
                    # Q1 periodically
                    if (loop_count % max(1, int(q1_every / max(1, cfg.read_interval)))) == 0:
                        try:
                            q1 = inv.query_q1()
                            if q1 and connected:
                                mqtt.publish_state(q1)
                        except Exception:
                            pass
                    # QPIRI at start and then every 24h
                    now = time.time()
                    if now - last_qpiri > 24 * 3600:
                        try:
                            qpiri = inv.query_qpiri()
                            if qpiri and connected:
                                mqtt.publish_state(qpiri)
                        except Exception:
                            pass
                        last_qpiri = now
                else:
                    logging.warning('No data received')
                time.sleep(cfg.read_interval)
        except KeyboardInterrupt:
            logging.info('Interrupted by user')
            break
        except Exception as e:
            logging.error(f'Loop error, will reopen port: {e}')
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
