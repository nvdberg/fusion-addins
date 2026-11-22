# NM Joinery - "NM Drawer": one dialog builds a whole drawer / box (clean-room).
# Every size is a user parameter (<name>_w, _d, _h, _t, ...) so Modify > Change Parameters resizes it later and
# the joints follow (they are an NM Box feature). Sketches are fully dimensioned with those parameters.
# Coordinates: x = width (left to right), y = depth (front y=0 to back), z = height (bottom z=0). Lengths in cm
# inside Fusion, parameter values in mm.
import adsk.core, adsk.fusion, os, re, json, traceback

CMD_ID = 'nmjDrawer'
PANEL_ID = 'SolidCreatePanel'
VI = adsk.core.ValueInput.createByString
P3 = adsk.core.Point3D.create
DIM_H = adsk.fusion.DimensionOrientations.HorizontalDimensionOrientation
DIM_V = adsk.fusion.DimensionOrientations.VerticalDimensionOrientation
NEW = adsk.fusion.FeatureOperations.NewBodyFeatureOperation
CUT = adsk.fusion.FeatureOperations.CutFeatureOperation

LAYOUTS = ['Front & back between the sides', 'Sides between front & back']
BOTTOMS = ['Finger-jointed (tabs into all 4 sides)', 'In a groove (slides in, e.g. plywood)']
PULLS = ['None', 'Finger pull (scoop in the top edge)', 'Hand hole (slot)']
SCREWS = ['None', '2 holes', '4 holes']
SIZES = ['Box outside sizes', 'Cabinet opening + slides']
# side-mount slides: name, gap per side (default), allowed gap range mm, lengths mm, gap below, drawer line, setback
# Lee Valley 61080 (02K49.35+, the user's 02K4950 = 500 mm zinc), from leevalley.com + its instruction sheet
# (checked 2026-11-21): 12.7-13.5 mm per side (never less), >= 6.4 mm under the drawer, cabinet line 61 mm up from
# the cabinet bottom 2 mm back, drawer line 44 mm up from the drawer bottom 5.2 mm back (soft-close), slide 46 mm high.
SLIDES = [
    {'name': 'Lee Valley 61080 soft-close, side-mount', 'gap': '13 mm', 'range': (12.7, 13.5),
     'lengths': (450, 500, 550, 600), 'below': '17 mm', 'line': 44, 'cab_line': 61, 'back': 5.2, 'min_below': 6.4,
     'high': 46.04},      # 1 13/16"
    {'name': 'Other side-mount (type the gap)', 'gap': None},
    {'name': 'No slides (runs on the shelf or on wooden runners)', 'gap': '1 mm', 'below': '0 mm', 'none': True},
]


def has_slides(o):
    """Opening mode with real slides (not 'No slides')."""
    return o['size'] == 1 and not SLIDES[o['slide']].get('none')
HEIGHTS = ['All the same', 'Graduated (each one taller than the one above)']
SPOS = ['Centred on the sides', 'Typed: line up from the bottom']
VSTOCK = [('1/2" ply (12 mm)', '12 mm'), ('1/4" ply (6 mm)', '6 mm'), ('Other', None)]

# dialog defaults (mm), the last used values are remembered in nm_drawer_last.json.
# Stock: 1/2" Baltic birch ply = 12 mm actual (metric, 9 plies; not 12.7). Groove bottom 1/4" BB = 6 mm,
# false front 3/4" BB = 18 mm. Measure the sheet and set <name>_t if it differs.
DEFAULTS = {
    'size': 0, 'ow': '560 mm', 'oh': '150 mm', 'od': '520 mm', 'slide': 0, 'sg': '13 mm', 'sl': '500 mm',
    'ot': '6 mm', 'ob': '17 mm', 'marks': True, 'spos': 0, 'sh': '46.04 mm',
    'sline': '44 mm', 'sback': '5.2 mm',
    'name': 'Drawer', 'layout': 0, 'w': '450 mm', 'd': '400 mm', 'h': '125 mm', 't': '12 mm', 'relief': 1, 'top': False,
    'bottom': 0, 'bt': '12 mm', 'gd': '6 mm', 'gh': '10 mm',
    'div_fb': 0, 'div_lr': 0, 'vt': '12 mm', 'vd': '6 mm', 'vdrop': '10 mm',
    'pull': 0, 'pw': '80 mm', 'pd': '25 mm', 'hl': '100 mm', 'hh': '30 mm', 'pz': '40 mm',
    'ff': False, 'ft': '18 mm', 'fs': '10 mm', 'ftop': '10 mm', 'fb': '10 mm', 'holes': 2, 'hd': '4.5 mm',
    'flat': False, 'nd': 1, 'heights': 0, 'step': '25 mm', 'rev': '3 mm',
}
DROPDOWNS = ('size', 'slide', 'spos', 'heights', 'layout', 'relief', 'bottom', 'pull', 'holes')
OPENING_KEYS = ('ow', 'oh', 'od', 'sg', 'sl', 'ot', 'ob')
MARK_KEYS = ('sh', 'sline', 'sback')
VALUE_KEYS = OPENING_KEYS + MARK_KEYS + ('w', 'd', 'h', 't', 'bt', 'gd', 'gh', 'vt', 'vd', 'vdrop', 'pw', 'pd', 'hl', 'hh', 'pz',
              'ft', 'fs', 'ftop', 'fb', 'hd', 'step', 'rev')
# user parameter comments (Change Parameters)
COMMENTS = {
    'ow': 'cabinet opening width', 'oh': 'cabinet opening height',
    'od': 'cabinet opening depth (reference only: the box depth = the slide length)',
    'sg': 'slide gap per side (box width = opening - 2 x this)', 'sl': 'slide length (= box depth)',
    'sh': 'slide height (Lee Valley 61080: 1 13/16 in)',
    'sline': 'top of the drawer slide, up from the bottom of the box sides',
    'sback': 'slide line mark: starts this far back from the box front (and ends as far from the back)',
    'smw': 'slide line mark: groove height, below the line (hidden under the slide)',
    'smd': 'slide line mark: groove depth into the outside of the sides',
    'ot': 'gap above the box in the opening', 'ob': 'gap below the box in the opening',
    'w': 'outside width (left to right)', 'd': 'outside depth (front to back)', 'h': 'outside height (sides)',
    't': 'board thickness (sides, front, back)', 'bt': 'bottom thickness', 'tt': 'top thickness',
    'gd': 'groove depth into the sides', 'gh': 'groove: bottom edge of the sides to the bottom panel',
    'gg': 'groove clearance per side (above and below the panel)', 'ge': 'room at the panel edges (groove / dado ends)',
    'vt': 'divider thickness', 'vd': 'dado depth for the dividers',
    'vw': 'dado and half-lap notch width (divider + clearance, at least the bit)', 'vdrop': 'dividers lower than the top by',
    'pw': 'finger pull width', 'pd': 'finger pull depth (at most half the width)',
    'hl': 'hand hole length', 'hh': 'hand hole height', 'pz': 'hand hole centre below the top edge',
    'ft': 'false front thickness', 'fs': 'false front overhang left and right', 'ftop': 'false front overhang at the top',
    'fb': 'false front overhang at the bottom', 'hd': 'screw hole diameter (box front)',
    'step': 'each drawer this much higher than the one above it', 'rev': 'gap between the false fronts',
    'hx': 'screw holes in from the sides', 'hz': 'screw holes in from the top and bottom',
}

HERE = os.path.dirname(os.path.abspath(__file__))
LAST = os.path.join(HERE, 'nm_drawer_last.json')
PRESETS = os.path.join(HERE, 'nm_drawer_presets.json')     # {name: dialog values}, saved from the dialog
PICK, BUILTIN = '(pick a preset)', 'Defaults (built in)'
nm = None           # the NMJoinery module (set by register)
note = ''           # one-line message from the preset buttons, shown under the dialog
applying = False    # True while a preset fills the dialog (skip the Changed side effects)


