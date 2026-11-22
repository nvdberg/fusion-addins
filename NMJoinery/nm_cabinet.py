# NM Joinery - "NM Cabinet": a whole cabinet carcass with sections stacked top to bottom (clean-room).
# Built on NM Drawer: the same Maker (fully dimensioned sketches), the same finger / tab joints (NM Box feature), and
# drawer sections are NM Drawer banks whose opening sizes point at the cabinet's own parameters, so Change Parameters
# on the cabinet resizes the drawers too.
# Coordinates: x = width (left to right), y = depth (front y=0 to back), z = height (floor z=0). Fronts (false fronts,
# doors) sit in front of y=0 (frameless, full overlay). Lengths in cm inside Fusion, parameter values in mm.
import adsk.core, adsk.fusion, os, re, sys, json, traceback

CMD_ID = 'nmjCabinet'
PANEL_ID = 'SolidCreatePanel'
VI = adsk.core.ValueInput.createByString
NEW = adsk.fusion.FeatureOperations.NewBodyFeatureOperation
CUT = adsk.fusion.FeatureOperations.CutFeatureOperation

DOORS = ['Auto (two when wider than 600 mm)', 'One', 'Two']
BASES = ['Toe kick notched in the sides', 'Separate plinth', 'None (flat bottom: wall cabinet, legs)']
TOPS = ['Full top panel', 'Two stretchers (under a counter top)']
KINDS = ['Drawers', 'Doors', 'Open shelves']
MAX_SECTIONS = 4

# Stock: 3/4" Baltic birch = 18 mm actual (carcass, fronts), back 1/4" BB = 6 mm in a groove.
SECTION = {'kind': 0, 'sh': '200 mm', 'nd': 3, 'heights': 1, 'step': '25 mm', 'slide': 0, 'dpreset': '',
           'nsh': 1, 'adj': True, 'ndoor': 0}
DEFAULTS = {
    'name': 'Cabinet', 'w': '600 mm', 'h': '870 mm', 'd': '560 mm', 't': '18 mm',
    'bk': '6 mm', 'bgd': '6 mm', 'bin': '10 mm', 'base': 0, 'kh': '100 mm', 'kd': '75 mm', 'top': 0, 'sw': '100 mm',
    'rev': '3 mm', 'ft': '18 mm', 'relief': 1, 'flat': True, 'ns': 1,
    'sections': [dict(SECTION) for _ in range(MAX_SECTIONS)],
}
COMMENTS = {
    'w': 'outside width', 'h': 'outside height (floor to top, base included)', 'd': 'outside depth (sides)',
    't': 'carcass board thickness', 'bk': 'back panel thickness', 'bgd': 'back groove depth',
    'bin': 'back panel set in from the back edge', 'gg': 'groove clearance per side', 'ge': 'room at panel edges',
    'rev': 'gap between fronts (doors / drawer fronts)', 'ft': 'front thickness (doors / drawer fronts)',
    'kh': 'toe kick / plinth height', 'kd': 'toe kick / plinth set back from the front', 'sw': 'stretcher width',
    'z0': 'inside bottom (top of the bottom panel)', 'z1': 'inside top (underside of the top)',
    'id': 'inside depth (front edge to the back panel)',
    'pin': 'shelf pin holes in from the front and back edge', 'pp': 'shelf pin hole pitch (32 mm system)',
    'pdia': 'shelf pin hole diameter', 'pdep': 'shelf pin hole depth', 'pm': 'first / last shelf pin hole from '
    'the section bottom / top',
}

HERE = os.path.dirname(os.path.abspath(__file__))
LAST = os.path.join(HERE, 'nm_cabinet_last.json')
nm = None           # the NMJoinery module (set by register)


def drw():
    return sys.modules['nm_drawer']


def sections(o):
    return [dict(SECTION, **s) for s in o['sections'][:int(o['ns'])]]


