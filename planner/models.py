"""Core data structures and the items-per-minute / clocking math.

Everything downstream (solver, reports, graph) is built on these.
All rates are items per minute unless a name says otherwise.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# In Satisfactory a machine's power scales with clock speed raised to this
# exponent.  Underclocking to 30% therefore uses 0.30 ** 1.6 of base power,
# which is much less than 30% -- that's why "underclock the last machine" is a
# real power saving, not just a cosmetic one.
OVERCLOCK_EXPONENT = 1.6


@dataclass(frozen=True)
class Recipe:
    """One recipe, exactly as written in recipes.yaml (quantities per craft)."""

    name: str
    building: str
    inputs: Dict[str, float]
    outputs: Dict[str, float]
    time: float          # seconds per craft
    alt: bool = False
    recipe_class: str = ""   # save-file id (Recipe_*_C), for mapping saves

    @property
    def primary_output(self) -> str:
        """The main product. For our data every recipe has a single output."""
        return next(iter(self.outputs))

    def output_per_min(self, item: str) -> float:
        """How many of `item` ONE building of this recipe makes per minute."""
        return self.outputs[item] * 60.0 / self.time

    def input_per_min(self, item: str) -> float:
        """How many of `item` ONE building of this recipe eats per minute."""
        return self.inputs[item] * 60.0 / self.time


@dataclass
class BuildingCount:
    """Turns a fractional building count into the two ways you'd actually build it.

    Example: you need 4.3 Constructors.
      * exact       = 4.3   (the pure number)
      * ceil        = 5     (round up to whole machines)
      * full        = 4     (run these at 100%)
      * last_clock  = 0.30  (run the 5th one at 30% to hit the exact rate)
    """

    exact: float

    @property
    def ceil(self) -> int:
        return max(1, math.ceil(round(self.exact, 9))) if self.exact > 0 else 0

    @property
    def full(self) -> int:
        """Machines running at 100%."""
        if self.exact <= 0:
            return 0
        f = math.floor(round(self.exact, 9))
        # If the count is a whole number, all machines run full, none underclocked.
        return f

    @property
    def last_clock(self) -> float:
        """Clock (0..1) for the final machine. 1.0 means no underclock needed."""
        if self.exact <= 0:
            return 0.0
        frac = round(self.exact - self.full, 9)
        return 1.0 if frac == 0 else frac

    @property
    def has_underclocked(self) -> bool:
        return self.last_clock not in (0.0, 1.0)


@dataclass
class ProductionStep:
    """One recipe's worth of production inside a solved plan."""

    item: str                       # the product this step supplies
    recipe: Recipe
    demand: float                   # items/min of `item` this step must output
    buildings: BuildingCount
    base_power: float               # MW for a single building at 100%
    # Aggregate flows for the WHOLE step (all buildings combined):
    outputs: Dict[str, float] = field(default_factory=dict)  # item -> items/min
    inputs: Dict[str, float] = field(default_factory=dict)   # item -> items/min

    @property
    def building(self) -> str:
        return self.recipe.building

    @property
    def power_exact(self) -> float:
        """Power if you could run a fractional number of machines at 100%."""
        return self.buildings.exact * self.base_power

    @property
    def power_clocked(self) -> float:
        """Power for 'round up + underclock the last machine'."""
        bc = self.buildings
        if bc.exact <= 0:
            return 0.0
        full_power = bc.full * self.base_power
        if bc.has_underclocked:
            full_power += self.base_power * (bc.last_clock ** OVERCLOCK_EXPONENT)
        return full_power


@dataclass
class ForwardResult:
    """Result of 'I want N of X per minute'."""

    target_item: str
    target_rate: float
    steps: List[ProductionStep]                 # topological, target first
    raws: Dict[str, float]                      # raw item -> items/min drawn
    recipe_choices: Dict[str, str]              # item -> recipe name used
    byproducts: Dict[str, float] = field(default_factory=dict)

    @property
    def total_power_exact(self) -> float:
        return sum(s.power_exact for s in self.steps)

    @property
    def total_power_clocked(self) -> float:
        return sum(s.power_clocked for s in self.steps)

    @property
    def total_buildings(self) -> int:
        return sum(s.buildings.ceil for s in self.steps)

    def step_for(self, item: str) -> Optional[ProductionStep]:
        for s in self.steps:
            if s.item == item:
                return s
        return None


@dataclass
class ProductLine:
    """One product's slice of a reverse solve."""

    item: str
    output: float                 # achievable items/min
    resource_used: float          # constrained resource/min consumed
    plan: ForwardResult           # full breakdown for this line at `output`


@dataclass
class ReverseResult:
    """Result of 'I have R of some resource, split across these products'."""

    resource: str
    supply: float
    lines: List[ProductLine]
    leftover: float               # resource/min left unused
    bottleneck: Optional[str]     # product that runs dry first (limits a scaled mix)
    mode: str                     # how the split was decided

    @property
    def resource_used(self) -> float:
        return sum(l.resource_used for l in self.lines)

    @property
    def total_power_clocked(self) -> float:
        return sum(l.plan.total_power_clocked for l in self.lines)

    @property
    def total_power_exact(self) -> float:
        return sum(l.plan.total_power_exact for l in self.lines)
