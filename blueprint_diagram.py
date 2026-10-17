#!/usr/bin/env python
"""Read a Satisfactory .sbp blueprint and draw a top-down schematic (HTML/SVG).

    python blueprint_diagram.py "path/to/blueprint.sbp" [out.html]

Parses building positions out of the blueprint and renders an accurate top-down
plan view, plus a parts list. Positions are in Unreal cm (800 = 8 m foundation).
"""
import collections
import html
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import sav_parse


def parse_blueprint(path):
    data = open(path, "rb").read()
    off = data.find(b"\xc1\x83\x2a\x9e")  # UE chunk signature
    dec = sav_parse.decompressSaveFile(off, data)
    seen, rows = set(), []
    for m in re.finditer(rb"/Game/[ -~]{5,90}?\.Build_[ -~]{2,60}?_C", dec):
        try:
            ah = sav_parse.ActorHeader()
            ah.parse(m.start() - 4, dec)
        except Exception:
            continue
        tp = getattr(ah, "typePath", "")
        pos = getattr(ah, "position", None)
        if "Build_" not in tp or not pos:
            continue
        x, y, z = pos
        if max(abs(x), abs(y), abs(z)) > 1e6:
            continue
        key = (round(x, 1), round(y, 1), round(z, 1), tp)
        if key in seen:
            continue
        seen.add(key)
        rows.append((tp.rsplit(".", 1)[-1], x, y, z))
    return rows


# friendly names + category for coloring
def classify(name, z):
    n = name.lower()
    if "foundation" in n:
        return ("Foundation (road deck)", "deck") if z > 1000 else ("Foundation (base)", "base")
    if "wall" in n:
        return "Wall (guardrail)", "wall"
    if "barrier" in n:
        return "Concrete Barrier (median)", "barrier"
    if "quarterpipe" in n:
        return "Quarter Pipe (curb)", "curb"
    if "vehiclepathnode" in n:
        return "Vehicle Path Node", "node"
    if "vehiclepath" in n:
        return "Vehicle Path (lane)", "path"
    if "pillar" in n:
        return "Pillar (support)", "pillar"
    if "ladder" in n:
        return "Ladder (access)", "ladder"
    return name, "other"