def upgrade(raw):
    """Saved dialog values (last used or a preset) -> a full set, older files included."""
    d = dict(DEFAULTS)
    raw = dict(raw)
    if 'div' in raw and 'div_fb' not in raw:          # before 2026-11-21: one direction + a count
        n = raw.get('div_n', 1)
        raw['div_fb'], raw['div_lr'] = {1: (n, 0), 2: (0, n)}.get(raw['div'], (0, 0))
    d.update({k: v for k, v in raw.items() if k in DEFAULTS})
    return d


def load_last():
    try:
        with open(LAST) as f:
            return upgrade(json.load(f))
    except Exception:
        return dict(DEFAULTS)


def load_presets():
    try:
        with open(PRESETS) as f:
            raw = json.load(f)
        return {k: upgrade(v) for k, v in raw.items() if isinstance(v, dict)}
    except Exception:
        return {}


def save_presets(p):
    with open(PRESETS, 'w') as f:
        json.dump(p, f, indent=1, sort_keys=True)


def save_last(o):
    try:
        with open(LAST, 'w') as f:
            json.dump(o, f, indent=1)
    except Exception:
        pass


def unique_prefix(des, name):
    slug = re.sub(r'[^a-z0-9]', '', name.lower()) or 'drawer'
    if slug[0].isdigit():
        slug = 'd' + slug
    up = des.userParameters
    pre, n = slug + '_', 2
    while up.itemByName(pre + 'w') or up.itemByName(pre + 't'):
        pre, n = '%s%d_' % (slug, n), n + 1
    return pre


class Maker:
    """Fully dimensioned sketches + extrudes in one component. Expressions use {key} for the drawer's own
    parameters (expanded to <prefix>key)."""
    def __init__(self, comp, pre):
        self.comp, self.pre = comp, pre
        self.um = nm.design().unitsManager
        self.placed = {}

    def x(self, e):
        return re.sub(r'\{(\w+)\}', lambda m: self.pre + m.group(1), e)

    def ev(self, e):
        return self.um.evaluateExpression(e, 'cm')

    def dim(self, sk, a, b, ori, expr, tp):
        """Distance a-b along ori = expr (signed: negative means b lies on the minus side)."""
        v = self.ev(expr)
        gc = sk.geometricConstraints
        if abs(v) < 1e-7:
            (gc.addVerticalPoints if ori == DIM_H else gc.addHorizontalPoints)(a, b)
            return
        d = sk.sketchDimensions.addDistanceDimension(a, b, ori, tp)
        if v < 0:
            m = re.fullmatch(r'-\((.*)\)', expr)
            expr = m.group(1) if m and expr.count('(') == 1 else '-(%s)' % expr
        d.parameter.expression = expr

    def place(self, sk, pt, X, Y):
        """Puts pt at (X, Y) from the sketch origin. A point that shares X or Y with one placed before in this
        sketch is aligned to it instead (Fusion calls a second dimension to the same x 'over constrained')."""
        o = sk.originPoint
        g = pt.geometry
        done = self.placed.setdefault(sk.entityToken, [])
        gc = sk.geometricConstraints
        same = [q for q, qx, qy in done if qx == X]
        if same:
            gc.addVerticalPoints(same[0], pt)
        else:
            self.dim(sk, o, pt, DIM_H, X, P3(g.x / 2, g.y - 0.8, 0))
        same = [q for q, qx, qy in done if qy == Y]
        if same:
            gc.addHorizontalPoints(same[0], pt)
        else:
            self.dim(sk, o, pt, DIM_V, Y, P3(g.x - 0.8, g.y / 2, 0))
        done.append((pt, X, Y))

    def rect(self, sk, X0, Y0, X1, Y1):
        """Rectangle between two corners given as signed sketch-space expressions."""
        ev = self.ev
        p0, p1 = P3(ev(X0), ev(Y0), 0), P3(ev(X1), ev(Y1), 0)
        lines = sk.sketchCurves.sketchLines.addTwoPointRectangle(p0, p1)
        pts = []
        for i in range(lines.count):
            for p in (lines.item(i).startSketchPoint, lines.item(i).endSketchPoint):
                if p not in pts:
                    pts.append(p)
        near = lambda q: min(pts, key=lambda p: p.geometry.distanceTo(q))
        a, b = near(p0), near(p1)
        self.place(sk, a, X0, Y0)
        self.dim(sk, a, b, DIM_H, '(%s) - (%s)' % (X1, X0), P3((p0.x + p1.x) / 2, p1.y + 0.8, 0))
        self.dim(sk, a, b, DIM_V, '(%s) - (%s)' % (Y1, Y0), P3(p1.x + 0.8, (p0.y + p1.y) / 2, 0))

    def circle(self, sk, X, Y, dia):
        c = sk.sketchCurves.sketchCircles.addByCenterRadius(P3(self.ev(X), self.ev(Y), 0), self.ev(dia) / 2)
        self.place(sk, c.centerSketchPoint, X, Y)
        dd = sk.sketchDimensions.addDiameterDimension(c, P3(self.ev(X) + self.ev(dia), self.ev(Y) + 0.5, 0))
        dd.parameter.expression = dia
        return c

    def extrude(self, sk, op, z0=None, z1=None, parts=None, through=None):
        """through = full length of a cut both ways from the sketch plane (through-all 'symmetric' only cut one way)."""
        profs = adsk.core.ObjectCollection.create()
        for one in (sk if isinstance(sk, (list, tuple)) else [sk]):    # several sketches on one plane: one feature
            for i in range(one.profiles.count):
                profs.add(one.profiles.item(i))
        ext = self.comp.features.extrudeFeatures
        ei = ext.createInput(profs, op)
        if through:
            ei.setSymmetricExtent(VI(self.x(through)), True)
        else:
            if z0 != '0':
                ei.startExtent = adsk.fusion.OffsetStartDefinition.create(VI(z0))
            ei.setDistanceExtent(False, VI('(%s) - (%s)' % (z1, z0)))
        if parts:
            ei.participantBodies = parts
        return ext.add(ei)

    def box(self, name, x0, y0, x1, y1, z0, z1, op=NEW, parts=None):
        """Plan rectangle on XY, extruded from z0 to z1. op=CUT cuts only the participant bodies."""
        x0, y0, x1, y1, z0, z1 = [self.x(e) for e in (x0, y0, x1, y1, z0, z1)]
        sk = self.comp.sketches.add(self.comp.xYConstructionPlane)
        sk.name = 'Sk ' + name
        self.rect(sk, x0, y0, x1, y1)
        f = self.extrude(sk, op, z0, z1, parts)
        f.name = name
        if op == NEW:
            b = f.bodies.item(0)
            b.name = name
            return b
        return f

    def front_sketch(self, name):
        """Sketch on the XZ plane (the front face, y = 0). Sketch x = world x, sketch y = minus world z."""
        sk = self.comp.sketches.add(self.comp.xZConstructionPlane)
        sk.name = 'Sk ' + name
        return sk

    def front_rect(self, sk, x0, z0, x1, z1):
        self.rect(sk, self.x(x0), '-(%s)' % self.x(z0), self.x(x1), '-(%s)' % self.x(z1))

    def front_circle(self, sk, x, z, dia):
        self.circle(sk, self.x(x), '-(%s)' % self.x(z), self.x(dia))

    def side_sketch(self, name):
        """Sketch on the YZ plane (x = 0). Sketch x = minus world z, sketch y = world y."""
        sk = self.comp.sketches.add(self.comp.yZConstructionPlane)
        sk.name = 'Sk ' + name
        return sk

    def side_rect(self, sk, y0, z0, y1, z1):
        self.rect(sk, '-(%s)' % self.x(z0), self.x(y0), '-(%s)' % self.x(z1), self.x(y1))

    def side_circle(self, sk, y, z, dia):
        self.circle(sk, '-(%s)' % self.x(z), self.x(y), self.x(dia))

    def notch(self, name, side, a0, a1, z_floor, z_open, relief):
        """Half-lap notch: a0..a1 across (x on the front plane, y on the side plane), from z_floor to z_open, plus the
        bit relief in its two inside corners (at z_floor): dogbone / T-bone sideways (into the walls) / deep (past
        the floor), the same choices as the finger joints. Returns the sketches: the notch and each relief circle get
        their own, because with thin dividers the circles overlap each other and the notch, and a sketch whose regions
        split up after a resize would leave part of the cut behind."""
        new = self.front_sketch if side == 'front' else self.side_sketch
        rect, circ = (self.front_rect, self.front_circle) if side == 'front' else (self.side_rect, self.side_circle)
        sk = new(name)
        rect(sk, a0, z_floor, a1, z_open)
        sks = [sk]
        if relief == 0:
            return sks
        r = 'nmj_bit / 2'
        k1, k2 = {3: ('', r), 4: (r, '')}.get(relief, ('nmj_bit / 2 / sqrt(2)',) * 2)
        up = self.ev(self.x(z_open)) > self.ev(self.x(z_floor))
        for a, sgn, tag in ((a0, '+', 'a'), (a1, '-', 'b')):     # into the notch along the floor
            ca = '%s %s %s' % (a, sgn, k1) if k1 else a
            cz = '%s %s %s' % (z_floor, '+' if up else '-', k2) if k2 else z_floor
            sks.append(new('%s relief %s' % (name, tag)))
            circ(sks[-1], ca, cz, 'nmj_bit')
        return sks

    def body(self, name):
        return self.comp.bRepBodies.itemByName(name)


