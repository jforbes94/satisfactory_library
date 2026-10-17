#!/usr/bin/env python
"""Build the static site into ./docs for GitHub Pages.

Each zone page has TWO tabbed views, both inside a fixed-height pan/zoom viewport
(drag to pan, wheel/pinch to zoom, buttons) driven by a tiny custom controller:
  * Map  -- schematic: each manifold is a labelled, family-coloured box at its
            rough location (de-overlapped so labels stay legible). Not to scale.
  * Flow -- material-flow diagram (manifolds collapsed, belts aggregated by item),
            rendered with Mermaid.

Plus docs/index.html (zone cards) and copies of factory_graph + resource_map.

Run:  python site.py [save.sav]
GitHub Pages: Settings -> Pages -> Deploy from branch -> main -> /docs.
"""
import sys, os, re, html, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "vendor"))

import zone_report as zr
import flow
import map_report
import factory_report

DOCS = os.path.join(HERE, "docs")
MERMAID = "https://cdnjs.cloudflare.com/ajax/libs/mermaid/10.9.1/mermaid.min.js"

RES_COLOR = {
    "Coal": "#6b7280", "Iron Ore": "#b36a2b", "Copper Ore": "#c0703a",
    "Limestone": "#b9a978", "Caterium Ore": "#d4a017", "Bauxite": "#9a6b4b",
    "Sulfur": "#c9b53f", "Raw Quartz": "#c76fb0", "Uranium": "#3faa5a",
    "SAM": "#8a5fc0", "Crude Oil": "#4b4b57", "Water": "#2f7fd6",
    "Nitrogen Gas": "#59b0b8",
}
FAM_COLOR = {
    "Base/Steel": "#5b86c0", "Computing": "#3fa6a6", "Quantum": "#9b6bd6",
    "Aluminum": "#6fa3c7", "Nuclear": "#3faa5a", "Sulfur/Ammo": "#c2a12e",
    "Oil/Fuel": "#c0703a", "Caterium": "#d4a017", "Power": "#d4a017",
}


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "zone"


def chips(counter, n=10):
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


def _box_color(gp):
    if gp["cls"] == "res":
        return RES_COLOR.get(gp["family"], "#9a6b4b")
    if gp["cls"] == "gen":
        return "#d4a017"
    if gp["cls"] == "store":
        return "#7a8699"
    return FAM_COLOR.get(gp["family"], "#5b7088")


def zone_map_svg(name, r):
    """Schematic map: one labelled, family-coloured box per manifold, placed at
    its rough location then de-overlapped. Readable, not to scale."""
    gps = flow.zone_groups(r, name)
    if not gps:
        return 800, 400, ""
    xs = [g["cx"] for g in gps]; ys = [g["cy"] for g in gps]
    minx, miny = min(xs), min(ys)
    span = max(max(xs) - minx, max(ys) - miny, 1.0)
    SC = 1200.0 / span
    boxes = []
    for gp in gps:
        lines = gp["label"].split("\n")
        w = max(len(ln) for ln in lines) * 6.3 + 20
        h = len(lines) * 13 + 11
        boxes.append({"x": (gp["cx"] - minx) * SC, "y": (gp["cy"] - miny) * SC,
                      "w": w, "h": h, "lines": lines, "col": _box_color(gp)})
    # push overlapping boxes apart (labels must be readable; scale isn't sacred)
    for _ in range(150):
        moved = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                dx = b["x"] - a["x"]; dy = b["y"] - a["y"]
                ox = (a["w"] + b["w"]) / 2 - abs(dx) + 9
                oy = (a["h"] + b["h"]) / 2 - abs(dy) + 9
                if ox > 0 and oy > 0:
                    if ox < oy:
                        s = ox / 2 * (1 if dx >= 0 else -1); a["x"] -= s; b["x"] += s
                    else:
                        s = oy / 2 * (1 if dy >= 0 else -1); a["y"] -= s; b["y"] += s
                    moved = True
        if not moved:
            break
    x0 = min(b["x"] - b["w"] / 2 for b in boxes); x1 = max(b["x"] + b["w"] / 2 for b in boxes)
    y0 = min(b["y"] - b["h"] / 2 for b in boxes); y1 = max(b["y"] + b["h"] / 2 for b in boxes)
    pad = 24
    vbW, vbH = x1 - x0 + 2 * pad, y1 - y0 + 2 * pad
    parts = []
    for b in boxes:
        bx = b["x"] - b["w"] / 2 - x0 + pad; by = b["y"] - b["h"] / 2 - y0 + pad
        parts.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{b["w"]:.1f}" height="{b["h"]:.1f}" '
                     f'rx="6" fill="{b["col"]}" stroke="#0007" stroke-width="0.8"/>')
        for li, ln in enumerate(b["lines"]):
            parts.append(f'<text x="{bx + b["w"] / 2:.1f}" y="{by + 15 + li * 13:.1f}" '
                         f'class="blab">{html.escape(ln)}</text>')
    return vbW, vbH, "\n".join(parts)