def geom(o):
    """The cabinet in numbers (mm): inside width / depth, inside bottom / top, each section's opening height and
    bottom (index 0 = top section)."""
    um = nm.design().unitsManager
    v = lambda e: um.evaluateExpression(e, 'mm') * 10
    t = v(o['t'])
    g = {'t': t, 'w': v(o['w']), 'h': v(o['h']), 'd': v(o['d'])}
    g['iw'] = g['w'] - 2 * t
    g['id'] = g['d'] - v(o['bin']) - v(o['bk'])
    g['z0'] = (v(o['kh']) if o['base'] in (0, 1) else 0) + t
    g['z1'] = g['h'] - t
    secs = sections(o)
    n = len(secs)
    s = [v(x['sh']) for x in secs[:-1]]
    s.append(g['z1'] - g['z0'] - sum(s) - (n - 1) * t)
    g['s'] = s
    g['b'] = [g['z0'] + sum(s[j] + t for j in range(k + 1, n)) for k in range(n)]
    return g


def slide_length(sp, depth, fallback):
    if sp.get('none'):
        return depth - 2          # no slides: the box runs to 2 mm short of the back
    if 'lengths' in sp:
        fits = [L for L in sp['lengths'] if L <= depth + 1e-6]
        return fits[-1] if fits else sp['lengths'][0]
    return min(fallback, depth)


def drawer_opts(o, k, P=None, g=None):
    """NM Drawer bank values for drawer section k (0 = top). P = cabinet parameter prefix (expressions), else
    numbers from g (for checking before anything exists)."""
    dr = drw()
    secs = sections(o)
    n, sct = len(secs), secs[k]
    d = dict(dr.DEFAULTS)
    if sct['dpreset']:
        d.update(dr.upgrade(dr.load_presets().get(sct['dpreset'], {})))
    sp = dr.SLIDES[sct['slide']]
    g = g or geom(o)
    um = nm.design().unitsManager
    if P:
        e = lambda x: re.sub(r'\{(\w+)\}', lambda m: P + m.group(1), x)
        ow, oh, od = e('{w} - 2 * {t}'), e('{s%d}' % (k + 1)), e('{id}')
    else:
        e = None
        ow, oh, od = ['%g mm' % x for x in (g['iw'], g['s'][k], g['id'])]
    num = lambda x: '%g mm' % x
    t, rev = (e('{t}'), e('{rev}')) if P else (o['t'], o['rev'])
    sl = slide_length(sp, g['id'], um.evaluateExpression(d['sl'], 'mm') * 10)
    names = [i for i, s in enumerate(secs) if s['kind'] == 0]
    name = o['name'] + (' drawer' if len(names) == 1 else ' S%d drawer' % (k + 1))
    d.update(size=1, nd=int(sct['nd']), heights=int(sct['heights']), step=sct['step'], slide=int(sct['slide']),
             name=name, ow=ow, oh=oh, od=od, sl=num(sl), top=False, flat=o['flat'],
             ff=True, ft=e('{ft}') if P else o['ft'], rev=rev,
             fs='%s - %s / 2' % (t, rev),
             ftop='%s - %s / 2' % (t if k == 0 else '%s / 2' % t, rev),
             fb='%s - %s / 2' % (t if k == n - 1 else '%s / 2' % t, rev))
    if sp['gap']:
        d['sg'], d['ob'] = sp['gap'], sp['below']
        d['ot'] = '3 mm' if sp.get('none') else dr.DEFAULTS['ot']
        if sp.get('none') and int(sct['nd']) > 1:     # stacked, nothing under them yet: same gap below as above
            d['ob'] = '3 mm'                         # (wooden runners will set this to the runner height)
    if 'line' in sp:
        d['sh'], d['sback'] = '%g mm' % sp['high'], '%g mm' % sp['back']
    if P:
        d['_x0'], d['_z0'] = e('{t}'), e('{b%d}' % (k + 1))
        if sp.get('none'):                      # no slide length to pick: the depth follows the cabinet
            d['sl'] = e('{id} - 2 mm')
    return d


