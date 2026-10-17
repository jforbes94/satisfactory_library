"""Reconstruct the physical material-flow graph (belts + pipes) from a save.

Graph (plain dicts, no deps):
    {"nodes": {bid: {"class": "Build_X_C", "pos": [x_m, y_m, z_m], "recipe": str|None}},
     "out":   {bid: set(bid)},          # producer -> consumers
     "in":    {bid: set(bid)},          # consumer -> producers
     "kinds": {(src, dst): set("belt"|"pipe")}}
bid is the building's save instanceName.

Method
  * Index every connector component (objects having mConnectedComponent) by
    full instanceName; owner building = instanceName.rsplit('.',1)[0].
  * SOLIDS: direction is explicit in connector names. Start at each machine
    Output# connector, follow mConnectedComponent. Belts/lifts: enter via one
    ConveyorAny end, leave via the other. Splitters/mergers: enter an Input#,
    fan out through all Output#. Terminate at a machine/storage Input# -> edge.
  * FLUIDS: pipes are undirected. Union-find over pipe connectors across
    pass-through parts (pipes, junctions, pumps, valves, fluid tanks). Within
    each pipe network every producer (PipeOutput*, extractors, pumps-from-ground)
    gets an edge to every consumer (PipeInput*, FGPipeConnectionFactory on
    generators/converters/collider). This over-approximates when one network
    holds several producers and consumers (no flow-level split), and tanks are
    merged into the network rather than being nodes.
  * Power / track / hypertube connectors are ignored.
"""
from __future__ import annotations

import glob
import os
import re
import sys
from collections import defaultdict

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_ROOT, "vendor"), _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import sav_parse as sp  # noqa: E402
from planner.extract import _short  # noqa: E402

_BELT = re.compile(r"^Build_Conveyor(Belt|Lift)")
_SPLIT = re.compile(r"^Build_ConveyorAttachment(Splitter|Merger)")
_PIPE_PASS = re.compile(r"^Build_(Pipeline|Valve|IndustrialTank|PipeStorageTank)")
_PIPE_OUT_CLASSES = re.compile(r"^Build_(FrackingExtractor|OilPump|WaterPump)")


def _owner(iname):
    return iname.rsplit(".", 1)[0]


def _last(iname):
    return iname.rsplit(".", 1)[-1]


def _is_pipe_conn(name):
    return name.startswith(("Pipe", "FGPipeConnection", "Connection")) and not name.startswith(("PipeHyper", "Pipeline"))


def _is_machine_pipe_conn(name):
    return name.startswith(("PipeInput", "PipeOutput", "FGPipeConnection"))


def _is_solid_conn(name):
    return name.startswith(("Input", "Output")) and "Inventory" not in name


def build_graph(save_path, parsed=None):
    gv = sp.getPropertyValue
    if parsed is None:
        parsed = sp.readFullSaveFile(save_path)
    cls_of, pos_of, recipe_of = {}, {}, {}
    target = {}  # connector iname -> connected connector iname
    for lvl in parsed.levels:
        hs = lvl.actorAndComponentObjectHeaders
        for i, o in enumerate(lvl.objects):
            iname = getattr(o, "instanceName", "") or ""
            h = hs[i] if i < len(hs) else None
            tp = getattr(h, "typePath", "") or ""
            last = _last(iname)
            if last.startswith("Build_") and tp:
                cls_of[iname] = _short(tp)
                p = getattr(h, "position", None)
                if p is not None:
                    pos_of[iname] = [round(p[0] / 100, 1), round(p[1] / 100, 1), round(p[2] / 100, 1)]
                try:
                    r = gv(o.properties, "mCurrentRecipe")
                    if r is not None:
                        recipe_of[iname] = _short(r)
                except Exception:
                    pass
            for pr in o.properties:
                if pr[0] == "mConnectedComponent":
                    pn = getattr(pr[1], "pathName", "")
                    if pn:
                        target[iname] = pn
    conns = defaultdict(list)
    for c in target:
        conns[_owner(c)].append(c)

    def kind(b):
        c = cls_of.get(b, "")
        if _BELT.match(c):
            return "belt"
        if _SPLIT.match(c):
            return "split"
        if _PIPE_PASS.match(c):
            return "pipe"
        return "machine"

    out, inn, kinds = defaultdict(set), defaultdict(set), defaultdict(set)

    def add(a, b, k):
        if a != b:
            out[a].add(b)
            inn[b].add(a)
            kinds[(a, b)].add(k)

    # ---- solids: walk from every machine Output# through belts/splitters
    for b, cs in conns.items():
        if kind(b) != "machine" or b not in cls_of:
            continue
        for c in cs:
            if not _last(c).startswith("Output"):
                continue
            seen, stack = set(), [target[c]]
            while stack:
                t = stack.pop()
                if t in seen:
                    continue
                seen.add(t)
                ob, nm = _owner(t), _last(t)
                k = kind(ob)
                if k == "belt":
                    other = ob + "." + ("ConveyorAny1" if nm == "ConveyorAny0" else "ConveyorAny0")
                    if other in target:
                        stack.append(target[other])
                elif k == "split":
                    if nm.startswith("Input"):
                        for oc in conns[ob]:
                            if _last(oc).startswith("Output") and oc in target:
                                stack.append(target[oc])
                elif ob in cls_of and nm.startswith("Input"):
                    add(b, ob, "belt")

    # ---- fluids: union-find over pipe connectors
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    for b, cs in conns.items():
        if kind(b) == "pipe":
            for c in cs:
                union(c, cs[0])
    for c, t in target.items():
        ob, to = _owner(c), _owner(t)
        okc = kind(ob) == "pipe" or _is_machine_pipe_conn(_last(c))
        okt = kind(to) == "pipe" or _is_machine_pipe_conn(_last(t))
        if okc and okt:
            union(c, t)
    prod, cons = defaultdict(set), defaultdict(set)
    for b, cs in conns.items():
        if kind(b) != "machine" or b not in cls_of:
            continue
        for c in cs:
            nm = _last(c)
            if not _is_machine_pipe_conn(nm):
                continue
            if "Output" in nm or _PIPE_OUT_CLASSES.match(cls_of[b]):
                prod[find(c)].add(b)
            else:
                cons[find(c)].add(b)
    for net, ps in prod.items():
        for p in ps:
            for q in cons.get(net, ()):
                add(p, q, "pipe")

    nodes = {}
    for b, c in cls_of.items():
        if kind(b) == "machine" and (b in out or b in inn or any(
                _is_solid_conn(_last(x)) or _is_machine_pipe_conn(_last(x)) for x in conns.get(b, ()))):
            nodes[b] = {"class": c, "pos": pos_of.get(b), "recipe": recipe_of.get(b)}
    return {"nodes": nodes, "out": {k: set(v) for k, v in out.items()},
            "in": {k: set(v) for k, v in inn.items()}, "kinds": dict(kinds)}