def build():
    save = sys.argv[1] if len(sys.argv) > 1 else zr.newest_save()
    print("Reading", os.path.basename(save))
    os.makedirs(os.path.join(DOCS, "zones"), exist_ok=True)

    r = zr.analyze(save)

    factory_report.run(save)
    map_report.main()
    for f in ("factory_graph.html", "resource_map.html"):
        src = os.path.join(HERE, f)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(DOCS, f))

    cards = []
    for name in r["order"]:
        z = r["zones"][name]
        mm = flow.to_mermaid(*flow.build_zone_flow(r, name))
        W, H, svg = zone_map_svg(name, r)
        page = (_ZONE.replace("__NAME__", html.escape(name))
                .replace("__SAVE__", html.escape(r["save"]))
                .replace("__NB__", str(len(z["bids"])))
                .replace("__MW__", f"{z['power']:,.0f}")
                .replace("__W__", f"{W:.0f}").replace("__H__", f"{H:.0f}")
                .replace("__MAPSVG__", svg)
                .replace("__MERMAID__", html.escape(mm))
                .replace("__EXTROWS__", extraction_rows(z["extraction"]))
                .replace("__PRODUCES__", chips(z["produces"]))
                .replace("__EXPORTS__", chips(z["exports"]))
                .replace("__IMPORTS__", chips(z["imports"]))
                .replace("__MERMAIDJS__", MERMAID))
        with open(os.path.join(DOCS, "zones", slug(name) + ".html"), "w", encoding="utf-8") as fh:
            fh.write(page)

        topprod = ", ".join(k for k, _ in z["produces"].most_common(2)) or "&mdash;"
        topex = ", ".join(z["extraction"].keys())
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
    print(f"Wrote docs/index.html + {len(cards)} zone pages (schematic map + flow) + 2 reports")


