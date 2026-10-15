"""Offline tests: no SDK builds, downloads, Jenkins calls or rendering sessions."""

import argparse
from contextlib import redirect_stdout
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import frt_ci


class FrtCiTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="wsc-frt-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = Path(__file__).with_name("frt_ci.json")
        self.enabled = {
            "WSC_FRT_ENABLED": "1",
            "WSC_FRT_BASELINE_WINDOWS_URL": "https://example.test/windows.zip",
            "WSC_FRT_BASELINE_WINDOWS_SHA256": "a" * 64,
        }
        self.result = {
            "schema": "font-rendering-tester/regression-result/v1", "status": "passed", "exit_code": 0,
            "baseline_run_id": 1, "specimen_run_id": 2, "total_case_count": 108,
            "passed_case_count": 108, "unavailable_field_count": 0,
            "pass_check_ids": ["line_metrics", "fonts"], "summary": "PASSED: 108/108 cases passed",
            "comparison_summary": {
                "total_field_count": 108, "failed_count": 0,
                "missing_baseline_count": 0, "missing_specimen_count": 0,
            },
        }

    def write_result(self, result=None, root=None):
        root = root or self.root
        frt_ci.write_json(root / "result.json", result or self.result)
        for role in ("baseline", "specimen"):
            bundle = root / f"{role}-client"
            bundle.mkdir(exist_ok=True)
            (bundle / "frt-pubspec.lock").write_text("identical pinned dependencies\n")

    def test_defaults_are_explicitly_disabled_and_master(self):
        plan = frt_ci.load_plan(self.config, ["windows", "macos"], {})
        self.assertFalse(plan["enabled"])
        self.assertEqual(plan["ref"], "master")

    def test_overrides_and_missing_selected_host(self):
        plan = frt_ci.load_plan(self.config, ["windows"], self.enabled)
        self.assertTrue(plan["enabled"])
        self.assertEqual(plan["baselines"]["windows"]["sha256"], "a" * 64)
        with self.assertRaises(ValueError):
            frt_ci.load_plan(self.config, ["windows", "macos"], self.enabled)
        with self.assertRaises(ValueError):
            frt_ci.load_plan(self.config, ["android"], {})

    def test_config_file_alone_can_enable_testing(self):
        plan = frt_ci.load_plan(self.config, ["windows"], self.enabled)
        path = self.root / "config.json"
        frt_ci.write_json(path, plan)
        self.assertTrue(frt_ci.load_plan(path, ["windows"], {})["enabled"])
        self.assertFalse(frt_ci.load_plan(path, ["windows"], {"WSC_FRT_ENABLED": "false"})["enabled"])

    def test_reject_unsafe_url_and_invalid_boolean(self):
        for url in ("https://user:secret@example.test/a", "file:///a", "https://example.test/a?key=secret"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                frt_ci.public_url(url)
        with self.assertRaises(ValueError):
            frt_ci.load_plan(self.config, ["windows"], {"WSC_FRT_ENABLED": "typo"})

    def test_download_verifies_hash(self):
        for expected in (hashlib.sha256(b"zip").hexdigest(), "0" * 64):
            with self.subTest(expected=expected):
                stream = io.BytesIO(b"zip")
                stream.url = "https://example.test/baseline.zip"
                destination = self.root / f"{expected}.zip"
                with patch.object(frt_ci, "urlopen", return_value=stream):
                    if expected.startswith("0"):
                        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                            frt_ci.download_baseline(stream.url, expected, destination)
                    else:
                        frt_ci.download_baseline(stream.url, expected, destination)

    def test_pass_and_mismatch(self):
        self.write_result()
        self.assertEqual(frt_ci.validate_result(self.root, 0)["exit_code"], 0)
        self.result.update(status="failed", exit_code=1, passed_case_count=107)
        self.result["comparison_summary"]["failed_count"] = 1
        self.write_result()
        self.assertEqual(frt_ci.validate_result(self.root, 1)["exit_code"], 1)

    def test_error_missing_report_unexpected_exit_and_dependencies(self):
        with self.assertRaises(FileNotFoundError):
            frt_ci.validate_result(self.root, 0)
        self.write_result()
        with self.assertRaises(ValueError):
            frt_ci.validate_result(self.root, 17)
        (self.root / "specimen-client/frt-pubspec.lock").write_text("different")
        with self.assertRaisesRegex(ValueError, "lockfiles"):
            frt_ci.validate_result(self.root, 0)
        self.result.update(status="error", exit_code=2)
        self.write_result()
        self.assertEqual(frt_ci.validate_result(self.root, 2)["exit_code"], 2)

    def test_incomplete_or_contradictory_comparison_never_passes(self):
        variants = [
            {"unavailable_field_count": 1}, {"pass_check_ids": []},
            {"total_case_count": 0}, {"specimen_run_id": 1}, {"passed_case_count": 107},
            {"status": "failed"}, {"exit_code": 1},
        ]
        for change in variants:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.write_result(dict(self.result, **change))
                frt_ci.validate_result(self.root, 0)
        for key in ("missing_baseline_count", "missing_specimen_count"):
            result = copy.deepcopy(self.result)
            result["comparison_summary"][key] = 1
            self.write_result(result)
            with self.assertRaises(ValueError):
                frt_ci.validate_result(self.root, 0)

    def test_wrapper_uses_two_zips_and_keeps_evidence_not_inputs(self):
        plan = frt_ci.load_plan(self.config, ["windows"], self.enabled)
        plan_path = self.root / "plan.json"
        frt_ci.write_json(plan_path, plan)
        frt = self.root / "source"
        fixture = frt / plan["fixture"]
        fixture.parent.mkdir(parents=True)
        fixture.write_text("{}")
        sdk = self.root / "sdk"
        sdk.mkdir()
        (sdk / "candidate.zip").write_bytes(b"candidate")
        output = self.root / "evidence"
        args = argparse.Namespace(plan=plan_path, host="windows", frt=frt,
                                  revision="b" * 40, output=output, sdk_directory=sdk)

        def fake_run(command, **kwargs):
            if "compare" in command:
                self.assertIn("--locked", command)
                self.assertIn("--dpi", command)
                self.assertNotIn("--interactive-comparison", command)
                self.write_result(root=output / "results")
            return subprocess.CompletedProcess(command, 0)

        with patch.object(frt_ci.subprocess, "check_output", return_value="b" * 40), \
                patch.object(frt_ci.subprocess, "run", side_effect=fake_run), \
                patch.object(frt_ci, "download_baseline"), redirect_stdout(io.StringIO()):
            self.assertEqual(frt_ci.run_comparison(args), 0)
        self.assertTrue((output / "identity.json").is_file())
        self.assertTrue((output / "jenkins-result.json").is_file())
        self.assertFalse(list(self.root.glob("frt-input-*")))
        self.assertEqual((sdk / "candidate.zip").read_bytes(), b"candidate")
        with self.assertRaises(FileExistsError), patch.object(
                frt_ci.subprocess, "check_output", return_value="b" * 40):
            frt_ci.run_comparison(args)

    def test_run_precondition_errors_exit_two_not_mismatch(self):
        command = [
            "frt_ci.py", "run", "--plan", str(self.root / "missing.json"),
            "--host", "windows", "--frt", str(self.root), "--revision", "b" * 40,
            "--sdk-directory", str(self.root), "--output", str(self.root / "evidence"),
        ]
        with patch("sys.argv", command), redirect_stdout(io.StringIO()):
            self.assertEqual(frt_ci.main(), 2)

    def test_evidence_archive_excludes_interrupted_scratch(self):
        source = self.root / "evidence"
        self.write_result(root=source)
        scratch = source / "results/work-interrupted/sdk"
        scratch.mkdir(parents=True)
        (scratch / "huge.zip").write_bytes(b"do not archive")
        archive = self.root / "private/evidence.tar.gz"
        frt_ci.archive_evidence(source, archive)
        with tarfile.open(archive) as contents:
            self.assertIn("evidence/result.json", contents.getnames())
            self.assertFalse(any("work-interrupted" in name for name in contents.getnames()))


if __name__ == "__main__":
    unittest.main()
