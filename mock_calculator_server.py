"""Mock Calculator REST API Server with OpenAPI 3.0 Spec & Interactive Swagger UI.

Runs a standalone HTTP REST API server on http://localhost:9998:
- GET  /docs (or /) -> Interactive Swagger UI
- GET  /v1/openapi.json -> OpenAPI 3.0 Specification
- GET  /v1/add?a=10&b=20 -> Addition
- GET  /v1/subtract?a=50&b=15 -> Subtraction
- POST /v1/multiply -> Body: {"a": 6, "b": 7}

Run: python mock_calculator_server.py
"""
import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

OPENAPI_SPEC = {
    "openapi": "3.0.0",
    "info": {
        "title": "Mock Calculator REST API",
        "version": "1.0.0",
        "description": "API for basic arithmetic operations"
    },
    "servers": [
        {"url": "http://localhost:9998/v1"}
    ],
    "paths": {
        "/add": {
            "get": {
                "operationId": "add",
                "summary": "Add two numbers",
                "parameters": [
                    {"name": "a", "in": "query", "required": True, "schema": {"type": "number"}},
                    {"name": "b", "in": "query", "required": True, "schema": {"type": "number"}}
                ],
                "responses": {
                    "200": {"description": "Result of addition"}
                }
            }
        },
        "/subtract": {
            "get": {
                "operationId": "subtract",
                "summary": "Subtract b from a",
                "parameters": [
                    {"name": "a", "in": "query", "required": True, "schema": {"type": "number"}},
                    {"name": "b", "in": "query", "required": True, "schema": {"type": "number"}}
                ],
                "responses": {
                    "200": {"description": "Result of subtraction"}
                }
            }
        },
        "/multiply": {
            "post": {
                "operationId": "multiply",
                "summary": "Multiply two numbers",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["a", "b"],
                                "properties": {
                                    "a": {"type": "number"},
                                    "b": {"type": "number"}
                                }
                            }
                        }
                    }
                },
                "responses": {
                    "200": {"description": "Result of multiplication"}
                }
            }
        }
    }
}

SWAGGER_UI_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>Mock Calculator API Docs</title>
    <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css" />
</head>
<body>
    <div id="swagger-ui"></div>
    <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
    <script>
        window.onload = () => {
            window.ui = SwaggerUIBundle({
                url: '/v1/openapi.json',
                dom_id: '#swagger-ui',
            });
        };
    </script>
</body>
</html>
"""


class CalculatorRequestHandler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, data: dict):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status: int, html_text: str):
        body = html_text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path in ("/", "/docs", "/swagger"):
            return self._send_html(200, SWAGGER_UI_HTML)

        if path == "/v1/openapi.json":
            return self._send_json(200, OPENAPI_SPEC)

        if path == "/v1/add":
            try:
                a = float(query.get("a", [0])[0])
                b = float(query.get("b", [0])[0])
                return self._send_json(200, {"operation": "add", "a": a, "b": b, "result": a + b})
            except Exception as exc:
                return self._send_json(400, {"error": str(exc)})

        if path == "/v1/subtract":
            try:
                a = float(query.get("a", [0])[0])
                b = float(query.get("b", [0])[0])
                return self._send_json(200, {"operation": "subtract", "a": a, "b": b, "result": a - b})
            except Exception as exc:
                return self._send_json(400, {"error": str(exc)})

        self._send_json(404, {"error": "Not Found"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/v1/multiply":
            content_length = int(self.headers.get("Content-Length", 0))
            body_bytes = self.rfile.read(content_length)
            try:
                data = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
                a = float(data.get("a", 0))
                b = float(data.get("b", 0))
                return self._send_json(200, {"operation": "multiply", "a": a, "b": b, "result": a * b})
            except Exception as exc:
                return self._send_json(400, {"error": str(exc)})

        self._send_json(404, {"error": "Not Found"})

    def log_message(self, format, *args):
        print(f"[Mock Calculator API] {format % args}")


def run_server(port: int = 9998):
    server_address = ("", port)
    httpd = HTTPServer(server_address, CalculatorRequestHandler)
    print(f"🚀 Mock Calculator REST API Server running on http://localhost:{port}")
    print(f"📖 Interactive Swagger UI: http://localhost:{port}/docs")
    print(f"📄 OpenAPI Spec URL: http://localhost:{port}/v1/openapi.json")
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down Mock Calculator API Server.")


if __name__ == "__main__":
    run_server()
