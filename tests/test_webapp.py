from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import closing

from src.webapp import api
from src.webapp.server import create_server


def _get(url: str):
    with closing(urllib.request.urlopen(url, timeout=10)) as resp:
        return resp.status, resp.headers.get('Content-Type', ''), resp.read()


def _post(url: str, payload: dict):
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        url, data=data, headers={'Content-Type': 'application/json'}, method='POST'
    )
    with closing(urllib.request.urlopen(req, timeout=10)) as resp:
        return resp.status, json.loads(resp.read())


class ApiLayerTests(unittest.TestCase):
    def test_overview_has_core_counts(self) -> None:
        ov = api.overview()
        self.assertGreaterEqual(ov['command_count'], 150)
        self.assertGreaterEqual(ov['tool_count'], 100)
        self.assertGreaterEqual(ov['total_python_files'], 20)

    def test_summary_and_manifest_render_markdown(self) -> None:
        self.assertIn('Python Porting Workspace Summary', api.summary()['markdown'])
        self.assertIn('Total Python files', api.manifest()['markdown'])

    def test_route_and_bootstrap(self) -> None:
        routed = api.route('review MCP tool', limit=5)
        self.assertGreaterEqual(routed['count'], 1)
        session = api.bootstrap('review MCP tool', limit=5)
        self.assertIn('Prompt:', session['turn_result']['output'])
        self.assertGreaterEqual(len(session['routed_matches']), 1)

    def test_route_rejects_empty_prompt(self) -> None:
        with self.assertRaises(api.ApiError):
            api.route('   ')

    def test_show_command_and_tool_not_found(self) -> None:
        with self.assertRaises(api.ApiError) as ctx:
            api.show_tool('definitely-not-a-real-tool')
        self.assertEqual(ctx.exception.status, 404)

    def test_exec_command_and_tool(self) -> None:
        self.assertTrue(api.exec_command('review', 'inspect')['handled'])
        self.assertTrue(api.exec_tool('MCPTool', 'fetch')['handled'])
        self.assertFalse(api.exec_command('nope-cmd')['handled'])

    def test_run_mode_validation(self) -> None:
        self.assertEqual(api.run_mode('remote', 'workspace')['mode'], 'remote')
        with self.assertRaises(api.ApiError):
            api.run_mode('bogus-mode', 'workspace')


class WebServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.httpd = create_server('127.0.0.1', 0)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.port}'

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)

    def test_serves_index_html(self) -> None:
        status, ctype, body = _get(self.base + '/')
        self.assertEqual(status, 200)
        self.assertIn('text/html', ctype)
        self.assertIn(b'AiKoding', body)

    def test_serves_static_assets(self) -> None:
        for path, expected in (('/static/app.js', 'javascript'), ('/static/style.css', 'css')):
            status, ctype, body = _get(self.base + path)
            self.assertEqual(status, 200, path)
            self.assertIn(expected, ctype, path)
            self.assertTrue(body)

    def test_api_overview_endpoint(self) -> None:
        status, ctype, body = _get(self.base + '/api/overview')
        self.assertEqual(status, 200)
        self.assertIn('application/json', ctype)
        data = json.loads(body)
        self.assertGreaterEqual(data['command_count'], 150)

    def test_api_commands_with_query(self) -> None:
        status, _, body = _get(self.base + '/api/commands?query=review&limit=3')
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertLessEqual(data['returned'], 3)
        self.assertEqual(data['query'], 'review')

    def test_api_tool_detail_and_404(self) -> None:
        status, _, body = _get(self.base + '/api/tool/MCPTool')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['name'], 'MCPTool')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            _get(self.base + '/api/tool/not-real-xyz')
        self.assertEqual(ctx.exception.code, 404)

    def test_api_route_post(self) -> None:
        status, data = _post(self.base + '/api/route', {'prompt': 'review MCP tool', 'limit': 4})
        self.assertEqual(status, 200)
        self.assertGreaterEqual(data['count'], 1)

    def test_api_bootstrap_post(self) -> None:
        status, data = _post(self.base + '/api/bootstrap', {'prompt': 'review MCP tool'})
        self.assertEqual(status, 200)
        self.assertEqual(data['turn_result']['stop_reason'], 'completed')

    def test_api_turn_loop_post(self) -> None:
        status, data = _post(
            self.base + '/api/turn-loop',
            {'prompt': 'review MCP tool', 'max_turns': 2, 'structured_output': True},
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(data['turns']), 2)

    def test_unknown_route_returns_404(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            _get(self.base + '/api/does-not-exist')
        self.assertEqual(ctx.exception.code, 404)

    def test_path_traversal_is_blocked(self) -> None:
        # The source module must never be reachable through the static route.
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            _get(self.base + '/static/%2e%2e/server.py')
        self.assertIn(ctx.exception.code, (403, 404))


if __name__ == '__main__':
    unittest.main()
