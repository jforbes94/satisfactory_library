"""Render the analysis into a self-contained, offline HTML page.

Static HTML (cards, tables, math) is built in Python; only the node-link graph
needs JavaScript (pan / zoom / hover-highlight). Everything is inlined so the
file opens with no server and no internet.
"""
from __future__ import annotations

import html
import json
from collections import defaultdict
from typing import Dict, List

from .recipes import RecipeBook

# ---- layout constants (pixels) ----
NODE_W, NODE_H = 216, 70
COL_GAP, ROW_GAP = 96, 28
PAD = 40


def _status(eff: float) -> str:
    if eff >= 0.999:
        return "good"
    if eff >= 0.5:
        return "warn"
    return "crit"


def _layout(nodes: List[dict], edges: List[dict]):
    by_layer: Dict[int, List[dict]] = defaultdict(list)
    for n in nodes:
        by_layer[n["layer"]].append(n)
    max_rows = max((len(v) for v in by_layer.values()), default=1)
    col_h = max_rows * (NODE_H + ROW_GAP)

    out_nodes = []
    for layer in sorted(by_layer):
        col = by_layer[layer]
        col.sort(key=lambda n: (n["kind"] != "raw", n.get("product") or n["label"]))
        this_h = len(col) * (NODE_H + ROW_GAP)
        y0 = (col_h - this_h) / 2 + PAD
        for i, n in enumerate(col):
            n = dict(n)
            n["x"] = PAD + layer * (NODE_W + COL_GAP)
            n["y"] = y0 + i * (NODE_H + ROW_GAP)
            n["w"] = NODE_W
            n["h"] = NODE_H
            if n["kind"] == "recipe":
                n["status"] = _status(n.get("eff", 1.0))
            else:
                n["status"] = n["kind"]
            out_nodes.append(n)

    max_layer = max((n["layer"] for n in nodes), default=0)
    width = PAD * 2 + (max_layer + 1) * (NODE_W + COL_GAP) - COL_GAP
    height = col_h + PAD * 2
    return out_nodes, edges, width, height


def _pct(x: float) -> str:
    return f"{round(x * 100)}%"


def _fmt(x: float) -> str:
    x = round(x + 0.0, 2)
    return f"{x:g}"


# ------------------------------------------------------------------ cards ----
def _tip(term: str, plain: str) -> str:
    return (f'<span class="tip" tabindex="0">{html.escape(term)}'
            f'<span class="tip-bubble">{html.escape(plain)}</span></span>')


def _cards(a: dict) -> str:
    m = a["metrics"]
    bn = a["bottlenecks"][0] if a["bottlenecks"] else None
    starved = f'{a["lines_starved"]} of {a["lines_total"]}'

    # bottleneck card
    if bn:
        b_head = html.escape(bn["item"])
        b_sub = f'{_pct(bn["ratio"])} supplied &middot; {starved} lines starved'
        b_status = _status(bn["ratio"])
    else:
        b_head, b_sub, b_status = "None", "everything is fed &middot; nice", "good"

    path = m["longest_path"]
    path_str = " &rarr; ".join(html.escape(p) for p in path)

    hub = m["hub"]
    hub_head = html.escape(hub["label"]) if hub else "&mdash;"
    hub_sub = (f'feeds {hub["out_degree"]} lines: '
               + ", ".join(html.escape(f) for f in hub["feeds"])) if hub else ""

    comps = m["components"]
    comp_sub = (f'{len(m["sources"])} raw sources &middot; '
                f'{len(m["sinks"])} final products')

    return f"""
    <section class="cards">
      <article class="card status-{b_status}">
        <div class="card-k">{_tip("Bottleneck", "The item you make less of than you need. Like the weakest link in a chain, it caps everything downstream. Graph idea: the lowest supply ratio (made / needed) anywhere in the graph.")}
          <span class="ghost">/ weakest link</span></div>
        <div class="card-v">{b_head}</div>
        <div class="card-s">{b_sub}</div>
      </article>

      <article class="card">
        <div class="card-k">{_tip("Longest chain", "The most steps between raw ore and a finished part. Tells you how deep your most complex product is. Graph idea: the longest path through the graph.")}
          <span class="ghost">/ longest path</span></div>
        <div class="card-v">{m["depth"]} steps deep</div>
        <div class="card-s mono">{path_str}</div>
      </article>

      <article class="card">
        <div class="card-k">{_tip("Biggest hub", "The item feeding the most different lines. If it wobbles, lots breaks downstream. Graph idea: the node with the highest out-degree (most outgoing arrows).")}
          <span class="ghost">/ out-degree</span></div>
        <div class="card-v">{hub_head}</div>
        <div class="card-s">{hub_sub}</div>
      </article>

      <article class="card">
        <div class="card-k">{_tip("Sub-factories", "Groups of machines that connect to each other but not to the other groups. Your biomass power chain is its own island. Graph idea: connected components.")}
          <span class="ghost">/ components</span></div>
        <div class="card-v">{len(comps)} sub-factories</div>
        <div class="card-s">{comp_sub}</div>
      </article>
    </section>
    """


