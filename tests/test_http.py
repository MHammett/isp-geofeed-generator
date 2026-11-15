import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from isp_geofeed_generator.client import GeofeedError, JsonHTTP


class TransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.redirect_target_hits = 0
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                cls.last_post = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                self.do_GET()
            def do_GET(self):
                if self.path == '/redirect':
                    self.send_response(302); self.send_header('Location', '/target'); self.end_headers()
                elif self.path == '/target':
                    cls.redirect_target_hits += 1
                    self.send_response(200); self.end_headers(); self.wfile.write(b'{}')
                elif self.path == '/denied':
                    self.send_response(403); self.end_headers(); self.wfile.write(b'secret response must not be logged')
                elif self.path == '/large':
                    self.send_response(200); self.end_headers(); self.wfile.write(b'x' * 1000)
                elif self.path == '/html':
                    self.send_response(200); self.end_headers(); self.wfile.write(b'<html>error</html>')
                else:
                    self.send_response(200); self.end_headers(); self.wfile.write(json.dumps({'ok': True}).encode())
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True); cls.thread.start()
        cls.url = 'http://127.0.0.1:' + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()

    def test_transport_can_read_actual_json(self):
        self.assertEqual(JsonHTTP().request(self.url + '/ok'), {'ok': True})

    def test_redirect_is_refused_before_credentials_can_be_forwarded(self):
        with self.assertRaisesRegex(GeofeedError, 'HTTP 302'):
            JsonHTTP().request(self.url + '/redirect', headers={'Authorization': 'Bearer example'})
        self.assertEqual(self.redirect_target_hits, 0)

    def test_access_denied_is_not_a_pass_or_secret_leak(self):
        with self.assertRaisesRegex(GeofeedError, 'HTTP 403') as exc:
            JsonHTTP().request(self.url + '/denied')
        self.assertNotIn('secret', str(exc.exception))

    def test_form_post_redirect_is_refused_without_forwarding_credentials(self):
        with self.assertRaisesRegex(GeofeedError, 'HTTP 302'):
            JsonHTTP().request(self.url + '/redirect', form={'apiKey': 'fake-key'}, method='POST')
        self.assertIn(b'apiKey=fake-key', self.last_post)
        self.assertEqual(self.redirect_target_hits, 0)

    def test_bounded_and_json_only_response(self):
        for path in ('/large', '/html'):
            with self.subTest(path=path), self.assertRaises(GeofeedError):
                JsonHTTP(max_bytes=100).request(self.url + path)
