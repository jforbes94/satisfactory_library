"""Balance, efficiency, and bottleneck math for a set of running machines.

ALL FORMULAS ARE DOCUMENTED HERE and mirrored to the user in MATH.md / the HTML.

  rate(item)         = qty_per_craft * 60 / craft_time_s          (items / min)
  produced[item]     = Σ over producers (machines * rate_out(item))
  consumed[item]     = Σ over consumers (machines * rate_in(item))
  balance[item]      = produced - consumed
  supply_ratio[item] = produced / consumed         (>=1 is healthy)
  efficiency(line)   = min(1, min over its inputs of supply_ratio[input])
                       raw inputs (ore, etc.) are assumed fully supplied.
  power(line)        = base_MW * Σ clock**1.6       (underclock saves power)

Efficiency is FIRST-ORDER: a line is limited by its most-starved input, using
each input's nameplate production. It does not cascade multi-hop starvation
(e.g. a starved Stator line still counts its full nameplate toward the Motor);
that keeps the number simple and explainable. Noted wherever it's reported.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional

from .extract import ExtractResult, MachineGroup
from .recipes import RecipeBook


def _round(x: float, n: int = 3) -> float:
    return round(x + 0.0, n)


def analyze(book: RecipeBook, extract: ExtractResult) -> dict:
    groups: List[MachineGroup] = extract.groups

    produced: Dict[str, float] = {}
    consumed: Dict[str, float] = {}
    live_produced: Dict[str, float] = {}   # actual output right now (× measured uptime)
    live_consumed: Dict[str, float] = {}
    # Which present recipe produces each item (for wiring edges & fixes).
    producer_of: Dict[str, MachineGroup] = {}

    for g in groups:
        for item in g.recipe.outputs:
            produced[item] = produced.get(item, 0.0) + g.output_per_min(item)
            live_produced[item] = live_produced.get(item, 0.0) + g.live_output_per_min(item)
            # prefer the bigger producer if an item has several
            if item not in producer_of or g.output_per_min(item) > producer_of[item].output_per_min(item):
                producer_of[item] = g
        for item in g.recipe.inputs:
            consumed[item] = consumed.get(item, 0.0) + g.input_per_min(item)
            live_consumed[item] = live_consumed.get(item, 0.0) + g.live_input_per_min(item)

    all_items = set(produced) | set(consumed)

    supply_ratio: Dict[str, float] = {}
    balance: Dict[str, float] = {}
    for it in all_items:
        p = produced.get(it, 0.0)
        c = consumed.get(it, 0.0)
        balance[it] = p - c
        if c <= 1e-9:
            supply_ratio[it] = math.inf
        else:
            supply_ratio[it] = p / c

    def avail_ratio(item: str) -> float:
        """How much of an input is actually available (1.0 for raws)."""
        if book.is_raw(item):
            return 1.0
        return min(1.0, supply_ratio.get(item, math.inf))

    # ---- per-line efficiency ----
    group_eff: Dict[str, float] = {}
    for g in groups:
        if not g.recipe.inputs:
            group_eff[g.recipe.name] = 1.0
            continue
        group_eff[g.recipe.name] = min(avail_ratio(i) for i in g.recipe.inputs)

    # Two honest efficiency numbers, because one alone misleads:
    #  * bulk_eff  : weighted by each line's nameplate output. Reflects "how much
    #                of total item-throughput is realized" -- but high-volume base
    #                items (screws, ingots) dominate and hide starved end products.
    #  * mean_eff  : plain average across lines. Every line counts equally, so a
    #                starved Motor line drags it down like a starved Screw line.
    num = den = 0.0
    for g in groups:
        w = g.output_per_min(g.recipe.primary_output)
        num += group_eff[g.recipe.name] * w
        den += w
    bulk_eff = (num / den) if den else 1.0
    mean_eff = (sum(group_eff.values()) / len(group_eff)) if group_eff else 1.0
    lines_total = len(groups)
    lines_starved = sum(1 for v in group_eff.values() if v < 0.999)

    # ---- power ----
    group_power: Dict[str, float] = {}
    total_power = 0.0
    for g in groups:
        mw = book.power_for(g.recipe.building) * g.power_factor
        group_power[g.recipe.name] = mw
        total_power += mw

    # ---- bottlenecks ----
    bottlenecks = []
    for it in all_items:
        if book.is_raw(it):
            continue
        c = consumed.get(it, 0.0)
        p = produced.get(it, 0.0)
        if c <= 1e-9 or p >= c - 1e-6:
            continue  # not consumed, or fully supplied
        deficit = c - p
        starves = sorted(
            g.recipe.name for g in groups if it in g.recipe.inputs
        )
        # smallest fix: how many more machines of the producing recipe
        prod_group = producer_of.get(it)
        if prod_group is not None:
            per_machine = prod_group.recipe.output_per_min(it)
            recipe_name = prod_group.recipe.name
            building = prod_group.recipe.building
            have = prod_group.count
        else:
            # nobody makes it yet -> propose the book's standard recipe
            book_producers = [r for r in book.producers.get(it, []) if not r.alt]
            r = (book_producers or book.producers.get(it, [None]))[0]
            per_machine = r.output_per_min(it) if r else 0.0
            recipe_name = r.name if r else it
            building = r.building if r else "?"
            have = 0
        need_more = math.ceil(deficit / per_machine) if per_machine > 0 else 0
        bottlenecks.append({
            "item": it,
            "produced": _round(p, 2),
            "consumed": _round(c, 2),
            "deficit": _round(deficit, 2),
            "ratio": _round(supply_ratio[it], 3),
            "starves": starves,
            "producer_present": prod_group is not None,
            "fix_recipe": recipe_name,
            "fix_building": building,
            "fix_have": have,
            "fix_add": need_more,
            "fix_gain": _round(need_more * per_machine, 2),
        })
    # worst ratio first; tie-break by larger deficit
    bottlenecks.sort(key=lambda b: (b["ratio"], -b["deficit"]))

    # ---- per-line rows: potential vs live, side by side ----
    lines = []
    for g in groups:
        out_item = g.recipe.primary_output
        lines.append({
            "name": g.recipe.name,
            "building": g.recipe.building,
            "count": g.count,
            "clock": _round(g.clock_sum / g.count, 3) if g.count else 1.0,
            "potential_out": _round(g.output_per_min(out_item), 2),
            "live_out": _round(g.live_output_per_min(out_item), 2),
            "design_eff": _round(group_eff[g.recipe.name], 3),   # supply-limited ceiling
            "live_prod": _round(g.live_productivity, 3),          # measured uptime
            "power": _round(group_power[g.recipe.name], 2),
        })
    # worst measured uptime first, so stalls float to the top
    lines.sort(key=lambda r: (r["live_prod"], r["design_eff"]))

    live_total = sum(l["live_out"] for l in lines)
    pot_total = sum(l["potential_out"] for l in lines)
    lines_stalled = sum(1 for l in lines if l["live_prod"] < 0.999)

    # ---- graph nodes & edges ----
    nodes = _build_nodes(book, groups, produced, consumed, supply_ratio,
                         group_eff, group_power, producer_of)
    edges = _build_edges(book, groups, producer_of, produced)
    _assign_layers(nodes, edges)
    metrics = _graph_metrics(nodes, edges)
    item_flows = _item_flows(book, groups, produced, consumed)

    return {
        "produced": produced,
        "consumed": consumed,
        "live_produced": live_produced,
        "live_consumed": live_consumed,
        "lines": lines,
        "lines_stalled": lines_stalled,
        "live_total": live_total,
        "pot_total": pot_total,
        "balance": balance,
        "supply_ratio": supply_ratio,
        "group_eff": group_eff,
        "bulk_eff": bulk_eff,
        "mean_eff": mean_eff,
        "lines_total": lines_total,
        "lines_starved": lines_starved,
        "group_power": group_power,
        "total_power": total_power,
        "bottlenecks": bottlenecks,
        "metrics": metrics,
        "item_flows": item_flows,
        "nodes": nodes,
        "edges": edges,
        "building_counts": extract.building_counts,
        "unknown_recipes": extract.unknown_recipes,
        "paused_recipes": extract.paused_recipes,
        "session": extract.session_name,
    }


def _item_flows(book, groups, produced, consumed) -> List[dict]:
    """Per-item breakdown: who MAKES it and who USES it, with rates. Sorted so the
    most-flowing items come first."""
    items = sorted(set(produced) | set(consumed))
    flows = []
    for it in items:
        makers = [{"recipe": g.recipe.name, "count": g.count,
                   "rate": _round(g.output_per_min(it), 1)}
                  for g in groups if it in g.recipe.outputs]
        users = [{"recipe": g.recipe.name, "count": g.count,
                  "rate": _round(g.input_per_min(it), 1)}
                 for g in groups if it in g.recipe.inputs]
        makers.sort(key=lambda r: -r["rate"])
        users.sort(key=lambda r: -r["rate"])
        p = produced.get(it, 0.0); c = consumed.get(it, 0.0)
        flows.append({
            "item": it,
            "made": _round(p, 1), "used": _round(c, 1), "net": _round(p - c, 1),
            "raw": book.is_raw(it),
            "makers": makers, "users": users,
        })
    flows.sort(key=lambda f: -(f["made"] + f["used"]))
    return flows


def _graph_metrics(nodes: List[dict], edges: List[dict]) -> dict:
    """Graph-theory measurements the report features (with tooltips in the HTML)."""
    by_id = {n["id"]: n for n in nodes}
    out_deg: Dict[str, int] = {n["id"]: 0 for n in nodes}
    in_deg: Dict[str, int] = {n["id"]: 0 for n in nodes}
    preds: Dict[str, List[str]] = {n["id"]: [] for n in nodes}
    succ_labels: Dict[str, set] = {n["id"]: set() for n in nodes}
    for e in edges:
        if e["from"] in by_id and e["to"] in by_id:
            out_deg[e["from"]] += 1
            in_deg[e["to"]] += 1
            preds[e["to"]].append(e["from"])
            succ_labels[e["from"]].add(by_id[e["to"]]["label"])

    # sources = raw inputs (mined/foraged); sinks = final products (feed nothing).
    # Gap nodes (craftable but unbuilt) also have in-degree 0 but aren't sources.
    sources = sorted(by_id[i]["label"] for i in by_id if by_id[i]["kind"] == "raw")
    gaps = sorted(by_id[i]["label"] for i in by_id if by_id[i]["kind"] == "gap")
    sinks = sorted(by_id[i]["label"] for i in by_id
                   if out_deg[i] == 0 and by_id[i]["kind"] == "recipe")

    # biggest hub = node feeding the most DISTINCT lines (out-degree, deduped)
    hub_id = max(by_id, key=lambda i: len(succ_labels[i])) if by_id else None
    hub = None
    if hub_id is not None and len(succ_labels[hub_id]) > 0:
        hub = {
            "label": by_id[hub_id]["label"],
            "out_degree": len(succ_labels[hub_id]),
            "feeds": sorted(succ_labels[hub_id]),
        }

    # longest chain (deepest raw->product path) -- reconstruct the actual path
    depth = max((n["layer"] for n in nodes), default=0)
    path: List[str] = []
    deepest = max(nodes, key=lambda n: n["layer"], default=None)
    if deepest is not None:
        cur = deepest["id"]
        seen = set()
        while cur is not None and cur not in seen:
            seen.add(cur)
            path.append(by_id[cur]["label"])
            ps = preds.get(cur, [])
            cur = max(ps, key=lambda p: by_id[p]["layer"]) if ps else None
        path.reverse()

    # connected components (undirected) -- separate sub-factories
    parent = {i: i for i in by_id}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in edges:
        if e["from"] in parent and e["to"] in parent:
            ra, rb = find(e["from"]), find(e["to"])
            if ra != rb:
                parent[ra] = rb
    comp: Dict[str, List[str]] = {}
    for i in by_id:
        comp.setdefault(find(i), []).append(i)
    components = []
    for members in comp.values():
        recipe_labels = sorted(by_id[m]["label"] for m in members
                               if by_id[m]["kind"] == "recipe")
        components.append({"size": len(members), "recipes": recipe_labels})
    components.sort(key=lambda c: -c["size"])

    return {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "sources": sources,
        "sinks": sinks,
        "hub": hub,
        "depth": depth,
        "longest_path": path,
        "components": components,
        "out_degree": out_deg,
        "in_degree": in_deg,
    }


def _node_id(kind: str, key: str) -> str:
    return f"{kind}:{key}"


def _build_nodes(book, groups, produced, consumed, supply_ratio,
                 group_eff, group_power, producer_of) -> List[dict]:
    nodes: List[dict] = []

    # raw source nodes (items consumed that nothing produces)
    raws = sorted({i for g in groups for i in g.recipe.inputs if book.is_raw(i)})
    for it in raws:
        nodes.append({
            "id": _node_id("raw", it), "kind": "raw", "label": it,
            "rate": _round(consumed.get(it, 0.0), 1),
        })

    # gap nodes: consumed, craftable, but produced by no present machine
    consumed_items = {i for g in groups for i in g.recipe.inputs}
    for it in sorted(consumed_items):
        if book.is_raw(it):
            continue
        if it not in producer_of:  # craftable but nobody builds it
            nodes.append({
                "id": _node_id("gap", it), "kind": "gap", "label": it,
                "needed": _round(consumed.get(it, 0.0), 1),
            })

    # recipe nodes
    for g in groups:
        item = g.recipe.primary_output
        is_product = supply_ratio.get(item, math.inf) == math.inf or consumed.get(item, 0.0) <= 1e-9
        eff = group_eff[g.recipe.name]
        nodes.append({
            "id": _node_id("r", g.recipe.name),
            "kind": "recipe",
            "label": g.recipe.name,
            "building": g.recipe.building,
            "count": g.count,
            "product": item,
            "out": _round(g.output_per_min(item), 1),
            "eff": _round(eff, 3),
            "power": _round(group_power[g.recipe.name], 1),
            "is_product": bool(is_product),
        })
    return nodes


def _build_edges(book, groups, producer_of, produced) -> List[dict]:
    # All present producers of an item, so shared items (e.g. Biomass from
    # Leaves/Wood/Mycelia) connect to every consumer, not just the biggest one.
    producers_by_item: Dict[str, List[MachineGroup]] = {}
    for g in groups:
        for it in g.recipe.outputs:
            producers_by_item.setdefault(it, []).append(g)

    edges: List[dict] = []
    for g in groups:
        dst = _node_id("r", g.recipe.name)
        for it in g.recipe.inputs:
            demand = g.input_per_min(it)
            if book.is_raw(it):
                edges.append({"from": _node_id("raw", it), "to": dst,
                              "item": it, "rate": _round(demand, 1)})
            elif it in producers_by_item:
                prods = producers_by_item[it]
                total = sum(p.output_per_min(it) for p in prods) or 1.0
                for p in prods:  # split demand across producers by their share
                    share = p.output_per_min(it) / total
                    edges.append({"from": _node_id("r", p.recipe.name), "to": dst,
                                  "item": it, "rate": _round(demand * share, 1)})
            else:
                edges.append({"from": _node_id("gap", it), "to": dst,
                              "item": it, "rate": _round(demand, 1)})
    return edges


def _assign_layers(nodes: List[dict], edges: List[dict]) -> None:
    """Longest-path layering: raw/gap = 0, each recipe = 1 + max(input layer)."""
    incoming: Dict[str, List[str]] = {n["id"]: [] for n in nodes}
    for e in edges:
        if e["to"] in incoming and e["from"] in incoming:
            incoming[e["to"]].append(e["from"])

    layer: Dict[str, int] = {}

    def compute(nid: str, stack: set) -> int:
        if nid in layer:
            return layer[nid]
        if nid in stack:  # cycle guard (shouldn't happen)
            return 0
        stack.add(nid)
        preds = incoming.get(nid, [])
        lv = 0 if not preds else 1 + max(compute(p, stack) for p in preds)
        stack.discard(nid)
        layer[nid] = lv
        return lv

    for n in nodes:
        n["layer"] = compute(n["id"], set())