def bank_slots(o):
    """Bank of drawers: the height of each drawer's share of the opening in mm, top drawer first."""
    um = nm.design().unitsManager
    n = int(o['nd'])
    oh = um.evaluateExpression(o['oh'], 'mm') * 10
    step = um.evaluateExpression(o['step'], 'mm') * 10 if o['heights'] == 1 else 0
    base = (oh - step * n * (n - 1) / 2) / n
    return [base + i * step for i in range(n)]


def bank_drawer(o, i, n, ref=None, slots=None):
    """Dialog values for drawer i (1 = top) of a bank of n: its share of the opening, and false fronts that cover
    the opening with the reveal between them. ref = bank parameter prefix (expressions), else numbers (mm)."""
    um = nm.design().unitsManager
    s = dict(o, nd=1, name='%s %d' % (o['name'], i))
    if ref:
        e = lambda k: ref + k
        s['oh'] = ref + 's%d' % i
    else:
        e = lambda k: '(%s)' % o[k]
        s['oh'] = '%g mm' % slots[i - 1]
    if o['ff']:
        s['fs'] = '%s + %s' % (e('sg'), e('fs'))
        s['ftop'] = '%s + %s' % (e('ot'), e('ftop')) if i == 1 else '%s - %s / 2' % (e('ot'), e('rev'))
        s['fb'] = '%s + %s' % (e('ob'), e('fb')) if i == n else '%s - %s / 2' % (e('ob'), e('rev'))
    return s


def check(o):
    """Problems with the dialog values, in words (empty = fine)."""
    if o['size'] == 1 and int(o['nd']) > 1:
        return check_bank(o)
    um = nm.design().unitsManager
    v = {k: um.evaluateExpression(o[k], 'mm') * 10 for k in VALUE_KEYS}      # Fusion gives cm
    out = []
    if o['size'] == 1:
        sp = SLIDES[o['slide']]
        for k, label in (('ow', 'Opening width'), ('oh', 'Opening height'), ('od', 'Opening depth'), ('sl', 'Slide length')):
            if v[k] <= 0:
                out.append('%s must be more than 0.' % label)
        if v['sl'] > v['od'] + 1e-6:
            out.append('The slides (%g mm) are longer than the opening is deep (%g mm).' % (v['sl'], v['od']))
        if v['ot'] < 0 or v['ob'] < 0:
            out.append('Gaps above and below must be 0 or more.')
        if 'range' in sp:
            lo, hi = sp['range']
            if not (lo - 1e-6 <= v['sg'] <= hi + 1e-6):
                out.append('These slides need %g to %g mm per side (never less).' % (lo, hi))
            if not any(abs(v['sl'] - L) < 1e-6 for L in sp['lengths']):
                out.append('These slides come in %s mm.' % ' / '.join('%d' % L for L in sp['lengths']))
            if v['ob'] < sp['min_below'] - 1e-6:
                out.append('Leave at least %g mm under the drawer for these slides.' % sp['min_below'])
        elif v['sg'] < 0:
            out.append('The slide gap must be 0 or more.')
        hh = v['oh'] - v['ot'] - v['ob']
        if sp.get('none'):
            if hh < 20:
                out.append('Box would be less than 20 mm high.')
        elif v['sh'] <= 0:
            out.append('Slide height must be more than 0.')
        elif hh < v['sh'] + 2:
            out.append('Box (%g mm high) is too low for a %g mm slide.' % (hh, v['sh']))
        if has_slides(o) and o['spos'] == 1 and not (3 < v['sline'] < hh - 3):
            out.append('Slide line must be more than 3 mm up and 3 mm below the top of the box (%g mm high).' % hh)
        if has_slides(o) and o['marks']:
            if not (0 <= v['sback'] < v['sl'] / 3):
                out.append('Slide setback must be 0 or more and well under the depth.')
    for k, label in (('w', 'Width'), ('d', 'Depth'), ('h', 'Height'), ('t', 'Board thickness'), ('bt', 'Bottom thickness')):
        if v[k] <= 0:
            out.append('%s must be more than 0.' % label)
    if out:
        return out
    if v['w'] <= 2 * v['t'] + 10 or v['d'] <= 2 * v['t'] + 10:
        out.append('Width and depth must be well over 2 x the board thickness.')
    if o['bottom'] == 1:
        if not (1.5 <= v['gd'] < v['t'] - 1):
            out.append('Groove depth must be between 1.5 mm and the board thickness minus 1 mm.')
        if v['gh'] < 3 or v['gh'] + v['bt'] > v['h'] - 10:
            out.append('Groove up: at least 3 mm, and the bottom must fit well below the top.')
    elif v['bt'] >= v['h'] - 10:
        out.append('Bottom too thick for this height.')
    if o['div_fb'] or o['div_lr']:
        if not (1.5 <= v['vd'] < v['t'] - 1):
            out.append('Dado depth must be between 1.5 mm and the board thickness minus 1 mm.')
        if v['vt'] <= 0:
            out.append('Dividers need a thickness.')
        zb = v['bt'] if o['bottom'] == 0 else v['gh'] + v['bt']
        zt = v['h'] - ((v['bt'] if o['bottom'] == 0 else v['t']) if o['top'] else 0) - v['vdrop']
        if zt - zb < 20:
            out.append('Dividers would be less than 20 mm high: make Lower smaller or the box higher.')
    if o['pull'] == 1 and not (0 < v['pd'] <= v['pw'] / 2):
        out.append('Finger pull depth must be more than 0 and at most half its width.')
    if o['pull'] == 2 and not (0 < v['hh'] < v['hl']):
        out.append('Hand hole: the height must be less than the length.')
    inner_w = v['w'] - 2 * v['t']
    if o['pull'] == 1 and v['pw'] > inner_w - 10:
        out.append('Finger pull is wider than the front between the sides.')
    if o['pull'] == 2 and v['hl'] > inner_w - 10:
        out.append('Hand hole is longer than the front between the sides.')
    if o['top'] and o['pull'] == 1:
        out.append('A finger pull needs an open box (the top board fills the top edge): use a hand hole.')
    if o['pull'] == 2:
        edge = v['h'] - ((v['bt'] if o['bottom'] == 0 else v['t']) if o['top'] else 0)
        hole_top = v['h'] + (v['ftop'] if o['ff'] else 0) - v['pz'] + v['hh'] / 2
        if hole_top > edge - 3:
            out.append('Hand hole must end 3 mm below the top edge of the box front%s: make From top bigger.'
                       % (' (under the top board)' if o['top'] else ''))
        if hole_top - v['hh'] < (v['bt'] if o['bottom'] == 0 else v['gh'] + v['bt']) + 3:
            out.append('Hand hole runs into the bottom: make From top smaller.')
    if o['ff'] and (v['ft'] <= 0 or min(v['fs'], v['ftop'], v['fb']) < 0):
        out.append('False front: thickness must be more than 0, overhangs 0 or more.')
    return out


