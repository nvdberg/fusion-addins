# NM Joinery - Fusion add-in (clean-room).
# One command, "NM Joint": select 2 or more boards; every pair that overlaps (box corner) or touches
# (end against face) gets a joint. Each joint is a Custom Feature in the timeline:
#   - double-click it to edit in the dialog
#   - its numbers live in Change Parameters (per joint) and follow the global nmj_bit / nmj_gap
#   - it recomputes by itself when a board changes size
import adsk.core, adsk.fusion, traceback, os, sys, json, glob, itertools, importlib

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import joint_core as jc
importlib.reload(jc)

FEAT_ID = 'NMWoodworks.JointT2'
CREATE_ID = 'nmjCreateJoint'
EDIT_ID = 'nmjEditJoint'
PANEL_ID = 'SolidModifyPanel'
TOOL_ORDER = ('cutA', 'joinB', 'cutB')
GLOBALS = (('nmj_bit', '6.35 mm', 'NM Joinery: default bit diameter (all joints that use nmj_bit)'),
           ('nmj_gap', '0.1 mm', 'NM Joinery: default clearance per side (all joints that use nmj_gap)'))
# id, label (Change Parameters), units, default expression
PARAMS = [
    ('gap', 'Clearance per side', 'mm', 'nmj_gap'),
    ('bit_d', 'Bit diameter', 'mm', 'nmj_bit'),
    ('relief', 'Corner relief 0 none / 1 dogbone / 2 rounded / 3 T-bone sideways / 4 T-bone deep', '', '1'),
    ('count', 'Fingers or tabs (0 = auto)', '', '0'),
    ('finger_w', 'Target finger width (0 = auto)', 'mm', '0 mm'),
    ('flip', 'Flip 0 / 1', '', '0'),
    ('depth', 'Depth (0 = through)', 'mm', '0 mm'),
    ('tenon_t', 'Tenon thickness (0 = full board; M&T 0 = auto)', 'mm', '0 mm'),
    ('tab_len', 'Tab / tenon width (0 = auto)', 'mm', '0 mm'),
    ('end_off', 'End offset / shoulder (M&T 0 = auto)', 'mm', '0 mm'),
    ('style', 'Joint type 0 fingers-tabs / 1 mortise & tenon', '', '0'),
    ('end_gap', 'M&T glue room at tenon end (blind)', 'mm', '1 mm'),
    ('mt_space', 'M&T spacing 0 auto / 1 even / 2 fixed gap', '', '0'),
    ('mt_gap', 'M&T fixed gap between tenons', 'mm', '10 mm'),
]
DEFAULT_EXPR = {p[0]: p[3] for p in PARAMS}
RELIEF_NAMES = ['None (square)', 'Dogbones', 'Rounded (M&T and tabs)', 'T-bones sideways', 'T-bones deep']
STYLE_NAMES = ['Fingers / tabs (auto)', 'Mortise & tenon']
SPACE_NAMES = ['Auto (gap = half a tenon)', 'Even (gap = tenon)', 'Fixed gap']
# dialog: short labels (Fusion cuts labels after ~8 characters), the explanation goes in the tooltip
LABELS = {
    'style': ('Joint', 'Fingers / tabs: picked from how the boards meet (overlapping corner = fingers, '
                       'end touching a face = tabs). Mortise & tenon: end-on-face joints only.'),
    'bit': ('Bit', 'The bit that cuts the joint: sets the dogbone / rounding size and the narrowest slot.'),
    'bit_custom': ('Bit dia', 'Custom bit diameter.'),
    'gap': ('Gap', 'Clearance per side of every finger, tab or tenon. Arrows step 0.05 mm. '
                   'Joint too tight after cutting: make it bigger; too loose: smaller.'),
    'gap_global': ('Global', 'Ticked: this joint uses the global nmj_gap (Modify > Change Parameters), shared by all '
                             'joints that are ticked. Change the Gap number to set this joint on its own.'),
    'relief': ('Corners', 'Inside corners a round bit leaves. Dogbones: the bit goes into the corner diagonally. '
                          'T-bones: the round only goes one way, so it hides better: sideways = along the joint into '
                          'the next finger, deep = further into the board. Rounded: rounded mortise ends and tenons '
                          '(finger joints then get dogbones).'),
    'count': ('Count', 'Number of fingers, tabs or tenons. 0 = auto.'),
    'finger_w': ('Width', 'Target finger / tab width. 0 = auto (2 x the board thickness).'),
    'flip': ('Flip', 'Swap which board gets the end fingers (corner), or put tabs at the ends (end-on-face).'),
    'depth': ('Depth', 'How far tabs / tenons go into the other board. 0 = through (its full thickness).'),
    'tenon_t': ('Thick', 'Tenon thickness. 0 = auto: tabs use the full board, M&T uses 1/3 of the board '
                         '(at least the bit).'),
    'tab_len': ('Length', 'Length of each tab / tenon along the joint. 0 = auto.'),
    'end_off': ('Ends', 'Distance kept free at both ends of the joint (M&T shoulders). 0 = auto '
                        '(M&T: the tenon thickness, at least 6 mm).'),
    'mt_space': ('Spacing', 'Gaps between tenons. Auto = half a tenon, Even = as wide as a tenon, '
                            'Fixed = the Gap value (the group is centred).'),
    'mt_gap': ('Between', 'Fixed space between tenons.'),
    'end_gap': ('Glue', 'Blind M&T: the mortise is this much deeper than the tenon.'),
    'which': ('Edit', 'All joints: the settings of the whole box. Pick one joint to see its real count and sizes '
                      'and give it its own (type, bit, gap and corners stay shared).'),
    'reset': ('Reset', 'Put every setting back to how it was when this dialog opened.'),
    'whole': ('Whole box', 'Ticked: click one board and every board of the box is picked too (all visible boards '
                           'in that component that touch it, directly or through other boards). '
                           'An open drawer (bottom + 4 sides) gets its 8 joints in one go.'),
}

whole_box_on = [False]   # the Whole box tick is remembered while Fusion runs

# edit dialog: fields that can be automatic show the real size; they stay automatic until you change them
AUTO_KEYS = ('count', 'finger_w', 'depth', 'tenon_t', 'tab_len', 'end_off')
# whole box: settings one joint can have on its own (the rest - type, bit, gap, corners - are shared by the box)
JOINT_KEYS = ('count', 'finger_w', 'flip', 'depth', 'tenon_t', 'tab_len', 'end_off', 'mt_space', 'mt_gap', 'end_gap')
SHARED_INPUTS = ('style', 'bit', 'bit_custom', 'gap', 'gap_global', 'relief')


def tip(inp):
    inp.tooltip = LABELS[inp.id][1]
    return inp

app = adsk.core.Application.get()
ui = app.userInterface
handlers = []
definition = None
edit_state = {}
HEAL_ID = 'NMJ_heal'
heal = {'pending': False, 'busy': False}


def design():
    return adsk.fusion.Design.cast(app.activeProduct)


def log(msg):
    """Text Commands panel + nmj_log.txt next to the add-in (never a blocking dialog)."""
    try:
        app.log('NMJoinery: ' + msg)
    except Exception:
        pass
    try:
        import datetime
        with open(os.path.join(HERE, 'nmj_log.txt'), 'a', encoding='utf-8') as f:
            f.write('%s  %s\n' % (datetime.datetime.now().isoformat(timespec='seconds'), msg))
    except Exception:
        pass


