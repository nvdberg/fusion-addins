# NM Joinery - joint geometry (clean-room, written from scratch).
#
# Two boards in, cut/join tool bodies out (temporary B-rep, same coordinate space as the boards).
#   corner mode : the boards OVERLAP (modelled full size, like Autodesk's fingerjointBox sample).
#                 The overlap block is split along the joint line; segments alternate between the boards.
#   butt mode   : board B's end face TOUCHES board A. Tabs grow out of that face into A (through or blind),
#                 A gets matching slots / mortises.  (= tab & slot, mortise & tenon)
# CNC aware: each board's bit axis = normal of its largest flat face. A cut corner gets a dogbone only when
# both walls meeting there are real material walls (an open side never needs one).
# All lengths are cm (Fusion internal units).
import adsk.core, adsk.fusion, math

P3 = adsk.core.Point3D
V3 = adsk.core.Vector3D
EPS = 0.001     # 0.01 mm: tabs reach this far back into B so the join is clean
OVER = 0.1      # 1 mm: cut tools run past open faces by this much
PROBE = 0.02    # 0.2 mm: probe step for "is there material beyond this wall?"

RELIEF_NONE, RELIEF_DOGBONE, RELIEF_ROUND, RELIEF_TB_SIDE, RELIEF_TB_DEEP = 0, 1, 2, 3, 4
BONES = (RELIEF_DOGBONE, RELIEF_TB_SIDE, RELIEF_TB_DEEP)   # reliefs made with dogbones()
STYLE_AUTO, STYLE_MT = 0, 1
SPACE_AUTO, SPACE_EVEN, SPACE_FIXED = 0, 1, 2   # M&T gaps between tenons: half a tenon / one tenon / mt_gap

# mortise & tenon rules of thumb (cm)
MT_MAX_TENON = 12.5     # wider than this -> split into more tenons (wood movement, glue starvation)
MT_MIN_CHEEK = 0.15     # keep at least 1.5 mm of B on each side of the tenon
MT_MIN_BOTTOM = 0.3     # warn when less than 3 mm of A is left behind a blind mortise


class JointError(Exception):
    pass


def _dot(a, b):
    return a.x * b.x + a.y * b.y + a.z * b.z


def _sub(p, q):
    return V3.create(p.x - q.x, p.y - q.y, p.z - q.z)


def _unit(v):
    v = v.copy(); v.normalize(); return v


def _tbm():
    return adsk.fusion.TemporaryBRepManager.get()


def inside(body, p):
    return body.pointContainment(p) == adsk.fusion.PointContainment.PointInsidePointContainment


def thin_normal(body):
    """Normal of the largest flat face = the axis a flat panel is cut along on the CNC."""
    best = None
    for f in body.faces:
        if f.geometry.surfaceType == adsk.core.SurfaceTypes.PlaneSurfaceType:
            a = f.area
            if best is None or a > best[0] + 1e-9:
                best = (a, f.geometry.normal)
    if best is None:
        raise JointError('%s has no flat faces.' % body.name)
    return _unit(best[1])


def face_normal(face):
    ok, n = face.evaluator.getNormalAtPoint(face.pointOnFace)
    return _unit(n)


