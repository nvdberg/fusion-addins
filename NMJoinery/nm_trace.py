"""
NM Name Trace (Manufacture > 2D): one Trace operation that engraves every part name in a setup.

The names from "Engrave part names" (NM Drawer / NM Cabinet) are wire bodies called "<board> name". This picks the ones
on the setup's boards that lie flat and face up (the Lay Flat copies), puts each letter stroke in the Trace as its own
chain, and sets a 60 deg V-bit and the depth. Run it again after a change: the setup's "Part names" Trace is updated
instead of a second one being added.
"""
import json, os, traceback
import adsk.core, adsk.fusion, adsk.cam

CMD_ID = 'nmjNameTrace'
PANEL_ID = 'CAM2DPanel'
HERE = os.path.dirname(os.path.abspath(__file__))
OP_NAME = 'Part names'
TOL = 0.002                                     # cm: a name is flat when all its points are this close along the setup Z
nm = None
last = {'setup': '', 'tool': '', 'depth': '0.5 mm'}
_tools = None                                   # [(label, Tool)], read once per session (cloud libraries are slow)

# 60 deg V-bit, 1/2" D x 1/4" shank (Whiteside 1550 class), used when no 60 deg V-bit is found in any tool library
BUILT_IN = {
    'BMC': 'carbide', 'GRADE': 'Mill Generic', 'type': 'chamfer mill', 'unit': 'inches',
    'description': '60 deg V-bit 1/2" D (NM built in - check feeds for your machine)',
    'geometry': {'CSP': False, 'DC': 0.5, 'HAND': True, 'LB': 1.0, 'LCF': 0.4375, 'NOF': 2, 'NT': 1, 'OAL': 2.0,
                 'RE': 0, 'SFDM': 0.25, 'TA': 30, 'TP': 0, 'assemblyGaugeLength': 1.0, 'shoulder-diameter': 0.25,
                 'shoulder-length': 0.4875, 'tip-diameter': 0, 'tip-length': 0, 'tip-offset': 0},
    'post-process': {'number': 51, 'diameter-offset': 51, 'length-offset': 51, 'live': True, 'turret': 0,
                     'break-control': False, 'manual-tool-change': False, 'comment': ''},
    'start-values': {'presets': [{'name': 'Default Preset', 'n': 13600, 'n_ramp': 13600, 'v_f': 115, 'v_f_leadIn': 115,
                                  'v_f_leadOut': 115, 'v_f_plunge': 17, 'v_f_ramp': 26, 'v_f_transition': 115,
                                  'tool-coolant': 'disabled', 'use-stepdown': False, 'use-stepover': False,
                                  'material': {'category': 'all', 'query': '', 'use-hardness': False}}]},
}


# ------------------------------------------------------------------------------------------------- finding names
def _pts(body):
    return [v.geometry for v in body.vertices]


def _span(pts, z):
    ds = [p.x * z.x + p.y * z.y + p.z * z.z for p in pts]
    return min(ds), max(ds)


def _zaxis(setup):
    o, x, y, z = setup.workCoordinateSystem.getAsCoordinateSystem()
    z.normalize()
    return z


def _bodies(ent):
    """All bodies (proxies where needed) under a setup model entity."""
    b = adsk.fusion.BRepBody.cast(ent)
    if b:
        return [b]
    oc = adsk.fusion.Occurrence.cast(ent)
    if oc:
        out = list(oc.bRepBodies)
        for c in oc.childOccurrences:
            out += _bodies(c)
        return out
    c = adsk.fusion.Component.cast(ent)
    if c:
        out = list(c.bRepBodies)
        for o in c.allOccurrences:
            out += list(o.bRepBodies)
        return out
    return []


def _key(b):
    oc = b.assemblyContext
    return (oc.fullPathName if oc else b.parentComponent.name, b.name)


