#!/usr/bin/env python
"""Build the static site into ./docs for GitHub Pages.

Produces:
    docs/index.html              -- landing page: zone cards + links
    docs/factory_graph.html      -- the production/bottleneck report
    docs/resource_map.html       -- the full top-down resource map
    docs/zones/<slug>.html        -- a focused SUB-MAP + stats for each zone

Run:  python site.py [save.sav]
GitHub Pages: Settings -> Pages -> Deploy from branch -> main -> /docs.
"""
import sys, os, re, html, math, shutil, glob

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "vendor"))

import zone_report as zr
import map_report
import factory_report
from planner.recipes import RecipeBook
from planner import nodes as nodemod

DOCS = os.path.join(HERE, "docs")

# resource -> dot colour (CSS var names defined in the page)
RES_COLOR = {
    "Coal": "#6b7280", "Iron Ore": "#b36a2b", "Copper Ore": "#c0703a",
    "Limestone": "#c9b68a", "Caterium Ore": "#d4a017", "Bauxite": "#9a6b4b",
    "Sulfur": "#d8c24a", "Raw Quartz": "#c76fb0", "Uranium": "#3faa5a",
    "SAM": "#8a5fc0", "Crude Oil": "#2b2b33", "Water": "#2f7fd6",
    "Nitrogen Gas": "#59b0b8",
}


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "zone"