def check_bank(o):
    um = nm.design().unitsManager
    n = int(o['nd'])
    v = {k: um.evaluateExpression(o[k], 'mm') * 10 for k in ('oh', 'ot', 'ob', 'step', 'rev')}
    out = []
    if o['heights'] == 1 and v['step'] < 0:
        out.append('Taller by must be 0 or more.')
    if o['ff'] and (v['rev'] < 0 or v['rev'] / 2 > min(v['ot'], v['ob'])):
        out.append('Reveal must be 0 or more and at most twice the gap above / below.')
    slots = bank_slots(o)
    if slots[0] <= v['ot'] + v['ob']:
        out.append('%d drawers do not fit in %g mm.' % (n, v['oh']))
    if out:
        return out
    seen = {}
    for i in range(1, n + 1):
        for msg in check(bank_drawer(o, i, n, slots=slots)):
            seen.setdefault(msg, []).append(i)
    for msg, nums in seen.items():
        out.append('%s %s: %s' % ('Drawer' if len(nums) == 1 else 'Drawers', ', '.join(map(str, nums)), msg)
                   if len(nums) < n else msg)
    return out


def build_bank(o):
    """Bank of drawers in one opening (open stack, no rails): one drawer per share of the opening, all sizes from the
    bank's own parameters, stacked with a Move that follows them. Returns (occurrences, text lines)."""
    des = nm.design()
    nm.ensure_globals(des)
    um = des.unitsManager
    n = int(o['nd'])
    B = unique_prefix(des, o['name'])
    same_t = abs(um.evaluateExpression(o['bt'], 'mm') - um.evaluateExpression(o['t'], 'mm')) < 1e-6
    slides = has_slides(o)
    keys = list(OPENING_KEYS) + (['sh'] if slides else []) + ['t', 'bt']
    keys += ['sline'] if slides and o['spos'] == 1 else []
    keys += ['sback'] if slides and o['marks'] else []
    keys += ['gd', 'gh'] if o['bottom'] == 1 else []
    keys += ['vt', 'vd', 'vdrop'] if (o['div_fb'] or o['div_lr']) else []
    keys += {1: ['pw', 'pd'], 2: ['hl', 'hh', 'pz']}.get(o['pull'], [])
    keys += (['ft', 'fs', 'ftop', 'fb', 'rev'] + (['hd'] if o['holes'] else [])) if o['ff'] else []
    graduated = o['heights'] == 1
    keys += ['step'] if graduated else []
    bank_c = {'fs': 'false fronts: past the opening left and right', 'ftop': 'top false front: past the opening top',
              'fb': 'bottom false front: past the opening bottom'}
    up = des.userParameters
    for k in keys:
        e = ('%st' % B) if (k == 'bt' and same_t) else o[k]
        up.add(B + k, VI(e), 'mm', '%s (bank): %s' % (o['name'], bank_c.get(k) or COMMENTS.get(k, k)))
    tri = n * (n - 1) // 2
    for i in range(1, n + 1):
        e = ('(%soh - %sstep * %d) / %d + %d * %sstep' % (B, B, tri, n, i - 1, B) if graduated
             else '%soh / %d' % (B, n))
        up.add(B + 's%d' % i, VI(e), 'mm', '%s (bank): drawer %d share of the opening height (1 = top)' % (o['name'], i))
    slots = bank_slots(o)
    mm = lambda k: um.evaluateExpression(o[k], 'mm') * 10
    lines = ['%s: bank of %d drawers, parameters %s* (the drawers: %sd1_* ...)' % (o['name'], n, B, B),
             'Opening %g x %g x %g mm, open stack; shares top to bottom: %s mm'
             % (mm('ow'), mm('oh'), mm('od'), ', '.join('%g' % round(x, 2) for x in slots))]
    occs = []
    col = 'max(%sow + 2 * %sfs; %ssl) + 100 mm' % (B, B, B) if o['ff'] else 'max(%sow; %ssl) + 100 mm' % (B, B)
    for i in range(1, n + 1):
        s = bank_drawer(o, i, n, ref=B)
        for k in keys:
            if k not in ('oh', 'fs', 'ftop', 'fb', 'rev', 'step'):
                s[k] = B + k
        s['_pre'] = '%sd%d_' % (B, i)
        dx = ['%d * (%s)' % (i - 1, col)] if i > 1 else []
        s['_flat_dx'] = ' + '.join(([o['_flat_dx0']] if o.get('_flat_dx0') else []) + dx) or None  # side by side
        s['_z'] = ' + '.join(([o['_z0']] if o.get('_z0') else []) + ['%sob' % B] +
                             ['%ss%d' % (B, j) for j in range(i + 1, n + 1)])
        s['_x'] = '%s + %ssg' % (o['_x0'], B) if o.get('_x0') else None   # the drawer's origin is its box side
        occ, sub = build(s)
        occs.append(occ)
        z0 = sum(slots[i:])
        hh = slots[i - 1] - mm('ot') - mm('ob')
        if not slides:
            lines.append('Drawer %d: box %g high, its share starts %g mm up from the opening bottom'
                         % (i, round(hh, 2), round(z0, 2)))
            continue
        L = hh / 2 + mm('sh') / 2 if o['spos'] == 0 else mm('sline')
        lines.append('Drawer %d: box %g high; top of its cabinet slide %g mm up from the opening bottom, its drawer '
                     'slide %g mm up from the bottom of the box sides' % (i, round(hh, 2), round(z0 + mm('ob') + L, 2),
                                                                          round(L, 2)))
    if o['ff']:
        lines.append('False fronts cover the opening: %g mm past it at the sides, %g at the top, %g at the bottom, '
                     '%g mm between them' % (mm('fs'), mm('ftop'), mm('fb'), mm('rev')))
    if o['flat']:
        lines.append('Flat copies for CAM made (one component per drawer)')
    nm.log('bank ' + ' | '.join(lines))
    return occs, lines