def names_for(setup):
    """(names to engrave, skipped count): visible "<board> name" wire bodies on the setup's boards, flat in the
    setup's XY and on the top of their board."""
    doc = adsk.core.Application.get().activeDocument
    des = adsk.fusion.Design.cast(doc.products.itemByProductType('DesignProductType'))
    ms = [setup.models.item(i) for i in range(setup.models.count)] if setup.models else []
    pool = []
    if ms:
        for m in ms:
            pool += _bodies(m)
        # a picked board brings its own name with it
        for b in list(pool):
            if b.isSolid:
                ctx = b.assemblyContext
                sib = ctx.bRepBodies if ctx else b.parentComponent.bRepBodies
                n = sib.itemByName(b.name + ' name')
                if n:
                    pool.append(n)
    else:
        pool = _bodies(des.rootComponent)
    seen, boards, wires = set(), {}, []
    for b in pool:
        k = _key(b)
        if k in seen:
            continue
        seen.add(k)
        if b.isSolid:
            boards[k] = b
        elif b.name.endswith(' name') and b.isVisible:
            wires.append(b)
    if not wires:
        return [], 0
    z = _zaxis(setup)
    good, skipped = [], 0
    in_flat = lambda w: any(x.startswith('Flat') for x in ((w.assemblyContext.fullPathName.split('+') if w.assemblyContext else [])
                                                            + [w.parentComponent.name]))
    if any(in_flat(w) for w in wires):              # Lay Flat copies there: the assembled boards are not for cutting
        skipped += sum(1 for w in wires if not in_flat(w))
        wires = [w for w in wires if in_flat(w)]
    for w in wires:
        lo, hi = _span(_pts(w), z)
        if hi - lo > TOL:
            skipped += 1                        # standing up (the assembled drawer), not this setup's
            continue
        k = _key(w)
        brd = boards.get((k[0], w.name[:-5]))
        if brd is None:
            ctx = w.assemblyContext
            brd = (ctx.bRepBodies if ctx else w.parentComponent.bRepBodies).itemByName(w.name[:-5])
        if brd is not None and abs(_span(_pts(brd), z)[1] - hi) > TOL:
            skipped += 1                        # on the underside: turn the board over in its own setup
            continue
        good.append(w)
    return good, skipped


def strokes(body):
    """The wire's edges grouped into connected strokes, each in drawing order (end of one edge = start of the next
    where possible), so the Trace can keep the bit down along a stroke."""
    es = list(body.edges)
    key = lambda p: (round(p.x, 5), round(p.y, 5), round(p.z, 5))
    par = list(range(len(es)))

    def find(i):
        while par[i] != i:
            par[i] = par[par[i]]
            i = par[i]
        return i
    at = {}
    for i, e in enumerate(es):
        for v in (e.startVertex, e.endVertex):
            k = key(v.geometry)
            if k in at:
                par[find(i)] = find(at[k])
            else:
                at[k] = i
    groups = {}
    for i, e in enumerate(es):
        groups.setdefault(find(i), []).append(e)
    out = []
    for g in groups.values():
        ends = lambda e: (key(e.startVertex.geometry), key(e.endVertex.geometry))
        deg = {}
        for e in g:
            for k in ends(e):
                deg[k] = deg.get(k, 0) + 1
        left = list(g)
        # start at a loose end if there is one
        cur = next((e for e in left if deg[ends(e)[0]] == 1 or deg[ends(e)[1]] == 1), left[0])
        at_ = ends(cur)[0] if deg[ends(cur)[0]] == 1 else ends(cur)[1]     # where the pen starts
        path = []
        while left:
            left.remove(cur)
            path.append(cur)
            a, b = ends(cur)
            at_ = b if a == at_ else a
            cur = next((e for e in left if at_ in ends(e)), left[0] if left else None)
            if cur is not None and at_ not in ends(cur):
                at_ = ends(cur)[0]
        out.append(path)
    return out


# ------------------------------------------------------------------------------------------------- tools
def _is_vbit(js):
    try:
        d = json.loads(js)
        return d.get('type') == 'chamfer mill' and abs(float(d['geometry']['TA']) - 30) < 0.01
    except Exception:
        return False


def _label(t, where):
    d = json.loads(t.toJson())
    n = d.get('post-process', {}).get('number')
    return 'T%s %s (%s)' % (n, d.get('description') or '60 deg V-bit', where)


