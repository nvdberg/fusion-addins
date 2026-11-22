# NM Joinery - "NM Lay Flat": a copy of every board laid flat for CAM, inside face up, in its own component
# (clean-room). It is a custom feature that depends on the source bodies, so it follows every size change.
# Each board: the normal of its largest flat face is its thickness direction; the face that looks toward the
# middle of all selected boards is the inside and ends up facing +Z; the longest straight edge of that big face
# runs along X. Boards are stacked along Y with a spacing, next to the originals (+X side), bottoms at Z = 0.
import adsk.core, adsk.fusion, os, json, math, traceback

FLAT_ID = 'NMWoodworks.Flat'
CMD_ID = 'nmjLayFlat'
EDIT_ID = 'nmjLayFlatEdit'
PANEL_ID = 'SolidCreatePanel'
VI = adsk.core.ValueInput.createByString
HERE = os.path.dirname(os.path.abspath(__file__))
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


def lay(bodies, gap, dx=0.0):
    """Flat copies (TemporaryBRep bodies, world coordinates) of the bodies, in the same order."""
    tbm = adsk.fusion.TemporaryBRepManager.get()
    union = None
    for b in bodies:
        if union is None:
            union = b.boundingBox.copy()
        else:
            union.combine(b.boundingBox)
    C = _centre(union)
    Z = adsk.core.Vector3D.create(0, 0, 1)
    X = adsk.core.Vector3D.create(1, 0, 0)
    origin = adsk.core.Point3D.create(0, 0, 0)
    x0, cursor = union.maxPoint.x + 10.0 + dx, union.minPoint.y      # dx: shift sideways (bank of drawers)
    out = []
    for b in bodies:
        tb = tbm.copy(b)
        face = _big_face(b)
        if face is not None:
            n = face.geometry.normal.copy()
            n.normalize()
            if _vec(_centre(b.boundingBox), C).dotProduct(n) < -1e-6:
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
                dx, dy = max(xs) - min(xs), max(ys) - min(ys)
                if dy > dx + 1e-6:
                    ang += math.pi / 2
                    dx, dy = dy, dx
                if best is None or dx * dy < best[0] - 1e-6:
                    best = (dx * dy, ang)
            if best:
                r = adsk.core.Matrix3D.create()
                r.setToRotation(-best[1], Z, origin)
                tbm.transform(tb, r)
        bb = tb.boundingBox
        t = adsk.core.Matrix3D.create()
        t.translation = adsk.core.Vector3D.create(x0 - bb.minPoint.x, cursor - bb.minPoint.y, -bb.minPoint.z)
        tbm.transform(tb, t)
        cursor += bb.maxPoint.y - bb.minPoint.y + gap
        out.append(tb)
    return out


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


