"""Offline tests: no SDK builds, downloads, Jenkins calls or rendering sessions."""

import argparse
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

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

    def test_defaults_enable_windows_macos_web_with_pinned_baselines(self):
        plan = frt_ci.load_plan(self.config, ["windows", "macos"], {})
        self.assertEqual(plan["targets"], ["windows", "web", "macos"])
        self.assertEqual(plan["ref"], "master")
        self.assertTrue(plan["enabled"])
        for host in ("windows", "macos"):
            self.assertIn(f"/19/{host}/", plan["baselines"][host]["url"])
            self.assertRegex(plan["baselines"][host]["sha256"], r"^[0-9a-f]{64}$")
        self.assertFalse(frt_ci.load_plan(self.config, plan["hosts"], {"WSC_FRT_ENABLED": "0"})["enabled"])
        self.assertEqual(frt_ci.load_plan(self.config, [], {})["targets"], [])

    def test_overrides_and_missing_selected_host(self):
        plan = frt_ci.load_plan(self.config, ["windows"], self.enabled)
        self.assertTrue(plan["enabled"])
        self.assertEqual(plan["baselines"]["windows"]["sha256"], "a" * 64)
        missing = {**self.enabled, "WSC_FRT_BASELINE_MACOS_SHA256": "invalid"}
        with self.assertRaises(ValueError):
            frt_ci.load_plan(self.config, ["windows", "macos"], missing)
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

    def test_browser_prefers_edge_and_allows_explicit_override(self):
        edge = self.root / "Microsoft/Edge/Application/msedge.exe"
        chrome = self.root / "Google/Chrome/Application/chrome.exe"
        for browser in (edge, chrome):
            browser.parent.mkdir(parents=True)
            browser.touch()
        self.assertEqual(frt_ci.web_browser({"ProgramFiles": str(self.root)}), edge.resolve())
        self.assertEqual(frt_ci.web_browser({"WSC_FRT_BROWSER": str(chrome)}), chrome.resolve())
        with self.assertRaises(ValueError):
            frt_ci.web_browser({"WSC_FRT_BROWSER": str(self.root / "missing.exe")})
        with self.assertRaises(ValueError):
            frt_ci.web_browser({})

    def test_browser_does_not_silently_substitute_chrome_for_edge(self):
        chrome = self.root / "Google/Chrome/Application/chrome.exe"
        chrome.parent.mkdir(parents=True)
        chrome.touch()
        with self.assertRaisesRegex(ValueError, "needs Edge"):
            frt_ci.web_browser({"ProgramFiles": str(self.root)})

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
            self.assertEqual(command[:3], [sys.executable, "-m", "uv"])
            if "compare" in command:
                gradle = Path(kwargs["env"]["GRADLE_USER_HOME"])
                self.assertTrue(gradle.is_dir())
                self.assertIn("org.gradle.daemon=false", (gradle / "gradle.properties").read_text())
                self.assertIn("-Dorg.gradle.daemon=false", kwargs["env"]["GRADLE_OPTS"])
                (gradle / "downloaded-maven.jar").write_bytes(b"temporary dependency")
                self.assertIn("--locked", command)
                self.assertIn("--dpi", command)
                self.assertEqual(command[command.index("--targets") + 1:command.index("--fixture")],
                                 ["windows", "web"])
                self.assertEqual(command[-2:], ["--browser", str(self.root / "edge.exe")])
                self.assertNotIn("--interactive-comparison", command)
                self.write_result(root=output / "results")
                # FRT, not this adapter, owns SDK-aware dependency validation.
                (output / "results/specimen-client/frt-pubspec.lock").write_text("SDK metadata differs")
            return subprocess.CompletedProcess(command, 0)

        with patch.object(frt_ci.subprocess, "check_output", return_value="b" * 40), \
                patch.object(frt_ci, "run_logged", side_effect=fake_run), \
                patch.object(frt_ci, "web_browser", return_value=self.root / "edge.exe"), \
                patch.object(frt_ci, "download_baseline"), redirect_stdout(io.StringIO()) as console:
            self.assertEqual(frt_ci.run_comparison(args), 0)
        self.assertIn('FRT windows result: {"status": "passed", "exit_code": 0}', console.getvalue())
        self.assertTrue((output / "identity.json").is_file())
        self.assertTrue((output / "jenkins-result.json").is_file())
        self.assertFalse(list(self.root.glob("frt-input-*")))
        self.assertEqual((sdk / "candidate.zip").read_bytes(), b"candidate")
        with self.assertRaises(FileExistsError), patch.object(
                frt_ci.subprocess, "check_output", return_value="b" * 40):
            frt_ci.run_comparison(args)

    def test_gradle_home_is_fresh_each_run_and_cleaned_on_failure(self):
        plan = frt_ci.load_plan(self.config, ["macos"], {"WSC_FRT_ENABLED": "1"})
        plan_path = self.root / "plan.json"
        frt_ci.write_json(plan_path, plan)
        fixture = self.root / "frt" / plan["fixture"]
        fixture.parent.mkdir(parents=True)
        fixture.write_text("{}")
        sdk = self.root / "sdk"
        sdk.mkdir()
        (sdk / "candidate.zip").write_bytes(b"sdk")
        shared = self.root / "shared-gradle-home"
        shared.mkdir()
        (shared / "keep.jar").write_bytes(b"agent cache")
        homes = []
        failure = [False]

        def run(command, **kwargs):
            self.assertEqual(command[:3], [sys.executable, "-m", "uv"])
            if "compare" in command:
                home = Path(kwargs["env"]["GRADLE_USER_HOME"])
                homes.append(home)
                self.assertNotEqual(home, shared)
                self.assertFalse((home / "download.jar").exists())
                (home / "download.jar").write_bytes(b"new dependency")
                if failure[0]:
                    raise OSError("client could not start")
                return subprocess.CompletedProcess(command, 1)
            return subprocess.CompletedProcess(command, 0)

        with patch.dict(os.environ, {"GRADLE_USER_HOME": str(shared)}), \
                patch.object(frt_ci.subprocess, "check_output", return_value="b" * 40), \
                patch.object(frt_ci, "run_logged", side_effect=run), \
                patch.object(frt_ci, "download_baseline"), redirect_stdout(io.StringIO()) as console:
            for index in range(2):
                failure[0] = bool(index)
                args = argparse.Namespace(plan=plan_path, host="macos", frt=self.root / "frt",
                    revision="b" * 40, output=self.root / f"evidence-{index}", sdk_directory=sdk)
                self.assertEqual(frt_ci.run_comparison(args), 2 if failure[0] else 1)
                self.assertFalse(homes[-1].exists())
        self.assertIn('FRT macos result: {"status": "failed", "exit_code": 1}', console.getvalue())
        self.assertIn('"error": "client could not start"', console.getvalue())
        self.assertNotEqual(homes[0], homes[1])
        self.assertEqual((shared / "keep.jar").read_bytes(), b"agent cache")
        self.assertFalse(list(self.root.glob("frt-input-*")))

    def test_run_precondition_errors_exit_two_not_mismatch(self):
        command = [
            "frt_ci.py", "run", "--plan", str(self.root / "missing.json"),
            "--host", "windows", "--frt", str(self.root), "--revision", "b" * 40,
            "--sdk-directory", str(self.root), "--output", str(self.root / "evidence"),
        ]
        with patch("sys.argv", command), redirect_stdout(io.StringIO()):
            self.assertEqual(frt_ci.main(), 2)

    def test_logged_child_streams_stdout_stderr_and_preserves_exit_codes(self):
        # Real tiny child processes: no uv, SDKs or network required.
        script = (
            "import os, sys; "
            "print('stdout caf\\u00e9'); "
            "print('stderr', file=sys.stderr); "
            "print(os.environ['FRT_TEST_VALUE']); "
            "sys.stdout.buffer.write(b'tail\\xff'); "
            "sys.exit(2)"
        )
        for check in (False, True):
            with self.subTest(check=check), (self.root / "runner.log").open(
                    "w+", encoding="utf-8") as log, redirect_stdout(io.StringIO()) as console:
                command = [sys.executable, "-c", script]
                with patch.dict(os.environ, {"FRT_TEST_VALUE": "environment preserved"}):
                    if check:
                        with self.assertRaises(subprocess.CalledProcessError) as error:
                            frt_ci.run_logged(command, cwd=self.root, log=log, host="windows", check=True)
                        self.assertEqual(error.exception.returncode, 2)
                    else:
                        result = frt_ci.run_logged(command, cwd=self.root, log=log, host="windows")
                        self.assertEqual(result.returncode, 2)
                log.seek(0)
                self.assertEqual(log.read(), "stdout caf\u00e9\nstderr\nenvironment preserved\ntail\ufffd")
                self.assertEqual(console.getvalue(),
                    "[FRT windows] stdout caf\u00e9\n[FRT windows] stderr\n"
                    "[FRT windows] environment preserved\n[FRT windows] tail\ufffd")

    def test_logged_output_is_forwarded_before_child_finishes(self):
        log = io.StringIO()
        console = io.StringIO()

        def lines():
            yield "progress\n"
            self.assertEqual(log.getvalue(), "progress\n")
            self.assertEqual(console.getvalue(), "[FRT macos] progress\n")
            yield "done\n"

        with patch.object(frt_ci.subprocess, "Popen") as popen, redirect_stdout(console):
            process = popen.return_value.__enter__.return_value
            process.stdout = lines()
            process.wait.return_value = 0
            result = frt_ci.run_logged(["test"], cwd=self.root, log=log, host="macos",
                                      env={"FRT_TEST_VALUE": "custom"})
            self.assertEqual(result.returncode, 0)
            self.assertEqual(popen.call_args.kwargs["env"], {
                "FRT_TEST_VALUE": "custom", "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8",
            })

    def report_args(self, hosts=("windows", "macos")):
        plan = self.root / "plan.json"
        frt_ci.write_json(plan, {"hosts": list(hosts),
                                "targets": [target for host in hosts for target in frt_ci.HOST_TARGETS[host]]})
        return argparse.Namespace(plan=plan, frt=self.root, inputs=self.root / "inputs",
                                  output=self.root / "artifacts")

    def fake_report(self, args, code=0, xml=True):
        def run(command, **kwargs):
            self.assertEqual(command[:3], [sys.executable, "-m", "uv"])
            if "report" in command:
                self.assertIn("--locked", command)
                self.assertIn("--format", command)
                self.assertEqual(command[command.index("--expect-targets") + 1:command.index("--output")],
                                 json.loads(args.plan.read_text())["targets"])
                self.assertEqual(command.count("--input"), len(json.loads(args.plan.read_text())["hosts"]))
                with ZipFile(args.output / "frt-comparisons.zip", "w") as archive:
                    archive.writestr("index.html", "offline report")
                    if xml:
                        archive.writestr("junit.xml", "<testsuites/>")
                return subprocess.CompletedProcess(command, code)
            return subprocess.CompletedProcess(command, 0)
        return run

    def capture_codes(self, args, values):
        for host, value in values.items():
            folder = args.inputs / host
            folder.mkdir(parents=True)
            (folder / "capture-exit.txt").write_text(str(value))

    def test_reporting_pass_mismatch_error_and_unexpected_status(self):
        for capture, report, expected in [(0, 0, 0), (1, 0, 1), (0, 1, 1),
                                           (2, 0, 2), (0, 2, 2), (0, 17, 2), (17, 0, 2)]:
            with self.subTest(capture=capture, report=report):
                args = self.report_args(("windows",))
                args.inputs = self.root / f"inputs-{capture}-{report}"
                args.output = self.root / f"artifacts-{capture}-{report}"
                self.capture_codes(args, {"windows": capture})
                with patch.object(frt_ci.subprocess, "run", side_effect=self.fake_report(args, report)):
                    self.assertEqual(frt_ci.aggregate_reports(args), expected)
                self.assertEqual((args.output / "frt-junit.xml").read_text(), "<testsuites/>")

    def test_missing_host_is_not_removed_from_expectations(self):
        args = self.report_args()
        self.capture_codes(args, {"windows": 0})
        with patch.object(frt_ci.subprocess, "run", side_effect=self.fake_report(args)):
            self.assertEqual(frt_ci.aggregate_reports(args), 2)
        self.assertTrue((args.output / "frt-comparisons.zip").exists())

    def test_missing_xml_keeps_zip_and_stale_outputs_are_rejected(self):
        args = self.report_args(("windows",))
        self.capture_codes(args, {"windows": 0})
        with patch.object(frt_ci.subprocess, "run", side_effect=self.fake_report(args, xml=False)):
            with self.assertRaises(KeyError):
                frt_ci.aggregate_reports(args)
        self.assertTrue((args.output / "frt-comparisons.zip").exists())
        with self.assertRaises(FileExistsError):
            frt_ci.aggregate_reports(args)

    def test_missing_zip_is_error_not_success(self):
        args = self.report_args(("windows",))
        self.capture_codes(args, {"windows": 0})
        with patch.object(frt_ci.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)):
            with self.assertRaises(FileNotFoundError):
                frt_ci.aggregate_reports(args)



if __name__ == "__main__":
    unittest.main()
