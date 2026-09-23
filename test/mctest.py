#!/usr/bin/env python3
# Copyright (c) 2026 Tyler Fursman
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Boot real vanilla servers with the built data packs and craft with a bot."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import pathlib
import platform
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request
import uuid
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
RUN = ROOT / "run"
BOT = pathlib.Path(__file__).resolve().parent / "bot"
CACHE = pathlib.Path(os.environ.get("MCTEST_CACHE", pathlib.Path.home() / ".cache" / "mctest"))

USER_AGENT = "mctest/1.0 (+https://github.com/WhoIsTyfur/craftable-notch-apples)"
VERSION_MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
ADOPTIUM = (
    "https://api.adoptium.net/v3/assets/latest/{feature}/hotspot"
    "?architecture=x64&image_type=jdk&os={os}&vendor=eclipse"
)
VIAPROXY = (
    "https://github.com/ViaVersion/ViaProxy/releases/download/v3.4.13/ViaProxy-3.4.13.jar",
    "4bbb6a6b9d3dd6a2028773ed44b97a98751e4a48e416aaad4bf6d9c860083be9",
)
BOT_NAME = "tester"
NAMESPACE = "craftablenotchapples"

# mineflayer 4.39.0 has no data for these; they share a protocol with the listed version.
BOT_ALIASES = {
    "1.19.1": "1.19.2",
    "1.21.2": "1.21.3",
    "1.21.7": "1.21.8",
    "26.1.1": "26.1",
    "26.1.2": "26.1",
}

# No same-protocol data at all: (client version the bot uses, ViaProxy target).
VIA_ROUTES = {
    "1.13.1": ("1.13.2", "1.13.1"),
    "1.14.2": ("1.14.4", "1.14.2"),
    "26.2": ("26.1", "26.2"),
    "26.3": ("26.1", "26.3"),
}

# ViaProxy 3.4.13 turns the bot's routine movement packets into ones these reject.
NO_MOVEMENT = {"26.3"}

_print_lock = threading.Lock()
_locks_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}


def log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def http_get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.read()
        except OSError:
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))
    raise AssertionError("unreachable")


