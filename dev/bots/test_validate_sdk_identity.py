"""Regression tests for the SDK identity gate (standard-library unittest)."""

import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from validate_sdk_identity import select_release_tag, validate_archive


class SdkIdentityTest(unittest.TestCase):
    revision = "abcdef1234" * 4

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
