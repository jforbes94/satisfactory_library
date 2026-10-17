"""Load recipes.yaml into a queryable RecipeBook.

The book is the single source of truth about what each recipe makes and costs.
It also knows which items are RAW (consumed somewhere but produced by no recipe).
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional

import yaml

from .models import Recipe

DEFAULT_RECIPES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "recipes.yaml"
)


class RecipeError(Exception):
    pass


class RecipeBook:
    def __init__(self, recipes: List[Recipe], building_power: Dict[str, float],
                 raw_overrides: Optional[set] = None):
        self.recipes = recipes
        self.building_power = building_power
        # items always treated as raw (from extractors) even if a byproduct makes them
        self.raw_overrides = set(raw_overrides or ())

        self.by_name: Dict[str, Recipe] = {}
        self.by_class: Dict[str, Recipe] = {}
        self.producers: Dict[str, List[Recipe]] = {}   # item -> recipes making it
        self.consumers: Dict[str, List[Recipe]] = {}   # item -> recipes using it

        for r in recipes:
            if r.name in self.by_name:
                raise RecipeError(f"Duplicate recipe name: {r.name}")
            self.by_name[r.name] = r
            if r.recipe_class:
                self.by_class[r.recipe_class] = r
            for item in r.outputs:
                self.producers.setdefault(item, []).append(r)
            for item in r.inputs:
                self.consumers.setdefault(item, []).append(r)

    # ---- construction ----
    @classmethod
    def load(cls, path: str = DEFAULT_RECIPES_PATH) -> "RecipeBook":
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if not data or "recipes" not in data:
            raise RecipeError(f"No 'recipes' key in {path}")

        building_power = dict(data.get("buildings", {}))
        raw_overrides = set(data.get("raw_items", []) or [])
        recipes: List[Recipe] = []
        for i, rd in enumerate(data["recipes"]):
            try:
                recipes.append(
                    Recipe(
                        name=rd["name"],
                        building=rd["building"],
                        inputs={k: float(v) for k, v in (rd.get("inputs") or {}).items()},
                        outputs={k: float(v) for k, v in (rd.get("outputs") or {}).items()},
                        time=float(rd["time"]),
                        alt=bool(rd.get("alt", False)),
                        recipe_class=str(rd.get("class", "")),
                    )
                )
            except KeyError as e:
                raise RecipeError(f"Recipe #{i} missing field {e}") from e
        return cls(recipes, building_power, raw_overrides)

    # ---- queries ----
    def power_for(self, building: str) -> float:
        """Base MW for a building; 0 (with no crash) if unknown."""
        return float(self.building_power.get(building, 0.0))

    def is_raw(self, item: str) -> bool:
        """Raw = mined/foraged/extracted. True if nothing produces it, OR it's in
        raw_items (e.g. Water: byproduct of Aluminum Scrap but supplied by extractors)."""
        return item in self.raw_overrides or item not in self.producers

    @property
    def all_items(self) -> set:
        items = set(self.producers) | set(self.consumers)
        return items

    @property
    def raw_items(self) -> set:
        return {it for it in self.all_items if self.is_raw(it)}
