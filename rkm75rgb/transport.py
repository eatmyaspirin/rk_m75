"""HID transport for the RK M75 vendor interface (feature report 9)."""
from __future__ import annotations

from typing import Optional

import hid

from .protocol import INTERFACE, PRODUCT_ID, REPORT_SIZE, USAGE, USAGE_PAGE, VENDOR_ID


def discover() -> dict:
    """Locate the RK M75 vendor collection that carries feature report 9."""
    for dev in hid.enumerate(VENDOR_ID, PRODUCT_ID):
        path = dev.get("path", b"")
        if (
            dev.get("usage_page") == USAGE_PAGE
            and dev.get("usage") == USAGE
            and b"MI_01" in path
            and b"Col05" in path
        ):
            return dev
    raise RuntimeError(
        f"RK M75 not found (VID {VENDOR_ID:04X}:PID {PRODUCT_ID:04X}). "
        "Is it plugged in with the USB cable?"
    )


class Transport:
    """Sends 520-byte feature reports to the keyboard."""

    def __init__(self, path: Optional[bytes] = None):
        self.path = path or discover()["path"]
        self._dev = hid.device()
        self._dev.open_path(self.path)
        self._closed = False
        self.frames_sent = 0

    def send_report(self, report: bytes) -> int:
        if self._closed:
            raise RuntimeError("transport is closed")
        if len(report) != REPORT_SIZE:
            raise ValueError(f"expected {REPORT_SIZE} bytes, got {len(report)}")
        n = self._dev.send_feature_report(report)
        self.frames_sent += 1
        return n

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._dev.close()
        finally:
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
