#!/usr/bin/env python3
"""Ground stitching for enocean-carrier.kicad_pcb (2 layers), run after routing.

Runs under KiCad's bundled Python:  $KPY tools/stitch.py

1. Reports signal vias DRC calls dangling (it doesn't remove them).
2. Places GND vias on a 1.6 mm grid wherever they keep clear of other nets,
   the antenna keepout and the board edge, so every piece of the top and
   bottom GND pours connect to each other.
3. Refills the zones, runs DRC and removes stitching vias DRC reports as
   dangling or in conflict, then saves.

Earlier stitching vias (marked by the 0.45/0.25 size and an unlocked GND via
not touching a track) are removed and placed again, so the script can be rerun.
"""
import json
import math
import os
import subprocess
import sys
import tempfile

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import placement  # noqa: E402

PCB = os.path.join(PROJ, "enocean-carrier.kicad_pcb")
CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
ORIGIN = (100.0, 100.0)
VIA_D, VIA_DRILL = 0.6, 0.3
STEP = 2.0
CLEAR = 0.2                       # copper clearance to other nets (Default/RF class)
EDGE = 0.6


def to_mm(v):
    return pcbnew.ToMM(v.x) - ORIGIN[0], pcbnew.ToMM(v.y) - ORIGIN[1]


def seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def box_dist(px, py, x0, y0, x1, y1):
    dx = max(x0 - px, 0, px - x1)
    dy = max(y0 - py, 0, py - y1)
    return math.hypot(dx, dy)


def is_stitch(v):
    return (v.GetNetname() == "GND" and not v.IsLocked()
            and abs(pcbnew.ToMM(v.GetWidth(pcbnew.F_Cu)) - VIA_D) < 1e-3
            and abs(pcbnew.ToMM(v.GetDrillValue()) - VIA_DRILL) < 1e-3)


