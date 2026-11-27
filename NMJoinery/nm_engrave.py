# NM Joinery - engraved part names (clean-room). Each board gets its name ("KITCHEN D1 L SIDE") on its inside face
# in single-stroke capitals, for one V-bit pass (Trace or Engrave in CAM, e.g. a 60 deg V-bit 0.5 mm deep).
# The letters are a wire body (lines only, no solid, nothing is cut from the board) named "<board> name":
# - a Move feature with parameter expressions puts it on the face, so it follows every size change;
# - NM Lay Flat copies it with its board (same turn and move), so the flat copies carry it too.
# The font is our own: every glyph is a few straight strokes on a 4 x 6 grid (6 = cap height).
import adsk.core, adsk.fusion, re

VI = adsk.core.ValueInput.createByString
SUFFIX = ' name'                 # body name = board name + this (NM Lay Flat pairs them by it)
CELL_W, CELL_H = 4.0, 6.0
ADV = 5.6                        # glyph advance: 4 wide + 1.6 space
MARGIN = 3.0                     # mm clear of the face edges, joints, grooves, dados and cut-outs
DEFAULT_H = '6.35 mm'            # 1/4 in letters

_O = [(1, 0), (0, 1), (0, 5), (1, 6), (3, 6), (4, 5), (4, 1), (3, 0), (1, 0)]
_P = [(0, 0), (0, 6), (3, 6), (4, 5), (4, 4), (3, 3), (0, 3)]
FONT = {
    'A': [[(0, 0), (2, 6), (4, 0)], [(0.67, 2), (3.33, 2)]],
    'B': [[(0, 3), (3, 3), (4, 2), (4, 1), (3, 0), (0, 0), (0, 6), (3, 6), (4, 5), (4, 4), (3, 3)]],
    'C': [[(4, 5), (3, 6), (1, 6), (0, 5), (0, 1), (1, 0), (3, 0), (4, 1)]],
    'D': [[(0, 0), (0, 6), (2.5, 6), (4, 4.5), (4, 1.5), (2.5, 0), (0, 0)]],
    'E': [[(4, 6), (0, 6), (0, 0), (4, 0)], [(0, 3), (3, 3)]],
    'F': [[(4, 6), (0, 6), (0, 0)], [(0, 3), (3, 3)]],
    'G': [[(4, 5), (3, 6), (1, 6), (0, 5), (0, 1), (1, 0), (3, 0), (4, 1), (4, 3), (2, 3)]],
    'H': [[(0, 0), (0, 6)], [(4, 0), (4, 6)], [(0, 3), (4, 3)]],
    'I': [[(2, 0), (2, 6)]],
    'J': [[(4, 6), (4, 1), (3, 0), (1, 0), (0, 1)]],
    'K': [[(0, 0), (0, 6)], [(4, 6), (0, 2)], [(1.33, 3.33), (4, 0)]],
    'L': [[(0, 6), (0, 0), (4, 0)]],
    'M': [[(0, 0), (0, 6), (2, 3), (4, 6), (4, 0)]],
    'N': [[(0, 0), (0, 6), (4, 0), (4, 6)]],
    'O': [_O],
    'P': [_P],
    'Q': [_O, [(2.5, 1.5), (4, 0)]],
    'R': [_P, [(2, 3), (4, 0)]],
    'S': [[(4, 5), (3, 6), (1, 6), (0, 5), (0, 4), (1, 3), (3, 3), (4, 2), (4, 1), (3, 0), (1, 0), (0, 1)]],
    'T': [[(0, 6), (4, 6)], [(2, 6), (2, 0)]],
    'U': [[(0, 6), (0, 1), (1, 0), (3, 0), (4, 1), (4, 6)]],
    'V': [[(0, 6), (2, 0), (4, 6)]],
    'W': [[(0, 6), (1, 0), (2, 4), (3, 0), (4, 6)]],
    'X': [[(0, 0), (4, 6)], [(0, 6), (4, 0)]],
    'Y': [[(0, 6), (2, 3), (4, 6)], [(2, 3), (2, 0)]],
    'Z': [[(0, 6), (4, 6), (0, 0), (4, 0)]],
    '0': [_O, [(1, 1.5), (3, 4.5)]],
    '1': [[(0.5, 4.5), (2, 6), (2, 0)], [(0.5, 0), (3.5, 0)]],
    '2': [[(0, 5), (1, 6), (3, 6), (4, 5), (4, 4), (0, 0), (4, 0)]],
    '3': [[(0, 5), (1, 6), (3, 6), (4, 5), (4, 4), (3, 3), (4, 2), (4, 1), (3, 0), (1, 0), (0, 1)], [(1.5, 3), (3, 3)]],
    '4': [[(3, 0), (3, 6), (0, 2), (4, 2)]],
    '5': [[(4, 6), (0, 6), (0, 3.5), (3, 3.5), (4, 2.5), (4, 1), (3, 0), (1, 0), (0, 1)]],
    '6': [[(4, 5), (3, 6), (1, 6), (0, 5), (0, 1), (1, 0), (3, 0), (4, 1), (4, 2), (3, 3), (0, 3)]],
    '7': [[(0, 6), (4, 6), (1.5, 0)]],
    '8': [[(1, 3), (0, 4), (0, 5), (1, 6), (3, 6), (4, 5), (4, 4), (3, 3), (1, 3), (0, 2), (0, 1), (1, 0), (3, 0),
           (4, 1), (4, 2), (3, 3)]],
    '9': [[(4, 3), (1, 3), (0, 4), (0, 5), (1, 6), (3, 6), (4, 5), (4, 1), (3, 0), (1, 0), (0, 1)]],
    '-': [[(0.5, 3), (3.5, 3)]],
    '+': [[(2, 1), (2, 5)], [(0, 3), (4, 3)]],
    '/': [[(0, 0), (4, 6)]],
    '.': [[(1.7, 0), (2.3, 0), (2.3, 0.6), (1.7, 0.6), (1.7, 0)]],
    '(': [[(2.5, 6.5), (1, 5), (1, 1), (2.5, -0.5)]],
    ')': [[(1.5, 6.5), (3, 5), (3, 1), (1.5, -0.5)]],
    '#': [[(1.3, 0), (1.3, 6)], [(2.7, 0), (2.7, 6)], [(0, 2), (4, 2)], [(0, 4), (4, 4)]],
    '&': [[(4, 0), (0.5, 4.5), (0.5, 5.5), (1, 6), (2, 6), (2.5, 5.5), (2.5, 4.5), (0, 2), (0, 1), (1, 0), (2.5, 0),
           (4, 2)]],
}


