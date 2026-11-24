"""
Edit an NM Drawer / NM Cabinet after it was made.

Every drawer, bank of drawers or cabinet made from its dialog gets one extra item at the end of the timeline
("NM Drawer <name>" / "NM Cabinet <name>", a custom feature holding an empty base feature). It remembers the dialog
values, the user parameters and the components that were made. Double-click it and the same dialog opens, filled in:
- only sizes changed (and each one is a plain parameter) -> those parameters are set, nothing is rebuilt, so
  anything that refers to the boards (CAM, your own joints) stays;
- anything else (joints, layout, number of drawers, sections, ...) -> the old components and parameters are
  deleted and it is built again with the same parameter names, in the same place.
"""
import json, os, sys, traceback
import adsk.core, adsk.fusion

FEAT_ID = 'nmjMade'
EDIT_ID = 'nmjMadeEdit'
HERE = os.path.dirname(os.path.abspath(__file__))
MODULES = {'drawer': 'nm_drawer', 'cabinet': 'nm_cabinet'}
LABEL = {'drawer': 'NM Drawer', 'cabinet': 'NM Cabinet'}
TOL = 1e-3          # cm (0.01 mm): sizes closer than this are the same (inch values are rounded to 0.0001 in)
nm = None
definition = None


def mod(kind):
    return sys.modules[MODULES[kind]]


def builder(kind, o):
    M = mod(kind)
    if kind == 'cabinet':
        return M.build
    return M.build_bank if o['size'] == 1 and int(o['nd']) > 1 else M.build


def made(kind, o):
    """Builds from the dialog values o and adds the edit item. Returns what the build returned."""
    des = nm.design()
    root, up = des.rootComponent, des.userParameters
    pre = mod('drawer').unique_prefix(des, o['name'])     # the prefix the build is about to take
    p0 = {up.item(i).name for i in range(up.count)}
    n0 = root.occurrences.count
    res = builder(kind, o)(o)
    occs = [root.occurrences.item(i) for i in range(n0, root.occurrences.count)]
    params = [up.item(i).name for i in range(up.count) if up.item(i).name not in p0]
    try:
        main = (next((x for x in occs if x.component.name == o['name']), None)
                or next((x for x in occs if not x.component.name.startswith('Flat ')), occs[0]))
        feats = main.component.features
        cfi = feats.customFeatures.createInput(definition)
        bf = feats.baseFeatures.add()
        bf.startEdit()
        bf.finishEdit()
        bf.name = 'Settings'
        cfi.setStartAndEndFeatures(bf, bf)
        cf = feats.customFeatures.add(cfi)
        cf.name = '%s %s' % (LABEL[kind], o['name'])
        cv = cf.customNamedValues
        cv.addOrSetValue('kind', kind)
        cv.addOrSetValue('opts', json.dumps(o))
        cv.addOrSetValue('pre', pre)
        cv.addOrSetValue('params', json.dumps(params))
        cv.addOrSetValue('occs', json.dumps([x.name for x in occs]))
        cv.addOrSetValue('tokens', json.dumps([x.entityToken for x in occs]))   # still found after a rename
    except Exception:
        nm.log('edit item not made:\n' + traceback.format_exc())
    return res


def record(cf):
    cv = cf.customNamedValues
    try:
        tokens = json.loads(cv.value('tokens') or '[]')         # items made before 0.8.0 have no tokens
    except Exception:
        tokens = []
    return {'kind': cv.value('kind'), 'opts': json.loads(cv.value('opts')), 'pre': cv.value('pre'),
            'params': json.loads(cv.value('params')), 'occs': json.loads(cv.value('occs')), 'tokens': tokens}


def direct(up, name):
    """The user parameter when it holds a plain value (no other parameter in it), else None."""
    p = up.itemByName(name)
    return p if p and p.dependencyParameters.count == 0 else None


def current(rec):
    """The stored dialog values, with the sizes read back from the parameters (Change Parameters may have changed
    them since)."""
    up = nm.design().userParameters
    o, pre = dict(rec['opts']), rec['pre']
    M = mod(rec['kind'])
    inches = int(o.get('units', 0)) == 1

    def now(name):
        """A plain parameter: its expression. One that follows others (bt = {t}): its present value, so a later
        rebuild uses what the boards are now (and links bt to t again when they are equal)."""
        p = up.itemByName(name)
        if not p:
            return None
        if p.dependencyParameters.count == 0:
            return p.expression
        return mod('drawer').fmt(p.value * 10, inches)
    for k in M.VALUE_KEYS:
        e = now(pre + k)
        if e is not None and k in o:
            o[k] = e
    if rec['kind'] == 'cabinet':
        o['sections'] = [dict(s) for s in o['sections']]
        for i in range(int(o['ns']) - 1):
            e = now(pre + 's%d' % (i + 1))
            if e is not None:
                o['sections'][i]['sh'] = e
    return o