# ---------------------------------------------------------------- templates
_CSS = """<style>
:root{--bg:#f3f1ec;--panel:#fff;--ink:#1b2028;--muted:#5d6773;--line:#e2ddd3;--accent:#c05617;--grid:#e9e3d7;
  --mono:ui-monospace,Consolas,monospace;--sans:"Segoe UI",system-ui,sans-serif;}
@media (prefers-color-scheme:dark){:root{--bg:#0f141b;--panel:#161d27;--ink:#e7edf4;--muted:#93a1b2;--line:#26303d;--accent:#f6963c;--grid:#1a232f;}}
:root[data-theme=dark]{--bg:#0f141b;--panel:#161d27;--ink:#e7edf4;--muted:#93a1b2;--line:#26303d;--accent:#f6963c;--grid:#1a232f;}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);line-height:1.5}
.wrap{max-width:1100px;margin:0 auto;padding:26px 18px 60px}
a{color:var(--accent);text-decoration:none}
.eyebrow{font-family:var(--mono);text-transform:uppercase;letter-spacing:.16em;font-size:12px;color:var(--accent);font-weight:600}
h1{font-size:26px;margin:2px 0}.sub{color:var(--muted);font-size:14px;margin-bottom:16px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;margin:14px 0;box-shadow:0 1px 2px #0001,0 8px 24px #0001}
.tabs{display:flex;gap:6px;margin-bottom:10px}
.tabs button{font:inherit;font-size:13px;font-weight:600;padding:6px 16px;border:1px solid var(--line);background:var(--bg);color:var(--muted);border-radius:8px;cursor:pointer}
.tabs button.active{background:var(--accent);color:#fff;border-color:var(--accent)}
.view{position:relative;height:72vh;min-height:380px;overflow:hidden;border:1px solid var(--line);border-radius:10px;
  background:radial-gradient(circle at 1px 1px,var(--grid) 1px,transparent 0);background-size:26px 26px;touch-action:none;cursor:grab}
.stage{position:absolute;top:0;left:0;transform-origin:0 0}
.stage svg{display:block}
.blab{fill:#fff;font-family:var(--sans);font-size:10.5px;font-weight:600;text-anchor:middle;paint-order:stroke;stroke:#0004;stroke-width:.4px}
.zc{position:absolute;right:10px;top:10px;display:flex;flex-direction:column;gap:5px}
.zc button{width:30px;height:30px;border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:7px;font-size:16px;cursor:pointer;line-height:1}
.hint{position:absolute;left:10px;bottom:8px;font-size:11.5px;color:var(--muted);background:var(--panel);padding:2px 8px;border-radius:6px;opacity:.85}
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
.cols{display:grid;grid-template-columns:1fr 1fr;gap:14px}@media (max-width:620px){.cols{grid-template-columns:1fr}.wrap{padding:18px 14px 48px}}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--muted);padding-top:8px}
.legend i{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:5px;vertical-align:-1px}
</style>"""

_INDEX = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Factory Atlas</title>""" + _CSS + """</head><body><div class="wrap">
<div class="eyebrow">FICSIT &middot; Factory Atlas</div>
<h1>Factory overview</h1>
<div class="sub">__NB__ buildings &middot; __NZ__ zones &middot; __SAVE__</div>
<div class="panel links">
  <a href="factory_graph.html">&#128202; Production &amp; bottlenecks</a>
  <a href="resource_map.html">&#128506; Full geographic map</a>
