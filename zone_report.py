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


def analyze(save_path, thresh=600.0):
    """Compute the full zone picture. Returns a dict shared by the printed report
    and the map/site builder:
        save, mode, graph, res_at, rate_at, up_at, named,
        zones = {name: {bids, extraction:{res:[pot,live]}, power, produces,
                        exports, imports, center:(x,y), bbox:(x0,y0,x1,y1)}},
        order = [zone names, largest first]
    """
    parsed = sp.readFullSaveFile(save_path)
    g = topology.build_graph(save_path, parsed=parsed)
    ext = nodemod.resolve_nodes(save_path)
    book = RecipeBook.load()

    # map each graph extractor building -> its resolved resource (nearest node rec)
    res_at, rate_at, up_at = {}, {}, {}
    for bid, nd in g["nodes"].items():
        if nd["class"] in EXTRACTOR_CLASSES and nd.get("pos"):
            x, y = nd["pos"][0], nd["pos"][1]
            best = min(ext, key=lambda e: math.hypot(e["pos"][0] - x, e["pos"][1] - y), default=None)
            if best and math.hypot(best["pos"][0] - x, best["pos"][1] - y) < 5:
                res_at[bid] = best["resource"]
                rate_at[bid] = best["rate_per_min"]
                up_at[bid] = best["live_uptime"]

    # ----- zone assignment (named regions from zones.yaml, else auto-cluster)
    named = load_zones_yaml()
    zone_of = {}
    positioned = [(bid, nd["pos"][0], nd["pos"][1]) for bid, nd in g["nodes"].items() if nd.get("pos")]
    if named:
        for bid, x, y in positioned:
            zone_of[bid] = assign_named(x, y, named) or "(unzoned)"
    else:
        for c in cluster(positioned, thresh):
            for bid in c["members"]:
                zone_of[bid] = (round(c["cx"]), round(c["cy"]))  # temp key; named below

    groups = collections.defaultdict(list)
    for bid in g["nodes"]:
        groups[zone_of.get(bid, "(unplaced)")].append(bid)

    # clocks for every machine (one pass) -- used for group rates + generator MW
    gv = sp.getPropertyValue
    clock_of = {}
    for lvl in parsed.levels:
        hs = lvl.actorAndComponentObjectHeaders
        for i, o in enumerate(lvl.objects):
            iname = getattr(o, "instanceName", "") or ""
            if iname in g["nodes"]:
                c = gv(o.properties, "mCurrentPotential")
                clock_of[iname] = 1.0 if c is None else c

    # cross-zone flows (edge = export of source zone, import of dest zone)
    exp = collections.defaultdict(collections.Counter)
    imp = collections.defaultdict(collections.Counter)
    for (a, b) in g["kinds"]:
        za, zb = zone_of.get(a), zone_of.get(b)
        if za is not None and zb is not None and za != zb:
            item = primary_output(a, g, book, res_at) or "?"
            exp[za][item] += 1
            imp[zb][item] += 1

    def zname(z, bids):
        if isinstance(z, str):
            return z
        fams = collections.Counter()
        for bid in bids:
            po = primary_output(bid, g, book, res_at)
            if po and po not in ("Power", "(storage)"):
                fams[family_of(po)] += 1
        lead = fams.most_common(1)[0][0] if fams else "mixed"
        return f"{lead} @({z[0]},{z[1]})"

    zones = {}
    for z, bids in groups.items():
        if len(bids) < 3:
            continue
        name = zname(z, bids)
        ex = collections.defaultdict(lambda: [0.0, 0.0])  # resource -> [potential, live]
        xs, ys = [], []
        for bid in bids:
            nd = g["nodes"][bid]
            if nd.get("pos"):
                xs.append(nd["pos"][0]); ys.append(nd["pos"][1])
            if bid in res_at and res_at[bid]:
                ex[res_at[bid]][0] += rate_at[bid]
                ex[res_at[bid]][1] += rate_at[bid] * up_at[bid]
        mw = sum(POWER_MW[g["nodes"][bid]["class"]] * clock_of.get(bid, 1.0)
                 for bid in bids if g["nodes"][bid]["class"] in POWER_MW)
        fam = collections.Counter()
        for bid in bids:
            po = primary_output(bid, g, book, res_at)
            if po and po not in ("Power", "(storage)") and g["nodes"][bid]["class"] not in EXTRACTOR_CLASSES:
                fam[family_of(po)] += 1
        zones[name] = {
            "bids": bids, "extraction": {k: v for k, v in ex.items()}, "power": mw,
            "produces": fam, "exports": exp.get(z, collections.Counter()),
            "imports": imp.get(z, collections.Counter()),
            "center": (sum(xs) / len(xs), sum(ys) / len(ys)) if xs else None,
            "bbox": (min(xs), min(ys), max(xs), max(ys)) if xs else None,
        }

    # final zone NAME per building (both modes), so downstream tools key by name
    keyname = {z: zname(z, bids) for z, bids in groups.items()}
    zone_of_named = {bid: keyname.get(zone_of.get(bid)) for bid in g["nodes"]}

    order = sorted(zones, key=lambda n: -len(zones[n]["bids"]))
    mode = f"zones.yaml ({len(named)} named)" if named else f"auto-cluster @ {thresh:.0f} m"
    return {"save": os.path.basename(save_path), "mode": mode, "graph": g, "named": named,
            "res_at": res_at, "rate_at": rate_at, "up_at": up_at, "zones": zones, "order": order,
            "zone_of": zone_of_named, "clock_of": clock_of, "book": book}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    thresh = 600.0
    if "--thresh" in sys.argv:
        thresh = float(sys.argv[sys.argv.index("--thresh") + 1])
    save = args[0] if args else newest_save()
    print("Reading", os.path.basename(save), "...")
    r = analyze(save, thresh)
    print(f"\n{len(r['order'])} zones | {r['mode']} | {len(r['graph']['nodes'])} placed buildings\n")
    for name in r["order"]:
        z = r["zones"][name]
        print(f"=== {name}  ({len(z['bids'])} buildings) ===")
        if z["extraction"]:
            print("  EXTRACTION (potential | live):")
            for res, (p, l) in sorted(z["extraction"].items(), key=lambda a: -a[1][0]):
                print(f"     {res:14s} {p:7.0f}/min | {l:6.0f}/min live")
        if z["power"]:
            print(f"  POWER: {z['power']:,.0f} MW")
        if z["produces"]:
            print("  PRODUCES: " + ", ".join(f"{k} x{v}" for k, v in z["produces"].most_common(5)))
        if z["exports"]:
            print("  EXPORTS ->: " + ", ".join(f"{k}({n})" for k, n in z["exports"].most_common(6)))
        if z["imports"]:
            print("  IMPORTS <-: " + ", ".join(f"{k}({n})" for k, n in z["imports"].most_common(6)))
        print()


if __name__ == "__main__":
    main()
