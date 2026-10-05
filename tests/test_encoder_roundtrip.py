import json
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motion import BounceSource
from opentrackio_encoder import (
    PoseLensSample,
    build_timecode_block,
    encode_packet,
    fletcher16,
    rate_to_fraction,
)
from state import AppState


class FletcherTests(unittest.TestCase):
    def test_known_vector(self):
        # This is a mod-256 Fletcher-16 variant (mod-256 sums), not the standard
        # mod-255 algorithm -
        # the expected value below is pinned against this implementation.
        self.assertEqual(fletcher16(b"abcde"), 0xC3EF)

    def test_empty(self):
        self.assertEqual(fletcher16(b""), 0)


class EncodePacketTests(unittest.TestCase):
    def _decode(self, packet: bytes):
        self.assertEqual(packet[0:4], b"OTrk")
        self.assertEqual(packet[5], 0x01)
        length = ((packet[12] & 0x7F) << 8) | packet[13]
        payload = packet[16 : 16 + length]
        return json.loads(payload.decode("utf-8"))

    def test_header_and_payload_roundtrip(self):
        sample = PoseLensSample(
            trans_x=1.0, trans_y=2.0, trans_z=3.0,
            pan=10.0, tilt=-5.0, roll=1.5,
            k1=-0.05, k2=0.8, k3=0.01, p1=0.001, p2=-0.002,
        )
        tc = build_timecode_block(1, 2, 3, 4, fr_num=60, fr_denom=1)
        packet = encode_packet(
            sample, seq=42, sample_rate=(60, 1),
            source_id="urn:uuid:test", timecode_block=tc,
        )
        data = self._decode(packet)

        self.assertEqual(data["protocol"]["name"], "OpenTrackIO")
        t = data["transforms"][0]
        self.assertEqual(t["translation"], {"x": 1.0, "y": 2.0, "z": 3.0})
        self.assertEqual(t["rotation"], {"pan": 10.0, "tilt": -5.0, "roll": 1.5})
        dist = data["lens"]["distortion"][0]
        self.assertEqual(dist["radial"], [-0.05, 0.8, 0.01])
        self.assertEqual(dist["tangential"], [0.001, -0.002])
        self.assertEqual(data["timing"]["timecode"]["frames"], 4)

    def test_focus_infinity_sentinel(self):
        sample = PoseLensSample(focus_distance=math.inf)
        tc = build_timecode_block(0, 0, 0, 0, fr_num=60, fr_denom=1)
        packet = encode_packet(sample, seq=0, sample_rate=(60, 1), source_id="urn:uuid:test", timecode_block=tc)
        data = self._decode(packet)
        self.assertEqual(data["lens"]["focusDistance"], 1000.0)

    def test_no_lens_block_when_disabled(self):
        sample = PoseLensSample(include_lens_block=False)
        tc = build_timecode_block(0, 0, 0, 0, fr_num=60, fr_denom=1)
        packet = encode_packet(sample, seq=0, sample_rate=(60, 1), source_id="urn:uuid:test", timecode_block=tc)
        data = self._decode(packet)
        self.assertNotIn("lens", data)


class RateToFractionTests(unittest.TestCase):
    def test_integer_rate(self):
        self.assertEqual(rate_to_fraction(60.0), (60, 1))

    def test_2997(self):
        self.assertEqual(rate_to_fraction(29.97), (30000, 1001))


class BounceBoundaryTests(unittest.TestCase):
    def test_direction_flip_at_upper_bound(self):
        state = AppState()
        state.set_range("pan", from_value=0.0, to_value=1.0, step=0.6)
        source = BounceSource(state)

        first = source.tick()   # 0.0 -> 0.6
        second = source.tick()  # 0.6 -> 1.0 (clamped, flips)
        third = source.tick()   # 1.0 -> 0.4 (descending)

        self.assertAlmostEqual(first.pan, 0.6)
        self.assertAlmostEqual(second.pan, 1.0)
        self.assertLess(third.pan, second.pan)


if __name__ == "__main__":
    unittest.main()
