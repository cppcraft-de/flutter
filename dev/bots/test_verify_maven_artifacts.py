import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from verify_maven_artifacts import verify


class Response(io.BytesIO):
    status = 200

    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}


class VerifyMavenTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.maven = self.root / "download.flutter.io/io/flutter/test/1.0.0-hash"
        self.maven.mkdir(parents=True)

    def test_reads_poms_and_heads_jars_without_upload_credentials(self):
        (self.maven / "test.pom").write_bytes(b"pom")
        (self.maven / "test.jar").write_bytes(b"jar")
        def request(req, timeout):
            self.assertEqual(req.headers, {})
            self.assertEqual(timeout, 60)
            self.assertTrue(req.full_url.startswith("https://mirror.invalid/download.flutter.io/"))
            self.assertEqual(req.method, "GET" if req.full_url.endswith(".pom") else "HEAD")
            return Response(b"pom" if req.method == "GET" else b"jar")
        with patch("verify_maven_artifacts.urllib.request.urlopen", side_effect=request) as opened:
            verify(self.root, "https://mirror.invalid")
        self.assertEqual(opened.call_count, 2)

    def test_retries_404_but_not_authentication_failure(self):
        (self.maven / "test.jar").write_bytes(b"jar")
        for code, expected in ((404, 2), (403, 1)):
            with patch("verify_maven_artifacts.urllib.request.urlopen", side_effect=urllib.error.HTTPError("url", code, "error", {}, None)) as opened, patch("verify_maven_artifacts.time.sleep"), self.assertRaises(urllib.error.HTTPError):
                verify(self.root, "https://mirror.invalid", attempts=2)
            self.assertEqual(opened.call_count, expected)

    def test_wrong_pom_is_not_accepted_as_successful_upload(self):
        (self.maven / "test.pom").write_bytes(b"expected")
        with patch("verify_maven_artifacts.urllib.request.urlopen", return_value=Response(b"wrong")), self.assertRaisesRegex(ValueError, "Published POM differs"):
            verify(self.root, "https://mirror.invalid")

    def test_empty_payload_fails(self):
        with self.assertRaises(ValueError):
            verify(self.root, "https://mirror.invalid")


if __name__ == "__main__":
    unittest.main()
