from __future__ import annotations

import json
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from campus_alerts.config import AppConfig
from campus_alerts.database import confirm_event, create_event, list_events
from campus_alerts.deepseek import assess_event


CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
}


def make_handler(config: AppConfig) -> type[BaseHTTPRequestHandler]:
    class CampusAlertHandler(BaseHTTPRequestHandler):
        server_version = "CampusAlertHTTP/1.0"

        def do_OPTIONS(self) -> None:
            self.send_response(HTTPStatus.NO_CONTENT)
            self._send_common_headers()
            self.end_headers()

        def do_GET(self) -> None:
            parsed_url = urlparse(self.path)
            if parsed_url.path.startswith("/api/"):
                self._handle_api_get(parsed_url.path, parsed_url.query)
                return

            self._serve_static(parsed_url.path)

        def do_POST(self) -> None:
            parsed_url = urlparse(self.path)
            if parsed_url.path == "/api/events":
                self._create_event()
                return

            if parsed_url.path.startswith("/api/events/") and parsed_url.path.endswith("/confirm"):
                self._confirm_event(parsed_url.path)
                return

            self._send_json(HTTPStatus.NOT_FOUND, {"error": "接口不存在。"})

        def log_message(self, format: str, *args: Any) -> None:
            print(f"{self.address_string()} - {format % args}")

        def _handle_api_get(self, path: str, query: str) -> None:
            if path == "/api/health":
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "status": "ok",
                        "deepseek_configured": bool(config.deepseek_api_key),
                    },
                )
                return

            if path == "/api/events":
                params = parse_qs(query)
                sort = params.get("sort", ["urgency"])[0]
                events = list_events(config.database_path, sort)
                self._send_json(HTTPStatus.OK, {"events": events})
                return

            self._send_json(HTTPStatus.NOT_FOUND, {"error": "接口不存在。"})

        def _create_event(self) -> None:
            try:
                payload = self._read_json()
            except ValueError as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return

            errors = validate_event_payload(payload)
            if errors:
                self._send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"errors": errors})
                return

            assessment = assess_event(payload, config)
            event = create_event(config.database_path, payload, assessment)
            self._send_json(HTTPStatus.CREATED, {"event": event, "assessment": assessment})

        def _confirm_event(self, path: str) -> None:
            pieces = path.strip("/").split("/")
            if len(pieces) != 4:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "接口不存在。"})
                return

            try:
                event_id = int(pieces[2])
            except ValueError:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "事件 ID 无效。"})
                return

            event = confirm_event(config.database_path, event_id)
            if event is None:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "事件不存在。"})
                return

            self._send_json(HTTPStatus.OK, {"event": event})

        def _read_json(self) -> dict[str, Any]:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0:
                raise ValueError("请求体不能为空。")
            if content_length > 100_000:
                raise ValueError("请求体过大。")

            raw_body = self.rfile.read(content_length).decode("utf-8")
            try:
                payload = json.loads(raw_body)
            except json.JSONDecodeError as exc:
                raise ValueError("请求体不是有效 JSON。") from exc

            if not isinstance(payload, dict):
                raise ValueError("请求体必须是 JSON 对象。")
            return payload

        def _serve_static(self, path: str) -> None:
            route = unquote(path)
            if route in ("", "/"):
                relative_path = "index.html"
            elif route in ("/admin", "/admin/"):
                relative_path = "admin.html"
            else:
                relative_path = route.lstrip("/")

            static_root = config.static_dir.resolve()
            requested_path = (static_root / relative_path).resolve()
            if static_root not in requested_path.parents and requested_path != static_root:
                self._send_json(HTTPStatus.FORBIDDEN, {"error": "禁止访问该路径。"})
                return

            if not requested_path.exists() or not requested_path.is_file():
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "页面不存在。"})
                return

            content_type = CONTENT_TYPES.get(requested_path.suffix, "application/octet-stream")
            body = requested_path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self._send_common_headers()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self._send_common_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_common_headers(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Cache-Control", "no-store")

    return CampusAlertHandler


def validate_event_payload(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required_fields = {
        "type": "事件类型",
        "description": "事件描述",
        "occurred_at": "发生时间",
        "location": "地点",
    }

    for field, label in required_fields.items():
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{label}不能为空。")
        elif field == "description" and len(value.strip()) < 6:
            errors.append("事件描述至少需要 6 个字符。")

    occurred_at = payload.get("occurred_at")
    if isinstance(occurred_at, str) and occurred_at.strip():
        try:
            datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
        except ValueError:
            errors.append("发生时间格式无效。")

    for optional_field in ("reporter_name", "reporter_contact"):
        value = payload.get(optional_field)
        if value is not None and not isinstance(value, str):
            errors.append(f"{optional_field} 必须是文本。")

    return errors


def run_server(config: AppConfig) -> None:
    handler = make_handler(config)
    server = ThreadingHTTPServer((config.host, config.port), handler)
    print(f"校园事件报警系统已启动: http://{config.host}:{config.port}/")
    print(f"管理员界面: http://{config.host}:{config.port}/admin")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("正在关闭服务器...")
    finally:
        server.server_close()

