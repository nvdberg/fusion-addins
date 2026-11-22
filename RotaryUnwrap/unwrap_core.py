"""
unwrap_core.py - unroll rotary-axis geometry into a flat layout (the inverse of wrap_y_to_a.py).

Flat layout (rotary axis along X, blank diameter D, R = D/2):
    X_flat = position along the axis          (same as the design's X when the axis is the X axis)
    Y_flat = R * angle                       (angle 0 = top of the part; strip runs -pi*R .. +pi*R, seam underneath)
    Z_flat = radius - R                      (Z0 = top of the blank, cuts are negative)

Post the flat toolpaths with the normal Avid post, then:  wrap_y_to_a.py FILE.tap --diameter D
The two scripts use the same D for angle and depth, so they cancel exactly.
Looking down on the flat result reads the same as looking down on the top of the part.
All lengths here are Fusion internal units (cm).
"""
import math
import adsk.core, adsk.fusion

TWO_PI = 2 * math.pi


# ---------------------------------------------------------------- frame
class Frame:
    """Cylindrical frame: axis line, 'up' direction (angle 0) and reference radius."""

    def __init__(self, origin, axis, radius, center_deg=0.0, flip=False):
        ax = _unit(axis)
        # point flat X the same way as world X when possible
        if ax[0] < -1e-9 or (abs(ax[0]) < 1e-9 and (ax[1] < -1e-9 or (abs(ax[1]) < 1e-9 and ax[2] < 0))):
            ax = (-ax[0], -ax[1], -ax[2])
        # O = world origin projected onto the axis, so flat X = world X for an X-axis part
        o = origin
        t = -_dot(o, ax)
        self.O = (o[0] + t * ax[0], o[1] + t * ax[1], o[2] + t * ax[2])
        self.ex = ax
        up = (0.0, 0.0, 1.0) if abs(ax[2]) < 0.9 else (0.0, 1.0, 0.0)
        d = _dot(up, ax)
        self.ez = _unit((up[0] - d * ax[0], up[1] - d * ax[1], up[2] - d * ax[2]))
        self.ey = _cross(self.ez, self.ex)          # +Y flat = +Y world at the top of an X-axis part
        self.R = float(radius)
        self.c = math.radians(center_deg)
        self.s = -1.0 if flip else 1.0

    def polar(self, p):
        """world point -> (x, angle(-pi..pi], radius)"""
        d = (p[0] - self.O[0], p[1] - self.O[1], p[2] - self.O[2])
        x = _dot(d, self.ex)
        u = _dot(d, self.ey)
        w = _dot(d, self.ez)
        a = math.atan2(u, w) - self.c
        a = (a + math.pi) % TWO_PI - math.pi
        if a <= -math.pi + 1e-12:
            a = math.pi
        return x, a, math.hypot(u, w)

    def flat(self, x, a, r):
        return (x, self.s * self.R * a, r - self.R)


def frame_from_selection(entity, diameter=None, center_deg=0.0, flip=False):
    """Cylindrical face, linear edge, sketch line or construction axis -> Frame."""
    radius = None
    if isinstance(entity, adsk.fusion.BRepFace):
        g = entity.geometry
        if not isinstance(g, adsk.core.Cylinder):
            raise ValueError('Pick a cylindrical face (or a straight edge / axis and type the diameter).')
        o, ax, radius = g.origin, g.axis, g.radius
    elif isinstance(entity, adsk.fusion.BRepEdge):
        g = entity.geometry
        if not isinstance(g, adsk.core.Line3D):
            raise ValueError('That edge is not straight.')
        o, e = g.startPoint, g.endPoint
        ax = o.vectorTo(e)
    elif isinstance(entity, adsk.fusion.SketchLine):
        g = entity.worldGeometry
        o, ax = g.startPoint, g.startPoint.vectorTo(g.endPoint)
    elif isinstance(entity, adsk.fusion.ConstructionAxis):
        g = entity.geometry
        o, ax = g.origin, g.direction
    else:
        raise ValueError('Unsupported axis selection.')
    if diameter:
        radius = diameter / 2.0
    if not radius:
        raise ValueError('Enter the blank diameter.')
    return Frame((o.x, o.y, o.z), (ax.x, ax.y, ax.z), radius, center_deg, flip)


