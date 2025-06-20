from __future__ import annotations

import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import urljoin

from defspec.template import RenderTemplate

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self


class OpenAPIHandler(BaseHTTPRequestHandler):
    spec: bytes
    path: str = "/openapi/"

    @classmethod
    def build(cls, spec: bytes, path: str = "/openapi") -> type[Self]:
        cls.spec = spec
        cls.path = path
        return cls

    def do_GET(self):
        if self.path == urljoin(self.path, "spec.json"):
            return self.send_spec()
        for template in RenderTemplate:
            if self.path == urljoin(self.path, template.name.lower()):
                return self.send_ui(template.value)
        self.send_response(404, "Not Found")
        self.end_headers()

    def send_spec(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(self.spec)

    def send_ui(self, template: str):
        content = template.format(spec_url=urljoin(self.path, "spec.json"))
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(content.encode())


def serve_openapi_http_daemon(host: str, port: int, daemon: bool, spec: bytes):
    server = ThreadingHTTPServer((host, port), OpenAPIHandler.build(spec))
    if daemon:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return
    server.serve_forever()
