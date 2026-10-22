"""Motion (rig-move) presets for the MotionJoy Tracking Generator.

Each preset drives the camera rig from a fixed starting point on the set
looking at the target at the world origin, using the SAME basis/columns
and euler math as (the fixed) motion.OrbitSource, so the pan/tilt/roll
sent to OpenTrackIO are what the gimbal would actually make for that move.

Preset kinds (``MOTION_KINDS``):
  dolly-front / dolly-back: move along the track, toward / away from
      the target, at constant eye height.
  dolly-left / dolly-right: move sideways relative to the rig, straddling
      the base point; the pan follows the lateral offset.
  crane: rise and look down at the target.
  handheld: organic jitter around the base frame - three incommensurate
      sines per position axis and per tilt/pan/roll axis.

All presets ping-pong (ease-in/out via smoothstep) over PERIOD_SECONDS so
the loop turnaround has no rate click. Presets read ``state.motion_kind``
and ``state.dolly_distance`` every tick, so UI changes take effect live
without re-instantiating the source.
"""

from __future__ import annotations

import math
from dataclasses import replace

from opentrackio_encoder import PoseLensSample
from state import AppState
from motion import _mat3_from_cols, _matrix_to_euler_zyx

PERIOD_SECONDS = 10.0

# Rig starting position looking at the target at the origin.
BASE_POS_X = 0.0
BASE_POS_Y = 6.0
BASE_HEIGHT = 1.6  # m, dolly eye height

# Crane sweep bounds (m).
CRANE_HEIGHT_FROM = 0.5
CRANE_HEIGHT_TO = 4.5

# Handheld amplitudes.
HANDHELD_POS_AMP = 0.012  # m per position axis
HANDHELD_ROT_AMP = 0.3    # degrees per pan/tilt/roll axis

MOTION_KINDS = [
    "dolly-front", "dolly-back", "dolly-left", "dolly-right",
    "crane", "handheld",
]

# (start_frac, end_frac) of state.dolly_distance, applied along each
# dolly axis relative to the target at the origin. Front approaches,
# back retreats, left/right straddle the base point on the lateral axis.
DOLLY_RANGES = {
    "dolly-front": (1.0, 0.4),
    "dolly-back": (0.4, 1.0),
    "dolly-left": (-0.5, 0.5),
    "dolly-right": (0.5, -0.5),
}

# World-space axis (dx, dy) for each dolly preset. +Y runs from the rig
# start toward the target; +X is the lateral (sideways) axis.
DOLLY_AXES = {
    "dolly-front": (0.0, 1.0),
    "dolly-back": (0.0, 1.0),
    "dolly-left": (1.0, 0.0),
    "dolly-right": (1.0, 0.0),
}


def _ping_pong(u: float) -> float:
    """Triangle wave in [0,1]: 0->1 for u in [0,0.5], 1->0 after."""
    u = u % 1.0
    return u * 2.0 if u < 0.5 else (1.0 - u) * 2.0


def _smoothstep(t: float) -> float:
    """Ease the turnaround so velocity passes through zero (no click)."""
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def _rig_to_origin_angles(pos: tuple[float, float, float]) -> tuple[float, float, float]:
    """(pan, tilt, roll) in degrees for a rig at ``pos`` looking at the
    origin with world up = +Z. Reuses OrbitSource's helpers so presets and
    the Orbit mode agree exactly."""
    px, py, pz = pos
    n = math.sqrt(px * px + py * py + pz * pz)
    if n < 1e-9:
        return 0.0, 0.0, 0.0
    forward = (-px / n, -py / n, -pz / n)
    up_ref = (0.0, 0.0, 1.0)
    right = (up_ref[1] * forward[2] - up_ref[2] * forward[1],
             up_ref[2] * forward[0] - up_ref[0] * forward[2],
             up_ref[0] * forward[1] - up_ref[1] * forward[0])
    rn = math.sqrt(right[0]**2 + right[1]**2 + right[2]**2)
    if rn < 1e-9:
        right = (1.0, 0.0, 0.0)
    else:
        right = (right[0] / rn, right[1] / rn, right[2] / rn)
    up = (forward[1] * right[2] - forward[2] * right[1],
          forward[2] * right[0] - forward[0] * right[2],
          forward[0] * right[1] - forward[1] * right[0])
    # Camera axes as COLUMNS, order (fwd, right, up) - same as OrbitSource.
    rot = _mat3_from_cols(forward, right, up)
    rx, ry, rz = _matrix_to_euler_zyx(rot)
    return math.degrees(rz), math.degrees(ry), math.degrees(rx)