# ---------------------------------------------------------------- curves -> flat polylines
def curve_points(entity, tol):
    """World-space stroke points along a sketch curve or B-rep edge."""
    if isinstance(entity, adsk.fusion.SketchCurve):
        ev = entity.worldGeometry.evaluator
    else:
        ev = entity.evaluator
    ok, p0, p1 = ev.getParameterExtents()
    ok, pts = ev.getStrokes(p0, p1, tol)
    return [(p.x, p.y, p.z) for p in pts] if ok else []


def unwrap_polyline(frame, pts):
    """World points -> list of flat polylines, split where the curve crosses the seam."""
    pol = [frame.polar(p) for p in pts]
    segs, cur = [], []
    for i, (x, a, r) in enumerate(pol):
        if cur:
            px, pa, pr = pol[i - 1]
            if abs(a - pa) > math.pi:                      # jumped across the seam
                edge = math.pi if pa > 0 else -math.pi     # side we are leaving
                a_cont = a + (TWO_PI if pa > 0 else -TWO_PI)
                t = (edge - pa) / (a_cont - pa) if a_cont != pa else 0.5
                xm, rm = px + t * (x - px), pr + t * (r - pr)
                cur.append(frame.flat(xm, edge, rm))
                segs.append(cur)
                cur = [frame.flat(xm, -edge, rm)]
        cur.append(frame.flat(x, a, r))
    if cur:
        segs.append(cur)
    return [s for s in segs if len(s) >= 2]


