"""Render spectrum data onto the keyboard's physical columns."""
from __future__ import annotations

import numpy as np

from .frame import Frame
from .protocol import ROWS
from .layout import KEY_COLUMNS

Color = tuple[int, int, int]

# ---------------------------------------------------------------- palettes
PALETTES: dict[str, list[tuple[float, Color]]] = {
    "rainbow": [(0.00, (255, 0, 0)), (0.17, (255, 170, 0)), (0.33, (0, 255, 0)),
                (0.50, (0, 255, 255)), (0.67, (0, 60, 255)), (0.83, (170, 0, 255)),
                (1.00, (255, 0, 120))],
    "fire": [(0.00, (120, 0, 0)), (0.35, (255, 60, 0)), (0.65, (255, 160, 0)),
             (0.85, (255, 230, 90)), (1.00, (255, 255, 220))],
    "ocean": [(0.00, (0, 10, 40)), (0.40, (0, 90, 180)), (0.75, (0, 200, 220)),
              (1.00, (180, 255, 255))],
    "ice": [(0.00, (0, 20, 60)), (0.50, (60, 140, 255)), (1.00, (235, 250, 255))],
    "neon": [(0.00, (60, 0, 120)), (0.45, (255, 0, 180)), (1.00, (0, 255, 200))],
    "mono": [(0.00, (0, 0, 0)), (1.00, (255, 255, 255))],
}

def palette_color(name: str, t: float, mono: Color = (0, 170, 255)) -> Color:
    """Sample a palette at position t in 0..1."""
    if name == "mono":
        return mono
    stops = PALETTES.get(name) or PALETTES["rainbow"]
    t = min(1.0, max(0.0, t))
    for i in range(len(stops) - 1):
        p0, c0 = stops[i]
        p1, c1 = stops[i + 1]
        if p0 <= t <= p1:
            span = (p1 - p0) or 1.0
            f = (t - p0) / span
            return (int(c0[0] + (c1[0] - c0[0]) * f),
                    int(c0[1] + (c1[1] - c0[1]) * f),
                    int(c0[2] + (c1[2] - c0[2]) * f))
    return stops[-1][1]


def to_columns(levels: np.ndarray, ncols: int = KEY_COLUMNS) -> np.ndarray:
    """Resample band levels onto the physical columns.

    Fewer bands than columns: interpolate, so each band stretches across several
    keys. More bands than columns: average the bands falling inside each column
    -- interpolating here would step straight past a narrow peak that happens to
    land between two columns.
    """
    levels = np.asarray(levels, dtype=np.float32).ravel()
    if levels.size == 0:
        return np.zeros(ncols, dtype=np.float32)
    if levels.size == 1:
        return np.full(ncols, float(levels[0]), dtype=np.float32)
    if levels.size == ncols:
        return levels.copy()

    if levels.size < ncols:
        src = np.linspace(0.0, 1.0, levels.size)
        dst = np.linspace(0.0, 1.0, ncols)
        return np.interp(dst, src, levels).astype(np.float32)

    # more bands than columns: split the bands as evenly as possible, then
    # average each group (levels.size > ncols guarantees every group is non-empty)
    q, r = divmod(levels.size, ncols)
    bounds = np.cumsum([0] + [q + (1 if i < r else 0) for i in range(ncols)])
    return np.array([levels[bounds[i]:bounds[i + 1]].mean() for i in range(ncols)],
                    dtype=np.float32)


def _scale(c: Color, f: float) -> Color:
    f = max(0.0, min(1.0, f))
    return (int(c[0] * f), int(c[1] * f), int(c[2] * f))


def render(frame: Frame, levels: np.ndarray, *, mode: str = "bars", palette: str = "rainbow",
           brightness: float = 1.0, mono: Color = (0, 170, 255), extra_leds: bool = False) -> None:
    """Draw the current spectrum into `frame`."""
    cols = to_columns(levels)
    n = cols.size
    frame.fill((0, 0, 0))

    if mode in ("bars", "mirror"):
        for c in range(n):
            lvl = float(cols[c]) * brightness
            color = palette_color(palette, c / max(1, n - 1), mono)
            if mode == "bars":
                lit = int(round(lvl * ROWS))
                for r in range(lit):
                    row = ROWS - 1 - r
                    frame.set_cell(c, row, _scale(color, 0.45 + 0.55 * (r / max(1, ROWS - 1))))
            else:  # mirror: grow from both ends toward the middle
                half = int(round(lvl * ROWS / 2))
                for r in range(half):
                    frame.set_cell(c, ROWS - 1 - r, color)
                    frame.set_cell(c, r, color)

    elif mode == "vu":
        lvl = float(cols.mean()) * brightness
        color = palette_color(palette, lvl, mono)
        for c in range(n):
            lit = int(round(lvl * ROWS))
            for r in range(lit):
                frame.set_led(frame.index_of(c, ROWS - 1 - r), color)

    elif mode == "pulse":
        lvl = float(cols.max()) * brightness
        color = palette_color(palette, min(1.0, lvl), mono)
        frame.fill(_scale(color, 0.15 + 0.85 * lvl))

    if extra_leds:
        lvl = float(cols.mean()) * brightness
        color = palette_color(palette, 0.5, mono)
        for idx in range(KEY_COLUMNS * ROWS, 126):
            frame.set_led(idx, _scale(color, lvl))