def render(rows, title):
    xs = [r[1] for r in rows]
    ys = [r[2] for r in rows]
    minx, maxx = min(xs) - 500, max(xs) + 500
    miny, maxy = min(ys) - 500, max(ys) + 500
    SCALE = 0.14  # px per cm
    W = (maxx - minx) * SCALE
    H = (maxy - miny) * SCALE

    def sx(x):  # world x -> svg x
        return (x - minx) * SCALE

    def sy(y):  # flip so +Y (travel dir) is up
        return (maxy - y) * SCALE

    parts = []
    counts = collections.Counter()
    # draw order: deck, base outline, curb, wall, barrier, pillar, path, nodes, ladder
    order = {"base": 0, "deck": 1, "curb": 2, "wall": 3, "barrier": 4,
             "pillar": 5, "path": 6, "node": 7, "ladder": 8, "other": 9}
    drawn = sorted(rows, key=lambda r: order.get(classify(r[0], r[3])[1], 9))
    svg = []
    path_pts = []
    for name, x, y, z in drawn:
        label, cat = classify(name, z)
        counts[label] += 1
        cx, cy = sx(x), sy(y)
        if cat == "deck":
            svg.append(f'<rect class="deck" x="{cx-800*SCALE/2:.1f}" y="{cy-800*SCALE/2:.1f}" '
                       f'width="{800*SCALE:.1f}" height="{800*SCALE:.1f}" rx="2"/>')
        elif cat == "base":
            svg.append(f'<rect class="base" x="{cx-800*SCALE/2:.1f}" y="{cy-800*SCALE/2:.1f}" '
                       f'width="{800*SCALE:.1f}" height="{800*SCALE:.1f}"/>')
        elif cat == "curb":
            svg.append(f'<rect class="curb" x="{cx-800*SCALE/2:.1f}" y="{cy-800*SCALE/2:.1f}" '
                       f'width="{800*SCALE:.1f}" height="{800*SCALE:.1f}"/>')
        elif cat == "wall":
            svg.append(f'<rect class="wall" x="{cx-40*SCALE:.1f}" y="{cy-800*SCALE/2:.1f}" '
                       f'width="{80*SCALE:.1f}" height="{800*SCALE:.1f}" rx="2"/>')
        elif cat == "barrier":
            svg.append(f'<rect class="barrier" x="{cx-90*SCALE:.1f}" y="{cy-190*SCALE:.1f}" '
                       f'width="{180*SCALE:.1f}" height="{380*SCALE:.1f}" rx="2"/>')
        elif cat == "pillar":
            r = 300 * SCALE
            svg.append(f'<circle class="pillar" cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}"/>'
                       f'<line class="pcross" x1="{cx-r*.6:.1f}" y1="{cy:.1f}" x2="{cx+r*.6:.1f}" y2="{cy:.1f}"/>'
                       f'<line class="pcross" x1="{cx:.1f}" y1="{cy-r*.6:.1f}" x2="{cx:.1f}" y2="{cy+r*.6:.1f}"/>')
        elif cat == "node":
            path_pts.append((cx, cy))
            svg.append(f'<circle class="node" cx="{cx:.1f}" cy="{cy:.1f}" r="5"/>')
        elif cat == "ladder":
            svg.append(f'<rect class="ladder" x="{cx-120*SCALE:.1f}" y="{cy-120*SCALE:.1f}" '
                       f'width="{240*SCALE:.1f}" height="{240*SCALE:.1f}" rx="2"/>'
                       f'<line class="lrung" x1="{cx-120*SCALE:.1f}" y1="{cy-6:.1f}" x2="{cx+120*SCALE:.1f}" y2="{cy-6:.1f}"/>'
                       f'<line class="lrung" x1="{cx-120*SCALE:.1f}" y1="{cy+6:.1f}" x2="{cx+120*SCALE:.1f}" y2="{cy+6:.1f}"/>')
    # vehicle path lanes: draw dashed arrowed lines through the deck along travel (Y)
    lane_x = sorted({round(x) for n, x, y, z in rows if "vehiclepath_universal" in n.lower()})
    for lx in lane_x:
        x0 = sx(lx)
        svg.append(f'<line class="lane" x1="{x0:.1f}" y1="{H-6:.1f}" x2="{x0:.1f}" y2="6" '
                   f'marker-end="url(#arrow)"/>')

    svg_txt = "\n".join(svg)
    width_m = (max(xs) - min(xs)) / 100
    length_m = (max(ys) - min(ys)) / 100
    height_m = max(z for _, _, _, z in rows) / 100

    legend_items = [
        ("deck", "Road deck (foundation)"),
        ("wall", "Guardrail wall"),
        ("barrier", "Center median barrier"),
        ("curb", "Quarter-pipe curb"),
        ("lane", "Truck lane (travel →)"),
        ("pillar", "Pillar support"),
        ("ladder", "Ladder access"),
    ]
    legend = "".join(
        f'<span class="lg"><i class="sw {c}"></i>{html.escape(t)}</span>' for c, t in legend_items
    )
    parts_rows = "".join(
        f"<tr><td>{html.escape(l)}</td><td class='num'>{n}</td></tr>"
        for l, n in sorted(counts.items(), key=lambda kv: -kv[1])
    )

    return _PAGE.replace("__TITLE__", html.escape(title)) \
        .replace("__W__", f"{W:.0f}").replace("__H__", f"{H:.0f}") \
        .replace("__SVG__", svg_txt).replace("__LEGEND__", legend) \
        .replace("__PARTS__", parts_rows) \
        .replace("__DIMS__", f"{width_m:.0f} m wide &times; {length_m:.0f} m long, "
                             f"raised {height_m - 0.5:.0f} m on a pillar") \
        .replace("__TOTAL__", str(len(rows)))


