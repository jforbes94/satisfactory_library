#!/usr/bin/env python
"""ZONE REPORT -- the unified understanding layer.

Fuses the three data layers:
  * planner/topology.py  -- real belt/pipe machine->machine graph (what feeds what)
  * planner/nodes.py     -- every extractor resolved to resource + purity + rate
  * planner/extract.py   -- recipe book (recipe class -> primary output)

Buildings are grouped into ZONES (spatial clusters, or named regions from
zones.yaml if present). For each zone it reports, from the ACTUAL wiring:
  - extraction by resource (potential rate, and live = rate x uptime)
  - production families (machine counts)
  - power generated
  - IMPORTS / EXPORTS: items that cross the zone boundary on a belt/pipe,
    i.e. edges whose two ends sit in different zones.

Because flow is traced through real connectors, coal mined in zone A that is
belted into zone B shows as an export of A and an import of B -- the global
item-balance model could never see that.

Usage:  python zone_report.py [save.sav] [--thresh METRES]
"""
import sys, os, glob, math, collections

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "vendor"))

import sav_parse as sp
from planner import topology, nodes as nodemod
from planner.extract import _short
from planner.recipes import RecipeBook

try:
    from map_report import family_of
except Exception:  # pragma: no cover - map_report shares the family keyword map
    def family_of(p):
        return p

POWER_MW = {
    "Build_GeneratorBiomass_C": 30, "Build_GeneratorIntegratedBiomass_C": 30,
    "Build_GeneratorCoal_C": 75, "Build_GeneratorFuel_C": 250,
    "Build_GeneratorNuclear_C": 2500, "Build_GeneratorGeoThermal_C": 200,
}
EXTRACTOR_CLASSES = set(nodemod.EXTRACTORS)


def newest_save(d=HERE):
    return sorted(glob.glob(os.path.join(d, (os.environ.get("SATISFACTORY_SAVE_SESSION", "") + "*.sav"))), key=os.path.getmtime)[-1]


# ------------------------------------------------------------------ zones
def cluster(points, thresh):
    """Greedy centroid clustering. points: list of (key, x, y). Returns list of
    {cx, cy, members:[key]}."""
    cs = []
    for key, x, y in points:
        best, bd = None, thresh
        for c in cs:
            dd = math.hypot(x - c["cx"], y - c["cy"])
            if dd < bd:
                bd, best = dd, c
        if best is None:
            cs.append({"cx": x, "cy": y, "members": [key]})
        else:
            best["members"].append(key)
            n = len(best["members"])
            best["cx"] += (x - best["cx"]) / n
            best["cy"] += (y - best["cy"]) / n
    return cs


def load_zones_yaml():
    """Optional zones.yaml: list of {name, center:[x,y], radius}. Returns [] if absent."""
    path = os.path.join(HERE, "zones.yaml")
    if not os.path.exists(path):
        return []
    try:
        import yaml
        data = yaml.safe_load(open(path)) or {}
        return data.get("zones", []) or []
    except Exception:
        return []


def assign_named(x, y, zones):
    """Nearest named zone whose radius covers (x,y); None if outside all."""
    best, bd = None, None
    for z in zones:
        cx, cy = z["center"]
        dd = math.hypot(x - cx, y - cy)
        if dd <= z.get("radius", 1e9) and (bd is None or dd < bd):
            bd, best = dd, z["name"]
    return best