def check(o):
    """Problems with the dialog values, in words (empty = fine)."""
    out = []
    try:
        g = geom(o)
    except Exception:
        return ['A size is not a valid length.']
    um = nm.design().unitsManager
    v = lambda e: um.evaluateExpression(e, 'mm') * 10
    t = g['t']
    if min(g['w'], g['h'], g['d'], t, v(o['bk'])) <= 0:
        return ['Sizes and thicknesses must be more than 0.']
    if g['iw'] < 100 or g['id'] < 100:
        out.append('The cabinet is too small inside (less than 100 mm wide or deep).')
    if not (1.5 <= v(o['bgd']) < t - 3):
        out.append('Back groove depth must be between 1.5 mm and the board thickness minus 3 mm.')
    if v(o['bin']) < 0:
        out.append('Back set in must be 0 or more.')
    if o['base'] in (0, 1) and (v(o['kh']) < 20 or v(o['kd']) < 0 or v(o['kd']) + 2 * t > g['d'] - 50):
        out.append('Toe kick / plinth: height at least 20 mm, set back 0 or more and well under the depth.')
    if o['top'] == 1 and not (30 <= v(o['sw']) < g['id'] / 2):
        out.append('Stretchers: at least 30 mm wide and less than half the depth.')
    if v(o['rev']) < 0 or v(o['rev']) > t:
        out.append('Gap between fronts: 0 to the board thickness.')
    secs = sections(o)
    for k, s in enumerate(g['s']):
        if s < 40:
            out.append('Section %d is only %g mm high: make the others lower or the cabinet higher.' % (k + 1, round(s, 1)))
    if out:
        return out
    dr = drw()
    for k, sct in enumerate(secs):
        if sct['kind'] == 0:
            for msg in dr.check(drawer_opts(o, k, g=g)):
                out.append('Section %d drawers: %s' % (k + 1, msg))
        elif sct['kind'] == 2 and not (0 <= int(sct['nsh']) <= 10):
            out.append('Section %d: 0 to 10 shelves.' % (k + 1))
    return out


def shelf_z(k, j, n_sh):
    """Bottom of shelf j (1-based) of n_sh evenly spaced in section k (1-based), as a {param} expression."""
    return '{b%d} + %d * ({s%d} - %d * {t}) / %d + %d * {t}' % (k, j, k, n_sh, n_sh + 1, j - 1)