def tools(cam):
    """60 deg V-bits: this document's first, then the local and cloud libraries, then the built-in one."""
    global _tools
    found, labels = [], set()

    def add(t, where):
        lb = _label(t, where)
        if lb not in labels:
            labels.add(lb)
            found.append((lb, t))
    try:
        lib = cam.documentToolLibrary
        for i in range(lib.count):
            if _is_vbit(lib.item(i).toJson()):
                add(lib.item(i), 'this document')
    except Exception:
        nm.log('name trace: document tools:\n' + traceback.format_exc())
    if _tools is None:
        _tools = []
        try:
            lm = adsk.cam.CAMManager.get().libraryManager.toolLibraries
            for loc, where in ((adsk.cam.LibraryLocations.LocalLibraryLocation, 'local'),
                               (adsk.cam.LibraryLocations.CloudLibraryLocation, 'cloud')):
                for url in lm.childAssetURLs(lm.urlByLocation(loc)):
                    try:
                        lib = lm.toolLibraryAtURL(url)
                        name = url.leafName
                        for i in range(lib.count):
                            if _is_vbit(lib.item(i).toJson()):
                                _tools.append((lib.item(i), name))
                    except Exception:
                        nm.log('name trace: library %s:\n%s' % (url.toString(), traceback.format_exc()))
        except Exception:
            nm.log('name trace: libraries:\n' + traceback.format_exc())
    num = lambda t: json.loads(t.toJson()).get('post-process', {}).get('number') or 0
    for t, where in sorted(_tools, key=lambda x: num(x[0]) == 0):   # numbered tools before T0 ones
        add(t, where)
    used = {num(t) for _, t in found}
    b = json.loads(json.dumps(BUILT_IN))
    n = next(i for i in [51] + list(range(60, 1000)) if i not in used)   # never the number of another bit
    b['post-process'].update({'number': n, 'diameter-offset': n, 'length-offset': n})
    add(adsk.cam.Tool.createFromJson(json.dumps(b)), 'built in')
    return found


# ------------------------------------------------------------------------------------------------- the operation
def make(setup, tool, depth_expr):
    """Adds (or updates) the setup's "Part names" Trace. Returns (operation, names, strokes, skipped)."""
    names, skipped = names_for(setup)
    if not names:
        return None, 0, 0, skipped
    # one chain per edge: a Fusion chain only follows tangent edges from its first edge, and letters have corners
    chains = [[e] for n in names for st in strokes(n) for e in st]
    op = None
    for i in range(setup.operations.count):
        o = setup.operations.item(i)
        if o.name == OP_NAME and o.strategy == 'trace':
            op = o
    params = None
    if op is None:
        oi = setup.operations.createInput('trace')
        oi.displayName = OP_NAME
        oi.tool = tool
        params = oi.parameters
    else:
        op.tool = tool
        params = op.parameters
    cv = params.itemByName('curves').value
    cs = cv.getCurveSelections()
    cs.clear()
    for edges in chains:
        ch = cs.createNewChainSelection()
        ch.inputGeometry = edges
    cv.applyCurveSelections(cs)
    params.itemByName('axialOffset').expression = '-(%s)' % depth_expr
    # feed height under the retract height (both default to +5 mm, which Fusion can see as 'feed above retract')
    params.itemByName('feedHeight_offset').expression = '2.5 mm'
    if op is None:
        op = setup.operations.add(oi)
    return op, len(names), len(chains), skipped


# ------------------------------------------------------------------------------------------------- dialog
def _cam():
    doc = adsk.core.Application.get().activeDocument
    return adsk.cam.CAM.cast(doc.products.itemByProductType('CAMProductType')) if doc else None


def _setups(cam):
    return [s for s in cam.setups if s.operationType == adsk.cam.OperationTypes.MillingOperation]


def _info(inputs, setups):
    i = inputs.itemById('setup').selectedItem.index if setups else -1
    box = inputs.itemById('info')
    if i < 0:
        box.formattedText = 'No milling setup yet: make a setup on the Lay Flat boards first.'
        return
    names, skipped = names_for(setups[i])
    t = '%d part name%s to engrave in this setup.' % (len(names), '' if len(names) == 1 else 's')
    if skipped:
        t += '<br>%d left out: standing up, or on the underside of their board (needs its own setup).' % skipped
    if not names and not skipped:
        t += '<br>Tick "Engrave part names" in NM Drawer / NM Cabinet (with Lay flat) to get names.'
    box.formattedText = t


