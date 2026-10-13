"""FFT -> log-spaced frequency bands with auto-gain and smoothing."""
from __future__ import annotations

import numpy as np


class Analyzer:
    """Turns audio blocks into normalised band levels suitable for lighting."""

    def __init__(
        self,
        samplerate: int = 48000,
        blocksize: int = 1024,
        bands: int = 16,
        f_min: float = 40.0,
        f_max: float = 15000.0,
        gate: float = 0.02,
    ):
        self.samplerate = samplerate
        self.blocksize = blocksize
        self.bands = int(bands)
        self.f_min = f_min
        self.f_max = f_max
        self.gate = gate

        self._window = np.hanning(blocksize).astype(np.float32)
        # band edges, log-spaced
        freqs = np.fft.rfftfreq(blocksize, 1.0 / samplerate)
        edges = np.logspace(np.log10(f_min), np.log10(f_max), self.bands + 1)
        self._masks = []
        for i in range(self.bands):
            m = (freqs >= edges[i]) & (freqs < edges[i + 1])
            if not m.any():
                m = np.zeros_like(freqs, dtype=bool)
                m[np.argmin(np.abs(freqs - edges[i]))] = True
            self._masks.append(m)

        # per-band running peak for auto-gain
        self._peak = np.full(self.bands, 1e-4, dtype=np.float32)
        self._levels = np.zeros(self.bands, dtype=np.float32)

    def set_bands(self, bands: int) -> None:
        if int(bands) != self.bands:
            self.__init__(  # noqa: PLC2801 - deliberate re-init
                self.samplerate, self.blocksize, bands, self.f_min, self.f_max, self.gate
            )

    def process(self, block: np.ndarray, attack: float = 0.55, release: float = 0.18,
                gain: float = 1.0, agc: float = 0.94) -> np.ndarray:
        """Return band levels in 0..1."""
        x = np.asarray(block, dtype=np.float32)
        if x.shape[0] != self.blocksize:
            x = np.resize(x, self.blocksize)

        rms = float(np.sqrt(np.mean(x * x)))
        if rms < self.gate:
            x = np.zeros_like(x)

        spec = np.abs(np.fft.rfft(x * self._window))
        spec = spec / (self.blocksize * 0.5)

        raw = np.array([spec[m].mean() for m in self._masks], dtype=np.float32)
        raw *= gain

        # auto-gain: track a decaying per-band peak so quiet sources still light up
        self._peak = np.maximum(raw, self._peak * agc)
        norm = raw / (self._peak + 1e-6)

        # gentle perceptual curve
        norm = np.clip(norm, 0.0, 1.0) ** 1.35

        # asymmetric smoothing: fast attack, slower release
        prev = self._levels
        self._levels = np.where(norm > prev,
                                prev + (norm - prev) * attack,
                                prev + (norm - prev) * release)
        return self._levels.copy()

    @property
    def level(self) -> float:
        return float(self._levels.mean())

    def bass(self) -> float:
        k = max(1, self.bands // 4)
        return float(self._levels[:k].mean())