def size_changes(rec, old, new):
    """[(parameter, new expression)] when only sizes changed and each is a plain parameter; None = rebuild."""
    des = nm.design()
    up, um = des.userParameters, des.unitsManager
    pre, kind = rec['pre'], rec['kind']
    M = mod(kind)
    mm = lambda e: um.evaluateExpression(e, 'mm')

    def same(a, b):                             # '450 mm' and '17.7165 in' are the same size
        if a == b:
            return True
        try:
            return isinstance(a, str) and isinstance(b, str) and abs(mm(a) - mm(b)) < TOL
        except Exception:
            return False
    dflt = M.DEFAULTS                           # an item made before a setting existed had its default
    diff = [k for k in set(old) | set(new) if not k.startswith('_') and k != 'units'
            and not same(old.get(k, dflt.get(k)), new.get(k, dflt.get(k)))]
    out = []
    if kind == 'drawer':
        same_t = lambda o: abs(mm(o['bt']) - mm(o['t'])) < TOL
        if same_t(old) != same_t(new):
            return None
        skip = ({'w', 'd', 'h'} if new['size'] == 1 else set()) | ({'bt'} if same_t(new) else set())
    else:
        skip = {'sections'}
        g0, g1 = M.geom(old), M.geom(new)
        secs = M.sections(new)
        if len(M.sections(old)) != len(secs):
            return None
        for i, (a, b) in enumerate(zip(M.sections(old), secs)):
            sd = [k for k in set(a) | set(b) if not same(a.get(k), b.get(k))]
            if any(k != 'sh' for k in sd):
                return None
            if sd and i < len(secs) - 1:
                p = direct(up, pre + 's%d' % (i + 1))
                if not p:
                    return None
                out.append((p, b['sh']))
            if b['kind'] == 1 and M.door_count(a, g0) != M.door_count(b, g1):
                return None                     # Auto doors: one became two or the other way round
        slides = [s for s in secs if s['kind'] == 0 and not mod('drawer').SLIDES[s['slide']].get('none')]
        if slides and abs(g0['id'] - g1['id']) > 0.01:
            return None                         # the slide length was picked from the inside depth (d, bk, bin, t)
    for k in diff:
        if k in skip:
            continue
        if k not in M.VALUE_KEYS:
            return None
        p = direct(up, pre + k)
        if not p:
            return None
        out.append((p, new[k]))
    return out


def rebuild(rec, new):
    des = nm.design()
    root, up = des.rootComponent, des.userParameters
    tokens = rec.get('tokens') or []
    found = []
    for i, n in enumerate(rec['occs']):
        occ = None
        if i < len(tokens):
            try:
                hits = des.findEntityByToken(tokens[i])
                occ = adsk.fusion.Occurrence.cast(hits[0]) if hits else None
            except Exception:
                occ = None
        if not occ or not occ.isValid:
            occ = root.occurrences.itemByName(n)
        found.append(occ)
    place = [occ.transform2 if occ else None for occ in found]      # same order as the build makes them
    memo = {}                                   # per joint settings you changed (NM Box edit): put back after
    for occ in found:
        if not occ:
            continue
        try:
            comps = [occ.component] + [occ.component.allOccurrences.item(i).component
                                       for i in range(occ.component.allOccurrences.count)]
            for c in comps:
                nm.joint_memo(c, memo)
        except Exception:
            nm.log('edit: joint settings not read:\n' + traceback.format_exc())
    for occ in found:
        if occ:
            occ.deleteMe()
    left = [n for n in rec['params']]
    for _ in range(len(left) + 1):              # parameters that others use go last
        keep = []
        for n in left:
            p = up.itemByName(n)
            try:
                if p and not p.deleteMe():
                    keep.append(n)
            except Exception:
                keep.append(n)
        if len(keep) == len(left):
            break
        left = keep
    if left:
        nm.log('edit: parameters still in use elsewhere, kept: %s' % ', '.join(left))
    n0 = root.occurrences.count
    nm.carry.clear()
    nm.carry.update(memo)
    nm.carry_used.clear()
    del nm.carry_failed[:]
    try:
        made(rec['kind'], new)
    finally:
        lost = ['%s: %s' % (k[0], ' / '.join(sorted(k[1]))) for k in memo if k not in nm.carry_used]
        lost = [x for x in lost if not any(f.startswith(x + ' (') for f in nm.carry_failed)] + list(nm.carry_failed)
        nm.carry.clear()
        nm.carry_used.clear()
        del nm.carry_failed[:]
    if memo:
        nm.log('edit: own joint settings put back on %d of %d joints' % (len(memo) - len(lost), len(memo)))
    moved = False
    for i in range(n0, root.occurrences.count):
        tf = place[i - n0] if i - n0 < len(place) else None
        if tf and not tf.isEqualTo(adsk.core.Matrix3D.create()):
            root.occurrences.item(i).transform2 = tf
            moved = True
    if moved and des.designType == adsk.fusion.DesignTypes.ParametricDesignType:
        try:
            if des.snapshots.hasPendingSnapshot:
                des.snapshots.add()             # capture the position, or the next recompute moves it back
        except Exception:
            nm.log('edit: position not captured:\n' + traceback.format_exc())
    return lost


