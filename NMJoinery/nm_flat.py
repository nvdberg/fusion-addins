# NM Joinery - "NM Lay Flat": a copy of every board laid flat for CAM, inside face up, in its own component
# (clean-room). It is a custom feature that depends on the source bodies, so it follows every size change.
# Each board: the normal of its largest flat face is its thickness direction; the face that looks toward the
# middle of its own component's boards is the inside and ends up facing +Z; the longest straight edge of that big
# face runs along X. Then either:
# - in a row: boards stacked along Y with a spacing, next to the originals (+X side), bottoms at Z = 0, or
# - nested on sheets: per thickness, the boards' outlines (+ spacing) are packed on sheets (leftover pieces first,
#   then standard or custom sheets), each sheet a translucent body of its own (use it as CAM stock: From solid).
#   Outlines are rectangles (the board's box, fingers included); grain stays along the sheet length unless turning
#   is allowed. The packer tries several orders and rules and keeps the layout with the fewest sheets.
import adsk.core, adsk.fusion, os, json, math, re, traceback

FLAT_ID = 'NMWoodworks.Flat'
CMD_ID = 'nmjLayFlat'
EDIT_ID = 'nmjLayFlatEdit'
PANEL_ID = 'SolidCreatePanel'
VI = adsk.core.ValueInput.createByString
HERE = os.path.dirname(os.path.abspath(__file__))
LAST_FILE = os.path.join(HERE, 'nm_flat_last.json')      # the dialog's last settings (not shared)
LAYOUTS = ['In a row', 'Nested on sheets']
SHEETS = [('4 x 8 ft (48 x 96 in)', '96 in', '48 in'),       # (name, length along X, width)
          ('5 x 5 ft Baltic birch (60 x 60 in)', '60 in', '60 in'),
          ('4 x 4 ft (48 x 48 in)', '48 in', '48 in'),
          ('2 x 4 ft (24 x 48 in)', '48 in', '24 in'),
          ('2440 x 1220 mm', '2440 mm', '1220 mm'),
          ('2500 x 1250 mm', '2500 mm', '1250 mm'),
          ('Custom size', None, None)]
CUSTOM = len(SHEETS) - 1
BITS = [('1/8" bit (3.2 mm)', 3.175), ('1/4" bit (6.35 mm)', 6.35), ('3/8" bit (9.5 mm)', 9.525),
        ('1/2" bit (12.7 mm)', 12.7), ('3 mm bit', 3.0), ('6 mm bit', 6.0), ('8 mm bit', 8.0), ('10 mm bit', 10.0),
        ('12 mm bit', 12.0), ('Minimum distance (type it)', None)]
BIT_FREE = len(BITS) - 1
BIT_EXTRA = 2.0                         # mm added to the bit diameter: the spacing a picked bit gives


def bit_gap(i):
    return ('%.3f' % (BITS[i][1] + BIT_EXTRA)).rstrip('0').rstrip('.') + ' mm'


DEFAULTS = {'gap': '20 mm', 'layout': 0, 'sheet': 0, 'sl': '96 in', 'sw': '48 in', 'margin': '10 mm',
            'rotate': False, 'offcuts': '', 'bit': 1}
SHEET_GAP, ROW_GAP = 10.0, 20.0         # cm between sheets / between the rows of different thicknesses
EPS = 1e-6
nm = None
definition = None


def _vec(a, b):
    return adsk.core.Vector3D.create(b.x - a.x, b.y - a.y, b.z - a.z)


def _centre(bb):
    return adsk.core.Point3D.create(*[(getattr(bb.minPoint, c) + getattr(bb.maxPoint, c)) / 2 for c in 'xyz'])


def _big_face(body):
    best = None
    for f in body.faces:
        if isinstance(f.geometry, adsk.core.Plane) and (best is None or f.area > best.area):
            best = f
    return best


def _move(tb, dx, dy, dz):
    t = adsk.core.Matrix3D.create()
    t.translation = adsk.core.Vector3D.create(dx, dy, dz)
    adsk.fusion.TemporaryBRepManager.get().transform(tb, t)


# ------------------------------------------------------------------------------------------------ nesting
def _inside(a, b):
    return a[0] >= b[0] - EPS and a[1] >= b[1] - EPS and a[0] + a[2] <= b[0] + b[2] + EPS and a[1] + a[3] <= b[1] + b[3] + EPS