# -------------------------------------------------------------- bottleneck ----
def _bottleneck_section(a: dict) -> str:
    bns = a["bottlenecks"]
    if not bns:
        return ('<section class="panel"><h2>Bottlenecks</h2>'
                '<p class="ok">Nothing is starved &mdash; every line has the inputs it needs.</p></section>')
    top = bns[0]
    no_prod = "" if top["producer_present"] else " You have <b>zero machines</b> making it."
    lead = (
        f'<div class="bn-lead status-{_status(top["ratio"])}">'
        f'<div class="bn-tag">Biggest bottleneck</div>'
        f'<div class="bn-name">{html.escape(top["item"])}</div>'
        f'<div class="bn-line">Running at <b>{_pct(top["ratio"])}</b> &mdash; '
        f'you make <b>{_fmt(top["produced"])}/min</b> but need <b>{_fmt(top["consumed"])}/min</b> '
        f'(<b>{_fmt(top["deficit"])}/min short</b>).{no_prod}</div>'
        f'<div class="bn-line">Starves: <b>{", ".join(html.escape(s) for s in top["starves"])}</b></div>'
        f'<div class="bn-fix">Smallest fix &rarr; add <b>{top["fix_add"]} {html.escape(top["fix_building"])}'
        f'</b> on <b>{html.escape(top["fix_recipe"])}</b> '
        f'(+{_fmt(top["fix_gain"])}/min, closes the gap)</div>'
        f'</div>'
    )
    rows = ""
    for b in bns:
        rows += (
            f'<tr class="status-{_status(b["ratio"])}">'
            f'<td>{html.escape(b["item"])}</td>'
            f'<td class="num">{_pct(b["ratio"])}</td>'
            f'<td class="num">{_fmt(b["produced"])}</td>'
            f'<td class="num">{_fmt(b["consumed"])}</td>'
            f'<td class="num neg">-{_fmt(b["deficit"])}</td>'
            f'<td>{", ".join(html.escape(s) for s in b["starves"])}</td>'
            f'<td>+{b["fix_add"]} {html.escape(b["fix_building"])} on {html.escape(b["fix_recipe"])}</td>'
            f'</tr>'
        )
    return f"""
    <section class="panel">
      <h2>Bottlenecks <span class="hint">what to fix, worst first</span></h2>
      {lead}
      <div class="scroll">
      <table class="grid">
        <thead><tr><th>Item</th><th class="num">Supplied</th><th class="num">Made/min</th>
        <th class="num">Need/min</th><th class="num">Short</th><th>Starves</th><th>Smallest fix</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
      </div>
    </section>
    """


# ---------------------------------------------------------- efficiency table ----
def _eff_table(a: dict) -> str:
    rows = ""
    for L in a["lines"]:
        live = L["live_prod"]         # measured uptime, drives the row status
        pot = L["potential_out"]
        act = L["live_out"]
        st = _status(live)
        clk = L["clock"]
        clk_badge = f' <span class="ghost">@{round(clk*100)}%</span>' if abs(clk - 1.0) > 0.01 else ""
        rows += (
            f'<tr class="status-{st}">'
            f'<td>{html.escape(L["name"])}</td>'
            f'<td class="num">{L["count"]}{clk_badge}</td>'
            f'<td>{html.escape(L["building"])}</td>'
            f'<td class="num">{_fmt(pot)}</td>'
            f'<td class="num"><b>{_fmt(act)}</b></td>'
            f'<td class="effcell"><span class="bar"><span class="fill s-{st}" style="width:{min(100, round(live*100))}%"></span></span>'
            f'<span class="num">{_pct(live)}</span></td>'
            f'<td class="num">{_fmt(L["power"])} MW</td>'
            f'</tr>'
        )
    pot_t = a["pot_total"]
    live_t = a["live_total"]
    ratio = (live_t / pot_t) if pot_t else 1.0
    return f"""
    <details class="panel" open>
      <summary><h2>Every line &middot; potential vs live</h2>
        <span class="hint">most-stalled first &middot; <b>Live</b> = actual output right now (from the save)</span></summary>
      <p class="livenote">Across the whole factory you're running at <b>{_pct(ratio)}</b> of potential
        &mdash; making <b>{_fmt(live_t)}</b> of a possible <b>{_fmt(pot_t)}</b> items/min
        ({a["lines_stalled"]} of {a["lines_total"]} lines below full uptime).
        <span class="tip" tabindex="0">Potential vs Live<span class="tip-bubble">
        <b>Potential</b> = nameplate: machines &times; clock, assuming every input is fully supplied.
        <b>Live</b> = what the machines have actually been producing, from each machine's measured
        uptime in the save. A big gap means starved inputs or backed-up outputs, not missing machines.</span></span></p>
      <div class="scroll">
      <table class="grid">
        <thead><tr><th>Line</th><th class="num">Machines</th><th>Building</th>
        <th class="num">Potential/min</th><th class="num">Live/min</th><th>Uptime</th><th class="num">Power</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
      </div>
    </details>
    """


