# satisfactory_library

A Python toolkit that reads a **Satisfactory** save file and analyses your
factory — production balance, bottlenecks, a spatial zone map, and the real
belt/pipe connection graph between machines.

Everything is computed from the save plus the game's recipe data. No mods, no
in-game overlay — just point it at a `.sav`.

## What it does

| Tool | Output |
|---|---|
| `factory_report.py` | `factory_graph.html` — production graph, per-item supply %, bottleneck ranking, per-line potential-vs-live efficiency, plus `MATH.md` showing every formula. |
| `map_report.py` | `resource_map.html` — top-down map of every building by world position, auto-grouped into labelled zones. |
| `zone_report.py` | Per-zone breakdown from the **actual wiring**: extraction by resource (potential vs live), power, what each zone produces, and imports/exports that cross a zone boundary on a belt/pipe. |
| `validate.py` | Invariant checks across all three data layers (resolution, graph consistency, conservation). |
| `sync_save.py` | Copies the newest save out of your game folder into the repo and builds the report. |

## The data layers

1. **`planner/extract.py` + `recipes.yaml`** — maps each running machine to its
   recipe and turns counts × clock × live-uptime into items/minute. Add new
   recipes by editing `recipes.yaml` only.
2. **`planner/nodes.py` + `planner/node_data.py`** — resolves every miner / pump
   to its node's **resource + purity + exact rate**. Purity is not stored in the
   save, so it comes from a static map table (see Credits).
3. **`planner/topology.py`** — reconstructs the directed **machine→machine flow
   graph** from belt/pipe connector references, and finds isolated sub-networks.

`zone_report.py` fuses all three so a question like "how much coal leaves this
area, and is it node-limited or belt-limited?" is a single line of output.

## Setup

Requires Python 3.11+ and PyYAML (`pip install pyyaml`).

Tell the tools where your saves live (defaults to the standard Windows location):

```
# Windows PowerShell
$env:SATISFACTORY_SAVE_DIR = "$env:LOCALAPPDATA\FactoryGame\Saved"
$env:SATISFACTORY_SAVE_SESSION = "MySession"   # optional: only pull saves starting with this
```

Or pass paths directly:

```
python sync_save.py --source "D:\path\to\SaveGames" --session "MySession"
```

## Usage

```
python sync_save.py              # pull newest save + build factory_graph.html
python factory_report.py         # (re)build the report from the newest .sav here
python map_report.py             # build resource_map.html
python zone_report.py            # per-zone report (uses zones.yaml if present)
python validate.py               # run the invariant checks
```

For named zones, copy `zones.example.yaml` to `zones.yaml` and set your own
centers (run `zone_report.py` once with no `zones.yaml` to see auto-detected
cluster centers to name).

## Credits & license

Save parsing and the resource-node/purity data come from
**[GreyHak/sat_sav_parse](https://github.com/GreyHak/sat_sav_parse)** (GPL-3.0),
vendored under `vendor/`. Node purity data was extracted from the Satisfactory
Interactive Map (SCIM). Because that code is GPL-3.0, this project is distributed
under the **GNU GPL-3.0** as well; see `LICENSE`.

Recipe numbers are verified against the official
[Satisfactory wiki](https://satisfactory.wiki.gg/). Satisfactory is a game by
Coffee Stain Studios; this is an unofficial fan tool.
