#!/usr/bin/env python3
"""Create enocean-carrier.kicad_pcb from the schematic's netlist and placement.py.

Runs under KiCad's bundled Python (it needs the pcbnew module):

    $KPY tools/gen_pcb.py [--force]

2 layers, board outline, footprints with nets and the link to their schematic
symbol, GND pours on both layers, JLCPCB 2-layer rules and net classes in the
project file, and the 868 MHz path routed. route.py does the rest.

It refuses to overwrite a board that already has tracks beyond the ones it
draws itself unless --force is given.
"""
import json
import os
import subprocess
import sys
import tempfile
import uuid as uuidlib

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import design      # noqa: E402
import placement   # noqa: E402
import sexp        # noqa: E402
from sexp import find, find1  # noqa: E402

NAME = "enocean-carrier"
PCB = os.path.join(PROJ, NAME + ".kicad_pcb")
KICAD_FP = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"
CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
NS = uuidlib.UUID("7c0f6a52-3b1e-4d8a-a6f4-2e9d51c8b7a3")   # same as gen_schematic.py
ORIGIN = (100.0, 100.0)
RF_W = 1.0           # 868 MHz line: 1.0 mm with 0.2 mm gap on 1.6 mm FR4, ~54 ohm (1.2 mm = 50 ohm)


def mm(x, y):
    return pcbnew.VECTOR2I(pcbnew.FromMM(ORIGIN[0] + x), pcbnew.FromMM(ORIGIN[1] + y))


def fp_lib_path(nick):
    if nick in design.LIBS:
        return os.path.join(PROJ, "..", "lib", nick + ".pretty")
    return os.path.join(KICAD_FP, nick + ".pretty")


def sym_uuid(ref):
    return str(uuidlib.uuid5(NS, "sym/" + ref))


def rect_poly(x0, y0, x1, y1):
    chain = pcbnew.SHAPE_LINE_CHAIN()
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        chain.Append(mm(x, y))
    chain.SetClosed(True)
    return chain


