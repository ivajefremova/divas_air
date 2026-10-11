"""Serve the web map locally.

    python scripts/serve_map.py [port]      ->  http://localhost:8080/app/web/

Serves the repo root (web app, map layers, replay bundle) and the orthophoto tiles under /tiles/
from config.TILES (set DIVAS_TILES_DIR to point at the hard drive).
"""

import socket
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from divas_air import config as C  # noqa: E402


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".geojson": "application/geo+json",
                      ".jsonl": "application/x-ndjson", ".js": "text/javascript"}

    def translate_path(self, path):
        if path.startswith("/tiles/"):
            return str(C.TILES / path[len("/tiles/"):].split("?")[0])
        return super().translate_path(path)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        if not str(args[1] if len(args) > 1 else "").startswith(("2", "3", "404")):
            super().log_message(fmt, *args)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    handler = partial(Handler, directory=str(C.ROOT))
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler)
    try:  # also answer on IPv6 loopback, which browsers try first for "localhost"
        class V6(ThreadingHTTPServer):
            address_family = socket.AF_INET6
        threading.Thread(target=V6(("::1", port), handler).serve_forever, daemon=True).start()
    except OSError:
        pass
    print(f"Divas Air map: http://localhost:{port}/app/web/   (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