# ----------------------------------------------------------------------------------------------- bits
def library_bits():
    """Flat end mills from the 'NM Shop Library' tool library, grouped by diameter (cm)."""
    roots = [os.path.expanduser('~/Library/Application Support/Autodesk/Autodesk Fusion 360'),
             os.path.join(os.environ.get('APPDATA', ''), 'Autodesk', 'Autodesk Fusion 360')]
    files = []
    for r in roots:
        files += glob.glob(os.path.join(r, '*', 'W.login', 'M2', '*', 'CAMTools', 'NM Shop Library*.json'))
    by_d = {}
    for f in sorted(files, key=os.path.getmtime, reverse=True)[:1]:
        try:
            data = json.load(open(f, encoding='utf-8'))['data']
        except Exception:
            continue
        for t in data:
            if t.get('type') != 'flat end mill':
                continue
            dc = t['geometry']['DC']
            d_cm = dc * 2.54 if t.get('unit', 'inches') == 'inches' else dc / 10.0
            if d_cm > 2.6:          # skip spoilboard surfacers
                continue
            key = round(d_cm, 4)
            by_d.setdefault(key, []).append(t['post-process']['number'])
    return sorted((d, sorted(n)) for d, n in by_d.items())


def frac(d_cm):
    inch = d_cm / 2.54
    for den in (2, 4, 8, 16, 32):
        if abs(inch * den - round(inch * den)) < 1e-3:
            n = int(round(inch * den))
            from math import gcd
            g = gcd(n, den)
            return '%d/%d"' % (n // g, den // g) if den // g > 1 else '%d"' % (n // g)
    return '%.3f"' % inch


# ----------------------------------------------------------------------------------------------- joints
def ensure_globals(des):
    up = des.userParameters
    for name, val, comment in GLOBALS:
        if not up.itemByName(name):
            up.add(name, adsk.core.ValueInput.createByString(val), 'mm', comment)


def spec_from_exprs(exprs):
    um = design().unitsManager
    return {pid: um.evaluateExpression(exprs[pid], units) for pid, _, units, _ in PARAMS}


def fparam(cf, pid):
    # itemById raises (not None) for an id the feature does not have, e.g. a joint from an older version
    try:
        return cf.parameters.itemById(pid)
    except Exception:
        return None


def spec_from_feature(cf):
    # joints made by an older version lack the newer parameters: use the defaults for those
    out = {}
    for pid, _, units, dflt in PARAMS:
        p = fparam(cf, pid)
        out[pid] = p.value if p else design().unitsManager.evaluateExpression(dflt, units)
    return out


def exprs_from_feature(cf):
    out = {}
    for pid in DEFAULT_EXPR:
        p = fparam(cf, pid)
        out[pid] = p.expression if p else DEFAULT_EXPR[pid]
    return out


def joint_kind(info):
    if info['mode'] == 'corner':
        return 'Fingers'
    return 'M&T' if info.get('style') == jc.STYLE_MT else 'Tabs'


def context_for(a, b):
    """Component to build in + the bodies in that component's space."""
    ca, cb = a.assemblyContext, b.assemblyContext
    if (ca is None and cb is None):
        return a.parentComponent, a, b, None
    if ca and cb and ca.fullPathName == cb.fullPathName:
        return ca.component, a.nativeObject, b.nativeObject, ca
    return design().rootComponent, a, b, None


def dep_body(cf, key):
    """Dependency board, back in the feature's own component space."""
    e = adsk.fusion.BRepBody.cast(cf.dependencies.itemById(key).entity)
    return e.nativeObject if e.assemblyContext else e


def board(cf, ab):
    """Board A/B as it is just before this joint: dependency if there is one, else the stored entity token."""
    d = cf.dependencies.itemById('board' + ab)
    if d:
        return dep_body(cf, 'board' + ab)
    nv = cf.customNamedValues
    if not nv.isExistingValue('tok' + ab):
        return None
    ents = design().findEntityByToken(nv.value('tok' + ab))
    return adsk.fusion.BRepBody.cast(ents[0]) if ents else None


MAX_WATCH = 16          # hidden watch parameters per joint


def _profile_sketches(f):
    prof = getattr(f, 'profile', None)
    if prof is None:
        return []
    items = [prof.item(i) for i in range(prof.count)] if isinstance(prof, adsk.core.ObjectCollection) else [prof]
    out = []
    for p in items:
        sk = getattr(adsk.fusion.Profile.cast(p), 'parentSketch', None) if adsk.fusion.Profile.cast(p) else None
        if sk and sk not in out:
            out.append(sk)
    return out


def moved_from(des, native, same, before, comps):
    """The board was moved to another component (Fusion: CutPasteBody). The features that made it then list no
    bodies, and the original body can only be reached by rolling the timeline back, so take every feature before
    the move whose bodies have all gone (moved away): they made this board or one moved with it."""
    tl = des.timeline
    last = -1
    for i in range(tl.count):
        e = tl.item(i).entity
        if e and e.objectType.endswith('CutPasteBody') and before(e):
            try:
                bs = e.bodies
                if any(same(bs.item(j)) for j in range(bs.count)):
                    last = i
            except Exception:
                pass
    if last < 0:
        return []
    out = []
    for comp in comps:
        for i in range(comp.features.count):
            f = comp.features.item(i)
            try:
                if f.timelineObject.index >= last or not _profile_sketches(f) or f.bodies.count:
                    continue
            except Exception:
                continue
            out.append(f)
    return out


def upstream(body):
    """What a board is made from, for change tracking: (sketches, model parameters).
    Fusion only fires the compute event for changed sketches and for our own parameters, so
    the boards' sketches become dependencies and every parameter of the features that made or
    modified the board (and of their sketch planes) gets a hidden 'watch' parameter that refers to it.
    The board itself can't be a dependency: this joint cuts it, which Fusion sees as a loop.
    The features can live in another component than the board (e.g. drawn in the root, then the
    bodies moved into a component), so every component is searched."""
    native = body.nativeObject if body.assemblyContext else body
    des = design()
    marker = des.timeline.markerPosition
    tok = native.entityToken

    def before(x):
        try:
            return x.timelineObject.index < marker
        except Exception:
            return False

    def same(b):
        try:
            return b == native or b.entityToken == tok
        except Exception:
            return False
    comps = [native.parentComponent] + [c for c in des.allComponents if c != native.parentComponent]
    feats = []
    for comp in comps:
        for i in range(comp.features.count):
            f = comp.features.item(i)
            if not before(f):
                continue
            ot = f.objectType
            if ot.endswith(('CustomFeature', 'CombineFeature', 'BaseFeature')):
                continue
            try:
                bodies = f.bodies
            except Exception:
                continue
            if any(same(bodies.item(j)) for j in range(bodies.count)):
                feats.append(f)
    moved = [f for f in feats if f.objectType.endswith('CutPasteBody')]
    if moved:                                     # the board was moved here from another component
        feats = [f for f in feats if f not in moved] + moved_from(des, native, same, before, comps)
    sketches, owners = [], list(feats)
    for f in feats:
        for sk in _profile_sketches(f):
            if sk not in sketches:
                sketches.append(sk)
            pl = adsk.fusion.ConstructionPlane.cast(sk.referencePlane)
            if pl and pl not in owners and before(pl):
                owners.append(pl)
    params = []
    for comp in comps:
        for i in range(comp.modelParameters.count):
            p = comp.modelParameters.item(i)
            try:
                if p.createdBy in owners and p not in params:
                    params.append(p)
            except Exception:
                pass
    return sketches, params


def make_joint(comp, a, b, exprs, fixed=False, occ=None):
    """One joint between two boards (native bodies of comp)."""
    cf, infos = make_group(comp, [a, b], [(0, 1)], exprs, fixed)
    return cf, infos[0]


MAX_WATCH_GROUP = 64    # a whole box watches more parameters (5 boards)


def same_body(x, y):
    try:
        return x == y or x.entityToken == y.entityToken
    except Exception:
        return False


def group_tools(boards, pidx, spec, fixed, pre=None):
    """Tool bodies for several joints at once, merged per board.
    Returns (infos, roles, ops): roles = [(ia, ib)] as built (A gets cut, B gets the tabs),
    ops = [(board index, 'join'|'cut', tool body)], per board the join first, then one cut with every slot
    and dogbone (a later cut also clears tab material that would sit in a slot).
    Why one feature: when a board gets a 3rd separate join (a drawer bottom with tabs on 4 sides), Fusion loses
    that combine's target body after a dimension change ('target body is lost'), even if nothing in the joint
    changed. With everything in one feature each board gets at most one join and one cut."""
    infos, roles, cut, join = [], [], {}, {}
    for j, (ia, ib) in enumerate(pidx):
        sp = spec[j] if isinstance(spec, list) else spec
        info, tools = (pre or {}).get((ia, ib)) or jc.build_tools(boards[ia], boards[ib], sp, fixed)
        if not same_body(info['A'], boards[ia]):
            ia, ib = ib, ia
        infos.append(info)
        roles.append((ia, ib))
        for i, key, store in ((ia, 'cutA', cut), (ib, 'cutB', cut), (ib, 'joinB', join)):
            if tools[key]:
                store.setdefault(i, []).append(tools[key])
    ops = []
    for i in range(len(boards)):
        if i in join:
            ops.append((i, 'join', jc.union(join[i])))
        if i in cut:
            ops.append((i, 'cut', jc.union(cut[i])))
    return infos, roles, ops


def ops_key(ops):
    return json.dumps([[i, op] for i, op, _ in ops])


def group_name(comp, boards, infos):
    if len(infos) == 1:
        return 'NM %s %s-%s' % (joint_kind(infos[0]), infos[0]['A'].name, infos[0]['B'].name)
    return 'NM Box %s (%d joints)' % (comp.name, len(infos))


def joint_specs(exprs, over, n):
    return [spec_from_exprs(dict(exprs, **over.get(j, {}))) for j in range(n)]


def clean_over(over, exprs):
    """Own values of each joint, only where they differ from the box setting."""
    um = design().unitsManager
    units = {p[0]: p[2] for p in PARAMS}
    out = {}
    for j, d in (over or {}).items():
        keep = {}
        for k, e in d.items():
            try:
                same = abs(um.evaluateExpression(e, units[k]) - um.evaluateExpression(exprs[k], units[k])) < 1e-7
            except Exception:
                same = e.replace(' ', '') == exprs[k].replace(' ', '')
            if not same:
                keep[k] = e
        if keep:
            out[int(j)] = keep
    return out


def make_group(comp, boards, pidx, exprs, fixed=False, pre=None, over=None):
    """One NM Joint custom feature for one or more joints between these boards (native bodies of comp):
    a base feature with one tool body per board operation + one combine per operation.
    over = {joint index: {key: expression}}: joints of a box with their own count / sizes."""
    over = clean_over(over, exprs)
    infos, roles, ops = group_tools(boards, pidx, joint_specs(exprs, over, len(pidx)), fixed, pre)
    feats = comp.features
    cfi = feats.customFeatures.createInput(definition)
    for pid, label, units, _ in PARAMS:
        cfi.addCustomParameter(pid, label, adsk.core.ValueInput.createByString(exprs[pid]), units, True)
    plabel = {p[0]: (p[1], p[2]) for p in PARAMS}
    for j in sorted(over):
        for k in JOINT_KEYS:
            if k in over[j]:
                cfi.addCustomParameter('j%d_%s' % (j, k), '%s-%s: %s' % (boards[roles[j][0]].name, boards[roles[j][1]].name,
                                       plabel[k][0]), adsk.core.ValueInput.createByString(over[j][k]), plabel[k][1], True)
    nw, ns = 0, 0
    cap = MAX_WATCH if len(boards) <= 2 else MAX_WATCH_GROUP
    seen_sk, seen_p = set(), set()
    for bi, body in enumerate(boards):
        sketches, params = upstream(body)
        ctx = body.assemblyContext
        sketches = [sk for sk in sketches if sk.entityToken not in seen_sk]
        seen_sk.update(sk.entityToken for sk in sketches)
        params = [p for p in params if p.name not in seen_p]
        seen_p.update(p.name for p in params)
        for sk in sketches:
            try:
                if cfi.addDependency('sk%d_%d' % (bi, ns), sk.createForAssemblyContext(ctx) if ctx else sk):
                    ns += 1
            except Exception as e:
                log('sketch dependency %s skipped: %s' % (sk.name, e))
        for p in params:
            if nw >= cap:
                log('more than %d parameters to watch, %s not watched' % (cap, p.name))
                break
            try:
                cfi.addCustomParameter('w%d' % nw, 'watch %s' % p.name,
                                       adsk.core.ValueInput.createByString(p.name), p.unit, False)
                nw += 1
            except Exception as e:
                log('watch %s skipped: %s' % (p.name, e))
    bf = feats.baseFeatures.add()
    bf.startEdit()
    for _, _, tool in ops:
        comp.bRepBodies.add(tool, bf)
    bf.finishEdit()
    bf.name = 'NMJ tools'
    tbs = [bf.bodies.item(i) for i in range(bf.bodies.count)]
    last = bf
    for (i, op, _), tb in zip(ops, tbs):
        tb.name = 'NMJ %s %s' % (op, boards[i].name)
        coll = adsk.core.ObjectCollection.create()
        coll.add(tb)
        ci = feats.combineFeatures.createInput(boards[i], coll)
        ci.operation = (adsk.fusion.FeatureOperations.JoinFeatureOperation if op == 'join'
                        else adsk.fusion.FeatureOperations.CutFeatureOperation)
        ci.isKeepToolBodies = False
        last = feats.combineFeatures.add(ci)
    cfi.setStartAndEndFeatures(bf, last)
    cf = feats.customFeatures.add(cfi)
    nv = cf.customNamedValues
    nv.addOrSetValue('boards', json.dumps([b.entityToken for b in boards]))
    nv.addOrSetValue('pairs', json.dumps(roles))
    nv.addOrSetValue('ops', ops_key(ops))
    nv.addOrSetValue('over', json.dumps({str(j): sorted(d) for j, d in over.items()}))
    nv.addOrSetValue('mode', infos[0]['mode'] if len(infos) == 1 else 'box')
    nv.addOrSetValue('tokA', boards[roles[0][0]].entityToken)       # first joint, for board()
    nv.addOrSetValue('tokB', boards[roles[0][1]].entityToken)
    log('joint %s: %d joints, %d sketch dependencies, %d watched parameters' % (cf.name, len(infos), ns, nw))
    try:
        cf.name = group_name(comp, boards, infos)
    except Exception:
        pass
    return cf, infos


def is_group(cf):
    return cf.customNamedValues.isExistingValue('ops')


def over_keys(cf):
    nv = cf.customNamedValues
    return {int(j): ks for j, ks in json.loads(nv.value('over')).items()} if nv.isExistingValue('over') else {}


def group_over(cf):
    """{joint index: {key: expression}} of the joints with their own settings."""
    out = {}
    for j, ks in over_keys(cf).items():
        d = {k: fparam(cf, 'j%d_%s' % (j, k)).expression for k in ks if fparam(cf, 'j%d_%s' % (j, k))}
        if d:
            out[j] = d
    return out


def group_specs(cf, n):
    shared = spec_from_feature(cf)
    out = []
    for j in range(n):
        s = dict(shared)
        for k in over_keys(cf).get(j, []):
            p = fparam(cf, 'j%d_%s' % (j, k))
            if p:
                s[k] = p.value
        out.append(s)
    return out


def group_boards(cf):
    out = []
    for t in json.loads(cf.customNamedValues.value('boards')):
        ents = design().findEntityByToken(t)
        out.append(adsk.fusion.BRepBody.cast(ents[0]) if ents else None)
    return out


def touching(a, b, tol=0.01):
    p, q = a.boundingBox, b.boundingBox
    return all(getattr(p.minPoint, c) <= getattr(q.maxPoint, c) + tol and
               getattr(q.minPoint, c) <= getattr(p.maxPoint, c) + tol for c in 'xyz')


def describe(info):
    a, b = info['A'].name, info['B'].name
    if info['mode'] == 'corner':
        s = '%s / %s: %d fingers of %.1f mm (corner)' % (a, b, info['segments'], info['width_mm'])
    elif info.get('style') == jc.STYLE_MT:
        s = '%s <- %s: %d tenon%s %.1f x %.1f mm, %s %.1f mm, shoulders %.1f mm' % (
            a, b, info['tabs_or_fingers'], 's' if info['tabs_or_fingers'] > 1 else '', info['width_mm'],
            info['tenon_t_mm'], 'through' if info['through'] else 'blind', info['depth_mm'], info['shoulder_mm'])
        if not info['through']:
            s += ', mortise +%.1f mm' % info['end_gap_mm']
    else:
        s = '%s <- %s: %d tabs of %.1f mm, %.1f mm deep' % (a, b, info['tabs_or_fingers'], info['width_mm'], info['depth_mm'])
    if info['notes']:
        s += '  ! ' + '; '.join(info['notes'])
    return s


def body_key(b):
    native = b.nativeObject if b.assemblyContext else b
    return (native.entityToken, b.assemblyContext.fullPathName if b.assemblyContext else '')


def whole_box(bodies):
    """The selected boards plus every visible solid board of the same component (same occurrence) that touches
    them, directly or through other boards: one click picks the whole box."""
    found = {body_key(b): b for b in bodies}
    cands = []
    for seed in bodies:
        occ = seed.assemblyContext
        native = seed.nativeObject if occ else seed
        for i in range(native.parentComponent.bRepBodies.count):
            nb = native.parentComponent.bRepBodies.item(i)
            p = nb.createForAssemblyContext(occ) if occ else nb
            k = body_key(p)
            if k not in found and nb.isSolid and p.isVisible and all(k != body_key(c) for c in cands):
                cands.append(p)
    todo = list(bodies)
    while todo:
        x = todo.pop()
        for c in list(cands):
            if touching(x, c):
                cands.remove(c)
                found[body_key(c)] = c
                todo.append(c)
    return list(found.values())


def create_all(bodies, exprs):
    """Every touching / overlapping pair gets a joint; all joints between boards of one component go into one
    feature (see group_tools for why)."""
    ensure_globals(design())
    lines, made = [], 0
    groups = {}                                 # (component, occurrence path) -> (comp, boards, pairs)
    for a, b in itertools.combinations(bodies, 2):
        if not touching(a, b):
            continue
        comp, na, nb, occ = context_for(a, b)
        key = (comp.entityToken, occ.fullPathName if occ else '')
        g = groups.setdefault(key, (comp, [], []))
        idx = []
        for nbody in (na, nb):
            i = next((k for k, x in enumerate(g[1]) if same_body(x, nbody)), None)
            if i is None:
                g[1].append(nbody)
                i = len(g[1]) - 1
            idx.append(i)
        g[2].append(tuple(idx))
    spec = spec_from_exprs(exprs)
    for comp, boards, pidx in groups.values():
        good, built = [], {}
        for ia, ib in pidx:                     # drop pairs whose boxes touch but the boards don't
            try:
                built[(ia, ib)] = jc.build_tools(boards[ia], boards[ib], spec, False)
                good.append((ia, ib))
            except jc.JointError as e:
                if 'neither overlap nor touch' not in str(e):
                    lines.append('%s / %s: %s' % (boards[ia].name, boards[ib].name, e))
        if not good:
            continue
        used = sorted({i for p in good for i in p})
        boards2 = [boards[i] for i in used]
        pidx2 = [(used.index(ia), used.index(ib)) for ia, ib in good]
        pre = {(used.index(ia), used.index(ib)): built[(ia, ib)] for ia, ib in good}
        try:
            cf, infos = make_group(comp, boards2, pidx2, exprs, pre=pre)
            lines += [describe(info) for info in infos]
            made += len(infos)
        except jc.JointError as e:
            lines.append(str(e))
    if not made:
        lines.insert(0, 'No joints: the selected boards do not overlap or touch.')
    return made, lines


# ----------------------------------------------------------------------------------------------- dialog
def add_inputs(inputs, exprs, with_selection):
    L_ = lambda k: LABELS[k][0]
    if with_selection:
        sel = inputs.addSelectionInput('bodies', 'Boards', 'Select 2 or more boards (or 1 with Whole box ticked). Every overlapping or touching pair gets a joint.')
        sel.addSelectionFilter('SolidBodies')
        sel.setSelectionLimits(1 if whole_box_on[0] else 2, 0)
        tip(inputs.addBoolValueInput('whole', L_('whole'), True, '', whole_box_on[0]))
    L = lambda k: LABELS[k][0]
    st = tip(inputs.addDropDownCommandInput('style', L('style'), adsk.core.DropDownStyles.TextListDropDownStyle))
    mt = int(float(exprs['style'])) == 1
    for i, n in enumerate(STYLE_NAMES):
        st.listItems.add(n, i == int(mt))
    bits = library_bits()
    dd = inputs.addDropDownCommandInput('bit', L('bit'), adsk.core.DropDownStyles.TextListDropDownStyle)
    dd.tooltip = LABELS['bit'][1]
    des = design()
    gb = des.userParameters.itemByName('nmj_bit')
    dd.listItems.add('Global nmj_bit (%s)' % (gb.expression if gb else '6.35 mm'), True)
    for d, nums in bits:
        dd.listItems.add('%s  %.2f mm   T%s' % (frac(d), d * 10, ' T'.join(str(n) for n in nums)), False)
    dd.listItems.add('Custom', False)
    edit_state['bits'] = bits
    cust = tip(inputs.addValueInput('bit_custom', L('bit_custom'), 'mm', adsk.core.ValueInput.createByString('6.35 mm')))
    cust.isVisible = False
    e = exprs['bit_d']
    if e.strip() != 'nmj_bit':
        try:
            v = des.unitsManager.evaluateExpression(e, 'mm')
        except Exception:
            v = None
        idx = next((i for i, (d, _) in enumerate(bits) if v is not None and abs(d - v) < 1e-4), None)
        if idx is not None and e.replace(' ', '').endswith('mm'):
            dd.listItems.item(idx + 1).isSelected = True
        else:
            dd.listItems.item(dd.listItems.count - 1).isSelected = True
            cust.expression = e
            cust.isVisible = True
    ge = exprs['gap']
    glob = ge.replace(' ', '') == 'nmj_gap'
    try:
        gv = des.unitsManager.evaluateExpression(ge, 'mm')
    except Exception:
        gv = 0.01
    # spinner limits/step/start are in the given unit (mm); .value reads back in cm like every other input
    gs = tip(inputs.addFloatSpinnerCommandInput('gap', L('gap'), 'mm', 0, 2, 0.05, round(gv * 10, 4)))
    if not glob:
        try:
            gs.expression = ge
        except Exception:
            pass
    tip(inputs.addBoolValueInput('gap_global', L('gap_global'), True, '', glob))
    rl = tip(inputs.addDropDownCommandInput('relief', L('relief'), adsk.core.DropDownStyles.TextListDropDownStyle))
    for i, n in enumerate(RELIEF_NAMES):
        rl.listItems.add(n, str(int(float(exprs['relief']))) == str(i))
    tip(inputs.addIntegerSpinnerCommandInput('count', L('count'), 0, 99, 1, int(float(exprs['count']))))
    tip(inputs.addValueInput('finger_w', L('finger_w'), 'mm', adsk.core.ValueInput.createByString(exprs['finger_w'])))
    tip(inputs.addBoolValueInput('flip', L('flip'), True, '', exprs['flip'].strip() not in ('0', '0.0', '')))
    grp = inputs.addGroupCommandInput('butt', 'End-to-face joints (tab & slot, mortise & tenon)')
    gi = grp.children
    for k in ('depth', 'tenon_t', 'tab_len', 'end_off'):
        tip(gi.addValueInput(k, L(k), 'mm', adsk.core.ValueInput.createByString(exprs[k])))
    sp = tip(gi.addDropDownCommandInput('mt_space', L('mt_space'), adsk.core.DropDownStyles.TextListDropDownStyle))
    for i, n in enumerate(SPACE_NAMES):
        sp.listItems.add(n, str(int(float(exprs['mt_space']))) == str(i))
    tip(gi.addValueInput('mt_gap', L('mt_gap'), 'mm', adsk.core.ValueInput.createByString(exprs['mt_gap'])))
    tip(gi.addValueInput('end_gap', L('end_gap'), 'mm', adsk.core.ValueInput.createByString(exprs['end_gap'])))
    tb = inputs.addTextBoxCommandInput('info', '', '', 6, True)
    tb.isFullWidth = True
    if not with_selection:
        rb = tip(inputs.addBoolValueInput('reset', L('reset'), False, '', False))
        rb.text = 'Back to how it was'
    show_for_style(inputs, mt)


def apply_exprs(inputs, exprs):
    """Reset button: put every input back to these expressions."""
    um = design().unitsManager
    inputs.itemById('style').listItems.item(int(float(exprs['style']))).isSelected = True
    dd, cust = inputs.itemById('bit'), inputs.itemById('bit_custom')
    e = exprs['bit_d']
    cust.isVisible = False
    if e.strip() == 'nmj_bit':
        dd.listItems.item(0).isSelected = True
    else:
        try:
            v = um.evaluateExpression(e, 'mm')
        except Exception:
            v = None
        bits = edit_state.get('bits', [])
        idx = next((i for i, (d, _) in enumerate(bits) if v is not None and abs(d - v) < 1e-4), None)
        if idx is not None and e.replace(' ', '').endswith('mm'):
            dd.listItems.item(idx + 1).isSelected = True
        else:
            dd.listItems.item(dd.listItems.count - 1).isSelected = True
            cust.expression = e
            cust.isVisible = True
    glob = exprs['gap'].replace(' ', '') == 'nmj_gap'
    inputs.itemById('gap_global').value = glob
    inputs.itemById('gap').value = um.evaluateExpression(exprs['gap'], 'mm')
    inputs.itemById('relief').listItems.item(int(float(exprs['relief']))).isSelected = True
    inputs.itemById('mt_space').listItems.item(int(float(exprs['mt_space']))).isSelected = True
    inputs.itemById('flip').value = exprs['flip'].strip() not in ('0', '0.0', '')
    inputs.itemById('count').value = int(float(exprs['count']))
    for k in ('finger_w', 'depth', 'tenon_t', 'tab_len', 'end_off', 'mt_gap', 'end_gap'):
        inputs.itemById(k).expression = exprs[k]
    show_for_style(inputs, int(float(exprs['style'])) == 1)


def show_for_style(inputs, mt):
    # fingers / flip mean nothing for a mortise & tenon; spacing and glue room only for M&T
    for k in ('finger_w', 'flip'):
        inputs.itemById(k).isVisible = not mt
    for k in ('mt_space', 'end_gap'):
        inputs.itemById(k).isVisible = mt
    inputs.itemById('mt_gap').isVisible = mt and inputs.itemById('mt_space').selectedItem.index == 2
    # editing a box-corner joint: the end-to-face settings do nothing, so hide them
    inputs.itemById('butt').isVisible = edit_state.get('mode') != 'corner'


def read_inputs(inputs):
    dd = inputs.itemById('bit')
    i = dd.selectedItem.index
    bits = edit_state.get('bits', [])
    if i == 0:
        bit = 'nmj_bit'
    elif i <= len(bits):
        bit = '%g mm' % round(bits[i - 1][0] * 10, 4)
    else:
        bit = inputs.itemById('bit_custom').expression
    auto = edit_state.get('auto', {})
    v = lambda k: '0 mm' if auto.get(k) else inputs.itemById(k).expression
    gap = 'nmj_gap' if inputs.itemById('gap_global').value else v('gap')
    return {'gap': gap, 'bit_d': bit, 'relief': str(inputs.itemById('relief').selectedItem.index),
            'count': '0' if auto.get('count') else str(inputs.itemById('count').value), 'finger_w': v('finger_w'),
            'flip': '1' if inputs.itemById('flip').value else '0', 'depth': v('depth'),
            'tenon_t': v('tenon_t'), 'tab_len': v('tab_len'), 'end_off': v('end_off'),
            'style': str(inputs.itemById('style').selectedItem.index), 'end_gap': v('end_gap'),
            'mt_space': str(inputs.itemById('mt_space').selectedItem.index), 'mt_gap': v('mt_gap')}


def mm(v):
    return ('%.2f' % v).rstrip('0').rstrip('.')


def now_text(info, spec):
    """What the joint really is right now, with the auto values filled in (edit dialog, short lines)."""
    ta, tb = info['thick_mm']
    autos = []
    if info['mode'] == 'corner':
        lines = ['Now: %d fingers of %s mm (corner)' % (info['segments'], mm(info['width_mm']))]
        names = (('count', 'count'), ('finger_w', 'width'))
    elif info.get('style') == jc.STYLE_MT:
        n = info['tabs_or_fingers']
        lines = ['Now: %d tenon%s %s x %s mm' % (n, 's' if n > 1 else '', mm(info['width_mm']), mm(info['tenon_t_mm']))
                 + (', gaps %s mm' % mm(info['tenon_gap_mm']) if n > 1 else ''),
                 '%s %s mm%s, shoulders %s mm' % ('Through' if info['through'] else 'Blind', mm(info['depth_mm']),
                                                 '' if info['through'] else ' (+%s glue)' % mm(info['end_gap_mm']),
                                                 mm(info['shoulder_mm']))]
        names = (('count', 'count'), ('tab_len', 'length'), ('tenon_t', 'thickness'), ('end_off', 'shoulders'))
    else:
        lines = ['Now: %d tabs of %s mm, %s mm deep' % (info['tabs_or_fingers'], mm(info['width_mm']), mm(info['depth_mm']))]
        names = (('count', 'count'), ('tab_len', 'length'))
    autos = [label for k, label in names if spec.get(k, 0) <= 0]
    if autos:
        lines.append('Auto: %s (type 0 for auto)' % ', '.join(autos))
    lines.append('Boards %s / %s mm thick, bit %s, gap %s mm/side' % (mm(ta), mm(tb), mm(spec['bit_d'] * 10), mm(spec['gap'] * 10)))
    if info['mode'] == 'corner' and int(spec.get('relief', 0)) == 2:
        lines.append('Fingers get dogbones for Rounded.')
    if info['notes']:
        lines.append('! ' + '; '.join(info['notes']))
    return '\n'.join(lines)


def edit_preview(inputs):
    """Edit dialog: show the real sizes for the values in the dialog (timeline is rolled back before the joint)."""
    cf = edit_state.get('cf')
    if not cf or 'marker' not in edit_state:
        return
    try:
        ensure_rolled(cf)
        spec = spec_from_exprs(read_inputs(inputs))
        if 'view' in edit_state:
            box_preview(inputs, spec)
            return
        A, B = board(cf, 'A'), board(cf, 'B')
        if not (A and B):
            raise jc.JointError('The boards of this joint can no longer be found.')
        info, _ = jc.build_tools(A, B, spec, True)
        inputs.itemById('info').text = now_text(info, spec)
        fill_auto(inputs, info)
    except jc.JointError as e:
        inputs.itemById('info').text = '! %s' % e
    except Exception as e:
        inputs.itemById('info').text = 'Error: %s' % e
        log(traceback.format_exc())


def box_preview(inputs, spec):
    """Whole box edit: all joints (box settings) or the one joint picked under Edit."""
    cf, view = edit_state['cf'], edit_state['view']
    boards = group_boards(cf)
    if any(b is None for b in boards):
        raise jc.JointError('The boards of this joint can no longer be found.')
    pidx = [tuple(p) for p in json.loads(cf.customNamedValues.value('pairs'))]
    if view != 'all':
        ia, ib = pidx[view]
        info, _ = jc.build_tools(boards[ia], boards[ib], spec, True)
        own = sorted(clean_over({view: {k: read_inputs(inputs)[k] for k in JOINT_KEYS}}, edit_state['shared']).get(view, {}))
        head = ('Own settings: %s.' % ', '.join(LABELS[k][0].lower() for k in own) if own
                else 'Same as the box settings.')
        inputs.itemById('info').text = (head + ' Type, bit, gap and corners: Edit > All joints.\n'
                                        + now_text(info, spec))
        fill_auto(inputs, [info])
        return
    ex = read_inputs(inputs)
    over = clean_over(edit_state['over'], ex)
    infos, _, _ = group_tools(boards, pidx, joint_specs(ex, over, len(pidx)), True)
    edit_state['jmodes'] = [i['mode'] for i in infos]
    lines = []
    for j, i in enumerate(infos):
        lines.append(describe(i) + ('   (own %s)' % ', '.join(LABELS[k][0].lower() for k in sorted(over[j]))
                                    if j in over else ''))
    differ = fill_auto(inputs, [i for j, i in enumerate(infos)], over)
    head = 'Whole box: these settings go to every joint (pick one under Edit for its own).'
    if differ:
        head += '\nAuto, differs per joint: %s.' % ', '.join(differ)
    inputs.itemById('info').text = head + '\n' + '\n'.join(lines)


def resolved(info):
    """The real value behind each automatic field (count as int, lengths in cm)."""
    mt = info.get('style') == jc.STYLE_MT
    out = {'count': info['segments'] if info['mode'] == 'corner' else info['tabs_or_fingers'],
           'finger_w': info['width_mm'] / 10, 'tab_len': info['width_mm'] / 10, 'depth': info['depth_mm'] / 10,
           'tenon_t': (info['tenon_t_mm'] if mt else info['thick_mm'][1]) / 10,
           'end_off': info['shoulder_mm'] / 10 if mt else 0.0}
    if mt and info.get('through'):
        out['depth'] = info['thick_mm'][0] / 10
    return out


CORNER_KEYS = ('count', 'finger_w')     # what a finger (corner) joint uses of AUTO_KEYS


def fill_auto(inputs, infos, over=None):
    """Automatic fields show the real size. Several joints (whole box): only where they all agree;
    returns the names of the automatic fields that differ per joint."""
    if not isinstance(infos, list):
        infos = [infos]
    auto, shown = edit_state.get('auto', {}), edit_state.setdefault('shown', {})
    differ = []
    edit_state['busy'] = True
    try:
        for k in AUTO_KEYS:
            if not auto.get(k):
                continue
            vals = [resolved(i)[k] for j, i in enumerate(infos)
                    if k not in (over or {}).get(j, {}) and (i['mode'] != 'corner' or k in CORNER_KEYS)]
            if not vals:
                continue
            if max(vals) - min(vals) > 1e-6:
                differ.append(LABELS[k][0].lower())
                continue
            inp = inputs.itemById(k)
            if k == 'count':
                if inp.value != vals[0]:
                    inp.value = int(vals[0])
            elif abs(inp.value - vals[0]) > 1e-6:
                inp.expression = '%s mm' % mm(vals[0] * 10)
            shown[k] = inp.value
    finally:
        edit_state['busy'] = False
    return differ


def auto_of(exprs):
    um = design().unitsManager
    return {k: um.evaluateExpression(exprs[k], 'mm' if k != 'count' else '') <= 0 for k in AUTO_KEYS}


def save_view(inputs):
    """Whole box edit: keep what the dialog shows for the current view (box settings or one joint's own)."""
    ex = read_inputs(inputs)
    v = edit_state['view']
    if v == 'all':
        edit_state['shared'] = ex
    else:
        edit_state['over'][v] = {k: ex[k] for k in JOINT_KEYS}
        edit_state['over'] = clean_over(edit_state['over'], edit_state['shared'])


def show_view(inputs, v):
    edit_state['view'] = v
    ex = dict(edit_state['shared'])
    if v != 'all':
        ex.update(edit_state['over'].get(v, {}))
    modes = edit_state.get('jmodes') or []
    edit_state['mode'] = 'box' if v == 'all' or v >= len(modes) else modes[v]
    edit_state['busy'] = True
    try:
        apply_exprs(inputs, ex)
        for k in SHARED_INPUTS:
            inputs.itemById(k).isEnabled = v == 'all'
    finally:
        edit_state['busy'] = False
    edit_state['auto'] = auto_of(ex)
    edit_state['shown'] = {}
    edit_preview(inputs)


def selected_bodies(inputs):
    sel = inputs.itemById('bodies')
    bodies = [adsk.fusion.BRepBody.cast(sel.selection(i).entity) for i in range(sel.selectionCount)]
    wh = inputs.itemById('whole')
    if wh and wh.value and bodies:
        bodies = whole_box(bodies)
    return bodies


def pick_whole_box(inputs):
    """Whole box ticked: add the rest of the box to the selection, so it shows highlighted."""
    sel, wh = inputs.itemById('bodies'), inputs.itemById('whole')
    sel.setSelectionLimits(1 if wh.value else 2, 0)
    if not (wh.value and sel.selectionCount):
        return
    have = [adsk.fusion.BRepBody.cast(sel.selection(i).entity) for i in range(sel.selectionCount)]
    keys = {body_key(b) for b in have}
    edit_state['busy'] = True
    try:
        for b in whole_box(have):
            if body_key(b) not in keys:
                sel.addSelection(b)
    finally:
        edit_state['busy'] = False


class InputChanged(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        try:
            inputs = args.input.parentCommand.commandInputs   # args.inputs is only the group for grouped inputs
            if edit_state.get('busy'):
                return                                         # our own fill / reset
            k = args.input.id
            if k in ('bodies', 'whole') and inputs.itemById('whole'):
                if k == 'whole':
                    whole_box_on[0] = args.input.value
                pick_whole_box(inputs)
                return
            if k == 'which':
                save_view(inputs)
                i = args.input.selectedItem.index
                show_view(inputs, 'all' if i == 0 else i - 1)
                return
            if k == 'reset' and 'view' in edit_state:
                edit_state['shared'] = dict(edit_state['orig'])
                edit_state['over'] = {j: dict(d) for j, d in edit_state['orig_over'].items()}
                show_view(inputs, edit_state['view'])
                return
            if k == 'reset':
                edit_state['busy'] = True
                try:
                    apply_exprs(inputs, edit_state['orig'])
                finally:
                    edit_state['busy'] = False
                edit_state['auto'] = dict(edit_state['orig_auto'])
                edit_state['shown'] = {}
                edit_preview(inputs)
                return
            if k in AUTO_KEYS and 'auto' in edit_state:
                shown = edit_state.setdefault('shown', {})
                v = args.input.value
                if k not in shown or abs(v - shown[k]) > 1e-6:  # the user changed it
                    edit_state['auto'][k] = v <= 0                 # 0 = back to automatic
                    shown.pop(k, None)
            if args.input.id in ('gap', 'gap_global'):
                g = design().userParameters.itemByName('nmj_gap')
                gv = g.value if g else 0.01
                gi, gg = inputs.itemById('gap'), inputs.itemById('gap_global')
                if args.input.id == 'gap' and abs(gi.value - gv) > 1e-9:
                    gg.value = False                           # own number typed: this joint only
                elif args.input.id == 'gap_global' and gg.value and abs(gi.value - gv) > 1e-9:
                    gi.value = gv                              # back to the global value
            elif args.input.id == 'bit':
                inputs.itemById('bit_custom').isVisible = (args.input.selectedItem.index == args.input.listItems.count - 1)
            elif args.input.id in ('style', 'mt_space'):
                show_for_style(inputs, inputs.itemById('style').selectedItem.index == 1)
            edit_preview(inputs)
        except Exception:
            log(traceback.format_exc())


class CreatePreview(adsk.core.CommandEventHandler):
    def notify(self, args):
        inputs = args.command.commandInputs
        try:
            made, lines = create_all(selected_bodies(inputs), read_inputs(inputs))
            inputs.itemById('info').text = '\n'.join(lines)
            args.isValidResult = made > 0
        except Exception as e:
            inputs.itemById('info').text = 'Error: %s' % e
            log(traceback.format_exc())


class CreateExecute(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            inputs = args.command.commandInputs
            made, lines = create_all(selected_bodies(inputs), read_inputs(inputs))
            if not made:
                ui.messageBox('\n'.join(lines), 'NM Joint')
        except Exception:
            ui.messageBox('NM Joint failed:\n' + traceback.format_exc())


class CreateCreated(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            for k in ('mode', 'auto', 'shown', 'orig', 'orig_auto', 'busy', 'view', 'over', 'orig_over', 'shared', 'jmodes'):
                edit_state.pop(k, None)           # new joints: every setting, 0 = auto as typed
            cmd = args.command
            cmd.setDialogInitialSize(380, 560)
            try:
                ensure_globals(design())
            except Exception:
                log('ensure_globals in dialog failed:\n' + traceback.format_exc())
            up = design().userParameters
            g = {name: (name if up.itemByName(name) else val) for name, val, _ in GLOBALS}
            add_inputs(cmd.commandInputs, {p[0]: g.get(p[3], p[3]) for p in PARAMS}, True)
            for ev, h in ((cmd.executePreview, CreatePreview()), (cmd.execute, CreateExecute()),
                          (cmd.inputChanged, InputChanged())):
                ev.add(h)
                handlers.append(h)
        except Exception:
            ui.messageBox('NM Joint failed:\n' + traceback.format_exc())


# --- edit (double-click in the timeline)
class EditActivate(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            des = design()
            tl = des.timeline
            edit_state['marker'] = tl.markerPosition
            edit_state['at_end'] = tl.markerPosition == tl.count
            edit_state['count'] = tl.count
            edit_state['cf'].timelineObject.rollTo(True)
            edit_preview(args.command.commandInputs)
        except Exception:
            log(traceback.format_exc())


def ensure_rolled(cf):
    """The edit dialog measures the boards as they are before this joint. Fusion can move the timeline back to the
    end while the dialog is open (seen after the first input change): roll back again when that happened."""
    tl = design().timeline
    if tl.markerPosition != cf.timelineObject.index:
        cf.timelineObject.rollTo(True)


def restore_marker():
    des = design()
    tl = des.timeline
    if 'marker' not in edit_state:
        return
    if edit_state['at_end']:
        tl.moveToEnd()
    else:
        tl.markerPosition = max(0, min(tl.count, edit_state['marker'] + tl.count - edit_state['count']))
    edit_state.pop('marker', None)


def edit_group(cf, exprs, over=None):
    boards = group_boards(cf)
    if any(b is None for b in boards):
        raise jc.JointError('The boards of this joint can no longer be found.')
    pidx = [tuple(p) for p in json.loads(cf.customNamedValues.value('pairs'))]
    over = clean_over(group_over(cf) if over is None else over, exprs)
    infos, _, ops = group_tools(boards, pidx, joint_specs(exprs, over, len(pidx)), True)
    same_keys = {j: sorted(d) for j, d in over.items()} == over_keys(cf)
    if (all(fparam(cf, pid) for pid in DEFAULT_EXPR) and same_keys
            and ops_key(ops) == cf.customNamedValues.value('ops')):
        for j, d in over.items():
            for k, e in d.items():
                q = fparam(cf, 'j%d_%s' % (j, k))
                if q.expression != e:
                    q.expression = e
        if len(infos) == 1 and cf.name.startswith(('NM Tabs ', 'NM M&T ')):   # keep a name the user typed
            try:
                cf.name = group_name(cf.parentComponent, boards, infos)
            except Exception:
                pass
        for pid, _, _, _ in PARAMS:
            p = fparam(cf, pid)
            if p.expression != exprs[pid]:
                p.expression = exprs[pid]
    else:                                       # other tool bodies -> rebuild in place
        comp = cf.parentComponent
        cf.deleteMe()
        make_group(comp, boards, pidx, exprs, fixed=True, over=over)


class EditExecute(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            cf = edit_state['cf']
            exprs = read_inputs(args.command.commandInputs)
            if 'marker' in edit_state:
                ensure_rolled(cf)
            if is_group(cf):
                if 'view' in edit_state:
                    save_view(args.command.commandInputs)
                    edit_group(cf, edit_state['shared'], edit_state['over'])
                else:
                    edit_group(cf, exprs)
                return
            A, B = board(cf, 'A'), board(cf, 'B')
            if not (A and B):
                raise jc.JointError('The boards of this joint can no longer be found.')
            info, tools = jc.build_tools(A, B, spec_from_exprs(exprs), True)
            keys = [k for k in TOOL_ORDER if tools[k]]
            complete = all(fparam(cf, pid) for pid in DEFAULT_EXPR)
            if complete and keys == cf.customNamedValues.value('tools').split(','):
                if cf.name.startswith(('NM Tabs ', 'NM M&T ')):      # keep a name the user typed
                    try:
                        cf.name = 'NM %s %s-%s' % (joint_kind(info), A.name, B.name)
                    except Exception:
                        pass
                for pid, _, _, _ in PARAMS:
                    p = fparam(cf, pid)
                    if p.expression != exprs[pid]:
                        p.expression = exprs[pid]
            else:                                   # other tool bodies, or an older joint -> rebuild in place
                comp = cf.parentComponent
                cf.deleteMe()
                make_joint(comp, A, B, exprs, fixed=True)
        except jc.JointError as e:
            ui.messageBox(str(e), 'NM Joint')
        except Exception:
            ui.messageBox('NM Joint edit failed:\n' + traceback.format_exc())
        finally:
            restore_marker()


class EditDestroy(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            restore_marker()
        except Exception:
            log(traceback.format_exc())


class EditCreated(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cf = adsk.fusion.CustomFeature.cast(ui.activeSelections.item(0).entity)
            edit_state['cf'] = cf
            edit_state['mode'] = cf.customNamedValues.value('mode')
            exprs = exprs_from_feature(cf)
            um = design().unitsManager
            edit_state['orig'] = dict(exprs)
            edit_state['orig_auto'] = {k: um.evaluateExpression(exprs[k], 'mm' if k != 'count' else '') <= 0 for k in AUTO_KEYS}
            edit_state['auto'] = dict(edit_state['orig_auto'])
            edit_state['shown'] = {}
            for k in ('view', 'over', 'orig_over', 'shared', 'jmodes'):
                edit_state.pop(k, None)
            cmd = args.command
            cmd.setDialogInitialSize(380, 560)
            if edit_state['mode'] == 'box':
                boards = group_boards(cf)
                nm_ = lambda i: boards[i].name if boards[i] else '?'
                wh = tip(cmd.commandInputs.addDropDownCommandInput('which', LABELS['which'][0],
                                                                   adsk.core.DropDownStyles.TextListDropDownStyle))
                wh.listItems.add('All joints (box settings)', True)
                over = group_over(cf)
                for j, (ia, ib) in enumerate(json.loads(cf.customNamedValues.value('pairs'))):
                    wh.listItems.add('%s / %s%s' % (nm_(ia), nm_(ib), '  *' if j in over else ''), False)
                edit_state.update(view='all', over=over, orig_over={j: dict(d) for j, d in over.items()}, shared=dict(exprs))
            add_inputs(cmd.commandInputs, exprs, False)
            if edit_state['mode'] == 'box':
                cmd.commandInputs.itemById('info').text = 'Whole box: %s.' % ', '.join(b.name for b in boards if b)
            else:
                cmd.commandInputs.itemById('info').text = 'Mode: %s joint between %s and %s.' % (
                    edit_state['mode'], (board(cf, 'A') or cf).name, (board(cf, 'B') or cf).name)
            for ev, h in ((cmd.activate, EditActivate()), (cmd.execute, EditExecute()),
                          (cmd.destroy, EditDestroy()), (cmd.inputChanged, InputChanged())):
                ev.add(h)
                handlers.append(h)
        except Exception:
            ui.messageBox('NM Joint edit failed:\n' + traceback.format_exc())


# --- recompute (board changed size, or a parameter changed)
def broken_joints(des):
    """NM joints with an inner combine that failed (the joint itself still says healthy)."""
    bad = []
    for comp in des.allComponents:
        for f in comp.features.customFeatures:
            try:
                if f.definition.id != FEAT_ID:
                    continue
                for g in f.features:
                    if g.healthState == adsk.fusion.FeatureHealthStates.ErrorFeatureHealthState:
                        bad.append('%s/%s' % (f.name, g.name))
            except Exception:
                pass
    return bad


class Heal(adsk.core.CustomEventHandler):
    """Several joins into one board (a drawer bottom gets tabs on 4 sides): after a dimension change Fusion
    sometimes loses a later join's target body ('target body is lost'); a full recompute puts it right.
    Runs once after the joint computes, outside the compute event (Fusion doesn't allow it in there)."""
    def notify(self, args):
        heal['pending'] = False
        if heal['busy']:
            return
        try:
            des = design()
            bad = broken_joints(des) if des else []
            if not bad:
                return
            heal['busy'] = True
            try:
                des.computeAll()
            finally:
                heal['busy'] = False
            left = broken_joints(des)
            log('heal: %s -> compute all -> %s' % (bad, left or 'all fine'))
        except Exception:
            heal['busy'] = False
            log('heal failed:\n' + traceback.format_exc())


def ask_heal():
    if not heal['busy'] and not heal['pending']:
        heal['pending'] = True
        try:
            app.fireCustomEvent(HEAL_ID)
        except Exception:
            heal['pending'] = False


def compute_group(cf, st):
    boards = group_boards(cf)
    missing = [i for i, b in enumerate(boards) if b is None]
    if missing:
        log('  boards not found yet (%s), keeping built geometry' % missing)
        return
    pidx = [tuple(p) for p in json.loads(cf.customNamedValues.value('pairs'))]
    infos, _, ops = group_tools(boards, pidx, group_specs(cf, len(pidx)), True)
    if ops_key(ops) != cf.customNamedValues.value('ops'):
        st.addWarning('NMJ_REBUILD', 'This change needs a rebuild: double-click the joint and press OK.')
        return
    bf = next(adsk.fusion.BaseFeature.cast(f) for f in cf.features if adsk.fusion.BaseFeature.cast(f))
    bf.startEdit()
    try:
        olds = [bf.bodies.item(i) for i in range(bf.bodies.count)]
        for (_, _, tool), old in zip(ops, olds):
            bf.updateBody(old, tool)
    finally:
        bf.finishEdit()
    log('  %d joints, %d tool bodies updated' % (len(infos), len(ops)))
    for n in sorted({n for info in infos for n in info['notes']}):
        st.addWarning('NMJ_NOTE', n)


def size_hint():
    """After a size change the boards no longer meet like before: most often a number typed without its unit."""
    return ('The boards no longer meet the way they did. Check the size you just changed: a number without a unit '
            'is read in that parameter\'s own unit (often mm), so type "20 in" for inches. Set it right and the joints follow again.')


class Compute(adsk.fusion.CustomFeatureEventHandler):
    def notify(self, args):
        log('compute event')
        try:
            args = adsk.fusion.CustomFeatureEventArgs.cast(args)
            st = args.computeStatus.statusMessages
            cf = args.customFeature
            log('compute ' + cf.name)
            if is_group(cf):
                compute_group(cf, st)
                ask_heal()
                return
            A, B = board(cf, 'A'), board(cf, 'B')
            if not (A and B):
                log('  boards not stored yet (first compute during add), keeping built geometry')
                return
            log('  boards %s %s vol %.3f %.3f' % (A.name, B.name, A.volume, B.volume))
            info, tools = jc.build_tools(A, B, spec_from_feature(cf), True)
            keys = [k for k in TOOL_ORDER if tools[k]]
            if keys != cf.customNamedValues.value('tools').split(','):
                st.addWarning('NMJ_REBUILD', 'This change needs a rebuild: double-click the joint and press OK.')
                return
            bf = next(adsk.fusion.BaseFeature.cast(f) for f in cf.features if adsk.fusion.BaseFeature.cast(f))
            bf.startEdit()
            try:
                olds = [bf.bodies.item(i) for i in range(bf.bodies.count)]
                for k, old in zip(keys, olds):
                    bf.updateBody(old, tools[k])
            finally:
                bf.finishEdit()
            for n in info['notes']:
                st.addWarning('NMJ_NOTE', n)
            ask_heal()
        except jc.JointError as e:
            log('  joint error: %s' % e)
            st.addError('NMJ_ERR', '%s %s' % (e, size_hint()))
        except Exception:
            log('compute failed:\n' + traceback.format_exc())
            st.addError('NMJ_ERR', traceback.format_exc().strip().splitlines()[-1])


# ----------------------------------------------------------------------------------------------- add-in
def run(context):
    global definition
    try:
        defs = ui.commandDefinitions
        for cid in (CREATE_ID, EDIT_ID):
            old = defs.itemById(cid)
            if old:
                old.deleteMe()
        c = defs.addButtonDefinition(CREATE_ID, 'NM Joint',
                                     'Finger joints, tab & slot and mortise & tenon between boards, with dogbones for '
                                     'your CNC bit. Select 2 or more boards; every touching or overlapping pair gets a '
                                     'joint. Double-click a joint in the timeline to edit it.',
                                     os.path.join(HERE, 'resources', 'create'))
        h = CreateCreated(); c.commandCreated.add(h); handlers.append(h)
        e = defs.addButtonDefinition(EDIT_ID, 'Edit NM Joint', '', os.path.join(HERE, 'resources', 'edit'))
        h = EditCreated(); e.commandCreated.add(h); handlers.append(h)

        # the edit command must exist before it can be tied to the feature type
        definition = adsk.fusion.CustomFeatureDefinition.create(FEAT_ID, 'NM Joint', os.path.join(HERE, 'resources', 'joint'))
        if definition is None:
            raise RuntimeError('CustomFeatureDefinition.create returned nothing')
        definition.editCommandId = EDIT_ID
        h = Compute()
        definition.customFeatureCompute.add(h)
        handlers.append(h)

        try:
            app.unregisterCustomEvent(HEAL_ID)
        except Exception:
            pass
        ev = app.registerCustomEvent(HEAL_ID)
        h = Heal(); ev.add(h); handlers.append(h)

        panel = ui.allToolbarPanels.itemById(PANEL_ID)
        if panel and not panel.controls.itemById(CREATE_ID):
            ctl = panel.controls.addCommand(c)
            ctl.isPromoted = True
        for mname in ('nm_flat', 'nm_drawer', 'nm_cabinet'):  # own modules; a failure there must not stop NM Joint
            try:
                mod = importlib.reload(importlib.import_module(mname))
                mod.register(sys.modules[__name__])
            except Exception:
                log('%s failed to start:\n%s' % (mname, traceback.format_exc()))
        log('started')
        try:                                    # "a newer version is out" notice (GitHub releases)
            import nmj_update
            nmj_update.start('NMJoinery', HERE, log)
        except Exception:
            log('update check:\n' + traceback.format_exc())
    except Exception:
        log('failed to start:\n' + traceback.format_exc())


def stop(context):
    try:
        panel = ui.allToolbarPanels.itemById(PANEL_ID)
        if panel:
            ctl = panel.controls.itemById(CREATE_ID)
            if ctl:
                ctl.deleteMe()
        for cid in (CREATE_ID, EDIT_ID):
            d = ui.commandDefinitions.itemById(cid)
            if d:
                d.deleteMe()
        app.unregisterCustomEvent(HEAL_ID)
    except Exception:
        log(traceback.format_exc())
    try:
        import nmj_update
        nmj_update.stop_('NMJoinery')
    except Exception:
        log(traceback.format_exc())
    for mname in ('nm_cabinet', 'nm_drawer', 'nm_flat'):
        try:
            importlib.import_module(mname).unregister(sys.modules[__name__])
        except Exception:
            log(traceback.format_exc())