def build(o):
    """Builds the cabinet from the dialog values o. Returns (occurrence, text lines)."""
    des = nm.design()
    nm.ensure_globals(des)
    dr = drw()
    P = dr.unique_prefix(des, o['name'])
    up = des.userParameters
    g = geom(o)
    secs = sections(o)
    n = len(secs)
    base, top = int(o['base']), int(o['top'])
    params = [(k, o[k]) for k in ('w', 'h', 'd', 't', 'bk', 'bgd', 'bin', 'rev', 'ft')]
    params += [('gg', 'nmj_gap'), ('ge', '1 mm')]
    if base in (0, 1):
        params += [('kh', o['kh']), ('kd', o['kd'])]
    if top == 1:
        params.append(('sw', o['sw']))
    params += [('z0', '{kh} + {t}' if base in (0, 1) else '{t}'), ('z1', '{h} - {t}'), ('id', '{d} - {bin} - {bk}')]
    for i, sct in enumerate(secs[:-1], 1):
        params.append(('s%d' % i, sct['sh']))
    params.append(('s%d' % n, '{z1} - {z0}' + ''.join(' - {s%d}' % j for j in range(1, n)) +
                   (' - %d * {t}' % (n - 1) if n > 1 else '')))
    for k in range(1, n + 1):
        params.append(('b%d' % k, '{z0}' + ''.join(' + {s%d} + {t}' % j for j in range(k + 1, n + 1))))
    if any(s['kind'] in (1, 2) and s['adj'] and int(s['nsh']) for s in secs):
        params += [('pin', '37 mm'), ('pp', '32 mm'), ('pdia', '5 mm'), ('pdep', '10 mm'), ('pm', '64 mm')]
    exp = lambda e: re.sub(r'\{(\w+)\}', lambda m: P + m.group(1), e)
    for k, e in params:
        c = COMMENTS.get(k) or ('section %s opening height (1 = top)' % k[1:] if k[0] == 's' else
                                'section %s: bottom of its opening' % k[1:])
        up.add(P + k, VI(exp(e)), 'mm', '%s: %s' % (o['name'], c))

    root = des.rootComponent
    occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    comp = occ.component
    comp.name = o['name']
    m = dr.Maker(comp, P)
    zs = '{kh}' if base == 1 else '0'
    sides = [m.box('Left', '0', '0', '{t}', '{d}', zs, '{h}'), m.box('Right', '{w} - {t}', '0', '{w}', '{d}', zs, '{h}')]
    if base == 0:
        m.box('Toe kick notch', '-1 mm', '-1 mm', '{w} + 1 mm', '{kd}', '-1 mm', '{kh}', CUT, sides)
    jointed = list(sides)
    jointed.append(m.box('Bottom', '{t}', '0', '{w} - {t}', '{d}', '{z0} - {t}', '{z0}'))
    if top == 0:
        jointed.append(m.box('Top', '{t}', '0', '{w} - {t}', '{d}', '{z1}', '{h}'))
    else:
        jointed.append(m.box('Front stretcher', '{t}', '0', '{w} - {t}', '{sw}', '{z1}', '{h}'))
        jointed.append(m.box('Back stretcher', '{t}', '{id} - {sw}', '{w} - {t}', '{id}', '{z1}', '{h}'))
    for k in range(1, n):                      # fixed shelf under section k, between it and the next one
        jointed.append(m.box('Fixed shelf %d' % k, '{t}', '0', '{w} - {t}', '{id} - {ge}', '{b%d} - {t}' % k, '{b%d}' % k))
    loose = []
    for k, sct in enumerate(secs, 1):
        nsh = int(sct['nsh']) if sct['kind'] in (1, 2) else 0
        for j in range(1, nsh + 1):
            z = shelf_z(k, j, nsh)
            if sct['adj']:     # rests on the nearest row of shelf pins (hole centre + pin radius)
                z = '{b%d} + {pm} + {pp} * floor((%s - {b%d} - {pm}) / {pp} + 0.5) + {pdia} / 2' % (k, z, k)
                loose.append((k, j, z))
            else:
                jointed.append(m.box('Shelf %d.%d' % (k, j), '{t}', '0', '{w} - {t}', '{id} - {ge}', z, '%s + {t}' % z))
    if base == 0:
        jointed.append(m.box('Toe kick', '{t}', '{kd}', '{w} - {t}', '{kd} + {t}', '0', '{kh}'))
    exprs = dict(nm.DEFAULT_EXPR)
    exprs['relief'] = str(int(o['relief']))
    made, lines = nm.create_all([b.createForAssemblyContext(occ) for b in jointed], exprs)
    if base == 1:
        plinth = [m.box('Plinth front', '0', '{kd}', '{w}', '{kd} + {t}', '0', '{kh}'),
                  m.box('Plinth back', '0', '{d} - {t}', '{w}', '{d}', '0', '{kh}'),
                  m.box('Plinth left', '0', '{kd} + {t}', '{t}', '{d} - {t}', '0', '{kh}'),
                  m.box('Plinth right', '{w} - {t}', '{kd} + {t}', '{w}', '{d} - {t}', '0', '{kh}')]
        made2, lines2 = nm.create_all([b.createForAssemblyContext(occ) for b in plinth], exprs)
        lines += lines2
    body = m.body
    grooved = [body('Left'), body('Right'), body('Bottom')] + ([body('Top')] if top == 0 else [])
    m.box('Back groove', '{t} - {bgd}', '{id} - {gg}', '{w} - {t} + {bgd}', '{id} + {bk} + {gg}', '{z0} - {bgd}',
          '{z1} + {bgd}' if top == 0 else '{h} + 1 mm', CUT, grooved)
    m.box('Back', '{t} - {bgd} + {ge}', '{id}', '{w} - {t} + {bgd} - {ge}', '{id} + {bk}', '{z0} - {bgd} + {ge}',
          '{z1} + {bgd} - {ge}' if top == 0 else '{h}')
    for k, j, z in loose:
        m.box('Shelf %d.%d' % (k, j), '{t} + {ge}', '{ge}', '{w} - {t} - {ge}', '{id} - {ge}', z, '%s + {t}' % z)
    for k, sct in enumerate(secs, 1):           # shelf pin holes where a section has loose shelves
        if sct['kind'] in (1, 2) and sct['adj'] and int(sct['nsh']):
            pin_holes(m, comp, k)
    for k, sct in enumerate(secs, 1):           # overlay doors: cover the box edges like the drawer fronts
        if sct['kind'] != 1:
            continue
        ov_top = '{t} - {rev} / 2' if k == 1 else '({t} - {rev}) / 2'
        ov_bot = '{t} - {rev} / 2' if k == n else '({t} - {rev}) / 2'
        z0, z1 = '{b%d} - (%s)' % (k, ov_bot), '{b%d} + {s%d} + %s' % (k, k, ov_top)
        if door_count(sct, g) == 1:
            m.box('Door %d' % k, '{rev} / 2', '-{ft}', '{w} - {rev} / 2', '0', z0, z1)
        else:
            m.box('Door %d left' % k, '{rev} / 2', '-{ft}', '{w} / 2 - {rev} / 2', '0', z0, z1)
            m.box('Door %d right' % k, '{w} / 2 + {rev} / 2', '-{ft}', '{w} - {rev} / 2', '0', z0, z1)
    lines.insert(0, '%s: parameters %s* (Modify > Change Parameters)' % (o['name'], P))
    lines.insert(1, 'Outside %g x %g x %g mm, %g mm boards; inside %g wide x %g deep; %s; %s'
                 % (g['w'], g['h'], g['d'], g['t'], g['iw'], g['id'], BASES[base].split(' (')[0].lower(),
                    TOPS[top].split(' (')[0].lower()))
    for k, sct in enumerate(secs):
        extra = ''
        if sct['kind'] == 1:
            extra = ', %d door%s' % (door_count(sct, g), 's' if door_count(sct, g) > 1 else '')
        if sct['kind'] in (1, 2) and int(sct['nsh']):
            extra += ', %d %s shel%s' % (int(sct['nsh']), 'loose' if sct['adj'] else 'fixed',
                                         'ves' if int(sct['nsh']) > 1 else 'f')
        lines.append('Section %d: %s, opening %g mm high, bottom %g mm up%s'
                     % (k + 1, KINDS[sct['kind']].lower(), round(g['s'][k], 2), round(g['b'][k], 2), extra))
    if o['flat']:
        try:
            import nm_flat
            nm_flat.make_flat([b.createForAssemblyContext(occ) for b in comp.bRepBodies], o['name'])
            lines.append('Flat copy of the carcass for CAM made')
        except Exception:
            nm.log('cabinet lay flat failed:\n' + traceback.format_exc())
            lines.append('Lay flat failed (see nmj_log.txt)')
    occs = [occ]
    col = exp('max(max({w}; {h}); {d}) + 200 mm')         # drawer flat copies: to the right of the carcass flat copy
    dx = [col]
    for k, sct in enumerate(secs):
        if sct['kind'] != 0:
            continue
        d = drawer_opts(o, k, P=P, g=g)
        d['_flat_dx0'] = ' + '.join(dx)
        bo, sub = dr.build_bank(d)
        occs += bo
        lines += ['Section %d: %s' % (k + 1, x) for x in sub[1:]]
        dx.append('%d * (%s)' % (int(sct['nd']), exp('max({w}; {d}) + 100 mm')))
    nm.log('cabinet ' + ' | '.join(lines))
    return occs, lines


