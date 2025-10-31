#!/usr/bin/env python3
import logging

logger = logging.getLogger(__name__)


def crc_pi(data_bytes: bytes) -> tuple[int, int]:
    """Voltronic/PI protocol CRC (same as used in your Solar prototype)."""
    crc = 0
    da = 0
    crc_ta = [
        0x0000, 0x1021, 0x2042, 0x3063,
        0x4084, 0x50A5, 0x60C6, 0x70E7,
        0x8108, 0x9129, 0xA14A, 0xB16B,
        0xC18C, 0xD1AD, 0xE1CE, 0xF1EF,
    ]
    for c in data_bytes:
        if isinstance(c, str):
            c = ord(c)
        da = ((crc >> 8) & 0xFF) >> 4
        crc = (crc << 4) & 0xFFFF
        index = da ^ (c >> 4)
        crc ^= crc_ta[index]
        da = ((crc >> 8) & 0xFF) >> 4
        crc = (crc << 4) & 0xFFFF
        index = da ^ (c & 0x0F)
        crc ^= crc_ta[index]

    crc_low = crc & 0xFF
    crc_high = (crc >> 8) & 0xFF
    # Avoid control chars
    if crc_low in (0x28, 0x0D, 0x0A, 0x00):
        crc_low += 1
    if crc_high in (0x28, 0x0D, 0x0A, 0x00):
        crc_high += 1
    return crc_high, crc_low


def build_command(cmd: str) -> bytes:
    """Build full command with CRC and CR terminator."""
    body = bytes(cmd, 'utf-8')
    ch, cl = crc_pi(body)
    return body + bytes([ch, cl, 13])