def load_netlist():
    """{'pins': {(ref, pad): net}, 'fields': {ref: {name: value}}} from kicad-cli's netlist."""
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "n.net")
        subprocess.run([CLI, "sch", "export", "netlist", "--format", "kicadsexpr", "-o", out,
                        os.path.join(PROJ, NAME + ".kicad_sch")],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        t = sexp.parse(open(out).read())
    pins = {}
    for n in find(find1(t, "nets"), "net"):
        name = str(find1(n, "name")[1])
        for node in find(n, "node"):
            pins[(str(find1(node, "ref")[1]), str(find1(node, "pin")[1]))] = name
    fields = {}
    for c in find(find1(t, "components"), "comp"):
        ref = str(find1(c, "ref")[1])
        fl = {}
        for k in ("datasheet", "description"):
            v = find1(c, k)
            if v and len(v) > 1:
                fl[k.capitalize()] = str(v[1])
        fs = find1(c, "fields")
        for fld in (find(fs, "field") if fs else []):
            name = str(find1(fld, "name")[1])
            val = str(fld[2]) if len(fld) > 2 and not isinstance(fld[2], list) else ""
            if name not in ("Reference", "Value", "Footprint"):
                fl[name] = val
        fields[ref] = fl
    return {"pins": pins, "fields": fields}


def write_project_rules():
    """Net classes and JLCPCB 2-layer limits (with margin) into the .kicad_pro."""
    path = os.path.join(PROJ, NAME + ".kicad_pro")
    pro = json.load(open(path)) if os.path.exists(path) else {}

    def cls(name, track, clearance, prio):
        return {"name": name, "track_width": track, "clearance": clearance,
                "via_diameter": 0.6, "via_drill": 0.3,
                "microvia_diameter": 0.3, "microvia_drill": 0.1,
                "diff_pair_width": 0.2, "diff_pair_gap": 0.25, "diff_pair_via_gap": 0.25,
                "bus_width": 12, "wire_width": 6, "line_style": 0, "priority": prio,
                "pcb_color": "rgba(0, 0, 0, 0.000)", "schematic_color": "rgba(0, 0, 0, 0.000)"}

    pro["net_settings"] = {
        "classes": [cls("Default", 0.25, 0.2, 2147483647), cls("RF", RF_W, 0.2, 0), cls("Power", 0.5, 0.2, 1)],
        "meta": {"version": 4}, "net_colors": None, "netclass_assignments": None,
        "netclass_patterns": [
            {"netclass": "RF", "pattern": "/RF_*"},
            {"netclass": "RF", "pattern": "/ANT_868"},
            {"netclass": "Power", "pattern": "+3V3"},
            {"netclass": "Power", "pattern": "/VDD_TCM"},
        ],
    }
    ds = pro.setdefault("board", {}).setdefault("design_settings", {})
    ds["rules"] = {
        "allow_blind_buried_vias": False, "allow_microvias": False, "max_error": 0.005,
        "min_clearance": 0.15, "min_connection": 0.0, "min_copper_edge_clearance": 0.3,
        "min_groove_width": 0.0, "min_hole_clearance": 0.25, "min_hole_to_hole": 0.25,
        "min_microvia_diameter": 0.2, "min_microvia_drill": 0.1, "min_resolved_spokes": 2,
        "min_silk_clearance": 0.0, "min_text_height": 0.8, "min_text_thickness": 0.12,
        "min_through_hole_diameter": 0.3, "min_track_width": 0.15, "min_via_annular_width": 0.13,
        "min_via_diameter": 0.6, "solder_mask_to_copper_clearance": 0.0,
        "use_height_for_length_calcs": True,
    }
    ds["track_widths"] = [0.0, 0.25, 0.5, RF_W]
    ds["via_dimensions"] = [{"diameter": 0.0, "drill": 0.0}, {"diameter": 0.6, "drill": 0.3}]
    pro.setdefault("meta", {"filename": NAME + ".kicad_pro", "version": 3})
    with open(path, "w") as f:
        json.dump(pro, f, indent=2)
        f.write("\n")


def main():
    if os.path.exists(PCB) and "--force" not in sys.argv:
        old = pcbnew.LoadBoard(PCB)
        if len(old.GetTracks()) > 0:
            sys.exit(f"{PCB} has {len(old.GetTracks())} tracks/vias; not overwriting (use --force)")

    board = pcbnew.BOARD()
    board.SetCopperLayerCount(2)
    board.GetDesignSettings().SetBoardThickness(pcbnew.FromMM(1.6))

    sch = load_netlist()
    nets = {}
    for (_ref, _pin), n in sch["pins"].items():
        if n not in nets:
            ni = pcbnew.NETINFO_ITEM(board, n)
            board.Add(ni)
            nets[n] = ni

    edge = pcbnew.PCB_SHAPE(board)
    edge.SetShape(pcbnew.SHAPE_T_RECT)
    edge.SetStart(mm(0, 0))
    edge.SetEnd(mm(placement.BOARD_W, placement.BOARD_H))
    edge.SetLayer(pcbnew.Edge_Cuts)
    edge.SetWidth(pcbnew.FromMM(0.1))
    board.Add(edge)

    missing = []
    for p in design.PARTS:
        ref = p["ref"]
        if ref not in placement.PLACE:
            missing.append(ref)
            continue
        nick, fpname = p["footprint"].split(":")
        fp = pcbnew.FootprintLoad(fp_lib_path(nick), fpname)
        if fp is None:
            sys.exit(f"{ref}: footprint {p['footprint']} not found")
        fp.SetFPID(pcbnew.LIB_ID(nick, fpname))
        fp.SetReference(ref)
        fp.SetValue(p["value"])
        fp.SetPath(pcbnew.KIID_PATH("/" + sym_uuid(ref)))
        fp.SetDNP(bool(p["dnp"]))
        fp.SetExcludedFromBOM(not p["in_bom"])
        for fname, fval in sch["fields"].get(ref, {}).items():
            fp.SetField(fname, fval)
            if fname not in ("Reference", "Value"):
                fp.GetField(fname).SetVisible(False)
        if ref in ("U2", "TP1", "H1", "H2", "R4", "R5", "R6", "D1", "D2", "D3"):   # obvious or tiny parts: labels would sit on others
            fp.Reference().SetVisible(False)
        fp.Reference().SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(0.9), pcbnew.FromMM(0.9)))
        fp.Reference().SetTextThickness(pcbnew.FromMM(0.14))
        x, y, rot, side = placement.PLACE[ref]
        board.Add(fp)
        fp.SetPosition(mm(x, y))
        if side == "B":
            fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        fp.SetOrientationDegrees(rot)
        for pad in fp.Pads():
            net = sch["pins"].get((ref, pad.GetNumber()))
            if net:
                pad.SetNet(nets[net])
            # through-hole GND pads (switches, Pro Micro): solid to the pours, no starved spokes
            if net == "GND" and pad.HasHole():
                pad.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_FULL)
    if missing:
        sys.exit("no placement for: " + " ".join(missing))

    W, H = placement.BOARD_W, placement.BOARD_H
    for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
        z = pcbnew.ZONE(board)
        z.SetLayer(layer)
        z.SetNet(nets["GND"])
        z.Outline().AddOutline(rect_poly(0, 0, W, H))
        z.SetLocalClearance(pcbnew.FromMM(0.25))
        z.SetMinThickness(pcbnew.FromMM(0.25))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        z.SetThermalReliefGap(pcbnew.FromMM(0.3))
        z.SetThermalReliefSpokeWidth(pcbnew.FromMM(0.4))
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        z.SetZoneName("GND")
        board.Add(z)

    route_868(board, nets)

    for s, x, y, size, layer in (("EnOcean carrier v0.2", 32.0, 31.6, 1.0, pcbnew.B_SilkS),
                                 ("WHIP", 44.4, 4.6, 0.8, pcbnew.F_SilkS)):
        t = pcbnew.PCB_TEXT(board)
        t.SetText(s)
        t.SetPosition(mm(x, y))
        t.SetLayer(layer)
        t.SetMirrored(layer == pcbnew.B_SilkS)
        t.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(size), pcbnew.FromMM(size)))
        t.SetTextThickness(pcbnew.FromMM(size * 0.15))
        board.Add(t)

    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(PCB, board)
    write_project_rules()
    print(f"{len(design.PARTS)} footprints, {len(nets)} nets -> {os.path.basename(PCB)}")


