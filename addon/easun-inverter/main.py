#!/usr/bin/env python3
import logging
import sys
import time

from addon_config import get_config, get_enabled_inverters
from inverter import Inverter
from mqtt_helper import InverterMQTT


def setup_logging(level: str = 'INFO'):
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(level=log_level, format='[%(levelname)s] %(message)s', stream=sys.stdout)


def main():
    cfg = get_config()
    setup_logging(cfg.log_level)
    logging.info('🔌 EASUN Inverter Add-on v0.2.0')
    logging.info(f'Port: {cfg.port} @ {cfg.baudrate} baud, interval: {cfg.read_interval}s')

    mqtt = InverterMQTT(cfg.mqtt_host, cfg.mqtt_port, cfg.mqtt_username, cfg.mqtt_password, device_id=cfg.device_id)
    connected = mqtt.connect(timeout=10)
    if connected:
        mqtt.publish_discovery()
    else:
        logging.warning('MQTT not connected; will run without publishing')

    # Prepare inverter configs
    inv_cfgs = get_enabled_inverters(cfg)
    # Publish discovery per inverter
    if connected:
        for ic in inv_cfgs:
            did = f"{cfg.device_id}_{(ic.name or ic.port).lower().replace(' ','_')}"
            mqtt.publish_discovery_for_device(did, ic.name or ic.port)
        # If 3-phase grouping requested and phases L1/L2/L3 present, publish aggregator discovery
        if cfg.group_3phase and {i.phase for i in inv_cfgs} >= {'L1','L2','L3'}:
            mqtt.publish_discovery_for_device(f"{cfg.device_id}_3phase", "EASUN 3-Phase System")

    # Keep process alive; retry on open/read errors for each inverter sequentially
    while True:
        # Build fresh objects each outer loop to recover failures
        inv_objs = []
        for ic in inv_cfgs:
            inv_objs.append((ic, Inverter(ic.port, baudrate=ic.baudrate, timeout=ic.timeout)))
        try:
            for _, inv in inv_objs:
                try:
                    inv.open()
                except Exception as e:
                    logging.error(f'Failed to open inverter port: {e}')
        except Exception as e:
            time.sleep(5)
            continue

        try:
            # Periodic counters
            last_qpiri: dict[str, float] = {}
            q1_every = max(30, cfg.read_interval * 2)
            loop_count = 0
            while True:
                loop_count += 1
                # Accumulate aggregator if 3-phase grouping
                agg_active = 0
                agg_apparent = 0
                agg_pv = 0
                phases_present = set()
                for ic, inv in inv_objs:
                    data = {}
                    try:
                        data = inv.read_snapshot()
                    except Exception as e:
                        logging.error(f'Read error ({ic.name or ic.port}): {e}')
                    if data:
                        short = ', '.join(f'{k}={v}' for k, v in list(data.items())[:6])
                        logging.info(f"{ic.name or ic.port} QPIGS: {short} ...")
                        if connected:
                            did = f"{cfg.device_id}_{(ic.name or ic.port).lower().replace(' ','_')}"
                            try:
                                mqtt.publish_state_for_device(did, data)
                            except Exception as e:
                                logging.error(f'MQTT publish error: {e}')
                        # extended queries
                        try:
                            mod = inv.query_qmod()
                            if mod and connected:
                                mqtt.publish_state_for_device(did, mod)
                        except Exception:
                            pass
                        if (loop_count % max(1, int(q1_every / max(1, cfg.read_interval)))) == 0:
                            try:
                                q1 = inv.query_q1()
                                if q1 and connected:
                                    mqtt.publish_state_for_device(did, q1)
                            except Exception:
                                pass
                        # FW/SN once
                        try:
                            fwsn = inv.query_fw_sn()
                            if fwsn and connected:
                                mqtt.publish_state_for_device(did, fwsn)
                        except Exception:
                            pass
                        now = time.time()
                        last_ts = last_qpiri.get(did, 0.0)
                        if now - last_ts > 24*3600:
                            try:
                                qpiri = inv.query_qpiri()
                                if qpiri and connected:
                                    mqtt.publish_state_for_device(did, qpiri)
                            except Exception:
                                pass
                            last_qpiri[did] = now
                        # aggregate sums
                        agg_active += int(data.get('ac_output_active_power_w', 0) or 0)
                        agg_apparent += int(data.get('ac_output_apparent_power_va', 0) or 0)
                        pv1 = int(data.get('pv_input_power_w', 0) or 0)
                        pv2 = int(data.get('pv2_input_power_w', 0) or 0)
                        agg_pv += pv1 + pv2
                        if ic.phase:
                            phases_present.add(ic.phase)
                # publish aggregator if configured and phases present
                if cfg.group_3phase and phases_present >= {'L1','L2','L3'} and connected:
                    agg_id = f"{cfg.device_id}_3phase"
                    agg_data = {
                        'total_active_power_w': agg_active,
                        'total_apparent_power_va': agg_apparent,
                        'total_pv_power_w': agg_pv,
                        'phases': ','.join(sorted(phases_present)),
                    }
                    mqtt.publish_state_for_device(agg_id, agg_data)
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
