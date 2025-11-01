#!/usr/bin/env python3
"""
Quick EASUN/Voltronic inverter probe over RS232/USB (PI protocol).

Sends QPI / QID / QPIGS with correct CRC and prints responses.

Examples:
  ./probe_inverter.py --port /dev/serial/by-id/usb-FTDI_... --baud 2400
  ./probe_inverter.py --port /dev/ttyUSB0 --baud 2400,9600 --cmds QPI QID QPIGS
"""

from __future__ import annotations

import argparse
import glob
import sys
import time
from typing import Iterable, List

try:
    import serial  # type: ignore
except Exception as e:  # pragma: no cover
    print("pyserial is required: pip install pyserial", file=sys.stderr)
    raise


CRC_TABLE = [
    0x0000, 0x1021, 0x2042, 0x3063,
    0x4084, 0x50A5, 0x60C6, 0x70E7,
    0x8108, 0x9129, 0xA14A, 0xB16B,
    0xC18C, 0xD1AD, 0xE1CE, 0xF1EF,
]


def crc_pi(data: bytes) -> tuple[int, int]:
    crc = 0
    for c in data:
        da = ((crc >> 8) & 0xFF) >> 4
        crc = (crc << 4) & 0xFFFF
        index = da ^ (c >> 4)
        crc ^= CRC_TABLE[index]

        da = ((crc >> 8) & 0xFF) >> 4
        crc = (crc << 4) & 0xFFFF
        index = da ^ (c & 0x0F)
        crc ^= CRC_TABLE[index]

    lo = crc & 0xFF
    hi = (crc >> 8) & 0xFF
    if lo in (0x28, 0x0D, 0x0A, 0x00):
        lo += 1
    if hi in (0x28, 0x0D, 0x0A, 0x00):
        hi += 1
    return hi, lo


def build_command(cmd: str) -> bytes:
    body = cmd.encode("utf-8")
    hi, lo = crc_pi(body)
    return body + bytes([hi, lo, 13])


def discover_default_port() -> str:
    by_id = sorted(glob.glob("/dev/serial/by-id/*"))
    if by_id:
        return by_id[0]
    return "/dev/ttyUSB0"


def parse_bauds(v: str) -> List[int]:
    parts = [p.strip() for p in v.replace(";", ",").split(",") if p.strip()]
    return [int(p) for p in parts] if parts else [2400]


def read_until_cr(ser: serial.Serial, timeout: float = 1.5) -> bytes:
    end = time.time() + timeout
    buf = bytearray()
    while time.time() < end:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
            if b"\r" in buf:
                break
        else:
            time.sleep(0.02)
    return bytes(buf)


def run_probe(port: str, bauds: Iterable[int], cmds: Iterable[str], timeout: float, delay: float, toggle: bool, repeat: int) -> int:
    rc_any = 1
    for baud in bauds:
        try:
            print(f"\n=== {port} @ {baud} ===")
            with serial.Serial(port, baudrate=baud, timeout=timeout) as ser:
                if toggle:
                    ser.dtr = False
                    ser.rts = False
                    time.sleep(0.05)
                    ser.dtr = True
                    ser.rts = True
                    time.sleep(0.05)
                for _ in range(repeat):
                    for cmd in cmds:
                        pkt = build_command(cmd)
                        ser.reset_input_buffer(); ser.reset_output_buffer()
                        ser.write(pkt)
                        time.sleep(delay)
                        raw = read_until_cr(ser, timeout)
                        try:
                            text = raw.decode("utf-8", errors="ignore").strip()
                        except Exception:
                            text = raw.hex()
                        print(f"{cmd}: {text}")
                        if text:
                            rc_any = 0
        except Exception as e:
            print(f"{baud} error: {e}")
    return rc_any


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="Probe EASUN/Voltronic inverter over serial (PI protocol)")
    ap.add_argument("--port", default=discover_default_port(), help="Serial device path (default: autodetect by-id or /dev/ttyUSB0)")
    ap.add_argument("--baud", default="2400", help="Baud rate or comma-separated list (e.g., '2400,9600')")
    ap.add_argument("--timeout", type=float, default=1.5, help="Read timeout seconds")
    ap.add_argument("--delay", type=float, default=0.15, help="Delay after write before read")
    ap.add_argument("--cmds", nargs="*", default=["QPI", "QID", "QPIGS"], help="Commands to send")
    ap.add_argument("--no-toggle", action="store_true", help="Do not toggle DTR/RTS before sending")
    ap.add_argument("--repeat", type=int, default=1, help="Repeat each command N times")
    args = ap.parse_args(argv)

    bauds = parse_bauds(args.baud)
    toggle = not args.no_toggle
    return run_probe(args.port, bauds, args.cmds, args.timeout, args.delay, toggle, args.repeat)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