# --------------------------------------------------------------- item flows ----
def _item_flows_section(a: dict) -> str:
    rows = []
    for f in a["item_flows"]:
        net = f["net"]
        if f["raw"]:
            badge = f'<span class="fbadge raw">raw &middot; {_fmt(f["used"])}/min drawn</span>'
        else:
            netcls = "pos" if net > 0.5 else ("neg" if net < -0.5 else "bal")
            sign = "+" if net >= 0 else ""
            badge = (f'<span class="fbadge">{_fmt(f["made"])} made</span>'
                     f'<span class="fbadge">{_fmt(f["used"])} used</span>'
                     f'<span class="fbadge {netcls}">{sign}{_fmt(net)} net</span>')
        makers = "".join(
            f'<li><b>{m["count"]}&times;</b> {html.escape(m["recipe"])}'
            f'<span class="r">{_fmt(m["rate"])}/min</span></li>' for m in f["makers"]
        ) or '<li class="dim">&mdash; raw / not made here &mdash;</li>'
        users = "".join(
            f'<li><b>{u["count"]}&times;</b> {html.escape(u["recipe"])}'
            f'<span class="r">{_fmt(u["rate"])}/min</span></li>' for u in f["users"]
        ) or '<li class="dim">&mdash; final product / unused &mdash;</li>'
        rows.append(
            f'<details class="iflow" data-name="{html.escape(f["item"].lower())}">'
            f'<summary><span class="iname">{html.escape(f["item"])}</span>{badge}</summary>'
            f'<div class="iflow-body"><div class="col mk"><h4>Made by</h4><ul>{makers}</ul></div>'
            f'<div class="col us"><h4>Used by</h4><ul>{users}</ul></div></div></details>'
        )
    return f"""
    <details class="panel">
      <summary><h2>Item flows</h2><span class="hint">who makes &amp; uses each item &middot; open, then search</span></summary>
      <input id="iflow-search" class="search" type="search" placeholder="Search an item&hellip;  (e.g. Cable)" oninput="filterFlows(this.value)">
      <div id="iflow-list">{''.join(rows)}</div>
    </details>
    """


# ---------------------------------------------------------------- math help ----
def _math_section(a: dict) -> str:
    # a couple of worked examples pulled from this very factory
    return f"""
    <details class="panel">
      <summary><h2>How the numbers work</h2><span class="hint">the exact math, no black box</span></summary>
      <div class="math">
        <p>Every rate is <b>items per minute</b>. A recipe lists a quantity per craft and a craft time in seconds, so:</p>
        <p class="eq">rate&nbsp;=&nbsp;quantity&nbsp;&times;&nbsp;60&nbsp;&divide;&nbsp;craft&nbsp;time&nbsp;(seconds)</p>
        <p class="ex">Example &mdash; a Screw Constructor: 4 screws every 6&nbsp;s = 4&nbsp;&times;&nbsp;60&nbsp;&divide;&nbsp;6 = <b>40 screws/min</b>. Your 12 of them = <b>480/min</b>.</p>

        <p>For each item I add up everything that <b>makes</b> it and everything that <b>uses</b> it:</p>
        <p class="eq">supplied&nbsp;=&nbsp;made&nbsp;&divide;&nbsp;needed</p>
        <p class="ex">Example &mdash; Steel Beam: made 60/min, needed 78/min (Versatile Framework 60 + Encased Beam 18). 60&nbsp;&divide;&nbsp;78 = <b>77% supplied</b> &rarr; starved.</p>

        <p>A line's <b>efficiency</b> is set by its most-starved input (raw ore is assumed always available):</p>
        <p class="eq">efficiency&nbsp;=&nbsp;the&nbsp;lowest&nbsp;&ldquo;supplied&rdquo;&nbsp;among&nbsp;its&nbsp;inputs&nbsp;(capped&nbsp;at&nbsp;100%)</p>
        <p class="ex">This is first-order: it uses each input's nameplate output and doesn't chain multiple starvations together. It's honest about that so the number stays easy to reason about.</p>

        <p><b>Power</b> uses the in-game rule that underclocking saves more than linearly:</p>
        <p class="eq">power&nbsp;=&nbsp;base&nbsp;MW&nbsp;&times;&nbsp;clock<sup>1.6</sup></p>
        <p class="ex">Your machines are all at 100% clock, so power is just base &times; machine count. Total: <b>{_fmt(a["total_power"])} MW</b>.</p>
      </div>
    </details>
    """


