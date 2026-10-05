"""Local network interface discovery, used to let the user pick which
NIC the sender socket binds to (machines with several adapters - e.g.
Ethernet + Wi-Fi + VPN - can otherwise have packets leave through the
wrong one and never reach the target)."""

from __future__ import annotations

import socket

import psutil

AUTO_LABEL = "Auto (OS default)"


def list_interfaces() -> list[tuple[str, str]]:
    """Return (label, ip) pairs for every non-loopback IPv4 interface."""
    interfaces: list[tuple[str, str]] = []
    for name, addrs in psutil.net_if_addrs().items():
        for addr in addrs:
            if addr.family == socket.AF_INET and addr.address != "127.0.0.1":
                interfaces.append((f"{name} ({addr.address})", addr.address))
    return interfaces
