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

    def test_tagged_pin_mismatch_fails_even_without_full_publication(self):
        for tag in ("wsc-3.44.4-r1", "wsc-3.45.0-0.1.pre-r1"):
            for full_publication in (False, True):
                with self.subTest(tag=tag, full_publication=full_publication):
                    with self.assertRaisesRegex(ValueError, "matching engine ID"):
                        validate_engine_pin("a" * 40, "b" * 40, tag, full_publication)

    def test_untagged_full_publication_still_rejects_mismatch(self):
        with self.assertRaises(ValueError):
            validate_engine_pin("a" * 40, "b" * 40, None, True)

    def test_untagged_testing_warns_on_mismatch(self):
        output = io.StringIO()
        with redirect_stdout(output):
            validate_engine_pin("a" * 40, "b" * 40, None, False)
        self.assertIn("WARNING:", output.getvalue())

    def test_matching_pins_pass_all_policies(self):
        for tag in (None, "wsc-3.44.4-r1", "wsc-3.45.0-0.1.pre-r1"):
            for full_publication in (False, True):
                with self.subTest(tag=tag, full_publication=full_publication):
                    validate_engine_pin("A" * 40, "a" * 40, tag, full_publication)

    def test_invalid_engine_ids_fail_even_for_untagged_testing(self):
        for actual, expected in (("", "a" * 40), ("a" * 40, ""), ("x" * 40, "a" * 40)):
            with self.subTest(actual=actual, expected=expected), self.assertRaises(ValueError):
                validate_engine_pin(actual, expected, None, False)

    def run_preflight(self, tags, *options):
        command = [
            "validate_sdk_identity.py", "--revision", self.revision,
            "--engine-id", "a" * 40, "--expected-engine-id", "b" * 40, *options,
        ]
        with patch("sys.argv", command), patch(
            "validate_sdk_identity.subprocess.check_output", return_value="\n".join(tags),
        ), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            main()

    def test_preflight_auto_detects_exact_tags_without_require_tag_or_sdk_directory(self):
        for tags in (["wsc-3.44.4-r1"], ["wsc-3.45.0-0.1.pre-r1"]):
            with self.subTest(tags=tags), self.assertRaises(SystemExit) as result:
                self.run_preflight(tags)
            self.assertEqual(result.exception.code, 1)
        # Plain upstream tags and unrelated tags are not WSC releases.
        self.run_preflight(["3.44.4", "candidate", "wsc-3.44.4"])
        self.run_preflight([])

    def test_preflight_require_tag_and_full_publication_fail_closed(self):
        cases = [
            ([], "--require-release-tag"),
            (["wsc-3.44.4-r1"], "--require-release-tag"),
            ([], "--full-rebuild-publication"),
        ]
        for tags, flag in cases:
            with self.subTest(tags=tags, flag=flag), self.assertRaises(SystemExit) as result:
                self.run_preflight(tags, flag)
            self.assertEqual(result.exception.code, 1)

    def test_preflight_rejects_incomplete_engine_options(self):
        for options in (["--engine-id", "a" * 40], ["--expected-engine-id", "a" * 40], ["--full-rebuild-publication"]):
            with patch("sys.argv", ["validate_sdk_identity.py", "--revision", self.revision, *options]), \
                    redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as result:
                main()
            self.assertEqual(result.exception.code, 2)

    def check_archive(self, wsc_version, release_tag=None, sdk_channel="stable", **overrides):
        metadata = {
            "frameworkRevision": self.revision,
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
            validate_archive(archive, self.revision, sdk_channel, release_tag)

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
