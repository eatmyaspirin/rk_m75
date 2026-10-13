# rk-m75 audio equalizer

Turns a Royal Kludge **M75** (wired USB, `258A:0163`) into a live audio
spectrum analyser: it captures your system audio, runs an FFT, and streams the
result to the keyboard's per-key RGB at ~30 fps.

Everything runs locally. No official RK software, no drivers, no cloud.

Explore the reverse-engineered internals: [docs/technical-notes.md](docs/technical-notes.md).

## Install

```powershell
pip install -r requirements.txt
```

## Run

```powershell
python -m rkm75rgb
```

Then open <http://127.0.0.1:8765/> (it opens automatically) and press **Start**.
Play some music and the keys light up.

Useful flags:

```powershell
python -m rkm75rgb --mode mirror --palette fire --bands 18 --fps 30
python -m rkm75rgb --device "Speakers (Realtek(R) Audio)"   # pick loopback device
python -m rkm75rgb --no-browser --port 9000
```

### Audio source

Capture uses WASAPI **loopback**, i.e. it records whatever is playing on a
selected output. If nothing lights up, you are almost certainly capturing the
wrong output device — pick the one your music actually plays through in the
**Audio source** dropdown. (If you output to an HDMI monitor and capture the
laptop speakers, you will get silence.)

## Modes

| Mode | Description |
| --- | --- |
| `bars` | Classic spectrum bars: each physical column is a band, level fills the column bottom-up |
| `mirror` | Same, but bars grow from both the bottom and top and meet in the middle |
| `vu` | Single colour, fills all keys proportionally to overall loudness |
| `pulse` | Whole keyboard pulses with the overall level |

Palettes: `rainbow`, `fire`, `ocean`, `ice`, `neon`, `mono` (with a colour
picker). Extras: band count, brightness, gain, attack/release smoothing, update
rate, idle glow, and an option to drive the 30 auxiliary LEDs.

The web UI also streams back exactly what the keyboard is showing — a live
spectrum canvas and a per-key preview grid.

## How it works

The M75 exposes a vendor HID collection and accepts a single 520-byte **feature
report (ID 9)** describing the whole RGB framebuffer:

```
09 08 00 00 01 00 7A 01 | <378 bytes: 126 x RGB> | <134 bytes padding>
^-- 8 byte packet header (cmd = 0x08 = RGB frame)
```

126 LEDs are driven as a `column * 6 + row` matrix; 16 columns carry real keys.
`rkm75rgb/layout.py` holds the validated logical-key -> LED map.

The firmware does **not** retain externally sent frames: it reclaims lighting
after ~1 second. So the stream is continuous — which is exactly what an
equalizer wants. Practical ceiling is ~33 fps (above that the HID transport
degrades to ~15 fps).

Pipeline:

```
system audio --> WASAPI loopback --> FFT --> log bands --> auto-gain/smoothing
     --> palette render --> 520-byte feature report --> keys
```

## Layout

```
rkm75rgb/
  protocol.py   constants for the vendor HID reports
  transport.py  hidapi transport (feature report 9)
  frame.py      126-LED framebuffer
  layout.py     key -> LED map and physical grid
  audio.py      WASAPI loopback capture
  dsp.py        FFT, log-spaced bands, auto-gain, smoothing
  effects.py    palettes + render modes
  engine.py     capture -> render -> send worker thread
  server.py     local HTTP + SSE server
  web/          the UI
```

The reverse-engineering scripts used to build this are kept locally in
`explore/` — they are intentionally not published (they contain extracts of
RK's minified driver).

## Notes & limitations

* **Wired USB only.** The 2.4 GHz dongle uses a different, more limited protocol.
* `soundcard` needs a working output device; on a headless box use a real input instead.
* Brightness/speed/effect settings you had configured in the driver are
  overridden while streaming, and return ~1s after you stop.

## Credits

The wired RGB framing and the 81-key LED mapping were reverse-engineered and
hardware-validated by <https://github.com/Lightning-13/rk-m75> (MIT). This
project re-implements the transport and adds audio analysis, rendering and a UI.

## The screen

The M75's OLED is a **status display** (connection, battery, RGB mode, time,
brightness). It has no host-reachable drawing path: the official WebHID driver
has no screen commands for this PID, the official desktop driver's
`Dev\0163\KB.ini` lacks the `ShowScreen`/`siScreen`/`MaxScreenFrame` keys that
screen models (e.g. RK S85, PID 0193) have, and the firmware ignores the
screen command set entirely.

Structurally it could not work either: the widest **output** report on the whole
device is **2 bytes**, so there is no pipe that could carry a framebuffer at any
speed. By contrast a keyboard whose screen *is* host-drivable — the Aula F75 Max —
exposes a dedicated interface with **4097-byte output reports**. Putting
arbitrary content on the M75's panel would require a hardware mod (driving the
panel directly) or custom firmware. See
[docs/technical-notes.md §6](docs/technical-notes.md#6-the-screen-protocol-and-why-it-doesnt-work).