def connected_components(graph):
    """Weakly connected components over buildings that have >=1 edge, largest first."""
    adj = defaultdict(set)
    for a, bs in graph["out"].items():
        for b in bs:
            adj[a].add(b)
            adj[b].add(a)
    seen, comps = set(), []
    for n in adj:
        if n in seen:
            continue
        comp, st = set(), [n]
        while st:
            x = st.pop()
            if x in comp:
                continue
            comp.add(x)
            st.extend(adj[x] - comp)
        seen |= comp
        comps.append(comp)
    return sorted(comps, key=len, reverse=True)


def feeders(graph, building):
    return set(graph["in"].get(building, ()))


def consumers(graph, building):
    return set(graph["out"].get(building, ()))


def upstream(graph, building):
    """All transitive feeders."""
    return _closure(graph["in"], building)


def downstream(graph, building):
    return _closure(graph["out"], building)


def _closure(m, s):
    seen, st = set(), [s]
    while st:
        for y in m.get(st.pop(), ()):
            if y not in seen:
                seen.add(y)
                st.append(y)
    return seen


def newest_save(d="."):
    return sorted(glob.glob(os.path.join(d, (os.environ.get("SATISFACTORY_SAVE_SESSION", "") + "*.sav"))), key=os.path.getmtime)[-1]


def _nm(g, b):
    n = g["nodes"].get(b, {})
    return "%s@%s" % (n.get("class", "?").replace("Build_", "").replace("_C", ""), n.get("pos"))


if __name__ == "__main__":
    from collections import Counter
    g = build_graph(sys.argv[1] if len(sys.argv) > 1 else newest_save(_ROOT))
    E = sum(len(v) for v in g["out"].values())
    comps = connected_components(g)
    comp_of = {b: i for i, c in enumerate(comps) for b in c}
    print("buildings", len(g["nodes"]), "edges", E,
          "belt-edges", sum(1 for k in g["kinds"].values() if "belt" in k),
          "pipe-edges", sum(1 for k in g["kinds"].values() if "pipe" in k))
    print("components", len(comps), "largest", [len(c) for c in comps[:8]])
    cc = [b for b, n in g["nodes"].items() if n["recipe"] and re.search("CompactedCoal|EnrichedCoal", n["recipe"])
          and "Assembler" in n["class"]]
    print("compacted-coal assemblers", len(cc))
    for a in cc[:3]:
        print("(a)", _nm(g, a), g["nodes"][a]["recipe"], "comp", comp_of.get(a))
        print("   direct feeders:", sorted(_nm(g, x) for x in feeders(g, a)))
        up = upstream(g, a)
        print("   upstream miners:", sorted(_nm(g, x) for x in up if "Miner" in g["nodes"][x]["class"]))
        print("   upstream size", len(up))
    miners = [b for b, n in g["nodes"].items() if "Miner" in n["class"]]
    coalm = [m for m in miners if any("Coal" in (g["nodes"][x]["recipe"] or "") or "Generator" in g["nodes"][x]["class"]
                                      for x in downstream(g, m))]
    for m in coalm[:3]:
        d = downstream(g, m)
        print("(b)", _nm(g, m), "comp", comp_of.get(m), "direct:", sorted(_nm(g, x) for x in consumers(g, m)))
        print("   downstream size", len(d), "recipes:",
              Counter(g["nodes"][x]["recipe"] for x in d if g["nodes"][x]["recipe"]).most_common(6))