def build(o):
    """Builds the drawer from the dialog options o. Returns (occurrence, text lines)."""
    des = nm.design()
    nm.ensure_globals(des)
    pre = o.get('_pre') or unique_prefix(des, o['name'])
    up = des.userParameters
    um = des.unitsManager
    same_t = abs(um.evaluateExpression(o['bt'], 'mm') - um.evaluateExpression(o['t'], 'mm')) < 1e-6
    if o['size'] == 1:
        params = [(k, o[k]) for k in OPENING_KEYS] + [('w', '{ow} - 2 * {sg}'), ('d', '{sl}'),
                                                       ('h', '{oh} - {ot} - {ob}')]
        if has_slides(o):
            params += [('sh', o['sh']), ('sline', '{h} / 2 + {sh} / 2' if o['spos'] == 0 else o['sline'])]
            if o['marks']:
                params += [('sback', o['sback']), ('smw', '1 mm'), ('smd', '0.5 mm')]
    else:
        params = [('w', o['w']), ('d', o['d']), ('h', o['h'])]
    params += [('t', o['t']), ('bt', '{t}' if same_t else o['bt'])]
    if o['top']:
        params.append(('tt', '{bt}' if o['bottom'] == 0 else '{t}'))
    if o['bottom'] == 1:
        params += [('gd', o['gd']), ('gh', o['gh']), ('gg', 'nmj_gap')]
    nfb, nlr = int(o['div_fb']), int(o['div_lr'])
    if o['bottom'] == 1 or nfb or nlr:
        params.append(('ge', '1 mm'))
    if nfb or nlr:
        params += [('vt', o['vt']), ('vd', o['vd']), ('vdrop', o['vdrop'])]
        narrow = (um.evaluateExpression(o['vt'], 'mm') + 2 * up.itemByName('nmj_gap').value
                  < up.itemByName('nmj_bit').value - 1e-6)   # thin ply: the bit sets the width
        params.append(('vw', 'max({vt} + 2 * nmj_gap; nmj_bit)'))   # follows vt and the bit later too
        for key, n, span in (('vx', nfb, '{w}'), ('vy', nlr, '{d}')):
            for i in range(1, n + 1):
                params.append(('%s%d' % (key, i), '{t} + %d * (%s - 2 * {t}) / %d' % (i, span, n + 1)))
    if o['pull'] == 1:
        params += [('pw', o['pw']), ('pd', o['pd'])]
    elif o['pull'] == 2:
        params += [('hl', o['hl']), ('hh', o['hh']), ('pz', o['pz'])]
    if o['ff']:
        params += [('ft', o['ft']), ('fs', o['fs']), ('ftop', o['ftop']), ('fb', o['fb'])]
        if o['holes']:
            params += [('hd', o['hd']), ('hx', '50 mm'), ('hz', '30 mm')]
    exp = lambda e: re.sub(r'\{(\w+)\}', lambda m: pre + m.group(1), e)
    for k, e in params:
        c = COMMENTS.get(k) or ('%s divider %s: centre from the %s' % (
            'front-to-back' if k.startswith('vx') else 'left-to-right', k[2:], 'left' if k.startswith('vx') else 'front'))
        up.add(pre + k, VI(exp(e)), 'mm', '%s: %s' % (o['name'], c))

    root = des.rootComponent
    occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    comp = occ.component
    comp.name = o['name']
    m = Maker(comp, pre)
    if o['layout'] == 0:          # front & back between the sides
        walls = (('Left', '0', '0', '{t}', '{d}'), ('Right', '{w} - {t}', '0', '{w}', '{d}'),
                 ('Front', '{t}', '0', '{w} - {t}', '{t}'), ('Back', '{t}', '{d} - {t}', '{w} - {t}', '{d}'))
    else:                         # sides between front & back
        walls = (('Front', '0', '0', '{w}', '{t}'), ('Back', '0', '{d} - {t}', '{w}', '{d}'),
                 ('Left', '0', '{t}', '{t}', '{d} - {t}'), ('Right', '{w} - {t}', '{t}', '{w}', '{d} - {t}'))
    jointed = [m.box(n, x0, y0, x1, y1, '0', '{h}') for n, x0, y0, x1, y1 in walls]
    inner = ('{t}', '{t}', '{w} - {t}', '{d} - {t}')
    if o['bottom'] == 0:
        jointed.append(m.box('Bottom', *inner, '0', '{bt}'))
    if o['top']:
        jointed.append(m.box('Top', *inner, '{h} - {tt}', '{h}'))
    exprs = dict(nm.DEFAULT_EXPR)
    exprs['relief'] = str(int(o['relief']))
    made, lines = nm.create_all([b.createForAssemblyContext(occ) for b in jointed], exprs)

    sides = lambda *names: [m.body(n) for n in names]
    if o['bottom'] == 1:
        m.box('Bottom groove', '{t} - {gd}', '{t} - {gd}', '{w} - {t} + {gd}', '{d} - {t} + {gd}',
              '{gh} - {gg}', '{gh} + {bt} + {gg}', CUT, sides('Left', 'Right', 'Front', 'Back'))
        m.box('Bottom', '{t} - {gd} + {ge}', '{t} - {gd} + {ge}', '{w} - {t} + {gd} - {ge}', '{d} - {t} + {gd} - {ge}',
              '{gh}', '{gh} + {bt}')
        lines.append('Bottom %s in a %s deep groove' % (o['bt'], o['gd']))
    if nfb or nlr:
        zb = '{bt}' if o['bottom'] == 0 else '{gh} + {bt}'
        ztop = '{h} - {tt}' if o['top'] else '{h}'
        zt = '%s - {vdrop}' % ztop                          # top edge of the dividers
        zdado = ztop if o['top'] else '{h} + 1 mm'
        for i in range(1, nfb + 1):       # front to back: dados in the front and back
            c = '{vx%d}' % i
            m.box('Dado F-B %d' % i, '%s - {vw} / 2' % c, '{t} - {vd}', '%s + {vw} / 2' % c,
                  '{d} - {t} + {vd}', zb, zdado, CUT, sides('Front', 'Back'))
            m.box('Divider F-B %d' % i, '%s - {vt} / 2' % c, '{t} - {vd} + {ge}', '%s + {vt} / 2' % c,
                  '{d} - {t} + {vd} - {ge}', zb, zt)
        for i in range(1, nlr + 1):       # left to right: dados in the sides
            c = '{vy%d}' % i
            m.box('Dado L-R %d' % i, '{t} - {vd}', '%s - {vw} / 2' % c, '{w} - {t} + {vd}',
                  '%s + {vw} / 2' % c, zb, zdado, CUT, sides('Left', 'Right'))
            m.box('Divider L-R %d' % i, '{t} - {vd} + {ge}', '%s - {vt} / 2' % c, '{w} - {t} + {vd} - {ge}',
                  '%s + {vt} / 2' % c, zb, zt)
        txt = ' + '.join(t for t in ('%d front-to-back' % nfb if nfb else '', '%d left-to-right' % nlr if nlr else '') if t)
        lines.append('%s divider(s) in %s deep dados' % (txt, o['vd']))
        if narrow:
            lines.append('Dados / notches as wide as the bit (%.2f mm) for the %s dividers'
                         % (up.itemByName('nmj_bit').value * 10, o['vt']))
        if nfb and nlr:                   # half-laps where they cross: F-B notched from the top, L-R from the bottom
            mid = '(%s + %s) / 2' % (zb, zt)
            relief = int(o['relief'])
            fbs = sides(*['Divider F-B %d' % i for i in range(1, nfb + 1)])
            lrs = sides(*['Divider L-R %d' % i for i in range(1, nlr + 1)])
            for i in range(1, nfb + 1):   # at each F-B divider: a notch from below in every L-R divider
                c = '{vx%d}' % i
                sk = m.notch('Lap F-B %d' % i, 'front', '%s - {vw} / 2' % c, '%s + {vw} / 2' % c, mid,
                        '%s - 1 mm' % zb, relief)
                m.extrude(sk, CUT, parts=lrs, through='2 * {d} + 10 mm').name = 'Lap F-B %d' % i
            for i in range(1, nlr + 1):   # at each L-R divider: a notch from above in every F-B divider
                c = '{vy%d}' % i
                sk = m.notch('Lap L-R %d' % i, 'side', '%s - {vw} / 2' % c, '%s + {vw} / 2' % c, mid,
                        '%s + 1 mm' % zt, relief)
                m.extrude(sk, CUT, parts=fbs, through='2 * {w} + 10 mm').name = 'Lap L-R %d' % i
            lines.append('%d half-laps where the dividers cross%s' % (nfb * nlr, ', with %s' % nm.RELIEF_NAMES[relief].lower()
                                                                       if relief else ''))
    if has_slides(o) and o['marks']:       # slide line grooves on the outside of both sides (joint ends too)
        cut = sides('Left', 'Right', 'Front', 'Back') + ([m.body('Top')] if o['top'] else [])
        for x0, x1 in (('0', '{smd}'), ('{w} - {smd}', '{w}')):
            m.box('Slide line', x0, '{sback}', x1, '{d} - {sback}', '{sline} - {smw}', '{sline}', CUT, cut)
        lines.append('Slide line grooves on both sides, top edge on the slide line, from %g mm back'
                     % (um.evaluateExpression(o['sback'], 'mm') * 10))
    fronts = ['Front']
    if o['ff']:
        m.box('False front', '-{fs}', '-{ft}', '{w} + {fs}', '0', '-{fb}', '{h} + {ftop}')
        fronts.append('False front')
        if o['holes']:
            sk = m.front_sketch('Screw holes')
            zs = ('{h} / 2',) if o['holes'] == 1 else ('{hz}', '{h} - {hz}')
            for x in ('{hx}', '{w} - {hx}'):
                for z in zs:
                    m.front_circle(sk, x, z, '{hd}')
            m.extrude(sk, CUT, parts=sides('Front'), through='2 * {t} + 10 mm').name = 'Screw holes'
    if o['pull']:
        top = '{h} + {ftop}' if o['ff'] else '{h}'
        sk = m.front_sketch('Pull')
        if o['pull'] == 1:        # circle through both ends of the scoop and its lowest point
            r = '({pw} * {pw} / 4 + {pd} * {pd}) / (2 * {pd})'      # Fusion rejects ^ on lengths
            m.front_circle(sk, '{w} / 2', '%s - {pd} + %s' % (top, r), '2 * %s' % r)
        else:
            zc = '%s - {pz}' % top
            half = '({hl} - {hh}) / 2'
            m.front_rect(sk, '{w} / 2 - %s' % half, '%s - {hh} / 2' % zc, '{w} / 2 + %s' % half, '%s + {hh} / 2' % zc)
            for sgn in ('-', '+'):
                m.front_circle(sk, '{w} / 2 %s %s' % (sgn, half), zc, '{hh}')
        m.extrude(sk, CUT, parts=sides(*fronts), through='2 * ({t} + {ft}) + 10 mm' if o['ff'] else '2 * {t} + 10 mm').name = 'Pull'
    if o['size'] == 1:
        mm = lambda k: um.evaluateExpression(o[k], 'mm') * 10
        sp = SLIDES[o['slide']]
        lines.insert(0, 'Opening %g x %g x %g mm -> box %g wide x %g high x %g deep (%g mm per side, %g above, %g below)'
                     % (mm('ow'), mm('oh'), mm('od'), mm('ow') - 2 * mm('sg'), mm('oh') - mm('ot') - mm('ob'), mm('sl'),
                        mm('sg'), mm('ot'), mm('ob')))
        hh = mm('oh') - mm('ot') - mm('ob')
        L = hh / 2 + mm('sh') / 2 if o['spos'] == 0 else mm('sline')
        if not has_slides(o):
            lines.insert(1, 'No slides: %g mm play per side, the box runs on what is under it' % mm('sg'))
        else:
            lines.insert(1, '%s, %g mm, %s: top of the drawer slide %g mm up from the bottom edge of the box sides, %g mm '
                         'back from the box front; top of the cabinet slide %g mm up from the opening bottom%s '
                         '(follows %s_sline in the parameters)'
                         % (sp['name'], mm('sl'), 'centred on the sides' if o['spos'] == 0 else 'typed line', round(L, 2),
                            mm('sback'), round(mm('ob') + L, 2), ', 2 mm back' if 'line' in sp else '', pre.rstrip('_')))
    lines.insert(0, '%s: parameters %s* (Modify > Change Parameters)' % (o['name'], pre))
    if o.get('_z') or o.get('_x'):   # bank / cabinet: to its place in the opening, follows the parameters
        bodies = adsk.core.ObjectCollection.create()
        for b in comp.bRepBodies:
            bodies.add(b)
        mi = comp.features.moveFeatures.createInput2(bodies)
        mi.defineAsTranslateXYZ(VI(o.get('_x') or '0 mm'), VI('0 mm'), VI(o.get('_z') or '0 mm'), True)
        comp.features.moveFeatures.add(mi).name = 'To its place in the %s' % ('cabinet' if o.get('_x') else 'bank')
    if o.get('flat'):
        try:
            import nm_flat
            nm_flat.make_flat([b.createForAssemblyContext(occ) for b in comp.bRepBodies], o['name'], dx=o.get('_flat_dx'))
            lines.append('Flat copy for CAM made')
        except Exception:
            nm.log('lay flat failed:\n' + traceback.format_exc())
            lines.append('Lay flat failed (see nmj_log.txt)')
    nm.log('drawer ' + ' | '.join(lines))
    return occ, lines