def door_count(sct, g):
    return {1: 1, 2: 2}.get(int(sct['ndoor']), 2 if g['w'] > 600 + 1e-6 else 1)


def pin_holes(m, comp, k):
    """32 mm system shelf pin holes in both sides for section k: two columns (pin in from the front and the back),
    rows every pp from pm above the section bottom to pm below its top; a pattern, so the count follows the sizes."""
    feats = []
    for side, x0, x1 in (('Left', '{t} - {pdep}', '{t}'), ('Right', '{w} - {t}', '{w} - {t} + {pdep}')):
        sk = m.side_sketch('Pin hole %d %s' % (k, side))
        m.side_circle(sk, '{pin}', '{b%d} + {pm}' % k, '{pdia}')
        f = m.extrude(sk, CUT, m.x(x0), m.x(x1), parts=[m.body(side)])
        f.name = 'Pin hole %d %s' % (k, side)
        feats.append(f)
    ents = adsk.core.ObjectCollection.create()
    for f in feats:
        ents.add(f)
    pats = comp.features.rectangularPatternFeatures
    pi = pats.createInput(ents, comp.zConstructionAxis, VI(m.x('floor(({s%d} - 2 * {pm}) / {pp}) + 1' % k)),
                          VI(m.x('{pp}')), adsk.fusion.PatternDistanceType.SpacingPatternDistanceType)
    pi.setDirectionTwo(comp.yConstructionAxis, VI('2'), VI(m.x('{id} - 2 * {pin}')))
    p = pats.add(pi)
    p.name = 'Pin holes %d' % k
    return p