class Frame:
    """Orthonormal frame: axis 0 = joint line, axes 1/2 across it. Right handed (e0 x e1 = e2)."""

    def __init__(self, o, e0, e1):
        self.o = o
        self.e = [_unit(e0), _unit(e1)]
        self.e.append(self.e[0].crossProduct(self.e[1]))
        self.e[2].normalize()

    def pt(self, c):
        o, e = self.o, self.e
        return P3.create(o.x + c[0] * e[0].x + c[1] * e[1].x + c[2] * e[2].x,
                         o.y + c[0] * e[0].y + c[1] * e[1].y + c[2] * e[2].y,
                         o.z + c[0] * e[0].z + c[1] * e[1].z + c[2] * e[2].z)

    def co(self, p):
        d = _sub(p, self.o)
        return [_dot(d, self.e[0]), _dot(d, self.e[1]), _dot(d, self.e[2])]

    def axis_of(self, v):
        return max(range(3), key=lambda k: abs(_dot(v, self.e[k])))

    def extents(self, body):
        cs = [self.co(vt.geometry) for vt in body.vertices]
        if not cs:
            raise JointError('Empty body.')
        return [(min(c[k] for c in cs), max(c[k] for c in cs)) for k in range(3)]

    def box(self, r):
        c = self.pt([(r[k][0] + r[k][1]) / 2 for k in range(3)])
        obb = adsk.core.OrientedBoundingBox3D.create(c, self.e[0], self.e[1], r[0][1] - r[0][0],
                                                     r[1][1] - r[1][0], r[2][1] - r[2][0])
        return _tbm().createBox(obb)

    def cyl(self, axis, a, b, centre, radius):
        def p(t):
            c = list(centre); c[axis] = t
            return self.pt(c)
        return _tbm().createCylinderOrCone(p(a), radius, p(b), radius)


def union(bodies):
    bodies = [b for b in bodies if b]
    if not bodies:
        return None
    acc = bodies[0]
    for b in bodies[1:]:
        _tbm().booleanOperation(acc, b, adsk.fusion.BooleanTypes.UnionBooleanType)
    return acc


def subtract(target, tool):
    _tbm().booleanOperation(target, tool, adsk.fusion.BooleanTypes.DifferenceBooleanType)
    return target


def intersect_copy(a, b):
    t = _tbm().copy(a)
    ok = _tbm().booleanOperation(t, _tbm().copy(b), adsk.fusion.BooleanTypes.IntersectionBooleanType)
    return t if ok and t.volume > 1e-6 else None


def contact_face(x, y):
    """Smallest flat face of x whose outside touches y (x's end face butting against y)."""
    best = None
    for f in x.faces:
        if f.geometry.surfaceType != adsk.core.SurfaceTypes.PlaneSurfaceType:
            continue
        n = face_normal(f)
        p = f.pointOnFace
        q = P3.create(p.x + n.x * PROBE, p.y + n.y * PROBE, p.z + n.z * PROBE)
        if inside(y, q) and not inside(x, q):
            if best is None or f.area < best.area:
                best = f
    return best


def _face_frame(face):
    n = face_normal(face)
    best = None
    for e in face.edges:
        if e.geometry.curveType == adsk.core.Curve3DTypes.Line3DCurveType:
            d = _sub(e.endVertex.geometry, e.startVertex.geometry)
            if best is None or d.length > best.length:
                best = d
    if best is None:
        raise JointError('Butt face needs a straight edge.')
    u = V3.create(best.x - _dot(best, n) * n.x, best.y - _dot(best, n) * n.y, best.z - _dot(best, n) * n.z)
    v = n.crossProduct(u)          # u x v = n  -> frame axis 2 points from B into A
    return Frame(face.pointOnFace, u, v)


# ----------------------------------------------------------------------------------------------- layout
def _half_up(x):
    """Round .5 up, also when float noise makes it 1.4999999: 4" boards and 1/2" stock hit such ties exactly, and
    Python's round() (and the noise) then gave different counts for the front and back of the same drawer."""
    return int(math.floor(x + 0.5 + 1e-6))