def make_flat(bodies, name, gap='20 mm', dx=None):
    """bodies: BRepBodies (proxies in the root context when they live in a component)."""
    des = nm.design()
    root = des.rootComponent
    occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    comp = occ.component
    comp.name = 'Flat ' + name
    feats = comp.features
    cfi = feats.customFeatures.createInput(definition)
    cfi.addCustomParameter('gap', 'Spacing', VI(gap), 'mm', True)
    if dx:
        cfi.addCustomParameter('dx', 'Shift sideways', VI(dx), 'mm', True)
    for i, b in enumerate(bodies):
        if not cfi.addDependency('b%d' % i, b):
            raise RuntimeError('could not follow body %s' % b.name)
    nw = watch(cfi, bodies)
    flats = lay(bodies, des.unitsManager.evaluateExpression(gap, 'mm'),
                des.unitsManager.evaluateExpression(dx, 'mm') if dx else 0.0)
    bf = feats.baseFeatures.add()
    bf.startEdit()
    for tb in flats:
        comp.bRepBodies.add(tb, bf)
    bf.finishEdit()
    bf.name = 'Flat boards'
    for i, b in enumerate(bodies):
        bf.bodies.item(i).name = b.name
    cfi.setStartAndEndFeatures(bf, bf)
    cf = feats.customFeatures.add(cfi)
    cf.name = 'NM Flat ' + name
    cf.customNamedValues.addOrSetValue('names', json.dumps([b.name for b in bodies]))
    nm.log('flat %s: %d boards, %d watched parameters' % (name, len(bodies), nw))
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
            bf = next(adsk.fusion.BaseFeature.cast(f) for f in cf.features if adsk.fusion.BaseFeature.cast(f))
            sh = nm.fparam(cf, 'dx')        # only on bank flats (itemById raises when missing)
            flats = lay(bodies, cf.parameters.itemById('gap').value, sh.value if sh else 0.0)
            bf.startEdit()
            try:
                olds = [bf.bodies.item(i) for i in range(bf.bodies.count)]
                if len(olds) != len(flats):
                    nm.log('flat compute %s: %d copies for %d boards, skipped' % (cf.name, len(olds), len(flats)))
                    return                           # first compute while the feature is being added
                for old, tb in zip(olds, flats):
                    bf.updateBody(old, tb)
            finally:
                bf.finishEdit()
            nm.log('compute %s: %d boards' % (cf.name, len(flats)))
        except Exception:
            nm.log('flat compute failed:\n' + traceback.format_exc())
            try:
                args.computeStatus.statusMessages.addError('NMF_ERR', traceback.format_exc().strip().splitlines()[-1])
            except Exception:
                pass


# ----------------------------------------------------------------------------------------------- commands
class MakeCreated(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = args.command
            inputs = cmd.commandInputs
            s = inputs.addSelectionInput('bodies', 'Boards', 'Pick the boards to lay flat')
            s.addSelectionFilter('Bodies')
            s.setSelectionLimits(1, 0)
            inputs.addValueInput('gap', 'Spacing', 'mm', VI('20 mm'))
            for ev, h in ((cmd.execute, MakeExecute()),):
                ev.add(h)
                nm.handlers.append(h)
        except Exception:
            nm.ui.messageBox('NM Lay Flat failed:\n' + traceback.format_exc())


class MakeExecute(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            inputs = args.command.commandInputs
            sel = inputs.itemById('bodies')
            bodies = [sel.selection(i).entity for i in range(sel.selectionCount)]
            name = bodies[0].assemblyContext.component.name if bodies[0].assemblyContext else bodies[0].parentComponent.name
            make_flat(bodies, name, inputs.itemById('gap').expression)
        except Exception:
            nm.log('lay flat failed:\n' + traceback.format_exc())
            nm.ui.messageBox('NM Lay Flat failed:\n' + traceback.format_exc())


class EditCreated(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cf = adsk.fusion.CustomFeature.cast(nm.ui.activeSelections.item(0).entity)
            cmd = args.command
            p = cf.parameters.itemById('gap')
            cmd.commandInputs.addValueInput('gap', 'Spacing', 'mm', VI(p.expression))
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
            self.cf.parameters.itemById('gap').expression = args.command.commandInputs.itemById('gap').expression
        except Exception:
            nm.ui.messageBox('NM Lay Flat edit failed:\n' + traceback.format_exc())


def register(mod):
    global nm, definition
    nm = mod
    defs = nm.ui.commandDefinitions
    for cid in (CMD_ID, EDIT_ID):
        old = defs.itemById(cid)
        if old:
            old.deleteMe()
    c = defs.addButtonDefinition(CMD_ID, 'NM Lay Flat',
                                 'A copy of the picked boards laid flat (inside face up, longest edge along X) in a new '
                                 'component, for CAM. It follows size changes of the boards.',
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
    if panel and not panel.controls.itemById(CMD_ID):
        panel.controls.addCommand(c)


def unregister(mod):
    ui = mod.ui
    panel = ui.allToolbarPanels.itemById(PANEL_ID)
    if panel and panel.controls.itemById(CMD_ID):
        panel.controls.itemById(CMD_ID).deleteMe()
    for cid in (CMD_ID, EDIT_ID):
        d = ui.commandDefinitions.itemById(cid)
        if d:
            d.deleteMe()