# --------------------------------------------------------------------------------------------------------- the dialog
TIPS = {
    'name': 'Name of the cabinet component; its parameters start with this name (e.g. kitchenbase_w).',
    'w': 'Outside width of the carcass (side to side).',
    'h': 'Outside height, floor to the top of the carcass, toe kick / plinth included.',
    'd': 'Outside depth of the sides (front edge to the back edge), without the fronts.',
    't': 'Carcass board thickness. 3/4" Baltic birch is 18 mm.',
    'relief': 'Corner relief in the tab joints, so the round bit can cut the inside corners.',
    'base': 'Toe kick: a notch cut out of the sides at the front, with a kick board behind it. Plinth: a separate '
            'frame under the carcass. None: the bottom sits at the floor (wall cabinets, legs).',
    'kh': 'Toe kick / plinth height.', 'kd': 'How far the toe kick / plinth front is set back from the front edge.',
    'top': 'Full panel, or two stretchers (front and back) when a counter top goes on top.',
    'sw': 'Width of each stretcher (front to back).',
    'bk': 'Back panel thickness (1/4" ply is 6 mm).', 'bgd': 'How deep the back groove goes into the sides, top '
    'and bottom.', 'bin': 'Back groove set in from the back edge (room to scribe to the wall).',
    'ft': 'Thickness of the doors and drawer fronts.', 'rev': 'Gap between neighbouring doors / drawer fronts. '
    'Fronts cover the carcass edges except half of it at the outside.',
    'ns': 'How many sections, stacked top to bottom. A fixed shelf (tabbed into the sides) separates them.',
    'flat': 'Also make flat copies of every board (carcass and drawers), laid side by side for CAM.',
}
SEC_TIPS = {
    'k': 'What goes in this section.',
    'sh': 'Opening height of this section (between the boards above and below it). The last section gets the rest.',
    'nd': 'Drawers in this section.', 'ht': 'All the same height, or each one taller than the one above.',
    'st': 'How much taller each drawer is than the one above it.',
    'sl': 'Slides for these drawers. The longest slide that fits the inside depth is used.',
    'dp': 'An NM Drawer preset for the box (boards, bottom, pull, dividers...). The cabinet sets the sizes, slides '
          'and fronts.',
    'nsh': 'Shelves in this section, evenly spaced.', 'adj': 'Loose shelves on 5 mm shelf pins (32 mm system holes '
           'in the sides). Off: fixed shelves, tabbed into the sides.',
    'dn': 'One or two doors.',
}
DEFAULT_PRESET = '(NM Drawer defaults)'
VALUE_KEYS = ('w', 'h', 'd', 't', 'kh', 'kd', 'sw', 'bk', 'bgd', 'bin', 'ft', 'rev')
note = ''


def upgrade(raw):
    o = dict(DEFAULTS)
    o.update({k: v for k, v in raw.items() if k in DEFAULTS and k != 'sections'})
    secs = raw.get('sections') or []
    o['sections'] = [dict(SECTION, **{k: v for k, v in (secs[i] if i < len(secs) else {}).items() if k in SECTION})
                     for i in range(MAX_SECTIONS)]
    return o


def load_last():
    try:
        with open(LAST) as f:
            return upgrade(json.load(f))
    except Exception:
        return upgrade({})


def save_last(o):
    try:
        with open(LAST, 'w') as f:
            json.dump(o, f, indent=1)
    except Exception:
        pass


def _tip(inp, text=None):
    inp.tooltip = text if text is not None else TIPS.get(inp.id, '')
    return inp


def _dropdown(ch, iid, label, names, sel, tip=None):
    dd = _tip(ch.addDropDownCommandInput(iid, label, adsk.core.DropDownStyles.TextListDropDownStyle), tip)
    for i, n in enumerate(names):
        dd.listItems.add(n, i == sel)
    return dd