# ----------------------------------------------------------------------------------------------- dialog
TIPS = {
    'size': 'Box outside sizes: type the box. Cabinet opening + slides: type the opening, the box size follows '
            '(width = opening - 2 x slide gap, height = opening - gaps, depth = slide length).',
    'ow': 'Width of the cabinet opening (inside, side to side).', 'oh': 'Height of the opening.',
    'od': 'Depth of the opening, front edge to the back. Picks the longest slide that fits.',
    'slide': 'Lee Valley 61080 soft-close full-extension side-mount (450-600 mm, 100 lb): 12.7-13.5 mm per side, '
             'at least 6.4 mm under the drawer.',
    'sg': 'Room for one slide: the box is this much narrower than the opening on each side.',
    'sl': 'Slide length = box depth.', 'ot': 'Gap above the box (in the opening).',
    'marks': 'Cuts a shallow groove (0.5 mm deep, 1 mm high) on the outside of both sides, its top edge on the '
             'slide line, so you can line the drawer slide up. It sits under the slide, so it does not show. '
             'Cut it with a V-bit / engraving pass (or set <name>_smw to the bit width).',
    'spos': 'Centred: the slide sits in the middle of the box sides (top of slide = half the box height + half the '
            'slide height), and the cabinet line follows. Typed: you give the line (Lee Valley sheet: 44 mm).',
    'sh': 'Height of the slide itself (Lee Valley 61080: 1 13/16" = 46.04 mm).',
    'sline': 'Top of the drawer slide, up from the bottom edge of the box sides (Lee Valley 61080: 44 mm).',
    'sback': 'Where the slide starts, back from the box front (Lee Valley 61080 soft-close: 5.2 mm).',
    'ob': 'Gap below the box. 17 mm matches the Lee Valley lines (cabinet 61 mm, drawer 44 mm).',
    'preset': 'Pick a saved setup to fill in every field below. Defaults = the add-in\'s own starting values.',
    'pname': 'Name for the current setup, e.g. Kitchen drawer or Screw sorter. The same name again updates it.',
    'psave': 'Save every field below under the name above.',
    'pdel': 'Delete the preset picked above (not the drawers made with it).',
    'name': 'Name of the new component; its parameters start with this name (e.g. drawer_w).',
    'layout': 'Which boards run the full length: the sides (front and back sit between them) or the front and back.',
    'w': 'Outside width, left to right.', 'd': 'Outside depth, front to back.', 'h': 'Outside height of the sides.',
    't': 'Thickness of the sides, front and back. Default 12 mm = 1/2" Baltic birch (measure your sheet).',
    'relief': 'Inside corners of the finger joints: dogbones or T-bones (see NM Joint).',
    'top': 'Closed box: a top board, finger-jointed like the bottom.',
    'bottom': 'Finger-jointed: tabs into all four sides. In a groove: a panel that slides into a groove in the sides.',
    'bt': 'Bottom thickness (same as the boards = linked to them).',
    'gd': 'How deep the groove goes into the sides (less than the board).',
    'gh': 'From the bottom edge of the sides to the underside of the panel.',
    'div_fb': 'Dividers running from the front to the back (left / right compartments), in dados in the front and '
              'back, evenly spaced. Move one later with its _vx1, _vx2 ... parameter.',
    'div_lr': 'Dividers running from left to right (front / back compartments), in dados in the sides. Move one '
              'later with its _vy1, _vy2 ... parameter. With both: half-lap joints where they cross, inside corners '
              'as set in Corners.',
    'vstock': 'Divider stock. 1/4" ply = 6 mm: the dados and notches are then cut as wide as the bit (nmj_bit), '
              'e.g. 6.35 mm for a 1/4" bit. Other: type the thickness below.',
    'vt': 'Divider thickness.', 'vd': 'Dado depth in the walls.',
    'vdrop': 'Dividers this much lower than the top of the sides.',
    'pull': 'A cut-out in the front to pull the drawer.',
    'pw': 'Width of the scoop at the top edge.', 'pd': 'How deep the scoop goes (at most half the width).',
    'hl': 'Length of the hand hole.', 'hh': 'Height of the hand hole.', 'pz': 'From the top edge to the hole centre.',
    'ff': 'A separate front board screwed on from the inside, overhanging the box.',
    'ft': 'False front thickness.', 'fs': 'Overhang left and right.', 'ftop': 'Overhang at the top.',
    'fb': 'Overhang at the bottom.', 'holes': 'Clearance holes in the box front for the screws.',
    'hd': 'Screw clearance hole diameter.',
    'nd': 'More than 1 = a bank of drawers stacked in this one opening (no rails between them). Each drawer gets '
          'its share of the opening height; the gaps above / below apply to every drawer.',
    'heights': 'All the same, or graduated (kitchen style): each drawer is Taller by more than the one above it.',
    'step': 'How much higher each drawer is than the one above it.',
    'rev': 'Bank of drawers: the false fronts together cover the opening; this is the gap between them. Sides / '
           'Top / Bottom are then how far they reach past the opening edges.',
    'flat': 'Also make a flat copy of every board (inside face up) in its own component, for CAM. It follows size changes.',
}