def layout(lo, hi, mode, s):
    """Segments (s0, s1, owner) along the joint line. owner 'A' or 'B' (B = tabs in butt mode)."""
    L = hi - lo
    flip = bool(s['flip'])
    if mode == 'corner':
        n = int(s['count'])
        if n < 1:
            tw = s['finger_w'] if s['finger_w'] > 0 else s['auto_w']
            n = max(3, 2 * int(L / tw / 2 + 1e-6) + 1)          # odd count -> both ends belong to the same board
        w = L / n
        return [(lo + i * w, lo + (i + 1) * w, 'A' if (i % 2 == 0) != flip else 'B') for i in range(n)]
    # butt mode: tabs (owner B) on the face
    a0, a1 = lo + s['end_off'], hi - s['end_off']
    if a1 - a0 <= 0:
        raise JointError('End offset leaves no room for tabs.')
    k = int(s['count'])
    if s['tab_len'] > 0:                                   # fixed tab length, spread evenly (mortise & tenon)
        if k < 1:
            k = 1
        tl = s['tab_len']
        if tl * k > a1 - a0 + 1e-6:
            raise JointError('%d tabs of %.1f mm do not fit in %.1f mm.' % (k, tl * 10, (a1 - a0) * 10))
        if k == 1:
            c = (a0 + a1) / 2
            tabs = [(c - tl / 2, c + tl / 2)]
        else:
            pitch = (a1 - a0 - tl) / (k - 1)
            tabs = [(a0 + i * pitch, a0 + i * pitch + tl) for i in range(k)]
    else:                                                  # equal tabs and gaps
        if k < 1:
            tw = s['finger_w'] if s['finger_w'] > 0 else s['auto_w']
            k = max(1, _half_up(((a1 - a0) / tw - 1) / 2)) if not flip else max(2, _half_up(((a1 - a0) / tw + 1) / 2))
        parts = 2 * k + 1 if not flip else 2 * k - 1
        w = (a1 - a0) / parts
        first = 1 if not flip else 0
        tabs = [(a0 + (first + 2 * i) * w, a0 + (first + 2 * i + 1) * w) for i in range(k)]
    segs, pos = [], lo
    for (t0, t1) in tabs:
        if t0 > pos + 1e-9:
            segs.append((pos, t0, 'A'))
        segs.append((t0, t1, 'B'))
        pos = t1
    if hi > pos + 1e-9:
        segs.append((pos, hi, 'A'))
    return segs


# ----------------------------------------------------------------------------------------------- tools
class Builder:
    def __init__(self, fr, s):
        self.fr, self.s = fr, s
        self.r = s['bit_d'] / 2.0
        self.notes = []

    def walls(self, rng, inside_fn):
        """For each axis/side: True if material continues beyond that face of the box (a real wall)."""
        fr, res = self.fr, []
        for k in range(3):
            row = []
            for j in (0, 1):
                c = [(rng[m][0] + rng[m][1]) / 2 for m in range(3)]
                c[k] = rng[k][j] + (PROBE if j else -PROBE)
                row.append(inside_fn(fr.pt(c)))
            res.append(row)
        return res

    def grow(self, rng, walls, gap):
        out = []
        for k in range(3):
            lo = rng[k][0] - (gap if walls[k][0] else OVER)
            hi = rng[k][1] + (gap if walls[k][1] else OVER)
            out.append((lo, hi))
        return out

    def dogbones(self, rng, walls, bit_axis):
        """Relief at each wall-wall corner seen along the bit axis. Dogbone: the bit goes in diagonally.
        T-bone: the bit's centre sits on one wall line, so the round only bites past that wall;
        sideways = past the wall across the joint line (into the next finger), deep = past the other wall.
        T-bones need the joint line (axis 0) in the cut plane, otherwise a dogbone is made."""
        p, q = [k for k in range(3) if k != bit_axis]
        mode = int(round(self.s.get('relief', RELIEF_DOGBONE)))
        along = None                         # the axis the T-bone round bites into
        if mode in (RELIEF_TB_SIDE, RELIEF_TB_DEEP) and 0 in (p, q):
            along = 0 if mode == RELIEF_TB_SIDE else (q if p == 0 else p)
        k = self.r / math.sqrt(2)
        out = []
        for jp in (0, 1):
            for jq in (0, 1):
                if walls[p][jp] and walls[q][jq]:
                    c = [0, 0, 0]
                    j = {p: jp, q: jq}
                    for a in (p, q):
                        inward = 1 if j[a] == 0 else -1
                        if along is None:
                            c[a] = rng[a][j[a]] + inward * k
                        elif a == along:
                            c[a] = rng[a][j[a]]
                        else:
                            c[a] = rng[a][j[a]] + inward * self.r
                    out.append(self.fr.cyl(bit_axis, rng[bit_axis][0], rng[bit_axis][1], c, self.r))
        return out

    def rounded(self, rng, walls, axis, radius):
        """Box with the wall-wall corners (in the plane normal to axis) rounded to radius."""
        b = self.fr.box(rng)
        if radius <= 0:
            return b
        p, q = [k for k in range(3) if k != axis]
        if radius * 2 > min(rng[p][1] - rng[p][0], rng[q][1] - rng[q][0]) + 1e-9:
            self.notes.append('bit too big to round a %.1f mm wide slot' % ((min(rng[p][1] - rng[p][0], rng[q][1] - rng[q][0])) * 10))
            return b
        for jp in (0, 1):
            for jq in (0, 1):
                if not (walls[p][jp] and walls[q][jq]):
                    continue
                cp, cq = rng[p][jp], rng[q][jq]
                r3 = [None, None, None]
                r3[axis] = (rng[axis][0] - EPS, rng[axis][1] + EPS)
                r3[p] = (cp - EPS, cp + radius) if jp == 0 else (cp - radius, cp + EPS)
                r3[q] = (cq - EPS, cq + radius) if jq == 0 else (cq - radius, cq + EPS)
                subtract(b, self.fr.box(r3))
                c = [0, 0, 0]
                c[p] = cp + radius if jp == 0 else cp - radius
                c[q] = cq + radius if jq == 0 else cq - radius
                union([b, self.fr.cyl(axis, rng[axis][0], rng[axis][1], c, radius)])
        return b