def zone_submap_svg(name, z, ext_in_zone, prod_pts, power_pts):
    """Focused SVG for one zone, zoomed to its bbox."""
    x0, y0, x1, y1 = z["bbox"]
    # pad 8% of the larger span (min 60 m) so edge buildings aren't clipped
    span = max(x1 - x0, y1 - y0, 1.0)
    pad = max(span * 0.08, 60.0)
    x0 -= pad; y0 -= pad; x1 += pad; y1 += pad
    W = 760.0
    H = max(W * (y1 - y0) / (x1 - x0), 240.0)

    def sx(x): return (x - x0) / (x1 - x0) * W
    def sy(y): return (y - y0) / (y1 - y0) * H

    parts = []
    for p in prod_pts:
        parts.append(f'<circle cx="{sx(p[0]):.1f}" cy="{sy(p[1]):.1f}" r="2.4" fill="var(--prod)" opacity="0.5"/>')
    for p in power_pts:
        parts.append(f'<circle cx="{sx(p[0]):.1f}" cy="{sy(p[1]):.1f}" r="4.5" fill="var(--pow)" stroke="#0007" stroke-width="0.7"/>')
    for e in ext_in_zone:
        x, y = e["pos"][0], e["pos"][1]
        col = RES_COLOR.get(e["resource"], "#999")
        parts.append(f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="6" fill="{col}" stroke="#0008" stroke-width="0.9"/>')
        lbl = f'{e["resource"]} {e["rate_per_min"]:.0f}'
        parts.append(f'<text x="{sx(x)+9:.1f}" y="{sy(y)+4:.1f}" class="nlab">{html.escape(lbl)}</text>')
    return W, H, "\n".join(parts)


def chips(counter, n=8):
    return " ".join(f'<span class="chip">{html.escape(str(k))} <b>{v}</b></span>'
                    for k, v in counter.most_common(n)) or '<span class="muted">&mdash;</span>'


def extraction_rows(ex):
    rows = []
    for res, (p, l) in sorted(ex.items(), key=lambda a: -a[1][0]):
        bar = min(100, (l / p * 100) if p else 0)
        rows.append(
            f'<tr><td>{html.escape(res)}</td><td class="n">{p:,.0f}</td>'
            f'<td class="n">{l:,.0f}</td>'
            f'<td><div class="bar"><div style="width:{bar:.0f}%"></div></div></td></tr>')
    return "\n".join(rows) or '<tr><td class="muted" colspan="4">no extraction in this zone</td></tr>'


def build():
    save = sys.argv[1] if len(sys.argv) > 1 else zr.newest_save()
    print("Reading", os.path.basename(save))
    os.makedirs(os.path.join(DOCS, "zones"), exist_ok=True)

    book = RecipeBook.load()
    r = zr.analyze(save)
    pts = map_report.extract_points(save, book)     # cm coords; cat/fam/name
    ext = [e for e in nodemod.resolve_nodes(save) if e.get("resource")]

    # the two main reports, generated then copied into docs/
    factory_report.run(save)
    map_report.main()
    for f in ("factory_graph.html", "resource_map.html"):
        src = os.path.join(HERE, f)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(DOCS, f))

    # per-zone sub-maps
    cards = []
    for name in r["order"]:
        z = r["zones"][name]
        if not z["bbox"]:
            continue
        x0, y0, x1, y1 = z["bbox"]
        span = max(x1 - x0, y1 - y0, 1.0); pad = max(span * 0.08, 60.0)
        bx0, by0, bx1, by1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad

        def inbox(px, py):
            return bx0 <= px <= bx1 and by0 <= py <= by1
        prod = [(p["x"] / 100, p["y"] / 100) for p in pts if p["cat"] == "prod" and inbox(p["x"] / 100, p["y"] / 100)]
        power = [(p["x"] / 100, p["y"] / 100) for p in pts if p["cat"] == "power" and inbox(p["x"] / 100, p["y"] / 100)]
        exz = [e for e in ext if inbox(e["pos"][0], e["pos"][1])]

        W, H, body = zone_submap_svg(name, z, exz, prod, power)
        page = (_ZONE.replace("__NAME__", html.escape(name))
                .replace("__SAVE__", html.escape(r["save"]))
                .replace("__NB__", str(len(z["bids"])))
                .replace("__MW__", f"{z['power']:,.0f}")
                .replace("__W__", f"{W:.0f}").replace("__H__", f"{H:.0f}")
                .replace("__SVG__", body)
                .replace("__EXTROWS__", extraction_rows(z["extraction"]))
                .replace("__PRODUCES__", chips(z["produces"]))
                .replace("__EXPORTS__", chips(z["exports"]))
                .replace("__IMPORTS__", chips(z["imports"])))
        with open(os.path.join(DOCS, "zones", slug(name) + ".html"), "w", encoding="utf-8") as fh:
            fh.write(page)

        topprod = ", ".join(f"{k}" for k, _ in z["produces"].most_common(2)) or "&mdash;"
        topex = ", ".join(f"{k}" for k, _ in {**z["extraction"]}.items()) if z["extraction"] else ""
        cards.append(
            f'<a class="card" href="zones/{slug(name)}.html"><h3>{html.escape(name)}</h3>'
            f'<div class="meta">{len(z["bids"])} buildings'
            + (f' &middot; {z["power"]:,.0f} MW' if z["power"] else "")
            + (f' &middot; {html.escape(topex)}' if topex else "")
            + f'</div><div class="meta muted">makes {html.escape(topprod)}</div></a>')

    idx = (_INDEX.replace("__SAVE__", html.escape(r["save"]))
           .replace("__NZ__", str(len(r["order"])))
           .replace("__NB__", str(len(r["graph"]["nodes"])))
           .replace("__CARDS__", "\n".join(cards)))
    with open(os.path.join(DOCS, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(idx)
    print(f"Wrote docs/index.html + {len(cards)} zone maps + 2 reports")


# ---------------------------------------------------------------- templates
_CSS = """<style>
:root{--bg:#f3f1ec;--panel:#fff;--ink:#1b2028;--muted:#5d6773;--line:#e2ddd3;--accent:#c05617;
  --pow:#d4a017;--prod:#9aa6b2;--grid:#e9e3d7;--mono:ui-monospace,Consolas,monospace;--sans:"Segoe UI",system-ui,sans-serif;}
@media (prefers-color-scheme:dark){:root{--bg:#0f141b;--panel:#161d27;--ink:#e7edf4;--muted:#93a1b2;--line:#26303d;
  --accent:#f6963c;--pow:#e3b94a;--prod:#4a5663;--grid:#1a232f;}}
:root[data-theme=dark]{--bg:#0f141b;--panel:#161d27;--ink:#e7edf4;--muted:#93a1b2;--line:#26303d;--accent:#f6963c;--pow:#e3b94a;--prod:#4a5663;--grid:#1a232f;}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);line-height:1.5}
.wrap{max-width:1040px;margin:0 auto;padding:26px 18px 60px}
a{color:var(--accent);text-decoration:none}
.eyebrow{font-family:var(--mono);text-transform:uppercase;letter-spacing:.16em;font-size:12px;color:var(--accent);font-weight:600}
h1{font-size:26px;margin:2px 0}.sub{color:var(--muted);font-size:14px;margin-bottom:16px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;margin:14px 0;box-shadow:0 1px 2px #0001,0 8px 24px #0001}
.mapwrap{background:radial-gradient(circle at 1px 1px,var(--grid) 1px,transparent 0);background-size:28px 28px;border-radius:10px;overflow:auto}
svg{display:block;max-width:100%;height:auto}
.nlab{fill:var(--ink);font-family:var(--mono);font-size:11px;paint-order:stroke;stroke:var(--panel);stroke-width:3px}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{padding:6px 9px;border-bottom:1px solid var(--grid);text-align:left}
th{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.05em}
td.n{font-family:var(--mono);text-align:right}
.bar{background:var(--grid);border-radius:4px;height:9px;min-width:80px}.bar div{background:var(--accent);height:9px;border-radius:4px}
.chip{display:inline-block;background:var(--grid);border-radius:20px;padding:2px 10px;margin:2px 3px;font-size:12.5px}
.muted{color:var(--muted)}h2{font-size:15px;margin:6px 0 8px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px}
.card{display:block;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;transition:.12s}
.card:hover{border-color:var(--accent);transform:translateY(-2px)}
.card h3{margin:0 0 4px;font-size:15px;color:var(--ink)}.meta{font-size:12.5px;color:var(--ink)}
.links a{margin-right:16px;font-weight:600}
@media (max-width:560px){.wrap{padding:18px 14px 48px}}
</style>"""

_INDEX = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Factory Atlas</title>""" + _CSS + """</head><body><div class="wrap">
<div class="eyebrow">FICSIT &middot; Factory Atlas</div>
<h1>Factory overview</h1>
<div class="sub">__NB__ buildings &middot; __NZ__ zones &middot; __SAVE__</div>
<div class="panel links">
  <a href="factory_graph.html">&#128202; Production &amp; bottlenecks</a>
  <a href="resource_map.html">&#128506; Full resource map</a>
</div>
<h2>Zones <span class="muted" style="font-weight:400;font-size:13px">&mdash; tap one for its sub-map</span></h2>
<div class="grid">__CARDS__</div>
</div></body></html>"""

_ZONE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__NAME__ &middot; Zone</title>""" + _CSS + """</head><body><div class="wrap">
<div class="eyebrow"><a href="../index.html">&#8592; Atlas</a></div>
<h1>__NAME__</h1>
<div class="sub">__NB__ buildings &middot; __MW__ MW &middot; __SAVE__</div>
<div class="panel"><div class="mapwrap">
  <svg viewBox="0 0 __W__ __H__" width="__W__" height="__H__" xmlns="http://www.w3.org/2000/svg">__SVG__</svg>
</div>
<div class="muted" style="font-size:12px;padding-top:8px">Dots = production machines &middot; gold = generators &middot; coloured + labelled = resource nodes (rate/min at current clock). Top-down world coords.</div>
</div>
<div class="panel"><h2>Extraction</h2>
<table><thead><tr><th>Resource</th><th class="n">Potential/min</th><th class="n">Live/min</th><th>Uptime</th></tr></thead>
<tbody>__EXTROWS__</tbody></table></div>
<div class="panel"><h2>Produces</h2>__PRODUCES__</div>
<div class="panel"><h2>Exports &rarr;</h2>__EXPORTS__</div>
<div class="panel"><h2>&larr; Imports</h2>__IMPORTS__</div>
</div></body></html>"""


if __name__ == "__main__":
    build()
