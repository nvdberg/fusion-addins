#!/usr/bin/env python3
"""
wrap_y_to_a.py - wrap a FLAT 3-axis Fusion program around the Avid rotary (A about X).

Why: Fusion's real rotary toolpaths need the paid Machining Extension. This lets you
draw the design flat (unrolled), make normal 2D/3D toolpaths, post them with the normal
"Avid CNC" post, and then turn every Y move into an A rotation.

    A (degrees) = -Y * 360 / (pi * D)        (sign flips with --reverse)
    Z_out       = Z + D/2                    (Fusion Z0 on top of the flat stock -> Mach4 Z0 on the axis)
    Y_out       = 0                          (Mach4 Y0 = rotation axis, set by the Rotary touch)
    feeds       -> G93 inverse time, computed from the flat (= surface) distance

Usage
    python3 wrap_y_to_a.py MyPart.tap --diameter 2in
    python3 wrap_y_to_a.py MyPart.tap --diameter 50.8mm --reverse
    python3 wrap_y_to_a.py MyPart.tap --diameter 2 --zero axis     (Fusion Z0 already on the axis)

Writes MyPart_A.tap next to the input (or -o OUTFILE). Prints the A range and depth checks.
Arcs (G2/G3, IJK) are cut into short lines. Canned drill cycles are converted and run in G94.
Default sign matches Avid's "Wrap Y to A" Fusion post (A axis vector [-1,0,0]).
ALWAYS air-cut a new file first. No warranty - check the output in a G-code viewer.
"""
import argparse, math, os, re, sys

WORD = re.compile(r'([A-Za-z])\s*([-+]?(?:\d+\.?\d*|\.\d+))')


def parse_len(text, prog_units):
    """'2', '2in', '2"', '50.8mm' -> value in program units ('in' or 'mm')."""
    t = text.strip().lower().replace('"', 'in')
    m = re.fullmatch(r'([0-9]*\.?[0-9]+)\s*(in|inch|mm)?', t)
    if not m:
        sys.exit(f"Can't read diameter '{text}'. Use e.g. 2in or 50.8mm")
    v, u = float(m.group(1)), m.group(2)
    if u is None:
        return v, False
    u = 'in' if u.startswith('in') else 'mm'
    if u == prog_units:
        return v, True
    return (v * 25.4 if u == 'in' else v / 25.4), True


def split_comment(line):
    """Return (code, comment). Keeps (...) and ; comments as text."""
    code, com, depth = [], [], 0
    i = 0
    while i < len(line):
        c = line[i]
        if c == ';' and depth == 0:
            com.append(line[i:]); break
        if c == '(':
            depth += 1
        if depth:
            com.append(c)
        else:
            code.append(c)
        if c == ')' and depth:
            depth -= 1
        i += 1
    return ''.join(code), ''.join(com)