# ------------------------------------------------------------------- page ----
def render_html(a: dict, book: RecipeBook, save_name: str) -> str:
    nodes, edges, gw, gh = _layout(a["nodes"], a["edges"])
    graph_data = json.dumps({"nodes": nodes, "edges": edges,
                             "width": gw, "height": gh})

    total_machines = sum(a["building_counts"].values())
    session = html.escape(a.get("session") or "Factory")
    bc = a["building_counts"]
    bstrip = " &middot; ".join(f'{v} {html.escape(k)}' for k, v in
                               sorted(bc.items(), key=lambda kv: -kv[1]))

    paused = a.get("paused_recipes") or {}
    if paused:
        n = sum(paused.values())
        detail = ", ".join(f'{v}&times; {html.escape(k)}' for k, v in
                           sorted(paused.items(), key=lambda kv: -kv[1]))
        paused_html = (f'<div class="paused"><b>{n} machine(s) toggled off</b> '
                       f'&mdash; excluded from the math: {detail}</div>')
    else:
        paused_html = ""

    return (_PAGE
            .replace("__PAUSED__", paused_html)
            .replace("__SESSION__", session)
            .replace("__SAVE__", html.escape(save_name))
            .replace("__MACHINES__", str(total_machines))
            .replace("__RECIPES__", str(a["lines_total"]))
            .replace("__POWER__", _fmt(a["total_power"]))
            .replace("__BSTRIP__", bstrip)
            .replace("__CARDS__", _cards(a))
            .replace("__BOTTLENECK__", _bottleneck_section(a))
            .replace("__EFFTABLE__", _eff_table(a))
            .replace("__ITEMFLOWS__", _item_flows_section(a))
            .replace("__MATH__", _math_section(a))
            .replace("__GRAPHDATA__", graph_data))


def render_math_md(a: dict, book: RecipeBook) -> str:
    top = a["bottlenecks"][0] if a["bottlenecks"] else None
    lines = [
        "# How this factory report is calculated",
        "",
        "Everything is in **items per minute**. No numbers are hidden; here is every formula.",
        "",
        "## 1. Rate of a single machine",
        "```",
        "rate = quantity_per_craft * 60 / craft_time_seconds",
        "```",
        "A Screw Constructor makes 4 screws per 6 s = 4 * 60 / 6 = **40 screws/min**.",
        "",
        "## 2. Item balance across the whole factory",
        "```",
        "made[item]     = sum over producers of (machines * rate_out)",
        "needed[item]   = sum over consumers of (machines * rate_in)",
        "supplied[item] = made / needed        (>= 100% is healthy)",
        "```",
        "",
        "## 3. Line efficiency",
        "```",
        "efficiency(line) = min over its inputs of supplied[input]   (capped at 100%)",
        "```",
        "Raw resources (ore, coal, water, leaves) are assumed fully supplied. This is a",
        "first-order measure: it uses each input's nameplate output and does not chain",
        "multiple starvations together.",
        "",
        "## 4. Power",
        "```",
        "power(line) = base_MW * sum over machines of clock**1.6",
        "```",
        "Underclocking a machine saves power faster than it cuts output (exponent 1.6),",
        "which is why 'round up and underclock the last machine' is a real saving.",
        "",
        "## 5. Bottleneck ranking",
        "Items where `supplied < 100%`, sorted by lowest supplied first, then biggest",
        "shortfall. The smallest fix is `ceil(shortfall / output_per_machine)` more machines.",
        "",
    ]
    if top:
        lines += [
            "### This factory's biggest bottleneck",
            f"- **{top['item']}** — running at {round(top['ratio']*100)}%, "
            f"made {_fmt(top['produced'])}/min vs needed {_fmt(top['consumed'])}/min "
            f"({_fmt(top['deficit'])}/min short).",
            f"- Fix: add {top['fix_add']} {top['fix_building']} on {top['fix_recipe']}.",
            "",
        ]
    lines += [
        "## Graph metrics",
        "- **Bottleneck (weakest link):** lowest supply ratio in the graph.",
        "- **Longest chain (longest path):** most steps from a raw resource to a product.",
        "- **Biggest hub (out-degree):** the item feeding the most lines.",
        "- **Sub-factories (connected components):** machine groups that connect to each",
        "  other but not to the rest (your biomass chain is separate).",
        "- **Sources / sinks:** raw inputs (in-degree 0) and final products (out-degree 0).",
        "",
    ]
    return "\n".join(lines)


