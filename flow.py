#!/usr/bin/env python
"""Per-zone MATERIAL-FLOW graph (readable, not geographic).

Collapses each manifold (N machines on the same recipe) into ONE node labelled
with its count + rate, and draws ONE aggregated edge per (source group -> dest
group -> item) instead of every individual belt. Items crossing the zone
boundary become import/export nodes, so you can read what flows in, through and
out of a zone at a glance.

Consumed by site.py; `build_zone_flow(result, zone_name)` returns (nodes, edges)
and `to_mermaid(nodes, edges)` renders a Mermaid flowchart string.
"""
import collections, re
import zone_report as zr

STORAGE_HINT = ("Storage", "FreightPlatform", "DroneStation", "TruckStation")


def _is_storage(cls):
    return any(h in cls for h in STORAGE_HINT)


def _gkey(bid, r):
    """Group key: manifolds of the same recipe collapse to one key."""
    cls = r["graph"]["nodes"][bid]["class"]
    if _is_storage(cls):
        return ("storage", "buffer")
    if cls in zr.EXTRACTOR_CLASSES:
        return ("res", r["res_at"].get(bid) or "ore")
    if cls in zr.POWER_MW:
        return ("gen", cls)
    rc = r["graph"]["nodes"][bid].get("recipe")
    if rc:
        return ("rec", rc)
    return ("cls", cls)


def _rate(key, members, r):
    kind, val = key
    if kind == "res":
        return sum(r["rate_at"].get(b, 0.0) for b in members), "/min"
    if kind == "gen":
        return sum(zr.POWER_MW[r["graph"]["nodes"][b]["class"]] * r["clock_of"].get(b, 1.0)
                   for b in members), " MW"
    if kind == "rec":
        rec = r["book"].by_class.get(val)
        if rec:
            per = rec.output_per_min(rec.primary_output)
            return sum(per * r["clock_of"].get(b, 1.0) for b in members), "/min"
    return 0.0, ""


def _label(key, members, r):
    kind, val = key
    n = len(members)
    rate, unit = _rate(key, members, r)
    if kind == "res":
        return f"{val}\n{rate:,.0f}{unit}", "res"
    if kind == "gen":
        nice = val.replace("Build_Generator", "").replace("_C", "")
        return f"{nice} gen x{n}\n{rate:,.0f}{unit}", "gen"
    if kind == "storage":
        return f"Storage x{n}", "store"
    if kind == "rec":
        rec = r["book"].by_class.get(val)
        name = rec.primary_output if rec else val.replace("Recipe_", "").replace("_C", "")
        return (f"{name} x{n}" + (f"\n{rate:,.0f}{unit}" if rate else "")), "mach"
    return f"{val.replace('Build_', '').replace('_C', '')} x{n}", "mach"


def build_zone_flow(r, zone_name):
    g = r["graph"]; book = r["book"]
    zone_of = r["zone_of"]
    bids = set(r["zones"][zone_name]["bids"])

    gkey = {b: _gkey(b, r) for b in bids}
    members = collections.defaultdict(list)
    for b in bids:
        members[gkey[b]].append(b)

    # aggregate edges at group level (+ import/export boundary nodes)
    gedges = collections.Counter()     # (srckey, dstkey, item) -> count
    used = set()
    for (a, b) in g["kinds"]:
        a_in, b_in = a in bids, b in bids
        if not a_in and not b_in:
            continue
        item = zr.primary_output(a, g, book, r["res_at"]) or ""
        if item in ("(storage)",):
            item = ""
        if a_in and b_in:
            ka, kb = gkey[a], gkey[b]
            if ka == kb:
                continue  # internal manifold wiring -> hidden
            gedges[(ka, kb, item)] += 1
            used.add(ka); used.add(kb)
        elif a_in and not b_in:
            dz = zone_of.get(b) or "elsewhere"
            ka = gkey[a]
            gedges[(ka, ("export", item or "mixed", dz), item)] += 1
            used.add(ka)
        elif b_in and not a_in:
            sz = zone_of.get(a) or "elsewhere"
            kb = gkey[b]
            gedges[(("import", item or "mixed", sz), kb, item)] += 1
            used.add(kb)

    # nodes: every group that participates in an edge, plus boundary nodes
    nodes = {}
    _n = [0]
    def nid(key):
        _n[0] += 1
        return "n%d" % _n[0]

    ids = {}
    for key in used:
        if key[0] in ("import", "export"):
            continue
        ids[key] = nid(key)
        nodes[ids[key]] = _label(key, members[key], r)

    edges = []
    for (src, dst, item), cnt in gedges.items():
        # realise boundary nodes lazily
        for side in (src, dst):
            if side[0] in ("import", "export") and side not in ids:
                ids[side] = nid(side)
                arrow = "⇤" if side[0] == "import" else "⇥"
                zlabel = side[2]
                nodes[ids[side]] = (f"{arrow} {side[1]}\n({'from' if side[0]=='import' else 'to'} {zlabel})",
                                    "io")
        edges.append((ids[src], ids[dst], item))
    return nodes, edges


_SHAPE = {  # (open, close) by node class
    "res": ("([", "])"), "gen": ("{{", "}}"), "store": ("[(", ")]"),
    "io": (">", "]"), "mach": ("[", "]"),
}


def _mm_text(s):
    return s.replace('"', "'").replace("\n", "<br/>")


def to_mermaid(nodes, edges):
    lines = ["flowchart LR"]
    for nodeid, (label, cls) in nodes.items():
        o, c = _SHAPE.get(cls, ("[", "]"))
        lines.append(f'  {nodeid}{o}"{_mm_text(label)}"{c}:::{cls}')
    seen = set()
    for src, dst, item in edges:
        k = (src, dst, item)
        if k in seen:
            continue
        seen.add(k)
        if item:
            lines.append(f'  {src} -->|"{_mm_text(item)}"| {dst}')
        else:
            lines.append(f"  {src} --> {dst}")
    lines += [
        "  classDef res fill:#b36a2b,stroke:#0006,color:#fff;",
        "  classDef gen fill:#d4a017,stroke:#0006,color:#1b2028;",
        "  classDef store fill:#7a8699,stroke:#0006,color:#fff;",
        "  classDef io fill:#c05617,stroke:#0006,color:#fff;",
        "  classDef mach fill:#2f7fd6,stroke:#0006,color:#fff;",
    ]
    return "\n".join(lines)
