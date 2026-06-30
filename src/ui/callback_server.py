"""HTTP callback server to receive notification button clicks and route them back to the agent."""

import threading
import queue
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs


class ReplyHTTPServer:
    """Lightweight HTTP server that listens for notification button clicks.

    When a user clicks a quick-reply button on a Windows toast notification,
    winotify launches the callback URL. This server catches those clicks
    and pushes them onto the agent's event queue as user input.
    """

    def __init__(self, port: int, event_queue: queue.Queue):
        self._port = port
        self._queue = event_queue
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self):
        """Start the HTTP server in a background thread."""
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path == "/reply":
                    params = parse_qs(parsed.query)
                    msg = params.get("msg", [""])[0]
                    if msg:
                        outer._queue.put(("user", f"[notification-reply] {msg}"))
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(
                        b"<html><body><h2>Reply sent to Chanel Agent.</h2>"
                        b"<p>You can close this window.</p></body></html>"
                    )
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, format, *args):
                pass

        self._server = HTTPServer(("127.0.0.1", self._port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the HTTP server."""
        if self._server:
            self._server.shutdown()
            self._server = None