# The CSS/JS live as plain strings (no f-strings) to avoid brace escaping.
_PAGE = r"""<title>__SESSION__ &middot; Factory Graph</title>
<style>
:root{
  --bg:#f3f1ec; --panel:#ffffff; --panel2:#f6f4ef; --ink:#1b2028; --muted:#5d6773;
  --line:#e2ddd3; --accent:#c05617; --accent-ink:#c05617;
  --good:#2f9e44; --warn:#b8860b; --crit:#c8371f;
  --raw:#7a6a55; --grid:#eee9df;
  --shadow:0 1px 2px rgba(20,20,20,.06),0 8px 24px rgba(20,20,20,.05);
  --mono:ui-monospace,"Cascadia Code","SFMono-Regular",Consolas,monospace;
  --sans:"Segoe UI",system-ui,-apple-system,Roboto,sans-serif;
}
@media (prefers-color-scheme:dark){
  :root{
    --bg:#0f141b; --panel:#161d27; --panel2:#1b2430; --ink:#e7edf4; --muted:#93a1b2;
    --line:#26303d; --accent:#f6963c; --accent-ink:#f9a95a;
    --good:#3fb950; --warn:#d9a21b; --crit:#f06a4d; --raw:#9c8a70; --grid:#1a232f;
    --shadow:0 1px 2px rgba(0,0,0,.4),0 10px 30px rgba(0,0,0,.35);
  }
}
:root[data-theme="light"]{
  --bg:#f3f1ec; --panel:#ffffff; --panel2:#f6f4ef; --ink:#1b2028; --muted:#5d6773;
  --line:#e2ddd3; --accent:#c05617; --accent-ink:#c05617;
  --good:#2f9e44; --warn:#b8860b; --crit:#c8371f; --raw:#7a6a55; --grid:#eee9df;
}
:root[data-theme="dark"]{
  --bg:#0f141b; --panel:#161d27; --panel2:#1b2430; --ink:#e7edf4; --muted:#93a1b2;
  --line:#26303d; --accent:#f6963c; --accent-ink:#f9a95a;
  --good:#3fb950; --warn:#d9a21b; --crit:#f06a4d; --raw:#9c8a70; --grid:#1a232f;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);
  line-height:1.5;-webkit-font-smoothing:antialiased}
.wrap{max-width:1160px;margin:0 auto;padding:28px 20px 80px}
a{color:var(--accent-ink)}
h1,h2{text-wrap:balance}
.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
.num{text-align:right;font-family:var(--mono);font-variant-numeric:tabular-nums;white-space:nowrap}

/* header */
.top{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px 16px;
  border-bottom:2px solid var(--line);padding-bottom:16px;margin-bottom:22px}
.eyebrow{font-family:var(--mono);text-transform:uppercase;letter-spacing:.16em;
  font-size:12px;color:var(--accent-ink);font-weight:600}
.top h1{margin:2px 0 0;font-size:30px;letter-spacing:-.01em;width:100%}
.top .save{color:var(--muted);font-family:var(--mono);font-size:13px}
.stats{margin-left:auto;display:flex;gap:22px;flex-wrap:wrap}
.stat b{font-family:var(--mono);font-size:19px;font-variant-numeric:tabular-nums}
.stat span{display:block;font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}
.bstrip{width:100%;color:var(--muted);font-size:13px;font-family:var(--mono);margin-top:4px}
.paused{width:100%;color:var(--muted);font-size:12.5px;margin-top:6px;padding:6px 10px;
  border:1px dashed var(--edge);border-radius:8px;background:var(--box)}
.paused b{color:var(--ink)}
.livenote{font-size:13px;color:var(--muted);margin:10px 0 0;padding:10px 12px;
  background:var(--panel2);border:1px solid var(--line);border-radius:8px}
.livenote b{color:var(--ink)}

/* cards */
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px;margin-bottom:22px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;
  padding:16px 16px 14px;box-shadow:var(--shadow);border-left:4px solid var(--line)}
.card.status-good{border-left-color:var(--good)}
.card.status-warn{border-left-color:var(--warn)}
.card.status-crit{border-left-color:var(--crit)}
.card-k{font-size:13px;color:var(--muted);display:flex;gap:6px;align-items:baseline;flex-wrap:wrap}
.card-k .ghost{font-size:11px;opacity:.6;font-family:var(--mono)}
.card-v{font-size:24px;font-weight:650;margin:6px 0 3px;letter-spacing:-.01em}
.card-s{font-size:12.5px;color:var(--muted)}
.card-s.mono{font-size:11.5px;line-height:1.45}

/* tooltip */
.tip{position:relative;border-bottom:1px dotted var(--muted);cursor:help;font-weight:600;color:var(--ink)}
.tip-bubble{position:absolute;left:0;top:135%;z-index:20;width:250px;background:var(--panel2);
  color:var(--ink);border:1px solid var(--line);border-radius:9px;padding:10px 12px;font-size:12px;
  font-weight:400;line-height:1.5;box-shadow:var(--shadow);opacity:0;visibility:hidden;
  transform:translateY(-4px);transition:.14s}
.tip:hover .tip-bubble,.tip:focus .tip-bubble{opacity:1;visibility:visible;transform:none}

/* panels */
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;
  padding:18px 20px;margin:16px 0;box-shadow:var(--shadow)}
.panel h2{margin:0;font-size:17px;display:inline}
.hint{color:var(--muted);font-size:12.5px;margin-left:10px;font-weight:400}
details.panel>summary{cursor:pointer;list-style:none;display:flex;align-items:baseline;gap:6px}
details.panel>summary::-webkit-details-marker{display:none}
details.panel>summary::before{content:"\25B8";color:var(--accent-ink);font-size:12px;margin-right:4px}
details.panel[open]>summary::before{content:"\25BE"}

/* bottleneck lead */
.bn-lead{border:1px solid var(--line);border-left:5px solid var(--crit);border-radius:10px;
  padding:14px 16px;margin:14px 0;background:var(--panel2)}
.bn-lead.status-warn{border-left-color:var(--warn)}
.bn-lead.status-good{border-left-color:var(--good)}
.bn-tag{font-family:var(--mono);text-transform:uppercase;letter-spacing:.12em;font-size:11px;color:var(--crit)}
.bn-name{font-size:22px;font-weight:700;margin:2px 0 6px}
.bn-line{font-size:14px;margin:3px 0}
.bn-fix{font-size:14px;margin-top:8px;padding-top:8px;border-top:1px dashed var(--line);color:var(--ink)}

/* tables */
.scroll{overflow-x:auto}
table.grid{border-collapse:collapse;width:100%;font-size:13.5px;margin-top:10px}
table.grid th{text-align:left;color:var(--muted);font-weight:600;font-size:11.5px;
  text-transform:uppercase;letter-spacing:.05em;padding:6px 10px;border-bottom:1px solid var(--line)}
table.grid th.num{text-align:right}
table.grid td{padding:7px 10px;border-bottom:1px solid var(--grid)}
table.grid tbody tr:hover{background:var(--panel2)}
td.neg{color:var(--crit)}
tr.status-crit td:first-child{box-shadow:inset 3px 0 var(--crit)}
tr.status-warn td:first-child{box-shadow:inset 3px 0 var(--warn)}
tr.status-good td:first-child{box-shadow:inset 3px 0 var(--good)}
.effcell{display:flex;align-items:center;gap:8px;min-width:130px}
.bar{flex:1;height:7px;background:var(--grid);border-radius:4px;overflow:hidden}
.fill{display:block;height:100%}
.fill.s-good{background:var(--good)}.fill.s-warn{background:var(--warn)}.fill.s-crit{background:var(--crit)}
.ok{color:var(--good)}

/* math */
.math{font-size:14px;margin-top:8px}
.math .eq{font-family:var(--mono);background:var(--panel2);border:1px solid var(--line);
  border-radius:8px;padding:10px 12px;font-size:13px}
.math .ex{color:var(--muted);font-size:13px;margin:4px 0 16px;padding-left:12px;border-left:2px solid var(--line)}

/* item flows */
.search{width:100%;max-width:340px;margin:12px 0 8px;padding:8px 12px;font:inherit;font-size:14px;
  background:var(--panel2);color:var(--ink);border:1px solid var(--line);border-radius:8px}
.iflow{border-bottom:1px solid var(--grid)}
.iflow>summary{cursor:pointer;list-style:none;display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:8px 2px}
.iflow>summary::-webkit-details-marker{display:none}
.iflow>summary::before{content:"\25B8";color:var(--accent-ink);font-size:11px}
.iflow[open]>summary::before{content:"\25BE"}
.iname{font-weight:600;font-size:14px;min-width:160px}
.fbadge{font-family:var(--mono);font-size:11.5px;padding:2px 7px;border-radius:20px;
  background:var(--panel2);border:1px solid var(--line);color:var(--muted)}
.fbadge.pos{color:var(--good);border-color:var(--good)}
.fbadge.neg{color:var(--crit);border-color:var(--crit)}
.fbadge.bal{color:var(--muted)}
.fbadge.raw{color:var(--raw);border-color:var(--raw)}
.iflow-body{display:flex;gap:24px;flex-wrap:wrap;padding:4px 0 12px 18px}
.iflow-body .col{flex:1;min-width:220px}
.iflow-body h4{margin:0 0 4px;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.iflow-body ul{list-style:none;margin:0;padding:0}
.iflow-body li{display:flex;justify-content:space-between;gap:10px;font-size:13px;padding:2px 0}
.iflow-body .r{font-family:var(--mono);color:var(--muted);font-variant-numeric:tabular-nums}
.iflow-body .dim{color:var(--muted);font-style:italic}
.col.mk h4{color:var(--good)}.col.us h4{color:var(--warn)}

/* graph */
.graphwrap{background:var(--panel);border:1px solid var(--line);border-radius:12px;
  box-shadow:var(--shadow);margin:16px 0;overflow:hidden}
.graphbar{display:flex;align-items:center;gap:14px;flex-wrap:wrap;padding:12px 16px;border-bottom:1px solid var(--line)}
.graphbar h2{margin:0;font-size:17px}
.legend{display:flex;gap:14px;flex-wrap:wrap;margin-left:auto;font-size:12px;color:var(--muted)}
.legend i{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:5px;vertical-align:-1px}
.controls{display:flex;gap:6px}
.controls button{font:inherit;font-size:12px;background:var(--panel2);color:var(--ink);
  border:1px solid var(--line);border-radius:7px;padding:4px 10px;cursor:pointer}
.controls button:hover{border-color:var(--accent)}
#stage{width:100%;height:600px;display:block;cursor:grab;touch-action:none;background:
  radial-gradient(circle at 1px 1px,var(--grid) 1px,transparent 0);background-size:26px 26px}
#stage.grab{cursor:grabbing}
.enode rect{stroke-width:1.5px}
.enode text{font-family:var(--sans);fill:var(--ink)}
.enode .sub{fill:var(--muted);font-family:var(--mono)}
.eedge{fill:none;stroke:var(--muted);opacity:.42}
.eedge-label{fill:var(--muted);font-family:var(--mono);font-size:10px;opacity:0}
.dim{opacity:.12}
.hl .eedge{opacity:.95;stroke:var(--accent)}
.foot{color:var(--muted);font-size:12px;margin-top:28px;text-align:center}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
</style>

<div class="wrap">
  <header class="top">
    <div class="eyebrow">FICSIT &middot; Factory Analysis</div>
    <h1>__SESSION__</h1>
    <div class="save">read from __SAVE__</div>
    <div class="stats">
      <div class="stat"><b>__MACHINES__</b><span>machines</span></div>
      <div class="stat"><b>__RECIPES__</b><span>recipes</span></div>
      <div class="stat"><b>__POWER__</b><span>MW power</span></div>
    </div>
    <div class="bstrip">__BSTRIP__</div>
    __PAUSED__
  </header>

  __CARDS__

  __BOTTLENECK__

  <section class="graphwrap">
    <div class="graphbar">
      <h2>Your factory as a graph</h2>
      <div class="controls">
        <button id="fit">Fit</button><button id="zin">+</button><button id="zout">&minus;</button>
      </div>
      <div class="legend">
        <span><i style="background:var(--raw)"></i>raw</span>
        <span><i style="background:var(--good)"></i>full</span>
        <span><i style="background:var(--warn)"></i>starved</span>
        <span><i style="background:var(--crit)"></i>critical / missing</span>
        <span>arrow = item flow &middot; hover a box</span>
      </div>
    </div>
    <svg id="stage"></svg>
  </section>

  __EFFTABLE__
  __ITEMFLOWS__
  __MATH__

  <p class="foot">Read straight from your save &middot; recipe data in <span class="mono">recipes.yaml</span> &middot;
  raw ore assumed fully supplied &middot; power at 100% clock.</p>
</div>

<script>
const G = __GRAPHDATA__;
const svg = document.getElementById('stage');
const SVGNS='http://www.w3.org/2000/svg';
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
function color(status){
  return {good:css('--good'),warn:css('--warn'),crit:css('--crit'),
          raw:css('--raw'),gap:css('--crit')}[status]||css('--muted');
}
const byId={}; G.nodes.forEach(n=>byId[n.id]=n);

// viewport group
const vp=document.createElementNS(SVGNS,'g'); svg.appendChild(vp);
// arrow marker
svg.insertAdjacentHTML('afterbegin',
 '<defs><marker id="arw" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto">'+
 '<path d="M0,0 L8,3 L0,6 Z" fill="'+css('--muted')+'"></path></marker></defs>');

const edgeEls=[];
G.edges.forEach(e=>{
  const s=byId[e.from], t=byId[e.to]; if(!s||!t) return;
  const x1=s.x+s.w, y1=s.y+s.h/2, x2=t.x, y2=t.y+t.h/2;
  const dx=Math.max(40,(x2-x1)/2);
  const p=document.createElementNS(SVGNS,'path');
  p.setAttribute('d',`M${x1},${y1} C${x1+dx},${y1} ${x2-dx},${y2} ${x2},${y2}`);
  p.setAttribute('class','eedge'); p.setAttribute('marker-end','url(#arw)');
  p.setAttribute('stroke-width',Math.max(1,Math.min(6,Math.log2(1+e.rate))).toFixed(1));
  p.dataset.from=e.from; p.dataset.to=e.to;
  vp.appendChild(p); edgeEls.push(p);
  const lbl=document.createElementNS(SVGNS,'text');
  lbl.setAttribute('x',(x1+x2)/2); lbl.setAttribute('y',(y1+y2)/2-3);
  lbl.setAttribute('text-anchor','middle'); lbl.setAttribute('class','eedge-label');
  lbl.textContent=e.item+' '+e.rate+'/m'; lbl.dataset.from=e.from; lbl.dataset.to=e.to;
  vp.appendChild(lbl);
});

function wrap(s,max){ if(s.length<=max) return [s];
  const w=s.split(' '),lines=[]; let cur='';
  w.forEach(x=>{ if((cur+' '+x).trim().length>max){lines.push(cur.trim());cur=x;} else cur+=' '+x;});
  if(cur.trim())lines.push(cur.trim()); return lines.slice(0,2);
}
const nodeEls={};
G.nodes.forEach(n=>{
  const g=document.createElementNS(SVGNS,'g'); g.setAttribute('class','enode');
  g.setAttribute('transform',`translate(${n.x},${n.y})`);
  const r=document.createElementNS(SVGNS,'rect');
  r.setAttribute('width',n.w); r.setAttribute('height',n.h); r.setAttribute('rx',10);
  const c=color(n.status);
  r.setAttribute('fill',css('--panel')); r.setAttribute('stroke',c);
  if(n.kind==='gap'){ r.setAttribute('stroke-dasharray','5 4'); }
  if(n.is_product){ r.setAttribute('stroke-width','3'); }
  g.appendChild(r);
  // severity stripe
  const stripe=document.createElementNS(SVGNS,'rect');
  stripe.setAttribute('width',5); stripe.setAttribute('height',n.h);
  stripe.setAttribute('fill',c); stripe.setAttribute('rx',2); g.appendChild(stripe);

  const title=wrap(n.label,20);
  title.forEach((ln,i)=>{
    const t=document.createElementNS(SVGNS,'text');
    t.setAttribute('x',14); t.setAttribute('y',22+i*15); t.setAttribute('font-size',13);
    t.setAttribute('font-weight',630); t.textContent=ln; g.appendChild(t);
  });
  const sub=document.createElementNS(SVGNS,'text');
  sub.setAttribute('x',14); sub.setAttribute('y',n.h-12); sub.setAttribute('font-size',11);
  sub.setAttribute('class','sub');
  if(n.kind==='recipe'){
    sub.textContent=`${n.count}× ${n.building} · ${n.out}/m · ${Math.round(n.eff*100)}%`;
  }else if(n.kind==='raw'){ sub.textContent=`raw · ${n.rate}/m drawn`; }
  else{ sub.textContent=`needs ${n.needed}/m · not built`; }
  g.appendChild(sub);

  g.addEventListener('mouseenter',()=>highlight(n.id));
  g.addEventListener('mouseleave',clear);
  vp.appendChild(g); nodeEls[n.id]=g;
});

function highlight(id){
  const keep=new Set([id]);
  edgeEls.forEach(p=>{ if(p.dataset.from===id||p.dataset.to===id){keep.add(p.dataset.from);keep.add(p.dataset.to);} });
  svg.classList.add('hl');
  Object.values(nodeEls).forEach(g=>g.classList.toggle('dim',!keep.has(idOf(g))));
  vp.querySelectorAll('.eedge').forEach(p=>{
    const on=p.dataset.from===id||p.dataset.to===id;
    p.classList.toggle('dim',!on); p.style.stroke=on?css('--accent'):'';
  });
  vp.querySelectorAll('.eedge-label').forEach(l=>{
    l.style.opacity=(l.dataset.from===id||l.dataset.to===id)?'1':'0';});
}
function idOf(g){ return Object.keys(nodeEls).find(k=>nodeEls[k]===g); }
function clear(){
  svg.classList.remove('hl');
  Object.values(nodeEls).forEach(g=>g.classList.remove('dim'));
  vp.querySelectorAll('.eedge').forEach(p=>{p.classList.remove('dim');p.style.stroke='';});
  vp.querySelectorAll('.eedge-label').forEach(l=>l.style.opacity='0');
}

// pan + zoom
let vx=0,vy=0,scale=1;
function apply(){ vp.setAttribute('transform',`translate(${vx},${vy}) scale(${scale})`); }
function fit(){
  const box=svg.getBoundingClientRect();
  const s=Math.min(box.width/G.width, box.height/G.height, 1.1)*0.94;
  scale=s; vx=(box.width-G.width*s)/2; vy=(box.height-G.height*s)/2; apply();
}
let drag=null;
svg.addEventListener('pointerdown',e=>{drag={x:e.clientX-vx,y:e.clientY-vy};svg.classList.add('grab');svg.setPointerCapture(e.pointerId);});
svg.addEventListener('pointermove',e=>{if(drag){vx=e.clientX-drag.x;vy=e.clientY-drag.y;apply();}});
svg.addEventListener('pointerup',e=>{drag=null;svg.classList.remove('grab');});
svg.addEventListener('wheel',e=>{e.preventDefault();
  const box=svg.getBoundingClientRect(),mx=e.clientX-box.left,my=e.clientY-box.top;
  const f=e.deltaY<0?1.12:1/1.12,ns=Math.max(0.2,Math.min(3,scale*f));
  vx=mx-(mx-vx)*(ns/scale); vy=my-(my-vy)*(ns/scale); scale=ns; apply();
},{passive:false});
document.getElementById('fit').onclick=fit;
document.getElementById('zin').onclick=()=>{scale=Math.min(3,scale*1.2);apply();};
document.getElementById('zout').onclick=()=>{scale=Math.max(0.2,scale/1.2);apply();};
requestAnimationFrame(fit);

// item-flow search filter
function filterFlows(q){
  q=(q||'').trim().toLowerCase();
  document.querySelectorAll('#iflow-list .iflow').forEach(d=>{
    d.hidden = q && d.dataset.name.indexOf(q)===-1;
  });
}
</script>
"""
