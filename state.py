"""Shared, thread-safe application state.

Tkinter variables must only be touched on the main thread, so the UI
mirrors its field values into this plain-Python, lock-protected object.
The sender thread (and the Manual/Bounce motion sources it drives) reads
only from here - never from Tk widgets directly.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from opentrackio_encoder import PoseLensSample

# Fields that can be driven manually and/or bounced. Each maps to the
# corresponding PoseLensSample attribute name.
BOUNCE_FIELDS = [
    "trans_x", "trans_y", "trans_z",
    "pan", "tilt", "roll",
    "zoom", "focus_distance", "iris_fstop",
    "k1", "k2", "k3", "p1", "p2",
]

PROTO_OPENTRACKIO = "opentrackio"
PROTO_FREED = "freed"
DEFAULT_PORTS = {PROTO_OPENTRACKIO: 4242, PROTO_FREED: 40000}

MODE_MANUAL = "manual"
MODE_ORBIT = "orbit"
MODE_BOUNCE = "bounce"
MODE_MOTION = "motion"


@dataclass
class FieldRange:
    from_value: float = 0.0
    to_value: float = 1.0
    step: float = 0.01


class AppState:
    """Live snapshot of every UI field, guarded by a single lock."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.ip = "127.0.0.1"
        self.ports = dict(DEFAULT_PORTS)
        self.enabled: set[str] = {PROTO_OPENTRACKIO}
        self.freed_camera_id = 1
        self.local_ip = ""  # "" = let the OS pick the outbound interface
        self.rate = 60.0
        self.mode = MODE_MANUAL
        self.motion_kind = "dolly-front"
        self.dolly_distance = 5.0

        self.manual = PoseLensSample()
        self.ranges: dict[str, FieldRange] = {name: FieldRange() for name in BOUNCE_FIELDS}

        # Latest sample actually sent, for the UI's read-only display refresh.
        self.last_sample: PoseLensSample | None = None
        self.last_seq: int = 0
        self.last_timecode: str = ""
        self.last_error: str = ""

    def snapshot_manual(self) -> PoseLensSample:
        with self._lock:
            return PoseLensSample(**vars(self.manual))

    def set_manual_field(self, name: str, value: float) -> None:
        with self._lock:
            setattr(self.manual, name, value)

    def get_range(self, name: str) -> FieldRange:
        with self._lock:
            r = self.ranges[name]
            return FieldRange(r.from_value, r.to_value, r.step)

    def set_range(self, name: str, *, from_value: float | None = None, to_value: float | None = None, step: float | None = None) -> None:
        with self._lock:
            r = self.ranges[name]
            if from_value is not None:
                r.from_value = from_value
            if to_value is not None:
                r.to_value = to_value
            if step is not None:
                r.step = step

    def set_motion(self, *, kind: str | None = None,
                   dolly_distance: float | None = None) -> None:
        with self._lock:
            if kind is not None:
                self.motion_kind = kind
            if dolly_distance is not None:
                self.dolly_distance = max(0.5, min(50.0, dolly_distance))

    def set_last_sample(self, sample: PoseLensSample, seq: int, timecode: str) -> None:
        with self._lock:
            self.last_sample = sample
            self.last_seq = seq
            self.last_timecode = timecode

    def get_last_sample(self) -> tuple[PoseLensSample | None, int, str]:
        with self._lock:
            return self.last_sample, self.last_seq, self.last_timecode

    def set_last_error(self, message: str) -> None:
        with self._lock:
            self.last_error = message

    def get_last_error(self) -> str:
        with self._lock:
            return self.last_error