def simplify(pts, tol):
    """Ramer-Douglas-Peucker in 3D."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        a, b = pts[i], pts[j]
        ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
        L2 = _dot(ab, ab)
        dmax, k = -1.0, -1
        for m in range(i + 1, j):
            p = pts[m]
            ap = (p[0] - a[0], p[1] - a[1], p[2] - a[2])
            if L2 < 1e-18:
                d = math.sqrt(_dot(ap, ap))
            else:
                t = max(0.0, min(1.0, _dot(ap, ab) / L2))
                q = (ap[0] - t * ab[0], ap[1] - t * ab[1], ap[2] - t * ab[2])
                d = math.sqrt(_dot(q, q))
            if d > dmax:
                dmax, k = d, m
        if dmax > tol:
            keep[k] = True
            stack += [(i, k), (k, j)]
    return [p for p, f in zip(pts, keep) if f]


def draw_polylines(sketch, polylines, keep_depth):
    """Add flat polylines to a sketch: lines for 2 points, fitted splines otherwise."""
    P = adsk.core.Point3D.create
    sketch.isComputeDeferred = True
    n = 0
    try:
        for pl in polylines:
            pts = [(x, y, z if keep_depth else 0.0) for (x, y, z) in pl]
            closed = len(pts) > 3 and _dist(pts[0], pts[-1]) < 1e-5
            if len(pts) == 2:
                sketch.sketchCurves.sketchLines.addByTwoPoints(P(*pts[0]), P(*pts[1]))
            elif _is_straight(pts):
                sketch.sketchCurves.sketchLines.addByTwoPoints(P(*pts[0]), P(*pts[-1]))
            else:
                oc = adsk.core.ObjectCollection.create()
                for p in (pts[:-1] if closed else pts):
                    oc.add(P(*p))
                sp = sketch.sketchCurves.sketchFittedSplines.add(oc)
                if closed:
                    sp.isClosed = True
            n += 1
    finally:
        sketch.isComputeDeferred = False
    return n


# ---------------------------------------------------------------- shapes -> flat mesh
def _face_mesh(face, max_side, tol):
    mc = face.meshManager.createMeshCalculator()
    mc.setQuality(adsk.fusion.TriangleMeshQualityOptions.VeryHighQualityTriangleMesh)
    mc.surfaceTolerance = tol
    if max_side:
        mc.maxSideLength = max_side
    return mc.calculate()


def is_end_cap(frame, face):
    """Planar face square to the axis that the axis passes through (end of the blank): skip it,
    it has no flat equivalent. Pocket end walls (square to the axis but away from it) are kept."""
    g = face.geometry
    if not isinstance(g, adsk.core.Plane):
        return False
    n = g.normal
    if abs(_dot((n.x, n.y, n.z), frame.ex)) < 0.999:
        return False
    po = g.origin
    t = _dot((po.x - frame.O[0], po.y - frame.O[1], po.z - frame.O[2]), frame.ex)
    hit = adsk.core.Point3D.create(frame.O[0] + t * frame.ex[0], frame.O[1] + t * frame.ex[1], frame.O[2] + t * frame.ex[2])
    ok, prm = face.evaluator.getParameterAtPoint(hit)
    return bool(ok and face.evaluator.isParameterOnFace(prm))


def is_coaxial(frame, face):
    """Cylindrical face around the rotary axis (the blank surface, or a turned step): its flat image is
    a plane at constant depth, so the mesh maps linearly with no extra error."""
    g = face.geometry
    if not isinstance(g, adsk.core.Cylinder):
        return False
    a = _unit((g.axis.x, g.axis.y, g.axis.z))
    if abs(_dot(a, frame.ex)) < 0.99999:
        return False
    d = (g.origin.x - frame.O[0], g.origin.y - frame.O[1], g.origin.z - frame.O[2])
    t = _dot(d, frame.ex)
    off = (d[0] - t * frame.ex[0], d[1] - t * frame.ex[1], d[2] - t * frame.ex[2])
    return _dot(off, off) < 1e-8


def collect_meshes(frame, entities, max_side, tol):
    """Faces, solid bodies and mesh bodies -> list of (coords flat list, indices)."""
    out, skipped = [], 0
    for e in entities:
        if isinstance(e, adsk.fusion.MeshBody):
            m = e.displayMesh
            out.append((list(m.nodeCoordinatesAsDouble), list(m.nodeIndices), False))
            continue
        faces = list(e.faces) if isinstance(e, adsk.fusion.BRepBody) else [e]
        for f in faces:
            if is_end_cap(frame, f):
                skipped += 1
                continue
            m = _face_mesh(f, max_side, tol)
            out.append((list(m.nodeCoordinatesAsDouble), list(m.nodeIndices), is_coaxial(frame, f)))
    return out, skipped


def unwrap_meshes(frame, meshes, max_dev):
    """Map mesh vertices to flat space. Triangles are subdivided in real space until the linear
    flat triangle sags less than max_dev (cm); triangles across the seam are copied to both ends
    of the strip and clipped at +-pi*R, so the strip is exactly -pi*R .. +pi*R wide."""
    coords, tris, cache = [], [], {}
    h = math.pi * frame.R
    circ = TWO_PI * frame.R

    def vid(fp):
        key = (round(fp[0], 6), round(fp[1], 6), round(fp[2], 6))
        i = cache.get(key)
        if i is None:
            i = len(coords) // 3
            coords.extend(fp)
            cache[key] = i
        return i

    def emit(poly):
        ids = [vid(p) for p in poly]
        for k in range(1, len(ids) - 1):
            a, b, c = ids[0], ids[k], ids[k + 1]
            if a != b and b != c and a != c:
                tris.extend((a, b, c))

    for m in meshes:
        xyz, idx, coax = (m + (False,))[:3]
        pts = [(xyz[3 * i], xyz[3 * i + 1], xyz[3 * i + 2]) for i in range(len(xyz) // 3)]
        for t in range(0, len(idx), 3):
            w = [pts[idx[t]], pts[idx[t + 1]], pts[idx[t + 2]]]
            angs = [frame.polar(p)[1] for p in w]
            wrap = max(angs) - min(angs) > math.pi
            for sub in _subdivide(frame, w, max_dev, wrap, coax):
                fl = [frame.flat(*p) for p in sub]
                if not wrap:
                    emit(fl)
                    continue
                for dy in (0.0, circ, -circ):
                    poly = _clip_y([(x, y + dy, z) for x, y, z in fl], h)
                    if len(poly) >= 3:
                        emit(poly)
    return coords, tris


def _polar_tri(frame, w, wrap):
    tri = [frame.polar(p) for p in w]
    if wrap:
        tri = [(x, a + TWO_PI if a < 0 else a, r) for (x, a, r) in tri]
    return tri


def _subdivide(frame, w, max_dev, wrap, coax=False, depth=0):
    """Split a (world-space) triangle until its flat image is within max_dev of the true unwrap,
    checked at the edge midpoints and the centre. Returns polar triangles. Midpoints are taken in
    real space, so planar floors and walls come out right."""
    tri = _polar_tri(frame, w, wrap)
    if coax or depth >= 6:
        return [tri]
    F = [frame.flat(*p) for p in tri]
    a, b, c = w
    mid = lambda p, q: ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2, (p[2] + q[2]) / 2)
    ab, bc, ca = mid(a, b), mid(b, c), mid(c, a)
    cen = ((a[0] + b[0] + c[0]) / 3, (a[1] + b[1] + c[1]) / 3, (a[2] + b[2] + c[2]) / 3)
    checks = ((ab, (0, 1)), (bc, (1, 2)), (ca, (2, 0)), (cen, (0, 1, 2)))
    err = 0.0
    for p, ks in checks:
        true = frame.flat(*_polar_tri(frame, [p], wrap)[0])
        lin = [sum(F[k][d] for k in ks) / len(ks) for d in range(3)]
        err = max(err, _dist(true, lin))
    if err <= max_dev:
        return [tri]
    out = []
    for t in ((a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca)):
        out += _subdivide(frame, list(t), max_dev, wrap, coax, depth + 1)
    return out


def _clip_y(poly, h):
    """Sutherland-Hodgman clip of a flat polygon to -h <= y <= h."""
    for sgn in (1.0, -1.0):
        if not poly:
            return poly
        out = []
        for k in range(len(poly)):
            p, q = poly[k - 1], poly[k]
            pin, qin = sgn * p[1] <= h + 1e-9, sgn * q[1] <= h + 1e-9
            if pin != qin:
                t = (sgn * h - p[1]) / (q[1] - p[1])
                out.append((p[0] + t * (q[0] - p[0]), sgn * h, p[2] + t * (q[2] - p[2])))
            if qin:
                out.append(q)
        poly = out
    return poly


def add_mesh_body(comp, coords, tris, name):
    """Create a mesh body with flat per-triangle normals."""
    normals, nidx = [], []
    for t in range(0, len(tris), 3):
        a, b, c = tris[t:t + 3]
        pa, pb, pc = coords[3 * a:3 * a + 3], coords[3 * b:3 * b + 3], coords[3 * c:3 * c + 3]
        n = _cross((pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2]), (pc[0] - pa[0], pc[1] - pa[1], pc[2] - pa[2]))
        L = math.sqrt(_dot(n, n)) or 1.0
        normals += [n[0] / L, n[1] / L, n[2] / L]
        k = t // 3
        nidx += [k, k, k]
    mb = comp.meshBodies.addByTriangleMeshData(coords, tris, normals, nidx)
    if mb:
        mb.name = name
    return mb


def x_extent(frame, entities, tol):
    """Min/max flat X over the edges of the given faces/bodies/curves."""
    xs = []
    for e in entities:
        edges = []
        if isinstance(e, adsk.fusion.BRepBody):
            edges = list(e.edges)
        elif isinstance(e, adsk.fusion.BRepFace):
            edges = list(e.edges)
        elif isinstance(e, (adsk.fusion.BRepEdge, adsk.fusion.SketchCurve)):
            edges = [e]
        elif isinstance(e, adsk.fusion.MeshBody):
            c = e.displayMesh.nodeCoordinatesAsDouble
            xs += [frame.polar((c[i], c[i + 1], c[i + 2]))[0] for i in range(0, len(c), 3)]
        for ed in edges:
            xs += [frame.polar(p)[0] for p in curve_points(ed, tol)]
    return (min(xs), max(xs)) if xs else None


# ---------------------------------------------------------------- tiny vector helpers
def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(v):
    L = math.sqrt(_dot(v, v))
    return (v[0] / L, v[1] / L, v[2] / L)


def _dist(a, b):
    return math.sqrt(sum((a[k] - b[k]) ** 2 for k in range(3)))


def _is_straight(pts, tol=1e-4):
    return len(simplify(pts, tol)) == 2
