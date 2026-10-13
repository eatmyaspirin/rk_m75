"""FFT -> log-spaced frequency bands with auto-gain and smoothing."""
from __future__ import annotations

import numpy as np


class Analyzer:
    """Turns audio blocks into normalised band levels suitable for lighting."""

    # A band whose peak decays towards zero eventually matches that band's own
    # spectral leakage, and `raw / peak` then climbs towards 1 even though the
    # band carries nothing. Flooring the peak stops that. The floor is relative
    # to the loudest band (not absolute) so that quiet sources still work: a
    # band 60 dB below the loudest is treated as empty.
    PEAK_FLOOR_ABS = 1e-6
    PEAK_FLOOR_REL = 1e-3

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

        # per-band running peak for auto-gain, plus the loudest band overall
        # (which sets the floor the per-band peaks are allowed to decay to)
        self._peak = np.full(self.bands, self.PEAK_FLOOR_ABS, dtype=np.float32)
        self._global = float(self.PEAK_FLOOR_ABS)
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

        # auto-gain: track a decaying peak per band so quiet sources still light
        # up, but never let a peak decay below the relative floor
        loudest = float(raw.max()) if raw.size else 0.0
        self._global = max(loudest, self._global * agc, self.PEAK_FLOOR_ABS)
        floor = max(self.PEAK_FLOOR_ABS, self._global * self.PEAK_FLOOR_REL)

        self._peak = np.maximum(raw, np.maximum(self._peak * agc, floor))
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
