"""Tests for the OrbitSource euler-column fix and the Motion presets.

Run: cd motionjoy repo && python3 -m unittest tests.test_motion_presets -v
(unit tests, no pytest dependency.)
"""

from __future__ import annotations

import math
import unittest

from motion import OrbitSource
from motion_presets import MOTION_KINDS, PERIOD_SECONDS, MotionPresetSource
from state import AppState

_INTERVAL = 1.0 / 60.0


def _state() -> AppState:
    s = AppState()
    s.motion_kind = "dolly-front"
    s.dolly_distance = 5.0
    return s


def _run(src, n: int):
    return [src.tick() for _ in range(n)]


def _spread(vals):
    return max(vals) - min(vals)


class TestOrbitSourceTilt(unittest.TestCase):
    """Regression: the look-at columns were built in (right, up, fwd) order
    instead of (fwd, right, up), which transposed the rotation and sent the
    camera's elevation into roll while tilt stayed exactly 0."""

    def test_orbit_tilt_sweeps(self):
        src = OrbitSource(_state(), interval=_INTERVAL)
        tilts = [s.tilt for s in _run(src, 7200)]  # 120 s
        self.assertGreater(_spread(tilts), 2.0,
                           f"orbit tilt spread too small: {_spread(tilts)}")

    def test_orbit_pan_sweeps(self):
        src = OrbitSource(_state(), interval=_INTERVAL)
        pans = [s.pan for s in _run(src, 7200)]
        self.assertGreater(_spread(pans), 180.0)

    def test_orbit_roll_bounded(self):
        src = OrbitSource(_state(), interval=_INTERVAL)
        rolls = [s.roll for s in _run(src, 7200)]
        self.assertLess(_spread(rolls), 25.0,
                        f"orbit roll blew up: {_spread(rolls)}")


class TestMotionPresets(unittest.TestCase):
    N = int(PERIOD_SECONDS * 60)  # one full period at 60 Hz

    def _src(self, kind: str) -> MotionPresetSource:
        s = _state()
        s.motion_kind = kind
        return MotionPresetSource(s, interval=_INTERVAL, kind=kind)

    def test_dolly_front_back_change_distance(self):
        for kind in ("dolly-front", "dolly-back"):
            samples = _run(self._src(kind), self.N)
            dists = [math.sqrt(s.trans_x**2 + s.trans_y**2 + s.trans_z**2)
                     for s in samples]
            self.assertGreater(_spread(dists), 1.0, f"{kind} distance static")

    def test_dolly_level_and_pan_follows(self):
        for kind in ("dolly-left", "dolly-right"):
            samples = _run(self._src(kind), self.N)
            self.assertLess(_spread([s.trans_z for s in samples]), 0.01)
            self.assertLess(_spread([s.roll for s in samples]), 2.0)
            self.assertGreater(_spread([s.pan for s in samples]), 2.0,
                               f"{kind} pan static")

    def test_crane_rises_and_tilts_down(self):
        samples = _run(self._src("crane"), self.N)
        self.assertGreater(_spread([s.trans_z for s in samples]), 2.0)
        tilts = [s.tilt for s in samples]
        self.assertGreater(_spread(tilts), 20.0)
        self.assertGreater(max(tilts), 30.0,
                           "crane should look down at the top of the sweep")

    def test_handheld_jitters_in_place(self):
        samples = _run(self._src("handheld"), self.N)
        xs = [s.trans_x for s in samples]
        ys = [s.trans_y for s in samples]
        self.assertLess(_spread(xs), 0.1)
        self.assertLess(_spread(ys), 0.1)
        for attr in ("pan", "tilt", "roll"):
            self.assertGreater(_spread([getattr(s, attr) for s in samples]),
                               0.2, f"handheld {attr} static")

    def test_live_kind_switch(self):
        s = _state()
        src = MotionPresetSource(s, interval=_INTERVAL, kind="dolly-front")
        _run(src, 10)
        s.motion_kind = "crane"
        mid = _run(src, 10)
        s.motion_kind = "handheld"
        _run(src, 10)
        zs = [m.trans_z for m in mid]
        # crane phase: height within its sweep band
        self.assertTrue(all(0.4 < z < 4.6 for z in zs), f"crane band: {zs}")

    def test_live_distance_change(self):
        s = _state()
        s.motion_kind = "dolly-front"
        src = MotionPresetSource(s, interval=_INTERVAL, kind="dolly-front")
        _run(src, 60)
        big = math.sqrt(src.tick().trans_y ** 2)  # distance with 5 m dolly
        s.dolly_distance = 0.5
        small = math.sqrt(src.tick().trans_y ** 2)
        self.assertLess(small, big,
                        "reducing dolly distance should move the rig closer")


if __name__ == "__main__":
    unittest.main()


class RollBehaviorTests(unittest.TestCase):
    def test_orbit_passes_manual_roll(self):
        st = AppState()
        st.set_manual_field("roll", 10.0)
        src = OrbitSource(st, interval=1 / 60)
        rolls = [src.tick().roll for _ in range(120)]
        self.assertTrue(all(r == 10.0 for r in rolls))

    def test_orbit_roll_zero_by_default(self):
        src = OrbitSource(AppState(), interval=1 / 60)
        rolls = [src.tick().roll for _ in range(60)]
        self.assertTrue(all(r == 0.0 for r in rolls))

    def test_handheld_jitter_includes_roll(self):
        st = AppState()
        st.motion_kind = "handheld"
        src = MotionPresetSource(st, kind="handheld", interval=1 / 60)
        rolls = [src.tick().roll for _ in range(240)]
        self.assertGreater(max(abs(r) for r in rolls), 0.1)