def _spec(s):
    d = dict(DEFAULTS)
    d.update(s or {})
    return d


def analyse(body_a, body_b, spec=None, fixed_roles=False):
    """Work out the joint between two boards. Returns dict with mode, frame, region, roles."""
    s = _spec(spec)
    ov = intersect_copy(body_a, body_b)
    if ov:
        na, nb = thin_normal(body_a), thin_normal(body_b)
        u = na.crossProduct(nb)
        if u.length < 0.999:
            raise JointError('%s and %s overlap but are not at 90 degrees (or not flat boards).' % (body_a.name, body_b.name))
        fr = Frame(ov.vertices.item(0).geometry, u, na)
        region = fr.extents(ov)
        auto_w = 2 * max(region[1][1] - region[1][0], region[2][1] - region[2][0])
        return {'mode': 'corner', 'A': body_a, 'B': body_b, 'fr': fr, 'region': region, 'auto_w': auto_w,
                'inside_B': lambda p: inside(body_b, p)}
    f = contact_face(body_b, body_a)
    if not fixed_roles:
        g = contact_face(body_a, body_b)
        if g and (f is None or g.area < f.area):
            body_a, body_b, f = body_b, body_a, g
    if f is None:
        raise JointError('%s and %s neither overlap nor touch.' % (body_a.name, body_b.name))
    fr = _face_frame(f)
    cs = [fr.co(v.geometry) for v in f.vertices]
    fe = [(min(c[k] for c in cs), max(c[k] for c in cs)) for k in range(3)]
    a_ext = fr.extents(body_a)
    through = a_ext[2][1]
    depth = through if (s['depth'] <= 0 or s['depth'] >= through) else s['depth']
    ext_r = [fe[0], fe[1], (0.0, depth)]
    ov = intersect_copy(body_a, fr.box(ext_r))
    if not ov:
        raise JointError('Nothing of %s in front of the end face of %s.' % (body_a.name, body_b.name))
    region = fr.extents(ov)
    tb = region[1][1] - region[1][0]

    def inside_bx(p, fr=fr, ext_r=ext_r):
        if inside(body_b, p):
            return True
        c = fr.co(p)
        return all(ext_r[k][0] < c[k] < ext_r[k][1] for k in range(3))
    return {'mode': 'butt', 'A': body_a, 'B': body_b, 'fr': fr, 'region': region, 'auto_w': 2 * tb,
            'inside_B': inside_bx, 'depth': depth, 'through': depth >= through - 1e-6, 'a_thick': through}


