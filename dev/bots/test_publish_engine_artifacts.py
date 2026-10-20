"""Offline publication protocol tests: separate origin/CDN views, no real uploads."""

from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import ssl
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

import publish_engine_artifacts as publish


class DownloadRetryTest(unittest.TestCase):
    url = "https://downloads.example/runtime.zip"
    expected = {"size": 3, "sha256": publish.hashlib.sha256(b"zip").hexdigest()}

    def response(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.headers = {"Content-Length": "3"}
        response.read.side_effect = [b"zip", b""]
        return response

    def verify(self, full=False):
        publish.verify_download("https://downloads.example", "runtime.zip", self.expected, full=full)

    def test_transient_failures_retry_then_succeed(self):
        errors = [
            urllib.error.URLError(ConnectionResetError(54, "Connection reset by peer")),
            ConnectionResetError("reset"),
            TimeoutError("timed out"),
            *[urllib.error.HTTPError(self.url, status, "temporary", {}, None)
              for status in (404, 408, 429, 500, 502, 503, 504)],
        ]
        for error in errors:
            with self.subTest(error=error), redirect_stdout(io.StringIO()) as log, \
                    patch.object(publish.urllib.request, "urlopen",
                                 side_effect=[error, self.response()]) as open_url, \
                    patch.object(publish.time, "sleep") as sleep:
                self.verify()
                self.assertEqual(open_url.call_count, 2)
                sleep.assert_called_once_with(5)
                self.assertIn(self.url, log.getvalue())
                self.assertIn("retrying", log.getvalue())

    def test_retry_budget_is_bounded(self):
        with redirect_stdout(io.StringIO()), \
                patch.object(publish.urllib.request, "urlopen",
                             side_effect=TimeoutError("timed out")) as open_url, \
                patch.object(publish.time, "sleep") as sleep:
            with self.assertRaises(TimeoutError):
                self.verify()
            self.assertEqual(open_url.call_count, 6)
            self.assertEqual(sleep.call_count, 5)

    def test_interrupted_get_restarts_hash_and_closes_response(self):
        for error in (ConnectionResetError("reset"), TimeoutError("timed out"),
                      publish.IncompleteRead(b"i", 1)):
            interrupted = self.response()
            interrupted.read.side_effect = [b"z", error]
            with self.subTest(error=error), redirect_stdout(io.StringIO()), \
                    patch.object(publish.urllib.request, "urlopen",
                                 side_effect=[interrupted, self.response()]) as open_url, \
                    patch.object(publish.time, "sleep"):
                self.verify(full=True)
                self.assertEqual(open_url.call_count, 2)
                interrupted.__exit__.assert_called_once()

    def test_permanent_errors_fail_without_retry(self):
        errors = [
            urllib.error.HTTPError(self.url, status, "permanent", {}, None)
            for status in (400, 401, 403)
        ] + [urllib.error.URLError(ssl.SSLCertVerificationError("bad certificate"))]
        for error in errors:
            with self.subTest(error=error), redirect_stdout(io.StringIO()), \
                    patch.object(publish.urllib.request, "urlopen", side_effect=error) as open_url, \
                    patch.object(publish.time, "sleep") as sleep:
                with self.assertRaises(type(error)):
                    self.verify()
                open_url.assert_called_once()
                sleep.assert_not_called()

    def test_integrity_mismatches_fail_without_retry(self):
        for size, content in (("4", b"zip"), ("3", b"bad")):
            response = self.response()
            response.headers["Content-Length"] = size
            response.read.side_effect = [content, b""]
            with self.subTest(size=size, content=content), redirect_stdout(io.StringIO()), \
                    patch.object(publish.urllib.request, "urlopen", return_value=response) as open_url, \
                    patch.object(publish.time, "sleep") as sleep:
                with self.assertRaisesRegex(ValueError, "differs"):
                    self.verify(full=True)
                open_url.assert_called_once()
                sleep.assert_not_called()


class PublicationTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.engine = "a" * 40
        self.prefix = f"flutter_infra_release/flutter/{self.engine}/"
        self.receipt_path = f"wsc-publications/{self.engine}.json"
        self.objects = {}
        self.stale = {}
        self.requests = []
        self.fail_put = None
        self.origin_status = None
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def read_object(self, head=False):
                owner.requests.append((self.command, self.path, dict(self.headers), None))
                _, endpoint, relative = self.path.split("/", 2)
                if endpoint == "origin" and owner.origin_status:
                    self.send_response(owner.origin_status)
                    if owner.origin_status == 307:
                        self.send_header("Location", owner.url + "/cdn/redirect-target")
                    self.end_headers()
                    return
                data = owner.objects.get(relative)
                if endpoint == "cdn":
                    data = owner.stale.get(relative, data)
                self.send_response(404 if data is None else 200)
                self.send_header("Content-Length", str(len(data or b"")))
                self.send_header("CDN-Cache", "HIT" if relative in owner.stale else "MISS")
                self.end_headers()
                if not head and data is not None:
                    self.wfile.write(data)

            def do_HEAD(self):
                self.read_object(head=True)

            def do_GET(self):
                self.read_object()

            def do_PUT(self):
                data = self.rfile.read(int(self.headers["Content-Length"]))
                owner.requests.append(("PUT", self.path, dict(self.headers), data))
                relative = self.path.removeprefix("/origin/")
                if relative == owner.fail_put:
                    self.send_response(500)
                else:
                    owner.objects[relative] = data
                    self.send_response(201)
                self.end_headers()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()

        def close():
            self.server.shutdown()
            self.server.server_close()
            thread.join()

        self.addCleanup(close)
        environment = patch.dict(os.environ, {"HTTP_UPLOAD_KEY": "private-test-key"}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def stage(self, name="runtime.zip", data=b"first engine", root=None):
        relative = self.prefix + name
        path = (root or self.root) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return relative

    def run_publish(self, overwrite=False, root=None):
        with redirect_stdout(io.StringIO()), patch.object(publish.time, "sleep"):
            publish.publish(root or self.root, self.url + "/origin", self.url + "/cdn", self.engine, overwrite)

    def puts(self):
        return [request for request in self.requests if request[0] == "PUT"]

    def receipt(self):
        return json.loads(self.objects[self.receipt_path])

    def test_first_publication_marks_pending_then_verifies_then_completes(self):
        relative = self.stage()
        self.run_publish()
        writes = self.puts()
        self.assertEqual([r[1] for r in writes], [
            "/origin/" + self.receipt_path, "/origin/" + relative, "/origin/" + self.receipt_path])
        self.assertEqual(json.loads(writes[0][3])["pending"], [relative])
        self.assertEqual(self.receipt()["pending"], [])
        self.assertEqual(self.receipt()["files"][relative], publish.file_identity(self.root / relative))
        self.assertIn(("GET", "/cdn/" + relative), [(r[0], r[1]) for r in self.requests])
        for _, path, headers, _ in self.requests:
            if path.startswith("/cdn/"):
                self.assertNotIn("Accesskey", headers)
                self.assertNotIn("Authorization", headers)
            else:
                self.assertEqual(headers["Accesskey"], "private-test-key")

    def test_reuse_ignores_new_local_bytes_and_performs_no_writes(self):
        relative = self.stage()
        self.run_publish()
        self.stage(data=b"new build, different length and metadata")
        self.requests.clear()
        self.run_publish()
        self.assertEqual(self.objects[relative], b"first engine")
        self.assertEqual(self.puts(), [])
        self.assertIn(("HEAD", "/cdn/" + relative), [(r[0], r[1]) for r in self.requests])

    def test_add_target_reuses_shared_files_and_preserves_old_inventory(self):
        shared = self.stage("engine_stamp.json", b'{"content_hash":"same"}')
        windows = self.stage("windows.zip")
        self.run_publish()
        # Keep all test files in the owned temporary directory, outside payload.
        other = self.root / "other-payload"
        self.stage("engine_stamp.json", b'{"content_hash":"same","new_date":true}', other)
        macos = self.stage("macos.zip", b"mac", other)
        self.requests.clear()
        self.run_publish(root=other)
        self.assertEqual(set(self.receipt()["files"]), {shared, windows, macos})
        self.assertNotIn("/origin/" + shared, [r[1] for r in self.puts()])

    def test_legacy_unrecorded_payload_fails_without_writes(self):
        relative = self.stage()
        self.objects[relative] = b"legacy"
        with self.assertRaisesRegex(ValueError, "Unrecorded existing artifact"):
            self.run_publish()
        self.assertEqual(self.puts(), [])

    def test_overwrite_requires_explicit_flag_and_replaces_receipt(self):
        relative = self.stage()
        self.run_publish()
        self.stage(data=b"replacement")
        self.requests.clear()
        self.run_publish(overwrite=True)
        self.assertEqual(json.loads(self.puts()[0][3])["pending"], [relative])
        self.assertEqual(self.objects[relative], b"replacement")
        self.assertEqual(self.receipt()["files"][relative], publish.file_identity(self.root / relative))

    def test_failed_upload_blocks_normal_retry_and_explicit_recovery_finishes(self):
        relative = self.stage()
        self.fail_put = relative
        with self.assertRaises(RuntimeError):
            self.run_publish()
        self.assertEqual(self.receipt()["pending"], [relative])
        self.requests.clear()
        with self.assertRaisesRegex(ValueError, "Incomplete publication"):
            self.run_publish()
        self.assertEqual(self.puts(), [])
        self.fail_put = None
        self.run_publish(overwrite=True)
        self.assertEqual(self.receipt()["pending"], [])

    def test_recovery_cannot_clear_other_targets_pending_paths(self):
        self.stage()
        self.objects[self.receipt_path] = json.dumps({"schema": 1, "engine_id": self.engine,
            "files": {}, "pending": [self.prefix + "another-target.zip"]}).encode()
        with self.assertRaisesRegex(ValueError, "Recovery must include all interrupted paths"):
            self.run_publish(overwrite=True)
        self.assertEqual(self.puts(), [])

    def test_stale_cdn_same_size_fails_hash_check_and_leaves_pending(self):
        relative = self.stage(data=b"new")
        self.stale[relative] = b"old"
        with self.assertRaisesRegex(ValueError, "SHA-256 differs.*CDN-Cache"):
            self.run_publish()
        self.assertEqual(self.receipt()["pending"], [relative])

    def test_missing_reused_object_does_not_silently_republish(self):
        relative = self.stage()
        self.run_publish()
        del self.objects[relative]
        self.requests.clear()
        # A CDN may still serve a removed origin object; do not trust that alone.
        self.stale[relative] = b"first engine"
        with self.assertRaisesRegex(ValueError, "missing at storage origin"):
            self.run_publish()
        self.assertEqual(self.puts(), [])

    def test_pending_receipt_readback_failure_prevents_payload_writes(self):
        self.stage()
        with patch.object(publish, "origin_get", side_effect=[None, None, b"wrong receipt"]):
            with self.assertRaisesRegex(ValueError, "receipt read-back failed"):
                self.run_publish()
        self.assertEqual([r[1] for r in self.puts()], ["/origin/" + self.receipt_path])

    def test_reused_metadata_checks_content_not_just_size(self):
        relative = self.stage("engine_stamp.json", b'{"revision":"a"}')
        self.run_publish()
        self.stale[relative] = b'{"revision":"b"}'
        self.requests.clear()
        with self.assertRaisesRegex(ValueError, "SHA-256 differs"):
            self.run_publish()
        self.assertEqual(self.puts(), [])

    def test_origin_auth_errors_and_redirects_are_not_treated_as_absence(self):
        self.stage()
        for status in (401, 403, 307, 500):
            with self.subTest(status=status):
                self.origin_status = status
                with self.assertRaises(urllib.error.HTTPError):
                    self.run_publish()
        self.assertEqual(self.puts(), [])
        self.assertFalse(any(r[1].startswith("/cdn/") for r in self.requests))

    def test_maven_publication_and_reuse_verify_the_canonical_pom_and_jar(self):
        prefix = f"download.flutter.io/io/flutter/arm64_v8a_debug/1.0.0-{self.engine}/"
        jar = prefix + f"arm64_v8a_debug-1.0.0-{self.engine}.jar"
        pom = jar.removesuffix(".jar") + ".pom"
        for relative, data in ((jar, b"engine jar"), (pom, b"canonical pom")):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.run_publish()
        self.assertEqual(set(self.receipt()["files"]), {jar, pom})
        (self.root / jar).write_bytes(b"different newly compiled engine jar")
        self.requests.clear()
        self.run_publish()
        self.assertEqual(self.puts(), [])
        requests = {(r[0], r[1]) for r in self.requests}
        self.assertIn(("HEAD", "/cdn/" + jar), requests)
        self.assertIn(("GET", "/cdn/" + pom), requests)

    def test_malformed_receipt_fails_even_with_overwrite(self):
        self.stage()
        for receipt in (b"not-json", b"{}", json.dumps({"schema": 1, "engine_id": self.engine,
                "files": {"../escape": {}}, "pending": []}).encode()):
            self.objects[self.receipt_path] = receipt
            with self.assertRaises(ValueError):
                self.run_publish(overwrite=True)
        self.assertEqual(self.puts(), [])

    def test_out_of_scope_payload_fails_before_network(self):
        (self.root / "unexpected.zip").write_bytes(b"wrong scope")
        with self.assertRaisesRegex(ValueError, "outside selected engine ID"):
            self.run_publish(overwrite=True)
        self.assertEqual(self.requests, [])


if __name__ == "__main__":
    unittest.main()
