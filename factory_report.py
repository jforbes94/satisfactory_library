#!/usr/bin/env python
"""Read a Satisfactory save and write a factory graph + bottleneck report.

Usage:
    python factory_report.py "MySave.sav"
    python factory_report.py            # auto-picks the newest .sav here

Writes:
    factory_graph.html   -- open in any browser (self-contained, offline)
    MATH.md              -- the formulas, in plain text
"""
import glob
import os
import sys

from planner.recipes import RecipeBook
from planner.extract import extract_save
from planner.analysis import analyze
from planner.render import render_html, render_math_md

HERE = os.path.dirname(os.path.abspath(__file__))


def pick_save(arg: str | None) -> str:
    if arg:
        return arg
    saves = sorted(glob.glob(os.path.join(HERE, "*.sav")), key=os.path.getmtime)
    if not saves:
        sys.exit("No .sav file given and none found in this folder.")
    return saves[-1]


def run(save: str) -> dict:
    """Read one save, write factory_graph.html + MATH.md, return the analysis."""
    print(f"Reading {os.path.basename(save)} ...")

    book = RecipeBook.load()
    extract = extract_save(save, book)
    if extract.unknown_recipes:
        print(f"  note: {len(extract.unknown_recipes)} recipe(s) not in recipes.yaml "
              f"(add them there): {', '.join(extract.unknown_recipes)}")
    if extract.paused_recipes:
        total_paused = sum(extract.paused_recipes.values())
        detail = ", ".join(f"{n}x {r}" for r, n in
                           sorted(extract.paused_recipes.items(), key=lambda kv: -kv[1]))
        print(f"  skipped {total_paused} paused machine(s) (toggled off): {detail}")
    analysis = analyze(book, extract)

    html_path = os.path.join(HERE, "factory_graph.html")
    math_path = os.path.join(HERE, "MATH.md")
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(render_html(analysis, book, os.path.basename(save)))
    with open(math_path, "w", encoding="utf-8") as fh:
        fh.write(render_math_md(analysis, book))

    bn = analysis["bottlenecks"]
    print(f"  {sum(analysis['building_counts'].values())} machines, "
          f"{analysis['lines_total']} recipes, "
          f"{analysis['lines_starved']} starved lines, "
          f"{analysis['total_power']:.0f} MW")
    if bn:
        top = bn[0]
        print(f"  biggest bottleneck: {top['item']} at {round(top['ratio']*100)}% "
              f"({top['deficit']:.0f}/min short)")
    print(f"Wrote {html_path}")
    print(f"Wrote {math_path}")
    return analysis


def main() -> None:
    save = pick_save(sys.argv[1] if len(sys.argv) > 1 else None)
    run(save)


if __name__ == "__main__":
    main()