def _tip(inp):
    inp.tooltip = TIPS.get(inp.id, '')
    return inp


def _dropdown(ch, iid, label, names, sel):
    dd = _tip(ch.addDropDownCommandInput(iid, label, adsk.core.DropDownStyles.TextListDropDownStyle))
    for i, n in enumerate(names):
        dd.listItems.add(n, i == sel)
    return dd


def vstock_index(expr):
    um = nm.design().unitsManager
    try:
        v = um.evaluateExpression(expr, 'mm')
        return next(i for i, (_, e) in enumerate(VSTOCK) if e and abs(um.evaluateExpression(e, 'mm') - v) < 1e-6)
    except Exception:
        return len(VSTOCK) - 1


def preset_names():
    return [PICK, BUILTIN] + sorted(load_presets(), key=str.lower)


def fill_presets(dd, sel=PICK):
    global applying
    was, applying = applying, True          # refilling the list is not a pick
    try:
        dd.listItems.clear()
        for n in preset_names():
            dd.listItems.add(n, n == sel)
    finally:
        applying = was


def add_inputs(inputs, o):
    val = lambda ch, k, label: _tip(ch.addValueInput(k, label, 'mm', VI(o[k])))
    g = inputs.addGroupCommandInput('g_preset', 'Presets')
    g.isExpanded = bool(load_presets())
    c = g.children
    fill_presets(_tip(c.addDropDownCommandInput('preset', 'Preset', adsk.core.DropDownStyles.TextListDropDownStyle)))
    _tip(c.addStringValueInput('pname', 'Save as', ''))
    _tip(c.addBoolValueInput('psave', 'Save', False, '', False))
    _tip(c.addBoolValueInput('pdel', 'Delete picked', False, '', False))
    g = inputs.addGroupCommandInput('g_open', 'Size')
    c = g.children
    _dropdown(c, 'size', 'Size from', SIZES, o['size'])
    for k, label in (('ow', 'Opening width'), ('oh', 'Opening height'), ('od', 'Opening depth')):
        val(c, k, label)
    _tip(c.addIntegerSpinnerCommandInput('nd', 'Drawers', 1, 12, 1, int(o['nd'])))
    _dropdown(c, 'heights', 'Heights', HEIGHTS, o['heights'])
    val(c, 'step', 'Taller by')
    _dropdown(c, 'slide', 'Slides', [x['name'] for x in SLIDES], o['slide'])
    for k, label in (('sg', 'Gap per side'), ('sl', 'Slide length'), ('ot', 'Gap above'), ('ob', 'Gap below')):
        val(c, k, label)
    _dropdown(c, 'spos', 'Slide position', SPOS, o['spos'])
    for k, label in (('sh', 'Slide height'), ('sline', 'Slide line up'), ('sback', 'Slide setback')):
        val(c, k, label)
    _tip(c.addBoolValueInput('marks', 'Mark slide lines', True, '', o['marks']))
    g = inputs.addGroupCommandInput('g_box', 'Box')
    c = g.children
    _tip(c.addStringValueInput('name', 'Name', o['name']))
    _dropdown(c, 'layout', 'Layout', LAYOUTS, o['layout'])
    for k, label in (('w', 'Width'), ('d', 'Depth'), ('h', 'Height'), ('t', 'Boards')):
        val(c, k, label)
    _dropdown(c, 'relief', 'Corners', nm.RELIEF_NAMES, o['relief'])
    _tip(c.addBoolValueInput('top', 'Top', True, '', o['top']))
    g = inputs.addGroupCommandInput('g_bottom', 'Bottom')
    c = g.children
    _dropdown(c, 'bottom', 'Bottom', BOTTOMS, o['bottom'])
    val(c, 'bt', 'Thick')
    val(c, 'gd', 'Groove')
    val(c, 'gh', 'Up')
    g = inputs.addGroupCommandInput('g_div', 'Dividers')
    g.isExpanded = bool(o['div_fb'] or o['div_lr'])
    c = g.children
    _tip(c.addIntegerSpinnerCommandInput('div_fb', 'Front-to-back', 0, 20, 1, int(o['div_fb'])))
    _tip(c.addIntegerSpinnerCommandInput('div_lr', 'Left-to-right', 0, 20, 1, int(o['div_lr'])))
    _dropdown(c, 'vstock', 'Stock', [n for n, _ in VSTOCK], vstock_index(o['vt']))
    val(c, 'vt', 'Thick')
    val(c, 'vd', 'Dado')
    val(c, 'vdrop', 'Lower')
    g = inputs.addGroupCommandInput('g_pull', 'Pull')
    g.isExpanded = bool(o['pull'])
    c = g.children
    _dropdown(c, 'pull', 'Pull', PULLS, o['pull'])
    val(c, 'pw', 'Width')
    val(c, 'pd', 'Depth')
    val(c, 'hl', 'Length')
    val(c, 'hh', 'Height')
    val(c, 'pz', 'From top')
    g = inputs.addGroupCommandInput('g_ff', 'False front')
    g.isExpanded = bool(o['ff'])
    c = g.children
    _tip(c.addBoolValueInput('ff', 'Add', True, '', o['ff']))
    val(c, 'ft', 'Thick')
    val(c, 'fs', 'Sides')
    val(c, 'ftop', 'Top')
    val(c, 'fb', 'Bottom')
    val(c, 'rev', 'Reveal')
    _dropdown(c, 'holes', 'Screws', SCREWS, o['holes'])
    val(c, 'hd', 'Hole dia')
    _tip(inputs.addBoolValueInput('flat', 'Lay flat', True, '', o['flat']))
    inputs.addTextBoxCommandInput('msg', '', '', 3, True)
    show(inputs)
    fit(inputs)


def fit(inputs, pick_length=False):
    """Opening mode: box width / height / depth from the opening (and the longest slide that fits)."""
    global note
    it = inputs.itemById
    if it('size').selectedItem.index != 1:
        return
    sp = SLIDES[it('slide').selectedItem.index]
    um = nm.design().unitsManager
    try:
        mm = {k: um.evaluateExpression(it(k).expression, 'mm') * 10 for k in OPENING_KEYS}
    except Exception:
        return
    if pick_length and sp.get('none') and abs(mm['sl'] - mm['od']) > 1e-6:
        it('sl').expression = it('od').expression          # no slides: as deep as the opening
        mm['sl'] = mm['od']
    if pick_length and 'lengths' in sp:
        fits = [L for L in sp['lengths'] if L <= mm['od'] + 1e-6]
        if fits and abs(fits[-1] - mm['sl']) > 1e-6:
            it('sl').expression = '%d mm' % fits[-1]
            mm['sl'] = fits[-1]
    hh = mm['oh'] - mm['ot'] - mm['ob']
    if it('nd').value > 1:
        try:
            o = {'nd': it('nd').value, 'oh': it('oh').expression, 'heights': it('heights').selectedItem.index,
                 'step': it('step').expression}
            hs = [x - mm['ot'] - mm['ob'] for x in bank_slots(o)]
            hh = hs[0]
            note = 'Drawer boxes, top to bottom: %s mm high (Height shows the top one).' % ', '.join(
                '%g' % round(x, 1) for x in hs)
        except Exception:
            pass
    for k, v in (('w', mm['ow'] - 2 * mm['sg']), ('h', hh), ('d', mm['sl'])):
        if abs(it(k).value * 10 - v) > 1e-6:
            it(k).expression = '%g mm' % round(v, 4)