class _Bin:
    """One sheet, packed with the MaxRects method (free rectangles may overlap)."""
    def __init__(self, key, L, W):
        self.key, self.L, self.W = key, L, W
        self.free = [(0.0, 0.0, L, W)]
        self.placed = []                        # (part id, x, y, turned)
        self.area = 0.0

    def find(self, w, h, turn, heur):
        best = None
        for fx, fy, fw, fh in self.free:
            for pw, ph, r in (((w, h, False), (h, w, True)) if turn else ((w, h, False),)):
                if pw <= fw + EPS and ph <= fh + EPS:
                    lw, lh = fw - pw, fh - ph
                    s = ((min(lw, lh), max(lw, lh)) if heur == 0 else     # best short side fit
                         (fw * fh - pw * ph, min(lw, lh)) if heur == 1 else   # best area fit
                         (fy + ph, fx))                                    # bottom left
                    if best is None or s < best[0]:
                        best = (s, fx, fy, pw, ph, r)
        return best

    def put(self, pid, f):
        _, x, y, w, h, r = f
        self.placed.append((pid, x, y, r))
        self.area += w * h
        out = []
        for fr in self.free:
            fx, fy, fw, fh = fr
            if x >= fx + fw - EPS or x + w <= fx + EPS or y >= fy + fh - EPS or y + h <= fy + EPS:
                out.append(fr)
                continue
            if x > fx + EPS:
                out.append((fx, fy, x - fx, fh))
            if x + w < fx + fw - EPS:
                out.append((x + w, fy, fx + fw - x - w, fh))
            if y > fy + EPS:
                out.append((fx, fy, fw, y - fy))
            if y + h < fy + fh - EPS:
                out.append((fx, y + h, fw, fy + fh - y - h))
        self.free = [a for i, a in enumerate(out)
                     if not any(j != i and _inside(a, b) and (not _inside(b, a) or j < i) for j, b in enumerate(out))]


def pack(parts, offcuts, sheet, turn):
    """parts [(id, w, h)], offcuts [(key, L, W)] (filled first), sheet (L, W) or None; all sizes include the spacing.
    Returns (the sheets that got parts, ids that fit nowhere): the best of several orders and placement rules."""
    orders = (lambda p: -p[1] * p[2], lambda p: -max(p[1], p[2]), lambda p: -(p[1] + p[2]),
              lambda p: -p[1], lambda p: -p[2], lambda p: -min(p[1], p[2]))
    best = None
    for order in orders:
        for heur in (0, 1, 2):
            bins = [_Bin(k, L, W) for k, L, W in offcuts]
            n_off, left = len(bins), []
            for pid, w, h in sorted(parts, key=order):
                for b in bins:
                    f = b.find(w, h, turn, heur)
                    if f:
                        b.put(pid, f)
                        break
                else:
                    b = _Bin('sheet', *sheet) if sheet else None
                    f = b.find(w, h, turn, heur) if b else None
                    if f:
                        b.put(pid, f)
                        bins.append(b)
                    else:
                        left.append(pid)
            new = bins[n_off:]
            score = (len(left), len(new), new[-1].area if new else 0.0)   # least on the last new sheet: a big leftover
            if best is None or score < best[0]:
                best = (score, [b for b in bins if b.placed], left)
    return best[1], best[2]


def parse_offcuts(text):
    """'600 x 900; 450 x 1200 x 18' -> [(length, width, thickness or None)] in cm, length >= width. Plain numbers are
    mm; '24 in x 30 in' works too. Raises ValueError with a readable message."""
    um = nm.design().unitsManager if nm else None
    out = []
    for piece in re.split(r'[;,\n]+', text or ''):
        piece = piece.strip()
        if not piece:
            continue
        toks = [t.strip() for t in re.split(r'\s*[xX×*]\s*', piece) if t.strip()]
        if len(toks) not in (2, 3):
            raise ValueError('Leftover "%s": write it as length x width, or length x width x thickness' % piece)
        try:
            v = [um.evaluateExpression(t, 'mm') for t in toks]
        except Exception:
            raise ValueError('Leftover "%s": could not read the sizes' % piece)
        if min(v) <= 0:
            raise ValueError('Leftover "%s": sizes must be above 0' % piece)
        L, W = max(v[:2]), min(v[:2])
        out.append((L, W, v[2] if len(v) == 3 else None))
    return out


def _mm(cm):
    return ('%.1f' % (cm * 10)).rstrip('0').rstrip('.')


