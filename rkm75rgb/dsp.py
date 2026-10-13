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

    # Width of the display window below a band's own peak. The ear is roughly
    # logarithmic, so the ratio is mapped over a dB range instead of being
    # raised to a power: 0 dB (at the peak) is full height, -DB_RANGE dB is dark.
    #
    # Tuned by measurement, not by taste: because the auto-gain normalises every
    # band towards its own peak, a wide window leaves everything lit (a 48 dB
    # window put the spectral skirt of a pure tone at 0.66 and saturated
    # broadband noise at ~1.0). 18 dB keeps only bands within 18 dB of their own
    # recent peak visible, which is what makes the spectrum read as a spectrum.
    DB_RANGE = 18.0

    # Per-band noise floor. A band carrying nothing still has a little energy --
    # spectral leakage from the rest of the signal, hiss, hum -- and the
    # auto-gain will happily normalise that up towards full height. Track the
    # quietest level each band reaches and subtract it.
    #
    # The floor is only learned in bands that are quiet relative to the loudest
    # band. Without that guard a band holding a sustained note would have its own
    # level learned as "noise" and be subtracted away, which is exactly the music
    # you want to see.
    FLOOR_LEARN_ABOVE = 0.03    # only learn in bands >= 30 dB below the loudest
    FLOOR_STEP = 2e-5           # rise per block; falling is instant

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
        self._floor = np.zeros(self.bands, dtype=np.float32)
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
        silent = rms < self.gate
        if silent:
            x = np.zeros_like(x)

        spec = np.abs(np.fft.rfft(x * self._window))
        spec = spec / (self.blocksize * 0.5)

        raw = np.array([spec[m].mean() for m in self._masks], dtype=np.float32)
        raw *= gain

        # track the loudest band, which both floors the auto-gain and sets the
        # threshold below which a band counts as "quiet" for noise-floor learning
        loudest = float(raw.max()) if raw.size else 0.0
        self._global = max(loudest, self._global * agc, self.PEAK_FLOOR_ABS)

        # subtract the per-band noise floor: instant fall, slow rise, and only
        # learned in bands that are quiet relative to the loudest. While the gate
        # says we are in silence the floor is left alone rather than reset to 0.
        if not silent:
            quiet = raw <= self._global * self.FLOOR_LEARN_ABOVE
            self._floor = np.where(
                quiet, np.minimum(raw, self._floor + self.FLOOR_STEP), self._floor)
        sig = np.maximum(raw - self._floor, 0.0)

        # auto-gain: track a decaying peak per band so quiet sources still light
        # up, but never let a peak decay below the relative floor
        floor = max(self.PEAK_FLOOR_ABS, self._global * self.PEAK_FLOOR_REL)
        self._peak = np.maximum(sig, np.maximum(self._peak * agc, floor))
        norm = sig / (self._peak + 1e-6)

        # perceptual mapping in dB rather than a fixed power curve, so the
        # response is roughly even across the range the ear cares about
        db = 20.0 * np.log10(np.maximum(norm, 1e-9))
        shaped = np.clip((db + self.DB_RANGE) / self.DB_RANGE, 0.0, 1.0).astype(np.float32)

        # asymmetric smoothing: fast attack, slower release
        prev = self._levels
        self._levels = np.where(shaped > prev,
                                prev + (shaped - prev) * attack,
                                prev + (shaped - prev) * release)
        return self._levels.copy()

    @property
    def level(self) -> float:
        return float(self._levels.mean())

    def bass(self) -> float:
        k = max(1, self.bands // 4)
        return float(self._levels[:k].mean())
