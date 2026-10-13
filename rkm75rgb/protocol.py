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