def arrange(flats, o, x0, y0):
    """Nests the flat copies (moved in place) on sheets, per thickness. Returns ([(name, sheet body)], notes)."""
    tbm = adsk.fusion.TemporaryBRepManager.get()
    Z = adsk.core.Vector3D.create(0, 0, 1)
    gap, m, SL, SW = o['gap'], o['margin'], o['sl'], o['sw']
    groups = {}
    for i, tb in enumerate(flats):
        bb = tb.boundingBox
        t = bb.maxPoint.z - bb.minPoint.z
        groups.setdefault(round(t * 10, 1), []).append((i, bb.maxPoint.x - bb.minPoint.x, bb.maxPoint.y - bb.minPoint.y))
    pool = [[L, W, T, False] for L, W, T in o['offcuts']]
    usable = lambda L, W: (L - 2 * m + gap, W - 2 * m + gap)
    sheet = usable(SL, SW) if SL > 2 * m and SW > 2 * m else None
    sheets, notes, y = [], [], y0
    for tmm in sorted(groups, reverse=True):
        t = tmm / 10
        parts = [(i, w + gap, h + gap) for i, w, h in groups[tmm]]
        offs = [(k,) + usable(c[0], c[1]) for k, c in enumerate(pool)
                if not c[3] and (c[2] is None or abs(c[2] - t) < 0.03) and c[0] > 2 * m and c[1] > 2 * m]
        bins, left = pack(parts, offs, sheet, o['rotate'])
        x, rowh, n_full, n_off, used, total = x0, 0.0, 0, 0, 0.0, 0.0
        for b in bins:
            if b.key == 'sheet':
                L, W = SL, SW
                n_full += 1
                name = 'Sheet %d - %s mm' % (n_full, _mm(t))
            else:
                L, W = pool[b.key][0], pool[b.key][1]
                pool[b.key][3] = True
                n_off += 1
                name = 'Leftover %s x %s - %s mm' % (_mm(L), _mm(W), _mm(t))
            for pid, px, py, r in b.placed:
                tb = flats[pid]
                if r:
                    rot = adsk.core.Matrix3D.create()
                    rot.setToRotation(math.pi / 2, Z, adsk.core.Point3D.create(0, 0, 0))
                    tbm.transform(tb, rot)
                bb = tb.boundingBox
                used += (bb.maxPoint.x - bb.minPoint.x) * (bb.maxPoint.y - bb.minPoint.y)
                _move(tb, x + m + px - bb.minPoint.x, y + m + py - bb.minPoint.y, -bb.minPoint.z)
            box = adsk.core.OrientedBoundingBox3D.create(adsk.core.Point3D.create(x + L / 2, y + W / 2, t / 2),
                                                         adsk.core.Vector3D.create(1, 0, 0),
                                                         adsk.core.Vector3D.create(0, 1, 0), L, W, t)
            sheets.append((name, tbm.createBox(box)))
            total += L * W
            x += L + SHEET_GAP
            rowh = max(rowh, W)
        cur = y
        for pid in left:                        # too big for any sheet: in a row after the sheets
            tb = flats[pid]
            bb = tb.boundingBox
            _move(tb, x - bb.minPoint.x, cur - bb.minPoint.y, -bb.minPoint.z)
            cur += bb.maxPoint.y - bb.minPoint.y + gap
        rowh = max(rowh, cur - y)
        what = ', '.join(s for s in ('%d sheet%s' % (n_full, '' if n_full == 1 else 's') if n_full else '',
                                     '%d leftover%s' % (n_off, '' if n_off == 1 else 's') if n_off else '') if s)
        notes.append('%s mm: %d board%s on %s%s%s' % (
            _mm(t), len(parts), '' if len(parts) == 1 else 's', what or 'no sheet',
            ', %d %% used' % round(100 * used / total) if total else '',
            '; %d too big for the sheet (next to it)' % len(left) if left else ''))
        y += rowh + ROW_GAP
    return sheets, notes


# ------------------------------------------------------------------------------------------------ laying flat
def lay(bodies, gap, dx=0.0, nest=None):
    """Flat copies (TemporaryBRep bodies, world coordinates) of the bodies, in the same order, plus the sheets
    ([(name, body)]) and notes when nested."""
    tbm = adsk.fusion.TemporaryBRepManager.get()
    union, per = None, {}
    for b in bodies:
        k = b.assemblyContext.fullPathName if b.assemblyContext else ''
        for key in ('*', k):
            if key not in per:
                per[key] = [b.boundingBox.copy(), 0]
            else:
                per[key][0].combine(b.boundingBox)
            per[key][1] += 1
    union = per['*'][0]
    Z = adsk.core.Vector3D.create(0, 0, 1)
    X = adsk.core.Vector3D.create(1, 0, 0)
    origin = adsk.core.Point3D.create(0, 0, 0)
    x0, cursor = union.maxPoint.x + 10.0 + dx, union.minPoint.y      # dx: shift sideways (bank of drawers)
    out = []
    for b in bodies:
        k = b.assemblyContext.fullPathName if b.assemblyContext else ''
        tb = tbm.copy(b)
        face = _big_face(b)
        if face is not None:
            n = face.geometry.normal.copy()
            n.normalize()
            # inside = toward the middle of its own component's boards (a drawer picked with its cabinet), or of
            # all boards when that middle lies in the board's own plane (two doors side by side)
            to = _vec(_centre(b.boundingBox), _centre(union)).dotProduct(n)
            if per[k][1] > 1:
                own = _vec(_centre(b.boundingBox), _centre(per[k][0])).dotProduct(n)
                if abs(own) > 0.05:
                    to = own
            if to < -1e-6:
                n.scaleBy(-1)                       # point it at the middle of the box: that is the inside
            m = adsk.core.Matrix3D.create()
            if n.dotProduct(Z) < -0.999999:
                m.setToRotation(math.pi, X, origin)
            elif n.dotProduct(Z) < 0.999999:
                m.setToRotateTo(n, Z)
            tbm.transform(tb, m)
            pts = []                                  # turn about Z: smallest outline, long side along X
            for v in b.vertices:
                q = v.geometry.copy()
                q.transformBy(m)
                pts.append((q.x, q.y))
            best = None
            for e in face.edges:
                if not isinstance(e.geometry, adsk.core.Line3D):
                    continue
                d = _vec(e.startVertex.geometry, e.endVertex.geometry)
                d.transformBy(m)
                ang = math.atan2(d.y, d.x)
                c, s_ = math.cos(-ang), math.sin(-ang)
                xs = [c * x - s_ * y for x, y in pts]
                ys = [s_ * x + c * y for x, y in pts]
                ex, ey = max(xs) - min(xs), max(ys) - min(ys)
                if ey > ex + 1e-6:
                    ang += math.pi / 2
                    ex, ey = ey, ex
                if best is None or ex * ey < best[0] - 1e-6:
                    best = (ex * ey, ang)
            if best:
                r = adsk.core.Matrix3D.create()
                r.setToRotation(-best[1], Z, origin)
                tbm.transform(tb, r)
        bb = tb.boundingBox
        _move(tb, x0 - bb.minPoint.x, cursor - bb.minPoint.y, -bb.minPoint.z)
        cursor += bb.maxPoint.y - bb.minPoint.y + gap
        out.append(tb)
    if nest:
        sheets, notes = arrange(out, nest, x0, union.minPoint.y)
        return out, sheets, notes
    return out, [], []