def download(url: str, dest: pathlib.Path, *, sha1: str | None = None, sha256: str | None = None) -> pathlib.Path:
    with lock_for(str(dest)):
        if dest.exists():
            return dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = http_get(url)
        if sha1 and hashlib.sha1(data).hexdigest() != sha1:
            raise RuntimeError(f"sha1 mismatch for {url}")
        if sha256 and hashlib.sha256(data).hexdigest() != sha256:
            raise RuntimeError(f"sha256 mismatch for {url}")
        tmp = dest.with_suffix(dest.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(dest)
        return dest


def java_executable(major: int) -> pathlib.Path:
    feature = 17 if major == 16 else major
    home = CACHE / "jdk" / str(feature)
    exe_name = "java.exe" if os.name == "nt" else "java"
    with lock_for(str(home)):
        found = sorted(home.glob(f"*/bin/{exe_name}"))
        if found:
            return found[0]
        os_name = {"Windows": "windows", "Linux": "linux", "Darwin": "mac"}[platform.system()]
        assets = json.loads(http_get(ADOPTIUM.format(feature=feature, os=os_name)))
        package = assets[0]["binary"]["package"]
        archive = download(package["link"], CACHE / "downloads" / package["name"], sha256=package["checksum"])
        log(f"extracting JDK {feature}")
        # Extract beside the target and rename, so a half-written JDK is never picked up.
        staging = home.with_name(home.name + ".extracting")
        shutil.rmtree(staging, ignore_errors=True)
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(staging)
        else:
            with tarfile.open(archive) as tf:
                tf.extractall(staging, filter="data")
            for java in staging.glob("*/bin/java"):
                java.chmod(0o755)
        shutil.rmtree(home, ignore_errors=True)
        staging.rename(home)
        return sorted(home.glob(f"*/bin/{exe_name}"))[0]


_manifest: dict | None = None


def version_json(version: str) -> dict:
    global _manifest
    with lock_for("manifest"):
        if _manifest is None:
            _manifest = json.loads(http_get(VERSION_MANIFEST))
    entry = next((v for v in _manifest["versions"] if v["id"] == version), None)
    if entry is None:
        raise RuntimeError(f"unknown Minecraft version {version}")
    path = download(entry["url"], CACHE / "versions" / f"{version}.json", sha1=entry["sha1"])
    return json.loads(path.read_text(encoding="utf-8"))


def vanilla_server(version: str) -> tuple[pathlib.Path, int]:
    meta = version_json(version)
    server = meta["downloads"]["server"]
    jar = download(server["url"], CACHE / "vanilla" / version / "server.jar", sha1=server["sha1"])
    return jar, meta.get("javaVersion", {}).get("majorVersion", 8)


def offline_uuid(name: str) -> str:
    # Same as Java's UUID.nameUUIDFromBytes("OfflinePlayer:" + name).
    digest = bytearray(hashlib.md5(f"OfflinePlayer:{name}".encode()).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30
    digest[8] = (digest[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(digest)))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Process:
    def __init__(self, args: list[str], workdir: pathlib.Path):
        self.lines: list[str] = []
        self._cond = threading.Condition()
        self.process = subprocess.Popen(
            args,
            cwd=workdir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self) -> None:
        for line in self.process.stdout:
            with self._cond:
                self.lines.append(line.rstrip("\n"))
                self._cond.notify_all()
        with self._cond:
            self._cond.notify_all()

    def wait_for(self, pattern: str, timeout: float, start: int = 0) -> re.Match | None:
        regex = re.compile(pattern)
        deadline = time.monotonic() + timeout
        index = start
        with self._cond:
            while True:
                while index < len(self.lines):
                    match = regex.search(self.lines[index])
                    if match:
                        return match
                    index += 1
                remaining = deadline - time.monotonic()
                if remaining <= 0 or self.process.poll() is not None:
                    return None
                self._cond.wait(min(remaining, 1.0))

    def command(self, text: str) -> int:
        with self._cond:
            mark = len(self.lines)
        self.process.stdin.write(text + "\n")
        self.process.stdin.flush()
        return mark

    def stop(self) -> None:
        if self.process.poll() is None:
            try:
                self.command("stop")
                self.process.wait(timeout=90)
            except (OSError, subprocess.TimeoutExpired):
                self.kill()
        self._reader.join(timeout=10)

    def kill(self) -> None:
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait()


def start_server(java: pathlib.Path, jar: pathlib.Path, workdir: pathlib.Path) -> Process:
    # Headless, so no server can pop a desktop dialog when it finds no console.
    args = [str(java), "-Xms512M", "-Xmx2G", "-Djava.awt.headless=true", "-Dlog4j2.formatMsgNoLookups=true", "-jar", str(jar), "nogui"]
    return Process(args, workdir)


def start_viaproxy(workdir: pathlib.Path, server_port: int, target: str) -> tuple[Process, int]:
    url, sha256 = VIAPROXY
    jar = download(url, CACHE / "viaproxy" / url.rsplit("/", 1)[1], sha256=sha256)
    proxy_dir = workdir / "viaproxy"
    proxy_dir.mkdir(exist_ok=True)
    port = free_port()
    args = [
        str(java_executable(21)),
        "-jar",
        str(jar),
        "cli",
        "--bind-address",
        f"127.0.0.1:{port}",
        "--target-address",
        f"127.0.0.1:{server_port}",
        "--target-version",
        target,
    ]
    proxy = Process(args, proxy_dir)
    proxy.wait_for(r"Binding proxy server to", timeout=90)
    proxy.wait_for(r"Finished mapping loading", timeout=60)
    return proxy, port


def prepare_instance(name: str, port: int, datapacks: list[pathlib.Path]) -> pathlib.Path:
    workdir = RUN / name
    if workdir.exists():
        shutil.rmtree(workdir)
    (workdir / "world" / "datapacks").mkdir(parents=True)
    for pack in datapacks:
        shutil.copy2(pack, workdir / "world" / "datapacks" / pack.name)
    (workdir / "eula.txt").write_text("eula=true\n", encoding="utf-8")
    properties = {
        "online-mode": "false",
        "server-port": str(port),
        "server-ip": "127.0.0.1",
        "level-type": "flat",
        "generate-structures": "false",
        "spawn-protection": "0",
        "spawn-monsters": "false",
        # spawn-monsters alone still let a slime kill the bot on 26.1.2.
        "difficulty": "0",
        "view-distance": "4",
        "simulation-distance": "4",
        "max-tick-time": "-1",
        "allow-flight": "true",
        "enforce-secure-profile": "false",
        "motd": "mctest",
    }
    (workdir / "server.properties").write_text(
        "".join(f"{k}={v}\n" for k, v in properties.items()), encoding="utf-8"
    )
    ops = [{"uuid": offline_uuid(BOT_NAME), "name": BOT_NAME, "level": 4, "bypassesPlayerLimit": False}]
    (workdir / "ops.json").write_text(json.dumps(ops), encoding="utf-8")
    return workdir


def run_bot(scenario: str, port: int, version: str, workdir: pathlib.Path, timeout: float = 120) -> dict:
    node = shutil.which("node")
    if node is None:
        return {"ok": False, "error": "node not found"}
    proxy = None
    client_version = BOT_ALIASES.get(version, version)
    try:
        if version in VIA_ROUTES:
            client_version, target = VIA_ROUTES[version]
            proxy, port = start_viaproxy(workdir, port, target)
        env = dict(os.environ, MCTEST_NO_MOVEMENT="1" if version in NO_MOVEMENT else "0")
        result = subprocess.run(
            [node, str(BOT / "craft.js"), "127.0.0.1", str(port), client_version, scenario, BOT_NAME],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "bot timed out"}
    finally:
        if proxy is not None:
            proxy.kill()
    for line in reversed(result.stdout.splitlines()):
        if line.startswith("RESULT "):
            return json.loads(line[len("RESULT "):])
    tail = (result.stdout + result.stderr).strip().splitlines()[-15:]
    return {"ok": False, "error": "bot gave no result", "output": tail}


def scan_errors(lines: list[str], needles: tuple[str, ...]) -> list[str]:
    bad = re.compile(r"ERROR|WARN|Couldn't|Parsing error|Failed|Exception", re.IGNORECASE)
    return [line for line in lines if any(n in line for n in needles) and bad.search(line)]


def test_datapack(version: str, pack: pathlib.Path, use_bot: bool) -> dict:
    jar, java_major = vanilla_server(version)
    java = java_executable(java_major)
    port = free_port()
    workdir = prepare_instance(f"datapack-{version}", port, [pack])
    server = start_server(java, jar, workdir)
    report: dict = {"version": version, "pack": pack.name}
    try:
        if not server.wait_for(r"Done \(", timeout=240):
            report.update(ok=False, error="server did not finish starting", tail=server.lines[-20:])
            return report
        mark = server.command("datapack list")
        listed = server.wait_for(r"enabled: ", timeout=20, start=mark)
        enabled_line = listed.string if listed else ""
        report["enabled"] = f"file/{pack.name}" in enabled_line
        errors = scan_errors(server.lines, (NAMESPACE, pack.name))
        report["errors"] = errors
        if use_bot:
            report["bot"] = run_bot("datapack", port, version, workdir)
        report["ok"] = report["enabled"] and not errors and (not use_bot or report["bot"].get("ok", False))
        if not report["ok"]:
            report["tail"] = server.lines[-25:]
        return report
    finally:
        server.stop()


def packs_by_version() -> dict[str, pathlib.Path]:
    manifest = json.loads((DIST / "manifest.json").read_text(encoding="utf-8"))
    return {v: DIST / entry["file"] for entry in manifest for v in entry["game_versions"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--versions", default="all", help="comma-separated list, or 'all'")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--no-bot", action="store_true", help="only check that the pack loads")
    args = parser.parse_args()

    packs = packs_by_version()
    versions = list(packs) if args.versions == "all" else [v.strip() for v in args.versions.split(",") if v.strip()]
    missing = [v for v in versions if v not in packs]
    if missing:
        parser.error(f"no pack built for: {', '.join(missing)} (run build.py first)")
    if not args.no_bot and not (BOT / "node_modules").exists():
        parser.error("run `npm ci` in test/bot first, or pass --no-bot")

    results: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(test_datapack, v, packs[v], not args.no_bot): v for v in versions}
        for future in concurrent.futures.as_completed(futures):
            version = futures[future]
            try:
                report = future.result()
            except Exception as exc:  # noqa: BLE001 - one broken version must not stop the rest
                report = {"version": version, "ok": False, "error": repr(exc)}
            results.append(report)
            log(f"{'PASS' if report['ok'] else 'FAIL'}  {version}")
            if not report["ok"]:
                log(json.dumps(report, indent=2))

    results.sort(key=lambda r: versions.index(r["version"]))
    RUN.mkdir(exist_ok=True)
    (RUN / "results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    failed = [r["version"] for r in results if not r["ok"]]
    log(f"\n{len(results) - len(failed)}/{len(results)} passed" + (f"; failed: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
