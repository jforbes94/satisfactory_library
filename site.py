#!/usr/bin/env python
"""Build the static site into ./docs for GitHub Pages.

Produces:
    docs/index.html              -- landing page: zone cards + links
    docs/factory_graph.html      -- the production/bottleneck report
    docs/resource_map.html       -- the full top-down resource map (geographic)
    docs/zones/<slug>.html        -- a readable MATERIAL-FLOW diagram + stats per zone

The zone pages are flow diagrams, not geographic maps: each manifold collapses to
one node (x count + rate) and belts are aggregated into one edge per item, with
import/export nodes for what crosses the zone boundary. See flow.py.

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


def build():
    save = sys.argv[1] if len(sys.argv) > 1 else zr.newest_save()
    print("Reading", os.path.basename(save))
    os.makedirs(os.path.join(DOCS, "zones"), exist_ok=True)

    r = zr.analyze(save)

    # the two main reports, generated then copied into docs/
    factory_report.run(save)
    map_report.main()
    for f in ("factory_graph.html", "resource_map.html"):
        src = os.path.join(HERE, f)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(DOCS, f))

    cards = []
    for name in r["order"]:
        z = r["zones"][name]
        nodes, edges = flow.build_zone_flow(r, name)
        mm = flow.to_mermaid(nodes, edges)
        page = (_ZONE.replace("__NAME__", html.escape(name))
                .replace("__SAVE__", html.escape(r["save"]))
                .replace("__NB__", str(len(z["bids"])))
                .replace("__MW__", f"{z['power']:,.0f}")
                .replace("__MERMAID__", html.escape(mm))      # escaped: Mermaid reads textContent
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
    print(f"Wrote docs/index.html + {len(cards)} zone flow diagrams + 2 reports")


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
.flow{overflow:auto}.flow .mermaid{min-width:100%}
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
  <a href="resource_map.html">&#128506; Geographic map</a>
</div>
<h2>Zones <span class="muted" style="font-weight:400;font-size:13px">&mdash; tap one for its material-flow diagram</span></h2>
<div class="grid">__CARDS__</div>
</div></body></html>"""

_ZONE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__NAME__ &middot; Flow</title>""" + _CSS + """</head><body><div class="wrap">
<div class="eyebrow"><a href="../index.html">&#8592; Atlas</a></div>
<h1>__NAME__</h1>
<div class="sub">__NB__ buildings &middot; __MW__ MW &middot; __SAVE__</div>
<div class="panel">
  <h2>Material flow <span class="muted" style="font-weight:400;font-size:12.5px">&mdash; manifolds collapsed, belts aggregated by item</span></h2>
  <div class="flow"><pre class="mermaid">__MERMAID__</pre></div>
  <div class="legend">
    <span><i style="background:#b36a2b"></i>resource node</span>
    <span><i style="background:#2f7fd6"></i>machine group (xN)</span>
    <span><i style="background:#d4a017"></i>generator</span>
    <span><i style="background:#7a8699"></i>storage buffer</span>
    <span><i style="background:#c05617"></i>&#8676; import / export &#8677; (other zones)</span>
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
  mermaid.initialize({startOnLoad:true, theme: dark?'dark':'default',
    flowchart:{useMaxWidth:false, htmlLabels:true, curve:'basis', nodeSpacing:45, rankSpacing:70}});
</script>
</div></body></html>"""


if __name__ == "__main__":
    build()
