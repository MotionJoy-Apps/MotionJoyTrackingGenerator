"""Standalone OpenTrackIO packet encoder.

Wire format: a 16-byte binary "OTrk" segmentation header (single-segment
only, per the SMPTE RIS OpenTrackIO transport spec) followed by a UTF-8
JSON payload. This module is self-contained so the app can be run and
distributed on its own.

This encoder applies no axis remapping or k-coefficient scaling:
values are emitted exactly as
provided, in OpenTrackIO's own convention (metres, X-forward/Y-left;
degrees for pan/tilt/roll).
"""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass
from typing import Any

FOCUS_INFINITY_SENTINEL = 1000.0


def fletcher16(data: bytes) -> int:
    """Return the 16-bit Fletcher checksum of ``data``."""

    sum1 = 0
    sum2 = 0
    for b in data:
        sum1 = (sum1 + b) & 0xFF
        sum2 = (sum2 + sum1) & 0xFF
    return (sum2 << 8) | sum1


@dataclass
class PoseLensSample:
    """A single 6DOF pose + FIZ + lens-distortion sample."""

    trans_x: float = 0.0
    trans_y: float = 0.0
    trans_z: float = 0.0
    pan: float = 0.0
    tilt: float = 0.0
    roll: float = 0.0

    focus_distance: float = 0.0
    iris_fstop: float = 0.0
    zoom: float = 0.0

    focal_length_x: float = 0.0
    focal_length_y: float = 0.0
    pinhole_focal_length: float = 0.0
    projection_offset_x: float = 0.0
    projection_offset_y: float = 0.0
    entrance_pupil_offset: float = 0.0

    k1: float = 0.0
    k2: float = 0.0
    k3: float = 0.0
    p1: float = 0.0
    p2: float = 0.0
    overscan: float = 0.0

    include_lens_block: bool = True


def build_timecode_block(h: int, m: int, s: int, f: int, *, fr_num: int, fr_denom: int, drop_frame: bool = False) -> dict:
    return {
        "hours": h,
        "minutes": m,
        "seconds": s,
        "frames": f,
        "subFrame": 0,
        "dropFrame": drop_frame,
        "frameRate": {"num": fr_num, "denom": fr_denom},
    }


def build_payload_dict(
    sample: PoseLensSample,
    *,
    seq: int,
    sample_rate: tuple[int, int],
    source_id: str,
    timecode_block: dict,
    timing_mode: str = "internal",
) -> dict[str, Any]:
    """Build the OpenTrackIO JSON payload dict for ``sample``."""

    fr_num, fr_denom = sample_rate

    data: dict[str, Any] = {
        "protocol": {"name": "OpenTrackIO", "version": [1, 0, 0]},
        "static": {
            "camera": {
                "activeSensorPhysicalDimensions": {"height": 24.0, "width": 36.0},
                "label": "A",
            },
            "lens": {"make": "LensMaker", "model": "Model15"},
        },
        "tracker": {
            "notes": "Simulated sample (MotionJoy Tracking Generator).",
            "recording": False,
            "slate": "A101_A_4",
            "status": "Optical Good",
        },
        "timing": {
            "mode": timing_mode,
            "sampleRate": {"num": fr_num, "denom": fr_denom},
            "timecode": timecode_block,
        },
        "sampleId": f"urn:uuid:{uuid.uuid4()}",
        "sourceId": source_id,
        "sourceNumber": 1,
        "transforms": [
            {
                "translation": {"x": sample.trans_x, "y": sample.trans_y, "z": sample.trans_z},
                "rotation": {"pan": sample.pan, "tilt": sample.tilt, "roll": sample.roll},
                "id": "Camera",
            }
        ],
    }

    if sample.include_lens_block:
        focus_value = sample.focus_distance
        if math.isinf(focus_value):
            focus_value = FOCUS_INFINITY_SENTINEL

        lens: dict[str, Any] = {
            "encoders": {"focus": focus_value, "iris": sample.iris_fstop, "zoom": sample.zoom},
            "projectionOffset": {"x": sample.projection_offset_x, "y": sample.projection_offset_y},
            "pinholeFocalLength": sample.pinhole_focal_length,
            "focalLength": {"x": sample.focal_length_x, "y": sample.focal_length_y},
            "focusDistance": focus_value,
            "fStop": sample.iris_fstop,
            "entrancePupilOffset": sample.entrance_pupil_offset,
            "custom": [sample.focal_length_x, sample.focal_length_y],
            "distortion": [
                {
                    "model": "Brown-Conrady",
                    "radial": [sample.k1, sample.k2, sample.k3],
                    "tangential": [sample.p1, sample.p2],
                    "overscan": sample.overscan,
                }
            ],
        }
        data["lens"] = lens

    return data


def encode_packet(
    sample: PoseLensSample,
    *,
    seq: int,
    sample_rate: tuple[int, int],
    source_id: str,
    timecode_block: dict,
    timing_mode: str = "internal",
) -> bytes:
    """Encode ``sample`` as a full OpenTrackIO UDP packet (header + JSON)."""

    data = build_payload_dict(
        sample,
        seq=seq,
        sample_rate=sample_rate,
        source_id=source_id,
        timecode_block=timecode_block,
        timing_mode=timing_mode,
    )
    payload = json.dumps(data).encode("utf-8")

    identifier = b"OTrk"
    reserved = 0
    encoding = 0x01
    sequence = seq & 0xFFFF
    segment_offset = 0
    last_flag = 1
    length = len(payload)

    header = bytearray(16)
    header[0:4] = identifier
    header[4] = reserved
    header[5] = encoding
    header[6:8] = sequence.to_bytes(2, "big")
    header[8:12] = segment_offset.to_bytes(4, "big")
    header[12] = (last_flag << 7) | ((length >> 8) & 0x7F)
    header[13] = length & 0xFF

    checksum = fletcher16(bytes(header[0:14]) + payload)
    header[14:16] = checksum.to_bytes(2, "big")

    return bytes(header) + payload


def rate_to_fraction(rate: float) -> tuple[int, int]:
    """Convert a frames-per-second float into an OpenTrackIO (num, denom) pair."""

    common_fractional = {
        23.976: (24000, 1001),
        29.97: (30000, 1001),
        59.94: (60000, 1001),
    }
    for approx, fraction in common_fractional.items():
        if abs(rate - approx) < 0.005:
            return fraction
    if float(rate).is_integer():
        return (int(rate), 1)
    return (round(rate), 1)
