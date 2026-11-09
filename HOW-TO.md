# How to Use MotionJoy Tracking Generator

A quick, screen-by-screen guide. For the wire format, protocol internals and
build instructions, see [README.md](README.md).

## 1. Start the app

**Easiest — grab a release.** Go to the
[Releases page](https://github.com/MotionJoy-Apps/MotionJoyTrackingGenerator/releases)
and download the build for your OS:

- **Windows** – `MotionJoyTrackingGenerator-windows.exe`, double-click to run.
- **macOS (Apple Silicon)** – unzip the `.zip`, then right-click the app → **Open**
  on first launch (it's unsigned).
- **Linux (x86_64)** – `chmod +x MotionJoyTrackingGenerator-linux-x86_64` and run it.

**Or run from source** (Python 3.9+, tkinter, `psutil`):

```bash
pip install -r requirements.txt
python3 main.py
```

## 2. Choose what to generate (landing page)

On first launch the app asks **what to generate** – tick one or both:

- **OpenTrackIO** – 6DOF pose plus focus/iris/zoom and lens distortion.
- **FreeD** – the classic 29-byte D1 packet (pan/tilt/roll + X/Y/Z, zoom, focus).

Then press **Continue**. Each protocol you tick gets its own port on the next
screen (defaults: OpenTrackIO `4242`, FreeD `40000`); they share the target IP,
rate, interface and motion mode. Use **\< Back** to return and change it.

## 3. Set the connection (top row)

| Field | What it does | Default |
|-------|--------------|---------|
| **Target IP** | Where packets are sent. `127.0.0.1` = same machine. | `127.0.0.1` |
| **OpenTrackIO Port** / **FreeD Port** | One port per enabled protocol. | `4242` / `40000` |
| **FreeD Cam ID** | Camera ID in the FreeD packet (only if FreeD is on). | `1` |
| **Rate (fps)** | How many samples per second. | `60` |
| **Interface** | Which network adapter sends. **Auto (OS default)** lets the OS choose; on multi-homed machines (Ethernet + Wi-Fi + VPN) that can pick the wrong adapter and packets never arrive. Pick the adapter that actually reaches the target. | `Auto (OS default)` |

Press **Start** (turns into **Stop**). The status line below shows
`Sending to <ip> (OpenTrackIO :4242, ...) @ 60fps ...` or **Stopped.**

## 4. Pick a motion mode (the radio row)

Switching modes **while running takes effect immediately** – no Stop/Start needed.

- **Manual** – every field is a live editable number sent as-is each tick.
  Zoom and Focus also have paired sliders.
- **Orbit** – the camera animates in a circle around the origin, always looking
  back at it (radius slowly breathes ~1.5–4.5 m). FIZ and distortion stay frozen
  at whatever Manual currently holds.
- **Bounce** – every field auto-sweeps between its **From / To** bounds at **Step**
  increments, reversing at each bound (a triangle wave). Set the From/To/Step
  columns in each field group.
- **Motion** – a rig-move preset from the **Move** dropdown (below).

## 5. Motion presets (the "Move" dropdown)

The **Move** dropdown is **only enabled when Motion mode is selected** – in
Manual/Orbit/Bounce it is grayed out. Options:

- **dolly-front** – pushes in toward the target.
- **dolly-back** – retreats from the target.
- **dolly-left** / **dolly-right** – straddles the base point sideways.
- **crane** – vertical lift.
- **handheld** – organic shake.

All presets ping-pong (ease-in/out) so the motion reverses smoothly.
**Dolly distance (m)** (default 5.0, clamped 0.5–50) sets how far the preset
travels; press **Enter** in the field to commit.

## 6. The field groups

Each group holds the values Manual mode sends and Bounce mode sweeps:

- **Position** – Pos X / Y / Z (metres).
- **Rotation** – Pan / Tilt / Roll (degrees).
- **FIZ** – Zoom, Focus (distance), Iris (fStop). Zoom and Focus have sliders.
- **Distortion** – Brown-Conrady coefficients k1, k2, k3, p1, p2.

In **Manual** mode, type a value and it goes out on the very next tick.

## 7. Point your receiver at it

- **OpenTrackIO** – aim your consumer at the target IP and OpenTrackIO port.
- **FreeD** – aim at the FreeD port.

To sanity-check packets without a full receiver, run a throwaway listener on the
target machine:

```python
import json, socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("127.0.0.1", 4242))   # the OpenTrackIO port you set
while True:
    data, _ = sock.recvfrom(65536)
    print(json.loads(data[16:]))
```

## Troubleshooting

- **No packets arriving?** On a multi-homed machine set **Interface** to the
  adapter that actually reaches the target instead of *Auto*.
- **Packet never seen, wrong port?** Confirm the receiver listens on the exact
  port shown in the status line, and that a firewall isn't dropping inbound UDP.
- **macOS "can't be opened"?** Right-click → **Open** once (unsigned build).
