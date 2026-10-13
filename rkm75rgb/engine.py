"""Capture -> analyse -> render -> send, on a background thread."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field, asdict

import numpy as np

from . import audio as audio_mod
from . import effects
from .dsp import Analyzer
from .frame import Frame
from .layout import KEY_COLUMNS, LABELS
from .protocol import ROWS
from .transport import Transport


@dataclass
class Settings:
    mode: str = "bars"            # bars | mirror | vu | pulse
    palette: str = "rainbow"      # rainbow | fire | ocean | ice | neon | mono
    mono: str = "#00AAFF"
    bands: int = 16
    brightness: float = 1.0
    gain: float = 1.6
    attack: float = 0.55
    release: float = 0.18
    gate: float = 0.02
    fps: float = 30.0
    extra_leds: bool = False
    idle_glow: bool = True
    device: str | None = None     # loopback device name; None = default
    samplerate: int = 48000
    blocksize: int = 1024

    def as_dict(self) -> dict:
        return asdict(self)


def _hex_to_rgb(s: str) -> tuple[int, int, int]:
    s = (s or "").lstrip("#")
    if len(s) != 6:
        return (0, 170, 255)
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return (0, 170, 255)


class Engine:
    def __init__(self, settings: Settings | None = None):
        self._lock = threading.RLock()
        self.settings = settings or Settings()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

        self.running = False
        self.error: str | None = None
        self.device_label: str | None = None
        self.frames = 0
        self.actual_fps = 0.0
        self.levels = np.zeros(self.settings.bands, dtype=np.float32)

        self._analyzer = Analyzer(blocksize=self.settings.blocksize,
                                  samplerate=self.settings.samplerate,
                                  bands=self.settings.bands)

    # ---------------------------------------------------------------- api
    def update(self, **changes) -> dict:
        with self._lock:
            for k, v in changes.items():
                if not hasattr(self.settings, k):
                    continue
                cur = getattr(self.settings, k)
                if isinstance(cur, bool):
                    v = bool(v)
                elif isinstance(cur, float):
                    v = float(v)
                elif isinstance(cur, int) and not isinstance(cur, bool):
                    v = int(v)
                setattr(self.settings, k, v)
            if "bands" in changes:
                self._analyzer.set_bands(int(self.settings.bands))
            return self.settings.as_dict()

    def start(self) -> None:
        with self._lock:
            if self.running:
                return
            self._stop.clear()
            self.error = None
            self._thread = threading.Thread(target=self._run, name="rk-engine", daemon=True)
            self.running = True
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            if not self.running:
                return
            self._stop.set()
            t = self._thread
        if t is not None:
            t.join(timeout=3.0)
        with self._lock:
            self.running = False
            self._thread = None

    def snapshot(self) -> dict:
        with self._lock:
            mono = _hex_to_rgb(self.settings.mono)
            s = self.settings
            return {
                "running": self.running,
                "error": self.error,
                "device": self.device_label,
                "frames": self.frames,
                "fps": round(self.actual_fps, 2),
                "levels": [round(float(x), 4) for x in self.levels],
                "settings": s.as_dict(),
                "keymap": {"rows": ROWS, "columns": KEY_COLUMNS},
                "labels": {str(i): name for i, name in LABELS.items()},
            }

    def preview_colors(self) -> list[list[int]]:
        """Last rendered frame as a 126-entry RGB list (for the UI)."""
        with self._lock:
            data = self._last_frame
        if data is None:
            return [[0, 0, 0]] * 126
        return [[data[i * 3], data[i * 3 + 1], data[i * 3 + 2]] for i in range(126)]

    _last_frame: bytes | None = None

    # ------------------------------------------------------------ internals
    def _run(self) -> None:
        transport: Transport | None = None
        source: audio_mod.AudioSource | None = None
        frame = Frame()
        try:
            transport = Transport()
            with self._lock:
                self.device_label = "RK M75 (USB)"

            s = self.settings
            source = audio_mod.AudioSource(device=s.device, samplerate=s.samplerate,
                                           blocksize=s.blocksize)
            source.open()
            with self._lock:
                self.device_label = f"RK M75 (USB) + {source.device_name}"

            analyzer = self._analyzer
            interval = 1.0 / max(1.0, self.settings.fps)
            next_send = time.perf_counter()
            idle_phase = 0.0
            count, t0 = 0, time.perf_counter()

            while not self._stop.is_set():
                s = self.settings
                block = source.read()
                levels = analyzer.process(block, attack=s.attack, release=s.release,
                                          gain=s.gain, agc=0.94)

                now = time.perf_counter()
                if now < next_send:
                    continue
                next_send = max(next_send + interval, now)

                with self._lock:
                    self.levels = levels

                loud = float(levels.mean()) > 0.03
                if loud or not s.idle_glow:
                    effects.render(frame, levels, mode=s.mode, palette=s.palette,
                                   brightness=s.brightness, mono=_hex_to_rgb(s.mono),
                                   extra_leds=s.extra_leds)
                else:
                    idle_phase = (idle_phase + 0.006) % 1.0
                    base = np.array([max(0.0, np.sin((idle_phase * 2 * np.pi) + i * 0.4)) * 0.12
                                     for i in range(KEY_COLUMNS)], dtype=np.float32)
                    effects.render(frame, base, mode="bars", palette=s.palette,
                                   brightness=s.brightness * 0.6, mono=_hex_to_rgb(s.mono))

                transport.send_report(frame.to_report())
                with self._lock:
                    self._last_frame = frame.raw
                    self.frames += 1
                    count += 1
                    el = now - t0
                    if el >= 0.5:
                        self.actual_fps = count / el
                        count, t0 = 0, now

        except Exception as exc:  # surface to the UI
            with self._lock:
                self.error = f"{type(exc).__name__}: {exc}"
        finally:
            if source is not None:
                source.close()
            if transport is not None:
                try:
                    off = Frame()
                    transport.send_report(off.to_report())
                except Exception:
                    pass
                transport.close()
            with self._lock:
                self.running = False
                self._thread = None
