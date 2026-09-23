#!/usr/bin/env python3
# Copyright (c) 2026 Tyler Fursman
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Upload the zips listed in dist/manifest.json to Modrinth and CurseForge.

Reads MODRINTH_TOKEN / MODRINTH_PROJECT_ID and CURSEFORGE_TOKEN /
CURSEFORGE_PROJECT_ID from the environment; a platform without both is skipped.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.request
import uuid

ROOT = pathlib.Path(__file__).resolve().parent
DIST = ROOT / "dist"
USER_AGENT = "TinyGecko920/craftable-notch-apples publish.py"
MODRINTH_API = "https://api.modrinth.com/v2"
CURSEFORGE_API = "https://minecraft.curseforge.com/api"


def multipart(fields: dict[str, str], files: dict[str, pathlib.Path]) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n'
            f"Content-Type: application/json\r\n\r\n{value}\r\n".encode()
        )
    for name, path in files.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{path.name}"\r\n'
            f"Content-Type: application/zip\r\n\r\n".encode()
            + path.read_bytes()
            + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def request(url: str, headers: dict[str, str], body: bytes | None = None, content_type: str | None = None):
    headers = {"User-Agent": USER_AGENT, **headers}
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=body, headers=headers, method="POST" if body else "GET")
    try:
        with urllib.request.urlopen(req, timeout=300) as response:
            return json.loads(response.read() or b"null")
    except urllib.error.HTTPError as err:
        raise RuntimeError(f"{url}: HTTP {err.code}: {err.read().decode(errors='replace')}") from None


def changelog_for(version: str) -> str:
    path = ROOT / "CHANGELOG.md"
    if not path.exists():
        return ""
    match = re.search(rf"^## {re.escape(version)}\b.*?\n(.*?)(?=^## |\Z)", path.read_text(encoding="utf-8"), re.S | re.M)
    return match.group(1).strip() if match else ""


def modrinth(entry: dict, changelog: str, dry_run: bool) -> None:
    data = {
        "project_id": os.environ.get("MODRINTH_PROJECT_ID", "<MODRINTH_PROJECT_ID>"),
        "name": f"Craftable Notch Apples {entry['version_number']}",
        "version_number": entry["version_number"],
        "changelog": changelog,
        "dependencies": [],
        "game_versions": entry["game_versions"],
        "version_type": "release",
        "loaders": entry["loaders"],
        "featured": False,
        "file_parts": ["file"],
        "primary_file": "file",
    }
    if dry_run:
        print("  modrinth:", json.dumps(data))
        return
    body, content_type = multipart({"data": json.dumps(data)}, {"file": DIST / entry["file"]})
    result = request(f"{MODRINTH_API}/version", {"Authorization": os.environ["MODRINTH_TOKEN"]}, body, content_type)
    print("  modrinth: version", result["id"])


_curseforge_versions: dict[str, int] | None = None


def curseforge_version_ids(names: list[str]) -> list[int]:
    global _curseforge_versions
    if _curseforge_versions is None:
        headers = {"X-Api-Token": os.environ["CURSEFORGE_TOKEN"]}
        types = request(f"{CURSEFORGE_API}/game/version-types", headers)
        minecraft_types = {t["id"] for t in types if t["slug"].startswith("minecraft-")}
        versions = request(f"{CURSEFORGE_API}/game/versions", headers)
        _curseforge_versions = {v["name"]: v["id"] for v in versions if v["gameVersionTypeID"] in minecraft_types}
    missing = [n for n in names if n not in _curseforge_versions]
    if missing:
        raise RuntimeError(f"CurseForge has no game version for: {', '.join(missing)}")
    return [_curseforge_versions[n] for n in names]


def curseforge(entry: dict, changelog: str, dry_run: bool) -> None:
    metadata = {
        "changelog": changelog,
        "changelogType": "markdown",
        "displayName": f"Craftable Notch Apples {entry['version_number']}",
        "releaseType": "release",
    }
    if dry_run:
        print("  curseforge:", json.dumps({**metadata, "gameVersions": entry["game_versions"]}))
        return
    metadata["gameVersions"] = curseforge_version_ids(entry["game_versions"])
    body, content_type = multipart({"metadata": json.dumps(metadata)}, {"file": DIST / entry["file"]})
    project = os.environ["CURSEFORGE_PROJECT_ID"]
    result = request(
        f"{CURSEFORGE_API}/projects/{project}/upload-file", {"X-Api-Token": os.environ["CURSEFORGE_TOKEN"]}, body, content_type
    )
    print("  curseforge: file", result["id"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="print what would be uploaded")
    args = parser.parse_args()

    manifest = json.loads((DIST / "manifest.json").read_text(encoding="utf-8"))
    targets = []
    if args.dry_run or (os.environ.get("MODRINTH_TOKEN") and os.environ.get("MODRINTH_PROJECT_ID")):
        targets.append(modrinth)
    if args.dry_run or (os.environ.get("CURSEFORGE_TOKEN") and os.environ.get("CURSEFORGE_PROJECT_ID")):
        targets.append(curseforge)
    if not targets:
        print("no platform credentials set; nothing to do", file=sys.stderr)
        return 1

    for entry in manifest:
        pack_version = entry["version_number"].split("+", 1)[0]
        print(entry["file"])
        for upload in targets:
            upload(entry, changelog_for(pack_version), args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