</div>
<h2>Zones <span class="muted" style="font-weight:400;font-size:13px">&mdash; each has a schematic map + a flow view</span></h2>
<div class="grid">__CARDS__</div>
</div></body></html>"""

_ZONE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__NAME__</title>""" + _CSS + """</head><body><div class="wrap">
<div class="eyebrow"><a href="../index.html">&#8592; Atlas</a></div>
<h1>__NAME__</h1>
<div class="sub">__NB__ buildings &middot; __MW__ MW &middot; __SAVE__</div>
<div class="panel">
  <div class="tabs">
    <button data-tab="map" class="active">&#128506; Map</button>
    <button data-tab="flow">&#128257; Flow</button>
  </div>
  <div class="view" data-pane="map">
    <div class="stage"><svg viewBox="0 0 __W__ __H__" width="__W__" height="__H__" xmlns="http://www.w3.org/2000/svg">__MAPSVG__</svg></div>
    <div class="zc"><button data-z="in">+</button><button data-z="out">&minus;</button><button data-z="fit">&#9635;</button></div>
    <div class="hint">drag to pan &middot; scroll to zoom</div>
  </div>
  <div class="view" data-pane="flow" hidden>
    <div class="stage"><pre class="mermaid" style="margin:0">__MERMAID__</pre></div>
    <div class="zc"><button data-z="in">+</button><button data-z="out">&minus;</button><button data-z="fit">&#9635;</button></div>
    <div class="hint">drag to pan &middot; scroll to zoom</div>
  </div>
  <div class="legend">
    <span><i style="background:#5b86c0"></i>machine group (xN)</span>
    <span><i style="background:#b36a2b"></i>resource</span>
    <span><i style="background:#d4a017"></i>generator</span>
    <span><i style="background:#7a8699"></i>storage</span>
    <span><i style="background:#c05617"></i>&#8676; import / export &#8677;</span>
  </div>
</div>
<div class="cols">
  <div class="panel"><h2>Extraction</h2>
    <table><thead><tr><th>Resource</th><th class="n">Potential/min</th><th class="n">Live/min</th><th>Uptime</th></tr></thead>
    <tbody>__EXTROWS__</tbody></table></div>
  <div class="panel"><h2>Produces</h2>__PRODUCES__
    <h2 style="margin-top:12px">Exports &rarr;</h2>__EXPORTS__
    <h2 style="margin-top:12px">&larr; Imports</h2>__IMPORTS__</div>
</div>
<script src="__MERMAIDJS__"></script>
<script>
var dark = matchMedia('(prefers-color-scheme: dark)').matches;
mermaid.initialize({startOnLoad:false, theme: dark?'dark':'default',
  flowchart:{useMaxWidth:false, htmlLabels:true, curve:'basis', nodeSpacing:40, rankSpacing:65}});

function panzoom(view){
  var stage=view.querySelector('.stage'), k=1,x=0,y=0,drag=false,lx,ly;
  function apply(){stage.style.transform='translate('+x+'px,'+y+'px) scale('+k+')';}
  function fit(){
    k=1;x=0;y=0;apply();
    var s=stage.getBoundingClientRect(), v=view.getBoundingClientRect();
    if(!s.width||!s.height) return;
    k=Math.min(v.width/s.width, v.height/s.height)*0.92;
    x=(v.width - s.width*k)/2; y=(v.height - s.height*k)/2; apply();
  }
  function zoomAt(mx,my,f){var nk=Math.min(Math.max(k*f,0.05),60);x=mx-(mx-x)*(nk/k);y=my-(my-y)*(nk/k);k=nk;apply();}
  view.addEventListener('wheel',function(e){e.preventDefault();var v=view.getBoundingClientRect();
    zoomAt(e.clientX-v.left,e.clientY-v.top, Math.exp(-e.deltaY*0.0016));},{passive:false});
  view.addEventListener('pointerdown',function(e){drag=true;lx=e.clientX;ly=e.clientY;view.setPointerCapture(e.pointerId);view.style.cursor='grabbing';});
  view.addEventListener('pointermove',function(e){if(!drag)return;x+=e.clientX-lx;y+=e.clientY-ly;lx=e.clientX;ly=e.clientY;apply();});
  function end(){drag=false;view.style.cursor='grab';}
  view.addEventListener('pointerup',end); view.addEventListener('pointercancel',end);
  view.querySelectorAll('.zc button').forEach(function(btn){btn.onclick=function(){
    var v=view.getBoundingClientRect();
    if(btn.dataset.z==='in') zoomAt(v.width/2,v.height/2,1.3);
    else if(btn.dataset.z==='out') zoomAt(v.width/2,v.height/2,1/1.3);
    else fit();
  };});
  fit();
}

panzoom(document.querySelector('.view[data-pane="map"]'));

var flowReady=false;
function showFlow(){
  if(flowReady) return; flowReady=true;
  var pane=document.querySelector('.view[data-pane="flow"]');
  mermaid.run({nodes:[pane.querySelector('.mermaid')]}).then(function(){
    var svg=pane.querySelector('svg');
    if(svg){svg.removeAttribute('style');svg.removeAttribute('width');svg.removeAttribute('height');}
    panzoom(pane);
  });
}
document.querySelectorAll('.tabs button').forEach(function(b){
  b.onclick=function(){
    document.querySelectorAll('.tabs button').forEach(function(x){x.classList.toggle('active',x===b);});
    document.querySelectorAll('.view').forEach(function(p){p.hidden = p.dataset.pane!==b.dataset.tab;});
    if(b.dataset.tab==='flow') showFlow();
  };
});
</script>
</div></body></html>"""


if __name__ == "__main__":
    build()
