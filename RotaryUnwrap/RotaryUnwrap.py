"""
RotaryUnwrap - Fusion add-in: Solid > Modify > Flatten for Rotary.

Unrolls a round part (cylinder with cuts, carving, text...) into the flat strip that
wrap_y_to_a.py expects:  X along the axis, Y0 = centre line (top of the part at A=0),
Y from -pi*D/2 to +pi*D/2, Z0 = top of the blank, cuts negative.

Output goes into a new component "Flat D=..." placed under the part:
  * sketch "Flat outline"  - edges that lie on the blank surface (the cut-out outlines) + the strip rectangle
  * mesh body "Flat relief" - the whole carved surface, for 3D toolpaths
Then: CAM setup on the flat component, post with the normal Avid post, run wrap_y_to_a.py --diameter D.
"""
import math, os, sys, traceback
import adsk.core, adsk.fusion

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import unwrap_core as uc  # noqa: E402

app = adsk.core.Application.get()
ui = app.userInterface
CMD_ID = 'nmRotaryFlatten'
PANEL_ID = 'SolidModifyPanel'
handlers = []


def log(msg):
    try:
        app.log('RotaryUnwrap: ' + msg)
    except Exception:
        pass
    try:
        import datetime
        with open(os.path.join(HERE, 'unwrap_log.txt'), 'a', encoding='utf-8') as f:
            f.write('%s  %s\n' % (datetime.datetime.now().isoformat(timespec='seconds'), msg))
    except Exception:
        pass


