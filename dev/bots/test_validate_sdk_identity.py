"""Regression tests for the SDK identity gate (standard-library unittest)."""

import json
from contextlib import redirect_stdout, redirect_stderr
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from validate_sdk_identity import main, select_release_tag, validate_archive, validate_engine_pin


class SdkIdentityTest(unittest.TestCase):
    revision = "abcdef1234" * 4

    identity = "a" * 40

    def test_pin_mismatch_always_fails(self):
        with self.assertRaisesRegex(ValueError, "content hash"):
            validate_engine_pin("a" * 40, "b" * 40)

    def test_matching_pin_passes(self):
        validate_engine_pin(self.identity, self.identity)

    def test_invalid_engine_ids_fail(self):
        for actual, expected in (("", "a" * 40), ("a" * 40, ""), ("x" * 40, "a" * 40), ("A" * 40, "a" * 40)):
            with self.subTest(actual=actual, expected=expected), self.assertRaises(ValueError):
                validate_engine_pin(actual, expected)

    def run_preflight(self, tags, *options, expected=None):
        command = ["validate_sdk_identity.py", "--revision", self.revision,
                   "--engine-id", self.identity, *options]
        with patch("sys.argv", command), patch(
            "validate_sdk_identity.subprocess.check_output", side_effect=[self.revision, "\n".join(tags)],
        ), patch("validate_sdk_identity.head_content_hash", return_value=expected or self.identity), \
                patch("pathlib.Path.read_text", return_value=self.identity), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            main()

    def test_preflight_accepts_matching_hash_with_or_without_release_tag(self):
        for tags in ([], ["wsc-3.44.4-r1"], ["3.44.4"]):
            self.run_preflight(tags)

    def test_preflight_rejects_stale_pin_for_all_builds(self):
        for tags in ([], ["wsc-3.44.4-r1"]):
            with self.subTest(tags=tags), self.assertRaises(SystemExit) as result:
                self.run_preflight(tags, expected="b" * 40)
            self.assertEqual(result.exception.code, 1)

    def test_requested_revision_must_match_checkout_before_reading_pin(self):
        for extra in ([], ["--directory", "unused", "--channel", "stable"]):
            command = ["validate_sdk_identity.py", "--revision", self.revision, *extra]
            errors = io.StringIO()
            with patch("sys.argv", command), patch(
                "validate_sdk_identity.subprocess.check_output", return_value="b" * 40,
            ) as git, patch("validate_sdk_identity.head_content_hash") as content_hash, \
                    patch("pathlib.Path.read_text") as read_pin, \
                    redirect_stderr(errors), self.assertRaises(SystemExit) as result:
                main()
            self.assertEqual(result.exception.code, 1)
            self.assertIn("but --revision requests", errors.getvalue())
            content_hash.assert_not_called()
            read_pin.assert_not_called()
            self.assertEqual(git.call_count, 1)

    def test_preflight_require_tag(self):
        with self.assertRaises(SystemExit) as result:
            self.run_preflight([], "--require-release-tag")
        self.assertEqual(result.exception.code, 1)
        self.run_preflight(["wsc-3.44.4-r1"], "--require-release-tag")

    def check_archive(self, wsc_version, release_tag=None, sdk_channel="stable", stamp_revision=None, **overrides):
        metadata = {
            "frameworkRevision": self.revision,
            "engineRevision": self.revision,
            "engineContentHash": self.identity,
            "frameworkVersion": "3.44.4",
            "flutterVersion": "3.44.4",
            "channel": sdk_channel,
            "wscVersion": wsc_version,
        }
        metadata.update(overrides)
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / f"flutter_windows_{wsc_version}-{sdk_channel}.zip"
            with zipfile.ZipFile(archive, "w") as sdk:
                sdk.writestr("flutter/bin/cache/flutter.version.json", json.dumps(metadata))
                sdk.writestr("flutter/bin/internal/engine.version", self.identity)
                sdk.writestr("flutter/bin/cache/engine.stamp", self.identity)
                sdk.writestr("flutter/bin/cache/engine_stamp.json", json.dumps({"git_revision": stamp_revision or self.revision, "content_hash": self.identity}))
            validate_archive(archive, self.revision, sdk_channel, release_tag, self.identity)

    def test_same_engine_hash_can_keep_earlier_build_provenance(self):
        self.check_archive("wsc-3.44.4-dev.2-gabcdef1234", stamp_revision="b" * 40,
                           engineRevision="b" * 40)

    def test_archive_rejects_inconsistent_download_pin_or_stamp(self):
        for wrong in ("bin/internal/engine.version", "bin/cache/engine.stamp", "bin/cache/engine_stamp.json"):
            with self.subTest(file=wrong), tempfile.TemporaryDirectory() as directory:
                archive = Path(directory) / "invalid.zip"
                files = {"bin/internal/engine.version": self.identity,
                         "bin/cache/engine.stamp": self.identity,
                         "bin/cache/engine_stamp.json": json.dumps({"git_revision": self.revision, "content_hash": self.identity}),
                         "bin/cache/flutter.version.json": "{}"}
                files[wrong] = (json.dumps({"git_revision": self.revision, "content_hash": "b" * 40})
                                if wrong.endswith(".json") else "b" * 40)
                with zipfile.ZipFile(archive, "w") as sdk:
                    for path, value in files.items():
                        sdk.writestr("flutter/" + path, value)
                with self.assertRaises(ValueError):
                    validate_archive(archive, self.revision, "stable", None, self.identity)

    def test_release_requires_exact_recognized_tag(self):
        self.assertIsNone(select_release_tag(["3.44.4"], False))
        for tags in ([], ["3.44.4"], ["wsc-3.44.4-dev.2-gabcdef1234"]):
            with self.subTest(tags=tags), self.assertRaises(ValueError):
                select_release_tag(tags, True)
        self.assertEqual(select_release_tag(["3.44.4", "wsc-3.44.4-r1"], True), "wsc-3.44.4-r1")

    def test_ambiguous_release_tags_are_rejected(self):
        with self.assertRaises(ValueError):
            select_release_tag(["wsc-3.44.4-r1", "wsc-3.44.4-r2"], False)

    def test_stable_and_beta_release_metadata(self):
        self.check_archive("wsc-3.44.4-r1", "wsc-3.44.4-r1")
        self.check_archive(
            "wsc-3.45.0-0.1.pre-r1", "wsc-3.45.0-0.1.pre-r1", "beta",
            frameworkVersion="3.45.0-0.1.pre", flutterVersion="3.45.0-0.1.pre",
        )

    def test_staging_allows_upstream_framework_fallback(self):
        for base in ("3.45.0-0.1.pre", "3.45.0-0.1.pre-r1"):
            with self.subTest(base=base):
                self.check_archive(
                    f"wsc-{base}-dev.2-gabcdef1234", sdk_channel="beta",
                    frameworkVersion="3.46.0-1.0.pre-6", flutterVersion="3.46.0-1.0.pre-6",
                )

    def test_release_rejects_stale_metadata(self):
        for field, value in {
            "frameworkRevision": "0" * 40,
            "engineRevision": "0" * 40,
            "engineContentHash": "0" * 40,
            "frameworkVersion": "3.46.0-1.0.pre-6",
            "flutterVersion": "3.46.0-1.0.pre-6",
            "channel": "beta",
            "wscVersion": "wsc-3.44.4-dev.2-gabcdef1234",
        }.items():
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.check_archive("wsc-3.44.4-r1", "wsc-3.44.4-r1", **{field: value})

    def test_untagged_source_cannot_claim_release_identity(self):
        with self.assertRaises(ValueError):
            self.check_archive("wsc-3.44.4-r1")

    def test_development_hash_must_match_source(self):
        with self.assertRaises(ValueError):
            self.check_archive("wsc-3.44.4-dev.2-g0000000000")

    def test_filename_must_match_metadata(self):
        with self.assertRaises(ValueError):
            self.check_archive(
                "wsc-3.44.4-dev.2-gabcdef1234", "wsc-3.44.4-r1",
                wscVersion="wsc-3.44.4-r1",
            )


if __name__ == "__main__":
    unittest.main()