def mt_sizes(J, s, notes):
    """Mortise & tenon: fill in the automatic sizes (0 = auto) in s. Lengths in cm.
    Rules: tenon about 1/3 of B's thickness but never thinner than the bit (the mortise is cut with it),
    shoulders at the edges as wide as the tenon is thick, one tenon per ~125 mm of width."""
    if J['mode'] != 'butt':
        raise JointError('%s and %s overlap. For a mortise & tenon, model %s so its end stops at the face of %s '
                         '(touching, not overlapping).' % (J['A'].name, J['B'].name, J['B'].name, J['A'].name))
    region = J['region']
    T = region[1][1] - region[1][0]            # B's thickness at the joint
    W = region[0][1] - region[0][0]            # B's width at the joint
    bit, gap = s['bit_d'], s['gap']
    t = s['tenon_t'] if s['tenon_t'] > 0 else max(T / 3.0, bit)
    if t > T - 2 * MT_MIN_CHEEK + 1e-9:
        if s['tenon_t'] > 0:
            raise JointError('Tenon %.1f mm is too thick for %.1f mm %s.' % (t * 10, T * 10, J['B'].name))
        raise JointError('%s is %.1f mm thick: too thin for a mortise & tenon with a %.2f mm bit '
                         '(use tab & slot, or a smaller bit).' % (J['B'].name, T * 10, bit * 10))
    if t + 2 * gap < bit - 1e-6:
        notes.append('mortise %.1f mm is narrower than the %.2f mm bit' % ((t + 2 * gap) * 10, bit * 10))
    sh = s['end_off'] if s['end_off'] > 0 else max(t, 0.6)
    usable = W - 2 * sh
    if usable < bit - 1e-9:
        raise JointError('%s is %.1f mm wide: no room for a tenon with %.1f mm shoulders.' % (J['B'].name, W * 10, sh * 10))
    k = int(s['count'])
    tl = s['tab_len']
    space = int(round(s.get('mt_space', SPACE_AUTO)))
    fixed_g = s.get('mt_gap', 1.0)
    if space == SPACE_FIXED and fixed_g <= 0:
        raise JointError('Fixed tenon spacing needs a gap bigger than 0 mm.')
    gap_for = lambda w: 0.5 * w if space == SPACE_AUTO else (w if space == SPACE_EVEN else fixed_g)
    if k < 1:
        k = max(1, int(round(usable / MT_MAX_TENON)))
        w = tl if tl > 0 else (bit if space == SPACE_FIXED else 0)
        if w > 0:                                           # as many as fit with these gaps
            k = max(1, min(k, int((usable + gap_for(w)) / (w + gap_for(w)) + 1e-9)))
    if tl <= 0:
        if k == 1:
            tl = usable
        elif space == SPACE_AUTO:
            tl = usable / (1.5 * k - 0.5)                   # gaps = half a tenon
        elif space == SPACE_EVEN:
            tl = usable / (2 * k - 1)                       # gaps = one tenon (evenly spaced)
        else:
            tl = (usable - (k - 1) * fixed_g) / k
            if tl < bit - 1e-9:
                raise JointError('%d tenons with %.1f mm gaps leave only %.1f mm per tenon (bit %.2f mm).'
                                 % (k, fixed_g * 10, tl * 10, bit * 10))
    if space == SPACE_FIXED and k > 1:                      # exact gaps: centre the group, shoulders take the rest
        total = k * tl + (k - 1) * fixed_g
        if total > usable + 1e-6:
            raise JointError('%d tenons of %.1f mm with %.1f mm gaps need %.1f mm; only %.1f mm between the shoulders.'
                             % (k, tl * 10, fixed_g * 10, total * 10, usable * 10))
        sh += (usable - total) / 2
    s.update({'tenon_t': t, 'end_off': sh, 'count': k, 'tab_len': tl})
    if not J['through']:
        left = J['a_thick'] - J['depth'] - max(s['end_gap'], gap)
        if left < -1e-6:
            notes.append('the mortise breaks through %s (Depth + glue room > %.1f mm): use Depth 0 for a through '
                         'tenon' % (J['A'].name, J['a_thick'] * 10))
        elif left < MT_MIN_BOTTOM:
            notes.append('only %.1f mm of %s left behind the mortise' % (left * 10, J['A'].name))


