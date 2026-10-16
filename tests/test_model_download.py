import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

from piano import download_model


class Response(io.BytesIO):
    def __init__(self, payload, headers=None):
        super().__init__(payload)
        self.headers = {} if headers is None else headers


class InterruptedResponse(Response):
    def read(self, size=-1):
        if self.tell():
            raise OSError("connection interrupted")
        return super().read(4)


class ModelDownloadTests(unittest.TestCase):
    payload = b"synthetic model bytes for integrity testing"

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.target = self.directory / "2.0.pt"
        self.size = patch.object(download_model, "MODEL_BYTES", len(self.payload))
        self.digest = patch.object(download_model, "MODEL_SHA256", hashlib.sha256(self.payload).hexdigest())
        self.size.start()
        self.digest.start()
        self.addCleanup(self.size.stop)
        self.addCleanup(self.digest.stop)

    def assert_old_file_preserved(self):
        self.assertEqual(self.target.read_bytes(), b"previous model")
        self.assertEqual(list(self.directory.iterdir()), [self.target])

    def test_correct_cache_is_verified_without_network(self):
        self.target.write_bytes(self.payload)
        with patch.object(download_model, "_open_download") as request:
            self.assertEqual(download_model.ensure_model(self.target), self.target)
        request.assert_not_called()

    def test_successful_download_replaces_only_after_integrity_check(self):
        self.target.write_bytes(b"previous model")
        response = Response(self.payload, {"Content-Length": str(len(self.payload))})
        with patch.object(download_model, "_open_download", return_value=response):
            result = download_model.ensure_model(self.target)
        self.assertEqual(result.read_bytes(), self.payload)
        self.assertEqual(list(self.directory.iterdir()), [self.target])

    def test_wrong_hash_or_truncation_preserves_existing_model(self):
        for payload in (b"x" * len(self.payload), self.payload[:-1]):
            with self.subTest(payload_length=len(payload)):
                self.target.write_bytes(b"previous model")
                with patch.object(download_model, "_open_download", return_value=Response(payload)):
                    with self.assertRaises(download_model.ModelDownloadError):
                        download_model.ensure_model(self.target)
                self.assert_old_file_preserved()

    def test_declared_and_streamed_size_limits_preserve_existing_model(self):
        self.target.write_bytes(b"previous model")
        response = Response(b"not read", {"Content-Length": str(download_model.MAX_DOWNLOAD_BYTES + 1)})
        with patch.object(response, "read", wraps=response.read) as read, \
                patch.object(download_model, "_open_download", return_value=response):
            with self.assertRaises(download_model.ModelDownloadError):
                download_model.ensure_model(self.target)
            read.assert_not_called()
        self.assert_old_file_preserved()
        with patch.object(download_model, "MAX_DOWNLOAD_BYTES", 8), \
                patch.object(download_model, "_open_download", return_value=Response(self.payload)):
            with self.assertRaises(download_model.ModelDownloadError):
                download_model.ensure_model(self.target)
        self.assert_old_file_preserved()

    def test_network_failure_before_and_during_download_cleans_temporary_files(self):
        self.target.write_bytes(b"previous model")
        with patch.object(download_model, "_open_download", side_effect=URLError("offline")):
            with self.assertRaises(download_model.ModelDownloadError):
                download_model.ensure_model(self.target)
        self.assert_old_file_preserved()
        with patch.object(download_model, "_open_download", return_value=InterruptedResponse(self.payload)):
            with self.assertRaises(download_model.ModelDownloadError):
                download_model.ensure_model(self.target)
        self.assert_old_file_preserved()


if __name__ == "__main__":
    unittest.main()
