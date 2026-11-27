# NM Joinery - "NM Drawer": one dialog builds a whole drawer / box (clean-room).
# Every size is a user parameter (<name>_w, _d, _h, _t, ...) so Modify > Change Parameters resizes it later and
# the joints follow (they are an NM Box feature). Sketches are fully dimensioned with those parameters.
# Coordinates: x = width (left to right), y = depth (front y=0 to back), z = height (bottom z=0). Lengths in cm
# inside Fusion, parameter values in mm.
import adsk.core, adsk.fusion, os, re, json, math, traceback

CMD_ID = 'nmjDrawer'
PANEL_ID = 'SolidCreatePanel'
VI = adsk.core.ValueInput.createByString
P3 = adsk.core.Point3D.create
DIM_H = adsk.fusion.DimensionOrientations.HorizontalDimensionOrientation
DIM_V = adsk.fusion.DimensionOrientations.VerticalDimensionOrientation
NEW = adsk.fusion.FeatureOperations.NewBodyFeatureOperation
CUT = adsk.fusion.FeatureOperations.CutFeatureOperation

LAYOUTS = ['Front & back between the sides', 'Sides between front & back']
JOINTS = ['Finger joints and tabs (CNC)', 'None: butt joints (Domino, dowels, screws)']
BOTTOMS = ['Between the 4 walls (tabs into them with finger joints)', 'In a groove (slides in, e.g. plywood)']
PULLS = ['None', 'Finger pull (scoop in the top edge)', 'Hand hole (slot)', 'Notch in the top edge (rounded corners)']
SCREWS = ['None', '2 holes', '4 holes']
SIZES = ['Box outside sizes', 'Cabinet opening + slides']
FRONTS = ['Plain box front', 'False front (separate board, screwed on)', 'Box front is the drawer face']
EJOINTS = ['Blind tabs (hidden)', 'Through tabs (show on the face)', 'Butt (no joint into the face)']
EPOS = ['Inset (inside the opening)', 'Partial overlay (laps the opening edge)', 'Full overlay (covers the cabinet edge)']
# side-mount slides: id (stored with the drawer, so the list can grow), name, gap per side (default), allowed gap range
# mm, lengths mm, gap below, drawer line, setback, slide height. All full extension.
# Lee Valley 61080 (02K49.35+, the user's 02K4950 = 500 mm zinc), from leevalley.com + its instruction sheet
# (checked 2026-11-21): 12.7-13.5 mm per side (never less), >= 1/4" (6.35 mm) under the drawer, cabinet line 61 mm up from
# the cabinet bottom 2 mm back, drawer line 44 mm up from the drawer bottom 5.2 mm back (soft-close), slide 46 mm high.
# The other Lee Valley slides: leevalley.com pages + instruction sheets (checked 2026-11-24): 1/2" +1/32" (12.7-13.5 mm)
# per side, the 200 lb 3/4" +1/64" (19.05-19.45 mm); drawer member 1/4" back from the drawer front, cabinet member
# 3/16" back from the cabinet front; screwed on the slide's own centre line. No sheet gives a clearance under the
# drawer (min_below 0); 'line' (typed slide position) = slide bottom flush with the box bottom.
IN = lambda *n: tuple(round(25.4 * x, 2) for x in n)
LV = {'below': '6.35 mm', 'min_below': 0, 'back': 6.35, 'cab_back': 4.76}
HALF = dict(LV, gap='13.1 mm', range=(12.7, 13.5))
SLIDES = [
    {'id': 'lv61080', 'name': 'Lee Valley 61080 soft-close, 100 lb', 'gap': '13.1 mm', 'range': (12.7, 13.5),
     'lengths': (450, 500, 550, 600), 'below': '6.35 mm', 'line': 44, 'cab_line': 61, 'back': 5.2, 'min_below': 6.35,
     'high': 46.04, 'sold': '450 / 500 / 550 / 600 mm'},      # 1 13/16"
    dict(HALF, id='lv100', name='Lee Valley 100 lb (02K70; same fit: Accuride 3832E, KV 8450FM)',
         lengths=IN(*range(12, 29, 2)), high=46.04, line=46.04, sold='12" to 28", every 2"'),
    dict(HALF, id='lv100ho', name='Lee Valley 100 lb hold-out, stays open (02K44)',
         lengths=IN(*range(16, 29, 2)), high=46.04, line=46.04, sold='16" to 28", every 2"'),
    dict(HALF, id='lvtouch', name='Lee Valley 100 lb touch-open, push to open (60897)',
         lengths=tuple(range(350, 701, 50)), high=44.45, line=44.45, sold='350 to 700 mm, every 50 mm'),
    dict(HALF, id='lv75', name='Lee Valley 75 lb, light drawers (02K42)',
         lengths=IN(*range(8, 27, 2)), high=38.1, line=38.1, sold='8" to 26", every 2"'),
    dict(LV, id='lv200', name='Lee Valley 200 lb, heavy drawers (02K32)', gap='19.25 mm', range=(19.05, 19.45),
         lengths=IN(16, 18, 20, 22, 24, 26, 28, 30, 32, 36), high=53.58, line=53.58,
         sold='16" to 28" every 2", 30", 32", 36"'),         # 2 7/64" high
    {'id': 'other', 'name': 'Other side-mount (type the gap)', 'gap': None},
    {'id': 'none', 'name': 'No slides (runs on the shelf or on wooden runners)', 'gap': '1 mm', 'below': '0 mm',
     'none': True},
]
OLD_SLIDES = ('lv61080', 'other', 'none')    # before 0.9.0 the drawer stored only the list position


def slide_index(raw):
    """Position in SLIDES of the slides saved in raw (by id; older saves: by the old list position)."""
    ids = [x['id'] for x in SLIDES]
    sid = raw.get('slide_id')
    if sid is None:
        i = int(raw.get('slide', 0))
        sid = OLD_SLIDES[i] if 0 <= i < len(OLD_SLIDES) else 'lv61080'
    return ids.index(sid) if sid in ids else 0


FACE_GAPS = {'ot': '25.4 mm', 'ob': '6.35 mm'}   # box front = face: 1" above the box, 1/4" below (the face hides them)


def face_gaps(o):
    """Box gaps above / below for a face drawer with slides o['slide'] (None: keep the slide's own)."""
    sp = SLIDES[int(o['slide'])]
    return None if sp.get('none') or not sp['gap'] else FACE_GAPS


SNAP = 0.05          # mm: a size typed / shown in inches (4 decimals) still counts as the catalog size


def catalog_length(o, e):
    """The slide length expression e, snapped to the slide's exact catalog length (mm) when it is within SNAP."""
    sp = SLIDES[o['slide']]
    try:
        v = nm.design().unitsManager.evaluateExpression(e, 'mm') * 10
    except Exception:
        return e
    L = next((L for L in sp.get('lengths', ()) if abs(v - L) < SNAP), None)
    return '%g mm' % L if L is not None and abs(v - L) > 1e-9 else e


def has_face(o):
    """The box front itself is the drawer face (wider / taller than the box, same board)."""
    return int(o.get('front', 0)) == 2 and not o.get('ff')


def has_slides(o):
    """Opening mode with real slides (not 'No slides')."""
    return o['size'] == 1 and not SLIDES[o['slide']].get('none')


EPOS_KEYS = {0: ('em',), 1: ('eov',), 2: ('ect', 'efo')}


def flush_inset(o):
    """Inset face on a drawer without slides: the box rides on the shelf, so the face is flush with the box
    sides and bottom (the side gap is the reveal there); the inset gap is kept at the top only."""
    return o['size'] == 1 and int(o.get('epos', 0)) == 0 and SLIDES[int(o['slide'])].get('none')


def face_past(o):
    """Face in an opening: how far it reaches past the opening edges, as a {key} expression (inset: negative)."""
    return {0: '-{em}', 1: '{eov}', 2: '{ect} - {efo}'}[int(o['epos'])]


