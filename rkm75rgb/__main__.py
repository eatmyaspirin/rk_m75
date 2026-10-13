"""python -m rkm75rgb  ->  launch the local equalizer web app."""
from __future__ import annotations

import argparse

from .engine import Settings
from .server import main


def cli() -> None:
    p = argparse.ArgumentParser(prog="rkm75rgb", description="RK M75 audio-reactive RGB")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--fps", type=float, default=30.0, help="target update rate (max ~33)")
    p.add_argument("--mode", default="bars", choices=["bars", "mirror", "vu", "pulse"])
    p.add_argument("--palette", default="rainbow",
                   choices=["rainbow", "fire", "ocean", "ice", "neon", "mono"])
    p.add_argument("--bands", type=int, default=16)
    p.add_argument("--brightness", type=float, default=1.0)
    p.add_argument("--gain", type=float, default=1.6)
    p.add_argument("--device", default=None, help="audio input/loopback device name")
    p.add_argument("--no-browser", action="store_true")
    a = p.parse_args()

    settings = Settings(fps=a.fps, mode=a.mode, palette=a.palette, bands=a.bands,
                        brightness=a.brightness, gain=a.gain, device=a.device)
    main(host=a.host, port=a.port, settings=settings, open_browser=not a.no_browser)


if __name__ == "__main__":
    cli()