def build_tools(body_a, body_b, spec=None, fixed_roles=False):
    """Returns (info, tools) where tools = {'cutA': tb, 'joinB': tb|None, 'cutB': tb|None}."""
    s = _spec(spec)
    J = analyse(body_a, body_b, s, fixed_roles)
    s['auto_w'] = J['auto_w']
    fr, region, A, B = J['fr'], [list(r) for r in J['region']], J['A'], J['B']
    bld = Builder(fr, s)
    mt = int(round(s['style'])) == STYLE_MT
    if mt:
        mt_sizes(J, s, bld.notes)
    relief = int(s['relief'])
    ax_a = fr.axis_of(thin_normal(A))
    ax_b = fr.axis_of(thin_normal(B))
    if mt and ax_a != 2:
        bld.notes.append('the mortise is in the edge of %s: a 3-axis CNC cannot plunge it from the face '
                         '(stand %s on end, or use a router jig / mortiser)' % (A.name, A.name))
    ax_m = 2 if mt else ax_a                 # M&T: the mortise is plunged along its depth
    gap = s['gap']
    inside_a = lambda p: inside(A, p)

    if J['mode'] == 'butt' and s['tenon_t'] > 0:
        kb = 1                               # across the end face = B's thickness
        m = (region[kb][0] + region[kb][1]) / 2
        if s['tenon_t'] < region[kb][1] - region[kb][0]:
            region[kb] = [m - s['tenon_t'] / 2, m + s['tenon_t'] / 2]

    segs = layout(region[0][0], region[0][1], J['mode'], s)
    cut_a, cut_b, join_b = [], [], []
    for (s0, s1, owner) in segs:
        rng = [(s0, s1), tuple(region[1]), tuple(region[2])]
        if J['mode'] == 'corner':
            if owner == 'B':                  # B keeps it -> cut from A
                w = bld.walls(rng, inside_a)
                g = bld.grow(rng, w, gap / 2)
                cut_a.append(fr.box(g))
                if relief:
                    cut_a += bld.dogbones(g, w, ax_a)
            else:                             # A keeps it -> cut from B
                w = bld.walls(rng, J['inside_B'])
                g = bld.grow(rng, w, gap / 2)
                cut_b.append(fr.box(g))
                if relief:
                    cut_b += bld.dogbones(g, w, ax_b)
            if (s1 - s0) + gap < s['bit_d'] - 1e-6:
                bld.notes.append('notch %.1f mm is narrower than the %.2f mm bit' % ((s1 - s0) * 10, s['bit_d'] * 10))
        else:
            if owner == 'B':                  # tab / tenon
                w = bld.walls(rng, inside_a)
                g = bld.grow(rng, w, gap)
                if mt and w[2][1]:            # blind mortise: room for glue below the tenon
                    g[2] = (g[2][0], rng[2][1] + max(s['end_gap'], gap))
                tab = [rng[0], rng[1], (rng[2][0] - EPS, rng[2][1])]
                if relief == RELIEF_ROUND:
                    cut_a.append(bld.rounded(g, w, ax_m, bld.r))
                    join_b.append(bld.rounded(tab, w, ax_m, max(bld.r - gap, 0.005)))
                else:
                    cut_a.append(fr.box(g))
                    if relief:
                        cut_a += bld.dogbones(g, w, ax_m)
                    join_b.append(fr.box(tab))
                if (s1 - s0) + 2 * gap < s['bit_d'] - 1e-6:
                    bld.notes.append('slot %.1f mm is narrower than the bit' % ((s1 - s0 + 2 * gap) * 10))
            elif relief in BONES or (mt and relief):   # shoulders on B: corners at the tab roots
                w = bld.walls(rng, J['inside_B'])
                g = bld.grow(rng, w, 0.0)
                cut_b += bld.dogbones(g, w, ax_b)
                if (s1 - s0) < s['bit_d'] - 1e-6 and w[0][0] and w[0][1]:
                    bld.notes.append('gap between tabs %.1f mm is narrower than the bit' % ((s1 - s0) * 10))
    tools = {'cutA': union(cut_a), 'joinB': union(join_b), 'cutB': union(cut_b)}
    tabs = [x for x in segs if x[2] == 'B']
    info = {'mode': J['mode'], 'A': A, 'B': B,
            'segments': len(segs), 'tabs_or_fingers': len(tabs),
            'width_mm': round((segs[0][1] - segs[0][0]) * 10, 2) if J['mode'] == 'corner' else
            round(max(x[1] - x[0] for x in tabs) * 10, 2),
            'length_mm': round((region[0][1] - region[0][0]) * 10, 2),
            'depth_mm': round((region[2][1] - region[2][0]) * 10, 2),
            'bit_axis': (ax_a, ax_b), 'notes': sorted(set(bld.notes)), 'style': STYLE_MT if mt else STYLE_AUTO,
            'thick_mm': (round((J['region'][2][1] - J['region'][2][0] if J['mode'] == 'corner' else J['a_thick']) * 10, 2),
                         round((J['region'][1][1] - J['region'][1][0]) * 10, 2))}
    if mt:
        info.update({'tenon_t_mm': round(s['tenon_t'] * 10, 2), 'shoulder_mm': round(s['end_off'] * 10, 2),
                     'tenon_gap_mm': round((tabs[1][0] - tabs[0][1]) * 10, 2) if len(tabs) > 1 else 0.0,
                     'through': J['through'], 'end_gap_mm': 0.0 if J['through'] else round(max(s['end_gap'], gap) * 10, 2)})
    return info, tools


