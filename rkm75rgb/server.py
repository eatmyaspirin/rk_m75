"""Local web app: serves the UI, an SSE telemetry stream and a small JSON API."""
from __future__ import annotations

import json
import pathlib
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import audio as audio_mod
from .engine import Engine, Settings

WEB_DIR = pathlib.Path(__file__).parent / "web"

_MIME = {".html": "text/html; charset=utf-8",
         ".js": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8",
         ".svg": "image/svg+xml",
         ".ico": "image/x-icon"}


class _Handler(BaseHTTPRequestHandler):
    engine: Engine = None            # set by serve()
    server_version = "rkm75rgb"

    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    # ------------------------------------------------------------- helpers
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    # ---------------------------------------------------------------- GET
    def do_GET(self):
        path = self.path.split("?", 1)[0]

        if path == "/api/state":
            return self._json(self.engine.snapshot())

        if path == "/api/devices":
            return self._json({
                "devices": audio_mod.list_inputs(),
                "default": audio_mod.default_loopback_name(),
                "available": audio_mod.available(),
            })

        if path == "/api/events":
            return self._events()

        # static files
        if path == "/":
            path = "/index.html"
        target = (WEB_DIR / path.lstrip("/")).resolve()
        if not str(target).startswith(str(WEB_DIR.resolve())) or not target.is_file():
            self.send_error(404)
            return
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", _MIME.get(target.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            while True:
                payload = self.engine.snapshot()
                payload["colors"] = self.engine.preview_colors()
                chunk = f"data: {json.dumps(payload)}\n\n".encode()
                self.wfile.write(chunk)
                self.wfile.flush()
                time.sleep(1 / 20)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            return

    # --------------------------------------------------------------- POST
    def do_POST(self):
        path = self.path.split("?", 1)[0]
        body = self._read_json()

        if path == "/api/config":
            s = self.engine.update(**body)
            return self._json({"ok": True, "settings": s})

        if path == "/api/start":
            self.engine.start()
            return self._json({"ok": True})

        if path == "/api/stop":
            self.engine.stop()
            return self._json({"ok": True})

        self.send_error(404)


def serve(engine: Engine, host: str = "127.0.0.1", port: int = 8765):
    _Handler.engine = engine
    httpd = ThreadingHTTPServer((host, port), _Handler)
    httpd.daemon_threads = True
    return httpd


def main(host: str = "127.0.0.1", port: int = 8765, settings: Settings | None = None,
         open_browser: bool = True):
    engine = Engine(settings)
    httpd = serve(engine, host, port)
    url = f"http://{host}:{port}/"
    print(f"rk-m75 equalizer running at {url}")
    print("press Ctrl+C to stop")
    if open_browser:
        threading.Timer(0.4, lambda: _open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        engine.stop()
        httpd.shutdown()
        print("\nstopped")


def _open(url: str):
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass
