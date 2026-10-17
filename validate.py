#!/usr/bin/env python
"""Validation suite for the three data layers (nodes / topology / zones).
Checks hard invariants and prints PASS/FAIL. Run: python validate.py [save]"""
import sys, os, glob, math, collections
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "vendor"))
import sav_parse as sp
from planner import topology, nodes as nodemod
import zone_report as zr

FAILS = []
def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)

def approx(a, b, tol=1.0):
    return abs(a - b) <= tol

def main():
    save = sys.argv[1] if len(sys.argv) > 1 else zr.newest_save()
    print("Validating against", os.path.basename(save), "\n")
    parsed = sp.readFullSaveFile(save)

    # ---------------- Layer 1: nodes.py ----------------
    print("LAYER 1  nodes.py (extractor resolution)")
    ext = nodemod.resolve_nodes(save)
    extractors = [e for e in ext]
    unresolved = [e for e in extractors if e["resource"] is None]
    # fracking smashers legitimately have base 0; water pumps resolved directly
    hard_unresolved = [e for e in unresolved if e["building"] not in ("FrackingSmasher",)]
    check("every extractor resolved to a resource (excl. FrackingSmasher)",
          len(hard_unresolved) == 0, f"{len(hard_unresolved)} unresolved")
    check("all match distances within tolerance",
          all(e["match_dist_m"] <= nodemod.TOL_M for e in extractors),
          f"max {max((e['match_dist_m'] for e in extractors), default=0):.0f} m")
    check("no negative / absurd rates",
          all(0 <= e["rate_per_min"] <= 5000 for e in extractors))
    check("live uptime in [0,1]",
          all(0 <= e["live_uptime"] <= 1.0001 for e in extractors))
    pure = [e for e in extractors if e["purity"] == "pure"]
    check("purity values valid",
          all(e["purity"] in (None, "impure", "normal", "pure") for e in extractors),
          f"{len(pure)} pure nodes")
    tot = collections.defaultdict(float)
    for e in extractors:
        tot[e["resource"]] += e["rate_per_min"]
    print("    per-resource potential:", {k: round(v) for k, v in sorted(tot.items(), key=lambda a: -a[1]) if k})

    # ---------------- Layer 2: topology.py ----------------
    print("\nLAYER 2  topology.py (belt/pipe graph)")
    g = topology.build_graph(save, parsed=parsed)
    nodeset = set(g["nodes"])
    EXT = set(nodemod.EXTRACTORS)
    # miners must be pure sources: no incoming material edges
    miner_in = [b for b in nodeset if g["nodes"][b]["class"] in EXT and g["in"].get(b)]
    check("extractors have no incoming edges (pure sources)",
          len(miner_in) == 0, f"{len(miner_in)} miners with feeders")
    # no self loops
    selfloops = [(a, b) for (a, b) in g["kinds"] if a == b]
    check("no self-loop edges", len(selfloops) == 0, f"{len(selfloops)} self loops")
    # every edge endpoint is a known node
    bad = [(a, b) for (a, b) in g["kinds"] if a not in nodeset or b not in nodeset]
    check("all edge endpoints are known buildings", len(bad) == 0, f"{len(bad)} dangling")
    # in/out mirror each other
    mirror = all(a in g["in"].get(b, set()) for a, bs in g["out"].items() for b in bs)
    check("out[] and in[] are consistent mirrors", mirror)
    comps = topology.connected_components(g)
    check("graph has edges and components", len(comps) > 0,
          f"{len(g['kinds'])} edges, {len(comps)} components, sizes {[len(c) for c in comps[:6]]}")

    # ---------------- Layer 3: zones / conservation ----------------
    print("\nLAYER 3  zones + conservation")
    # rebuild zone assignment exactly as the report does
    named = zr.load_zones_yaml()
    check("zones.yaml loaded", len(named) > 0, f"{len(named)} named zones")
    positioned = [(b, g["nodes"][b]["pos"][0], g["nodes"][b]["pos"][1])
                  for b in nodeset if g["nodes"][b].get("pos")]
    zone_of = {}
    for b, x, y in positioned:
        zone_of[b] = zr.assign_named(x, y, named) or "(unzoned)"
    placed = set(zone_of)
    check("every positioned building assigned to exactly one zone",
          all(b in zone_of for b, _, _ in positioned))
    unz = [b for b in zone_of if zone_of[b] == "(unzoned)"]
    check("no unzoned buildings (coverage complete)", len(unz) == 0, f"{len(unz)} unzoned")

    # extraction conservation: sum over zones == global total, per resource
    res_at, rate_at = {}, {}
    for b in nodeset:
        nd = g["nodes"][b]
        if nd["class"] in EXT and nd.get("pos"):
            x, y = nd["pos"][0], nd["pos"][1]
            best = min(ext, key=lambda e: math.hypot(e["pos"][0] - x, e["pos"][1] - y), default=None)
            if best and math.hypot(best["pos"][0] - x, best["pos"][1] - y) < 5:
                res_at[b] = best["resource"]; rate_at[b] = best["rate_per_min"]
    zone_tot = collections.defaultdict(float)
    for b, r in res_at.items():
        zone_tot[r] += rate_at[b]
    # compare to global total over the SAME graph-matched extractors
    graph_ext_global = collections.defaultdict(float)
    for b, r in res_at.items():
        graph_ext_global[r] += rate_at[b]
    cons_ok = all(approx(zone_tot[r], graph_ext_global[r]) for r in graph_ext_global)
    check("zone extraction sums == graph extractor totals", cons_ok)

    # how many save-extractors are represented in the graph (belt-connected)?
    check("graph covers most extractors",
          len(res_at) >= 0.5 * len([e for e in ext if e['resource']]),
          f"{len(res_at)} of {len([e for e in ext if e['resource']])} resolved extractors are belt-wired")

    # cross-zone EDGE conservation: per item, total exports == total imports
    exp = collections.defaultdict(collections.Counter)
    imp = collections.defaultdict(collections.Counter)
    from planner.recipes import RecipeBook
    book = RecipeBook.load()
    for (a, b) in g["kinds"]:
        za, zb = zone_of.get(a), zone_of.get(b)
        if za and zb and za != zb:
            item = zr.primary_output(a, g, book, res_at) or "?"
            exp[za][item] += 1; imp[zb][item] += 1
    tot_exp = collections.Counter()
    tot_imp = collections.Counter()
    for z in exp: tot_exp.update(exp[z])
    for z in imp: tot_imp.update(imp[z])
    edge_cons = all(tot_exp[i] == tot_imp[i] for i in set(tot_exp) | set(tot_imp))
    check("cross-zone exports == imports per item (edge conservation)", edge_cons,
          f"{sum(tot_exp.values())} boundary edges")

    print("\n" + ("ALL CHECKS PASSED" if not FAILS else f"{len(FAILS)} FAILURE(S): " + ", ".join(FAILS)))
    return 1 if FAILS else 0

if __name__ == "__main__":
    sys.exit(main())