def sources(cf):
    deps = sorted((d for d in cf.dependencies if d.id.startswith('b')), key=lambda d: int(d.id[1:]))
    return [d.entity for d in deps]


MAX_WATCH = 64


def roots(des, names):
    """Parameters that are only expressions of other parameters (d12 = drawer_w - 2 * drawer_t) are replaced by the
    parameters they come from, down to the ones holding a value: far fewer to watch, and a change still reaches us."""
    allp = des.allParameters
    out, seen = [], set()

    def walk(p, depth):
        if p is None or p.name in seen:
            return
        seen.add(p.name)
        try:
            deps = list(p.dependencyParameters) if depth < 30 else []
        except Exception:
            deps = []
        if not deps:
            out.append((p.name, p.unit))
        for q in deps:
            walk(q, depth + 1)
    for n, u in names:
        p = allp.itemByName(n)
        if p is None:
            if n not in seen:
                seen.add(n)
                out.append((n, u))
        else:
            walk(p, 0)
    return out


def watch(cfi, bodies):
    """Fusion does not recompute us when a body we depend on changes, only for changed sketches and our own
    parameters. So: the boards' sketches become dependencies, and every parameter that shapes a board (the ones
    of the features that made it, and the NM Joint / NM Box settings that cut it) gets a hidden watch parameter."""
    des = nm.design()
    seen_sk, names, ns = set(), [], 0
    for bi, body in enumerate(bodies):
        ctx = body.assemblyContext
        try:
            sketches, params = nm.upstream(body)
        except Exception as e:
            nm.log('flat: upstream of %s failed: %s' % (body.name, e))
            sketches, params = [], []
        for sk in sketches:
            if sk.entityToken in seen_sk:
                continue
            seen_sk.add(sk.entityToken)
            try:
                if cfi.addDependency('sk%d' % ns, sk.createForAssemblyContext(ctx) if ctx and not sk.assemblyContext else sk):
                    ns += 1
            except Exception as e:
                nm.log('flat: sketch dependency %s skipped: %s' % (sk.name, e))
        names += [(p.name, p.unit) for p in params]
        native = body.nativeObject if ctx else body
        for cf in native.parentComponent.features.customFeatures:     # NM Joint / NM Box that cut this board
            try:
                if cf.definition.id != nm.FEAT_ID:
                    continue
                toks = json.loads(cf.customNamedValues.value('boards'))
                if native.entityToken not in toks and not any(nm.same_body(native, t) for t in toks):
                    continue
            except Exception:
                continue
            names += [(cf.parameters.item(i).name, cf.parameters.item(i).unit) for i in range(cf.parameters.count)]
    names = roots(des, names)
    nw, done = 0, set()
    for n, u in names:
        if n in done or not n:
            continue
        done.add(n)
        if nw >= MAX_WATCH:
            nm.log('flat: more than %d parameters to watch, %s not watched' % (MAX_WATCH, n))
            break
        try:
            cfi.addCustomParameter('w%d' % nw, 'watch %s' % n, VI(n), u, False)
            nw += 1
        except Exception as e:
            nm.log('flat: watch %s skipped: %s' % (n, e))
    return nw


def nest_options(cf):
    """The nesting settings of a flat feature, None = in a row (also every flat made before 0.8.0)."""
    try:
        o = json.loads(cf.customNamedValues.value('nest'))
    except Exception:
        return None
    if not o.get('layout'):
        return None
    P = lambda k: nm.fparam(cf, k)
    return {'gap': P('gap').value, 'margin': P('margin').value, 'sl': P('sl').value, 'sw': P('sw').value,
            'rotate': bool(o.get('rotate')), 'offcuts': parse_offcuts(o.get('offcuts', ''))}