# ----------------------------------------------------------------------------------------------- core
def flatten(des, axis_ent, items, dia, center_deg=0.0, flip=False, outline=True, relief=True, tol=0.005):
    """Do the unwrap. Lengths in cm. Returns (occurrence, report lines)."""
    frame = uc.frame_from_selection(axis_ent, dia, center_deg, flip)
    R = frame.R
    rep = []
    ext = uc.x_extent(frame, items, tol)
    if not ext:
        raise ValueError('Nothing to flatten: select the body (or faces / edges / sketch curves).')
    x0, x1 = ext

    # place the flat strip under everything that was selected, so it never overlaps the part
    zmin = None
    for e in items:
        bb = getattr(e, 'boundingBox', None)
        if bb:
            zmin = bb.minPoint.z if zmin is None else min(zmin, bb.minPoint.z)
    top = (zmin if zmin is not None else -R) - 2.0 - R          # 2 cm gap + room for deep cuts
    m = adsk.core.Matrix3D.create()
    m.translation = adsk.core.Vector3D.create(0, 0, top)
    root = des.rootComponent
    occ = root.occurrences.addNewComponent(m)
    comp = occ.component
    mm = lambda v: ('%.3f' % (v * 10)).rstrip('0').rstrip('.')
    comp.name = 'Flat D=%s mm' % mm(2 * R)

    if outline:
        sk = comp.sketches.add(comp.xYConstructionPlane)
        sk.name = 'Flat outline'
        P = adsk.core.Point3D.create
        h = math.pi * R
        lines = sk.sketchCurves.sketchLines
        rect = lines.addTwoPointRectangle(P(x0, -h, 0), P(x1, h, 0))
        for i in range(rect.count):
            rect.item(i).isConstruction = False
        lines.addByTwoPoints(P(x0, 0, 0), P(x1, 0, 0)).isConstruction = True   # Y0 centre line
        polys, skipped = [], 0
        for e in items:
            if isinstance(e, (adsk.fusion.BRepBody, adsk.fusion.BRepFace)):
                edges = list(e.edges)
            elif isinstance(e, (adsk.fusion.BRepEdge, adsk.fusion.SketchCurve)):
                edges = [e]
            else:
                edges = []
            for ed in edges:
                pts = uc.curve_points(ed, tol)
                if not pts:
                    continue
                # keep only edges on the blank surface (unless the user picked the curve itself)
                if not isinstance(e, (adsk.fusion.BRepEdge, adsk.fusion.SketchCurve)):
                    if max(abs(frame.polar(p)[2] - R) for p in pts) > max(0.01, 2 * tol):
                        skipped += 1
                        continue
                for pl in uc.unwrap_polyline(frame, pts):
                    pl = uc.simplify(pl, tol / 4)
                    # end circles of the blank unwrap onto the rectangle ends: already drawn
                    if all(abs(p[0] - x0) < 1e-4 for p in pl) or all(abs(p[0] - x1) < 1e-4 for p in pl):
                        continue
                    if all(abs(abs(p[1]) - h) < 1e-4 for p in pl):
                        continue
                    polys.append(pl)
        n = uc.draw_polylines(sk, polys, False)
        rep.append('outline sketch: %d curves + strip rectangle (%d edges below the surface left out)' % (n, skipped))

    if relief:
        bodies = [e for e in items if isinstance(e, (adsk.fusion.BRepBody, adsk.fusion.BRepFace, adsk.fusion.MeshBody))]
        if bodies:
            meshes, caps = uc.collect_meshes(frame, bodies, 0, tol)
            coords, tris = uc.unwrap_meshes(frame, meshes, tol)
            mb = uc.add_mesh_body(comp, coords, tris, 'Flat relief')
            zs = coords[2::3]
            rep.append('relief mesh: %d triangles, deepest %.2f mm (%d end caps skipped)' % (len(tris) // 3, -min(zs) * 10, caps))
            if mb is None:
                rep.append('relief mesh could not be created')
        else:
            rep.append('relief mesh: no bodies or faces selected, skipped')

    rep.insert(0, 'strip X %.2f .. %.2f mm, Y -%.2f .. +%.2f mm (circumference %.2f mm), diameter %.3f mm'
               % (x0 * 10, x1 * 10, math.pi * R * 10, math.pi * R * 10, 2 * math.pi * R * 10, 2 * R * 10))
    return occ, rep


# ----------------------------------------------------------------------------------------------- command
def _inputs(cmd):
    i = cmd.commandInputs
    return {k: i.itemById(k) for k in ('axis', 'geo', 'dia', 'center', 'flip', 'outline', 'relief', 'tol', 'info')}


class CmdCreated(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = adsk.core.CommandCreatedEventArgs.cast(args).command
            ins = cmd.commandInputs
            a = ins.addSelectionInput('axis', 'Cylinder / axis', 'Pick the round face of the blank (or a straight edge, sketch line or axis along the rotary axis)')
            for f in ('CylindricalFaces', 'LinearEdges', 'SketchLines', 'ConstructionLines'):
                a.addSelectionFilter(f)
            a.setSelectionLimits(1, 1)
            g = ins.addSelectionInput('geo', 'Flatten', 'Bodies, faces, edges or sketch curves to unroll (the body is added for you when you pick its round face)')
            for f in ('SolidBodies', 'MeshBodies', 'Faces', 'Edges', 'SketchCurves'):
                g.addSelectionFilter(f)
            g.setSelectionLimits(1, 0)
            ins.addValueInput('dia', 'Blank diameter', 'mm', adsk.core.ValueInput.createByString('50.8 mm'))
            ins.addValueInput('center', 'Angle on Y0 line', 'deg', adsk.core.ValueInput.createByString('0 deg'))
            ins.addBoolValueInput('flip', 'Flip Y', True, '', False)
            ins.addBoolValueInput('outline', 'Outline sketch', True, '', True)
            ins.addBoolValueInput('relief', '3D relief mesh', True, '', True)
            ins.addValueInput('tol', 'Accuracy', 'mm', adsk.core.ValueInput.createByString('0.05 mm'))
            ins.addTextBoxCommandInput('info', '', 'Angle 0 (straight up) becomes the Y0 centre line. '
                                       'Use the same diameter in wrap_y_to_a.py.', 3, True)
            for ev, cls in ((cmd.inputChanged, Changed), (cmd.execute, Execute)):
                h = cls(); ev.add(h); handlers.append(h)
        except Exception:
            log(traceback.format_exc())


class Changed(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        try:
            args = adsk.core.InputChangedEventArgs.cast(args)
            if args.input.id != 'axis':
                return
            I = _inputs(args.input.parentCommand)
            if I['axis'].selectionCount:
                e = I['axis'].selection(0).entity
                if isinstance(e, adsk.fusion.BRepFace) and isinstance(e.geometry, adsk.core.Cylinder):
                    I['dia'].value = 2 * e.geometry.radius
                    if I['geo'].selectionCount == 0:
                        I['geo'].addSelection(e.body)
        except Exception:
            log(traceback.format_exc())


class Execute(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            I = _inputs(adsk.core.CommandEventArgs.cast(args).command)
            des = adsk.fusion.Design.cast(app.activeProduct)
            ax = I['axis'].selection(0).entity
            items = [I['geo'].selection(k).entity for k in range(I['geo'].selectionCount)]
            occ, rep = flatten(des, ax, items, I['dia'].value, math.degrees(I['center'].value),
                               I['flip'].value, I['outline'].value, I['relief'].value, max(I['tol'].value, 0.0005))
            for r in rep:
                log(r)
            ui.messageBox('Made component "%s":\n\n%s\n\nNext: Manufacture > Setup on this component, '
                          'WCS on the top face, X0 at the end, Y0 on the centre line. Post with the normal Avid '
                          'post, then run wrap_y_to_a.py --diameter %.3fmm.'
                          % (occ.component.name, '\n'.join(rep), I['dia'].value * 10),
                          'Flatten for Rotary')
        except ValueError as e:
            ui.messageBox(str(e), 'Flatten for Rotary')
        except Exception:
            log(traceback.format_exc())
            ui.messageBox('Flatten failed:\n' + traceback.format_exc(), 'Flatten for Rotary')


def run(context):
    try:
        d = ui.commandDefinitions.itemById(CMD_ID)
        if d:
            d.deleteMe()
        d = ui.commandDefinitions.addButtonDefinition(
            CMD_ID, 'Flatten for Rotary',
            'Unroll a round part into a flat strip (X = axis, Y = around, Z0 = top) for 3-axis toolpaths. '
            'Post with the normal Avid post, then run wrap_y_to_a.py to turn Y into A.',
            os.path.join(HERE, 'resources'))
        h = CmdCreated(); d.commandCreated.add(h); handlers.append(h)
        panel = ui.allToolbarPanels.itemById(PANEL_ID)
        if panel and not panel.controls.itemById(CMD_ID):
            panel.controls.addCommand(d).isPromoted = True
        log('started')
        try:                                    # "a newer version is out" notice (GitHub releases)
            import ru_update
            ru_update.start('RotaryUnwrap', HERE, log)
        except Exception:
            log('update check:\n' + traceback.format_exc())
    except Exception:
        log('failed to start:\n' + traceback.format_exc())


def stop(context):
    try:
        import ru_update
        ru_update.stop_('RotaryUnwrap')
    except Exception:
        log(traceback.format_exc())
    try:
        panel = ui.allToolbarPanels.itemById(PANEL_ID)
        c = panel and panel.controls.itemById(CMD_ID)
        if c:
            c.deleteMe()
        d = ui.commandDefinitions.itemById(CMD_ID)
        if d:
            d.deleteMe()
    except Exception:
        log(traceback.format_exc())
