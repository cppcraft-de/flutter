"""Offline HTTP integration tests for artifact uploads and mirror seeding."""

import base64
from contextlib import redirect_stdout
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error

import seed_artifact_mirror as seed
import upload_artifact_tree as upload
from validate_sdk_identity import write_checksum


class PublishingTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.requests = []
        self.objects = {}
        self.statuses = {}
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_HEAD(self):
                owner.requests.append(("HEAD", self.path, dict(self.headers), b""))
                status = owner.statuses.get(self.path, 200 if self.path in owner.objects else 404)
                self.send_response(status)
                self.end_headers()

            def do_GET(self):
                owner.requests.append(("GET", self.path, dict(self.headers), b""))
                if self.path.startswith("/origin/"):
                    status = owner.statuses.get(self.path, 200 if self.path in owner.objects else 404)
                    data = owner.objects.get(self.path, b"")
                    self.send_response(status)
                    if status == 307:
                        self.send_header("Location", owner.url + "/redirect-destination")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                data = owner.objects.get(self.path, b"fixture contents")
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                md5 = hashlib.md5(data, usedforsecurity=False).digest()
                if self.path in ("/bad-checksum", "/bad-split-checksum"):
                    md5 = b"wrong"
                md5_header = "md5=" + base64.b64encode(md5).decode()
                if self.path in ("/split-checksum", "/bad-split-checksum"):
                    self.send_header("x-goog-hash", "crc32c=unused")
                    self.send_header("x-goog-hash", md5_header)
                elif self.path == "/split-md5-first":
                    self.send_header("x-goog-hash", md5_header)
                    self.send_header("x-goog-hash", "crc32c=unused")
                elif self.path == "/missing-md5":
                    self.send_header("x-goog-hash", "crc32c=unused")
                elif self.path != "/missing-hashes":
                    self.send_header("x-goog-hash", "crc32c=unused," + md5_header)
                self.end_headers()
                self.wfile.write(data)

            def do_PUT(self):
                data = self.rfile.read(int(self.headers["Content-Length"]))
                owner.requests.append(("PUT", self.path, dict(self.headers), data))
                if self.path == "/redirect":
                    self.send_response(307)
                    self.send_header("Location", owner.url + "/redirect-destination")
                elif self.path == "/retry" and len(owner.requests) == 1:
                    self.send_response(503)
                else:
                    owner.objects[self.path] = data
                    self.send_response(201)
                self.end_headers()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.environment = patch.dict(os.environ, {"HTTP_UPLOAD_KEY": "dummy-test-key"}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def payload(self):
        path = self.root / "archive.zip"
        path.write_bytes(b"payload" * 1000)
        return path

    def test_upload_sends_access_key_and_complete_body(self):
        path = self.payload()
        upload.upload_file(path, self.url + "/upload")
        method, _, headers, body = self.requests[0]
        self.assertEqual(method, "PUT")
        self.assertEqual(headers["Accesskey"], "dummy-test-key")
        self.assertNotIn("Authorization", headers)
        self.assertEqual(body, path.read_bytes())

    def test_retry_reopens_file(self):
        path = self.payload()
        with patch.object(upload.time, "sleep"):
            upload.upload_file(path, self.url + "/retry")
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.requests[0][3], self.requests[1][3])

    def test_redirect_never_forwards_credentials(self):
        with self.assertRaises(RuntimeError):
            upload.upload_file(self.payload(), self.url + "/redirect", attempts=1)
        self.assertEqual([request[1] for request in self.requests], ["/redirect"])

    def test_empty_key_and_invalid_attempt_count_fail_before_request(self):
        with patch.dict(os.environ, {"HTTP_UPLOAD_KEY": ""}), self.assertRaises(ValueError):
            upload.upload_file(self.payload(), self.url)
        with self.assertRaises(ValueError):
            upload.upload_file(self.payload(), self.url, attempts=0)
        self.assertEqual(self.requests, [])

    def test_head_is_anonymous_and_only_404_means_missing(self):
        self.assertFalse(seed.exists(self.url + "/missing"))
        self.objects["/present"] = b"x"
        self.assertTrue(seed.exists(self.url + "/present"))
        for status in (401, 403, 405, 500):
            self.statuses["/error"] = status
            with self.assertRaises(urllib.error.HTTPError):
                seed.exists(self.url + "/error")
        for _, _, headers, _ in self.requests:
            self.assertNotIn("Accesskey", headers)
            self.assertNotIn("Authorization", headers)

    def test_download_verifies_checksum_and_is_anonymous(self):
        destination = self.root / "seed.zip"
        with patch.object(seed, "UPSTREAM", self.url), redirect_stdout(io.StringIO()):
            seed.download("good", destination)
            self.assertEqual(destination.read_bytes(), b"fixture contents")
            with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                seed.download("bad-checksum", self.root / "bad.zip")
        self.assertFalse((self.root / "bad.zip").exists())
        self.assertFalse((self.root / "bad.zip.partial").exists())
        for _, _, headers, _ in self.requests:
            self.assertNotIn("Accesskey", headers)

    def test_download_accepts_split_checksum_headers_in_either_order(self):
        with patch.object(seed, "UPSTREAM", self.url), redirect_stdout(io.StringIO()):
            for relative in ("split-checksum", "split-md5-first"):
                with self.subTest(relative=relative):
                    destination = self.root / relative
                    seed.download(relative, destination)
                    self.assertEqual(destination.read_bytes(), b"fixture contents")
                    self.assertFalse(destination.with_name(relative + ".partial").exists())

    def test_download_rejects_bad_checksum_in_second_header(self):
        destination = self.root / "bad.zip"
        with patch.object(seed, "UPSTREAM", self.url), self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
            seed.download("bad-split-checksum", destination)
        self.assertFalse(destination.exists())
        self.assertFalse((self.root / "bad.zip.partial").exists())

    def test_download_still_requires_md5(self):
        with patch.object(seed, "UPSTREAM", self.url):
            for relative in ("missing-md5", "missing-hashes"):
                with self.subTest(relative=relative), self.assertRaisesRegex(RuntimeError, "no MD5"):
                    seed.download(relative, self.root / relative)
                self.assertFalse((self.root / relative).exists())
                self.assertFalse((self.root / (relative + ".partial")).exists())

    def test_only_missing_seeds_are_staged_then_verified(self):
        self.objects["/origin/already-present"] = b"keep"
        self.objects["/already-present"] = b"keep"
        output = self.root / "seeds"
        with patch.object(seed, "seed_paths", return_value=["already-present", "missing"]), \
                patch.object(seed, "UPSTREAM", self.url), redirect_stdout(io.StringIO()):
            seed.prepare(self.root, {"windows"}, self.url, output,
                         upload_base_url=self.url + "/origin")
            self.assertFalse((output / "already-present").exists())
            upload.upload_file(output / "missing", self.url + "/missing")
            seed.prepare(self.root, {"windows"}, self.url, output, verify_only=True)
        self.assertEqual(self.objects["/already-present"], b"keep")
        self.assertEqual([r[1] for r in self.requests if r[0] == "GET"],
                         ["/origin/already-present", "/origin/missing", "/missing"])
        for method, path, headers, body in self.requests:
            if path.startswith("/origin/"):
                self.assertEqual(headers["Accesskey"], "dummy-test-key")
            elif method != "PUT":
                self.assertNotIn("Accesskey", headers)

    def test_stale_cdn_404_preserves_existing_origin_seeds_including_empty_files(self):
        self.objects["/origin/coverage"] = b"original snapshot"
        self.objects["/origin/empty"] = b""
        with patch.object(seed, "seed_paths", return_value=["coverage", "empty"]), \
                patch.object(seed, "UPSTREAM", self.url), redirect_stdout(io.StringIO()):
            seed.prepare(self.root, {"windows"}, self.url, self.root / "seeds",
                         upload_base_url=self.url + "/origin")
        self.assertEqual(list((self.root / "seeds").iterdir()), [])
        self.assertEqual([(r[0], r[1]) for r in self.requests],
                         [("GET", "/origin/coverage"), ("GET", "/origin/empty")])

    def test_origin_errors_and_redirects_never_stage_or_forward_credentials(self):
        with patch.object(seed, "seed_paths", return_value=["seed"]):
            for status in (401, 403, 500, 307):
                with self.subTest(status=status):
                    self.requests.clear()
                    self.statuses["/origin/seed"] = status
                    with self.assertRaises(urllib.error.HTTPError):
                        seed.prepare(self.root, {"windows"}, self.url, self.root / "seeds",
                                     upload_base_url=self.url + "/origin")
                    self.assertEqual([(r[0], r[1]) for r in self.requests], [("GET", "/origin/seed")])
                    self.assertEqual(list((self.root / "seeds").iterdir()), [])

    def test_later_seed_run_preserves_first_upload_despite_stale_cdn(self):
        with patch.object(seed, "seed_paths", return_value=["seed"]), \
                patch.object(seed, "UPSTREAM", self.url), redirect_stdout(io.StringIO()):
            first = self.root / "first"
            seed.prepare(self.root, {"windows"}, self.url, first,
                         upload_base_url=self.url + "/origin")
            upload.upload_file(first / "seed", self.url + "/origin/seed")
            self.objects["/seed"] = b"changed upstream"
            self.statuses["/seed"] = 404
            seed.prepare(self.root, {"windows"}, self.url, self.root / "second",
                         upload_base_url=self.url + "/origin")
        self.assertEqual(list((self.root / "second").iterdir()), [])
        self.assertEqual(self.objects["/origin/seed"], b"fixture contents")
        self.assertEqual(len([r for r in self.requests if r[0] == "PUT"]), 1)

    def test_staging_requires_origin_before_any_request(self):
        with self.assertRaisesRegex(ValueError, "--upload-base-url"):
            seed.prepare(self.root, {"windows"}, self.url, self.root / "seeds")
        self.assertEqual(self.requests, [])

    def test_verification_waits_but_does_not_download_or_upload(self):
        with patch.object(seed, "seed_paths", return_value=["absent"]), \
                patch.object(seed.time, "sleep"), self.assertRaises(RuntimeError):
            seed.prepare(self.root, {"windows"}, self.url, self.root, verify_only=True)
        self.assertEqual(len(self.requests), 6)
        self.assertTrue(all(r[0] == "HEAD" for r in self.requests))

    def test_current_pins_select_only_upstream_inputs(self):
        checkout = Path(__file__).resolve().parents[2]
        windows = seed.seed_paths(checkout, {"windows"})
        macos = seed.seed_paths(checkout, {"windows", "macos"})
        self.assertEqual(len(windows), 3)
        self.assertEqual(len(macos), 9)
        self.assertTrue(set(windows) < set(macos))
        # Catch changes to upstream's tool inventory during the next rebase.
        source = (checkout / "packages/flutter_tools/lib/src/flutter_cache.dart").read_text()
        inventory = source.split("static const artifactNames = <String>[")[1].split("];", 1)[0]
        self.assertEqual(set(seed.re.findall(r"'([^']+)'", inventory)), set(seed.IOS_TOOLS))

    def test_checksum_sidecar(self):
        path = self.payload()
        write_checksum(path)
        self.assertEqual(
            path.with_name(path.name + ".sha256").read_text(),
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n",
        )


if __name__ == "__main__":
    unittest.main()
