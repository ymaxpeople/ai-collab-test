"""HTTP layer on the Python standard library only (no web framework).

Endpoints (JSON):
  GET /health
  GET /v1/prices
  GET /v1/price/{tokenAddress}
  GET /v1/twap/{tokenAddress}?window=1h|24h
  GET /v1/pairs
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from . import config
from .service import PriceService
from .store import WINDOWS


def make_handler(service: PriceService):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # keep stdout clean
            pass

        def _send_json(self, obj, status=200):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            try:
                if path == "/health":
                    return self._send_json(service.health())
                if path == "/v1/prices":
                    return self._send_json(service.prices())
                if path == "/v1/pairs":
                    return self._send_json({"pairs": service.pairs()})
                if path.startswith("/v1/price/"):
                    address = path[len("/v1/price/"):]
                    result = service.price_by_address(address)
                    if result is None:
                        return self._send_json(
                            {"error": "token not found", "address": address}, 404)
                    return self._send_json(result)
                if path.startswith("/v1/twap/"):
                    address = path[len("/v1/twap/"):]
                    window = parse_qs(parsed.query).get("window", ["1h"])[0]
                    if window not in WINDOWS:
                        return self._send_json(
                            {"error": "window must be 1h or 24h"}, 400)
                    result = service.twap(address, window)
                    if result is None:
                        return self._send_json(
                            {"error": "token not found", "address": address}, 404)
                    return self._send_json(result)
                return self._send_json({"error": "not found", "path": path}, 404)
            except Exception as exc:  # noqa: BLE001 - surface as 500 JSON
                return self._send_json({"error": str(exc)}, 500)

    return Handler


def _background_refresh(service: PriceService, stop_event: threading.Event):
    while not stop_event.is_set():
        service.refresh()
        stop_event.wait(service.refresh_interval)


def serve(host: str, port: int, service: PriceService | None = None,
          background: bool = True):
    service = service or PriceService()
    service.refresh(force=True)
    stop_event = threading.Event()
    thread = None
    if background:
        thread = threading.Thread(target=_background_refresh,
                                  args=(service, stop_event), daemon=True)
        thread.start()
    server = ThreadingHTTPServer((host, port), make_handler(service))
    print(f"babel-fish-prices listening on http://{host}:{port} "
          f"(mode={'fixture' if service.fixture_mode else 'live'})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        server.server_close()
