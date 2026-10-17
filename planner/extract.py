"""Read a Satisfactory .sav and pull out the production machines.

Output is a list of MachineGroup: one row per recipe actually running in the
save, with how many machines run it and their combined clock (so overclocking is
handled if present). Everything downstream works from these rows.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .models import OVERCLOCK_EXPONENT, Recipe
from .recipes import RecipeBook

# Make the vendored parser importable.
_VENDOR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "vendor")
if _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)


def _short(path) -> str:
    if not isinstance(path, str):
        path = getattr(path, "pathName", "") or ""
    return path.rsplit(".", 1)[-1].rsplit("/", 1)[-1]


def _ratio(props, gv, produce_key, dur_key):
    """produce/duration as a 0..1 ratio, or None if unreadable/zero."""
    try:
        pd = float(gv(props, produce_key))
        du = float(gv(props, dur_key))
    except (TypeError, ValueError):
        return None
    if du <= 0:
        return None
    return min(1.0, max(0.0, pd / du))


def _live_productivity(props, gv) -> float:
    """Fraction of time this machine has actually been producing (the in-game
    productivity %). Reads the last completed measurement window, falls back to
    the in-progress window, then to the mIsProducing flag, then assumes running."""
    r = _ratio(props, gv, "mLastProductivityMeasurementProduceDuration",
               "mLastProductivityMeasurementDuration")
    if r is not None:
        return r
    r = _ratio(props, gv, "mCurrentProductivityMeasurementProduceDuration",
               "mCurrentProductivityMeasurementDuration")
    if r is not None:
        return r
    ip = gv(props, "mIsProducing")
    if ip is not None:
        return 1.0 if ip else 0.0
    return 1.0  # no data: assume running rather than raise a false stall


@dataclass
class MachineGroup:
    recipe: Recipe
    count: int = 0                 # number of machines running this recipe
    clock_sum: float = 0.0         # Σ clock (== count if all at 100%)
    power_factor: float = 0.0      # Σ clock**1.6  (for power at any clock)
    live_sum: float = 0.0          # Σ (clock × live productivity) — actual, from the save

    @property
    def effective(self) -> float:
        """Machine-equivalents at 100% clock, full supply assumed (POTENTIAL)."""
        return self.clock_sum

    @property
    def live_productivity(self) -> float:
        """Average measured uptime across this group's machines (0..1)."""
        return (self.live_sum / self.clock_sum) if self.clock_sum else 0.0

    def output_per_min(self, item: str) -> float:
        """Potential output: nameplate × clock, assuming full supply."""
        return self.effective * self.recipe.output_per_min(item)

    def input_per_min(self, item: str) -> float:
        return self.effective * self.recipe.input_per_min(item)

    def live_output_per_min(self, item: str) -> float:
        """Actual output right now: nameplate × clock × measured productivity."""
        return self.live_sum * self.recipe.output_per_min(item)

    def live_input_per_min(self, item: str) -> float:
        return self.live_sum * self.recipe.input_per_min(item)


@dataclass
class ExtractResult:
    groups: List[MachineGroup]
    building_counts: Dict[str, int] = field(default_factory=dict)   # friendly building -> total machines
    unknown_recipes: Dict[str, int] = field(default_factory=dict)   # Recipe_*_C not in book -> count
    paused_recipes: Dict[str, int] = field(default_factory=dict)    # recipe name -> machines toggled OFF (excluded)
    session_name: str = ""


def extract_save(save_path: str, book: RecipeBook) -> ExtractResult:
    import sav_parse  # vendored

    parsed = sav_parse.readFullSaveFile(save_path)
    session = getattr(getattr(parsed, "saveFileInfo", None), "sessionName", "") or ""

    groups: Dict[str, MachineGroup] = {}       # recipe_class -> group
    building_counts: Dict[str, int] = {}
    unknown: Dict[str, int] = {}
    paused: Dict[str, int] = {}                 # recipe name -> machines toggled OFF

    for lvl in parsed.levels:
        headers = lvl.actorAndComponentObjectHeaders
        for idx, obj in enumerate(lvl.objects):
            header = headers[idx] if idx < len(headers) else None
            cls = _short(getattr(header, "typePath", None) or getattr(header, "className", "") or "")
            if not cls.startswith("Build_"):
                continue
            props = getattr(obj, "properties", None) or []
            recipe_ref = sav_parse.getPropertyValue(props, "mCurrentRecipe")
            if recipe_ref is None:
                continue  # not a production machine with a set recipe
            recipe_class = _short(recipe_ref)
            recipe = book.by_class.get(recipe_class)
            if recipe is None:
                unknown[recipe_class] = unknown.get(recipe_class, 0) + 1
                continue

            # Skip machines the player has toggled OFF (the pause/hand button).
            # BoolProperty true is stored as byte 0x10 (16); absent == running.
            if sav_parse.getPropertyValue(props, "mIsProductionPaused"):
                paused[recipe.name] = paused.get(recipe.name, 0) + 1
                continue

            # Clock speed (mCurrentPotential); default 100% if absent.
            clock = sav_parse.getPropertyValue(props, "mCurrentPotential")
            try:
                clock = float(clock)
            except (TypeError, ValueError):
                clock = 1.0
            if clock <= 0:
                clock = 1.0

            live = _live_productivity(props, sav_parse.getPropertyValue)

            g = groups.get(recipe_class)
            if g is None:
                g = groups[recipe_class] = MachineGroup(recipe=recipe)
            g.count += 1
            g.clock_sum += clock
            g.live_sum += clock * live
            g.power_factor += clock ** OVERCLOCK_EXPONENT
            building_counts[recipe.building] = building_counts.get(recipe.building, 0) + 1

    ordered = sorted(groups.values(), key=lambda g: (-g.count, g.recipe.name))
    return ExtractResult(
        groups=ordered,
        building_counts=building_counts,
        unknown_recipes=unknown,
        paused_recipes=paused,
        session_name=session,
    )
