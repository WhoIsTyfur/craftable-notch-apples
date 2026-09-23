#!/usr/bin/env python3
# Copyright (c) 2026 Tyler Fursman
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Build one data pack zip per pack-format band into dist/."""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
import zipfile
from dataclasses import dataclass

PACK_VERSION = "1.0.0"
NAMESPACE = "craftablenotchapples"
RECIPE_ID = f"{NAMESPACE}:enchanted_golden_apple"
DESCRIPTION = "Craftable Notch Apples: 8 gold blocks + 1 apple"

ROOT = pathlib.Path(__file__).resolve().parent
DIST = ROOT / "dist"
LICENSE = ROOT / "LICENSE"
ICON = ROOT / "pack.png"

# First pack format of each data format change this pack cares about.
FORMAT_1_17 = 7  # item predicates take an "items" list
FORMAT_1_19 = 10  # recipes gain "category" (1.19.3; older ones ignore it)
FORMAT_1_20_5 = 41  # results use "id"; item predicates take a bare id
FORMAT_1_21 = 48  # "recipes"/"advancements" folders drop the "s"
FORMAT_1_21_2 = 57  # ingredients become plain id strings
FORMAT_26_3 = 121  # recipe_unlocked reads "recipes" instead of "recipe"


@dataclass(frozen=True)
class Band:
    name: str
    game_versions: tuple[str, ...]
    pack_format: int | None = None
    supported_formats: tuple[int, int] | None = None
    min_format: int | None = None
    max_format: int | None = None

    @property
    def first_format(self) -> int:
        return self.pack_format if self.min_format is None else self.min_format


BANDS = (
    Band("1.13-1.14.4", ("1.13", "1.13.1", "1.13.2", "1.14", "1.14.1", "1.14.2", "1.14.3", "1.14.4"), pack_format=4),
    Band("1.15-1.16.1", ("1.15", "1.15.1", "1.15.2", "1.16", "1.16.1"), pack_format=5),
    Band("1.16.2-1.16.5", ("1.16.2", "1.16.3", "1.16.4", "1.16.5"), pack_format=6),
    Band("1.17-1.17.1", ("1.17", "1.17.1"), pack_format=7),
    Band("1.18-1.18.1", ("1.18", "1.18.1"), pack_format=8),
    Band("1.18.2", ("1.18.2",), pack_format=9),
    Band("1.19-1.19.3", ("1.19", "1.19.1", "1.19.2", "1.19.3"), pack_format=10),
    Band("1.19.4", ("1.19.4",), pack_format=12),
    Band("1.20-1.20.1", ("1.20", "1.20.1"), pack_format=15),
    Band("1.20.2-1.20.4", ("1.20.2", "1.20.3", "1.20.4"), pack_format=18, supported_formats=(18, 26)),
    Band("1.20.5-1.20.6", ("1.20.5", "1.20.6"), pack_format=41),
    Band("1.21-1.21.1", ("1.21", "1.21.1"), pack_format=48),
    Band(
        "1.21.2-1.21.8",
        ("1.21.2", "1.21.3", "1.21.4", "1.21.5", "1.21.6", "1.21.7", "1.21.8"),
        pack_format=57,
        supported_formats=(57, 81),
    ),
    Band(
        "1.21.9-26.2",
        ("1.21.9", "1.21.10", "1.21.11", "26.1", "26.1.1", "26.1.2", "26.2"),
        min_format=88,
        max_format=107,
    ),
    Band("26.3", ("26.3",), min_format=121, max_format=121),
)


def pack_mcmeta(band: Band) -> dict:
    pack: dict = {"description": DESCRIPTION}
    if band.pack_format is not None:
        pack["pack_format"] = band.pack_format
    if band.supported_formats is not None:
        pack["supported_formats"] = list(band.supported_formats)
    if band.min_format is not None:
        pack["min_format"] = band.min_format
        pack["max_format"] = band.max_format
    return {"pack": pack}


def ingredient(fmt: int, item: str):
    return item if fmt >= FORMAT_1_21_2 else {"item": item}


def recipe(fmt: int) -> dict:
    # 1.13.x only resolves the type without a namespace; later versions default it.
    data: dict = {"type": "crafting_shaped"}
    if fmt >= FORMAT_1_19:
        data["category"] = "misc"
    data["pattern"] = ["###", "#A#", "###"]
    data["key"] = {"#": ingredient(fmt, "minecraft:gold_block"), "A": ingredient(fmt, "minecraft:apple")}
    result_key = "id" if fmt >= FORMAT_1_20_5 else "item"
    data["result"] = {result_key: "minecraft:enchanted_golden_apple", "count": 1}
    return data


def item_predicate(fmt: int, item: str) -> dict:
    if fmt >= FORMAT_1_20_5:
        return {"items": item}
    if fmt >= FORMAT_1_17:
        return {"items": [item]}
    return {"item": item}


def advancement(fmt: int) -> dict:
    unlock_key = "recipes" if fmt >= FORMAT_26_3 else "recipe"
    return {
        "parent": "minecraft:recipes/root",
        "criteria": {
            "has_gold_block": {
                "trigger": "minecraft:inventory_changed",
                "conditions": {"items": [item_predicate(fmt, "minecraft:gold_block")]},
            },
            "has_the_recipe": {
                "trigger": "minecraft:recipe_unlocked",
                "conditions": {unlock_key: RECIPE_ID},
            },
        },
        "requirements": [["has_the_recipe", "has_gold_block"]],
        "rewards": {"recipes": [RECIPE_ID]},
    }


def pack_files(band: Band) -> dict[str, str]:
    fmt = band.first_format
    plural = "s" if fmt < FORMAT_1_21 else ""
    files = {
        "pack.mcmeta": pack_mcmeta(band),
        f"data/{NAMESPACE}/recipe{plural}/enchanted_golden_apple.json": recipe(fmt),
        f"data/{NAMESPACE}/advancement{plural}/recipes/food/enchanted_golden_apple.json": advancement(fmt),
    }
    return {path: json.dumps(data, indent=2) + "\n" for path, data in files.items()}


def file_name(band: Band) -> str:
    return f"craftable-notch-apples-{PACK_VERSION}+mc{band.name}.zip"


def write_zip(band: Band, target: pathlib.Path) -> None:
    entries = pack_files(band)
    entries["LICENSE"] = LICENSE.read_text(encoding="utf-8")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        # Fixed timestamps keep the zips byte-identical between builds.
        for path in sorted(entries):
            zf.writestr(zipfile.ZipInfo(path, (1980, 1, 1, 0, 0, 0)), entries[path], zipfile.ZIP_DEFLATED)
        if ICON.exists():
            zf.writestr(zipfile.ZipInfo("pack.png", (1980, 1, 1, 0, 0, 0)), ICON.read_bytes(), zipfile.ZIP_DEFLATED)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unzipped", action="store_true", help="also write each band as a plain folder")
    args = parser.parse_args()

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()

    manifest = []
    for band in BANDS:
        name = file_name(band)
        write_zip(band, DIST / name)
        if args.unzipped:
            folder = DIST / "unzipped" / band.name
            for path, text in pack_files(band).items():
                out = folder / path
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(text, encoding="utf-8", newline="\n")
        manifest.append(
            {
                "file": name,
                "version_number": f"{PACK_VERSION}+mc{band.name}",
                "game_versions": list(band.game_versions),
                "loaders": ["datapack"],
            }
        )
        print(f"{name}  ({', '.join(band.game_versions)})")

    (DIST / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
