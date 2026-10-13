"""RK M75 wired RGB protocol constants.

Reverse-engineered from the official RK WebHID driver and independently
validated on hardware by the `rk-m75` community project (MIT).
"""

VENDOR_ID = 0x258A
PRODUCT_ID = 0x0163

USAGE_PAGE = 0xFF02
USAGE = 0x0001
INTERFACE = 1

REPORT_ID = 0x09
REPORT_SIZE = 520

# feature-report payload header: 09 08 00 00 01 00 7A 01
HEADER = bytes.fromhex("09 08 00 00 01 00 7A 01")
HEADER_SIZE = len(HEADER)

LED_COUNT = 126
RGB_SIZE = 3
FRAME_SIZE = LED_COUNT * RGB_SIZE
PADDING_SIZE = REPORT_SIZE - HEADER_SIZE - FRAME_SIZE

# Physical matrix geometry recovered from the logical key -> LED mapping.
# LED index = column * ROWS + row ; row 0 is the top row of that column.
ROWS = 6
COLUMNS = LED_COUNT // ROWS          # 21 (16 carry real keys, the rest are aux)

# --------------------------------------------------------------- commands
# Every command is a 519-byte payload in feature report 9:
#   [0] cmdId  [2] cmdVal  [3] 1  [5..6] dataLength (u16 LE)  [7..] data
#
# Verified working on PID 0x0163:
CMD_SET_PROFILE = 0x04
CMD_RGB_FRAME = 0x08
CMD_GET_PROFILE = 0x84
#
# Present in the official driver's shared protocol class, but this firmware does
# not answer them (see docs/technical-notes.md -- the board has a reduced
# command set, like the TFT/screen commands):
CMD_SET_LED_COLORS = 0x06     # stored per-key colour table, 378 bytes, 4 slots
CMD_GET_LED_COLORS = 0x86
CMD_TFT_PICTURE = 0x0C
CMD_TFT_CONTROL = 0x0D

# A response echoes the command; its data starts at byte 8 of the 520-byte report.
RESPONSE_DATA_OFFSET = 8

PROFILE_SIZE = 128
PROFILE_SLOTS = 4
LED_COLOR_SLOTS = 4

# boardProfile byte offsets, from the official driver's field map.
PROFILE_FIELDS = {
    "Profile": 0, "ReportRate": 1, "Debounce": 3, "LedParameterType": 5,
    "LedBrightness": 6, "LedSpeed": 7, "LedColor": 8, "LedModeSelection": 9,
    "LedMode": 10, "LedGameMode": 11, "WirelessChannel": 13, "KbConnectMode": 14,
    "WinLock": 15, "KeyLock": 16, "WASDSwitch": 17, "LogoMode": 18, "LogoColor": 19,
    "LogoBrightness": 20, "LogoSpeed": 21, "TapDelay": 22, "SleepTime": 24,
    "LedModeMemery": 26, "Logo2Mode": 27, "TimeFormat": 47, "WinMacMode": 54,
}

# The M75's effect list, in order, as shipped by the official driver. The stored
# LedMode byte holds the same index.
LIGHT_EFFECTS = [
    "FixedOn", "Respire", "Rainbow", "FlashAway", "Raindrops", "RainbowWheel",
    "RippleShining", "StarsTwinkle", "ShadowDisappear", "RetroSnake",
    "NeonStream", "Reaction", "SineWave", "Blossoming", "SelfDefine", "OFF",
]
LED_MODE_SELF_DEFINE = LIGHT_EFFECTS.index("SelfDefine")   # 14
LED_MODE_OFF = LIGHT_EFFECTS.index("OFF")                  # 15
