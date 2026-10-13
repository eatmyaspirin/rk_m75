"""System-audio capture (WASAPI loopback on Windows) via `soundcard`."""
from __future__ import annotations

import numpy as np

try:
    import soundcard as sc
except Exception:  # pragma: no cover - platform without soundcard
    sc = None


def available() -> bool:
    return sc is not None


def list_inputs() -> list[dict]:
    """List loopback (system output) and real input devices."""
    if sc is None:
        return []
    out: list[dict] = []
    try:
        for m in sc.all_microphones(include_loopback=True):
            if getattr(m, "isloopback", False):
                out.append({"id": m.name, "label": f"{m.name}  [system output]", "loopback": True})
    except Exception:
        pass
    try:
        for m in sc.all_microphones(include_loopback=False):
            out.append({"id": m.name, "label": m.name, "loopback": False})
    except Exception:
        pass
    return out


def default_loopback_name() -> str | None:
    """Name of the loopback device matching the default speaker."""
    if sc is None:
        return None
    try:
        spk = sc.default_speaker()
        mic = sc.get_microphone(spk.name, include_loopback=True)
        return mic.name
    except Exception:
        return None


class AudioSource:
    """Blocking reader of system audio as mono float32 blocks."""

    def __init__(self, device: str | None = None, samplerate: int = 48000, blocksize: int = 1024):
        self.device_name = device or default_loopback_name()
        self.samplerate = samplerate
        self.blocksize = blocksize
        self._rec = None
        self._ctx = None
        self.channels = 2

    def open(self) -> None:
        if sc is None:
            raise RuntimeError("soundcard is not installed")
        if not self.device_name:
            raise RuntimeError("no loopback audio device found")
        mic = sc.get_microphone(self.device_name, include_loopback=True)
        self._ctx = mic.recorder(samplerate=self.samplerate, blocksize=self.blocksize)
        self._rec = self._ctx.__enter__()

    def read(self) -> np.ndarray:
        """Return the next mono block (float32, values roughly -1..1)."""
        data = self._rec.record(numframes=self.blocksize)
        if data.ndim == 2:
            data = data.mean(axis=1)
        return np.asarray(data, dtype=np.float32)

    def close(self) -> None:
        if self._ctx is not None:
            try:
                self._ctx.__exit__(None, None, None)
            except Exception:
                pass
        self._ctx = None
        self._rec = None
