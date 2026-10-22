"""Motion sources: Manual passthrough, Orbit animation, Bounce triangle-wave.

Each source exposes ``tick() -> PoseLensSample``. OrbitSource is a
pure-Python (no numpy) orbiting-camera-looking-at-origin
animation, expressed in metres as OpenTrackIO requires. BounceSource is a
triangle-wave auto-sweep between per-field bounds.
motion_presets.py adds rig-move presets (dolly, crane, handheld)
built on the same look-at math.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Protocol

from opentrackio_encoder import PoseLensSample
from state import BOUNCE_FIELDS, AppState


class MotionSource(Protocol):
    def tick(self) -> PoseLensSample: ...


class ManualSource:
    """Returns whatever the user currently has dialed into the UI."""

    def __init__(self, state: AppState) -> None:
        self._state = state

    def tick(self) -> PoseLensSample:
        return self._state.snapshot_manual()


def _vec_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _vec_scale(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _vec_cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _vec_norm(a):
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


def _vec_normalize(a):
    n = _vec_norm(a)
    if n < 1e-9:
        return a
    return (a[0] / n, a[1] / n, a[2] / n)


def _mat3_from_cols(c0, c1, c2):
    return (c0, c1, c2)


def _mat3_mul(a, b):
    """Multiply two 3x3 matrices given as (col0, col1, col2) tuples of columns."""

    def col_mul(bcol):
        return (
            a[0][0] * bcol[0] + a[1][0] * bcol[1] + a[2][0] * bcol[2],
            a[0][1] * bcol[0] + a[1][1] * bcol[1] + a[2][1] * bcol[2],
            a[0][2] * bcol[0] + a[1][2] * bcol[1] + a[2][2] * bcol[2],
        )

    return _mat3_from_cols(col_mul(b[0]), col_mul(b[1]), col_mul(b[2]))


def _axis_angle_matrix(axis, angle):
    ax = _vec_normalize(axis)
    ca, sa = math.cos(angle), math.sin(angle)
    x, y, z = ax
    # Columns of the rotation matrix.
    c0 = (ca + x * x * (1 - ca), x * y * (1 - ca) + z * sa, x * z * (1 - ca) - y * sa)
    c1 = (y * x * (1 - ca) - z * sa, ca + y * y * (1 - ca), y * z * (1 - ca) + x * sa)
    c2 = (z * x * (1 - ca) + y * sa, z * y * (1 - ca) - x * sa, ca + z * z * (1 - ca))
    return _mat3_from_cols(c0, c1, c2)


def _matrix_to_euler_zyx(m):
    """Extract (rx, ry, rz) Euler angles (radians) from a rotation matrix
    given as (col0, col1, col2), using ZYX convention (matches
    backend/network.py's ``_matrix_to_euler(..., "ZYX")``)."""

    m00, m01, m02 = m[0][0], m[1][0], m[2][0]
    m10, m11, m12 = m[0][1], m[1][1], m[2][1]
    m20, m21, m22 = m[0][2], m[1][2], m[2][2]

    ry = math.asin(max(-1.0, min(1.0, -m20)))
    if abs(m20) < 0.9999999:
        rx = math.atan2(m21, m22)
        rz = math.atan2(m10, m00)
    else:
        rx = math.atan2(-m12, m11)
        rz = 0.0
    return rx, ry, rz


class OrbitSource:
    """Camera orbiting the origin on a slowly breathing sphere, always
    looking back at the origin. FIZ/distortion fields are frozen at
    whatever the Manual fields currently hold."""

    RADIUS_BASE_M = 3.0
    RADIUS_AMPLITUDE_M = 1.5

    def __init__(self, state: AppState, *, interval: float) -> None:
        self._state = state
        self._interval = interval
        self._elapsed = 0.0

    def tick(self) -> PoseLensSample:
        elapsed = self._elapsed
        self._elapsed += self._interval

        r = self.RADIUS_BASE_M + self.RADIUS_AMPLITUDE_M * math.sin(0.1 * elapsed)
        theta = elapsed * 0.5
        phi = 0.3 * math.sin(0.05 * elapsed)
        phi = max(min(phi, math.radians(85.0)), math.radians(-85.0))

        cos_phi = math.cos(phi)
        x = r * cos_phi * math.cos(theta)
        y = r * cos_phi * math.sin(theta)
        z = r * math.sin(phi)

        cam = (x, y, z)
        forward = _vec_normalize(_vec_scale(cam, -1.0))
        up_ref = (0.0, 0.0, 1.0)
        right = _vec_cross(up_ref, forward)
        if _vec_norm(right) < 1e-6:
            right = (1.0, 0.0, 0.0)
        else:
            right = _vec_normalize(right)
        up = _vec_cross(forward, right)

        rot = _mat3_from_cols(forward, right, up)
        rx, ry, rz = _matrix_to_euler_zyx(rot)
        pan = math.degrees(rz)
        tilt = math.degrees(ry)
        roll = math.degrees(rx)

        manual = self._state.snapshot_manual()
        return replace(
            manual,
            trans_x=x,
            trans_y=y,
            trans_z=z,
            pan=pan,
            tilt=tilt,
            roll=roll,
        )


@dataclass
class _Sweep:
    """Position and heading (+1 rising, -1 falling) of one bouncing field."""

    pos: float
    heading: int = 1


class BounceSource:
    """Sweeps every field back and forth between its From/To bounds.

    Each tick moves a field by its Step in the current heading. A move that
    would pass a bound is clamped to that bound and the heading reverses,
    so the field traces a triangle wave."""

    def __init__(self, state: AppState) -> None:
        self._state = state
        self._sweeps = {name: _Sweep(state.get_range(name).from_value) for name in BOUNCE_FIELDS}

    def tick(self) -> PoseLensSample:
        manual = self._state.snapshot_manual()
        updated = {}
        for name, sweep in self._sweeps.items():
            r = self._state.get_range(name)
            lo, hi = sorted((r.from_value, r.to_value))
            nxt = sweep.pos + sweep.heading * abs(r.step)
            if nxt >= hi:
                nxt, sweep.heading = hi, -1
            elif nxt <= lo:
                nxt, sweep.heading = lo, 1
            sweep.pos = nxt
            updated[name] = nxt
        return replace(manual, **updated)
