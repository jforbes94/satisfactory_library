#!/usr/bin/env python
"""Build a top-down RESOURCE MAP of the factory from a .sav, with zones labelled
by their core production.

Plots every extraction point, production machine (tagged with what it makes) and
power building at its real world position, auto-groups them into zones, names each
zone by its dominant production family, and writes resource_map.html.
"""
import glob, os, sys, math, html
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_VENDOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor")
if _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)
import sav_parse
from planner.extract import _short
from planner.recipes import RecipeBook

HERE = os.path.dirname(os.path.abspath(__file__))

EXTRACT = {
    "MinerMk1": ("ore", "Miner Mk1"), "MinerMk2": ("ore", "Miner Mk2"),
    "MinerMk3": ("ore", "Miner Mk3"), "OilPump": ("oil", "Oil"),
    "WaterPump": ("water", "Water"), "FrackingExtractor": ("frack", "Fracking"),
    "FrackingSmasher": ("frack", "Fracking"), "ResourceWellExtractor": ("frack", "Well"),
    "ResourceWellPressurizer": ("frack", "Well"),
}
PROD = {"ConstructorMk1", "AssemblerMk1", "ManufacturerMk1", "SmelterMk1",
        "FoundryMk1", "OilRefinery", "Packager", "Blender", "HadronCollider",
        "Converter", "QuantumEncoder"}
POWER = {"GeneratorFuel": "Fuel", "GeneratorCoal": "Coal", "GeneratorNuclear": "Nuclear",
         "GeneratorBiomass": "Biomass", "GeneratorGeoThermal": "Geothermal",
         "GeneratorIntegratedBiomass": "Biomass"}

# product -> family, by keyword (first match wins; order = specific before general)
FAMILY_RULES = [
    (("Uranium", "Plutonium", "Non-Fissile", "Ficsonium"), "Nuclear"),
    (("Diamond", "Time Crystal", "Ficsite", "Photonic", "Quantum", "Nuclear Pasta",
      "Dark Matter", "Singularity", "Superposition"), "Quantum"),
    (("Alumina", "Aluminum", "Alclad", "Casing", "Heat Sink", "Cooling", "Fluid Tank"), "Aluminum"),
    (("Sulfuric", "Black Powder", "Smokeless", "Compacted", "Nobelisk", "Rebar"), "Sulfur/Ammo"),
    (("Circuit Board", "Computer", "AI Limiter", "High-Speed", "Supercomputer"), "Computing"),
    (("Fuel", "Plastic", "Rubber", "Resin", "Turbofuel", "Petroleum", "Canister", "Packaged"), "Oil/Fuel"),
    (("Caterium", "Quickwire"), "Caterium"),
    (("Iron", "Steel", "Screw", "Rotor", "Stator", "Motor", "Modular", "Concrete",
      "Wire", "Cable", "Copper", "Rotor", "Frame", "Beam", "Pipe", "Plate", "Rod"), "Base/Steel"),
]


def family_of(product):
    for keys, fam in FAMILY_RULES:
        if any(k in product for k in keys):
            return fam
    return product  # fall back to the item name itself


def extract_points(save, book):
    parsed = sav_parse.readFullSaveFile(save)
    gv = sav_parse.getPropertyValue
    pts = []
    for lvl in parsed.levels:
        hs = lvl.actorAndComponentObjectHeaders
        for i, o in enumerate(lvl.objects):
            h = hs[i] if i < len(hs) else None
            cls = _short(getattr(h, "typePath", None) or "")
            if not cls.startswith("Build_"):
                continue
            short = cls[6:].replace("_C", "")
            pos = getattr(h, "position", None)
            if not pos or len(pos) < 2:
                continue
            x, y = pos[0], pos[1]
            if short in EXTRACT:
                cat, nm = EXTRACT[short]
                pts.append({"x": x, "y": y, "cat": cat, "fam": None, "name": nm})
            elif short in POWER:
                pts.append({"x": x, "y": y, "cat": "power", "fam": "Power:" + POWER[short], "name": "Generator"})
            elif short in PROD:
                props = getattr(o, "properties", None) or []
                rref = gv(props, "mCurrentRecipe")
                fam = None
                if rref is not None:
                    r = book.by_class.get(_short(rref))
                    if r:
                        fam = family_of(r.primary_output)
                pts.append({"x": x, "y": y, "cat": "prod", "fam": fam, "name": short})
    return pts


def cluster(pts, thresh=70000.0):
    clusters = []
    for p in pts:
        best, bd = None, thresh
        for c in clusters:
            d = math.hypot(p["x"] - c["cx"], p["y"] - c["cy"])
            if d < bd:
                bd, best = d, c
        if best is None:
            clusters.append({"cx": p["x"], "cy": p["y"], "pts": [p]})
        else:
            best["pts"].append(p)
            n = len(best["pts"])
            best["cx"] += (p["x"] - best["cx"]) / n
            best["cy"] += (p["y"] - best["cy"]) / n
    return clusters


