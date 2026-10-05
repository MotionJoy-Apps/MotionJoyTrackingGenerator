# MotionJoy Tracking Generator

A standalone desktop app that generates simulated camera-tracking UDP
data - **OpenTrackIO**, **FreeD**, or both at once - for testing
receivers without real tracking hardware. The OpenTrackIO stream carries
6DOF camera pose, focus/iris/zoom and Brown-Conrady lens distortion.

## Requirements

Python 3.9+ with `tkinter` (ships with most Python installs), plus
`psutil` for interface discovery:

```bash
pip install -r requirements.txt
```

## Run

```bash
python3 main.py
```

Set a target IP/port (default `127.0.0.1:4242`), optionally pick a
specific **Interface** if the machine has more than one NIC (Ethernet,
Wi-Fi, VPN, ...) - "Auto (OS default)" lets the OS routing table choose,
but on multi-homed machines that can pick the wrong adapter and the
packets never reach the target - and press **Start**.

## Choosing what to generate

The landing page asks what to generate: tick **OpenTrackIO**, **FreeD**,
or both, then **Continue**. Each selected protocol gets its own port
(defaults: OpenTrackIO 4242, FreeD 40000) and shares the target IP, rate,
interface and motion mode. FreeD also has a camera ID. Use **< Back** to
return to the landing page.

FreeD output is the 29-byte D1 packet (`freed_encoder.py`): pan/tilt/roll
and X/Y/Z from the same fields, zoom and focus written as `value * 100`.
FreeD carries no iris, optics or distortion data.

## Modes

- **Manual** — every field is a live, editable value sent as-is each tick.
  Zoom/Focus also have paired sliders.
- **Orbit** — the camera animates in a circle around the origin, always
  looking back at it (radius breathes slowly between ~1.5–4.5 m). FIZ and
  distortion fields stay frozen at whatever Manual currently holds.
- **Bounce** — every field auto-sweeps between its From/To bounds at Step
  increments, reversing direction at each bound (a triangle wave).

Switching modes while running takes effect immediately — no need to
Stop/Start.

## Wire format

UDP payload = a 16-byte binary `"OTrk"` segmentation header (single
segment only, per the OpenTrackIO/SMPTE RIS transport framing) followed
by a UTF-8 JSON sample:

```
bytes 0-3   "OTrk"
byte  4     reserved (0)
byte  5     encoding (1 = JSON)
bytes 6-7   sequence (uint16, big-endian)
bytes 8-11  segment offset (uint32, big-endian, always 0 here)
byte  12    last-segment flag (top bit) | length high bits
byte  13    length low byte
bytes 14-15 Fletcher-16 checksum over bytes 0-13 + JSON payload
bytes 16+   JSON payload (protocol.version [1,0,0])
```

This module (`opentrackio_encoder.py`) is self-contained, so the app can
be run and distributed independently.

**Note on values:** the simulator emits values exactly as dialed into the
UI, already in OpenTrackIO's own convention (metres, X-forward/Y-left;
degrees for pan/tilt/roll), with no axis remapping or lens-coefficient
scaling.

## Testing a receiver

Point your OpenTrackIO consumer at the configured IP:port. To sanity
check packets manually without a full receiver, a throwaway listener
works:

```python
import json, socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("127.0.0.1", 4242))
while True:
    data, _ = sock.recvfrom(65536)
    print(json.loads(data[16:]))
```

## Downloads

Tagged releases (`v*`) publish Windows (`.exe`), macOS (Apple Silicon `.zip`) and Linux (x86_64) builds on the GitHub Releases page. The macOS app is unsigned: right-click > Open the first time. On Linux, `chmod +x` the file and run it (Tk is bundled).

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## License

[MIT](LICENSE) © MotionJoy
