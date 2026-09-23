# Craftable Notch Apples

A data pack that brings back the original enchanted golden apple recipe,
which Minecraft removed in 1.9:

Works in singleplayer and on servers (vanilla, Paper, Spigot, Fabric, NeoForge,
Forge, anything that loads data packs). The data pack was made so you only need
to install it on the server - no need for players to install anything.

## Versions

Every Java release from **1.13 to 26.3** is covered.
Each download covers one pack format, so grab the one for your version:

| Minecraft | File |
|---|---|
| 1.13 - 1.14.4 | `craftable-notch-apples-<ver>+mc1.13-1.14.4.zip` |
| 1.15 - 1.16.1 | `...+mc1.15-1.16.1.zip` |
| 1.16.2 - 1.16.5 | `...+mc1.16.2-1.16.5.zip` |
| 1.17 - 1.17.1 | `...+mc1.17-1.17.1.zip` |
| 1.18 - 1.18.1 | `...+mc1.18-1.18.1.zip` |
| 1.18.2 | `...+mc1.18.2.zip` |
| 1.19 - 1.19.3 | `...+mc1.19-1.19.3.zip` |
| 1.19.4 | `...+mc1.19.4.zip` |
| 1.20 - 1.20.1 | `...+mc1.20-1.20.1.zip` |
| 1.20.2 - 1.20.4 | `...+mc1.20.2-1.20.4.zip` |
| 1.20.5 - 1.20.6 | `...+mc1.20.5-1.20.6.zip` |
| 1.21 - 1.21.1 | `...+mc1.21-1.21.1.zip` |
| 1.21.2 - 1.21.8 | `...+mc1.21.2-1.21.8.zip` |
| 1.21.9 - 26.2 | `...+mc1.21.9-26.2.zip` |
| 26.3 | `...+mc26.3.zip` |

## Building

Needs Python 3.10+. No other dependencies.

```
python build.py
```

Writes one zip per band to `dist/`, plus `dist/manifest.json` listing the game
versions of each (used for publishing). Add a `pack.png` next to `build.py` and
it goes into every zip as the pack icon.

## Testing

`test/mctest.py` boots the official server for each version with its zip in a
fresh world, checks the pack loads cleanly, then has a headless client
(mineflayer) craft the apple and confirms the server consumed the ingredients.
JDKs, server jars and ViaProxy are downloaded into `~/.cache/mctest` on first
use.

```
cd test/bot && npm ci && cd ../..
python build.py
python test/mctest.py --versions all --jobs 4
python test/mctest.py --versions 1.21.1,26.3
```

Needs Node 18+. Versions the client can't speak directly (1.13.1, 1.14.2,
26.2, 26.3) are tested through ViaProxy.

## License

[Mozilla Public License 2.0](LICENSE). Copyright (c) 2026 Tyler Fursman.