def apply(inputs, o):
    """Put a full set of dialog values into the inputs (dropdowns first, then the sizes)."""
    it = inputs.itemById
    for k in DROPDOWNS:
        it(k).listItems.item(int(o[k])).isSelected = True
    it('vstock').listItems.item(vstock_index(o['vt'])).isSelected = True
    it('name').value = o['name']
    for k in VALUE_KEYS:
        it(k).expression = o[k]
    it('div_fb').value, it('div_lr').value = int(o['div_fb']), int(o['div_lr'])
    for k in ('top', 'ff', 'flat', 'marks'):
        it(k).value = bool(o[k])
    it('nd').value = int(o['nd'])
    it('g_div').isExpanded = bool(o['div_fb'] or o['div_lr'])
    it('g_pull').isExpanded = bool(o['pull'])
    it('g_ff').isExpanded = bool(o['ff'])
    it('g_open').isExpanded = bool(o['size'])
    fit(inputs)


def preset_event(inputs, iid):
    """The preset dropdown and buttons. Returns True when it handled the event."""
    global note, applying
    it = inputs.itemById
    dd = it('preset')
    picked = dd.selectedItem.name if dd.selectedItem else PICK
    if iid == 'preset':
        if picked == PICK:
            return True
        o = dict(DEFAULTS) if picked == BUILTIN else load_presets().get(picked)
        if o:
            applying = True
            try:
                apply(inputs, o)
            finally:
                applying = False
            if picked != BUILTIN:
                it('pname').value = picked
            note = 'Filled in from "%s".' % picked
        return True
    if iid == 'psave':
        name = it('pname').value.strip()
        if not name or name in (PICK, BUILTIN):
            note = 'Type a name under Save as first.'
            return True
        p = load_presets()
        new = name not in p
        p[name] = read(inputs)
        save_presets(p)
        fill_presets(dd, name)
        note = ('Saved preset "%s".' if new else 'Updated preset "%s".') % name
        return True
    if iid == 'pdel':
        p = load_presets()
        if picked not in p:
            note = 'Pick one of your own presets first (the built-in one can\'t be deleted).'
            return True
        del p[picked]
        save_presets(p)
        fill_presets(dd)
        note = 'Deleted preset "%s".' % picked
        return True
    return False


def show(inputs):
    it = inputs.itemById
    opening = it('size').selectedItem.index == 1
    for k in OPENING_KEYS + ('slide', 'nd'):
        it(k).isVisible = opening
    real = opening and not SLIDES[it('slide').selectedItem.index].get('none')
    for k in ('marks', 'spos', 'sh', 'sback'):
        it(k).isVisible = real
    bank = opening and it('nd').value > 1
    it('heights').isVisible = bank
    it('step').isVisible = bank and it('heights').selectedItem.index == 1
    it('sline').isVisible = real and it('spos').selectedItem.index == 1
    for k in ('w', 'd', 'h'):
        it(k).isEnabled = not opening          # follow the opening
    groove = it('bottom').selectedItem.index == 1
    for k in ('gd', 'gh'):
        it(k).isVisible = groove
    div = it('div_fb').value > 0 or it('div_lr').value > 0
    for k in ('vstock', 'vt', 'vd', 'vdrop'):
        it(k).isVisible = div
    pull = it('pull').selectedItem.index
    for k in ('pw', 'pd'):
        it(k).isVisible = pull == 1
    for k in ('hl', 'hh', 'pz'):
        it(k).isVisible = pull == 2
    ff = it('ff').value
    for k in ('ft', 'fs', 'ftop', 'fb', 'holes', 'hd'):
        it(k).isVisible = ff
    it('rev').isVisible = ff and bank
    it('hd').isVisible = ff and it('holes').selectedItem.index > 0


def read(inputs):
    it = inputs.itemById
    o = {'name': it('name').value.strip() or 'Drawer'}
    for k in DROPDOWNS:
        o[k] = it(k).selectedItem.index
    for k in VALUE_KEYS:
        o[k] = it(k).expression
    o['div_fb'], o['div_lr'] = it('div_fb').value, it('div_lr').value
    o['nd'] = it('nd').value
    for k in ('top', 'ff', 'flat', 'marks'):
        o[k] = it(k).value
    return o


class Changed(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        global note
        try:
            inputs = args.inputs
            if applying:
                return
            if preset_event(inputs, args.input.id):
                show(inputs)
                return
            note = ''
            iid = args.input.id
            if iid == 'slide':
                sp = SLIDES[args.input.selectedItem.index]
                if sp['gap']:
                    inputs.itemById('sg').expression = sp['gap']
                    inputs.itemById('ob').expression = sp['below']
                if 'line' in sp:
                    inputs.itemById('sline').expression = '%g mm' % sp['line']
                    inputs.itemById('sh').expression = '%g mm' % sp['high']
                    inputs.itemById('sback').expression = '%g mm' % sp['back']
            if iid in OPENING_KEYS + ('size', 'slide', 'nd', 'heights', 'step'):
                fit(inputs, pick_length=iid in ('od', 'slide', 'size'))
            if args.input.id == 'bottom':        # groove: a thin panel; fingers: the board thickness
                um = nm.design().unitsManager
                bt, t = inputs.itemById('bt'), inputs.itemById('t')
                if args.input.selectedItem.index == 1 and abs(bt.value - t.value) < 1e-9:
                    bt.expression = '6 mm'
                elif args.input.selectedItem.index == 0:
                    bt.expression = t.expression
            elif args.input.id == 'vstock':
                e = VSTOCK[args.input.selectedItem.index][1]
                if e:
                    inputs.itemById('vt').expression = e
            elif args.input.id == 'vt':
                i = vstock_index(args.input.expression)
                dd = inputs.itemById('vstock')
                if dd.selectedItem.index != i:
                    dd.listItems.item(i).isSelected = True
            show(inputs)
        except Exception:
            nm.log('drawer dialog:\n' + traceback.format_exc())


class Validate(adsk.core.ValidateInputsEventHandler):
    def notify(self, args):
        try:
            bad = check(read(args.inputs))
            args.areInputsValid = not bad
            args.inputs.itemById('msg').formattedText = '<br>'.join(bad + ([note] if note else []))
        except Exception:
            args.areInputsValid = False
            try:
                args.inputs.itemById('msg').formattedText = 'A value is not a valid size (use e.g. 450 mm).'
            except Exception:
                pass


class Execute(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            o = read(args.command.commandInputs)
            bad = check(o)
            if bad:
                nm.ui.messageBox('\n'.join(bad), 'NM Drawer')
                return
            save_last(o)
            if o['size'] == 1 and int(o['nd']) > 1:
                build_bank(o)
            else:
                build(o)
        except Exception:
            nm.log('drawer failed:\n' + traceback.format_exc())
            nm.ui.messageBox('NM Drawer failed:\n' + traceback.format_exc())


class Created(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = args.command
            cmd.setDialogInitialSize(380, 640)
            global note
            note = ''
            add_inputs(cmd.commandInputs, load_last())
            for ev, h in ((cmd.execute, Execute()), (cmd.inputChanged, Changed()), (cmd.validateInputs, Validate())):
                ev.add(h)
                nm.handlers.append(h)
        except Exception:
            nm.ui.messageBox('NM Drawer failed:\n' + traceback.format_exc())


def register(mod):
    global nm
    nm = mod
    defs = nm.ui.commandDefinitions
    old = defs.itemById(CMD_ID)
    if old:
        old.deleteMe()
    c = defs.addButtonDefinition(CMD_ID, 'NM Drawer',
                                 'Builds a whole drawer or box from its sizes: boards, finger joints, a finger-jointed '
                                 'or grooved bottom, dividers, a pull and a false front. Every size is a parameter, so '
                                 'Change Parameters resizes it later and the joints follow.',
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
