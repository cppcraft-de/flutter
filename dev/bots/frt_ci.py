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
import sys
import tempfile
from urllib.parse import urlsplit
from urllib.request import urlopen
from zipfile import BadZipFile, ZipFile


HOST_TARGETS = {"windows": ("windows", "web"), "macos": ("macos",)}
HOSTS = tuple(HOST_TARGETS)


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
    plan["targets"] = [target for host in hosts for target in HOST_TARGETS[host]]
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


def web_browser(environ=None) -> Path:
    """Use installed Edge unless explicitly overridden; no browser downloads."""
    environ = os.environ if environ is None else environ
    override = environ.get("WSC_FRT_BROWSER", "").strip()
    if override:
        browser = Path(override)
        if not browser.is_file():
            raise ValueError("WSC_FRT_BROWSER must point to an existing Chrome/Edge executable")
        return browser.resolve()
    for variable in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        directory = environ.get(variable)
        if directory and (browser := Path(directory) / "Microsoft/Edge/Application/msedge.exe").is_file():
            return browser.resolve()
    raise ValueError("Web capture needs Edge; install it or explicitly set WSC_FRT_BROWSER to a Chrome/Edge executable")


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
            subprocess.run([sys.executable, "-m", "uv", "sync", "--locked"], cwd=frt, stdout=log, stderr=subprocess.STDOUT, check=True)
            # Only this owned temporary input directory is removed. Engine
            # workspaces, candidate ZIPs and result bundles are never cleaned.
            with tempfile.TemporaryDirectory(prefix="frt-input-", dir=output.parent) as temporary:
                # A fresh Gradle home avoids old Maven artifacts and Gradle build
                # caches without deleting anything in the agent's shared home.
                # Owned by this context: removed on success or ordinary failure.
                gradle_home = Path(temporary) / "gradle-home"
                gradle_home.mkdir()
                (gradle_home / "gradle.properties").write_text(
                    "org.gradle.daemon=false\norg.gradle.caching=false\n", encoding="utf-8")
                environment = os.environ.copy()
                environment["GRADLE_USER_HOME"] = str(gradle_home)
                environment["GRADLE_OPTS"] = (
                    environment.get("GRADLE_OPTS", "") + " -Dorg.gradle.daemon=false -Dorg.gradle.caching=false"
                ).strip()
                print("FRT: fresh temporary GRADLE_USER_HOME; removed after comparison. "
                      "CDN caching is configured separately.", flush=True)
                baseline_zip = Path(temporary) / "baseline.zip"
                download_baseline(baseline["url"], baseline["sha256"], baseline_zip)
                command = [
                    sys.executable, "-m", "uv", "run", "--locked", "font-rendering-regression", "compare",
                    "--baseline-sdk", str(baseline_zip), "--specimen-sdk", str(candidate),
                    "--targets", *HOST_TARGETS[args.host], "--fixture", str(fixture),
                    "--build-mode", plan["build_mode"], "--dpi", str(plan["dpi"]),
                    "--output-dir", str(output / "results"),
                ]
                if "web" in HOST_TARGETS[args.host]:
                    command.extend(["--browser", str(web_browser())])
                print(f"FRT {args.host}: building/capturing both clients; details in runner.log", flush=True)
                completed = subprocess.run(command, cwd=frt, env=environment, stdout=log, stderr=subprocess.STDOUT)
        # FRT compare owns dependency compatibility; FRT report owns result
        # validation. Do not duplicate either policy in this Jenkins adapter.
        code = completed.returncode if completed.returncode in (0, 1, 2) else 2
        result = {"status": {0: "passed", 1: "failed", 2: "error"}[code], "exit_code": code}
        write_json(output / "jenkins-result.json", result)
        return code
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        # Summarize the cause in emailed console logs; retain full build logs
        # privately. No credential values are supplied to this adapter.
        write_json(output / "jenkins-result.json", {"status": "error", "exit_code": 2, "error": str(error)})
        print(f"FRT failed: {error}; see private jenkins-result.json and runner.log", flush=True)
        return 2


def aggregate_reports(args) -> int:
    """Package saved reports offline; missing hosts remain expected inputs."""
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    hosts = plan["hosts"]
    if not hosts or any(host not in HOSTS for host in hosts):
        raise ValueError("Expected at least one configured desktop host")
    frt = args.frt.resolve(strict=True)
    output = args.output.resolve()
    # Never accept a ZIP/XML left by an earlier attempt.
    output.mkdir(parents=True, exist_ok=False)
    subprocess.run([sys.executable, "-m", "uv", "sync", "--locked"], cwd=frt, check=True)
    command = [sys.executable, "-m", "uv", "run", "--locked", "font-rendering-regression", "report", "--format", "zip"]
    codes = []
    for host in hosts:
        source = args.inputs.resolve() / host
        command.extend(["--input", str(source / "results")])
        try:
            saved = (source / "capture-exit.txt").read_text(encoding="utf-8").strip()
        except OSError:
            saved = ""
        codes.append(int(saved) if saved in ("0", "1", "2") else 2)
    archive = output / "frt-comparisons.zip"
    command.extend(["--expect-targets", *plan["targets"], "--output", str(archive)])
    codes.append(subprocess.run(command, cwd=frt, check=False).returncode)
    # Read one known member, not extractall. Jenkins still archives the ZIP if
    # XML extraction fails, and checks both outputs independently.
    with ZipFile(archive) as contents:
        (output / "frt-junit.xml").write_bytes(contents.read("junit.xml"))
    return 2 if any(code not in (0, 1) for code in codes) else max(codes)


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
    report = commands.add_parser("report")
    report.add_argument("--plan", type=Path, required=True)
    report.add_argument("--frt", type=Path, required=True)
    report.add_argument("--inputs", type=Path, required=True)
    report.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "plan":
        write_json(args.output, load_plan(args.config, [host for host in args.hosts.split(",") if host]))
    else:
        try:
            return run_comparison(args) if args.command == "run" else aggregate_reports(args)
        except (OSError, ValueError, KeyError, TypeError, BadZipFile, subprocess.SubprocessError) as error:
            # Precondition errors occur before evidence creation. Never let a
            # Python exception's usual exit 1 masquerade as a rendering mismatch.
            print(f"FRT {args.command} failed: {error}", flush=True)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