class MotionPresetSource:
    """Drives one rig-move preset; call tick() once per frame."""

    def __init__(self, state: AppState, *, interval: float, kind: str) -> None:
        self._state = state
        self._interval = interval
        self._kind = kind
        self._elapsed = 0.0
        self._pos_phase = 0.0
        self._rot_phase = 0.0

    def tick(self) -> PoseLensSample:
        self._elapsed += self._interval
        self._pos_phase += self._interval * (2.0 * math.pi / PERIOD_SECONDS)
        self._rot_phase += self._interval * (2.0 * math.pi / (PERIOD_SECONDS * 2.0))

        # Live UI values.
        kind = self._state.motion_kind if self._state.motion_kind in MOTION_KINDS else self._kind
        distance = self._state.dolly_distance
        u = (self._elapsed / PERIOD_SECONDS) % 1.0
        t = _smoothstep(_ping_pong(u))

        if kind in DOLLY_RANGES:
            sf, se = DOLLY_RANGES[kind]
            frac = sf + (se - sf) * t
            ax = DOLLY_AXES[kind]
            pos = (BASE_POS_X + ax[0] * frac * distance,
                   BASE_POS_Y + ax[1] * frac * distance,
                   BASE_HEIGHT)
            pan, tilt, roll = _rig_to_origin_angles(pos)
        elif kind == "crane":
            h = CRANE_HEIGHT_FROM + (CRANE_HEIGHT_TO - CRANE_HEIGHT_FROM) * t
            pos = (BASE_POS_X, BASE_POS_Y, h)
            pan, tilt, roll = _rig_to_origin_angles(pos)
        else:  # handheld
            p, q = self._pos_phase, self._rot_phase
            jx = (math.sin(2.1 * p) + 0.6 * math.sin(4.7 * p + 1.1)
                  + 0.3 * math.sin(7.3 * p + 0.5))
            jy = (math.sin(2.4 * p + 0.7) + 0.6 * math.sin(5.1 * p + 2.3)
                  + 0.3 * math.sin(8.2 * p + 1.9))
            jz = (math.sin(1.9 * p + 2.1) + 0.6 * math.sin(4.2 * p + 0.3)
                  + 0.3 * math.sin(7.9 * p + 1.5))
            pos = (BASE_POS_X + HANDHELD_POS_AMP * jx,
                   BASE_POS_Y + HANDHELD_POS_AMP * jy,
                   BASE_HEIGHT + HANDHELD_POS_AMP * jz)
            jpan = (math.sin(1.4 * q) + 0.5 * math.sin(3.1 * q + 2.3)
                    + 0.3 * math.sin(5.3 * q + 1.1))
            jtilt = (math.sin(1.7 * q + 1.5) + 0.5 * math.sin(3.7 * q + 0.2)
                     + 0.3 * math.sin(5.9 * q + 2.7))
            jroll = (math.sin(1.2 * q + 0.4) + 0.5 * math.sin(2.9 * q + 1.9)
                     + 0.3 * math.sin(4.8 * q + 3.3))
            pan, tilt, roll = _rig_to_origin_angles(pos)
            pan += HANDHELD_ROT_AMP * jpan
            tilt += HANDHELD_ROT_AMP * jtilt
            roll += HANDHELD_ROT_AMP * jroll

        manual = self._state.snapshot_manual()
        return replace(manual,
                       trans_x=pos[0], trans_y=pos[1], trans_z=pos[2],
                       pan=pan, tilt=tilt, roll=roll)