def face_params(o):
    """The drawer's face parameters (key, {key} expression): overhangs past the box sides / top / bottom."""
    if o.get('_face_given'):                      # a bank drawer: worked out from the bank's parameters
        return [('es', o['es']), ('etop', o['etop']), ('eb', o['eb'])]
    if o['size'] == 1:
        if flush_inset(o):
            return [('em', o['em']), ('ep', '-{em}'), ('es', '0 mm'), ('etop', '{ot} + {ep}'), ('eb', '0 mm')]
        return ([(k, o[k]) for k in EPOS_KEYS[int(o['epos'])]] +
                [('ep', face_past(o)), ('es', '{sg} + {ep}'), ('etop', '{ot} + {ep}'), ('eb', '{ob} + {ep}')])
    if o['esame']:
        return [('es', o['es']), ('etop', '0 mm'), ('eb', '0 mm')]
    return [('es', o['es']), ('etop', o['etop']), ('eb', o['eb'])]


def face_mm(o, v):
    """Face overhangs (sides, top, bottom) in mm from the dialog values v (mm)."""
    if o.get('_face_given'):
        return v['es'], v['etop'], v['eb']
    if o['size'] == 1 and flush_inset(o):
        return 0, v['ot'] - v['em'], 0
    if o['size'] == 1:
        p = {0: -v['em'], 1: v['eov'], 2: v['ect'] - v['efo']}[int(o['epos'])]
        return v['sg'] + p, v['ot'] + p, v['ob'] + p
    return (v['es'], 0, 0) if o['esame'] else (v['es'], v['etop'], v['eb'])
HEIGHTS = ['All the same', 'Graduated (each one taller than the one above)']
SPOS = ['Centred on the sides', 'Typed: line up from the bottom']
VSTOCK = [('1/2" ply (12 mm)', '12 mm'), ('1/4" ply (6 mm)', '6 mm'), ('Other', None)]

# dialog defaults (mm), the last used values are remembered in nm_drawer_last.json.
# Stock: 1/2" Baltic birch ply = 12 mm actual (metric, 9 plies; not 12.7). Groove bottom 1/4" BB = 6 mm,
# false front 3/4" BB = 18 mm. Measure the sheet and set <name>_t if it differs.
DEFAULTS = {
    'size': 0, 'ow': '560 mm', 'oh': '150 mm', 'od': '520 mm', 'slide': 0, 'slide_id': 'lv61080', 'sg': '13.1 mm', 'sl': '500 mm',
    'ot': '6 mm', 'ob': '6.35 mm', 'marks': True, 'spos': 0, 'sh': '46.04 mm',
    'sline': '44 mm', 'sback': '5.2 mm',
    'name': 'Drawer', 'layout': 0, 'joints': 0, 'w': '450 mm', 'd': '400 mm', 'h': '125 mm', 't': '12 mm', 'relief': 1, 'fr': 2.0, 'top': False,
    'bottom': 0, 'bt': '12 mm', 'gd': '6 mm', 'gh': '10 mm',
    'div_fb': 0, 'div_lr': 0, 'vt': '12 mm', 'vd': '6 mm', 'vdrop': '10 mm',
    'pull': 0, 'pw': '80 mm', 'pd': '25 mm', 'hl': '100 mm', 'hh': '30 mm', 'pz': '40 mm',
    # notch pull (0.9.0): the kitchen-island handle, 5 x 1 3/4 in, 1/2 in corners, 1/4 in where it meets the top edge
    'uw': '127 mm', 'uh': '44.45 mm', 'ur': '12.7 mm', 'ue': '6.35 mm',
    'ff': False, 'ft': '18 mm', 'fs': '10 mm', 'ftop': '10 mm', 'fb': '10 mm', 'holes': 2, 'hd': '4.5 mm',
    'flat': False, 'nd': 1, 'heights': 0, 'step': '25 mm', 'rev': '3.175 mm', 'units': 0,
    # box front = drawer face (0.9.0): overhangs (box sizes), joint into the face, place in the opening
    'front': 0, 'es': '13.1 mm', 'etop': '50.8 mm', 'eb': '6.35 mm', 'esame': False, 'ejoint': 0, 'efrac': 0.75,
    'epos': 0, 'em': '3.175 mm', 'eov': '9.525 mm', 'ect': '18 mm', 'efo': '1.5875 mm', 'et': '12 mm',
    # engraved part names (0.10.0): single-stroke letters on each board's inside face, 1/4 in high
    'engrave': False, 'eh': '6.35 mm',
}
DROPDOWNS = ('size', 'slide', 'spos', 'heights', 'layout', 'joints', 'relief', 'bottom', 'pull', 'holes', 'front',
             'ejoint', 'epos')
FACE_KEYS = ('es', 'etop', 'eb', 'em', 'eov', 'ect', 'efo', 'et')
OPENING_KEYS = ('ow', 'oh', 'od', 'sg', 'sl', 'ot', 'ob')
MARK_KEYS = ('sh', 'sline', 'sback')
VALUE_KEYS = OPENING_KEYS + MARK_KEYS + ('w', 'd', 'h', 't', 'bt', 'gd', 'gh', 'vt', 'vd', 'vdrop', 'pw', 'pd', 'hl', 'hh', 'pz',
              'uw', 'uh', 'ur', 'ue', 'ft', 'fs', 'ftop', 'fb', 'hd', 'step', 'rev', 'eh') + FACE_KEYS

# Units toggle (dialog only): plain sizes are shown in mm or inches. Formulas stay as they are. Fusion reads both, so
# the parameters simply get what the dialog shows (e.g. "17.7165 in").
UNITS = ['mm (metric)', 'inch (imperial)']
UNITS_TIP = 'Show the sizes in mm or in inches. Switching converts every plain size in the dialog; you can ' \
            'always type either (e.g. 450 mm or 17.75 in).'
PLAIN = re.compile(r'^\s*[-+]?(\d+\.?\d*|\.\d+)\s*(mm|cm|m|in|inch|ft|")?\s*$')


BARE = re.compile(r'^\s*([-+]?(?:\d+\.?\d*|\.\d+))\s*$')


def dexpr(inputs, k):
    """The text of size input k with its unit made explicit. The size inputs take the dialog's units (to_units
    sets their unitType), so Fusion itself turns a typed "16" into "16 in" (Units = inch) or "16 mm"; a number
    without a unit that still comes through follows the Units dropdown too."""
    e = inputs.itemById(k).expression
    m = BARE.match(e)
    if m:
        return m.group(1) + (' in' if inch(inputs) else ' mm')
    return e


def inch(inputs):
    u = inputs.itemById('units')
    return bool(u and u.selectedItem and u.selectedItem.index == 1)


def fmt(v_mm, inches):
    """A length in mm as dialog text: mm to 0.01, or inches to 0.0001 (exact when it is a multiple of 1/64)."""
    if inches:
        x = v_mm / 25.4
        r = round(x * 64) / 64
        x = r if abs(x - r) < 1e-6 else round(x, 4)
        return ('%.6f' % x).rstrip('0').rstrip('.') + ' in'
    return ('%.2f' % v_mm).rstrip('0').rstrip('.') + ' mm'


def to_units(inputs, ids, memo):
    """Shows every plain size among the value inputs ids in the dialog's units. memo remembers the text before a
    switch, so switching back gives exactly what was there (when the value wasn't touched in between)."""
    um = nm.design().unitsManager
    inches = inch(inputs)
    for k in ids:
        inp = inputs.itemById(k)
        if not inp:
            continue
        try:
            inp.unitType = 'in' if inches else 'mm'       # a plain number typed from now on is in the dialog's units
        except Exception:
            pass
        e = inp.expression
        back = memo.get(k)
        if back and back[0] == e:
            new = back[1]
        elif PLAIN.match(e):
            try:
                was = e + (' mm' if inches else ' in') if BARE.match(e) else e   # plain number: the old units
                new = fmt(um.evaluateExpression(was, 'mm') * 10, inches)
            except Exception:
                continue
        else:
            continue
        if new != e:
            inp.expression = new
            memo[k] = (new, e)
