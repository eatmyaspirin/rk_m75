# RK M75 — full technical notes

Everything learned while reverse-engineering the Royal Kludge M75 and building
`rkm75rgb`. Written so you could redo the whole thing from scratch.

* [0. TL;DR cheat sheet](#0-tldr-cheat-sheet)
* [1. The device](#1-the-device)
* [2. Windows HID fundamentals](#2-windows-hid-fundamentals)
* [3. The M75 HID layout](#3-the-m75-hid-layout)
* [4. The vendor protocol](#4-the-vendor-protocol)
* [5. Reverse-engineering the official web driver](#5-reverse-engineering-the-official-web-driver)
* [6. The screen protocol, and why it doesn't work](#6-the-screen-protocol-and-why-it-doesnt-work)
* [7. Unpacking the official desktop driver](#7-unpacking-the-official-desktop-driver)
* [8. The RGB framebuffer and key map](#8-the-rgb-framebuffer-and-key-map)
* [9. The audio equalizer](#9-the-audio-equalizer)
* [10. Toolbox](#10-toolbox)
* [11. Pitfalls](#11-pitfalls)
* [12. Reproduction checklist](#12-reproduction-checklist)

---

## 0. TL;DR cheat sheet

| Thing | Value |
| --- | --- |
| Vendor / Product | `0x258A` / `0x0163` (Sino Wealth) |
| RK's name for it | `RK-M75RGB New layout` |
| Command channel | HID **feature report ID `0x09`**, **520 bytes** |
| Collection | interface 1, `MI_01`, usage page `0xFF02`, usage `0x01`, **`Col05`** |
| Notification channel | interface 1, `Col03`, **input report ID `0x03`**, 3 bytes |
| RGB command | `cmdId = 0x08` + 378 bytes framebuffer |
| Framebuffer | 126 LEDs × RGB = 378 bytes, index = `col * 6 + row` |
| Max stable stream | ~33 Hz |
| Firmware reclaims lighting | ~1 s after you stop sending |
| Screen (OLED) | status only — **no host drawing path** |

Minimal working sender:

```python
import hid

VENDOR, PRODUCT = 0x258A, 0x0163
HEADER = bytes.fromhex("09 08 00 00 01 00 7A 01")   # report id + cmd 0x08

path = next(d["path"] for d in hid.enumerate(VENDOR, PRODUCT)
            if b"Col05" in d["path"])

frame = bytes([255, 0, 0]) * 126            # all keys red
report = HEADER + frame + bytes(520 - 8 - 378)

dev = hid.device()
dev.open_path(path)
for _ in range(30):                          # keep it alive ~1 s
    dev.send_feature_report(report)
dev.close()
```

---

## 1. The device

```
VID              0x258A   (Sino Wealth Electronic)
PID              0x0163
iProduct         "Gaming KB "
iManufacturer    "SINO WEALTH"
bcdDevice        0x2005
Bus              USB composite, 2 interfaces
```

Find it on Windows:

```powershell
Get-PnpDevice -PresentOnly |
  Where-Object { $_.InstanceId -match 'VID_258A&PID_0163' } |
  Select-Object Class, FriendlyName, InstanceId
```

```
USB\VID_258A&PID_0163&MI_00   -> keyboard  (usage page 0x01, usage 0x06)
USB\VID_258A&PID_0163&MI_01   -> vendor    (8 HID collections)
```

> **Note.** `PID 0x0163` is shared across RK product lines. RK's firmware index
> file calls it `RK872_upf_v1.33_231027_PID_0163_2002.rar`, while the web driver
> calls it `RK M75`. "RK872" is a PCB/platform designation, not a product name.

**How we know it's an M75:** the official web driver's device table contains

```js
{ name:"RK M75", image:"keyboard_rk-m75.png",
  vendorId:9610, productId:355,        // 0x258A, 0x0163
  usagePage:65280, usage:1,            // 0xFF00 : 1
  connectType:"USB", protocolType:"BeiYing",
  protocol: Y_t.create }
```

---

## 2. Windows HID fundamentals

You need three different levels of access, and each has its own API.

### 2.1 Enumeration — hidapi

```python
import hid
for d in hid.enumerate(0x258A, 0x0163):
    print(d["path"], d["usage_page"], d["usage"], d["interface_number"])
```

`hid.enumerate()` returns one entry **per HID collection**, not per device.
Useful keys: `path`, `usage_page`, `usage`, `interface_number`,
`product_string`, `manufacturer_string`.

Install: `pip install hidapi` (module name is `hid`).

> ⚠️ The module from PyPI `hidapi` exposes the **old lowercase API**:
> `hid.device()`, `dev.open_path()`, `dev.send_feature_report()`,
> `dev.get_feature_report()`, `dev.read()`, `dev.get_report_descriptor()`.
> There is **no** `hid.Device` (that's the different `hid` package).

### 2.2 Report lengths — `HidP_GetCaps`

The only reliable way to learn how big a collection's reports are:

```python
import ctypes as C
from ctypes import wintypes as W

k32 = C.WinDLL("kernel32", use_last_error=True)
hid_dll = C.WinDLL("hid.dll")
k32.CreateFileW.restype = C.c_void_p
k32.CreateFileW.argtypes = [C.c_wchar_p, C.c_uint32, C.c_uint32, C.c_void_p,
                            C.c_uint32, C.c_uint32, C.c_void_p]
hid_dll.HidD_GetPreparsedData.argtypes = [C.c_void_p, C.POINTER(C.c_void_p)]
hid_dll.HidP_GetCaps.argtypes = [C.c_void_p, C.c_void_p]

class HIDP_CAPS(C.Structure):
    _fields_ = [("Usage", W.USHORT), ("UsagePage", W.USHORT),
                ("InputReportByteLength", W.USHORT),
                ("OutputReportByteLength", W.USHORT),
                ("FeatureReportByteLength", W.USHORT)]

# access=0 works even for collections Windows "reserves" (keyboard/mouse)
h = k32.CreateFileW(path.decode(), 0, 3, None, 3, 0, None)   # 3 = OPEN_EXISTING
pp = C.c_void_p()
hid_dll.HidD_GetPreparsedData(h, C.byref(pp))
caps = HIDP_CAPS()
hid_dll.HidP_GetCaps(pp, C.byref(caps))
print(caps.FeatureReportByteLength)
```

### 2.3 Report descriptors — use hidapi, not the IOCTL

`DeviceIoControl(IOCTL_HID_GET_REPORT_DESCRIPTOR, ...)` on Windows returns a
blob prefixed with the ASCII magic `HidP KDR` — it is **not** the raw report
descriptor and does not parse as one. hidapi's own accessor gives you the real
thing:

```python
dev = hid.device(); dev.open_path(path)
desc = bytes(dev.get_report_descriptor())     # real HID report descriptor
```

Tiny HID item parser (enough to read report IDs and sizes):

```python
def parse(desc):
    i, report_id, rsize, rcount, rows = 0, 0, 0, 0, []
    while i < len(desc):
        b = desc[i]
        if b == 0xFE:                       # long item
            size = desc[i+1]; i += 3 + size; continue
        size = 4 if (b & 3) == 3 else (b & 3)
        val  = int.from_bytes(desc[i+1:i+1+size], "little") if size else 0
        i += 1 + size
        typ, tag = (b >> 2) & 3, (b >> 4) & 0xF
        if typ == 1:                        # global
            if tag == 8: report_id = val
            elif tag == 7: rsize = val
            elif tag == 9: rcount = val
        elif typ == 0 and tag in (8, 9, 11):  # input/output/feature
            rows.append((tag, report_id, rsize, rcount,
                         (rsize * rcount + 7) // 8))
    return rows
```

`tag`: `8 = Input`, `9 = Output`, `11 = Feature`.

### 2.4 Reading and writing

```python
dev = hid.device()
dev.open_path(path)
dev.set_nonblocking(1)                        # 0 = blocking

# WRITE: the first byte of the buffer IS the report id
dev.send_feature_report(bytes([0x09]) + payload)

# READ: pass the report id, and the length must match exactly
data = dev.get_feature_report(0x09, 520)      # NOT 519 — see pitfalls
```

---

## 3. The M75 HID layout

Interface 1 (`MI_01`) exposes eight collections. Dumped with the techniques
above:

| Collection | Usage page:usage | Kind | Report ID | Payload | What it is |
| --- | --- | --- | --- | --- | --- |
| `Col01` | `0x0001:0x0080` | Input | — | — | System control |
| `Col02` | `0x000C:0x0001` | Input | — | — | Consumer control (media keys) |
| **`Col03`** | `0xFF02:0x0001` | **Input** | **`0x03`** | **3 B** | **Device → host notifications** |
| `Col04` | `0x0001:0x0006` | Input | — | — | Keyboard |
| **`Col05`** | `0xFF02:0x0001` | **Feature** | **`0x09`** | **519 B** | **The command channel** |
| `Col06` | `0x0001:0x0002` | Input | — | — | Mouse (NKRO fallback) |
| `Col07` | `0xFF00:0x0001` | Feature | `0x05` | 5 B | small vendor channel |
| `Col08` | `0xFF00:0x0001` | Feature | `0x06` | 1031 B | large vendor channel |

Key observations:

* **Two collections share `0xFF02:0x0001`.** They are not interchangeable:
  `Col03` is input-only, `Col05` is feature-only. You must match on `Col05`.
* `FeatureReportByteLength` from `HidP_GetCaps` is **1 more** than the
  descriptor's payload (it includes the report ID). `520 = 1 + 519`.
* `Col07`/`Col08` (`0xFF00`) exist but do **not** accept report 9 — sending
  report 9 to them returns `-1`. Only `Col05` does.
* The web driver's device table lists `usagePage 0xFF00` for the M75 (USB),
  yet its protocol sends feature report 9 — which lives on the `0xFF02`
  collection. Trust the descriptors, not the driver's filter list.

---

## 4. The vendor protocol

### 4.1 Frame format

Every command is a 519-byte payload wrapped in feature report 9:

```
byte  0        cmdId
byte  1        cmdVal
byte  2..3     varies
byte  4        packageNum        (multi-packet ops)
byte  5        packageIndex
byte  6..7     dataLength        (little-endian u16)
byte  8..      data
```

The base packet class in the official driver:

```js
class DE {
  constructor(t) { this.cmdId = t; this.cmdVal = 0;
                   this.packageNum = 0; this.packageIndex = 0; this.dataLength = 0; }
  fromReportData(t) {
    this.packageNum   = t.getUint8(4);
    this.packageIndex = t.getUint8(5);
    this.dataLength   = t.getUint8(6) | (t.getUint8(7) << 8);
    return this;
  }
}
```

Note the driver's constant `I1 = 7`: responses are sliced at **offset 7**, i.e.
the JS DataView it receives already excludes the report ID, so `slice(1, …)`
plus `I1` lands on payload byte 8.

### 4.2 Known commands

| cmdId | Name | Notes |
| --- | --- | --- |
| `0x04` (4) | `setProfile` | payload at offset 7, 128 bytes, `cmdVal = profile & 3` |
| `0x05` (5) | — | used by some packet classes |
| `0x07` (7) | — | |
| `0x08` (8) | **RGB frame** | 378-byte framebuffer at offset 8 |
| `0x0B` (11) | status | observed in captures |
| `0x0C` (12) | TFT picture chunk | **not implemented on this model** |
| `0x0D` (13) | TFT control | **not implemented on this model** |
| `0x11` (17) | — | 1-byte payload class |
| `0x44` (68) | paged data | |
| `0x82` (130) | `getPassword` / firmware version | read-only |
| `0x84` (132) | `getProfile` | read-only |

### 4.3 Reads vs writes

Two fundamentally different behaviours:

* **Read commands** (`130`, `132`, …) answer via `get_feature_report(9, 520)`.
* **Write commands** (`4`, `8`, `12`, `13`, …) are fire-and-forget: no
  acknowledgement, no response. In the driver they are pushed onto a queue
  (`postMessage`) and the worker paces them. **This is why "no reply" proves
  nothing about whether a write command is supported.**

That subtlety cost real time during the screen investigation.

### 4.4 Handshake

```python
def get_password():
    p = bytearray(519)
    p[0] = 130     # cmdId
    p[1] = 1       # cmdVal
    p[3] = 1
    p[5] = 10      # dataLength = 10
    dev.send_feature_report(bytes([9]) + bytes(p))
    return dev.get_feature_report(9, 520)
```

Observed reply:

```
09 82 01 00 01 00 0a 00 03 00 00 00 00 a7 00 00 50 00
^  ^  ^        ^
|  |  |        dataLength = 0x0a
|  |  cmdVal = 1
|  cmdId = 0x82 (130) echoed
report id 9
```

### 4.5 Reading the configuration profile

```python
def get_profile(index=0):
    p = bytearray(519)
    p[0] = 132            # cmdId
    p[2] = index & 3      # cmdVal
    p[3] = 1
    p[5] = 128            # dataLength
    dev.send_feature_report(bytes([9]) + bytes(p))
    return bytes(dev.get_feature_report(9, 520))
```

Real reply from the keyboard (trimmed):

```
09 84 00 00 01 00 80 00 | 00 03 03 01 00 00 13 04 0b 00 0f 20 01 00 … 5a a5
                          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ 128-byte profile
^  ^                    ^
|  cmd 132              dataLength = 0x80 (128)
report id
```

The profile is a flat 128-byte buffer addressed by byte offset. The field
enumeration (identical across the several RK platforms in the bundle):

```
Profile=0  ReportRate=1  Debounce=3  LedParameterType=5
LedBrightness=6  LedSpeed=7  LedColor=8  LedModeSelection=9  LedMode=10
LedGameMode=11  WirelessChannel=13  KbConnectMode=14  WinLock=15  KeyLock=16
WASDSwitch=17  LogoMode=18  LogoColor=19  LogoBrightness=20  LogoSpeed=21
TapDelay=22  SleepTime=24  LedModeMemery=26  Logo2Mode=27  TimeFormat=47
WinMacMode=54
```

> **This list is the proof about the screen.** There is no screen-content,
> image, GIF, TFT or LCD field anywhere in it. The only display-adjacent setting
> is `TimeFormat` (12/24 h) — consistent with a clock on the panel.

---

## 5. Reverse-engineering the official web driver

RK's keyboards are configured by a WebHID web app, not only the desktop exe.
That made the protocol readable as JavaScript.

### 5.1 Getting the bundle

* App: `https://drive.rkgaming.com/` (also `drive2.rkgaming.com`, `rk.hubx.pro`)
* `index.html` → `/assets/index-XXXX.js` (~20 MB, minified)
* An offline mirror of an older version exists:
  `https://github.com/Flalal/RKGaming-offline`

```powershell
$r = Invoke-WebRequest 'https://drive.rkgaming.com/' -UseBasicParsing
[regex]::Matches($r.Content,'(?:src|href)="([^"]+)"') | % { $_.Groups[1].Value }
```

The bundle lazy-loads its protocol code from a Web Worker
(`/assets/communication-*.js`) — but in this case those workers only do
retry/pacing; the packet builders are inline in the main bundle.

### 5.2 Finding the device table

```python
import re
text = open("index-VUAGPBO3.js", encoding="utf-8", errors="replace").read()
for m in list(re.finditer(r'name:"RK M75"', text))[:3]:
    print(text[m.start()-200 : m.start()+400])
```

That yields the entry in §1, including `protocol: $B.create`.

### 5.3 Following aliases

Minifiers rename everything. The M75 entry pointed at `$B`, defined elsewhere as:

```js
$B = class Y_t extends O_t { … }
```

Extract classes by **brace matching** rather than trying to read the file:

```python
def block_at(text, start):
    i = text.index("{", start); depth = 0
    for j in range(i, len(text)):
        c = text[j]
        if c in "{([": depth += 1
        elif c in "})]":
            depth -= 1
            if depth == 0:
                return text[i:j+1]
```

(Good enough on minified JS. A production parser would need string/comment
awareness, but these bundles don't contain `{` inside strings often enough to
matter in practice — verify anything surprising by hand.)

Reading `Y_t` was the turning point: it has `getProfile`, `setProfile`,
`getLedEffect`, `getKeyMatrix`, `setMacros`, `setLedColors`, `setFactory` — and
**no screen methods at all**. Screens live in *other* protocol classes.

### 5.4 Extracting the packet layout

The RGB packet (in the same family of classes):

```js
r7t = class extends DE {                       // cmd 12, TFT picture chunk
  constructor() {
    super(12);
    this.setReport = new Uint8Array(519);
  }
  setPayload() {
    let s = 0;
    this.setReport[s++] = this.cmdId;          // [0] cmd
    this.setReport[s++] = 0;                   // [1]
    this.setReport[s++] = this.frameIndex;     // [2]
    this.setReport[s++] = this.packageIndex;   // [3]
    s++;                                       // [4] checksum (filled below)
    let len = …;
    this.setReport[s++] = len & 255;           // [5]
    this.setReport[s++] = len >> 8;            // [6]
    let n = 0;
    for (…) { this.setReport[s++] = data[_]; n += data[_]; }
    this.setReport[4] = 255 & n;               // sum of bytes mod 256
    return this;
  }
}
```

And the constants that go with it:

```js
Ete = 512;                    // chunk size
I1  = 7;                      // payload data offset
Ile = 128;                    // profile length
TN  = 512; TNe = 4096;        // macro chunk / total
vg  = 9;                      // feature report id   (also named Dh)
```

Different protocol families in the same bundle use different report ids and
different command numbers — **always confirm which class your device maps to**
before trusting a constant.

---

## 6. The screen protocol, and why it doesn't work

The M75 has a small OLED ("OLED Smart Display" per RK's own store listing) that
shows connection mode, battery, RGB mode, time and brightness.

### 6.1 The screen protocol (used by *other* RK models)

Lifted from the TFT-capable protocol classes:

```js
// cmd 13 — control
K0e = class extends DE {
  constructor() { super(13); this.dataLength = 5;
                  this.setReport = new Uint8Array(519);
                  this.setReport[0] = 13; this.setReport[3] = 1;
                  this.setReport[5] = 5; }
  setPayload(frameCount, mode, delay) {
    this.setReport[7]  = mode << 6;      // 1 = start, 0 = commit, 2 = abort
    this.setReport[8]  = frameCount;
    this.setReport[10] = delay & 255;
    this.setReport[11] = delay >> 8;
    return this;
  }
}
```

Frames are **big-endian RGB565**, two bytes per pixel, chunked into 512-byte
packets, one `cmd 12` packet per chunk, driven by a start (mode 1) and a commit
(mode 0).

### 6.2 It is not implemented on the M75

Three independent confirmations:

1. **Web driver** — the M75's protocol class `Y_t` has no `setTftPic`; the
   screen methods exist only in classes bound to other PIDs.
2. **Desktop driver** — screen support is gated by per-model keys. Compare:

   ```ini
   ; Dev\0193\KB.ini   (RK S85 — a screen model)
   ShowScreen=1
   RGBScreen=1
   MaxScreenFrame=60
   DataUnitSize=512
   siScreen=320,172
   LatticeW=1
   DrawFrameTime=180

   ; Dev\0163\KB.ini   (your M75)  -> none of these keys exist
   Fw=1
   Psd=3,0,0,0,0,A7
   RGBKb=1
   LayoutKeyNum=84
   KbLayout=5
   LayerNum=3
   ShowSleepTime=1
   SendSysParam=2000
   ```

   Only `Dev\0193` and `Dev\01B8` ship a `screen.gif` at all.
3. **Hardware** — sending `cmd 13` start → 512-byte `cmd 12` chunks → `cmd 13`
   commit at both 240×135 and 128×128 produced no visible change and no
   acknowledgement.

### 6.3 Why "no ACK" was a trap

Write commands are fire-and-forget (§4.3), so a silent `cmd 13` did **not**
prove anything on its own. What settled it was the *combination*: no ACK, no
visual change, no reference to the command in any RK software path, and no
config surface for a screen.

### 6.4 What would be required

* **Hardware:** own the panel — sniff its bus (I²C `SSD1306`/`SH1106` if
  monochrome, SPI `ST77xx` if colour), learn the init sequence, then drive it
  from your own MCU. Always works, replaces the stock status UI.
* **Firmware:** dump and patch the stock image. RK's firmware file
  (`RK872_upf_v1.33_231027_PID_0163_2002.rar`) 404s and was never archived by
  the Wayback Machine. Long project, real brick risk.

---

## 7. Unpacking the official desktop driver

The current installer is advertised in:

```
http://www.rkgaming.com/work/Update-RGB/update_version.xml
  <drv version="0406" url="…/RK_Keyboard_Software_BY_Setup.exe"/>
  <fw  pid="0163" version="2000" url="…/RK872_upf_v1.33_231027_PID_0163_2002.rar"/>
```

("BY" = BeiYing, the protocol family your keyboard speaks.)

`7z` **cannot** open this installer — it is **Inno Setup**, not an archive.
Use `innoextract`:

```powershell
# https://github.com/dscharrer/innoextract/releases -> innoextract-1.9-windows.zip
innoextract.exe -e -d out RK_Keyboard_Software_BY_Setup.exe
```

Useful things that fall out:

```
app/DeviceDriver.exe      the MFC application (2.4 MB)
app/Dev/0163/KB.ini       per-model capability config
app/Dev/0193/screen.gif   screen animation for the RK S85
app/Cartoon/<n>/          LED animation descriptors (not screens)
app/Cfg.ini               global config: PID list, DevName… mappings
```

Static analysis is just strings, in both encodings:

```python
import re, pathlib
b = pathlib.Path("DeviceDriver.exe").read_bytes()
ascii_s = re.findall(rb"[\x20-\x7e]{4,}", b)
utf16_s = re.findall(rb"(?:[\x20-\x7e]\x00){4,}", b)
```

Class names recovered this way told the whole story:

```
CDevRKKB, CDevG5KB, CDev3632        the three device protocol families
CScreenDlg, CBurnScreenDlg          screen UI
SetGIFParam: nGifIndex=%d, nFrameNum=%d, nGifDelay=%d
CDevG5KB::AccessData_Page frame=%d, page=%d, CRC(out)=%x, CRC(in)=%x
Found screen dev, read psd now. / Screen psd match ok.
Get kb psd err, ShowScreen=2 must need to read psd
```

Notice the naming: the M75 belongs to `CDevRKKB`, and the screen machinery
belongs to the G5 platform (`CDevG5KB`) — two different worlds.

---

## 8. The RGB framebuffer and key map

### 8.1 Packet

```
offset  size  content
0       8     header: 09 08 00 00 01 00 7A 01
              09        report id
              08        cmdId (RGB frame)
              00 00
              01
              00
              7A 01     dataLength = 0x017A = 378  (little-endian)
8       378   126 LEDs x (R,G,B)
386     134   zero padding
total   520
```

### 8.2 Indexing

The LED chain is wired **column-major with 6 rows per column**:

```
led_index = column * 6 + row      row 0 = top row of that column
```

So `ESC=0, GRAVE=1, TAB=2, CAPS_LOCK=3, LEFT_SHIFT=4, LEFT_CTRL=5`, then the
next column starts at 6: `1=7, Q=8, A=9, Z=10, LEFT_WIN=11, F1=12`, …

126 LEDs = 21 columns × 6 rows, but only **16 columns** carry physical keys
(the remaining 30 LEDs are auxiliary outputs — we never identified them, and we
leave them dark by default).

This is why a vertical-bar equalizer works so naturally: lighting `(col, row)`
for increasing `row` draws a bar straight up a physical column.

### 8.3 Persistence

A single frame is transient. The firmware reclaims lighting after **~1 s**, so
you must keep streaming. Measured behaviour:

| Rate | Result |
| --- | --- |
| 10–33 Hz | stable; 33 Hz sustained for 5 min / 9900 frames with 0 errors |
| ≥ 34 Hz | transport degrades to ~15 Hz with 60–90 ms per send |

Hence the 33 fps cap in `rkm75rgb`.

---

## 9. The audio equalizer

### 9.1 Pipeline

```
system output ──WASAPI loopback──▶ mono float32 blocks (1024 @ 48 kHz)
   ──Hann window──▶ rFFT ──log-spaced bands──▶ per-band magnitude
   ──AGC (decaying peak)──▶ perceptual curve ──asymmetric smoothing──▶ 0..1
   ──palette ──▶ 126-LED frame ──▶ 520-byte feature report ──▶ keyboard
```

Threading: one worker thread does capture → analyse → render → send. The HTTP
server only reads state; nothing blocks the audio path.

### 9.2 Auto-gain (the thing that makes it feel good)

Without AGC, quiet tracks barely move and loud tracks clip. Each band tracks a
decaying peak:

```python
self._peak = np.maximum(raw, self._peak * 0.94)     # decay ~6% per block
norm = raw / (self._peak + 1e-6)
```

Then a perceptual curve (`**1.35`) and asymmetric smoothing — fast attack so
transients punch, slow release so it decays gracefully:

```python
self._levels = np.where(norm > prev,
                        prev + (norm - prev) * attack,     # 0.55
                        prev + (norm - prev) * release)    # 0.18
```

### 9.3 Band → column mapping

```python
src = np.linspace(0, 1, len(levels))       # e.g. 16 bands
dst = np.linspace(0, 1, 16)                # physical columns
cols = np.interp(dst, src, levels)
```

Modes then differ only in how a column's level becomes rows:

* `bars` — `lit = round(level * 6)`, fill bottom-up, brightness ramps with height
* `mirror` — grow from both ends toward the middle
* `vu` — one colour, fill proportional to overall level
* `pulse` — whole board brightness follows peak level

### 9.4 Audio capture on Windows

```python
import soundcard as sc
spk = sc.default_speaker()
mic = sc.get_microphone(spk.name, include_loopback=True)   # WASAPI loopback
with mic.recorder(samplerate=48000, blocksize=1024) as rec:
    block = rec.record(numframes=1024)                     # (frames, channels)
```

Loopback records a chosen **output**. If the app looks dead, the music is
almost always playing through a different output device than the one being
captured — that is the single most common failure.

### 9.5 Server shape

Stdlib only (`ThreadingHTTPServer`), which avoids a dependency on FastAPI:

| Route | Purpose |
| --- | --- |
| `GET /` | UI |
| `GET /api/state` | one-shot snapshot |
| `GET /api/devices` | loopback + input device list |
| `GET /api/events` | **SSE**, 20 Hz telemetry (bands + 126 LED colours) |
| `POST /api/config` | live settings |
| `POST /api/start` / `/api/stop` | run control |

Server-Sent Events are a good fit here: one-way, text, trivially implemented,
and they auto-reconnect.

---

## 10. Toolbox

### Python

| Need | Use |
| --- | --- |
| HID enumeration / IO | `hidapi` (`import hid`) |
| Report sizes | `ctypes` → `HidP_GetCaps` |
| Real report descriptors | `hid.device.get_report_descriptor()` |
| FFT / arrays | `numpy` |
| System audio | `soundcard` |
| Image handling (research) | `pillow` |
| PDF page rendering | `pymupdf` |

### Shell (Windows)

```powershell
# device presence
Get-PnpDevice -PresentOnly | ? { $_.InstanceId -match 'VID_258A' }

# registry: every enumerated instance of a VID/PID
Get-ChildItem 'HKLM:\SYSTEM\CurrentControlSet\Enum\USB\VID_258A&PID_0163'

# which HID collections exist
Get-ChildItem 'HKLM:\SYSTEM\CurrentControlSet\Enum\HID' | ? { $_.PSChildName -match '258A' }
```

### Tools

| Tool | Why |
| --- | --- |
| `innoextract` | unpack Inno Setup installers (`7z` cannot) |
| `7-Zip` | everything else |
| brace-matching extractor | read specific classes out of a 20 MB minified bundle |
| ASCII + UTF-16LE string scan | recover class names and log strings from an MFC exe |

### Search workarounds

Reddit, DuckDuckGo, manuals.plus and `manuals.plus` all captcha-bot-blocked
plain HTTP fetching. What worked:

* `https://html.duckduckgo.com/html/?q=…` for a while, then it added a captcha
* **Bing** via a real browser (`tools.chrome.*`) — reliable
* **A site's own JSON API** is the best route. e.g. RK's manuals index:

  ```
  GET https://en.rkgaming.com/api/support-books/?cid=1&page=1&keyword=M75
  → [{"id":99,"name":"M75","file":"/media/files/…/…pdf"}]
  ```

  and driver/firmware metadata:

  ```
  GET https://en.rkgaming.com/download/get_version_or_attr_ajax/?category_id=1
  ```

---

## 11. Pitfalls

**HID**

1. `hid.Device` does not exist in the PyPI `hidapi` module — it's `hid.device()`.
2. `send_feature_report(buf)` takes the report ID as `buf[0]`.
3. `get_feature_report(9, 519)` fails with `OSError: read error`;
   `get_feature_report(9, 520)` works. **Pass the full length including the
   report ID.**
4. Opening a keyboard's `Col04` top-level collection with `GENERIC_READ` fails
   with `err 5`. Open with **access = 0** instead.
5. Two collections can share `usage_page`/`usage`. Match on the **path**
   (`Col05`) or on report size, never on usage alone.
6. The `IOCTL_HID_GET_REPORT_DESCRIPTOR` blob is prefixed with `HidP KDR` and
   is not a valid descriptor. Use hidapi's accessor.
7. Windows keeps *three* registry instances for this single keyboard
   (`7&1f77a4bc`, `7&316e7b4a`, `7&88d61e8`) — historical enumerations, not
   three devices.

**PowerShell**

8. `$B`, `$var`, `$env:` inside **double-quoted** strings get expanded and
   silently corrupt regexes. Use single quotes: `'\$B\s*='`.
9. The default console encoding is cp1252 and will `UnicodeEncodeError` on
   box-drawing/symbol bytes. Set `sys.stdout.reconfigure(encoding="utf-8",
   errors="replace")` or write results to a file.
10. `Select-String` on a UTF-16 XML file shows nothing — decode with
    `[Text.Encoding]::Unicode` first.
11. Recursive `Get-ChildItem C:\ -Recurse` will time out. Scope it.

**Reverse-engineering method**

12. Minified names are meaningless; follow the **data**, not the names. Here the
    M75 entry's `protocol:` field was the single most valuable byte of the whole
    investigation.
13. Same-named constants differ between protocol families in one bundle. Confirm
    the class first.
14. **Absence of an ACK is not evidence** when writes are fire-and-forget.
15. Distinguish *not implemented* from *not exercised*. The screen commands are
    implemented in the codebase — just not in the firmware bound to PID 0163.

**Audio**

16. Loopback captures a specific output device. Wrong device = silence.
17. Cap at ~33 Hz; above it the HID transport degrades.

---

## 12. Reproduction checklist

```powershell
# 1. Dependencies
pip install hidapi numpy soundcard

# 2. Confirm the device is present
python explore/enum_hid.py            # 9 collections, Col05 = feature 520 B
python explore/dump_reports.py        # report ids: Col03=0x03, Col05=0x09

# 3. Talk to it
python explore/probe_read.py          # handshake cmd 130 -> fw version
python explore/rgb_test.py            # solid colours, column sweep, WASD

# 4. Run the app
python -m rkm75rgb                    # http://127.0.0.1:8765/
```

Research scripts used along the way are kept locally in `explore/` and are
deliberately **not** part of the published repository (they contain extracts of
RK's minified driver). The commands below are the ones they run.

### Quick protocol self-test

```python
import hid
V, P = 0x258A, 0x0163
path = next(d["path"] for d in hid.enumerate(V, P) if b"Col05" in d["path"])
dev = hid.device(); dev.open_path(path); dev.set_nonblocking(1)

# read the config profile (proves the channel works)
p = bytearray(519); p[0] = 132; p[3] = 1; p[5] = 128
dev.send_feature_report(bytes([9]) + bytes(p))
resp = bytes(dev.get_feature_report(9, 520))
assert resp[1] == 0x84, resp.hex(" ")          # cmd 132 echoed
print("profile:", resp[8:8+128].hex(" "))
```