def clean(text):
    """Upper case, only what the font has (anything else becomes a space), single spaces."""
    t = ''.join(c if c in FONT else ' ' for c in (text or '').upper())
    return re.sub(r'\s+', ' ', t).strip()


def width_mm(text, h):
    n = len(text)
    return 0.0 if not n else (n * ADV - (ADV - CELL_W)) * h / CELL_H


def strokes(text):
    """Polylines in font units, the text's middle at x = 0, baseline y = 0."""
    x0 = -(len(text) * ADV - (ADV - CELL_W)) / 2
    out = []
    for i, c in enumerate(text):
        for line in FONT.get(c, []):
            out.append([(x0 + i * ADV + x, y) for x, y in line])
    return out


def initials(name):
    """'Kitchen drawer 2' -> 'KD2', 'Cabinet S1 drawer 3' -> 'CS1D3'."""
    out = ''
    for w in clean(name).split():
        out += w if any(ch.isdigit() for ch in w) else w[0]
    return out


def labels(name, long_part, short_part):
    """The texts to try, longest first."""
    n, i = clean(name), initials(name)
    out = []
    for t in ('%s %s' % (n, long_part), '%s %s' % (n, short_part), '%s %s' % (i, long_part), '%s %s' % (i, short_part)):
        t = clean(t)
        if t and t not in out:
            out.append(t)
    return out


def _free(lo, hi, blocks):
    """lo / hi = (mm, expression); blocks [(mm0, expr0, mm1, expr1)]: the gaps between them, widest first."""
    gaps = [(lo, hi)]
    for b0, e0, b1, e1 in blocks:
        nxt = []
        for a, b in gaps:
            if b0 - MARGIN >= b[0] or b1 + MARGIN <= a[0]:
                nxt.append((a, b))
                continue
            if b0 - MARGIN > a[0]:
                nxt.append((a, (b0 - MARGIN, '(%s) - %g mm' % (e0, MARGIN))))
            if b1 + MARGIN < b[0]:
                nxt.append(((b1 + MARGIN, '(%s) + %g mm' % (e1, MARGIN)), b))
        gaps = [(a, b) for a, b in nxt if b[0] > a[0]]
    return sorted(gaps, key=lambda g: g[0][0] - g[1][0])