_PAGE = r"""<title>Road Piece &middot; Blueprint Plan</title>
<style>
:root{--bg:#f3f1ec;--panel:#fff;--ink:#1b2028;--muted:#5d6773;--line:#e2ddd3;--accent:#c05617;
 --deck:#c9c2b4;--deck-l:#b8b0a0;--wall:#e08a2e;--barrier:#d9a21b;--curb:#a89b86;--lane:#c05617;
 --pillar:#6b7a88;--ladder:#8a6d3b;--grid:#e7e1d5;--mono:ui-monospace,Consolas,monospace;
 --sans:"Segoe UI",system-ui,sans-serif;}
@media (prefers-color-scheme:dark){:root{--bg:#0f141b;--panel:#161d27;--ink:#e7edf4;--muted:#93a1b2;
 --line:#26303d;--accent:#f6963c;--deck:#3a4048;--deck-l:#2c333c;--wall:#f6963c;--barrier:#d9a21b;
 --curb:#4a4f57;--lane:#f6963c;--pillar:#5a6b7a;--ladder:#b98a44;--grid:#1a232f;}}
:root[data-theme="dark"]{--bg:#0f141b;--panel:#161d27;--ink:#e7edf4;--muted:#93a1b2;--line:#26303d;
 --accent:#f6963c;--deck:#3a4048;--deck-l:#2c333c;--wall:#f6963c;--barrier:#d9a21b;--curb:#4a4f57;
 --lane:#f6963c;--pillar:#5a6b7a;--ladder:#b98a44;--grid:#1a232f;}
:root[data-theme="light"]{--bg:#f3f1ec;--panel:#fff;--ink:#1b2028;--muted:#5d6773;--line:#e2ddd3;
 --accent:#c05617;--deck:#c9c2b4;--deck-l:#b8b0a0;--wall:#e08a2e;--barrier:#d9a21b;--curb:#a89b86;
 --lane:#c05617;--pillar:#6b7a88;--ladder:#8a6d3b;--grid:#e7e1d5;}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);line-height:1.5}
.wrap{max-width:900px;margin:0 auto;padding:28px 20px 60px}
.eyebrow{font-family:var(--mono);text-transform:uppercase;letter-spacing:.16em;font-size:12px;color:var(--accent);font-weight:600}
h1{font-size:26px;margin:2px 0 2px}.sub{color:var(--muted);font-size:14px;margin-bottom:20px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px;margin:16px 0;
 box-shadow:0 1px 2px rgba(0,0,0,.05),0 8px 24px rgba(0,0,0,.05)}
.diagram{display:flex;justify-content:center;background:
 radial-gradient(circle at 1px 1px,var(--grid) 1px,transparent 0);background-size:20px 20px;border-radius:10px;padding:14px;overflow:auto}
svg{max-width:100%;height:auto}
.deck{fill:var(--deck);stroke:var(--deck-l);stroke-width:1}
.base{fill:none;stroke:var(--muted);stroke-width:1;stroke-dasharray:4 3;opacity:.5}
.curb{fill:var(--curb);opacity:.5}
.wall{fill:var(--wall)}
.barrier{fill:var(--barrier)}
.pillar{fill:var(--pillar);opacity:.85}
.node{fill:var(--lane)}
.ladder{fill:var(--ladder);opacity:.9}
.lane{stroke:var(--lane);stroke-width:2.5;stroke-dasharray:7 6;fill:none}
.pcross{stroke:#fff;stroke-width:1.5;opacity:.8}.lrung{stroke:#fff;stroke-width:1.2;opacity:.7}
.legend{display:flex;flex-wrap:wrap;gap:10px 16px;margin-top:12px;font-size:12.5px;color:var(--muted)}
.lg{display:flex;align-items:center;gap:6px}.sw{width:14px;height:14px;border-radius:3px;display:inline-block}
.sw.deck{background:var(--deck)}.sw.wall{background:var(--wall)}.sw.barrier{background:var(--barrier)}
.sw.curb{background:var(--curb)}.sw.lane{background:var(--lane)}.sw.pillar{background:var(--pillar);border-radius:50%}
.sw.ladder{background:var(--ladder)}
h2{font-size:15px;margin:0 0 8px}.hint{color:var(--muted);font-weight:400;font-size:12.5px;margin-left:8px}
table{border-collapse:collapse;width:100%;font-size:13.5px}
td{padding:5px 8px;border-bottom:1px solid var(--grid)}.num{text-align:right;font-family:var(--mono)}
.compass{font-family:var(--mono);font-size:12px;color:var(--muted);text-align:center;margin-top:6px}
</style>
<div class="wrap">
  <div class="eyebrow">FICSIT &middot; Blueprint Plan</div>
  <h1>__TITLE__</h1>
  <div class="sub">__DIMS__ &middot; __TOTAL__ pieces &middot; top-down view</div>

  <div class="panel">
    <div class="diagram">
      <svg viewBox="0 0 __W__ __H__" width="__W__" height="__H__" xmlns="http://www.w3.org/2000/svg">
        <defs><marker id="arrow" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto">
          <path d="M0,0 L7,3 L0,6 Z" fill="var(--lane)"/></marker></defs>
        __SVG__
      </svg>
    </div>
    <div class="compass">&uarr; direction of travel</div>
    <div class="legend">__LEGEND__</div>
  </div>

  <div class="panel">
    <h2>Parts list <span class="hint">what one stamp places</span></h2>
    <table><tbody>__PARTS__</tbody></table>
  </div>
</div>
"""


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: python blueprint_diagram.py <blueprint.sbp> [out.html]")
    sbp = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "blueprint_diagram.html"
    title = os.path.splitext(os.path.basename(sbp))[0]
    rows = parse_blueprint(sbp)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(render(rows, title))
    print(f"parsed {len(rows)} pieces -> {out}")


if __name__ == "__main__":
    main()