def route_868(board, nets):
    """TCM RF_50 up and right to the node; node -> R2 -> whip hole, node -> R3 -> u.FL; C4 shunt on the line."""
    def pad(ref, num):
        v = board.FindFootprintByReference(ref).FindPadByNumber(num).GetPosition()
        return (round(pcbnew.ToMM(v.x) - ORIGIN[0], 4), round(pcbnew.ToMM(v.y) - ORIGIN[1], 4))

    def track(net, pts, width):
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(mm(x0, y0))
            t.SetEnd(mm(x1, y1))
            t.SetWidth(pcbnew.FromMM(width))
            t.SetLayer(pcbnew.F_Cu)
            t.SetNet(nets[net])
            t.SetLocked(True)
            board.Add(t)

    def via(x, y):
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(mm(x, y))
        v.SetWidth(pcbnew.FromMM(0.6))
        v.SetDrill(pcbnew.FromMM(0.3))
        v.SetNet(nets["GND"])
        v.SetLocked(True)
        board.Add(v)

    node = placement.RF_NODE_868
    y = placement.RF_Y
    rf = pad("U2", "2")
    # 0.6 mm neck off the TCM pad (its neighbours, pads 1 and 3, are GND at 1.0 mm pitch)
    neck = (rf[0], rf[1] - 1.5)
    track("/RF_868", [rf, neck], 0.6)
    track("/RF_868", [neck, (rf[0], y), node, pad("R2", "1")], RF_W)     # over C4 pad 1
    track("/RF_868", [node, pad("R3", "1")], RF_W)
    track("/ANT_868", [pad("R2", "2"), pad("TP1", "1")], RF_W)
    r3, j1 = pad("R3", "2"), pad("J1", "1")
    track("/RF_UFL", [r3, (r3[0], j1[1]), j1], RF_W)              # down, then right to the edge
    gx, gy = pad("C4", "2")
    track("GND", [(gx, gy), (gx, gy + 1.1)], 0.5)
    via(gx, gy + 1.1)
    # TCM corner GND pads: a fixed via each, so routing can't cut them off the pours
    for num, (dx, dy) in (("23", (1.55, 0.9)), ("15", (0.0, 2.5)), ("6", (0.0, -1.8))):
        gx, gy = pad("U2", num)
        track("GND", [(gx, gy), (gx + dx, gy + dy)], 0.4)
        via(gx + dx, gy + dy)


if __name__ == "__main__":
    main()