# ------------------------------------------------------------------ build
def primary_output(bid, g, book, res_at):
    cls = g["nodes"][bid]["class"]
    if cls in EXTRACTOR_CLASSES:
        return res_at.get(bid)
    if cls in POWER_MW:
        return "Power"
    rc = g["nodes"][bid].get("recipe")
    if rc:
        r = book.by_class.get(rc) if hasattr(book, "by_class") else None
        if r is not None:
            return r.primary_output
    if "Storage" in cls or "FreightPlatform" in cls:
        return "(storage)"
    return None


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    thresh = 600.0
    if "--thresh" in sys.argv:
        thresh = float(sys.argv[sys.argv.index("--thresh") + 1])
    save = args[0] if args else newest_save()
    print("Reading", os.path.basename(save), "...")

    parsed = sp.readFullSaveFile(save)
    g = topology.build_graph(save, parsed=parsed)
    ext = nodemod.resolve_nodes(save)
    book = RecipeBook.load()

    # map each graph extractor building -> its resolved resource (nearest node rec)
    res_at = {}
    rate_at = {}
    up_at = {}
    for bid, nd in g["nodes"].items():
        if nd["class"] in EXTRACTOR_CLASSES and nd.get("pos"):
            x, y = nd["pos"][0], nd["pos"][1]
            best = min(ext, key=lambda e: math.hypot(e["pos"][0] - x, e["pos"][1] - y), default=None)
            if best and math.hypot(best["pos"][0] - x, best["pos"][1] - y) < 5:
                res_at[bid] = best["resource"]
                rate_at[bid] = best["rate_per_min"]
                up_at[bid] = best["live_uptime"]

    # ----- zone assignment
    named = load_zones_yaml()
    zone_of = {}
    positioned = [(bid, nd["pos"][0], nd["pos"][1]) for bid, nd in g["nodes"].items() if nd.get("pos")]
    if named:
        for bid, x, y in positioned:
            zone_of[bid] = assign_named(x, y, named) or "(unzoned)"
    else:
        for c in cluster(positioned, thresh):
            label = None
            zone_of_members = c["members"]
            for bid in zone_of_members:
                zone_of[bid] = (round(c["cx"]), round(c["cy"]))  # temp key; name later

    # group buildings by zone
    zones = collections.defaultdict(list)
    for bid in g["nodes"]:
        zones[zone_of.get(bid, "(unplaced)")].append(bid)

    # generator clocks (own light pass)
    gv = sp.getPropertyValue
    clock_of = {}
    for lvl in parsed.levels:
        hs = lvl.actorAndComponentObjectHeaders
        for i, o in enumerate(lvl.objects):
            iname = getattr(o, "instanceName", "") or ""
            if iname in g["nodes"] and g["nodes"][iname]["class"] in POWER_MW:
                c = gv(o.properties, "mCurrentPotential")
                clock_of[iname] = 1.0 if c is None else c

    # cross-zone flows
    exp = collections.defaultdict(lambda: collections.Counter())
    imp = collections.defaultdict(lambda: collections.Counter())
    for (a, b) in g["kinds"]:
        za, zb = zone_of.get(a), zone_of.get(b)
        if za is not None and zb is not None and za != zb:
            item = primary_output(a, g, book, res_at) or "?"
            exp[za][item] += 1
            imp[zb][item] += 1

    # ----- name auto-zones by dominant family + report
    def zone_name(z, bids):
        if isinstance(z, str):
            return z
        fams = collections.Counter()
        for bid in bids:
            po = primary_output(bid, g, book, res_at)
            if po and po not in ("Power", "(storage)"):
                fams[family_of(po)] += 1
        lead = fams.most_common(1)[0][0] if fams else "mixed"
        return f"{lead} @({z[0]},{z[1]})"

    order = sorted(zones, key=lambda z: -len(zones[z]))
    mode = f"zones.yaml ({len(named)} named)" if named else f"auto-cluster @ {thresh:.0f} m"
    print(f"\n{len([z for z in order if len(zones[z]) >= 3])} zones | {mode} | {len(g['nodes'])} placed buildings\n")
    for z in order:
        bids = zones[z]
        if len(bids) < 3:
            continue
        name = zone_name(z, bids)
        # extraction
        ex = collections.defaultdict(lambda: [0.0, 0.0])  # resource -> [potential, live]
        for bid in bids:
            if bid in res_at and res_at[bid]:
                ex[res_at[bid]][0] += rate_at[bid]
                ex[res_at[bid]][1] += rate_at[bid] * up_at[bid]
        # power
        mw = sum(POWER_MW[g["nodes"][bid]["class"]] * clock_of.get(bid, 1.0)
                 for bid in bids if g["nodes"][bid]["class"] in POWER_MW)
        # production families
        fam = collections.Counter()
        for bid in bids:
            po = primary_output(bid, g, book, res_at)
            if po and po not in ("Power", "(storage)") and g["nodes"][bid]["class"] not in EXTRACTOR_CLASSES:
                fam[family_of(po)] += 1

        print(f"=== {name}  ({len(bids)} buildings) ===")
        if ex:
            print("  EXTRACTION (potential | live):")
            for r, (p, l) in sorted(ex.items(), key=lambda a: -a[1][0]):
                print(f"     {r:14s} {p:7.0f}/min | {l:6.0f}/min live")
        if mw:
            print(f"  POWER: {mw:,.0f} MW")
        if fam:
            top = ", ".join(f"{k} x{v}" for k, v in fam.most_common(5))
            print(f"  PRODUCES: {top}")
        if exp.get(z):
            print("  EXPORTS ->: " + ", ".join(f"{k}({n})" for k, n in exp[z].most_common(6)))
        if imp.get(z):
            print("  IMPORTS <-: " + ", ".join(f"{k}({n})" for k, n in imp[z].most_common(6)))
        print()


if __name__ == "__main__":
    main()
