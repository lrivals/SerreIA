"""systemd notifications (READY, WATCHDOG) without the python-systemd dependency."""

import os
import socket


def sd_notify(message: str) -> bool:
    """Send e.g. "READY=1" or "WATCHDOG=1"; no-op (False) outside a systemd service."""
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return False
    if addr.startswith("@"):  # abstract namespace
        addr = "\0" + addr[1:]
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
        s.connect(addr)
        s.sendall(message.encode())
    return True