def _style_sheets(bodies):
    for b in bodies:
        try:
            b.opacity = 0.25                    # see the boards through the sheet
        except Exception:
            pass


def _store_notes(cf, notes):
    cf.customNamedValues.addOrSetValue('notes', json.dumps(notes))
    for n in notes:
        nm.log('  ' + n)


def make_flat(bodies, name, gap='20 mm', dx=None, o=None):
    """bodies: BRepBodies (proxies in the root context when they live in a component). o: the dialog settings
    (layout, sheet, ...); None = in a row with this gap."""
    o = dict(DEFAULTS, **(o or {'gap': gap}))
    des = nm.design()
    um = des.unitsManager
    root = des.rootComponent
    occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    comp = occ.component
    comp.name = 'Flat ' + name
    feats = comp.features
    cfi = feats.customFeatures.createInput(definition)
    cfi.addCustomParameter('gap', 'Spacing', VI(o['gap']), 'mm', True)
    if dx:
        cfi.addCustomParameter('dx', 'Shift sideways', VI(dx), 'mm', True)
    cfi.addCustomParameter('margin', 'Sheet edge margin', VI(o['margin']), 'mm', True)
    cfi.addCustomParameter('sl', 'Sheet length', VI(o['sl']), 'mm', True)
    cfi.addCustomParameter('sw', 'Sheet width', VI(o['sw']), 'mm', True)
    cfi.addCustomParameter('rev', 'settings changed', VI('0'), '', False)   # bumped by the edit: recompute
    for i, b in enumerate(bodies):
        if not cfi.addDependency('b%d' % i, b):
            raise RuntimeError('could not follow body %s' % b.name)
    nw = watch(cfi, bodies)
    ev = lambda e: um.evaluateExpression(e, 'mm')
    nest = None
    if o['layout']:
        nest = {'gap': ev(o['gap']), 'margin': ev(o['margin']), 'sl': ev(o['sl']), 'sw': ev(o['sw']),
                'rotate': bool(o['rotate']), 'offcuts': parse_offcuts(o['offcuts'])}
    flats, sheets, notes = lay(bodies, ev(o['gap']), ev(dx) if dx else 0.0, nest)
    bf = feats.baseFeatures.add()
    bf.startEdit()
    for tb in flats:
        comp.bRepBodies.add(tb, bf)
    for _, tb in sheets:
        comp.bRepBodies.add(tb, bf)
    bf.finishEdit()
    bf.name = 'Flat boards'
    for i, b in enumerate(bodies):
        bf.bodies.item(i).name = b.name
    for j, (sn, _) in enumerate(sheets):
        bf.bodies.item(len(bodies) + j).name = sn
    _style_sheets([bf.bodies.item(len(bodies) + j) for j in range(len(sheets))])
    cfi.setStartAndEndFeatures(bf, bf)
    cf = feats.customFeatures.add(cfi)
    cf.name = 'NM Flat ' + name
    cv = cf.customNamedValues
    cv.addOrSetValue('names', json.dumps([b.name for b in bodies]))
    cv.addOrSetValue('nest', json.dumps({k: o[k] for k in ('layout', 'sheet', 'rotate', 'offcuts', 'bit')}))
    nm.log('flat %s: %d boards, %d watched parameters%s' % (name, len(bodies), nw, ', nested' if nest else ''))
    _store_notes(cf, notes)
    return occ


class Compute(adsk.fusion.CustomFeatureEventHandler):
    def notify(self, args):
        try:
            args = adsk.fusion.CustomFeatureEventArgs.cast(args)
            cf = args.customFeature
            st = args.computeStatus.statusMessages
            bodies = sources(cf)
            if any(b is None for b in bodies):
                st.addWarning('NMF_LOST', 'A board this flat copy follows is gone; its copy is kept as it was.')
                return
            if nm.fparam(cf, 'rev') is not None:
                try:
                    stored = cf.customNamedValues.value('nest')
                except Exception:
                    stored = ''
                if not stored:
                    return                          # being added: its settings are stored right after
            bf = next(adsk.fusion.BaseFeature.cast(f) for f in cf.features if adsk.fusion.BaseFeature.cast(f))
            sh = nm.fparam(cf, 'dx')        # only on bank flats (itemById raises when missing)
            flats, sheets, notes = lay(bodies, cf.parameters.itemById('gap').value, sh.value if sh else 0.0,
                                       nest_options(cf))
            n = len(flats)
            bf.startEdit()
            try:
                olds = [bf.bodies.item(i) for i in range(bf.bodies.count)]
                if len(olds) < n:
                    nm.log('flat compute %s: %d copies for %d boards, skipped' % (cf.name, len(olds), n))
                    return                           # first compute while the feature is being added
                for old, tb in zip(olds, flats):
                    bf.updateBody(old, tb)
                olds = olds[n:]                      # the sheets: as many as the nesting needs now
                new = []
                for j, (sn, tb) in enumerate(sheets):
                    if j < len(olds):
                        bf.updateBody(olds[j], tb)
                        new.append(olds[j])
                    else:
                        new.append(cf.parentComponent.bRepBodies.add(tb, bf))
                for old in olds[len(sheets):]:
                    old.deleteMe()
            finally:
                bf.finishEdit()
            for b, (sn, _) in zip(new, sheets):
                try:
                    if b and b.isValid and b.name != sn:
                        b.name = sn
                except Exception:
                    pass
            _style_sheets([b for b in new if b])
            try:
                had = json.loads(cf.customNamedValues.value('notes') or '[]')
            except Exception:
                had = None
            if notes != had:                    # also clears the sheet notes after a switch back to "In a row"
                _store_notes(cf, notes)
            nm.log('compute %s: %d boards%s' % (cf.name, n, ', %d sheets' % len(sheets) if sheets else ''))
        except Exception:
            nm.log('flat compute failed:\n' + traceback.format_exc())
            try:
                args.computeStatus.statusMessages.addError('NMF_ERR', traceback.format_exc().strip().splitlines()[-1])
            except Exception:
                pass