def zone_label(z):
    """Name a zone by its dominant production family (or power / extraction)."""
    fams = Counter(p["fam"] for p in z["pts"] if p["fam"])
    if fams:
        top, n = fams.most_common(1)[0]
        return top
    # no production -> extraction-only outpost
    cats = Counter(p["cat"] for p in z["pts"])
    c = cats.most_common(1)[0][0]
    return {"ore": "Ore outpost", "oil": "Oil wells", "water": "Water", "frack": "Wells"}.get(c, "Outpost")


def main():
    save = sorted(glob.glob(os.path.join(HERE, (os.environ.get("SATISFACTORY_SAVE_SESSION", "") + "*.sav"))), key=os.path.getmtime)[-1]
    print("Reading", os.path.basename(save))
    book = RecipeBook.load()
    pts = extract_points(save, book)
    print(f"  {len(pts)} buildings")
    clusters = cluster(pts)
    zones = sorted([c for c in clusters if len(c["pts"]) >= 4], key=lambda c: -len(c["pts"]))
    for z in zones:
        z["label"] = zone_label(z)
    print(f"  {len(zones)} zones")

    xs = [p["x"] for p in pts]; ys = [p["y"] for p in pts]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    pad, W = 46.0, 940.0
    H = W * (maxy - miny) / (maxx - minx)

    def sx(x): return pad + (x - minx) / (maxx - minx) * (W - 2 * pad)
    def sy(y): return pad + (y - miny) / (maxy - miny) * (H - 2 * pad)

    colors = {"ore": "var(--ore)", "oil": "var(--oil)", "water": "var(--water)",
              "frack": "var(--frack)", "power": "var(--pow)", "prod": "var(--prod)"}

    dots = [f'<circle cx="{sx(p["x"]):.1f}" cy="{sy(p["y"]):.1f}" r="2.3" fill="var(--prod)" opacity="0.45"/>'
            for p in pts if p["cat"] == "prod"]
    marks = [f'<circle cx="{sx(p["x"]):.1f}" cy="{sy(p["y"]):.1f}" r="5" fill="{colors[p["cat"]]}" stroke="#0007" stroke-width="0.8"/>'
             for p in pts if p["cat"] != "prod"]

    zbox, zrows = [], []
    for z in zones:
        zxs = [p["x"] for p in z["pts"]]; zys = [p["y"] for p in z["pts"]]
        x0, x1, y0, y1 = sx(min(zxs)), sx(max(zxs)), sy(min(zys)), sy(max(zys))
        zbox.append(
            f'<rect x="{x0-15:.1f}" y="{y0-15:.1f}" width="{x1-x0+30:.1f}" height="{y1-y0+30:.1f}" '
            f'rx="11" fill="none" stroke="var(--zone)" stroke-width="1.5" stroke-dasharray="7 5"/>'
            f'<text x="{x0-11:.1f}" y="{y0-21:.1f}" class="zlab">{html.escape(z["label"])}</text>')
        fams = Counter(p["fam"] for p in z["pts"] if p["fam"] and not p["fam"].startswith("Power"))
        topf = ", ".join(f"{f} ({n})" for f, n in fams.most_common(3)) or "&mdash;"
        extr = Counter(p["cat"] for p in z["pts"] if p["cat"] in ("ore", "oil", "water", "frack", "power"))
        ebits = ", ".join(f"{n} {k}" for k, n in extr.items()) or "&mdash;"
        zrows.append(
            f'<tr><td><b>{html.escape(z["label"])}</b></td><td class="n">{len(z["pts"])}</td>'
            f'<td>{topf}</td><td>{ebits}</td><td class="n">({z["cx"]/100:.0f}, {z["cy"]/100:.0f})</td></tr>')

    page = (_PAGE.replace("__SAVE__", html.escape(os.path.basename(save)))
            .replace("__W__", f"{W:.0f}").replace("__H__", f"{H:.0f}")
            .replace("__ZBOX__", "\n".join(zbox)).replace("__DOTS__", "\n".join(dots))
            .replace("__MARKS__", "\n".join(marks)).replace("__ZROWS__", "\n".join(zrows))
            .replace("__NB__", str(len(pts))).replace("__NZ__", str(len(zones))))
    out = os.path.join(HERE, "resource_map.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(page)
    print("Wrote", out)


_PAGE = """<title>Factory Resource Map</title>
<style>
:root{--bg:#f3f1ec;--panel:#fff;--ink:#1b2028;--muted:#5d6773;--line:#e2ddd3;--accent:#c05617;
  --ore:#b36a2b;--oil:#2b2b33;--water:#2f7fd6;--frack:#8a5fc0;--pow:#d4a017;--prod:#9aa6b2;--zone:#c05617;--grid:#e9e3d7;
  --mono:ui-monospace,Consolas,monospace;--sans:"Segoe UI",system-ui,sans-serif;}
@media (prefers-color-scheme:dark){:root{--bg:#0f141b;--panel:#161d27;--ink:#e7edf4;--muted:#93a1b2;--line:#26303d;
  --accent:#f6963c;--ore:#d4914e;--oil:#8893a3;--water:#4ea0f0;--frack:#b084e8;--pow:#e3b94a;--prod:#4a5663;--zone:#f6963c;--grid:#1a232f;}}
:root[data-theme=light]{--bg:#f3f1ec;--panel:#fff;--ink:#1b2028;--muted:#5d6773;--line:#e2ddd3;--accent:#c05617;
  --ore:#b36a2b;--oil:#2b2b33;--water:#2f7fd6;--frack:#8a5fc0;--pow:#d4a017;--prod:#9aa6b2;--zone:#c05617;--grid:#e9e3d7;}
:root[data-theme=dark]{--bg:#0f141b;--panel:#161d27;--ink:#e7edf4;--muted:#93a1b2;--line:#26303d;
  --accent:#f6963c;--ore:#d4914e;--oil:#8893a3;--water:#4ea0f0;--frack:#b084e8;--pow:#e3b94a;--prod:#4a5663;--zone:#f6963c;--grid:#1a232f;}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);line-height:1.5}
.wrap{max-width:1040px;margin:0 auto;padding:26px 18px 60px}
.eyebrow{font-family:var(--mono);text-transform:uppercase;letter-spacing:.16em;font-size:12px;color:var(--accent);font-weight:600}
h1{font-size:26px;margin:2px 0} .sub{color:var(--muted);font-size:14px;margin-bottom:16px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;margin:14px 0;box-shadow:0 1px 2px #0001,0 8px 24px #0001}
.mapwrap{background:radial-gradient(circle at 1px 1px,var(--grid) 1px,transparent 0);background-size:28px 28px;border-radius:10px;overflow:auto}
svg{display:block;max-width:100%;height:auto}
.zlab{fill:var(--zone);font-family:var(--sans);font-weight:700;font-size:14px;paint-order:stroke;stroke:var(--panel);stroke-width:3px}
.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:12.5px;color:var(--muted);padding:10px 4px 0}
.legend i{display:inline-block;width:11px;height:11px;border-radius:50%;margin-right:5px;vertical-align:-1px}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{padding:6px 9px;border-bottom:1px solid var(--grid);text-align:left}
th{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.05em}
td.n{font-family:var(--mono);text-align:right}
h2{font-size:15px;margin:2px 0 8px}.hint{color:var(--muted);font-weight:400;font-size:12.5px;margin-left:8px}
.note{font-size:12.5px;color:var(--muted);margin-top:8px}
</style>
<div class="wrap">
  <div class="eyebrow">FICSIT &middot; Factory Resource Map</div>
  <h1>Zones by core production</h1>
  <div class="sub">__NB__ buildings &middot; __NZ__ zones, auto-named by what they make &middot; __SAVE__ &middot; coords in meters</div>
  <div class="panel">
    <div class="mapwrap">
      <svg viewBox="0 0 __W__ __H__" width="__W__" height="__H__" xmlns="http://www.w3.org/2000/svg">
        __ZBOX__
        __DOTS__
        __MARKS__
      </svg>
    </div>
    <div class="legend">
      <span><i style="background:var(--ore)"></i>ore miner</span>
      <span><i style="background:var(--oil)"></i>oil</span>
      <span><i style="background:var(--water)"></i>water</span>
      <span><i style="background:var(--frack)"></i>fracking / well</span>
      <span><i style="background:var(--pow)"></i>generator</span>
      <span><i style="background:var(--prod)"></i>production machine</span>
      <span>label = zone's dominant production</span>
    </div>
    <div class="note">Zone names come from the recipes machines are actually set to. Top-down from world coords (may be mirrored vs in-game, distances exact). Solid-ore type isn't in the save, so ore miners are located, not named.</div>
  </div>
  <div class="panel">
    <h2>Zones <span class="hint">named by dominant production family</span></h2>
    <table>
      <thead><tr><th>Zone (core)</th><th class="n">Buildings</th><th>Top products</th><th>Extraction / power</th><th class="n">Center (m)</th></tr></thead>
      <tbody>__ZROWS__</tbody>
    </table>
  </div>
</div>
"""

if __name__ == "__main__":
    main()
