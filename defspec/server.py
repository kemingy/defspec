from __future__ import annotations

import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from defspec.template import RenderTemplate

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self


class OpenAPIHandler(BaseHTTPRequestHandler):
    spec: bytes

    @classmethod
    def set_openapi_handler(cls, spec: bytes) -> Self:
        cls.spec = spec
        return cls

    def do_GET(self):
        print(self.path)
        if self.path == "/openapi/spec.json":
            return self.send_spec()
        for template in RenderTemplate:
            if self.path == f"/openapi/{template.name.lower()}":
                return self.send_ui(template.value)
        self.send_response(404, "Not Found")
        self.end_headers()

    def send_spec(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(self.spec)

    def send_ui(self, template: str):
        content = template.format(spec_url="/openapi/spec.json")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(content.encode())


def serve_openapi_http_daemon(host: str, port: int, daemon: bool, spec: bytes):
    server = ThreadingHTTPServer((host, port), OpenAPIHandler.set_openapi_handler(spec))
    if daemon:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return
    server.serve_forever()
