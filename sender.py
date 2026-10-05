"""Background UDP sender thread for the OpenTrackIO simulator."""

from __future__ import annotations

import logging
import socket
import threading
import time
import uuid
from typing import Callable

from motion import MotionSource
from freed_encoder import encode_freed_packet
from opentrackio_encoder import build_timecode_block, encode_packet, rate_to_fraction
from state import PROTO_FREED, PROTO_OPENTRACKIO, AppState

logger = logging.getLogger("otio_sim.sender")


class SenderThread(threading.Thread):
    """Continuously encodes/sends OpenTrackIO packets from ``source_fn()``
    until stopped. Never dies on a send error - it logs and continues."""

    def __init__(
        self,
        *,
        state: AppState,
        ip: str,
        targets: dict[str, int],
        freed_camera_id: int = 1,
        local_ip: str = "",
        rate_fn: Callable[[], float],
        source_fn: Callable[[], MotionSource],
    ) -> None:
        """``targets`` maps each enabled protocol to its destination port."""
        super().__init__(daemon=True)
        self._state = state
        self._ip = ip
        self._targets = dict(targets)
        self._freed_camera_id = freed_camera_id
        self._local_ip = local_ip
        self._rate_fn = rate_fn
        self._source_fn = source_fn
        self._stop_event = threading.Event()
        self._seq = 0
        self._source_id = f"urn:uuid:{uuid.uuid4()}"
        self._sock: socket.socket | None = None

        now = time.localtime()
        self._tc_h, self._tc_m, self._tc_s, self._tc_f = now.tm_hour, now.tm_min, now.tm_sec, 0

    def _advance_timecode(self, fps_int: int) -> None:
        self._tc_f += 1
        if fps_int and self._tc_f >= fps_int:
            self._tc_f = 0
            self._tc_s += 1
            if self._tc_s >= 60:
                self._tc_s = 0
                self._tc_m += 1
                if self._tc_m >= 60:
                    self._tc_m = 0
                    self._tc_h = (self._tc_h + 1) % 24

    def run(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if self._local_ip:
            try:
                self._sock.bind((self._local_ip, 0))
            except OSError as exc:
                logger.warning("Bind to %s failed: %s", self._local_ip, exc)
                self._state.set_last_error(f"Bind to {self._local_ip} failed: {exc}")
        try:
            while not self._stop_event.is_set():
                rate = self._rate_fn()
                interval = 1.0 / rate if rate > 0 else 0.0

                try:
                    source = self._source_fn()
                    sample = source.tick()

                    fr_num, fr_denom = rate_to_fraction(rate if rate > 0 else 1.0)
                    fps_int = round(rate) if rate > 0 else 1

                    # Send every enabled protocol; a failure on one must not
                    # stop the other, so collect errors and report after.
                    errors: list[str] = []
                    for proto, port in self._targets.items():
                        try:
                            if proto == PROTO_OPENTRACKIO:
                                tc_block = build_timecode_block(
                                    self._tc_h, self._tc_m, self._tc_s, self._tc_f,
                                    fr_num=fr_num, fr_denom=fr_denom,
                                )
                                packet = encode_packet(
                                    sample,
                                    seq=self._seq,
                                    sample_rate=(fr_num, fr_denom),
                                    source_id=self._source_id,
                                    timecode_block=tc_block,
                                )
                            elif proto == PROTO_FREED:
                                packet = encode_freed_packet(sample, camera_id=self._freed_camera_id)
                            else:
                                continue
                            self._sock.sendto(packet, (self._ip, port))
                        except OSError as exc:
                            logger.warning("Send (%s) failed: %s", proto, exc)
                            errors.append(f"{proto}: {exc}")
                    self._state.set_last_error("Send failed: " + "; ".join(errors) if errors else "")

                    tc_str = f"{self._tc_h:02}:{self._tc_m:02}:{self._tc_s:02}:{self._tc_f:02}"
                    self._state.set_last_sample(sample, self._seq, tc_str)

                    self._advance_timecode(fps_int)
                    self._seq = (self._seq + 1) & 0xFFFF
                except Exception:  # noqa: BLE001 - never let one bad tick kill the thread
                    logger.exception("Unexpected error while generating/sending a packet")

                if self._stop_event.wait(timeout=interval):
                    break
        finally:
            if self._sock is not None:
                self._sock.close()
                self._sock = None

    def stop(self) -> None:
        self._stop_event.set()
        self.join(timeout=2.0)


def start_sender(
    *,
    state: AppState,
    ip: str,
    targets: dict[str, int],
    freed_camera_id: int = 1,
    local_ip: str = "",
    rate_fn: Callable[[], float],
    source_fn: Callable[[], MotionSource],
) -> SenderThread:
    thread = SenderThread(
        state=state, ip=ip, targets=targets, freed_camera_id=freed_camera_id,
        local_ip=local_ip, rate_fn=rate_fn, source_fn=source_fn,
    )
    thread.start()
    return thread
