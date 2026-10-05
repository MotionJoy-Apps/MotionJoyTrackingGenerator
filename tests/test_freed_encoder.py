import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from freed_encoder import encode_freed_packet
from opentrackio_encoder import PoseLensSample


class FreeDEncoderTests(unittest.TestCase):
    def test_layout_and_checksum(self):
        s = PoseLensSample(pan=90.0, tilt=-45.0, roll=1.0, trans_x=1.0, trans_y=-2.0, trans_z=0.5, zoom=10.0, focus_distance=2.0)
        p = encode_freed_packet(s, camera_id=3)
        self.assertEqual(len(p), 29)
        self.assertEqual(p[0], 0xD1)
        self.assertEqual(p[1], 3)
        self.assertEqual(int.from_bytes(p[2:5], "big", signed=True), 90 * 32768)
        self.assertEqual(int.from_bytes(p[5:8], "big", signed=True), -45 * 32768)
        self.assertEqual(int.from_bytes(p[11:14], "big", signed=True), 64000)
        self.assertEqual(int.from_bytes(p[14:17], "big", signed=True), -128000)
        self.assertEqual(int.from_bytes(p[20:23], "big"), 1000)
        self.assertEqual(int.from_bytes(p[23:26], "big"), 200)
        self.assertEqual((sum(p[:28]) + p[28]) & 0xFF, 0x40)

    def test_clamps(self):
        p = encode_freed_packet(PoseLensSample(trans_x=1e9, zoom=-5.0))
        self.assertEqual(int.from_bytes(p[11:14], "big", signed=True), 8388607)
        self.assertEqual(int.from_bytes(p[20:23], "big"), 0)


if __name__ == "__main__":
    unittest.main()