# ----------------------------------------------------------------------------------------------- dialog
def load_last():
    try:
        with open(LAST_FILE) as f:
            return dict(DEFAULTS, **json.load(f))
    except Exception:
        return dict(DEFAULTS)


def save_last(o):
    try:
        with open(LAST_FILE, 'w') as f:
            json.dump(o, f)
    except Exception:
        pass


TIPS = {
    'layout': 'In a row: the boards one after the other, next to the model.\n'
              'Nested on sheets: packed on sheets per thickness (leftovers first), each sheet a see-through body '
              'you can use as CAM stock (Setup > Stock > From solid).',
    'gap': 'Space between the boards. Nested: set by the bit (its diameter + %g mm); type a value for your own '
           'minimum distance.' % BIT_EXTRA,
    'bit': 'The bit that cuts the boards out: the spacing becomes its diameter + %g mm, so it fits between '
           'neighbours. Minimum distance: type the spacing yourself.' % BIT_EXTRA,
    'sheet': 'Sheet size. Length runs along X; the boards keep their long side (the grain) along it.',
    'sl': 'Sheet length (along the grain).', 'sw': 'Sheet width.',
    'margin': 'Kept free along every sheet edge (rough or out-of-square edges, clamps).',
    'rotate': 'Allow turning boards 90 degrees on the sheet. Fits more, but the grain then runs across those boards.',
    'offcuts': 'Leftover pieces you have, used before new sheets: length x width, or length x width x thickness, '
               'separated by ; (e.g. 600 x 900; 450 x 1200 x 18). Plain numbers are mm; 24 in x 30 in works too. '
               'Without a thickness a piece can take boards of any thickness (once).',
}


def add_inputs(inputs, o, pick=True):
    if pick:
        s = inputs.addSelectionInput('bodies', 'Boards', 'Pick the boards (or whole components) to lay flat')
        s.addSelectionFilter('Bodies')
        s.addSelectionFilter('Occurrences')
        s.setSelectionLimits(1, 0)
        s.tooltip = 'Pick boards, or components (a cabinet, a drawer) for all their visible boards.'
    dd = inputs.addDropDownCommandInput('layout', 'Layout', adsk.core.DropDownStyles.TextListDropDownStyle)
    for i, x in enumerate(LAYOUTS):
        dd.listItems.add(x, i == int(o['layout']))
    dd = inputs.addDropDownCommandInput('bit', 'Bit', adsk.core.DropDownStyles.TextListDropDownStyle)
    for i, x in enumerate(BITS):
        dd.listItems.add(x[0], i == int(o.get('bit', 1)))
    inputs.addValueInput('gap', 'Spacing', 'mm', VI(o['gap']))
    dd = inputs.addDropDownCommandInput('sheet', 'Sheet', adsk.core.DropDownStyles.TextListDropDownStyle)
    for i, x in enumerate(SHEETS):
        dd.listItems.add(x[0], i == int(o['sheet']))
    inputs.addValueInput('sl', 'Sheet length', 'mm', VI(o['sl']))
    inputs.addValueInput('sw', 'Sheet width', 'mm', VI(o['sw']))
    inputs.addValueInput('margin', 'Edge margin', 'mm', VI(o['margin']))
    inputs.addBoolValueInput('rotate', 'Turn boards 90°', True, '', bool(o['rotate']))
    inputs.addStringValueInput('offcuts', 'Leftovers first', o['offcuts'])
    for k, tip in TIPS.items():
        it = inputs.itemById(k)
        if it:
            it.tooltip = tip
    show(inputs)


def show(inputs):
    nest = inputs.itemById('layout').selectedItem.index == 1
    custom = inputs.itemById('sheet').selectedItem.index == CUSTOM
    for k in ('bit', 'sheet', 'margin', 'rotate', 'offcuts'):
        inputs.itemById(k).isVisible = nest
    for k in ('sl', 'sw'):
        inputs.itemById(k).isVisible = nest and custom


