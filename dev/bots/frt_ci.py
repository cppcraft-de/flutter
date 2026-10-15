#!/usr/bin/env python3
"""Small Jenkins adapter for FRT's existing SDK comparison command (stdlib only)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
from urllib.parse import urlsplit
from urllib.request import urlopen


HOSTS = ("windows", "macos")


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def public_url(value: str) -> None:
    parsed = urlsplit(value)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or any(char.isspace() for char in value)):
        raise ValueError("FRT URLs must be HTTP(S), without credentials, query strings or fragments")


def load_plan(path: Path, hosts: list[str], environ=None) -> dict:
    environ = os.environ if environ is None else environ
    plan = json.loads(path.read_text(encoding="utf-8"))
    for key in ("repository", "ref", "credentials_id"):
        override = environ.get(f"WSC_FRT_{key.upper()}", "").strip()
        if override:
            plan[key] = override
    enabled = environ.get("WSC_FRT_ENABLED", "").strip().lower()
    if enabled:
        if enabled not in ("1", "true", "yes", "on", "0", "false", "no", "off"):
            raise ValueError("WSC_FRT_ENABLED must be a boolean value")
        plan["enabled"] = enabled in ("1", "true", "yes", "on")
    if type(plan["enabled"]) is not bool:
        raise ValueError("FRT enabled must be a boolean")
    if any(host not in HOSTS for host in hosts):
        raise ValueError("Only Windows/macOS FRT capture is implemented")
    plan["hosts"] = hosts
    for host in HOSTS:
        for key in ("url", "sha256"):
            override = environ.get(f"WSC_FRT_BASELINE_{host.upper()}_{key.upper()}", "").strip()
            if override:
                plan["baselines"][host][key] = override
    if not plan["enabled"] or not hosts:
        return plan
    public_url(plan["repository"])
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", plan["ref"]):
        raise ValueError("FRT ref must be a branch, tag ref, or commit SHA")
    fixture = Path(plan["fixture"])
    if fixture.is_absolute() or ".." in fixture.parts or "\\" in plan["fixture"] or ":" in plan["fixture"]:
        raise ValueError("FRT fixture must be a relative repository path")
    if plan["build_mode"] not in ("debug", "profile", "release"):
        raise ValueError("Invalid FRT build_mode")
    if type(plan["dpi"]) not in (int, float) or not 0 < plan["dpi"] < float("inf"):
        raise ValueError("FRT dpi must be positive and finite")
    for host in hosts:
        baseline = plan["baselines"][host]
        public_url(baseline["url"])
        if not re.fullmatch(r"[0-9a-fA-F]{64}", baseline["sha256"]):
            raise ValueError(f"Configure the approved {host} baseline URL and SHA-256 before enabling FRT")
    return plan


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_baseline(url: str, checksum: str, destination: Path) -> None:
    public_url(url)
    with urlopen(url, timeout=120) as response, destination.open("xb") as stream:
        public_url(response.url)
        shutil.copyfileobj(response, stream)
    if sha256(destination) != checksum.lower():
        raise ValueError("Baseline SDK SHA-256 mismatch; refusing to run it")


def validate_result(results: Path, exit_code: int) -> dict:
    result = json.loads((results / "result.json").read_text(encoding="utf-8"))
    if (exit_code not in (0, 1, 2)
            or result.get("schema") != "font-rendering-tester/regression-result/v1"
            or result.get("exit_code") != exit_code
            or result.get("status") != {0: "passed", 1: "failed", 2: "error"}.get(exit_code)):
        raise ValueError("FRT exit status and result.json disagree or use an unsupported schema")
    if exit_code == 2:
        return result
    counts = result["comparison_summary"]
    total, passed = result["total_case_count"], result["passed_case_count"]
    if (type(total) is not int or type(passed) is not int or total <= 0
            or not 0 <= passed <= total or counts["total_field_count"] != total
            or counts["missing_baseline_count"] or counts["missing_specimen_count"]
            or result["unavailable_field_count"]
            or not {"line_metrics", "fonts"}.issubset(result["pass_check_ids"])):
        raise ValueError("FRT comparison is empty/incomplete or required checks are unavailable")
    baseline, specimen = result["baseline_run_id"], result["specimen_run_id"]
    if (type(baseline) is not int or type(specimen) is not int
            or min(baseline, specimen) <= 0 or baseline == specimen):
        raise ValueError("FRT must compare two distinct committed runs")
    if (exit_code == 0 and (passed != total or counts["failed_count"])) or (
            exit_code == 1 and not counts["failed_count"]):
        raise ValueError("FRT case counts disagree with the reported outcome")
    # The runner uses pub get. Detect different resolved dependencies without
    # introducing a YAML parser or silently accepting a changed test client.
    baseline_lock = (results / "baseline-client/frt-pubspec.lock").read_bytes()
    specimen_lock = (results / "specimen-client/frt-pubspec.lock").read_bytes()
    if not baseline_lock or baseline_lock != specimen_lock:
        raise ValueError("FRT clients resolved different dependency lockfiles; review compatibility in FRT")
    return result


def run_comparison(args) -> int:
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    if not plan["enabled"] or args.host not in plan["hosts"]:
        raise ValueError("This host is not enabled in the resolved FRT plan")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", args.revision):
        raise ValueError("FRT revision must be the exact resolved commit")
    frt = args.frt.resolve(strict=True)
    actual_revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=frt, text=True).strip()
    if actual_revision.lower() != args.revision.lower():
        raise ValueError("FRT checkout differs from this build's resolved revision")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "inputs.json", {"config": plan, "host": args.host, "frt_revision": actual_revision})
    try:
        archives = list(args.sdk_directory.glob("*.zip"))
        if len(archives) != 1:
            raise ValueError("Expected exactly one candidate SDK ZIP from this host's packaging stage")
        candidate = archives[0].resolve(strict=True)
        fixture = (frt / plan["fixture"]).resolve(strict=True)
        if not fixture.is_relative_to(frt):
            raise ValueError("FRT fixture escapes its checkout")
        baseline = plan["baselines"][args.host]
        write_json(output / "identity.json", {
            "frt_revision": actual_revision, "candidate_zip": candidate.name,
            "candidate_sha256": sha256(candidate), "baseline_url": baseline["url"],
            "baseline_sha256": baseline["sha256"], "fixture_sha256": sha256(fixture),
        })
        print(f"FRT {args.host}: preparing pinned tools and verified baseline SDK", flush=True)
        with (output / "runner.log").open("w", encoding="utf-8") as log:
            subprocess.run(["uv", "sync", "--locked"], cwd=frt, stdout=log, stderr=subprocess.STDOUT, check=True)
            # Only this owned temporary input directory is removed. Engine
            # workspaces, candidate ZIPs and result bundles are never cleaned.
            with tempfile.TemporaryDirectory(prefix="frt-input-", dir=output.parent) as temporary:
                baseline_zip = Path(temporary) / "baseline.zip"
                download_baseline(baseline["url"], baseline["sha256"], baseline_zip)
                command = [
                    "uv", "run", "--locked", "font-rendering-regression", "compare",
                    "--baseline-sdk", str(baseline_zip), "--specimen-sdk", str(candidate),
                    "--target", args.host, "--fixture", str(fixture),
                    "--build-mode", plan["build_mode"], "--dpi", str(plan["dpi"]),
                    "--output-dir", str(output / "results"),
                ]
                print(f"FRT {args.host}: building/capturing both clients; details in runner.log", flush=True)
                completed = subprocess.run(command, cwd=frt, stdout=log, stderr=subprocess.STDOUT)
        result = validate_result(output / "results", completed.returncode)
        print(result.get("summary", result["status"]), flush=True)
        write_json(output / "jenkins-result.json", result)
        return completed.returncode
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        # Summarize the cause in emailed console logs; retain full build logs
        # privately. No credential values are supplied to this adapter.
        write_json(output / "jenkins-result.json", {"status": "error", "exit_code": 2, "error": str(error)})
        print(f"FRT failed: {error}; see private jenkins-result.json and runner.log", flush=True)
        return 2


def archive_evidence(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Preserve macOS bundle symlinks. Exclude interrupted extraction/build
    # scratch trees; these are not useful retained evidence and may be huge.
    def retained(member):
        return None if any(part.startswith("work-") for part in Path(member.name).parts) else member
    with tarfile.open(destination, "x:gz", dereference=False) as archive:
        archive.add(source, arcname=source.name, filter=retained)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--config", type=Path, default=Path("dev/bots/frt_ci.json"))
    plan.add_argument("--hosts", required=True)
    plan.add_argument("--output", type=Path, required=True)
    run = commands.add_parser("run")
    run.add_argument("--plan", type=Path, required=True)
    run.add_argument("--host", choices=HOSTS, required=True)
    run.add_argument("--frt", type=Path, required=True)
    run.add_argument("--revision", required=True)
    run.add_argument("--sdk-directory", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    archive = commands.add_parser("archive")
    archive.add_argument("--source", type=Path, required=True)
    archive.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "plan":
        write_json(args.output, load_plan(args.config, [host for host in args.hosts.split(",") if host]))
    elif args.command == "run":
        try:
            return run_comparison(args)
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
            # Precondition errors occur before evidence creation. Never let a
            # Python exception's usual exit 1 masquerade as a rendering mismatch.
            print(f"FRT could not start: {error}", flush=True)
            return 2
    else:
        archive_evidence(args.source, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