def place(face, h, ev):
    """Where the name goes on one face. face: dict with
         labels  texts to try, longest first
         r, u    (axis, sign): the reading direction and 'up' of the letters (u sign is +1)
         rr, ur  (lo, hi) expressions of the clear area along r and u (world coordinates on those axes)
         obst    [(r0, r1, u0, u1)] expressions of cut-outs / dados in it (None = from edge to edge)
    ev(expr) -> mm. Returns (text, centre expression along r, baseline expression along u) or None."""
    r_lo, r_hi = face['rr']
    u_lo, u_hi = face['ur']
    rl, rh, ul, uh = ev(r_lo), ev(r_hi), ev(u_lo), ev(u_hi)
    if uh - ul < h + 2 * MARGIN:
        return None
    bands = [(ul + MARGIN, '(%s) + %g mm' % (u_lo, MARGIN)),
             (uh - MARGIN - h, '(%s) - %g mm' % (u_hi, MARGIN + h))]
    for text in face['labels']:
        w = width_mm(text, h)
        for b, be in bands:
            blocks = []
            for r0, r1, u0, u1 in face.get('obst', []):
                if u0 is not None and (ev(u1) <= b - MARGIN or ev(u0) >= b + h + MARGIN):
                    continue                        # above or below the letters
                if r0 is None:
                    blocks = None                   # right across the face: this band is out
                    break
                blocks.append((ev(r0), r0, ev(r1), r1))
            if blocks is None:
                continue
            for a, z in _free((rl + MARGIN, '(%s) + %g mm' % (r_lo, MARGIN)),
                              (rh - MARGIN, '(%s) - %g mm' % (r_hi, MARGIN)), blocks):
                if z[0] - a[0] >= w:
                    return text, '((%s) + (%s)) / 2' % (a[1], z[1]), be
                break                               # only the widest gap can hold it
    return None


def _wire(text, h_cm, r, u):
    """Wire body of the text, its middle / baseline at the origin; r, u = unit Vector3D."""
    k = h_cm / CELL_H
    curves = []
    for line in strokes(text):
        pts = [adsk.core.Point3D.create(r.x * x * k + u.x * y * k, r.y * x * k + u.y * y * k, r.z * x * k + u.z * y * k)
               for x, y in line]
        for a, b in zip(pts, pts[1:]):
            if a.distanceTo(b) > 1e-6:
                curves.append(adsk.core.Line3D.create(a, b))
    if not curves:
        return None
    body = adsk.fusion.TemporaryBRepManager.get().createWireFromCurves(curves, True)
    return body[0] if isinstance(body, (list, tuple)) else body


AXES = {'x': (1, 0, 0), 'y': (0, 1, 0), 'z': (0, 0, 1)}


def add(comp, faces, h_expr, ex, ev):
    """faces: as in place(), plus 'body' (board name) and 'plane' (axis, expression of the face). ex expands {key};
    ev(expr) -> mm. Adds one base feature with the wire bodies and a Move per name. Returns (placed, missing):
    [(board, text)], [board names without room]."""
    h = ev(h_expr)
    todo, missing = [], []
    for f in faces:
        f = dict(f, rr=tuple(ex(e) for e in f['rr']), ur=tuple(ex(e) for e in f['ur']),
                 obst=[tuple(None if e is None else ex(e) for e in o) for o in f.get('obst', [])])
        p = place(f, h, ev)
        if not p:
            missing.append(f['body'])
            continue
        text, rc, ub = p
        r = adsk.core.Vector3D.create(*[c * f['r'][1] for c in AXES[f['r'][0]]])
        u = adsk.core.Vector3D.create(*[c * f['u'][1] for c in AXES[f['u'][0]]])
        w = _wire(text, h / 10, r, u)
        if w is None:
            missing.append(f['body'])
            continue
        at = {f['plane'][0]: ex(f['plane'][1]), f['r'][0]: rc, f['u'][0]: ub}
        todo.append((f['body'], text, w, at))
    if not todo:
        return [], missing
    bf = comp.features.baseFeatures.add()
    bf.startEdit()
    try:
        for _, _, w, _ in todo:
            comp.bRepBodies.add(w, bf)
    finally:
        bf.finishEdit()
    bf.name = 'Part names'
    mf = comp.features.moveFeatures
    for i, (board, text, _, at) in enumerate(todo):
        b = bf.bodies.item(i)
        b.name = board + SUFFIX
        oc = adsk.core.ObjectCollection.create()
        oc.add(b)
        mi = mf.createInput2(oc)
        mi.defineAsTranslateXYZ(VI(at.get('x', '0 mm')), VI(at.get('y', '0 mm')), VI(at.get('z', '0 mm')), True)
        mf.add(mi).name = '%s%s: %s' % (board, SUFFIX, text)
    return [(t[0], t[1]) for t in todo], missing
