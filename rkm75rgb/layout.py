"""Logical key -> LED index map, plus a physical (column, row) grid.

LED index = column * 6 + row. Recovered from the official RK software's
per-device layout for PID 0x0163 and validated by the `rk-m75` project.
"""
from __future__ import annotations

from .protocol import COLUMNS, LED_COUNT, ROWS

KEYMAP: dict[str, int] = {
    "ESC": 0, "F1": 12, "F2": 18, "F3": 24, "F4": 30, "F5": 36, "F6": 42,
    "F7": 48, "F8": 54, "F9": 60, "F10": 66, "F11": 72, "F12": 78, "DELETE": 84,
    "GRAVE": 1, "1": 7, "2": 13, "3": 19, "4": 25, "5": 31, "6": 37, "7": 43,
    "8": 49, "9": 55, "0": 61, "MINUS": 67, "EQUAL": 73, "BACKSPACE": 79, "HOME": 91,
    "TAB": 2, "Q": 8, "W": 14, "E": 20, "R": 26, "T": 32, "Y": 38, "U": 44,
    "I": 50, "O": 56, "P": 62, "LEFT_BRACKET": 68, "RIGHT_BRACKET": 74,
    "BACKSLASH": 80, "PAGE_UP": 92,
    "CAPS_LOCK": 3, "A": 9, "S": 15, "D": 21, "F": 27, "G": 33, "H": 39, "J": 45,
    "K": 51, "L": 57, "SEMICOLON": 63, "APOSTROPHE": 69, "ENTER": 81,
    "LEFT_SHIFT": 4, "Z": 10, "X": 16, "C": 22, "V": 28, "B": 34, "N": 40,
    "M": 46, "COMMA": 52, "PERIOD": 58, "SLASH": 64, "RIGHT_SHIFT": 82, "UP": 88,
    "LEFT_CTRL": 5, "LEFT_WIN": 11, "LEFT_ALT": 17, "SPACE": 35, "RIGHT_ALT": 53,
    "FN": 59, "RIGHT_CTRL": 65, "LEFT": 83, "DOWN": 89, "PAGE_DOWN": 93, "RIGHT": 95,
}

# Pretty labels for the UI grid; index -> label.
LABELS: dict[int, str] = {idx: name for name, idx in KEYMAP.items()}

# Columns that carry real keys (the rest of the 126 LEDs are aux outputs).
KEY_COLUMNS = max(KEYMAP.values()) // ROWS + 1


def grid() -> list[list[int | None]]:
    """Return COLUMNS x ROWS matrix of LED indices actually used by keys."""
    used = set(KEYMAP.values())
    return [
        [(col * ROWS + row) if (col * ROWS + row) in used else None for row in range(ROWS)]
        for col in range(COLUMNS)
    ]