def drc_dangling(any_net=False):
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "drc.json")
        subprocess.run([CLI, "pcb", "drc", "--format", "json", "--severity-all", "-o", out, PCB],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        rep = json.load(open(out))
    bad = set()
    for v in rep.get("violations", []):
        for it in v.get("items", []):
            desc = it.get("description", "")
            if any_net and v["type"] == "via_dangling" and desc.startswith("Via ["):
                p = it["pos"]
                bad.add((round(p["x"], 3), round(p["y"], 3)))
            elif desc.startswith("Via [GND]") and v["type"] in (
                    "via_dangling", "clearance", "hole_clearance", "hole_to_hole", "starved_thermal",
                    "shorting_items", "copper_edge_clearance"):
                p = it["pos"]
                bad.add((round(p["x"], 3), round(p["y"], 3)))
    return bad


def main():
    board = pcbnew.LoadBoard(PCB)
    tracks = list(board.GetTracks())

    # 1. vias DRC reports as dangling (unlocked, not GND); 2. old stitching vias
    dangling = drc_dangling(any_net=True)
    removed = restitched = 0
    ends = {}
    for t in tracks:
        if t.GetClass() == "PCB_TRACK":
            for p in (t.GetStart(), t.GetEnd()):
                ends.setdefault((p.x, p.y, t.GetNetCode()), set()).add(t.GetLayer())
    for v in [t for t in tracks if t.GetClass() == "PCB_VIA"]:
        if v.IsLocked():
            continue
        key = (round(pcbnew.ToMM(v.GetPosition().x), 3), round(pcbnew.ToMM(v.GetPosition().y), 3))
        if v.GetNetname() != "GND" and key in dangling:
            # report only: DRC can call a via in a pad "dangling" although it connects
            print(f"note: DRC calls the {v.GetNetname()} via at ({key[0] - ORIGIN[0]:.2f}, {key[1] - ORIGIN[1]:.2f}) dangling")
        elif is_stitch(v) and not ends.get((v.GetPosition().x, v.GetPosition().y, v.GetNetCode())):
            board.Remove(v)
            restitched += 1

    # obstacles: everything not on GND
    segs, boxes, holes, vias = [], [], [], []
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA":
            vias.append(to_mm(t.GetPosition()))
        elif t.GetNetname() != "GND":
            (ax, ay), (bx, by) = to_mm(t.GetStart()), to_mm(t.GetEnd())
            segs.append((ax, ay, bx, by, pcbnew.ToMM(t.GetWidth()) / 2))
    for fp in board.GetFootprints():
        for p in fp.Pads():
            bb = p.GetBoundingBox()
            x0, y0 = to_mm(pcbnew.VECTOR2I(bb.GetLeft(), bb.GetTop()))
            x1, y1 = to_mm(pcbnew.VECTOR2I(bb.GetRight(), bb.GetBottom()))
            gnd = p.GetNetname() == "GND"
            # GND pads: no via inside them (paste), other pads: full clearance
            boxes.append((x0, y0, x1, y1, 0.05 if gnd else CLEAR))
            if p.HasHole():
                holes.append(to_mm(p.GetPosition()))
    kx0, ky0, kx1, ky1 = placement.ANT_KEEPOUT
    rule_areas = [z for z in board.Zones() if z.GetIsRuleArea() and z.GetDoNotAllowVias()]
    for fp in board.GetFootprints():
        rule_areas += [z for z in fp.Zones() if z.GetIsRuleArea() and z.GetDoNotAllowVias()]

    def in_rule_area(x, y):
        p = pcbnew.VECTOR2I(pcbnew.FromMM(ORIGIN[0] + x), pcbnew.FromMM(ORIGIN[1] + y))
        m = pcbnew.FromMM(r + 0.1)
        return any(z.Outline().Collide(p, m) for z in rule_areas)

    gnd = board.FindNet("GND")
    r = VIA_D / 2
    added = 0
    y = EDGE + r
    while y < placement.BOARD_H - EDGE - r:
        x = EDGE + r
        while x < placement.BOARD_W - EDGE - r:
            ok = not (kx0 - 0.6 < x < kx1 + 0.6 and ky0 - 0.6 < y < ky1 + 0.6)
            ok = ok and not in_rule_area(x, y)
            ok = ok and all(seg_dist(x, y, *s[:4]) >= s[4] + r + CLEAR for s in segs)
            ok = ok and all(box_dist(x, y, *b[:4]) >= r + b[4] for b in boxes)
            ok = ok and all(math.hypot(x - hx, y - hy) >= 1.3 for hx, hy in holes)
            ok = ok and all(math.hypot(x - vx, y - vy) >= VIA_D + 0.3 for vx, vy in vias)
            if ok:
                v = pcbnew.PCB_VIA(board)
                v.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(ORIGIN[0] + x), pcbnew.FromMM(ORIGIN[1] + y)))
                v.SetWidth(pcbnew.FromMM(VIA_D))
                v.SetDrill(pcbnew.FromMM(VIA_DRILL))
                v.SetNet(gnd)
                board.Add(v)
                vias.append((x, y))
                added += 1
            x += STEP
        y += STEP

    pcbnew.ZONE_FILLER(board).Fill(board.Zones())

    # pour pieces the grid missed (small islands around pads): one via inside each
    def unstitched():
        gvias = [t.GetPosition() for t in board.GetTracks() if t.GetClass() == "PCB_VIA" and t.GetNetname() == "GND"]
        gvias += [p.GetPosition() for fp in board.GetFootprints() for p in fp.Pads()
                  if p.GetNetname() == "GND" and p.HasHole()]
        out = []
        for z in board.Zones():
            if z.GetIsRuleArea() or z.GetNetname() != "GND":
                continue
            for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
                if not z.IsOnLayer(layer):
                    continue
                ps = z.GetFilledPolysList(layer)
                for i in range(ps.OutlineCount()):
                    ol = ps.Outline(i)
                    if not any(ol.PointInside(v) for v in gvias):
                        out.append(ol)
        return out

    def fits(x, y):
        return (not in_rule_area(x, y)
                and all(seg_dist(x, y, *s[:4]) >= s[4] + r + CLEAR for s in segs)
                and all(box_dist(x, y, *b[:4]) >= r + b[4] for b in boxes)
                and all(math.hypot(x - hx, y - hy) >= 1.3 for hx, hy in holes)
                and all(math.hypot(x - vx, y - vy) >= VIA_D + 0.25 for vx, vy in vias))

    islands = 0
    for ol in unstitched():
        bb = ol.BBox()
        x0, y0 = to_mm(pcbnew.VECTOR2I(bb.GetLeft(), bb.GetTop()))
        x1, y1 = to_mm(pcbnew.VECTOR2I(bb.GetRight(), bb.GetBottom()))
        done = False
        yy = y0 + r
        while yy <= y1 - r and not done:
            xx = x0 + r
            while xx <= x1 - r and not done:
                p = pcbnew.VECTOR2I(pcbnew.FromMM(ORIGIN[0] + xx), pcbnew.FromMM(ORIGIN[1] + yy))
                # the whole via pad must sit inside the island
                if ol.PointInside(p) and all(ol.PointInside(pcbnew.VECTOR2I(p.x + int(dx), p.y + int(dy)))
                                             for dx, dy in ((pcbnew.FromMM(r), 0), (-pcbnew.FromMM(r), 0),
                                                            (0, pcbnew.FromMM(r)), (0, -pcbnew.FromMM(r)))) \
                        and fits(xx, yy):
                    v = pcbnew.PCB_VIA(board)
                    v.SetPosition(p)
                    v.SetWidth(pcbnew.FromMM(VIA_D))
                    v.SetDrill(pcbnew.FromMM(VIA_DRILL))
                    v.SetNet(gnd)
                    board.Add(v)
                    vias.append((xx, yy))
                    islands += 1
                    done = True
                xx += 0.1
            yy += 0.1
        if not done:
            print(f"no room for a via in the GND island at x {x0:.2f}..{x1:.2f}, y {y0:.2f}..{y1:.2f}")
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    added += islands

    # groups of pour pieces joined to each other but not to the main GND: one bridging
    # via where a piece of such a group lies over main-group copper on the other layer
    def pour_groups():
        pieces = []
        for z in board.Zones():
            if z.GetIsRuleArea() or z.GetNetname() != "GND":
                continue
            for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
                if z.IsOnLayer(layer):
                    ps = z.GetFilledPolysList(layer)
                    pieces += [(layer, ps.Outline(i)) for i in range(ps.OutlineCount())]
        links = [t.GetPosition() for t in board.GetTracks() if t.GetClass() == "PCB_VIA" and t.GetNetname() == "GND"]
        links += [p.GetPosition() for fp in board.GetFootprints() for p in fp.Pads()
                  if p.GetNetname() == "GND" and p.HasHole()]
        parent = list(range(len(pieces)))

        def root(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        for v in links:
            inside = [i for i, (_l, ol) in enumerate(pieces) if ol.PointInside(v)]
            for k in inside[1:]:
                parent[root(k)] = root(inside[0])
        groups = {}
        for i in range(len(pieces)):
            groups.setdefault(root(i), []).append(pieces[i])
        return sorted(groups.values(), key=lambda g: -sum(ol.Area() for _l, ol in g))

    def inside_r(ol, p):
        d = pcbnew.FromMM(r)
        return ol.PointInside(p) and all(ol.PointInside(pcbnew.VECTOR2I(p.x + dx, p.y + dy))
                                         for dx, dy in ((d, 0), (-d, 0), (0, d), (0, -d)))

    bridges = 0
    for _round in range(5):
        groups = pour_groups()
        if len(groups) < 2:
            break
        main = groups[0]
        done = False
        for layer, ol in [pc for g in groups[1:] for pc in g]:
            others = [o for (l2, o) in main if l2 != layer]
            bb = ol.BBox()
            x0, y0 = to_mm(pcbnew.VECTOR2I(bb.GetLeft(), bb.GetTop()))
            x1, y1 = to_mm(pcbnew.VECTOR2I(bb.GetRight(), bb.GetBottom()))
            yy = y0
            while yy <= y1 and not done:
                xx = x0
                while xx <= x1 and not done:
                    p = pcbnew.VECTOR2I(pcbnew.FromMM(ORIGIN[0] + xx), pcbnew.FromMM(ORIGIN[1] + yy))
                    if inside_r(ol, p) and any(inside_r(o, p) for o in others) and fits(xx, yy):
                        v = pcbnew.PCB_VIA(board)
                        v.SetPosition(p)
                        v.SetWidth(pcbnew.FromMM(VIA_D))
                        v.SetDrill(pcbnew.FromMM(VIA_DRILL))
                        v.SetNet(gnd)
                        board.Add(v)
                        vias.append((xx, yy))
                        bridges += 1
                        done = True
                    xx += 0.1
                yy += 0.1
            if done:
                break
        if not done:
            print(f"{len(groups) - 1} GND pour group(s) still separate: no room for a bridging via")
            break
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    added += bridges
    pcbnew.SaveBoard(PCB, board)

    # 3. drop stitching vias that DRC doesn't like
    bad = drc_dangling()
    dropped = 0
    if bad:
        board = pcbnew.LoadBoard(PCB)
        for v in [t for t in board.GetTracks() if t.GetClass() == "PCB_VIA" and is_stitch(t)]:
            key = (round(pcbnew.ToMM(v.GetPosition().x), 3), round(pcbnew.ToMM(v.GetPosition().y), 3))
            if key in bad:
                board.Remove(v)
                dropped += 1
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
        pcbnew.SaveBoard(PCB, board)
    print(f"removed {removed} dangling signal vias, {restitched} old stitching vias; "
          f"added {added} GND vias, dropped {dropped} after DRC")


if __name__ == "__main__":
    main()