def add_inputs(inputs, o):
    val = lambda ch, k, label: _tip(ch.addValueInput(k, label, 'mm', VI(o[k])))
    g = inputs.addGroupCommandInput('g_cab', 'Cabinet')
    c = g.children
    _tip(c.addStringValueInput('name', 'Name', o['name']))
    for k, label in (('w', 'Width'), ('h', 'Height'), ('d', 'Depth'), ('t', 'Boards')):
        val(c, k, label)
    _dropdown(c, 'relief', 'Corners', nm.RELIEF_NAMES, o['relief'])
    g = inputs.addGroupCommandInput('g_base', 'Base and top')
    c = g.children
    _dropdown(c, 'base', 'Base', BASES, o['base'])
    val(c, 'kh', 'Height')
    val(c, 'kd', 'Set back')
    _dropdown(c, 'top', 'Top', TOPS, o['top'])
    val(c, 'sw', 'Stretcher width')
    g = inputs.addGroupCommandInput('g_back', 'Back and fronts')
    g.isExpanded = False
    c = g.children
    val(c, 'bk', 'Back thick')
    val(c, 'bgd', 'Groove depth')
    val(c, 'bin', 'Set in')
    val(c, 'ft', 'Front thick')
    val(c, 'rev', 'Gap between')
    _tip(inputs.addIntegerSpinnerCommandInput('ns', 'Sections', 1, MAX_SECTIONS, 1, int(o['ns'])))
    dr = drw()
    slides = [x['name'] for x in dr.SLIDES]
    presets = [DEFAULT_PRESET] + sorted(dr.load_presets(), key=str.lower)
    for i, s in enumerate(o['sections'], 1):
        g = inputs.addGroupCommandInput('g_s%d' % i, 'Section %d%s' % (i, ' (top)' if i == 1 else ''))  # titles can't change later
        c = g.children
        tip = lambda k: SEC_TIPS[k]
        _dropdown(c, 'k%d' % i, 'Holds', KINDS, s['kind'], tip('k'))
        _tip(c.addValueInput('sh%d' % i, 'Opening height', 'mm', VI(s['sh'])), tip('sh'))
        _tip(c.addIntegerSpinnerCommandInput('nd%d' % i, 'Drawers', 1, 8, 1, int(s['nd'])), tip('nd'))
        _dropdown(c, 'ht%d' % i, 'Heights', dr.HEIGHTS, s['heights'], tip('ht'))
        _tip(c.addValueInput('st%d' % i, 'Taller by', 'mm', VI(s['step'])), tip('st'))
        _dropdown(c, 'sl%d' % i, 'Slides', slides, min(int(s['slide']), len(slides) - 1), tip('sl'))
        dd = _dropdown(c, 'dp%d' % i, 'Drawer preset', presets,
                       presets.index(s['dpreset']) if s['dpreset'] in presets else 0, tip('dp'))
        _dropdown(c, 'dn%d' % i, 'Doors', DOORS, int(s['ndoor']), tip('dn'))
        _tip(c.addIntegerSpinnerCommandInput('nsh%d' % i, 'Shelves', 0, 10, 1, int(s['nsh'])), tip('nsh'))
        _tip(c.addBoolValueInput('adj%d' % i, 'Adjustable', True, '', bool(s['adj'])), tip('adj'))
    _tip(inputs.addBoolValueInput('flat', 'Lay flat', True, '', o['flat']))
    inputs.addTextBoxCommandInput('msg', '', '', 4, True)
    show(inputs)


def read(inputs):
    it = inputs.itemById
    o = {'name': it('name').value.strip() or 'Cabinet'}
    for k in ('relief', 'base', 'top'):
        o[k] = it(k).selectedItem.index
    for k in VALUE_KEYS:
        o[k] = it(k).expression
    o['ns'], o['flat'] = it('ns').value, it('flat').value
    o['sections'] = []
    for i in range(1, MAX_SECTIONS + 1):
        dp = it('dp%d' % i).selectedItem.name
        o['sections'].append({'kind': it('k%d' % i).selectedItem.index, 'sh': it('sh%d' % i).expression,
                              'nd': it('nd%d' % i).value, 'heights': it('ht%d' % i).selectedItem.index,
                              'step': it('st%d' % i).expression, 'slide': it('sl%d' % i).selectedItem.index,
                              'dpreset': '' if dp == DEFAULT_PRESET else dp, 'ndoor': it('dn%d' % i).selectedItem.index,
                              'nsh': it('nsh%d' % i).value, 'adj': it('adj%d' % i).value})
    return o


