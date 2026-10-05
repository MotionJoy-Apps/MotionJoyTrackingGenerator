"""Standalone FreeD (D1) packet encoder.

29-byte UDP payload, big-endian:

    byte  0      0xD1 (message type D1 - camera position/orientation)
    byte  1      camera ID
    bytes 2-10   pan, tilt, roll  - 24-bit signed, degrees * 32768
    bytes 11-19  x, y, z          - 24-bit signed, 1/64 mm (metres * 64000)
    bytes 20-22  zoom             - 24-bit unsigned
    bytes 23-25  focus            - 24-bit unsigned
    bytes 26-27  user-defined     - 16-bit unsigned (0xFFFF = unused)
    byte  28     checksum         - (0x40 - sum(bytes 0-27)) & 0xFF

Zoom and focus are written as ``value * 100``, clamped to 24 bits.
"""

from __future__ import annotations

from opentrackio_encoder import PoseLensSample

ROTATION_SCALE = 32768.0
POSITION_SCALE = 64000.0  # metres -> 1/64 mm
ZOOM_FOCUS_SCALE = 100.0


def _signed24(value: float) -> bytes:
    i = max(min(int(round(value)), 8388607), -8388608)
    return i.to_bytes(3, "big", signed=True)


def _unsigned24(value: float) -> bytes:
    i = max(min(int(round(value)), 0xFFFFFF), 0)
    return i.to_bytes(3, "big", signed=False)


def freed_checksum(payload: bytes) -> int:
    return (0x40 - (sum(payload) & 0xFF)) & 0xFF


def encode_freed_packet(sample: PoseLensSample, *, camera_id: int = 1) -> bytes:
    payload = bytearray(29)
    payload[0] = 0xD1
    payload[1] = camera_id & 0xFF
    payload[2:5] = _signed24(sample.pan * ROTATION_SCALE)
    payload[5:8] = _signed24(sample.tilt * ROTATION_SCALE)
    payload[8:11] = _signed24(sample.roll * ROTATION_SCALE)
    payload[11:14] = _signed24(sample.trans_x * POSITION_SCALE)
    payload[14:17] = _signed24(sample.trans_y * POSITION_SCALE)
    payload[17:20] = _signed24(sample.trans_z * POSITION_SCALE)
    payload[20:23] = _unsigned24(sample.zoom * ZOOM_FOCUS_SCALE)
    payload[23:26] = _unsigned24(sample.focus_distance * ZOOM_FOCUS_SCALE)
    payload[26:28] = b"\xff\xff"
    payload[28] = freed_checksum(payload[:28])
    return bytes(payload)
