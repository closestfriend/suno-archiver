"""Shared test helpers: a tiny threaded HTTP server with per-test handlers."""

import http.server
import json
import threading


class LocalServer:
    """handler(method, path, headers, body) -> (status, headers_dict, body_bytes)."""

    def __init__(self, handler):
        outer_handler = handler

        class Handler(http.server.BaseHTTPRequestHandler):
            def _respond(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                status, headers, out = outer_handler(
                    self.command, self.path, dict(self.headers), body
                )
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            do_GET = _respond
            do_POST = _respond

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def json_response(status, payload):
    return (status, {"Content-Type": "application/json"}, json.dumps(payload).encode())
