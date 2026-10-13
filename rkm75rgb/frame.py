"""126-LED RGB framebuffer for the RK M75."""
from __future__ import annotations

from typing import Iterable, Tuple

from .protocol import COLUMNS, FRAME_SIZE, HEADER, LED_COUNT, PADDING_SIZE, REPORT_SIZE, RGB_SIZE, ROWS

Color = Tuple[int, int, int]

_BLACK = (0, 0, 0)


class Frame:
    """A full RGB frame, addressable by LED index or by (column, row)."""

    __slots__ = ("_data",)

    def __init__(self, fill: Color = _BLACK):
        self._data = bytearray(FRAME_SIZE)
        if fill != _BLACK:
            self.fill(fill)

    # ---- addressing -------------------------------------------------
    @staticmethod
    def index_of(col: int, row: int) -> int:
        return col * ROWS + row

    def set_led(self, index: int, color: Color) -> None:
        if not 0 <= index < LED_COUNT:
            raise IndexError(index)
        o = index * RGB_SIZE
        self._data[o] = color[0]
        self._data[o + 1] = color[1]
        self._data[o + 2] = color[2]

    def set_cell(self, col: int, row: int, color: Color) -> None:
        self.set_led(self.index_of(col, row), color)

    def fill(self, color: Color) -> None:
        self._data[:] = bytes(color) * LED_COUNT

    # ---- output -----------------------------------------------------
    def to_report(self) -> bytes:
        return HEADER + bytes(self._data) + bytes(PADDING_SIZE)

    @property
    def raw(self) -> bytes:
        return bytes(self._data)
