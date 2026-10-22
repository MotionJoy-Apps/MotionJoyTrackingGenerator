"""Tkinter UI for the MotionJoy Tracking Generator."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from motion import BounceSource, ManualSource, OrbitSource
from motion_presets import MOTION_KINDS, MotionPresetSource
from network import AUTO_LABEL, list_interfaces
from sender import SenderThread, start_sender
from state import (
    DEFAULT_PORTS, MODE_BOUNCE, MODE_MANUAL, MODE_MOTION, MODE_ORBIT, PROTO_FREED, PROTO_OPENTRACKIO, AppState,
)

APP_TITLE = "MotionJoy Tracking Generator"
PROTOCOL_LABELS = {PROTO_OPENTRACKIO: "OpenTrackIO", PROTO_FREED: "FreeD"}
PROTOCOL_BLURBS = {
    PROTO_OPENTRACKIO: "6DOF pose, FIZ and lens distortion\nas JSON over UDP",
    PROTO_FREED: "FreeD D1 packets: pose, zoom and focus\n(29-byte binary UDP)",
}

# (attribute name, display label, default value, has slider)
POSITION_FIELDS = [
    ("trans_x", "Pos X (m)", 0.0, False),
    ("trans_y", "Pos Y (m)", 0.0, False),
    ("trans_z", "Pos Z (m)", 2.0, False),
]
ROTATION_FIELDS = [
    ("pan", "Pan (deg)", 0.0, False),
    ("tilt", "Tilt (deg)", 0.0, False),
    ("roll", "Roll (deg)", 0.0, False),
]
FIZ_FIELDS = [
    ("zoom", "Zoom", 0.0, True),
    ("focus_distance", "Focus", 2.0, True),
    ("iris_fstop", "Iris (fStop)", 2.8, False),
]
DISTORTION_FIELDS = [
    ("k1", "k1", 0.0, False),
    ("k2", "k2", 0.0, False),
    ("k3", "k3", 0.0, False),
    ("p1", "p1", 0.0, False),
    ("p2", "p2", 0.0, False),
]
BOUNCEABLE_GROUPS = [
    ("Position", POSITION_FIELDS),
    ("Rotation", ROTATION_FIELDS),
    ("FIZ", FIZ_FIELDS),
    ("Distortion", DISTORTION_FIELDS),
]

OPTICS_FIELDS = [
    ("focal_length_x", "Focal Length X (mm)", 24.0),
    ("focal_length_y", "Focal Length Y (mm)", 24.0),
    ("pinhole_focal_length", "Pinhole Focal Length (mm)", 24.0),
    ("projection_offset_x", "Projection Offset X (mm)", 0.0),
    ("projection_offset_y", "Projection Offset Y (mm)", 0.0),
    ("entrance_pupil_offset", "Entrance Pupil Offset (m)", 0.0),
]


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.state_ = AppState()
        self.sender: SenderThread | None = None
        self.sources: dict[str, object] = {}

        self._value_vars: dict[str, tk.StringVar] = {}
        self._range_vars: dict[str, tuple[tk.StringVar, tk.StringVar, tk.StringVar]] = {}
        self._value_entries: dict[str, tk.Widget] = {}
        self._range_entries: dict[str, tuple[tk.Widget, tk.Widget, tk.Widget]] = {}

        self._proto_vars = {p: tk.BooleanVar(value=(p == PROTO_OPENTRACKIO)) for p in PROTOCOL_LABELS}
        self._container = ttk.Frame(self)
        self._container.pack(fill="both", expand=True)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._show_landing()
        self.after(33, self._refresh_ui)

    # ---- landing page -------------------------------------------------

    def _clear_container(self) -> None:
        for child in self._container.winfo_children():
            child.destroy()
        self._value_vars.clear()
        self._range_vars.clear()
        self._value_entries.clear()
        self._range_entries.clear()

    def _show_landing(self) -> None:
        self._stop_sender()
        self._clear_container()
        self._in_main = False
        self.geometry("")
        frame = ttk.Frame(self._container, padding=24)
        frame.pack()
        ttk.Label(frame, text=APP_TITLE, font=("", 18, "bold")).pack(pady=(0, 4))
        ttk.Label(frame, text="Choose what to generate (select one or both)").pack(pady=(0, 16))

        cards = ttk.Frame(frame)
        cards.pack()
        for col, proto in enumerate(PROTOCOL_LABELS):
            card = ttk.LabelFrame(cards, padding=12)
            card.grid(row=0, column=col, padx=8, sticky="n")
            ttk.Checkbutton(
                card, text=PROTOCOL_LABELS[proto], variable=self._proto_vars[proto],
                command=self._update_continue_state,
            ).pack(anchor="w")
            ttk.Label(card, text=PROTOCOL_BLURBS[proto], justify="left").pack(anchor="w", pady=(6, 0))

        self.continue_button = ttk.Button(frame, text="Continue", command=self._on_continue)
        self.continue_button.pack(pady=(20, 0))
        self._update_continue_state()

    def _update_continue_state(self) -> None:
        any_selected = any(v.get() for v in self._proto_vars.values())
        self.continue_button.configure(state="normal" if any_selected else "disabled")

    def _on_continue(self) -> None:
        enabled = {p for p, v in self._proto_vars.items() if v.get()}
        if not enabled:
            return
        self.state_.enabled = enabled
        self._show_main()

    def _show_main(self) -> None:
        self._clear_container()
        self._in_main = True
        self.state_.mode = MODE_MANUAL
        self._build_connection_row()
        self._build_mode_row()
        for label, fields in BOUNCEABLE_GROUPS:
            self._build_field_group(label, fields, bounceable=True)
        if PROTO_OPENTRACKIO in self.state_.enabled:
            self._build_field_group("Optics", [(n, l, d, False) for n, l, d in OPTICS_FIELDS], bounceable=False)
        self._build_status_row()
        self._seed_defaults()

    # ---- construction -------------------------------------------------

    def _build_connection_row(self) -> None:
        frame = ttk.Frame(self._container, padding=6)
        frame.pack(fill="x")
        enabled = self.state_.enabled
        col = 0

        ttk.Button(frame, text="< Back", command=self._show_landing).grid(row=0, column=col, padx=4)
        col += 1

        ttk.Label(frame, text="Target IP").grid(row=0, column=col, padx=4)
        self.ip_var = tk.StringVar(value=self.state_.ip)
        ttk.Entry(frame, textvariable=self.ip_var, width=14).grid(row=0, column=col + 1, padx=4)
        col += 2

        self.port_vars: dict[str, tk.StringVar] = {}
        for proto in PROTOCOL_LABELS:
            if proto not in enabled:
                continue
            ttk.Label(frame, text=f"{PROTOCOL_LABELS[proto]} Port").grid(row=0, column=col, padx=4)
            var = tk.StringVar(value=str(self.state_.ports[proto]))
            self.port_vars[proto] = var
            ttk.Entry(frame, textvariable=var, width=7).grid(row=0, column=col + 1, padx=4)
            col += 2

        if PROTO_FREED in enabled:
            ttk.Label(frame, text="FreeD Cam ID").grid(row=0, column=col, padx=4)
            self.cam_id_var = tk.StringVar(value=str(self.state_.freed_camera_id))
            ttk.Entry(frame, textvariable=self.cam_id_var, width=4).grid(row=0, column=col + 1, padx=4)
            col += 2

        ttk.Label(frame, text="Rate (fps)").grid(row=0, column=col, padx=4)
        self.rate_var = tk.StringVar(value=str(self.state_.rate))
        self.rate_var.trace_add("write", lambda *_: self._on_rate_change())
        ttk.Entry(frame, textvariable=self.rate_var, width=7).grid(row=0, column=col + 1, padx=4)
        col += 2

        ttk.Label(frame, text="Interface").grid(row=0, column=col, padx=4)
        self._interface_ips: dict[str, str] = {AUTO_LABEL: ""}
        for label, ip in list_interfaces():
            self._interface_ips[label] = ip
        self.interface_var = tk.StringVar(value=AUTO_LABEL)
        ttk.Combobox(
            frame, textvariable=self.interface_var, values=list(self._interface_ips), width=22, state="readonly",
        ).grid(row=0, column=col + 1, padx=4)
        col += 2

        self.start_button = ttk.Button(frame, text="Start", command=self._on_toggle_start)
        self.start_button.grid(row=0, column=col, padx=12)

        self.error_label = ttk.Label(frame, text="", foreground="red")
        self.error_label.grid(row=0, column=col + 1, padx=4)

    def _build_mode_row(self) -> None:
        frame = ttk.Frame(self._container, padding=(6, 0))
        frame.pack(fill="x")
        self.mode_var = tk.StringVar(value=MODE_MANUAL)
        for text, value in [("Manual", MODE_MANUAL), ("Orbit", MODE_ORBIT), ("Bounce", MODE_BOUNCE), ("Motion", MODE_MOTION)]:
            ttk.Radiobutton(frame, text=text, value=value, variable=self.mode_var, command=self._on_mode_change).pack(side="left", padx=6)
        self._build_motion_row()

    def _build_motion_row(self) -> None:
        frame = ttk.Frame(self._container, padding=(6, 0))
        frame.pack(fill="x")
        ttk.Label(frame, text="Move").pack(side="left", padx=6)
        self.motion_kind_var = tk.StringVar(value=self.state_.motion_kind)
        menu = ttk.Combobox(frame, textvariable=self.motion_kind_var,
                            values=list(MOTION_KINDS), width=14, state="readonly")
        menu.pack(side="left", padx=6)
        menu.bind("<<ComboboxSelected>>", lambda *_: self.state_.set_motion(kind=self.motion_kind_var.get()))
        ttk.Label(frame, text="Dolly distance (m)").pack(side="left", padx=(16, 4))
        self.dolly_distance_var = tk.StringVar(value=f"{self.state_.dolly_distance:.1f}")
        entry = ttk.Entry(frame, textvariable=self.dolly_distance_var, width=7)
        entry.pack(side="left", padx=4)
        def _commit(_e=None):
            try:
                self.state_.set_motion(dolly_distance=float(self.dolly_distance_var.get()))
            except ValueError:
                pass
        entry.bind("<Return>", _commit)
        entry.bind("<FocusOut>", _commit)

    def _build_field_group(self, title: str, fields, *, bounceable: bool) -> None:
        outer = ttk.LabelFrame(self._container, text=title, padding=6)
        outer.pack(fill="x", padx=6, pady=3)

        header = ["Field", "Value"]
        if bounceable:
            header += ["From", "To", "Step"]
        for c, text in enumerate(header):
            ttk.Label(outer, text=text, font=("", 9, "bold")).grid(row=0, column=c, padx=4)

        for r, entry in enumerate(fields, start=1):
            name, label, default = entry[0], entry[1], entry[2]
            has_slider = entry[3] if len(entry) > 3 else False

            ttk.Label(outer, text=label).grid(row=r, column=0, sticky="w", padx=4)

            value_var = tk.StringVar(value=str(default))
            self._value_vars[name] = value_var
            value_entry = ttk.Entry(outer, textvariable=value_var, width=10)
            value_entry.grid(row=r, column=1, padx=4)
            value_entry.bind("<FocusOut>", lambda e, n=name: self._on_value_commit(n))
            value_entry.bind("<Return>", lambda e, n=name: self._on_value_commit(n))
            self._value_entries[name] = value_entry

            if has_slider:
                slider = ttk.Scale(
                    outer, from_=0.0, to=100.0, orient="horizontal",
                    command=lambda v, n=name: self._on_slider_move(n, v),
                )
                slider.grid(row=r, column=6, padx=8)

            if bounceable:
                from_var = tk.StringVar(value="0.0")
                to_var = tk.StringVar(value="1.0")
                step_var = tk.StringVar(value="0.01")
                self._range_vars[name] = (from_var, to_var, step_var)
                entries = []
                for c, var in enumerate((from_var, to_var, step_var), start=2):
                    e = ttk.Entry(outer, textvariable=var, width=8)
                    e.grid(row=r, column=c, padx=2)
                    e.bind("<FocusOut>", lambda ev, n=name: self._on_range_commit(n))
                    e.bind("<Return>", lambda ev, n=name: self._on_range_commit(n))
                    entries.append(e)
                self._range_entries[name] = tuple(entries)

    def _build_status_row(self) -> None:
        self.status_var = tk.StringVar(value="Stopped.")
        ttk.Label(self._container, textvariable=self.status_var, anchor="w").pack(fill="x", padx=6, pady=4)

    def _seed_defaults(self) -> None:
        for _, fields in BOUNCEABLE_GROUPS:
            for name, _label, default, *_ in fields:
                self.state_.set_manual_field(name, default)
                lo = min(default, default - 1.0) if default else -1.0
                hi = max(default, default + 1.0) if default else 1.0
                self.state_.set_range(name, from_value=lo, to_value=hi, step=abs(hi - lo) / 50.0 or 0.01)
                from_var, to_var, step_var = self._range_vars[name]
                r = self.state_.get_range(name)
                from_var.set(str(r.from_value))
                to_var.set(str(r.to_value))
                step_var.set(str(r.step))
        for name, _label, default in OPTICS_FIELDS:
            self.state_.set_manual_field(name, default)

    # ---- field callbacks (main thread only) ----------------------------

    def _on_value_commit(self, name: str) -> None:
        raw = self._value_vars[name].get()
        try:
            value = float(raw)
        except ValueError:
            return
        self.state_.set_manual_field(name, value)

    def _on_slider_move(self, name: str, raw_value: str) -> None:
        if self.mode_var.get() != MODE_MANUAL:
            return
        try:
            value = float(raw_value)
        except ValueError:
            return
        self.state_.set_manual_field(name, value)
        self._value_vars[name].set(f"{value:.3f}")

    def _on_range_commit(self, name: str) -> None:
        from_var, to_var, step_var = self._range_vars[name]
        try:
            from_value = float(from_var.get())
            to_value = float(to_var.get())
            step = float(step_var.get())
        except ValueError:
            return
        self.state_.set_range(name, from_value=from_value, to_value=to_value, step=step)

    def _on_mode_change(self) -> None:
        mode = self.mode_var.get()
        self.state_.mode = mode
        manual_only = mode == MODE_MANUAL
        for name, entry in self._value_entries.items():
            if name in self._range_vars:  # bounceable field
                entry.configure(state="normal" if manual_only else "disabled")
        for name, entries in self._range_entries.items():
            enabled = mode == MODE_BOUNCE
            for e in entries:
                e.configure(state="normal" if enabled else "disabled")
        self._on_mode_change_bounce_reset()

    def _on_mode_change_bounce_reset(self) -> None:
        # Re-instantiate the bounce source on mode entry so its internal
        # direction/value state restarts cleanly from the current ranges.
        if self.sender is not None:
            self.sources[MODE_BOUNCE] = BounceSource(self.state_)
            rate = self._safe_rate()
            self.sources[MODE_ORBIT] = self.sources.get(MODE_ORBIT) or OrbitSource(self.state_, interval=1.0 / rate if rate else 1.0 / 60.0)

    # ---- start/stop -----------------------------------------------------

    def _safe_rate(self) -> float:
        """Main-thread-only helper: reads the Tk rate field directly."""
        try:
            return max(0.1, float(self.rate_var.get()))
        except ValueError:
            return 60.0

    def _on_rate_change(self) -> None:
        """Main-thread trace callback: mirrors the Tk rate field into the
        thread-safe AppState so the sender thread never touches Tk vars."""
        try:
            rate = max(0.1, float(self.rate_var.get()))
        except ValueError:
            return
        self.state_.rate = rate

    def _validate_connection(self) -> tuple[str, dict[str, int], int, float] | None:
        ip = self.ip_var.get().strip()
        if not ip:
            self.error_label.configure(text="IP required")
            return None
        ports: dict[str, int] = {}
        for proto, var in self.port_vars.items():
            try:
                port = int(var.get())
                if not (1 <= port <= 65535):
                    raise ValueError
            except ValueError:
                self.error_label.configure(text=f"Invalid {PROTOCOL_LABELS[proto]} port")
                return None
            ports[proto] = port
        cam_id = 1
        if PROTO_FREED in ports:
            try:
                cam_id = int(self.cam_id_var.get())
                if not (0 <= cam_id <= 255):
                    raise ValueError
            except ValueError:
                self.error_label.configure(text="Invalid FreeD camera ID")
                return None
        rate = self._safe_rate()
        self.error_label.configure(text="")
        return ip, ports, cam_id, rate

    def _on_toggle_start(self) -> None:
        if self.sender is not None:
            self._stop_sender()
        else:
            self._start_sender()

    def _start_sender(self) -> None:
        validated = self._validate_connection()
        if validated is None:
            return
        ip, ports, cam_id, rate = validated
        self.state_.ip, self.state_.rate = ip, rate
        self.state_.ports.update(ports)
        self.state_.freed_camera_id = cam_id
        self.state_.local_ip = self._interface_ips.get(self.interface_var.get(), "")
        self.state_.set_last_error("")

        interval = 1.0 / rate if rate > 0 else 1.0 / 60.0
        self.sources = {
            MODE_MANUAL: ManualSource(self.state_),
            MODE_ORBIT: OrbitSource(self.state_, interval=interval),
            MODE_BOUNCE: BounceSource(self.state_),
            MODE_MOTION: MotionPresetSource(self.state_, interval=interval, kind=self.state_.motion_kind),
        }

        self.sender = start_sender(
            state=self.state_,
            ip=ip,
            targets=ports,
            freed_camera_id=cam_id,
            local_ip=self.state_.local_ip,
            rate_fn=lambda: self.state_.rate,
            source_fn=lambda: self.sources[self.state_.mode],
        )
        self.start_button.configure(text="Stop")
        self.status_var.set(f"Sending to {ip} ({self._ports_text()}) @ {rate}fps ...")

    def _ports_text(self) -> str:
        return ", ".join(f"{PROTOCOL_LABELS[p]} :{self.state_.ports[p]}" for p in PROTOCOL_LABELS if p in self.state_.enabled)

    def _stop_sender(self) -> None:
        if self.sender is not None:
            self.sender.stop()
            self.sender = None
        if getattr(self, "_in_main", False):
            self.start_button.configure(text="Start")
            self.status_var.set("Stopped.")

    def _on_close(self) -> None:
        self._stop_sender()
        self.destroy()

    # ---- refresh loop (main thread only) --------------------------------

    def _refresh_ui(self) -> None:
        if not getattr(self, "_in_main", False):
            self.after(33, self._refresh_ui)
            return
        sample, seq, tc = self.state_.get_last_sample()
        if sample is not None and self.mode_var.get() != MODE_MANUAL:
            for name in self._value_vars:
                if name in self._range_vars:  # bounceable field only
                    value = getattr(sample, name, None)
                    if value is not None:
                        self._value_vars[name].set(f"{value:.4f}")

        error = self.state_.get_last_error() if self.sender is not None else ""
        self.error_label.configure(text=error)

        if error:
            self.status_var.set(f"Sending to {self.state_.ip} ({self._ports_text()}) ... {error}")
        elif sample is not None and self.sender is not None:
            self.status_var.set(
                f"seq={seq} tc={tc}  X={sample.trans_x:.3f} Y={sample.trans_y:.3f} Z={sample.trans_z:.3f} "
                f"Pan={sample.pan:.2f} Tilt={sample.tilt:.2f} Roll={sample.roll:.2f}"
            )
        self.after(33, self._refresh_ui)
