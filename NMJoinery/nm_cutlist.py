"""
NM Cut List: every board with its size, to cut by hand or to order sheet goods.

Pick components or boards, or nothing for the whole design. Boards of the same size in the same component are
counted together. The size is the board's own box: thickness across its biggest face, length = the longest side,
fingers and tabs included (the blank you cut it from). Hidden boards and Lay Flat copies are left out.
OK saves the list as a CSV file (opens in Excel, Numbers or Google Sheets).
"""
import csv, math, os, re, sys, traceback
import adsk.core, adsk.fusion

CMD_ID = 'nmjCutList'
PANEL_ID = 'SolidCreatePanel'
HERE = os.path.dirname(os.path.abspath(__file__))
UNITS = ['mm (metric)', 'inch (imperial)']
SHEETS = [('4 x 8 ft (1220 x 2440 mm)', 1220.0, 2440.0), ('5 x 5 ft (1525 x 1525 mm)', 1525.0, 1525.0),
          ('No sheet count', 0.0, 0.0)]
WASTE = 0.15                                    # sheet count = board area + 15 %, rounded up (no nesting)
nm = None
last = {'units': 0, 'sheet': 0}


def _big_face(body):
    best = None
    for f in body.faces:
        if isinstance(f.geometry, adsk.core.Plane) and (best is None or f.area > best.area):
            best = f
    return best


def size(body):
    """(thickness, width, length) in mm of a board (native body), measured along its own faces."""
    f = _big_face(body)
    try:
        n = f.geometry.normal
        edge = max((e for e in f.edges if isinstance(e.geometry, adsk.core.Line3D)), key=lambda e: e.length)
        lv = edge.startVertex.geometry.vectorTo(edge.endVertex.geometry)
        lv.normalize()
        wv = n.crossProduct(lv)
        ob = adsk.core.Application.get().measureManager.getOrientedBoundingBox(body, lv, wv)
        t, a, b = ob.height, ob.length, ob.width    # height = across the big face
    except Exception:                           # no flat face / no straight edge: the plain box
        bb = body.boundingBox
        t, a, b = sorted(getattr(bb.maxPoint, c) - getattr(bb.minPoint, c) for c in 'xyz')
    a, b = sorted((a * 10, b * 10))
    return t * 10, a, b


def boards(entities):
    """[(component name, board name, native body)] of the visible boards in the picked components / bodies
    (none picked = the whole design)."""
    des = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
    root = des.rootComponent
    flat = lambda path: any(p.startswith('Flat ') for p in path.split('+'))
    occs = [o for o in root.allOccurrences if o.isVisible and not flat(o.fullPathName)]
    out, seen = [], set()

    def add(comp_name, body, key):
        if not body.isSolid:                    # engraved part names (lines, no board)
            return
        if key not in seen:
            seen.add(key)
            out.append((comp_name, body.name, body.nativeObject or body))

    if not entities:
        for b in root.bRepBodies:
            if b.isVisible:
                add(root.name, b, ('', b.name))
        picks = occs
    else:
        picks = []
        for e in entities:
            if isinstance(e, adsk.fusion.BRepBody):
                if e.isVisible and not (e.assemblyContext and flat(e.assemblyContext.fullPathName)):
                    path = e.assemblyContext.fullPathName if e.assemblyContext else ''
                    add(e.parentComponent.name, e, (path, e.name))
            elif isinstance(e, adsk.fusion.Occurrence):
                picks += [o for o in occs if o.fullPathName == e.fullPathName or
                          o.fullPathName.startswith(e.fullPathName + '+')]
    for o in picks:
        for b in o.component.bRepBodies:
            p = b.createForAssemblyContext(o)
            if p.isVisible:
                add(o.component.name, p, (o.fullPathName, b.name))
    return out