def read(inputs):
    it = inputs.itemById
    return {'gap': it('gap').expression, 'layout': it('layout').selectedItem.index,
            'sheet': it('sheet').selectedItem.index, 'sl': it('sl').expression, 'sw': it('sw').expression,
            'margin': it('margin').expression, 'rotate': it('rotate').value, 'offcuts': it('offcuts').value.strip(),
            'bit': it('bit').selectedItem.index}


def picked_bodies(entities):
    """Bodies (root-context proxies) of the picked boards and components; hidden boards and flat copies left out."""
    root = nm.design().rootComponent
    out, seen = [], set()
    flat = lambda path: any(p.startswith('Flat ') for p in path.split('+'))
    occs = [o for o in root.allOccurrences if o.isVisible and not flat(o.fullPathName)]
    for e in entities:
        if isinstance(e, adsk.fusion.BRepBody):
            k = (e.assemblyContext.fullPathName if e.assemblyContext else '', e.name)
            if k not in seen:
                seen.add(k)
                out.append(e)
        elif isinstance(e, adsk.fusion.Occurrence):
            for o in occs:
                if o.fullPathName == e.fullPathName or o.fullPathName.startswith(e.fullPathName + '+'):
                    for b in o.component.bRepBodies:
                        p = b.createForAssemblyContext(o)
                        k = (o.fullPathName, b.name)
                        if p.isVisible and k not in seen:
                            seen.add(k)
                            out.append(p)
    return out


def problems(o):
    um = nm.design().unitsManager
    ev = lambda e: um.evaluateExpression(e, 'mm')
    bad = []
    try:
        if ev(o['gap']) < 0:
            bad.append('Spacing cannot be below 0.')
        if o['layout']:
            if ev(o['margin']) < 0:
                bad.append('Edge margin cannot be below 0.')
            if min(ev(o['sl']), ev(o['sw'])) <= 2 * ev(o['margin']):
                bad.append('The sheet is smaller than its edge margins.')
            parse_offcuts(o['offcuts'])
    except ValueError as e:
        bad.append(str(e))
    except Exception:
        bad.append('A size could not be read.')
    return bad


