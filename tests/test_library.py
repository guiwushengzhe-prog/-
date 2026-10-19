import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.request import urlopen

from piano import server
from piano.music import demo_project


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.runtime = Path(self.temporary.name)
        self.patch = patch.object(server, "RUNTIME", self.runtime)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.addCleanup(self.temporary.cleanup)
        self.project = demo_project()
        self.project["title"] = "已转换练习曲"
        self.project["source"] = {"kind": "audio", "filename": "练习曲.mp3"}

    def save(self, project_id, project, encoding="utf-8"):
        directory = self.runtime / project_id
        directory.mkdir()
        (directory / "project.json").write_text(
            json.dumps(project, ensure_ascii=False), encoding=encoding)

    def test_only_completed_scores_and_old_windows_encoding(self):
        self.save("a" * 32, self.project, "gb18030")
        self.save("b" * 32, self.project)
        self.save("c" * 32, {"notes": [], "groups": []})
        self.save("not-a-conversion", self.project)
        entries = server.library_entries()
        self.assertEqual({entry["id"] for entry in entries}, {"a" * 32, "b" * 32})
        self.assertTrue(all(entry["title"] == self.project["title"] for entry in entries))
        self.assertEqual(server.load_library_project("a" * 32), self.project)
        with self.assertRaises(ValueError):
            server.load_library_project("../outside")

    def test_history_loads_without_in_memory_jobs(self):
        self.save("a" * 32, self.project)
        http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict(server.JOBS, {}, clear=True):
                base = f"http://127.0.0.1:{http.server_port}"
                with urlopen(base + "/api/library", timeout=5) as response:
                    self.assertEqual(json.load(response)["items"][0]["id"], "a" * 32)
                with urlopen(base + "/api/library/" + "a" * 32, timeout=5) as response:
                    self.assertEqual(json.load(response), self.project)
        finally:
            http.shutdown()
            http.server_close()
            thread.join(timeout=5)

    def test_original_audio_remains_available_after_restart(self):
        project_id = "d" * 32
        self.save(project_id, self.project)
        data = b"RIFF-original-upload"
        (self.runtime / project_id / "input.wav").write_bytes(data)
        project = server.load_library_project(project_id)
        self.assertEqual(project["source"]["audio_url"], f"/api/jobs/{project_id}/source-audio")
        http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen(f"http://127.0.0.1:{http.server_port}/api/jobs/{project_id}/source-audio", timeout=5) as response:
                self.assertEqual(response.headers.get_content_type(), "audio/wav")
                self.assertEqual(response.read(), data)
        finally:
            http.shutdown()
            http.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
