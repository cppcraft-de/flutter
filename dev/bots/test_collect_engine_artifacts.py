"""Publish upstream-generated hash variants without modifying their contents."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import collect_engine_artifacts as collector


class CollectorTest(unittest.TestCase):
    revision = "a" * 40
    identity = "b" * 40

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "maven"
        self.output = self.root / "output"
        self.build = {"name": "ci/android_debug", "gn": ["--android-cpu=arm64"], "ninja": {
            "targets": ["flutter/shell/platform/android:abi_jars", "flutter/shell/platform/android:embedding_jars"]}}

    def files(self, artifact, directory=None, version=None):
        version = version or self.identity
        directory = directory or self.revision
        root = self.source / "io/flutter" / artifact / f"1.0.0-{directory}"
        root.mkdir(parents=True, exist_ok=True)
        stem = f"{artifact}-1.0.0-{version}"
        pom = root / (stem + ".pom")
        pom.write_text(f'''<project xmlns="http://maven.apache.org/POM/4.0.0"><groupId>io.flutter</groupId><artifactId>{artifact}</artifactId><version>1.0.0-{version}</version><dependencies><dependency><groupId>example</groupId><artifactId>untouched</artifactId><version>2.3</version></dependency></dependencies></project>''')
        (root / (stem + ".jar")).write_bytes(b"original jar")
        if artifact.startswith("flutter_embedding_"):
            (root / (stem + "-sources.jar")).write_bytes(b"original sources")
        return pom

    def collect(self):
        collector._copy_maven(self.source, self.output, self.build, self.revision, self.identity)

    def test_moves_only_current_hash_variants_and_preserves_bytes(self):
        originals = {}
        for artifact in ("arm64_v8a_debug", "flutter_embedding_debug"):
            originals[artifact] = self.files(artifact).read_bytes()
            self.files(artifact, version=self.revision)  # legacy SHA variant
            self.files(artifact, directory="c" * 40)  # stale incremental output
        self.collect()
        files = list(self.output.rglob("*.*"))
        self.assertEqual(len([p for p in files if p.is_file()]), 5)
        for artifact, original in originals.items():
            pom = self.output / "download.flutter.io/io/flutter" / artifact / f"1.0.0-{self.identity}" / f"{artifact}-1.0.0-{self.identity}.pom"
            self.assertEqual(pom.read_bytes(), original)
            self.assertEqual(pom.with_suffix(".jar").read_bytes(), b"original jar")
        self.collect()  # identical entries from multiple collections are harmless

    def test_missing_current_variant_does_not_fall_back_to_old_directory(self):
        for artifact in ("arm64_v8a_debug", "flutter_embedding_debug"):
            self.files(artifact, directory="c" * 40)
        with self.assertRaises(FileNotFoundError):
            self.collect()

    def test_incorrect_pom_version_is_rejected(self):
        pom = self.files("arm64_v8a_debug")
        pom.write_text(pom.read_text().replace(f"<version>1.0.0-{self.identity}", f"<version>1.0.0-{self.revision}"))
        with self.assertRaisesRegex(ValueError, "invalid version"):
            self.collect()

    def test_missing_jar_fails(self):
        pom = self.files("arm64_v8a_debug")
        pom.with_suffix(".jar").unlink()
        with self.assertRaises(FileNotFoundError):
            self.collect()

    def test_different_payload_cannot_replace_collected_file(self):
        pom = self.files("arm64_v8a_debug")
        self.files("flutter_embedding_debug")
        self.collect()
        pom.with_suffix(".jar").write_bytes(b"different jar")
        with self.assertRaisesRegex(RuntimeError, "Conflicting artifact"):
            self.collect()

    def test_all_supported_modes_and_abis(self):
        self.build["ninja"]["targets"] = ["flutter/shell/platform/android:abi_jars"]
        for cpu, artifact in (("arm", "armeabi_v7a"), ("arm64", "arm64_v8a"), ("x64", "x86_64"), ("x86", "x86")):
            for mode in ("debug", "profile", "release"):
                self.build["gn"] = ["--android-cpu", cpu, "--runtime-mode", mode]
                self.files(f"{artifact}_{mode}")
                self.collect()

    def test_main_validates_gn_and_uses_manifest_config_not_build_name(self):
        src = self.root / "engine/src"
        config = src / "flutter/ci/builders/test.json"
        config.parent.mkdir(parents=True)
        build_dir = src / "out/wasm_release"
        archives = build_dir / "zip_archives"
        archives.mkdir(parents=True)
        (archives / "flutter-web-sdk.zip").write_bytes(b"web")
        (build_dir / "args.gn").write_text(f'engine_version = "{self.revision}"\ncontent_hash = "{self.identity}"\n')
        config.write_text(json.dumps({"builds": [{"name": "ci/wasm_release", "ninja": {"config": "wasm_release"}, "archives": [{"base_path": "out/wasm_release/zip_archives", "include_paths": ["out/wasm_release/zip_archives/flutter-web-sdk.zip"]}]}]}))
        command = ["collect", "--engine-src", str(src), "--engine-id", self.identity, "--output", str(self.output), "--builder", "test", "--build", "ci/wasm_release"]
        with patch("sys.argv", command), patch.object(collector, "head_content_hash", return_value=self.identity), patch.object(collector.subprocess, "check_output", return_value=self.revision):
            collector.main()
            self.assertEqual((self.output / f"flutter_infra_release/flutter/{self.identity}/flutter-web-sdk.zip").read_bytes(), b"web")
            (build_dir / "args.gn").write_text('content_hash = "' + "c" * 40 + '"\n')
            with self.assertRaises(ValueError):
                collector.main()


if __name__ == "__main__":
    unittest.main()
