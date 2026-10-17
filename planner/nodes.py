"""Resolve every extractor in a save to resource + purity + rate.
Node table: planner/node_data.py (GreyHak sat_sav_parse, SCIM data). Matched by
mExtractableResource path name first, then nearest node by world position."""
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'vendor'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import sav_parse as sp
from planner.extract import _short
from planner.node_data import RESOURCE_PURITY

EXTRACTORS = {
    'Build_MinerMk1_C': ('MinerMk1', 'Mk1', 60), 'Build_MinerMk2_C': ('MinerMk2', 'Mk2', 120),
    'Build_MinerMk3_C': ('MinerMk3', 'Mk3', 240), 'Build_OilPump_C': ('OilPump', 'Mk1', 120),
    'Build_WaterPump_C': ('WaterPump', 'Mk1', 120),
    'Build_FrackingExtractor_C': ('FrackingExtractor', 'Mk1', 60),
    'Build_FrackingSmasher_C': ('FrackingSmasher', 'Mk1', 0),
    'Build_ResourceWellExtractor_C': ('ResourceWellExtractor', 'Mk1', 60),
}
NAMES = {'Desc_OreIron_C': 'Iron Ore', 'Desc_Stone_C': 'Limestone', 'Desc_Coal_C': 'Coal',
         'Desc_Water_C': 'Water', 'Desc_OreCopper_C': 'Copper Ore', 'Desc_LiquidOil_C': 'Crude Oil',
         'Desc_NitrogenGas_C': 'Nitrogen Gas', 'Desc_Geyser_C': 'Geyser', 'Desc_SAM_C': 'SAM',
         'Desc_OreGold_C': 'Caterium Ore', 'Desc_RawQuartz_C': 'Raw Quartz',
         'Desc_OreBauxite_C': 'Bauxite', 'Desc_Sulfur_C': 'Sulfur', 'Desc_OreUranium_C': 'Uranium'}
MULT = {1: ('impure', .5), 2: ('normal', 1.), 3: ('pure', 2.)}
TOL_M = 200.0

def _table():
    t = []
    for k, (res, pur, (x, y, z), core) in RESOURCE_PURITY.items():
        t.append((k.split('.')[-1], x / 100, y / 100, res, pur.value))
    return t

def resolve_nodes(save_path):
    parsed = sp.readFullSaveFile(save_path)
    gv = sp.getPropertyValue
    tab = _table()
    byname = {n: r for r in tab for n in [r[0]]}
    out = []
    for lvl in parsed.levels:
        hs = lvl.actorAndComponentObjectHeaders
        for i, o in enumerate(lvl.objects):
            h = hs[i] if i < len(hs) else None
            cls = _short(getattr(h, 'typePath', '') or '')
            if cls not in EXTRACTORS:
                continue
            p = getattr(h, 'position', None) or [0, 0, 0]
            pos = [p[0] / 100, p[1] / 100, p[2] / 100]
            b, mk, base = EXTRACTORS[cls]
            props = o.properties
            clock = gv(props, 'mCurrentPotential')
            clock = 1.0 if clock is None else clock
            d, t = gv(props, 'mLastProductivityMeasurementProduceDuration'), gv(props, 'mLastProductivityMeasurementDuration')
            up = (d / t) if d is not None and t else 0.0
            ref = gv(props, 'mExtractableResource')
            pn = (getattr(ref, 'pathName', '') or '').split('.')[-1]
            m = byname.get(pn)
            dist = 0.0
            if m is None and cls != 'Build_WaterPump_C':
                best = min(tab, key=lambda r: math.hypot(r[1] - pos[0], r[2] - pos[1]))
                dist = math.hypot(best[1] - pos[0], best[2] - pos[1])
                m = best if dist <= TOL_M else None
            rec = {'pos': pos, 'building': b, 'mk': mk, 'clock': clock, 'live_uptime': up,
                   'resource': None, 'purity': None, 'rate_per_min': 0.0, 'node': pn, 'match_dist_m': dist}
            if cls == 'Build_WaterPump_C':
                rec.update(resource='Water', purity='normal', rate_per_min=base * clock)
            elif m:
                rec['resource'] = NAMES.get(m[3], m[3])
                rec['purity'], mult = MULT.get(m[4], ('normal', 1.))
                rec['rate_per_min'] = base * mult * clock
            out.append(rec)
    return out

if __name__ == '__main__':
    import glob, collections
    f = sorted(glob.glob((os.environ.get("SATISFACTORY_SAVE_SESSION", "") + "*.sav")), key=os.path.getmtime)[-1]
    r = resolve_nodes(f)
    print(f, len(r))
    tot = collections.defaultdict(float)
    for x in r: tot[x['resource']] += x['rate_per_min']
    for k, v in sorted(tot.items(), key=lambda a: str(a[0])): print(f'{k}: {v:.0f}/min')
    print('COAL')
    for x in r:
        if x['resource'] == 'Coal':
            print([round(c) for c in x['pos']], x['mk'], x['clock'], x['purity'], x['rate_per_min'], round(x['live_uptime'], 2))
    print('UNMATCHED')
    for x in r:
        if not x['resource']: print(x['building'], [round(c) for c in x['pos']], x['node'])