DEFAULTS = {
    'gap': 0.01,        # clearance per side of each finger/tab (cm) = 0.1 mm
    'bit_d': 0.635,     # 1/4" bit
    'relief': RELIEF_DOGBONE,
    'count': 0,         # 0 = auto (finger width ~ 2 x board thickness, odd count for corners)
    'finger_w': 0.0,    # target finger width, 0 = auto
    'flip': 0,          # corner: swap which board owns the end fingers; butt: tabs at the ends
    'depth': 0.0,       # butt joints: 0 = through
    'tenon_t': 0.0,     # butt joints: 0 = full board thickness, else centred tenon
    'tab_len': 0.0,     # butt joints: 0 = equal tabs and gaps, else fixed tab length
    'end_off': 0.0,     # butt joints: keep this far from the ends of the face (M&T: edge shoulders, 0 = auto)
    'style': STYLE_AUTO,  # 0 = fingers / tabs, 1 = mortise & tenon
    'end_gap': 0.1,     # M&T blind: mortise this much deeper than the tenon (glue room) = 1 mm
    'mt_space': SPACE_AUTO,  # M&T gaps between tenons: 0 half a tenon, 1 one tenon (even), 2 = mt_gap
    'mt_gap': 1.0,      # M&T fixed gap between tenons = 10 mm
}