def rows(entities):
    """[[component, names, qty, t, w, l]] (mm), same size in the same component counted together."""
    groups = {}
    for comp, name, body in boards(entities):
        t, w, l = size(body)
        k = (comp, round(t, 1), round(w, 1), round(l, 1))
        g = groups.setdefault(k, [comp, [], 0, t, w, l])
        g[2] += 1
        if name not in g[1]:
            g[1].append(name)
    return sorted(groups.values(), key=lambda g: (g[0], -round(g[3], 1), -round(g[5], 1), -round(g[4], 1)))


def fmt(v_mm, inches, mark='"'):
    if not inches:
        return ('%.1f' % v_mm).rstrip('0').rstrip('.')
    n = int(round(v_mm / 25.4 * 32))           # nearest 1/32"
    whole, frac = divmod(n, 32)
    if not frac:
        return '%d%s' % (whole, mark)
    g = math.gcd(frac, 32)
    return ('%d %d/%d' % (whole, frac // g, 32 // g) if whole else '%d/%d' % (frac // g, 32 // g)) + mark


def summary(rs, sheet):
    """[(thickness mm, area m2, sheets or None)] per thickness."""
    by = {}
    for r in rs:
        by.setdefault(round(r[3], 1), 0.0)
        by[round(r[3], 1)] += r[2] * r[4] * r[5] / 1e6
    _, sw, sl = SHEETS[sheet]
    return [(t, a, math.ceil(a * (1 + WASTE) / (sw * sl / 1e6)) if sw else None) for t, a in sorted(by.items(), reverse=True)]


def area_text(a, inches):
    return '%.1f sq ft' % (a * 10.7639) if inches else '%.2f m²' % a


def table_html(rs, inches, sheet):
    if not rs:
        return 'No visible boards found.'
    h = ['<table cellpadding="2"><tr><th align="left">Part</th><th>Qty</th><th>Length</th><th>Width</th>'
         '<th>Thick</th></tr>']
    comp = None
    for c, names, q, t, w, l in rs:
        if c != comp:
            comp = c
            h.append('<tr><td colspan="5"><b>%s</b></td></tr>' % c)
        h.append('<tr><td>%s</td><td align="center">%d</td><td align="right">%s</td><td align="right">%s</td>'
                 '<td align="right">%s</td></tr>' % (', '.join(names), q, fmt(l, inches), fmt(w, inches), fmt(t, inches)))
    h.append('</table><br>')
    for t, a, n in summary(rs, sheet):
        h.append('%s thick: %s%s<br>' % (fmt(t, inches), area_text(a, inches),
                                         '' if n is None else ', about %d sheet%s' % (n, '' if n == 1 else 's')))
    if SHEETS[sheet][1]:
        h.append('<i>Sheets: board area + %d %%, rounded up; not a nesting.</i>' % int(WASTE * 100))
    return ''.join(h)


def write_csv(path, rs, inches, sheet):
    u = 'in' if inches else 'mm'
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['Component', 'Part', 'Qty', 'Length (%s)' % u, 'Width (%s)' % u, 'Thickness (%s)' % u])
        for c, names, q, t, wd, l in rs:
            w.writerow([c, ', '.join(names), q, fmt(l, inches, ''), fmt(wd, inches, ''), fmt(t, inches, '')])
        w.writerow([])
        for t, a, n in summary(rs, sheet):
            w.writerow(['Total', '%s thick' % fmt(t, inches), '', area_text(a, inches),
                        '' if n is None else 'about %d sheet%s of %s' % (n, '' if n == 1 else 's', SHEETS[sheet][0]), ''])


def picked(inputs):
    s = inputs.itemById('sel')
    return [s.selection(i).entity for i in range(s.selectionCount)]


def refresh(inputs):
    inches, sheet = inputs.itemById('units').selectedItem.index == 1, inputs.itemById('sheet').selectedItem.index
    rs = rows(picked(inputs))
    box = inputs.itemById('table')
    box.formattedText = table_html(rs, inches, sheet)
    box.numRows = max(6, min(30, len(rs) + len({r[0] for r in rs}) + 6))
    return rs


class Created(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            nm.log('cut list: dialog opening')
            cmd = args.command
            cmd.isExecutedWhenPreEmpted = False      # starting another command = Cancel, not OK (an auto-OK mid-build crashed Fusion)
            cmd.setDialogInitialSize(460, 640)
            cmd.okButtonText = 'Save CSV'
            inputs = cmd.commandInputs
            s = inputs.addSelectionInput('sel', 'Boards', 'Pick components or boards; nothing picked = the whole design')
            s.addSelectionFilter('Occurrences')
            s.addSelectionFilter('Bodies')
            s.setSelectionLimits(0, 0)
            s.tooltip = 'Pick components (a cabinet, a drawer) or single boards. Nothing picked = every visible board.'
            for iid, name, items, sel in (('units', 'Units', UNITS, last['units']),
                                          ('sheet', 'Sheets', [x[0] for x in SHEETS], last['sheet'])):
                d = inputs.addDropDownCommandInput(iid, name, adsk.core.DropDownStyles.TextListDropDownStyle)
                for i, x in enumerate(items):
                    d.listItems.add(x, i == sel)
            inputs.itemById('sheet').tooltip = 'Sheet size for a rough sheet count per thickness (area + 15 %).'
            inputs.addTextBoxCommandInput('table', '', '', 12, True).isFullWidth = True
            refresh(inputs)
            for ev, h in ((cmd.execute, Execute()), (cmd.inputChanged, Changed())):
                ev.add(h)
                nm.handlers.append(h)
        except Exception:
            nm.log('cut list dialog failed:\n' + traceback.format_exc())
            nm.ui.messageBox('NM Cut List failed:\n' + traceback.format_exc())


class Changed(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        try:
            if args.input.id != 'table':
                refresh(args.input.parentCommand.commandInputs)
        except Exception:
            nm.log('cut list dialog:\n' + traceback.format_exc())


class Execute(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            inputs = args.command.commandInputs
            inches, sheet = inputs.itemById('units').selectedItem.index == 1, inputs.itemById('sheet').selectedItem.index
            last.update(units=int(inches), sheet=sheet)
            rs = rows(picked(inputs))
            if not rs:
                return
            app = adsk.core.Application.get()
            fd = nm.ui.createFileDialog()
            fd.title = 'Save the cut list'
            fd.filter = 'CSV file (*.csv)'
            doc = re.sub(r' v\d+$', '', app.activeDocument.name).strip() or 'Design'   # "Kitchen vanity v3" -> "Kitchen vanity"
            fd.initialFilename = '%s cut list.csv' % re.sub(r'[\\/:*?"<>|]', '-', doc)
            if fd.showSave() != adsk.core.DialogResults.DialogOK:
                return
            write_csv(fd.filename, rs, inches, sheet)
            nm.log('cut list: %d rows saved' % len(rs))
        except Exception:
            nm.log('cut list failed:\n' + traceback.format_exc())
            nm.ui.messageBox('NM Cut List failed:\n' + traceback.format_exc())


def register(mod):
    global nm
    nm = mod
    unregister(mod)                             # button + definition: a button left on a deleted definition is dead
    defs = nm.ui.commandDefinitions
    old = defs.itemById(CMD_ID)
    if old:
        old.deleteMe()
    c = defs.addButtonDefinition(CMD_ID, 'NM Cut List',
                                 'A list of every board with its size (length x width x thickness), counted per '
                                 'component, with the area per thickness and a rough sheet count. Save it as CSV.',
                                 os.path.join(HERE, 'resources', 'create'))
    h = Created()
    c.commandCreated.add(h)
    nm.handlers.append(h)
    panel = nm.ui.allToolbarPanels.itemById(PANEL_ID)
    if panel:
        panel.controls.addCommand(c)


def unregister(mod):
    ui = mod.ui
    panel = ui.allToolbarPanels.itemById(PANEL_ID)
    if panel and panel.controls.itemById(CMD_ID):
        panel.controls.itemById(CMD_ID).deleteMe()
    d = ui.commandDefinitions.itemById(CMD_ID)
    if d:
        d.deleteMe()