# user parameter comments (Change Parameters)
COMMENTS = {
    'ow': 'cabinet opening width', 'oh': 'cabinet opening height',
    'od': 'cabinet opening depth (reference only: the box depth = the slide length)',
    'sg': 'slide gap per side (box width = opening - 2 x this)', 'sl': 'slide length (= box depth)',
    'sh': 'slide height (Lee Valley 61080: 1 13/16 in)',
    'sline': 'top of the drawer slide, up from the bottom of the box sides',
    'sback': 'slide line mark: starts this far back from the box front (and ends as far from the back)',
    'smw': 'slide line mark: groove height, centred on the slide centre line (hidden under the slide)',
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
    'uw': 'notch pull width', 'uh': 'notch pull depth below the top edge', 'ur': 'notch pull radius at its bottom corners',
    'ue': 'notch pull radius where it meets the top edge (0 = sharp)',
    'ft': 'false front thickness', 'fs': 'false front overhang left and right', 'ftop': 'false front overhang at the top',
    'fb': 'false front overhang at the bottom', 'hd': 'screw hole diameter (box front)',
    'step': 'each drawer this much higher than the one above it', 'rev': 'gap between the faces / false fronts (1/8 in)',
    'hx': 'screw holes in from the sides', 'hz': 'screw holes in from the top and bottom',
    'es': 'face past the box sides, left and right', 'etop': 'face above the top of the box sides',
    'eb': 'face below the bottom of the box sides', 'et': 'drawer face thickness (the box front)', 'fd': 'depth of the blind slots in the face (tabs of the sides / bottom)',
    'em': 'inset face: gap to the opening, all round', 'eov': 'partial overlay: face laps the opening edge by this',
    'ect': 'full overlay: cabinet board thickness (the face covers it)', 'efo': 'full overlay: face this much short of the cabinet outside',
    'ep': 'face past the opening edges (negative = inside it)',
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
    if 'front' not in raw:                            # before 0.9.0: a false front or not
        raw['front'] = 1 if raw.get('ff') else 0
    d.update({k: v for k, v in raw.items() if k in DEFAULTS})
    if 'et' not in raw:                               # before the face had its own thickness: the board's
        d['et'] = d['t']
    d['slide'] = slide_index(raw)                     # by id: the slide list can grow without moving saved drawers
    d['slide_id'] = SLIDES[d['slide']]['id']
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
            if isinstance(one, adsk.fusion.Profile):                  # one picked region of a sketch
                profs.add(one)
                continue
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

    def notch_pull(self, top, edge_rounds, sk):
        """U-notch pull down from the top edge (z = top) of the front, centred, {uw} wide, {uh} deep, bottom corners
        {ur}, and (edge_rounds) {ue} rounds where it meets the top edge. Each piece is its own sketch (as in notch()), so
        a resize never splits a region and leaves part of the cut behind. Returns what extrude() takes."""
        x0, x1 = '{w} / 2 - {uw} / 2', '{w} / 2 + {uw} / 2'
        zb, above = '%s - {uh}' % top, '%s + 1 mm' % top
        self.front_rect(sk, x0, '%s + {ur}' % zb, x1, above)                   # full width, above the round corners
        out = [sk]
        sk = self.front_sketch('Pull middle')
        self.front_rect(sk, '%s + {ur}' % x0, zb, '%s - {ur}' % x1, above)     # between the round corners, to the bottom
        out.append(sk)
        for tag, xc in (('left', '%s + {ur}' % x0), ('right', '%s - {ur}' % x1)):
            sk = self.front_sketch('Pull corner ' + tag)
            self.front_circle(sk, xc, '%s + {ur}' % zb, '2 * {ur}')
            out.append(sk)
        if edge_rounds:   # the corner of the top edge: a square {ue} x 2{ue} minus a circle; keep the region outside it
            for tag, xa, xb, xc in (('left', '%s - {ue}' % x0, x0, '%s - {ue}' % x0),
                                    ('right', x1, '%s + {ue}' % x1, '%s + {ue}' % x1)):
                sk = self.front_sketch('Pull edge round ' + tag)
                self.front_rect(sk, xa, '%s - {ue}' % top, xb, '%s + {ue}' % top)
                self.front_circle(sk, xc, '%s - {ue}' % top, '2 * {ue}')
                r = self.ev(self.x('{ue}'))
                want = (2 - math.pi / 4) * r * r                # the square's area outside the quarter circle
                out.append(min((sk.profiles.item(i) for i in range(sk.profiles.count)),
                               key=lambda p: abs(p.areaProperties().area - want)))
        return out

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
    if has_face(o):                # faces cover the opening as set by Position, Reveal between them
        p = e('ep') if ref else '(%s)' % re.sub(r'\{(\w+)\}', lambda m: '(%s)' % o[m.group(1)], face_past(o))
        s['_face_given'] = True       # a cabinet may give its own reach past the side / top / bottom edge
        ps, pt, pb = ['(%s)' % o[k] if o.get(k) else p for k in ('_eps', '_ept', '_epb')]
        s['es'] = '%s + %s' % (e('sg'), ps)
        s['etop'] = '%s + %s' % (e('ot'), pt) if i == 1 else '%s - %s / 2' % (e('ot'), e('rev'))
        s['eb'] = '%s + %s' % (e('ob'), pb) if i == n else '%s - %s / 2' % (e('ob'), e('rev'))
        if flush_inset(o) and not o.get('_eps'):   # no slides: each box rides on its runner, face flush with it
            s['es'], s['eb'] = '0 mm', '0 mm'
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
        if v['sl'] > v['od'] + SNAP:
            out.append('The slides (%g mm) are longer than the opening is deep (%g mm).' % (v['sl'], v['od']))
        elif has_face(o) and int(o['epos']) == 0 and v['sl'] + v['et'] > v['od'] + SNAP:
            out.append('An inset face needs slide + face (%g mm) to fit the opening depth (%g mm): use a shorter '
                       'slide or an overlay face.' % (v['sl'] + v['et'], v['od']))
        if v['ot'] < 0 or v['ob'] < 0:
            out.append('Gaps above and below must be 0 or more.')
        if 'range' in sp:
            lo, hi = sp['range']
            if not (lo - SNAP <= v['sg'] <= hi + SNAP):
                out.append('These slides need %g to %g mm per side (never less).' % (lo, hi))
            if not any(abs(v['sl'] - L) < SNAP for L in sp['lengths']):   # inch text: 19.685 in = 499.999 mm
                out.append('These slides come in %s.' % sp['sold'])
            if v['ob'] < sp['min_below'] - SNAP:
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
    if o['top'] and o['pull'] in (1, 3):
        out.append('A finger pull or notch needs an open box (the top board fills the top edge): use a hand hole.')
    if o['pull'] == 3:
        if not (0 < v['ur'] < v['uw'] / 2 and v['ur'] <= v['uh']):
            out.append('Notch pull: the corner radius must be more than 0, less than half the width and at most the depth.')
        if v['ue'] < 0:
            out.append('Notch pull: the top edge radius must be 0 or more.')
        if v['uw'] + 2 * v['ue'] > inner_w - 10:
            out.append('Notch pull (with its top edge rounds) is wider than the front between the sides.')
        up3 = v['ftop'] if o['ff'] else face_mm(o, v)[1] if has_face(o) else 0
        if v['h'] + up3 - v['uh'] < (v['bt'] if o['bottom'] == 0 else v['gh'] + v['bt']) + 10:
            out.append('Notch pull goes down into the bottom: make it less deep.')
    if o['pull'] == 2:
        up = v['ftop'] if o['ff'] else face_mm(o, v)[1] if has_face(o) else 0     # front reaches past the box
        edge = (v['h'] + up if has_face(o) and up > 0 else v['h']) - (
            (v['bt'] if o['bottom'] == 0 else v['t']) if o['top'] else 0)           # face: its own top edge
        hole_top = v['h'] + up - v['pz'] + v['hh'] / 2
        if hole_top > edge - 3:
            out.append('Hand hole must end 3 mm below the top edge of the box front%s: make From top bigger.'
                       % (' (under the top board)' if o['top'] else ''))
        if hole_top - v['hh'] < (v['bt'] if o['bottom'] == 0 else v['gh'] + v['bt']) + 3:
            out.append('Hand hole runs into the bottom: make From top smaller.')
    if o['ff'] and (v['ft'] <= 0 or min(v['fs'], v['ftop'], v['fb']) < 0):
        out.append('False front: thickness must be more than 0, overhangs 0 or more.')
    if has_face(o):
        es, etp, eb = face_mm(o, v)
        if v['et'] <= 0:
            out.append('Face thickness must be more than 0.')
        if o['size'] == 1 and int(o['epos']) == 0 and v['em'] < 0:
            out.append('The inset gap must be 0 or more.')
        if min(es, etp, eb) < -1e-6:
            out.append('The face would be smaller than the box (%s): %s.' % (
                ', '.join(n for n, x in (('sides', es), ('top', etp), ('bottom', eb)) if x < -1e-6),
                ('make Box gap above at least the inset gap' if flush_inset(o) else
                 'make Gap per side, Box gap above and below at least the inset gap (%g mm)' % v['em'])
                if o['size'] == 1 else 'overhangs 0 or more'))
        if o['joints'] == 0 and int(o['ejoint']) == 0 and not (0.25 <= float(o['efrac']) <= 1):
            out.append('Slot depth: 0.25 to 1 x the face (1 = through).')
    return out


def check_bank(o):
    um = nm.design().unitsManager
    n = int(o['nd'])
    v = {k: um.evaluateExpression(o[k], 'mm') * 10 for k in ('oh', 'ot', 'ob', 'step', 'rev')}
    out = []
    if o['heights'] == 1 and v['step'] < 0:
        out.append('Taller by must be 0 or more.')
    if (o['ff'] or has_face(o)) and (v['rev'] < 0 or v['rev'] / 2 > min(v['ot'], v['ob'])):
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


def face_text(o, mm, bank=False):
    """One result line about the drawer face. mm(key) = value in mm."""
    joint = ('no joint into it (the sides butt against it)' if o['joints'] == 1 or int(o['ejoint']) == 2 else
             'tabs of the sides / bottom go through it' if int(o['ejoint']) == 1 else
             'blind slots %g mm deep for the tabs of the sides / bottom' % round(float(o['efrac']) * mm('et'), 2))
    if o['size'] == 1:
        pos = int(o['epos'])
        where = ('inset, %g mm gap to the opening' % mm('em') if pos == 0 else
                 'partial overlay, %g mm past the opening edges' % mm('eov') if pos == 1 else
                 'full overlay, %g mm short of the cabinet outside (cabinet board %g mm)' % (mm('efo'), mm('ect')))
        txt = 'Faces' if bank else 'Face'
        return '%s %s; %s%s' % (txt, where, joint, ', %g mm between the faces' % mm('rev') if bank else '')
    return 'Face %s thick, %s' % (o['et'], joint)


def build_bank(o):
    """Bank of drawers in one opening (open stack, no rails): one drawer per share of the opening, all sizes from the
    bank's own parameters, stacked with a Move that follows them. Returns (occurrences, text lines)."""
    o = dict(o, sl=catalog_length(o, o['sl']))       # 19.685 in -> 500 mm exactly
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
    keys += {1: ['pw', 'pd'], 2: ['hl', 'hh', 'pz'], 3: ['uw', 'uh', 'ur', 'ue']}.get(o['pull'], [])
    keys += (['ft', 'fs', 'ftop', 'fb', 'rev'] + (['hd'] if o['holes'] else [])) if o['ff'] else []
    face = has_face(o)
    keys += (['et', 'rev'] + list(EPOS_KEYS[int(o['epos'])])) if face else []
    same_et = face and abs(um.evaluateExpression(o['et'], 'mm') - um.evaluateExpression(o['t'], 'mm')) < 1e-6
    graduated = o['heights'] == 1
    keys += ['step'] if graduated else []
    bank_c = {'fs': 'false fronts: past the opening left and right', 'ftop': 'top false front: past the opening top',
              'fb': 'bottom false front: past the opening bottom'}
    up = des.userParameters
    for k in keys:
        e = ('%st' % B) if (k == 'bt' and same_t) or (k == 'et' and same_et) else o[k]
        up.add(B + k, VI(e), 'mm', '%s (bank): %s' % (o['name'], bank_c.get(k) or COMMENTS.get(k, k)))
    if face:
        up.add(B + 'ep', VI(re.sub(r'\{(\w+)\}', lambda m: B + m.group(1), face_past(o))), 'mm',
               '%s (bank): %s' % (o['name'], COMMENTS['ep']))
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
    col = ('max(%sow + 2 * %sfs; %ssl) + 100 mm' % (B, B, B) if o['ff'] else
           'max(%sow + 2 * abs(%sep); %ssl + %set) + 100 mm' % (B, B, B, B) if face else 'max(%sow; %ssl) + 100 mm' % (B, B))
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
        s['_y'] = '-%set' % B if face and o.get('_yface') else None     # overlay face: in front of the cabinet
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
    if face:
        lines.append(face_text(o, mm, bank=True))
    if o['ff']:
        lines.append('False fronts cover the opening: %g mm past it at the sides, %g at the top, %g at the bottom, '
                     '%g mm between them' % (mm('fs'), mm('ftop'), mm('fb'), mm('rev')))
    if o['flat']:
        lines.append('Flat copies for CAM made (one component per drawer)')
    nm.log('bank ' + ' | '.join(lines))
    return occs, lines


def engrave(o, m, comp, face, nfb, nlr):
    """Each board's name on its inside face (nm_engrave). Every face: the axis it lies on, its reading direction r
    and up u (r = u x the normal into the box, so it reads from inside), the clear area and the cut-outs in it."""
    import nm_engrave as ne
    name = o['name']
    yf = '{et}' if face else '{t}'
    zfloor = '{bt}' if o['bottom'] == 0 else '{gh} + {bt} + {gg}'      # above the bottom's tabs / groove
    ztop = '{h} - {tt}' if o['top'] else '{h}'
    zb = '{bt}' if o['bottom'] == 0 else '{gh} + {bt}'
    zt = '%s - {vdrop}' % ztop
    mid = '(%s + %s) / 2' % (zb, zt)
    dx = [('{vx%d} - {vw} / 2' % i, '{vx%d} + {vw} / 2' % i) for i in range(1, nfb + 1)]   # dados / laps
    dy = [('{vy%d} - {vw} / 2' % i, '{vy%d} + {vw} / 2' % i) for i in range(1, nlr + 1)]
    front_cut = []                            # the pull goes through the front (and the false front)
    if o['pull']:
        top = '{h} + {ftop}' if o['ff'] else '{h} + {etop}' if face else '{h}'
        if o['pull'] == 1:
            front_cut.append(('{w} / 2 - {pw} / 2', '{w} / 2 + {pw} / 2', '%s - {pd}' % top, top))
        elif o['pull'] == 2:
            front_cut.append(('{w} / 2 - {hl} / 2', '{w} / 2 + {hl} / 2', '%s - {pz} - {hh} / 2' % top,
                              '%s - {pz} + {hh} / 2' % top))
        else:
            front_cut.append(('{w} / 2 - {uw} / 2 - {ue}', '{w} / 2 + {uw} / 2 + {ue}', '%s - {uh}' % top, top))
    holes = []
    if o['ff'] and o['holes']:
        for x in ('{hx}', '{w} - {hx}'):
            for z in (('{h} / 2',) if o['holes'] == 1 else ('{hz}', '{h} - {hz}')):
                holes.append(('%s - {hd} / 2' % x, '%s + {hd} / 2' % x, '%s - {hd} / 2' % z, '%s + {hd} / 2' % z))
    full = lambda spans: [(a, b, None, None) for a, b in spans]
    walls_u = (zfloor, ztop)
    faces = [
        ('Left', ('L SIDE', 'L'), ('x', '{t}'), ('y', 1), ('z', 1), (yf, '{d} - {t}'), walls_u, full(dy)),
        ('Right', ('R SIDE', 'R'), ('x', '{w} - {t}'), ('y', -1), ('z', 1), (yf, '{d} - {t}'), walls_u, full(dy)),
        ('Front', ('FACE' if face else 'FRONT', 'F'), ('y', yf), ('x', -1), ('z', 1), ('{t}', '{w} - {t}'), walls_u,
         full(dx) + front_cut + holes),
        ('Back', ('BACK', 'BK'), ('y', '{d} - {t}'), ('x', 1), ('z', 1), ('{t}', '{w} - {t}'), walls_u, full(dx)),
        ('Bottom', ('BOTTOM', 'BOT'), ('z', zb), ('x', 1), ('y', 1), ('{t}', '{w} - {t}'), (yf, '{d} - {t}'),
         [(a, b, None, None) for a, b in (('{vx%d} - {vt} / 2' % i, '{vx%d} + {vt} / 2' % i) for i in range(1, nfb + 1))]
         + [(None, None, a, b) for a, b in (('{vy%d} - {vt} / 2' % i, '{vy%d} + {vt} / 2' % i)
                                             for i in range(1, nlr + 1))]),
    ]
    if o['top']:
        faces.append(('Top', ('TOP', 'TOP'), ('z', '{h} - {tt}'), ('x', -1), ('y', 1), ('{t}', '{w} - {t}'),
                      (yf, '{d} - {t}'), []))
    for i in range(1, nfb + 1):      # F-B dividers: notched from the top where the L-R ones cross
        faces.append(('Divider F-B %d' % i, ('DIV FB%d' % i, 'FB%d' % i), ('x', '{vx%d} + {vt} / 2' % i), ('y', 1),
                      ('z', 1), (yf, '{d} - {t}'), (zb, zt), [(a, b, mid, zt) for a, b in dy]))
    for i in range(1, nlr + 1):      # L-R dividers: notched from below where the F-B ones cross
        faces.append(('Divider L-R %d' % i, ('DIV LR%d' % i, 'LR%d' % i), ('y', '{vy%d} - {vt} / 2' % i), ('x', 1),
                      ('z', 1), ('{t}', '{w} - {t}'), (zb, zt), [(a, b, zb, mid) for a, b in dx]))
    if o['ff']:                      # its back, against the box front
        faces.append(('False front', ('FALSE FRONT', 'FF'), ('y', '0 mm'), ('x', -1), ('z', 1),
                      ('-{fs}', '{w} + {fs}'), ('-{fb}', '{h} + {ftop}'), list(front_cut)))
    have = {b.name for b in comp.bRepBodies}
    todo = [dict(body=n, labels=ne.labels(name, *parts), plane=pl, r=r, u=u, rr=rr, ur=ur, obst=ob)
            for n, parts, pl, r, u, rr, ur, ob in faces if n in have]
    placed, missing = ne.add(comp, todo, o.get('eh') or ne.DEFAULT_H, m.x, lambda e: m.ev(e) * 10)
    out = 'Part names on the inside faces (%s letters, for one V-bit pass: Trace / Engrave): %s' % (
        o.get('eh') or ne.DEFAULT_H, ', '.join(t for _, t in placed) or 'none')
    if missing:
        out += '. No room for: %s' % ', '.join(missing)
    return out


def build(o):
    """Builds the drawer from the dialog options o. Returns (occurrence, text lines)."""
    if o['size'] == 1 and not o.get('_pre'):
        o = dict(o, sl=catalog_length(o, o['sl']))   # 19.685 in -> 500 mm exactly
    des = nm.design()
    nm.ensure_globals(des)
    pre = o.get('_pre') or unique_prefix(des, o['name'])
    up = des.userParameters
    um = des.unitsManager
    same_t = abs(um.evaluateExpression(o['bt'], 'mm') - um.evaluateExpression(o['t'], 'mm')) < 1e-6
    face = has_face(o)
    same_et = face and abs(um.evaluateExpression(o['et'], 'mm') - um.evaluateExpression(o['t'], 'mm')) < 1e-6
    face_t = [('et', '{t}' if same_et else o['et'])] if face else []    # the face: its own thickness (3/4" on 1/2")
    if o['size'] == 1:
        params = [(k, o[k]) for k in OPENING_KEYS] + [('t', o['t'])] + face_t + [
            ('w', '{ow} - 2 * {sg}'), ('d', '{sl} + {et}' if face else '{sl}'), ('h', '{oh} - {ot} - {ob}')]
        # overall depth with a face: the face is in front of the sides, the sides = the slide
        if has_slides(o):
            params += [('sh', o['sh']), ('sline', '{h} / 2 + {sh} / 2' if o['spos'] == 0 else o['sline'])]
            if o['marks']:
                params += [('sback', o['sback']), ('smw', '1 mm'), ('smd', '0.5 mm')]
    else:
        params = [('t', o['t'])] + face_t + [('w', o['w']), ('d', o['d']), ('h', o['h'])]
    params += [('bt', '{t}' if same_t else o['bt'])]      # t / et come first: the face depth {sl} + {et} needs it
    blind = face and o['joints'] == 0 and int(o['ejoint']) == 0
    if face:
        params += face_params(o)
        if blind:
            params.append(('fd', '%g * {et}' % float(o['efrac'])))
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
                if key == 'vy' and face:          # front to back: from the inside of the face
                    params.append(('vy%d' % i, '{et} + %d * ({d} - {et} - {t}) / %d' % (i, n + 1)))
                else:
                    params.append(('%s%d' % (key, i), '{t} + %d * (%s - 2 * {t}) / %d' % (i, span, n + 1)))
    if o['pull'] == 1:
        params += [('pw', o['pw']), ('pd', o['pd'])]
    elif o['pull'] == 2:
        params += [('hl', o['hl']), ('hh', o['hh']), ('pz', o['pz'])]
    elif o['pull'] == 3:
        params += [('uw', o['uw']), ('uh', o['uh']), ('ur', o['ur']), ('ue', o['ue'])]
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
    if face:                      # the front is the face: wider / taller than the box, the sides butt into it
        lay0 = o['layout'] == 0
        walls = (('Left', '0', '{et}', '{t}', '{d}' if lay0 else '{d} - {t}'),
                 ('Right', '{w} - {t}', '{et}', '{w}', '{d}' if lay0 else '{d} - {t}'),
                 ('Front', '-{es}', '0', '{w} + {es}', '{et}'),
                 ('Back', '{t}' if lay0 else '0', '{d} - {t}', '{w} - {t}' if lay0 else '{w}', '{d}'))
    elif o['layout'] == 0:        # front & back between the sides
        walls = (('Left', '0', '0', '{t}', '{d}'), ('Right', '{w} - {t}', '0', '{w}', '{d}'),
                 ('Front', '{t}', '0', '{w} - {t}', '{t}'), ('Back', '{t}', '{d} - {t}', '{w} - {t}', '{d}'))
    else:                         # sides between front & back
        walls = (('Front', '0', '0', '{w}', '{t}'), ('Back', '0', '{d} - {t}', '{w}', '{d}'),
                 ('Left', '0', '{t}', '{t}', '{d} - {t}'), ('Right', '{w} - {t}', '{t}', '{w}', '{d} - {t}'))
    jointed = [m.box(n, x0, y0, x1, y1, '-{eb}' if face and n == 'Front' else '0',
                     '{h} + {etop}' if face and n == 'Front' else '{h}') for n, x0, y0, x1, y1 in walls]
    if face and int(o['ejoint']) == 2:     # butt: the face is not jointed (glue / screws / Dominos)
        jointed = [b for b in jointed if b.name != 'Front']
    yf = '{et}' if face else '{t}'          # inside of the front board
    inner = ('{t}', yf, '{w} - {t}', '{d} - {t}')
    if o['bottom'] == 0:
        jointed.append(m.box('Bottom', *inner, '0', '{bt}'))
    if o['top']:
        jointed.append(m.box('Top', *inner, '{h} - {tt}', '{h}'))
    exprs = dict(nm.DEFAULT_EXPR)
    exprs['relief'] = str(int(o['relief']))
    exprs['ratio'] = '%g' % float(o.get('fr', 2.0))
    if o['joints'] == 0:
        by_pair = ({frozenset(('Front', n)): {'depth': pre + 'fd'}
                    for n in ('Left', 'Right', 'Bottom', 'Top')} if blind else None)
        made, lines = nm.create_all([b.createForAssemblyContext(occ) for b in jointed], exprs, by_pair=by_pair)
    else:                         # plain panels that butt against each other: Domino, dowels, screws
        lines = ['No joints cut: the boards butt against each other (join them with Dominos, dowels or screws)']

    sides = lambda *names: [m.body(n) for n in names]
    if o['bottom'] == 1:
        m.box('Bottom groove', '{t} - {gd}', yf + ' - {gd}', '{w} - {t} + {gd}', '{d} - {t} + {gd}',
              '{gh} - {gg}', '{gh} + {bt} + {gg}', CUT, sides('Left', 'Right', 'Front', 'Back'))
        m.box('Bottom', '{t} - {gd} + {ge}', yf + ' - {gd} + {ge}', '{w} - {t} + {gd} - {ge}', '{d} - {t} + {gd} - {ge}',
              '{gh}', '{gh} + {bt}')
        lines.append('Bottom %s in a %s deep groove' % (o['bt'], o['gd']))
    if nfb or nlr:
        zb = '{bt}' if o['bottom'] == 0 else '{gh} + {bt}'
        ztop = '{h} - {tt}' if o['top'] else '{h}'
        zt = '%s - {vdrop}' % ztop                          # top edge of the dividers
        zdado = ztop if o['top'] else '{h} + 1 mm'
        for i in range(1, nfb + 1):       # front to back: dados in the front and back
            c = '{vx%d}' % i
            m.box('Dado F-B %d' % i, '%s - {vw} / 2' % c, yf + ' - {vd}', '%s + {vw} / 2' % c,
                  '{d} - {t} + {vd}', zb, zdado, CUT, sides('Front', 'Back'))
            m.box('Divider F-B %d' % i, '%s - {vt} / 2' % c, yf + ' - {vd} + {ge}', '%s + {vt} / 2' % c,
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
    if has_slides(o) and o['marks']:       # slide line grooves on the outside of the sides only
        # They stop one bit width short of the front / back boards, so they never cross a finger, slot or dogbone
        # (a groove over the joint would confuse the machining).
        cut = sides('Left', 'Right')
        clear = '{t} + nmj_bit'
        if face:
            y0 = '{et} + {sback}'                        # the sides start behind the face; nothing crosses them there
        else:
            y0 = clear if (um.evaluateExpression(o['t'], 'mm') + up.itemByName('nmj_bit').value
                          >= um.evaluateExpression(o['sback'], 'mm')) else '{sback}'
        for x0, x1 in (('0', '{smd}'), ('{w} - {smd}', '{w}')):
            m.box('Slide line', x0, y0, x1, '{d} - (%s)' % clear, '{sline} - {sh} / 2 - {smw} / 2',
                  '{sline} - {sh} / 2 + {smw} / 2', CUT, cut)    # on the slide's centre line (its screw holes)
        lines.append('Slide line grooves on both sides, on the centre line of the slide, clear of the joints')
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
        top = '{h} + {ftop}' if o['ff'] else '{h} + {etop}' if face else '{h}'
        sk = m.front_sketch('Pull')
        if o['pull'] == 3:
            sk = m.notch_pull(top, um.evaluateExpression(o['ue'], 'mm') > 1e-6, sk)
        elif o['pull'] == 1:        # circle through both ends of the scoop and its lowest point
            r = '({pw} * {pw} / 4 + {pd} * {pd}) / (2 * {pd})'      # Fusion rejects ^ on lengths
            m.front_circle(sk, '{w} / 2', '%s - {pd} + %s' % (top, r), '2 * %s' % r)
        else:
            zc = '%s - {pz}' % top
            half = '({hl} - {hh}) / 2'
            m.front_rect(sk, '{w} / 2 - %s' % half, '%s - {hh} / 2' % zc, '{w} / 2 + %s' % half, '%s + {hh} / 2' % zc)
            for sgn in ('-', '+'):
                m.front_circle(sk, '{w} / 2 %s %s' % (sgn, half), zc, '{hh}')
        m.extrude(sk, CUT, parts=sides(*fronts), through='2 * ({t} + {ft}) + 10 mm' if o['ff'] else
                  '2 * {et} + 10 mm' if face else '2 * {t} + 10 mm').name = 'Pull'
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
            lines.insert(1, '%s, %g mm, %s: top of the drawer slide %g mm up from the bottom edge of the box sides '
                         '(its centre line %g mm up), %g mm back from the box front; top of the cabinet slide %g mm up '
                         'from the opening bottom%s (follows %s_sline in the parameters)'
                         % (sp['name'], mm('sl'), 'centred on the sides' if o['spos'] == 0 else 'typed line', round(L, 2),
                            round(L - mm('sh') / 2, 2), mm('sback'), round(mm('ob') + L, 2),
                            ', %g mm back' % sp.get('cab_back', 2) if 'line' in sp else '', pre.rstrip('_')))
            if face:
                lines[1] = lines[1].replace('back from the box front', 'back from the front of the box sides (behind the face)')
    if face and not o.get('_face_given'):
        fm = lambda k: um.evaluateExpression(pre + k, 'mm') * 10
        lines.append(face_text(o, lambda k: um.evaluateExpression(o[k], 'mm') * 10 if k in o else fm(k)))
        lines.append('Face %g x %g mm: %g past the box sides, %g above, %g below'
                     % (round(fm('w') + 2 * fm('es'), 2), round(fm('h') + fm('etop') + fm('eb'), 2),
                        round(fm('es'), 2), round(fm('etop'), 2), round(fm('eb'), 2)))
    lines.insert(0, '%s: parameters %s* (Modify > Change Parameters)' % (o['name'], pre))
    if o.get('engrave'):          # before the move to its place: that move takes every body, the names too
        try:
            lines.append(engrave(o, m, comp, face, nfb, nlr))
        except Exception:
            nm.log('part names failed:\n' + traceback.format_exc())
            lines.append('Part names failed (see nmj_log.txt)')
    if o.get('_z') or o.get('_x') or o.get('_y'):   # bank / cabinet: to its place, follows the parameters
        bodies = adsk.core.ObjectCollection.create()
        for b in comp.bRepBodies:
            bodies.add(b)
        mi = comp.features.moveFeatures.createInput2(bodies)
        mi.defineAsTranslateXYZ(VI(o.get('_x') or '0 mm'), VI(o.get('_y') or '0 mm'), VI(o.get('_z') or '0 mm'), True)
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
    'slide': 'Sets the gap per side, the slide height / setback and the lengths the slides come in (the longest that '
             'fits the opening depth is picked). All full extension. Lee Valley 100 lb, hold-out, touch-open and 75 lb '
             'need 1/2" per side (12.7-13.5 mm); the 200 lb (heavy drawers) 3/4" (19.05-19.45 mm). Accuride 3832E / '
             'KV 8450FM fit the Lee Valley 100 lb settings. Anything else: Other side-mount, type its gap.',
    'sg': 'Room for one slide: the box is this much narrower than the opening on each side.',
    'sl': 'Slide length = box depth.',
    'ot': 'Clearance between the top of the box sides and the top of the opening (not the slide: Slide position '
          'sets where the slide sits on the box sides).',
    'marks': 'Cuts a shallow groove (0.5 mm deep, 1 mm high) on the outside of both sides, on the centre line of '
             'the slide (where its screw holes are), so you can line the drawer slide up. It sits under the slide, so it does not show. '
             'Cut it with a V-bit / engraving pass (or set <name>_smw to the bit width).',
    'spos': 'Centred: the slide sits in the middle of the box sides (its centre line = half the box height; top of '
            'slide = half the box height + half the slide height), and the cabinet line follows. Typed: you give the line (Lee Valley sheet: 44 mm).',
    'sh': 'Height of the slide itself (Lee Valley 61080: 1 13/16" = 46.04 mm).',
    'sline': 'Top of the drawer slide, up from the bottom edge of the box sides (Lee Valley 61080: 44 mm).',
    'sback': 'Where the slide starts, back from the box front (Lee Valley 61080 soft-close: 5.2 mm).',
    'ob': 'Clearance under the box sides, to the bottom of the opening (1/4" default, the slide needs at least 1/4"). '
          'With a drawer face the face hides it.',
    'preset': 'Pick a saved setup to fill in every field below. Defaults = the add-in\'s own starting values.',
    'pname': 'Name for the current setup, e.g. Kitchen drawer or Screw sorter. The same name again updates it.',
    'psave': 'Save every field below under the name above.',
    'pdel': 'Delete the preset picked above (not the drawers made with it).',
    'name': 'Name of the new component; its parameters start with this name (e.g. drawer_w).',
    'layout': 'Which boards run the full length: the sides (front and back sit between them) or the front and back.',
    'w': 'Outside width, left to right.', 'd': 'Outside depth, front to back.', 'h': 'Outside height of the sides.',
    't': 'Thickness of the sides, front and back. Default 12 mm = 1/2" Baltic birch (measure your sheet).',
    'relief': 'Inside corners of the finger joints: dogbones or T-bones (see NM Joint).',
    'fr': 'Finger and tab width = this x the board thickness (2 = twice the board; 2.5 or 3 = wider fingers). '
          'A low side still gets at least 3 fingers, so they come out narrower there (the result says so).',
    'joints': 'Finger joints and tabs cut by the CNC, or none: plain panels that butt against each other, '
              'for joining with a Domino, dowels or screws (no CNC needed). Sizes stay the same.',
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
    'uw': 'Width of the notch (between its straight sides). 127 mm = 5 in.',
    'uh': 'How far the notch goes down from the top edge. 44.45 mm = 1 3/4 in; use less on low drawers.',
    'ur': 'Radius of the two bottom corners (12.7 mm = 1/2 in). Less than half the width, at most the depth.',
    'ue': 'Radius where the notch meets the top edge, so no sharp corner for the fingers (6.35 mm = 1/4 in). '
          '0 = sharp. A 1/4 in or smaller bit cuts it in one pass.',
    'ff': 'A separate front board screwed on from the inside, overhanging the box.',
    'front': 'Plain: the box front is a board like the others. False front: a separate board screwed on, overhanging '
             'the box. Face: the box front itself is the drawer face (same board, wider / taller than the box); the '
             'sides and bottom join it end-on. Depth is then overall, face included.',
    'ejoint': 'How the sides / bottom join the face. Blind: tabs into slots that do not go through (hidden from the '
              'front). Through: the tab ends show on the face. Butt: no joint, the face is glued / screwed on.',
    'efrac': 'Blind slot depth as a part of the face thickness (0.75 = 3/4 of it; 1 = through).',
    'et': 'Face thickness: the box front can be thicker than the rest of the box, e.g. a 3/4" (18 mm) face on a '
          '1/2" (12 mm) box. The same as Board thickness = linked to it. With an Inset face the slides start one '
          'face thickness back.',
    'esame': 'The face is as high as the box sides (only wider).',
    'es': 'How far the face reaches past the box sides, left and right (the slide gap covers the slides).',
    'etop': 'How far the face reaches above the box sides (2" by default: covers the gap above in a cabinet).',
    'eb': 'How far the face reaches below the bottom of the box sides.',
    'epos': 'Inset: the face sits inside the opening with a gap all round (the slides go one face thickness back). '
            'Partial overlay: the face laps the opening edges (face frames). Full overlay: the face covers the '
            'cabinet edge, a little short of the outside so cabinets side by side keep a gap. '
            'No slides + Inset: the box rides on the shelf, so the face is flush with the box sides and bottom; '
            'Gap per side is the side reveal (set to the inset gap for you).',
    'em': 'Inset face: gap between the face and the opening, all round (1/8").',
    'eov': 'Partial overlay: how far the face laps over the opening edges (3/8" is common).',
    'ect': 'Full overlay: the cabinet board thickness at the opening edge (the face covers it).',
    'efo': 'Full overlay: the face stops this much short of the cabinet outside (1/16"; two cabinets side by side '
           'then have 1/8" between their faces).',
    'ft': 'False front thickness.', 'fs': 'Overhang left and right.', 'ftop': 'Overhang at the top.',
    'fb': 'Overhang at the bottom.', 'holes': 'Clearance holes in the box front for the screws.',
    'hd': 'Screw clearance hole diameter.',
    'nd': 'More than 1 = a bank of drawers stacked in this one opening (no rails between them). Each drawer gets '
          'its share of the opening height; the gaps above / below apply to every drawer.',
    'heights': 'All the same, or graduated (kitchen style): each drawer is Taller by more than the one above it.',
    'step': 'How much higher each drawer is than the one above it.',
    'rev': 'Bank of drawers: the gap between the drawer faces (or false fronts), 1/8" = 3.175 mm by default. With '
           'false fronts, Sides / Top / Bottom are how far they reach past the opening edges; with face = box front, '
           'Face position sets that.',
    'flat': 'Also make a flat copy of every board (inside face up) in its own component, for CAM. It follows size changes.',
    'engrave': 'Puts each board\'s name (e.g. KITCHEN DRAWER 2 L SIDE) on its inside face in single-stroke capitals, '
               'clear of the joints, grooves, dados and cut-outs; shortened (KD2 L) where it does not fit. Nothing is '
               'cut from the board: the letters are lines (a body "<board> name") for one V-bit pass in CAM: Trace '
               'or Engrave, e.g. the 60 deg V-bit 0.5 mm deep (a line about 0.6 mm wide). They follow size changes and '
               'come along on the flat copies.',
    'eh': 'Height of the capitals (1/4 in = 6.35 mm).',
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
    memo.clear()
    _dropdown(inputs, 'units', 'Units', UNITS, int(o.get('units', 0))).tooltip = UNITS_TIP
    add_err(inputs)
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
    for k, label in (('sg', 'Gap per side'), ('sl', 'Slide length'), ('ot', 'Box gap above'), ('ob', 'Box gap below')):
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
    _dropdown(c, 'joints', 'Joints', JOINTS, o['joints'])
    _dropdown(c, 'relief', 'Corners', nm.RELIEF_NAMES, o['relief'])
    _tip(c.addFloatSpinnerCommandInput('fr', 'Finger x board', '', 1, 6, 0.5, float(o.get('fr', 2.0))))
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
    val(c, 'uw', 'Width')
    val(c, 'uh', 'Depth')
    val(c, 'ur', 'Corner r')
    val(c, 'ue', 'Top edge r')
    g = inputs.addGroupCommandInput('g_ff', 'Front')
    front = 1 if o['ff'] else int(o.get('front', 0))
    g.isExpanded = bool(front)
    c = g.children
    _dropdown(c, 'front', 'Front', FRONTS, front)
    val(c, 'et', 'Face thick')
    _dropdown(c, 'ejoint', 'Into the face', EJOINTS, int(o['ejoint']))
    _tip(c.addFloatSpinnerCommandInput('efrac', 'Slot depth x face', '', 0.25, 1, 0.05, float(o['efrac'])))
    _tip(c.addBoolValueInput('esame', 'Same height as sides', True, '', bool(o['esame'])))
    val(c, 'es', 'Past sides')
    val(c, 'etop', 'Above')
    val(c, 'eb', 'Below')
    _dropdown(c, 'epos', 'Position', EPOS, int(o['epos']))
    val(c, 'em', 'Inset gap')
    val(c, 'eov', 'Overlap')
    val(c, 'ect', 'Cabinet board')
    val(c, 'efo', 'Short of edge')
    val(c, 'ft', 'Thick')
    val(c, 'fs', 'Sides')
    val(c, 'ftop', 'Top')
    val(c, 'fb', 'Bottom')
    val(c, 'rev', 'Reveal')
    _dropdown(c, 'holes', 'Screws', SCREWS, o['holes'])
    val(c, 'hd', 'Hole dia')
    _tip(inputs.addBoolValueInput('engrave', 'Engrave part names', True, '', bool(o.get('engrave'))))
    val(inputs, 'eh', 'Letter height')
    _tip(inputs.addBoolValueInput('flat', 'Lay flat', True, '', o['flat']))
    inputs.addTextBoxCommandInput('msg', '', '', 3, True)
    show(inputs)
    to_units(inputs, VALUE_KEYS, memo)
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
        mm = {k: um.evaluateExpression(dexpr(inputs, k), 'mm') * 10 for k in OPENING_KEYS}
    except Exception:
        return
    if pick_length and sp.get('none') and abs(mm['sl'] - mm['od']) > 1e-6:
        it('sl').expression = it('od').expression          # no slides: as deep as the opening
        mm['sl'] = mm['od']
    if pick_length and 'lengths' in sp:
        fits = [L for L in sp['lengths'] if L <= mm['od'] + SNAP]
        if fits and abs(fits[-1] - mm['sl']) > SNAP:
            it('sl').expression = fmt(fits[-1], inch(inputs))
            mm['sl'] = fits[-1]
    hh = mm['oh'] - mm['ot'] - mm['ob']
    if it('nd').value > 1:
        try:
            o = {'nd': it('nd').value, 'oh': dexpr(inputs, 'oh'), 'heights': it('heights').selectedItem.index,
                 'step': dexpr(inputs, 'step')}
            hs = [x - mm['ot'] - mm['ob'] for x in bank_slots(o)]
            hh = hs[0]
            note = 'Drawer boxes, top to bottom: %s mm high (Height shows the top one).' % ', '.join(
                '%g' % round(x, 1) for x in hs)
        except Exception:
            pass
    face = it('front').selectedItem.index == 2          # overall depth: face + sides (the sides = the slide)
    tt = um.evaluateExpression(dexpr(inputs, 'et'), 'mm') * 10 if face else 0
    for k, v in (('w', mm['ow'] - 2 * mm['sg']), ('h', hh), ('d', mm['sl'] + tt)):
        if abs(it(k).value * 10 - v) > 1e-6:
            it(k).expression = fmt(v, inch(inputs))


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
    for k in ('top', 'flat', 'marks', 'esame'):
        it(k).value = bool(o[k])
    if o['ff']:                                   # a preset from before 0.9.0
        it('front').listItems.item(1).isSelected = True
    it('efrac').value = float(o['efrac'])
    it('nd').value = int(o['nd'])
    it('g_div').isExpanded = bool(o['div_fb'] or o['div_lr'])
    it('g_pull').isExpanded = bool(o['pull'])
    it('g_ff').isExpanded = bool(o['ff'] or int(o['front']))
    it('g_open').isExpanded = bool(o['size'])
    memo.clear()
    to_units(inputs, VALUE_KEYS, memo)            # a preset saved in the other units
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
    it('relief').isVisible = it('joints').selectedItem.index == 0 or div    # dividers half-lap with it too
    it('fr').isVisible = it('joints').selectedItem.index == 0
    pull = it('pull').selectedItem.index
    for k in ('pw', 'pd'):
        it(k).isVisible = pull == 1
    for k in ('hl', 'hh', 'pz'):
        it(k).isVisible = pull == 2
    for k in ('uw', 'uh', 'ur', 'ue'):
        it(k).isVisible = pull == 3
    front = it('front').selectedItem.index
    ff, face = front == 1, front == 2
    for k in ('ft', 'fs', 'ftop', 'fb', 'holes', 'hd'):
        it(k).isVisible = ff
    it('rev').isVisible = (ff or face) and bank
    it('hd').isVisible = ff and it('holes').selectedItem.index > 0
    joints = it('joints').selectedItem.index == 0
    it('ejoint').isVisible = face and joints
    it('et').isVisible = face
    it('efrac').isVisible = face and joints and it('ejoint').selectedItem.index == 0
    same = it('esame').value
    it('esame').isVisible = it('es').isVisible = face and not opening
    it('etop').isVisible = it('eb').isVisible = face and not opening and not same
    it('epos').isVisible = face and opening
    pos = it('epos').selectedItem.index
    for k, p in (('em', 0), ('eov', 1), ('ect', 2), ('efo', 2)):
        it(k).isVisible = face and opening and pos == p
    it('eh').isVisible = it('engrave').value


def read(inputs):
    it = inputs.itemById
    o = {'name': it('name').value.strip() or 'Drawer'}
    for k in DROPDOWNS:
        o[k] = it(k).selectedItem.index
    for k in VALUE_KEYS:
        o[k] = dexpr(inputs, k)
    o['div_fb'], o['div_lr'] = it('div_fb').value, it('div_lr').value
    o['nd'] = it('nd').value
    o['fr'] = round(it('fr').value, 2)
    for k in ('top', 'flat', 'marks', 'esame', 'engrave'):
        o[k] = it(k).value
    o['ff'] = o['front'] == 1
    o['efrac'] = round(it('efrac').value, 2)
    o['units'] = 1 if inch(inputs) else 0
    o['slide_id'] = SLIDES[o['slide']]['id']
    return o


def emm(inputs, k):
    """A value input in mm, from its expression (.value can lag behind an expression set by code)."""
    try:
        return nm.design().unitsManager.evaluateExpression(dexpr(inputs, k), 'mm') * 10
    except Exception:
        return inputs.itemById(k).value * 10


def _mm(e):
    return nm.design().unitsManager.evaluateExpression(e, 'mm') * 10


memo = {}           # units toggle: text before the last switch, per input


def add_err(inputs):
    """A red line at the top saying why OK is greyed out (the full message is at the bottom)."""
    e = inputs.addTextBoxCommandInput('err', '', '', 2, True)
    e.isFullWidth = True
    e.isVisible = False


def show_err(inputs, bad):
    e = inputs.itemById('err')
    if e:
        e.formattedText = '<span style="color:#ff6b6b"><b>OK is off:</b> %s</span>' % bad[0] if bad else ''
        e.isVisible = bool(bad)


class Changed(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        global note, applying
        try:
            inputs = args.input.parentCommand.commandInputs   # args.inputs is only the group for grouped inputs
            if applying:
                return
            if preset_event(inputs, args.input.id):
                show(inputs)
                return
            note = ''
            iid = args.input.id
            if iid == 'units':
                applying = True
                try:
                    to_units(inputs, VALUE_KEYS, memo)
                finally:
                    applying = False
                show(inputs)
                return
            ins = inch(inputs)
            if iid == 'slide':
                sp = SLIDES[args.input.selectedItem.index]
                if sp['gap']:
                    face_on = inputs.itemById('front').selectedItem.index == 2 and not sp.get('none')
                    inputs.itemById('sg').expression = fmt(_mm(sp['gap']), ins)
                    inputs.itemById('ob').expression = fmt(_mm(FACE_GAPS['ob'] if face_on else sp['below']), ins)
                    if (sp.get('none') and inputs.itemById('front').selectedItem.index == 2
                            and inputs.itemById('epos').selectedItem.index == 0):
                        inputs.itemById('sg').expression = inputs.itemById('em').expression
                if 'line' in sp:
                    inputs.itemById('sline').expression = fmt(sp['line'], ins)
                    inputs.itemById('sh').expression = fmt(sp['high'], ins)
                    inputs.itemById('sback').expression = fmt(sp['back'], ins)
            if iid in ('front', 'epos') and SLIDES[inputs.itemById('slide').selectedItem.index].get('none'):
                if (inputs.itemById('front').selectedItem.index == 2 and inputs.itemById('epos').selectedItem.index == 0
                        and emm(inputs, 'sg') < emm(inputs, 'em') - 1e-6):
                    inputs.itemById('sg').expression = inputs.itemById('em').expression   # side gap = reveal
            if iid == 'front':                   # face: 1" / 1/4" box gaps; back to the slide's own when not
                sp = SLIDES[inputs.itemById('slide').selectedItem.index]
                if sp['gap'] and not sp.get('none'):
                    ot, ob = inputs.itemById('ot'), inputs.itemById('ob')
                    plain = (_mm(DEFAULTS['ot']), _mm(sp['below']))
                    facev = (_mm(FACE_GAPS['ot']), _mm(FACE_GAPS['ob']))
                    now = (round(emm(inputs, 'ot'), 2), round(emm(inputs, 'ob'), 2))
                    face_on = args.input.selectedItem.index == 2
                    old, new = (plain, facev) if face_on else (facev, plain)
                    if all(abs(a - b) < SNAP for a, b in zip(now, old)):     # only when not typed by hand
                        ot.expression, ob.expression = fmt(new[0], ins), fmt(new[1], ins)
            if iid in OPENING_KEYS + ('size', 'slide', 'nd', 'heights', 'step', 'front', 't', 'et'):
                fit(inputs, pick_length=iid in ('od', 'slide', 'size'))
            if args.input.id == 'bottom':        # groove: a thin panel; fingers: the board thickness
                um = nm.design().unitsManager
                bt, t = inputs.itemById('bt'), inputs.itemById('t')
                if args.input.selectedItem.index == 1 and abs(bt.value - t.value) < 1e-9:
                    bt.expression = fmt(6, ins)
                elif args.input.selectedItem.index == 0:
                    bt.expression = t.expression
            elif args.input.id == 'vstock':
                e = VSTOCK[args.input.selectedItem.index][1]
                if e:
                    inputs.itemById('vt').expression = fmt(_mm(e), ins)
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
            show_err(args.inputs, bad)
        except Exception:
            args.areInputsValid = False
            try:
                args.inputs.itemById('msg').formattedText = 'A value is not a valid size (use e.g. 450 mm).'
                show_err(args.inputs, ['a value is not a valid size (use e.g. 450 mm or 17.75 in).'])
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
            import nm_edit
            nm_edit.made('drawer', o)           # builds it + the timeline item to edit it later
        except Exception:
            nm.log('drawer failed:\n' + traceback.format_exc())
            nm.ui.messageBox('NM Drawer failed:\n' + traceback.format_exc())


class Created(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = args.command
            cmd.isExecutedWhenPreEmpted = False      # starting another command = Cancel, not OK (an auto-OK mid-build crashed Fusion)
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
