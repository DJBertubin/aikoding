"""Zero-dependency HTTP server for the porting-workspace web UI.

Uses only the Python standard library so it runs in any environment without a
pip install step. Serves a single-page UI from ``static/`` and a JSON API
under ``/api/`` that mirrors every ``src.main`` CLI capability.
"""

from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse

from . import api

STATIC_DIR = Path(__file__).resolve().parent / 'static'


def _truthy(value: str | None) -> bool:
    return str(value).lower() in {'1', 'true', 'yes', 'on'}


def _first(params: dict[str, list[str]], key: str, default: str | None = None) -> str | None:
    values = params.get(key)
    return values[0] if values else default


def _int(params: dict[str, list[str]], key: str, default: int) -> int:
    raw = _first(params, key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise api.ApiError(f'Invalid integer for {key!r}: {raw}') from exc


class Handler(BaseHTTPRequestHandler):
    server_version = 'AiKodingWeb/1.0'

    # -- helpers ------------------------------------------------------------

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def _send_error_json(self, message: str, status: int) -> None:
        self._send_json({'error': message, 'status': status}, status=status)

    def _read_body(self) -> dict[str, Any]:
        length = int(self.headers.get('Content-Length') or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            parsed = json.loads(raw.decode('utf-8'))
        except (ValueError, UnicodeDecodeError) as exc:
            raise api.ApiError(f'Invalid JSON body: {exc}') from exc
        if not isinstance(parsed, dict):
            raise api.ApiError('Request body must be a JSON object.')
        return parsed

    def _serve_static(self, path: str) -> None:
        rel = unquote(path).lstrip('/')
        if rel in ('', 'index.html'):
            rel = 'index.html'
        elif rel.startswith('static/'):
            rel = rel[len('static/') :]
        target = (STATIC_DIR / rel).resolve()
        if STATIC_DIR not in target.parents and target != STATIC_DIR:
            self._send_error_json('Forbidden', 403)
            return
        if not target.is_file():
            self._send_error_json('Not found', 404)
            return
        content_type, _ = mimetypes.guess_type(str(target))
        data = target.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', content_type or 'application/octet-stream')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(data)

    # -- routing ------------------------------------------------------------

    def _dispatch(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if not path.startswith('/api/'):
            if self.command in ('GET', 'HEAD'):
                self._serve_static(path)
            else:
                self._send_error_json('Method not allowed', 405)
            return

        try:
            payload = self._route_api(path, params)
        except api.ApiError as exc:
            self._send_error_json(exc.message, exc.status)
        except Exception as exc:  # noqa: BLE001 - surface as 500 to the client
            self._send_error_json(f'{type(exc).__name__}: {exc}', 500)
        else:
            self._send_json(payload)

    def _route_api(self, path: str, params: dict[str, list[str]]) -> Any:
        body: dict[str, Any] = {}
        if self.command == 'POST':
            body = self._read_body()

        # GET endpoints -----------------------------------------------------
        get_routes: dict[str, Callable[[], Any]] = {
            '/api/overview': api.overview,
            '/api/summary': api.summary,
            '/api/manifest': api.manifest,
            '/api/parity-audit': api.parity_audit,
            '/api/setup-report': api.setup_report,
            '/api/command-graph': api.command_graph,
            '/api/bootstrap-graph': api.bootstrap_graph,
            '/api/system-init': api.system_init,
        }
        if self.command in ('GET', 'HEAD') and path in get_routes:
            return get_routes[path]()

        if self.command in ('GET', 'HEAD'):
            if path == '/api/subsystems':
                return api.subsystems(limit=_int(params, 'limit', 32))
            if path == '/api/commands':
                return api.commands(
                    limit=_int(params, 'limit', 20),
                    query=_first(params, 'query'),
                    include_plugin_commands=not _truthy(_first(params, 'no_plugin')),
                    include_skill_commands=not _truthy(_first(params, 'no_skill')),
                )
            if path == '/api/tools':
                return api.tools(
                    limit=_int(params, 'limit', 20),
                    query=_first(params, 'query'),
                    simple_mode=_truthy(_first(params, 'simple_mode')),
                    include_mcp=not _truthy(_first(params, 'no_mcp')),
                    deny_tools=params.get('deny', []),
                    deny_prefixes=params.get('deny_prefix', []),
                )
            if path == '/api/tool-pool':
                return api.tool_pool(
                    simple_mode=_truthy(_first(params, 'simple_mode')),
                    include_mcp=not _truthy(_first(params, 'no_mcp')),
                )
            if path.startswith('/api/command/'):
                return api.show_command(unquote(path[len('/api/command/') :]))
            if path.startswith('/api/tool/'):
                return api.show_tool(unquote(path[len('/api/tool/') :]))
            if path.startswith('/api/session/'):
                return api.get_session(unquote(path[len('/api/session/') :]))
            if path.startswith('/api/mode/'):
                mode = unquote(path[len('/api/mode/') :])
                return api.run_mode(mode, _first(params, 'target', '') or '')

        # POST endpoints ----------------------------------------------------
        if self.command == 'POST':
            if path == '/api/route':
                return api.route(
                    str(body.get('prompt', '')),
                    limit=int(body.get('limit', 5)),
                )
            if path == '/api/bootstrap':
                return api.bootstrap(
                    str(body.get('prompt', '')),
                    limit=int(body.get('limit', 5)),
                )
            if path == '/api/turn-loop':
                return api.turn_loop(
                    str(body.get('prompt', '')),
                    limit=int(body.get('limit', 5)),
                    max_turns=int(body.get('max_turns', 3)),
                    structured_output=bool(body.get('structured_output', False)),
                )
            if path == '/api/exec-command':
                return api.exec_command(
                    str(body.get('name', '')),
                    str(body.get('prompt', '')),
                )
            if path == '/api/exec-tool':
                return api.exec_tool(
                    str(body.get('name', '')),
                    str(body.get('payload', '')),
                )
            if path == '/api/flush-transcript':
                return api.flush_transcript(str(body.get('prompt', '')))

        raise api.ApiError(f'No route for {self.command} {path}', status=404)

    # -- verb entrypoints ---------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 - required name
        self._dispatch()

    def do_HEAD(self) -> None:  # noqa: N802 - required name
        self._dispatch()

    def do_POST(self) -> None:  # noqa: N802 - required name
        self._dispatch()

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: D401
        # Quiet by default; the CLI prints its own startup banner.
        return


def create_server(host: str = '127.0.0.1', port: int = 8000) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), Handler)


def serve(host: str = '127.0.0.1', port: int = 8000) -> int:
    httpd = create_server(host, port)
    bound_host, bound_port = httpd.server_address[:2]
    print(f'AiKoding web UI running at http://{bound_host}:{bound_port}')
    print('Press Ctrl+C to stop.')
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\nShutting down.')
    finally:
        httpd.server_close()
    return 0