def apply(cf, new):
    """Applies the edited dialog values. Returns 'sizes' or 'rebuilt'."""
    rec = record(cf)
    old = current(rec)
    ch = size_changes(rec, old, new)
    if ch is not None:
        if ch:
            try:                                # one recompute for all of them
                nm.design().modifyParameters([p for p, _ in ch], [adsk.core.ValueInput.createByString(e) for _, e in ch])
            except Exception:
                for p, e in ch:
                    p.expression = e
        cf.customNamedValues.addOrSetValue('opts', json.dumps(new))
        return 'sizes'
    lost = rebuild(rec, new)
    if lost:
        nm.log('edit: own joint settings not put back: %s' % '; '.join(lost))
        nm.ui.messageBox('Rebuilt. These joints had their own settings (NM Box edit) that could not be put back, '
                         'because those boards no longer meet or the settings no longer fit:\n\n%s\n\n'
                         'They use the drawer / cabinet settings now; double-click the NM Box item to change them '
                         'again.' % '\n'.join(lost), 'NM Edit')
    return 'rebuilt'


class EditExecute(adsk.core.CommandEventHandler):
    def __init__(self, cf, kind):
        super().__init__()
        self.cf, self.kind = cf, kind

    def notify(self, args):
        try:
            M = mod(self.kind)
            o = M.read(args.command.commandInputs)
            bad = M.check(o)
            if bad:
                nm.ui.messageBox('\n'.join(bad), LABEL[self.kind])
                return
            r = apply(self.cf, o)
            nm.log('edit %s %s: %s' % (self.kind, o['name'], r))
        except Exception:
            nm.log('edit failed:\n' + traceback.format_exc())
            nm.ui.messageBox('%s edit failed:\n%s' % (LABEL.get(self.kind, 'NM'), traceback.format_exc()))


class EditCreated(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cf = adsk.fusion.CustomFeature.cast(nm.ui.activeSelections.item(0).entity)
            rec = record(cf)
            kind = rec['kind']
            M = mod(kind)
            cmd = args.command
            cmd.isExecutedWhenPreEmpted = False      # starting another command = Cancel, not OK (an auto-OK mid-build crashed Fusion)
            cmd.setDialogInitialSize(380, 680)
            if hasattr(M, 'note'):
                M.note = ''
            M.add_inputs(cmd.commandInputs, M.upgrade(current(rec)))
            for ev, h in ((cmd.execute, EditExecute(cf, kind)), (cmd.inputChanged, M.Changed()),
                          (cmd.validateInputs, M.Validate())):
                ev.add(h)
                nm.handlers.append(h)
        except Exception:
            nm.ui.messageBox('Edit failed:\n' + traceback.format_exc())


class Compute(adsk.fusion.CustomFeatureEventHandler):
    def notify(self, args):
        pass                                    # nothing to compute: the item only holds the settings


def register(mod_):
    global nm, definition
    nm = mod_
    defs = nm.ui.commandDefinitions
    old = defs.itemById(EDIT_ID)
    if old:
        old.deleteMe()
    e = defs.addButtonDefinition(EDIT_ID, 'Edit NM Drawer / Cabinet', '', os.path.join(HERE, 'resources', 'edit'))
    h = EditCreated()
    e.commandCreated.add(h)
    nm.handlers.append(h)
    definition = adsk.fusion.CustomFeatureDefinition.create(FEAT_ID, 'NM Drawer / Cabinet',
                                                            os.path.join(HERE, 'resources', 'create'))
    definition.editCommandId = EDIT_ID
    h = Compute()
    definition.customFeatureCompute.add(h)
    nm.handlers.append(h)


def unregister(mod_):
    d = mod_.ui.commandDefinitions.itemById(EDIT_ID)
    if d:
        d.deleteMe()
