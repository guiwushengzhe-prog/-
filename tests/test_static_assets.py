"""The real entry page must link to assets the HTTP server actually serves."""
from html.parser import HTMLParser
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.parse import urljoin
from urllib.request import urlopen

from piano.server import Handler


class AssetLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "link" and attrs.get("rel") == "stylesheet":
            self.assets.append((attrs["href"], "text/css"))
        if tag == "script" and attrs.get("src"):
            self.assets.append((attrs["src"], "text/javascript"))


class StaticAssetsTests(unittest.TestCase):
    def test_entry_page_assets_load_from_real_server(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}/"
            with urlopen(base, timeout=5) as response:
                parser = AssetLinks()
                parser.feed(response.read().decode("utf-8"))
            self.assertTrue(parser.assets, "The entry page must include its UI assets")
            self.assertEqual({mime for _, mime in parser.assets},
                             {"text/css", "text/javascript"})
            for path, mime in parser.assets:
                with self.subTest(asset=path), urlopen(urljoin(base, path), timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.headers.get_content_type(), mime)
                    self.assertTrue(response.read())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
