# The equalizer, explained from first principles

*Why* each stage of `rkm75rgb` has the shape it does, and the maths behind it.
[technical-notes.md](technical-notes.md#9-the-audio-equalizer) describes what the
chain does; this explains the reasoning.

Every number here was measured from the code in this repo, not estimated. The
scripts that produced them are noted where relevant.

* [1. Sound becomes numbers](#1-sound-becomes-numbers)
* [2. The one idea behind the FFT](#2-the-one-idea-behind-the-fft)
* [3. Why the code divides by N/2](#3-why-the-code-divides-by-n2)
* [4. Bins, and why tones don't land on them](#4-bins-and-why-tones-dont-land-on-them)
* [5. Leakage, and why there's a window](#5-leakage-and-why-theres-a-window)
* [6. Bands: log spacing and the maths of logspace](#6-bands-log-spacing-and-the-maths-of-logspace)
* [7. Decibels: what they are and why 20·log10](#7-decibels-what-they-are-and-why-20log10)
* [8. Auto-gain: the ratio trick](#8-auto-gain-the-ratio-trick)
* [9. Smoothing: a one-pole filter](#9-smoothing-a-one-pole-filter)
* [10. The noise floor: a leaky minimum](#10-the-noise-floor-a-leaky-minimum)
* [11. Bands to columns](#11-bands-to-columns)
* [12. The whole chain, traced with measured numbers](#12-the-whole-chain-traced-with-measured-numbers)
* [13. `process()` line by line](#13-process-line-by-line)
* [14. Experiments to make it click](#14-experiments-to-make-it-click)

---

## 1. Sound becomes numbers

Air pressure is a continuous curve `p(t)`. The sound card measures it 48 000 times
a second and hands you a list of numbers.

| Quantity | Value | Meaning |
| --- | --- | --- |
| Sample rate `SR` | 48 000 Hz | one measurement every 20.8 µs |
| Block size `N` | 1024 samples | 21.333 ms of sound |
| Bin width | `SR/N` = **46.875 Hz** | see §4 |

A block is just `x[0], x[1], … x[1023]` — 1024 pressure values, nothing more.

**Nyquist limit.** To represent a frequency `f` you need `SR > 2f`. At 48 kHz you
can represent up to 24 kHz, which is why the spectrum ends there.

---

## 2. The one idea behind the FFT

Strip away the notation. The question "how much 500 Hz is in this block?" is
really:

> Does this block of numbers look like a 500 Hz sine?

And "how much does A resemble B?" has one standard answer: **multiply them
together and average.**

* If they match, every product is positive → the average is big.
* If they don't, the products alternate in sign and cancel → the average is ~0.

That is the entire idea. The DFT correlates the block against a sine and a cosine
at every candidate frequency:

```
X[k] = Σₙ x[n] · e^(−2πikn/N)
```

Euler's formula, `e^(−iθ) = cos θ − i·sin θ`, means that one line is secretly
*two* correlations:

```
Re X[k] =  Σₙ x[n]·cos(2πkn/N)      ← correlate with a cosine
Im X[k] = −Σₙ x[n]·sin(2πkn/N)      ← correlate with a sine
|X[k]|  =  √(Re² + Im²)
```

**Why both sine and cosine?** A wave has an amplitude *and* a phase. Correlating
with a cosine alone would report zero for a sine shifted 90°, which is absurd —
it's the same sound. Combining the two by Pythagoras makes the result independent
of phase.

**Why `rfft` and not `fft`?** The input is real, so the negative-frequency half of
the spectrum is a mirror image carrying no extra information. `rfft` returns only
the useful half: bins 0…512, 513 values.

---

## 3. Why the code divides by N/2

The correlation sums 1024 products, so it grows with block size and isn't a
sensible "amount of signal". Let's find out what it actually equals.

Take `x[n] = A·sin(2πk₀n/N)` — a sine sitting exactly on bin `k₀`. Evaluate the
imaginary part at bin `k₀`:

```
Im X[k₀] = −A·Σₙ sin²(2πk₀n/N) = −A·(N/2)
|X[k₀]|  = A·N/2
```

So dividing by `N/2` turns the sum back into `A`. That is exactly
`spec / (self.blocksize * 0.5)`.

**Now the important part.** A 1 kHz sine of amplitude 1.0 has a peak bin reading
**0.465**, not 1.0. Two constant losses:

1. the Hann window has a mean of 0.4995, i.e. it halves the correlation;
2. 1000 Hz does not sit on a bin centre (next section), so its peak is split.

**Neither matters.** A constant scale factor is divided out by the auto-gain. This
is the single most important thing to internalise about this pipeline:

> Almost every absolute magnitude in the chain is arbitrary by design. You only
> ever compare numbers *within* one frame.

---

## 4. Bins, and why tones don't land on them

```
bin k  ↔  frequency k · SR/N  =  k · 46.875 Hz
```

512 bins × 46.875 = 24 000 Hz. Put 1000 Hz in: `1000 / 46.875 = 21.333`. **Not an
integer.** A pure 1 kHz tone has no single bin representing it; its energy lands
between bin 21 (984.4 Hz) and bin 22 (1031.25 Hz). Measured:

```
bin 20 =  937.50 Hz -> 0.1332
bin 21 =  984.38 Hz -> 0.4648   <- peak
bin 22 = 1031.25 Hz -> 0.3720
```

Normal and unavoidable. Only exact multiples of 46.875 Hz land dead-centre.

---

## 5. Leakage, and why there's a window

The DFT assumes your block repeats forever. A 21 ms slice of a 1 kHz tone starts
and ends mid-cycle, so imagining it looping produces a **jump** at the seam. A
jump contains every frequency, so the spectrum smears across the whole range:
**spectral leakage**.

The fix is to fade the block in and out so the ends meet at zero — multiply by a
window. Hann:

```
w[n] = 0.5 − 0.5·cos(2πn/(N−1))
```

Zero at both ends, maximum in the middle. Measured effect on a 1 kHz sine:

| | peak height | energy outside the top 3 bins | bins above 1% of peak |
| --- | --- | --- | --- |
| no window | 0.830 | **63.0%** | **53** |
| Hann | 0.465 | **8.0%** | **6** |

The window gives up peak height (a flat constant) to stop one tone smearing across
53 bins. Without it, a single note would light most of the keyboard.

**The trade-off is real.** A window *widens* each peak slightly. You cannot have
perfect amplitude accuracy and perfect frequency resolution at once — the
uncertainty principle of signal processing — and `N` is how you pick your side of
it.

---

## 6. Bands: log spacing and the maths of `logspace`

513 bins can't drive 16 columns, so bins are grouped into bands.

**Why not equal-width bands?** At 46.875 Hz per bin, 40–15000 Hz is 319 bins.
Sixteen equal slices is 20 bins each, and 13 of the 16 would sit above 5 kHz,
where music has very little energy and the ear barely resolves it. The keyboard
would sit mostly dark with one lonely bar at the bottom.

**Log spacing** makes each band the same *ratio* wider than the last:

```
edge(i) = 40 · rⁱ        where r = (15000/40)^(1/16) = 1.4484
```

`np.logspace(log10(40), log10(15000), 17)` is just "17 points, equal steps in log
space" — the same thing. Measured edges:

```
40  58  84  122  176  255  369  535  775  1122
1625  2353  3409  4937  7151  10357  15000
```

1.4484 is about 6.5 semitones (a semitone is 1.0595), so each band is roughly a
musical interval wide. Not a coincidence — it matches the ear.

**The critical consequence:** band 0 contains **1** bin. Band 15 contains **100**
bins.

That is why the code takes the **mean** and not the **sum**. Summing would make
the top bands scream purely because they hold more bins.

**The cost of `mean`:** it dilutes a narrow peak. For a 1 kHz tone, band 8
(775–1122 Hz) holds 7 bins:

```
peak in band = 0.4648     mean of band = 0.1480     <- a third of the peak
```

**Amplitude, not power.** The code uses `|X|`, not `|X|²`. Power squares the
ratio and emphasises loud content much more aggressively; amplitude gives a
gentler, more readable display.

---

## 7. Decibels: what they are and why `20·log10`

A decibel is always a **ratio**, on a log scale:

```
amplitude ratio:  dB = 20·log₁₀(a₁/a₂)
power ratio:      dB = 10·log₁₀(p₁/p₂)
```

The `20` is `2 × 10` because power ∝ amplitude², so `10·log(a²) = 20·log(a)`.

| ratio | dB |
| --- | --- |
| 1.0 | 0 |
| 0.5 | −6.02 |
| 0.1 | −20 |
| 0.03 | −30.46 |
| 0.001 | −60 |

**Why bother?** Hearing is roughly logarithmic. Halving the amplitude doesn't
sound "half as loud", it sounds like a fixed small step. Equal dB steps ≈ equal
perceived steps, so a dB scale *looks* the way the sound *feels*.

The display mapping is then a straight line in dB:

```
level = (db + 18) / 18     clipped to 0…1
```

* `0 dB` → 1.0 (full height)
* `−9 dB` → 0.5 (half a column)
* `−18 dB` → 0.0 (dark)

The **18** is the window: how many dB below a band's own peak still shows. Wider
means more detail visible but everything stays lit; narrower means punchier but
quiet detail is lost.

---

## 8. Auto-gain: the ratio trick

```python
norm = raw / peak
peak = max(raw, peak * 0.94)
```

**Why a ratio.** `20·log10(raw/peak)` — the ratio is *dimensionless*. Turn your
speakers down and `raw` and `peak` both shrink by the same factor, so `norm` is
**unchanged**. That's why the display behaves identically on laptop speakers and a
club PA. It is the cleverest part of the design.

**Why `max()`.** It's a peak follower:

* signal jumps up → `peak` snaps up instantly (**instant attack**)
* signal falls → `peak` decays 6% per block (**exponential release**)

Half-life: `0.94ⁿ = 0.5` → `n = ln(0.5)/ln(0.94) = 11.2` blocks = **239 ms**. A
band "remembers" its loudest recent moment for about a quarter of a second.

**A consequence found by measuring.** Because `norm` is a pure ratio, the `gain`
multiplier scales `raw` *and* `peak` together — it cancels. In steady state the
Gain slider does nothing at all; it only matters for the first block after
silence. The slider looks like a main control and isn't.

**The failure mode with no floor.** In a band with no content, `raw` is just
leakage. `peak` decays down to meet it and `raw/peak` climbs to 1 — a band
carrying nothing reads full height. Hence the floor at `loudest × 10⁻³`, which
stops `peak` from collapsing that far.

---

## 9. Smoothing: a one-pole filter

```python
levels[n] = prev + (target − prev)·k
```

Rearranged:

```
levels[n] = (1−k)·prev + k·target
```

A weighted average of the past and the present — a **one-pole IIR filter**, or
exponential moving average. For a sudden step it has a closed form:

```
levels[n] = target + (levels₀ − target)·(1−k)ⁿ
```

The gap shrinks **exponentially**; each block closes `k` of what's left.

| `k` | role | gap left after 1 block | after 3 blocks | time constant τ = Δt/(−ln(1−k)) |
| --- | --- | --- | --- | --- |
| 0.55 | attack | 45% | 9.1% | **27 ms** |
| 0.18 | release | 82% | 55.1% | **107 ms** |

`np.where(shaped > prev, attack, release)` makes it **asymmetric**: fast up, slow
down. That is what a compressor's envelope follower does — snappy on transients,
no flicker on decay.

This runs once per *audio block* (46.9 times per second), not per send, so the fps
slider changes how often the keyboard updates but not how the response feels.

---

## 10. The noise floor: a leaky minimum

```python
floor[n] = min(raw[n], floor[n−1] + step)
```

To find a minimum you can only jump **down** when you see something lower, and you
**creep up** slowly so you can follow a floor that rises. `min()` is the instant
drop; `+ step` is the slow rise. Then `sig = max(raw − floor, 0)` removes it at
the source.

**The trap.** For a band holding a sustained note, the quietest level it reaches
*is the note*. A plain min-tracker would learn the music as "noise" and subtract
it. Hence the guard: only learn in bands below `loudest × 0.03` (−30 dB). Measured
— a real tone 20 dB, and even 30 dB, below a loud tone survives untouched.

---

## 11. Bands to columns

Sixteen bands, sixteen columns by default, so nothing happens. The interesting
cases:

* **fewer bands than columns** → interpolate; each band stretches over several keys
* **more bands than columns** → must combine. Averaging is right; interpolating
  would *step past* a peak landing between two columns. Measured: one lone band
  out of 21 came out at **0.33** with interpolation and **1.0** with averaging.

---

## 12. The whole chain, traced with measured numbers

A 1 kHz sine, amplitude 1.0. Note how the arbitrary constants cancel:

| Step | Band 8 (the tone) | Band 7 (empty) |
| --- | --- | --- |
| FFT + Hann + `/N/2` | peak 0.4648 | — |
| mean over the band's 7 bins | 0.1480 *(diluted 3×)* | 0.0005 |
| × `gain` 1.6 | 0.2368 | 0.0008 |
| AGC: `norm = sig/peak` | 1.0 *(ratio!)* | → 0 after the floor learns |
| dB: `20·log10(1.0)` | 0.0 dB | — |
| display: `(0 + 18)/18` | **1.00** | **0.00** |

That is exactly what the probe printed: band 8 at `1.00`, bands 0–7 and 9–15 at
`0.00`. The absolute numbers wandered (1.0 → 0.465 → 0.148) but because the AGC
divides by a peak, the *displayed* number landed where it should.

---

## 13. `process()` line by line

```python
rms = sqrt(mean(x*x))            # RMS = "typical level"; mean(x) would be ~0 for a wave
silent = rms < gate              # 0.02 ~= -34 dBFS. Below this, call it silence.
if silent: x = zeros             # hard mute so every band's raw goes to exactly 0

spec = abs(rfft(x * window))     # correlate with every frequency (s.2, s.5)
spec = spec / (N * 0.5)          # back to amplitude scale (s.3)

raw = [spec[mask].mean() for each band]   # log bands, mean not sum (s.6)
raw *= gain                      # pre-AGC scale -- cancelled out later (s.8)

loudest = raw.max()
global = max(loudest, global*0.94, tiny)  # loudest band, same decay
floor = max(tiny, global * 1e-3)          # peak may not decay below -60 dB (s.8)

quiet = raw <= global * 0.03              # "this band is effectively empty"
floor_per_band = where(quiet, min(raw, floor_per_band + step), floor_per_band)
sig = max(raw - floor_per_band, 0)        # subtract the noise floor (s.10)

peak = max(sig, max(peak*0.94, floor))    # peak follower per band (s.8)
norm = sig / (peak + 1e-6)                # dimensionless ratio

db = 20*log10(max(norm, 1e-9))            # logarithmic mapping (s.7)
shaped = clip((db + 18) / 18, 0, 1)

levels = where(shaped > prev,             # fast up...
               prev + (shaped-prev)*0.55,
               prev + (shaped-prev)*0.18) # ...slow down (s.9)
```

---

## 14. Experiments to make it click

Run these and watch the numbers — this is how the auto-gain bug was found.

```python
import numpy as np
SR, N = 48000, 1024
n = np.arange(N)
BW = SR / N                                     # 46.875

# 1. where does a tone land, and how tall is its peak?
x = np.sin(2*np.pi*1000*n/SR)
X = np.abs(np.fft.rfft(x*np.hanning(N))) / (N/2)
k = int(np.argmax(X))
print(1000/BW, k*BW, X[k], X[k+1])              # 21.33  984.4  0.465  0.372

# 2. what the window buys you
for w in (np.ones(N), np.hanning(N)):
    X = np.abs(np.fft.rfft(x*w))/(N/2)
    print((X > 0.01*X.max()).sum())             # 53 bins vs 6 bins

# 3. prove the AGC is a ratio: scale the input, output is identical
from rkm75rgb.dsp import Analyzer
a, b = Analyzer(bands=16), Analyzer(bands=16)
for _ in range(200):
    o1 = a.process((0.5 *np.sin(2*np.pi*1000*n/SR)).astype('float32'))
    o2 = b.process((0.05*np.sin(2*np.pi*1000*n/SR)).astype('float32'))
print(o1[8], o2[8])                             # 1.0  1.0  <- 10x quieter, same output
```

The third one is the whole design in two lines: **10× quieter input, identical
output.**