class Changed(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        try:
            inputs = args.input.parentCommand.commandInputs
            iid = args.input.id
            g, bit = inputs.itemById('gap'), inputs.itemById('bit')
            b = bit.selectedItem.index
            if iid == 'layout':                  # the bit's spacing when nesting / back to the row spacing
                nest = args.input.selectedItem.index == 1
                if nest and b != BIT_FREE and g.expression == DEFAULTS['gap']:
                    g.expression = bit_gap(b)
                elif not nest and b != BIT_FREE and g.expression == bit_gap(b):
                    g.expression = DEFAULTS['gap']
            if iid == 'bit' and b != BIT_FREE:
                g.expression = bit_gap(b)
            if iid == 'gap' and b != BIT_FREE and g.expression != bit_gap(b) and inputs.itemById('layout').selectedItem.index == 1:
                bit.listItems.item(BIT_FREE).isSelected = True       # typed its own distance
            if iid == 'sheet':
                i = args.input.selectedItem.index
                if i != CUSTOM:
                    inputs.itemById('sl').expression = SHEETS[i][1]
                    inputs.itemById('sw').expression = SHEETS[i][2]
            show(inputs)
        except Exception:
            nm.log('lay flat dialog:\n' + traceback.format_exc())


class Validate(adsk.core.ValidateInputsEventHandler):
    def notify(self, args):
        try:
            inputs = args.inputs
            if inputs.itemById('layout') is None:
                return
            args.areInputsValid = not problems(read(inputs))
        except Exception:
            pass


# ----------------------------------------------------------------------------------------------- commands
class MakeCreated(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = args.command
            cmd.isExecutedWhenPreEmpted = False      # starting another command = Cancel, not OK (an auto-OK mid-build crashed Fusion)
            cmd.setDialogInitialSize(380, 420)
            add_inputs(cmd.commandInputs, load_last())
            for ev, h in ((cmd.execute, MakeExecute()), (cmd.inputChanged, Changed()), (cmd.validateInputs, Validate())):
                ev.add(h)
                nm.handlers.append(h)
        except Exception:
            nm.ui.messageBox('NM Lay Flat failed:\n' + traceback.format_exc())


class MakeExecute(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            inputs = args.command.commandInputs
            o = read(inputs)
            bad = problems(o)
            if bad:
                nm.ui.messageBox('\n'.join(bad), 'NM Lay Flat')
                return
            save_last(o)
            sel = inputs.itemById('bodies')
            bodies = picked_bodies([sel.selection(i).entity for i in range(sel.selectionCount)])
            if not bodies:
                nm.ui.messageBox('No visible boards in what was picked.', 'NM Lay Flat')
                return
            name = bodies[0].assemblyContext.component.name if bodies[0].assemblyContext else bodies[0].parentComponent.name
            make_flat(bodies, name, o=o)
        except Exception:
            nm.log('lay flat failed:\n' + traceback.format_exc())
            nm.ui.messageBox('NM Lay Flat failed:\n' + traceback.format_exc())


class EditCreated(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cf = adsk.fusion.CustomFeature.cast(nm.ui.activeSelections.item(0).entity)
            cmd = args.command
            cmd.isExecutedWhenPreEmpted = False      # starting another command = Cancel, not OK (an auto-OK mid-build crashed Fusion)
            inputs = cmd.commandInputs
            if nm.fparam(cf, 'rev') is None:     # made before 0.8.0: spacing only
                inputs.addValueInput('gap', 'Spacing', 'mm', VI(cf.parameters.itemById('gap').expression))
                inputs.addTextBoxCommandInput('note', '', 'Made with an older version: only the spacing can be '
                                              'changed here. Make a new Lay Flat to nest it on sheets.', 3, True)
            else:
                try:
                    o = json.loads(cf.customNamedValues.value('nest'))
                except Exception:
                    o = {}
                o = dict(DEFAULTS, **o)
                for k in ('gap', 'margin', 'sl', 'sw'):
                    o[k] = cf.parameters.itemById(k).expression
                cmd.setDialogInitialSize(380, 420)
                add_inputs(inputs, o, pick=False)
                try:
                    notes = json.loads(cf.customNamedValues.value('notes'))
                except Exception:
                    notes = []
                if notes:
                    inputs.addTextBoxCommandInput('note', 'Now', '<br>'.join(notes), max(2, len(notes) + 1), True)
                for ev, h in ((cmd.inputChanged, Changed()), (cmd.validateInputs, Validate())):
                    ev.add(h)
                    nm.handlers.append(h)
            h = EditExecute(cf)
            cmd.execute.add(h)
            nm.handlers.append(h)
        except Exception:
            nm.ui.messageBox('NM Lay Flat edit failed:\n' + traceback.format_exc())


class EditExecute(adsk.core.CommandEventHandler):
    def __init__(self, cf):
        super().__init__()
        self.cf = cf

    def notify(self, args):
        try:
            inputs = args.command.commandInputs
            cf = self.cf
            if inputs.itemById('layout') is None:
                cf.parameters.itemById('gap').expression = inputs.itemById('gap').expression
                return
            o = read(inputs)
            bad = problems(o)
            if bad:
                nm.ui.messageBox('\n'.join(bad), 'NM Lay Flat')
                return
            cf.customNamedValues.addOrSetValue('nest', json.dumps({k: o[k] for k in ('layout', 'sheet', 'rotate', 'offcuts', 'bit')}))
            for k in ('gap', 'margin', 'sl', 'sw'):
                p = cf.parameters.itemById(k)
                if p.expression != o[k]:
                    p.expression = o[k]
            rev = cf.parameters.itemById('rev')
            rev.expression = str(int(round(rev.value)) + 1)      # always recompute (layout, turning, leftovers)
            nm.log('edit flat %s: %s' % (cf.name, LAYOUTS[int(o['layout'])]))
        except Exception:
            nm.log('lay flat edit failed:\n' + traceback.format_exc())
            nm.ui.messageBox('NM Lay Flat edit failed:\n' + traceback.format_exc())


def register(mod):
    global nm, definition
    nm = mod
    unregister(mod)                             # a button left on a deleted definition would be dead
    defs = nm.ui.commandDefinitions
    c = defs.addButtonDefinition(CMD_ID, 'NM Lay Flat',
                                 'A copy of the picked boards laid flat (inside face up, longest edge along X) in a new '
                                 'component, for CAM: in a row, or nested on sheets (leftover pieces first). '
                                 'It follows size changes of the boards.',
                                 os.path.join(HERE, 'resources', 'create'))
    h = MakeCreated()
    c.commandCreated.add(h)
    nm.handlers.append(h)
    e = defs.addButtonDefinition(EDIT_ID, 'Edit NM Lay Flat', '', os.path.join(HERE, 'resources', 'edit'))
    h = EditCreated()
    e.commandCreated.add(h)
    nm.handlers.append(h)
    definition = adsk.fusion.CustomFeatureDefinition.create(FLAT_ID, 'NM Lay Flat', os.path.join(HERE, 'resources', 'joint'))
    definition.editCommandId = EDIT_ID
    h = Compute()
    definition.customFeatureCompute.add(h)
    nm.handlers.append(h)
    panel = nm.ui.allToolbarPanels.itemById(PANEL_ID)
    if panel:
        panel.controls.addCommand(c, 'nmjDrawer', True) if panel.controls.itemById('nmjDrawer') else panel.controls.addCommand(c)


def unregister(mod):
    ui = mod.ui
    panel = ui.allToolbarPanels.itemById(PANEL_ID)
    if panel and panel.controls.itemById(CMD_ID):
        panel.controls.itemById(CMD_ID).deleteMe()
    for cid in (CMD_ID, EDIT_ID):
        d = ui.commandDefinitions.itemById(cid)
        if d:
            d.deleteMe()