class Created(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = args.command
            cmd.isExecutedWhenPreEmpted = False
            inputs = cmd.commandInputs
            cam = _cam()
            setups = _setups(cam) if cam else []
            d = inputs.addDropDownCommandInput('setup', 'Setup', adsk.core.DropDownStyles.TextListDropDownStyle)
            pick = next((i for i, s in enumerate(setups) if s.name == last['setup']), 0)
            for i, s in enumerate(setups):
                d.listItems.add(s.name, i == pick)
            d.tooltip = 'The setup whose boards get their names engraved (usually the Lay Flat copies).'
            ts = tools(cam) if cam else []
            cmd_tools[:] = ts
            t = inputs.addDropDownCommandInput('tool', 'V-bit', adsk.core.DropDownStyles.TextListDropDownStyle)
            pick = next((i for i, x in enumerate(ts) if x[0] == last['tool']), 0)
            for i, x in enumerate(ts):
                t.listItems.add(x[0], i == pick)
            t.tooltip = ('60 deg V-bits from this document and your tool libraries; the built-in one is a 1/2" 60 deg '
                         'V-bit with middle-of-the-road feeds: check them for your machine.')
            v = inputs.addValueInput('depth', 'Depth', 'mm', adsk.core.ValueInput.createByString(last['depth']))
            v.tooltip = 'How deep the V-bit goes. 0.5 mm with a 60 deg bit is a line about 0.6 mm wide.'
            inputs.addTextBoxCommandInput('info', '', '', 3, True).isFullWidth = True
            _info(inputs, setups)
            for ev, h in ((cmd.execute, Execute()), (cmd.inputChanged, Changed()), (cmd.validateInputs, Validate())):
                ev.add(h)
                nm.handlers.append(h)
        except Exception:
            nm.log('name trace dialog failed:\n' + traceback.format_exc())
            nm.ui.messageBox('NM Name Trace failed:\n' + traceback.format_exc())


cmd_tools = []


class Changed(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        try:
            if args.input.id == 'setup':
                cam = _cam()
                _info(args.input.parentCommand.commandInputs, _setups(cam) if cam else [])
        except Exception:
            nm.log('name trace dialog:\n' + traceback.format_exc())


class Validate(adsk.core.ValidateInputsEventHandler):
    def notify(self, args):
        try:
            inputs = args.inputs
            v = inputs.itemById('depth')
            args.areInputsValid = bool(inputs.itemById('setup').selectedItem) and v.isValidExpression and v.value > 0
        except Exception:
            args.areInputsValid = False


class Execute(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            inputs = args.command.commandInputs
            cam = _cam()
            setups = _setups(cam)
            setup = setups[inputs.itemById('setup').selectedItem.index]
            label, tool = cmd_tools[inputs.itemById('tool').selectedItem.index]
            depth = inputs.itemById('depth').expression
            last.update(setup=setup.name, tool=label, depth=depth)
            op, n, ch, skipped = make(setup, tool, depth)
            if op is None:
                nm.log('name trace: no names in %s (%d left out)' % (setup.name, skipped))
                nm.ui.messageBox('No part names to engrave in "%s".' % setup.name)
                return
            cam.generateToolpath(op)
            nm.log('name trace: %s / %s: %d names, %d strokes, %s, depth %s, %d left out'
                   % (setup.name, op.name, n, ch, label, depth, skipped))
        except Exception:
            nm.log('name trace failed:\n' + traceback.format_exc())
            nm.ui.messageBox('NM Name Trace failed:\n' + traceback.format_exc())


def register(mod):
    global nm
    nm = mod
    unregister(mod)
    c = nm.ui.commandDefinitions.addButtonDefinition(
        CMD_ID, 'NM Name Trace',
        'One Trace that engraves every part name (from "Engrave part names") on a setup\'s boards with a 60 deg V-bit. '
        'Run it again after a change to update it.',
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