def show(inputs):
    it = inputs.itemById
    base, top, ns = it('base').selectedItem.index, it('top').selectedItem.index, it('ns').value
    it('kh').isVisible = it('kd').isVisible = base in (0, 1)
    it('sw').isVisible = top == 1
    for i in range(1, MAX_SECTIONS + 1):
        it('g_s%d' % i).isVisible = i <= ns
        kind = it('k%d' % i).selectedItem.index
        last = i == ns
        it('sh%d' % i).isEnabled = not last
        for k in ('nd', 'ht', 'sl', 'dp'):
            it('%s%d' % (k, i)).isVisible = kind == 0
        it('st%d' % i).isVisible = kind == 0 and it('ht%d' % i).selectedItem.index == 1
        it('dn%d' % i).isVisible = kind == 1
        it('nsh%d' % i).isVisible = kind in (1, 2)
        it('adj%d' % i).isVisible = kind in (1, 2) and it('nsh%d' % i).value > 0
    try:                                        # the last section: show the height it gets
        g = geom(read(inputs))
        it('sh%d' % ns).expression = '%g mm' % round(g['s'][-1], 2)
    except Exception:
        pass


class Changed(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        try:
            if not re.match(r'sh\d$', args.input.id) or args.input.isEnabled:
                show(args.inputs)
        except Exception:
            nm.log('cabinet dialog:\n' + traceback.format_exc())


class Validate(adsk.core.ValidateInputsEventHandler):
    def notify(self, args):
        try:
            bad = check(read(args.inputs))
            args.areInputsValid = not bad
            args.inputs.itemById('msg').formattedText = '<br>'.join(bad)
        except Exception:
            args.areInputsValid = False
            try:
                args.inputs.itemById('msg').formattedText = 'A value is not a valid size (use e.g. 600 mm).'
            except Exception:
                pass


class Execute(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            o = read(args.command.commandInputs)
            bad = check(o)
            if bad:
                nm.ui.messageBox('\n'.join(bad), 'NM Cabinet')
                return
            save_last(o)
            build(o)
        except Exception:
            nm.log('cabinet failed:\n' + traceback.format_exc())
            nm.ui.messageBox('NM Cabinet failed:\n' + traceback.format_exc())


class Created(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = args.command
            cmd.setDialogInitialSize(380, 680)
            add_inputs(cmd.commandInputs, load_last())
            for ev, h in ((cmd.execute, Execute()), (cmd.inputChanged, Changed()), (cmd.validateInputs, Validate())):
                ev.add(h)
                nm.handlers.append(h)
        except Exception:
            nm.ui.messageBox('NM Cabinet failed:\n' + traceback.format_exc())


def register(mod):
    global nm
    nm = mod
    defs = nm.ui.commandDefinitions
    old = defs.itemById(CMD_ID)
    if old:
        old.deleteMe()
    c = defs.addButtonDefinition(CMD_ID, 'NM Cabinet',
                                 'Builds a whole cabinet: carcass boards with tab joints, back in a groove, toe kick / '
                                 'plinth, and up to 4 sections stacked top to bottom with drawers (NM Drawer, on slides '
                                 'or not), doors or shelves. Every size is a parameter, so Change Parameters resizes '
                                 'the cabinet and its drawers later.',
                                 os.path.join(HERE, 'resources', 'create'))
    h = Created()
    c.commandCreated.add(h)
    nm.handlers.append(h)
    panel = nm.ui.allToolbarPanels.itemById(PANEL_ID)
    if panel and not panel.controls.itemById(CMD_ID):
        panel.controls.addCommand(c)


def unregister(mod):
    ui = mod.ui
    panel = ui.allToolbarPanels.itemById(PANEL_ID)
    if panel and panel.controls.itemById(CMD_ID):
        panel.controls.itemById(CMD_ID).deleteMe()
    d = ui.commandDefinitions.itemById(CMD_ID)
    if d:
        d.deleteMe()