def main():
    ap = argparse.ArgumentParser(description="Wrap flat Fusion G-code Y moves onto the A axis (rotary along X).")
    ap.add_argument('input')
    ap.add_argument('--diameter', '-d', required=True, help='blank diameter, e.g. 2in or 50.8mm (no unit = program units)')
    ap.add_argument('--zero', choices=['top', 'axis'], default='top',
                    help='where Fusion Z0 is: top of flat stock (default) or already on the rotation axis')
    ap.add_argument('--reverse', action='store_true', help='flip A direction (use if a test comes out mirrored)')
    ap.add_argument('--tol', type=float, default=None, help='arc chord tolerance (default 0.0005in / 0.01mm)')
    ap.add_argument('-o', '--output')
    a = ap.parse_args()

    with open(a.input, 'r', errors='replace') as f:
        lines = f.read().splitlines()

    units = 'mm' if any(re.search(r'\bG0*21\b', split_comment(l)[0].upper()) for l in lines[:80]) else 'in'
    D, had_unit = parse_len(a.diameter, units)
    if D <= 0:
        sys.exit('Diameter must be > 0')
    R = D / 2.0
    k = (1 if a.reverse else -1) * 360.0 / (math.pi * D)
    zoff = R if a.zero == 'top' else 0.0
    tol = a.tol if a.tol else (0.0005 if units == 'in' else 0.01)
    lf = '{:.4f}' if units == 'in' else '{:.3f}'

    def L(v):
        s = lf.format(v)
        return '0' if float(s) == 0 else s.rstrip('0').rstrip('.') if '.' in s else s

    def AF(v):
        s = '{:.3f}'.format(v + 0.0)
        s = s.rstrip('0').rstrip('.')
        return '0' if s in ('-0', '', '0') else s

    out = []
    if lines and lines[0].strip() == '%':
        out.append(lines.pop(0))
    out.append('(WRAPPED Y->A by wrap_y_to_a.py from %s)' % os.path.basename(a.input))
    out.append('(diameter %s %s, A = %sY*%.6f deg, Z %s, Y held at 0 = rotation axis)'
               % (L(D), units, '' if k > 0 else '-', abs(k), '+ %s (top -> axis)' % L(R) if zoff else 'unchanged'))
    out.append('(MACH4: Rotary touch Z+Y on the axis, Zero X at the Fusion X origin, Zero A. AIR CUT FIRST.)')

    pos = {'X': None, 'Y': None, 'Z': None}
    motion, plane, absmode = 0, 17, True
    feed = None
    feedmode = None          # what we have told the machine: 93 / 94
    in_cycle = False
    y_seen = False
    amin, amax, zmin = float('inf'), float('-inf'), float('inf')
    warnings = set()
    n_arcs = n_seg = 0

    def note_a(av):
        nonlocal amin, amax
        amin, amax = min(amin, av), max(amax, av)

    def emit_linear(gcode, tgt, f_upm, prefix_words):
        """Emit one straight move in flat coords tgt={'X','Y','Z'} (None = unchanged)."""
        nonlocal feedmode, y_seen, zmin, n_seg
        pre_n = [w for w in prefix_words if w[0] == 'N']
        pre_g = [w for w in prefix_words if w[0] == 'G']
        post_w = [w for w in prefix_words if w[0] not in 'NG']
        words = pre_n + pre_g
        start = dict(pos)
        end = {ax: (tgt[ax] if tgt.get(ax) is not None else pos[ax]) for ax in 'XYZ'}
        if gcode == 1:
            if feedmode != 93:
                words.insert(len(pre_n), 'G93'); feedmode = 93
        words.append('G%d' % gcode)
        if tgt.get('X') is not None:
            words.append('X' + L(end['X']))
        if tgt.get('Y') is not None:
            if not y_seen:
                words.append('Y0'); y_seen = True
            av = end['Y'] * k
            note_a(av)
            words.append('A' + AF(av))
        if tgt.get('Z') is not None:
            zo = end['Z'] + zoff
            zmin = min(zmin, zo)
            words.append('Z' + L(zo))
        words += post_w
        if gcode == 1:
            if f_upm is None:
                sys.exit('Cutting move before any feed (F) was set - is this a Fusion post output?')
            known = all(start[ax] is not None for ax in 'XYZ' if tgt.get(ax) is not None)
            if not known:
                # start point unknown: run this one move in units/min
                words.insert(len(pre_n), 'G94'); feedmode = 94
                words.append('F' + '{:.1f}'.format(f_upm))
                warnings.add('first cutting move had an unknown start point; it runs in G94')
            else:
                dist = math.sqrt(sum(((end[ax] - start[ax]) if tgt.get(ax) is not None else 0.0) ** 2 for ax in 'XYZ'))
                if dist < 1e-7:
                    for ax in 'XYZ':
                        pos[ax] = end[ax]
                    return None
                words.append('F' + '{:.3f}'.format(f_upm / dist).rstrip('0').rstrip('.'))
        n_seg += 1
        for ax in 'XYZ':
            if end[ax] is not None:
                pos[ax] = end[ax]
        return ' '.join(words)

    for raw in lines:
        code, comment = split_comment(raw)
        U = code.upper()
        words = [(m.group(1).upper(), float(m.group(2))) for m in WORD.finditer(U)]
        if not words:
            out.append(raw); continue
        gs = [v for l, v in words if l == 'G']
        gi = [round(v, 1) for v in gs]   # keep G91.1 distinct from G91
        ms = [int(round(v)) for l, v in words if l == 'M']
        vals = {l: v for l, v in words if l not in 'GM'}

        # machine-coordinate / reference moves: leave alone
        if any(g in (28, 30, 53, 92) for g in gi) or 10 in gi:
            if 'Y' in vals and 53 in gi:
                warnings.add('G53 move with Y left unchanged (machine coordinates)')
            out.append(raw); continue

        if 91 in gi:
            sys.exit('G91 incremental mode found - Fusion posts should be G90 absolute. Stop.')
        if 90 in gi:
            absmode = True
        if 20 in gi or 21 in gi:
            u2 = 'mm' if 21 in gi else 'in'
            if u2 != units:
                sys.exit('Program switches units mid-file - not supported.')
        for p in (17, 18, 19):
            if p in gi:
                plane = p
        if 'R' in vals and any(g in (2, 3) for g in gi):
            sys.exit('R-format arcs found; this tool expects I/J/K arcs (Avid post default).')
        if 'F' in vals:
            feed = vals['F']

        # program end: return to normal feed mode
        if any(m in (2, 30) for m in ms) and feedmode == 93:
            out.append('G94'); feedmode = 94

        cyc = [g for g in gi if 73 <= g <= 89 and g != 80]
        if 80 in gi:
            in_cycle = False
        if cyc:
            in_cycle = True
        for g in gi:
            if g in (0, 1, 2, 3):
                motion = g
                in_cycle = False if not cyc else in_cycle

        has_xyz = any(ax in vals for ax in 'XYZ')

        # ---- canned drilling cycles (G81..G89): convert positions, run in G94 ----
        if in_cycle and (cyc or has_xyz):
            parts = []
            if feedmode != 94:
                parts.append('G94'); feedmode = 94
            for l, v in words:
                if l == 'Y':
                    if not y_seen:
                        parts.append('Y0'); y_seen = True
                    av = v * k; note_a(av); parts.append('A' + AF(av)); pos['Y'] = v
                elif l == 'Z':
                    zo = v + zoff; zmin = min(zmin, zo); parts.append('Z' + L(zo))
                elif l == 'R' and cyc:
                    parts.append('R' + L(v + zoff))
                elif l == 'X':
                    parts.append('X' + L(v)); pos['X'] = v
                elif l == 'F':
                    parts.append('F' + '{:.1f}'.format(v))
                elif l == 'G':
                    parts.append('G' + ('%g' % v))
                else:
                    parts.append(l + ('%g' % v))
            out.append(' '.join(parts) + ((' ' + comment) if comment else ''))
            warnings.add('drill cycles: holes point at the axis; R plane and depth were shifted by the radius')
            continue

        if not has_xyz:
            # no motion on this line: copy, but drop G93/G94 the post writes (we manage feed mode)
            keep = [w for w in re.split(r'\s+', code.strip()) if w.upper() not in ('G94', 'G93')]
            line = ' '.join(keep)
            out.append((line + (' ' + comment if comment else '')).strip())
            continue

        # other words on the line (G43, H, S, M, T, N...) go in front of the move
        prefix = []
        for l, v in words:
            if l in 'XYZIJKF':
                continue
            if l == 'G' and round(v, 1) in (0, 1, 2, 3, 93, 94, 17, 18, 19, 90):
                continue
            prefix.append(l + ('%g' % v))

        tgt = {ax: vals.get(ax) for ax in 'XYZ'}

        if motion in (0, 1):
            line = emit_linear(motion, tgt, feed, prefix)
            if line:
                out.append(line + ((' ' + comment) if comment else ''))
            continue

        # ---- arcs: linearise in flat space ----
        n_arcs += 1
        if any(pos[ax] is None for ax in 'XYZ'):
            sys.exit('Arc before the start position is known - cannot convert.')
        s = dict(pos)
        e = {ax: (tgt[ax] if tgt[ax] is not None else pos[ax]) for ax in 'XYZ'}
        ax_u, ax_v, ax_w = {17: ('X', 'Y', 'Z'), 18: ('Z', 'X', 'Y'), 19: ('Y', 'Z', 'X')}[plane]
        off = {'X': vals.get('I', 0.0), 'Y': vals.get('J', 0.0), 'Z': vals.get('K', 0.0)}
        cu, cv = s[ax_u] + off[ax_u], s[ax_v] + off[ax_v]
        r = math.hypot(s[ax_u] - cu, s[ax_v] - cv)
        a0 = math.atan2(s[ax_v] - cv, s[ax_u] - cu)
        a1 = math.atan2(e[ax_v] - cv, e[ax_u] - cu)
        cw = (motion == 2)
        sweep = a1 - a0
        if cw:
            while sweep >= -1e-12: sweep -= 2 * math.pi
        else:
            while sweep <= 1e-12: sweep += 2 * math.pi
        if r < 1e-9:
            nseg = 1
        else:
            ratio = max(-1.0, min(1.0, 1 - tol / r))
            step = 2 * math.acos(ratio) if ratio < 1 else abs(sweep)
            nseg = max(1, int(math.ceil(abs(sweep) / max(step, 1e-6))))
            nseg = min(nseg, 3600)
        first = True
        for i in range(1, nseg + 1):
            t = i / nseg
            ang = a0 + sweep * t
            p = {ax_u: cu + r * math.cos(ang), ax_v: cv + r * math.sin(ang),
                 ax_w: s[ax_w] + (e[ax_w] - s[ax_w]) * t}
            if i == nseg:
                p = dict(e)
            line = emit_linear(1, p, feed, prefix if first else [])
            first = False
            if line:
                out.append(line + ((' ' + comment) if comment and i == 1 else ''))

    if feedmode == 93:
        # file had no M30: still leave the machine in normal feed mode
        idx = len(out)
        while idx and out[idx - 1].strip() in ('%', ''):
            idx -= 1
        out.insert(idx, 'G94')

    dst = a.output or os.path.splitext(a.input)[0] + '_A' + os.path.splitext(a.input)[1]
    with open(dst, 'w', newline='\r\n') as f:
        f.write('\n'.join(out) + '\n')

    print(f'Wrote {dst}')
    print(f'  units {units}, diameter {L(D)}, radius {L(R)}' + ('' if had_unit else '  (no unit given: taken as program units)'))
    if amin <= amax:
        span = amax - amin
        print(f'  A range {amin + 0.0:.1f} .. {amax + 0.0:.1f} deg  (span {span:.1f})'.replace('-0.0 ', '0.0 '))
        if span > 360.5:
            print('  WARNING: design spans more than one turn - it will overlap itself.')
    if zmin < float('inf'):
        print(f'  lowest Z above axis {L(zmin)} {units}  (deepest cut = {L(R - zmin)} below the surface)')
        if zmin < 0:
            print('  WARNING: toolpath goes below the rotation axis - check stock thickness / --zero.')
    print(f'  arcs linearised: {n_arcs}, moves written: {n_seg}')
    for w in sorted(warnings):
        print('  note: ' + w)


if __name__ == '__main__':
    main()
