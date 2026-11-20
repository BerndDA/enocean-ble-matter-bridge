#!/usr/bin/env python3
"""Create enocean-bridge.kicad_pcb from design.py (parts, nets) and placement.py.

Runs under KiCad's bundled Python (it needs the pcbnew module):

    /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 tools/gen_pcb.py

What it sets up: 4 copper layers, board outline, footprints with nets and the
link to their schematic symbol (so "Update PCB from Schematic" keeps working),
GND zones on all copper layers, the 2.4 GHz antenna keepout, and the JLCPCB
design rules and net classes in the project file. It does no routing.

It refuses to overwrite a board that already has tracks: once routing has
started, the board is edited in KiCad. --force overrides that.
"""
import json
import math
import os
import sys
import uuid as uuidlib

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import design      # noqa: E402
import placement   # noqa: E402

NAME = "enocean-bridge"
PCB = os.path.join(PROJ, NAME + ".kicad_pcb")
KICAD_FP = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"
NS = uuidlib.UUID("5a1d3c2e-0e0c-4e5a-9d1b-6e0c3a7b9f10")   # same as gen_schematic.py
ORIGIN = (100.0, 100.0)                                       # board corner on the KiCad canvas


def mm(x, y):
    return pcbnew.VECTOR2I(pcbnew.FromMM(ORIGIN[0] + x), pcbnew.FromMM(ORIGIN[1] + y))


def fp_lib_path(nick):
    if nick == "EnOcean":
        return os.path.join(PROJ, "..", "lib", "EnOcean.pretty")
    return os.path.join(KICAD_FP, nick + ".pretty")


def sym_uuid(ref):
    return str(uuidlib.uuid5(NS, "sym/" + ref))


def rect_poly(x0, y0, x1, y1):
    chain = pcbnew.SHAPE_LINE_CHAIN()
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        chain.Append(mm(x, y))
    chain.SetClosed(True)
    return chain


def add_zone(board, layer, net, outline, priority=0, name=""):
    z = pcbnew.ZONE(board)
    z.SetLayer(layer)
    z.SetNet(net)
    z.Outline().AddOutline(outline)
    z.SetAssignedPriority(priority)
    z.SetLocalClearance(pcbnew.FromMM(0.2))
    z.SetMinThickness(pcbnew.FromMM(0.15))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
    z.SetThermalReliefGap(pcbnew.FromMM(0.2))
    z.SetThermalReliefSpokeWidth(pcbnew.FromMM(0.25))
    z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    if name:
        z.SetZoneName(name)
    board.Add(z)
    return z


def add_keepout(board, outline, name):
    z = pcbnew.ZONE(board)
    z.SetIsRuleArea(True)
    z.SetLayerSet(pcbnew.LSET.AllCuMask())
    z.SetDoNotAllowZoneFills(True)
    z.SetDoNotAllowTracks(True)
    z.SetDoNotAllowVias(True)
    z.SetDoNotAllowPads(False)
    z.SetDoNotAllowFootprints(False)
    z.Outline().AddOutline(outline)
    z.SetZoneName(name)
    board.Add(z)


def load_netlist():
    """{'pins': {(ref, pad): net}, 'fields': {ref: {name: value}}} from kicad-cli's netlist."""
    import subprocess
    import tempfile
    import sexp
    from sexp import find, find1
    cli = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "n.net")
        subprocess.run([cli, "sch", "export", "netlist", "--format", "kicadsexpr", "-o", out,
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


def route_rf(board, nets):
    """The two RF paths and their ground vias. Everything else is routed in KiCad."""
    def pad(ref, num):
        p = board.FindFootprintByReference(ref).FindPadByNumber(num)
        v = p.GetPosition()
        return (round(pcbnew.ToMM(v.x) - ORIGIN[0], 4), round(pcbnew.ToMM(v.y) - ORIGIN[1], 4))

    def track(net, pts, width, layer=pcbnew.F_Cu):
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(mm(x0, y0))
            t.SetEnd(mm(x1, y1))
            t.SetWidth(pcbnew.FromMM(width))
            t.SetLayer(layer)
            t.SetNet(nets[net])
            t.SetLocked(True)           # the autorouter must route around these
            board.Add(t)

    def via(x, y, net="GND", d=0.45, drill=0.25):
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(mm(x, y))
        v.SetWidth(pcbnew.FromMM(d))
        v.SetDrill(pcbnew.FromMM(drill))
        v.SetNet(nets[net])
        v.SetLocked(True)
        board.Add(v)

    W = 0.37                        # 50 ohm CPWG, see write_project_rules
    y = placement.RF_Y
    # 2.4 GHz: ANT (inner pad) escapes at 45 deg into the channel between E24 and J24 as a
    # 0.15 mm neck, then widens to 50 ohm once clear of the outer pads
    ant = pad("U1", "H23")
    track("/RF_ANT", [ant, (ant[0] + (ant[1] - y), y), (43.1, y)], 0.15)
    track("/RF_ANT", [(43.1, y), pad("L1", "1")], W)               # over C19 pad 1
    track("/RF_M1", [pad("L1", "2"), pad("L2", "1")], W)           # over C20 pad 1
    feed = pad("AE1", "1")
    track("/RF_ANT_2G4", [pad("L2", "2"), (feed[0] - 1.0, y), (feed[0], y - 1.0), feed], W)
    # VSS_PA (inner pad) to the exposed pad, as in Nordic's reference
    vss = pad("U1", "F23")
    track("GND", [vss, (vss[0] - 0.4, vss[1])], 0.15)
    # VSS B7 (inner pad, top row) to the exposed pad the same way
    b7 = pad("U1", "B7")
    track("GND", [b7, (b7[0], b7[1] + 0.45)], 0.15)
    # inner-row pads with no escape gap between their outer neighbours: via in pad
    # (JLC minimum 0.25/0.15 mm, order with epoxy-filled and capped vias), routed on B.Cu
    for num, vnet in (("AC5", "/DECUSB"), ("AC13", "/NRESET")):
        vx, vy = pad("U1", num)
        via(vx, vy, net=vnet, d=0.25, drill=0.15)
    # VDD pins: each one straight out to its own via into the In2 +3V3 plane
    cx, cy = pad("U1", "EP")
    for num in ("B1", "A22", "AD14", "AD23", "W1"):
        px, py = pad("U1", num)
        dx, dy = px - cx, py - cy
        if abs(dx) >= abs(dy):
            to = (px + (0.85 if dx > 0 else -0.85), py)
        else:
            to = (px, py + (0.85 if dy > 0 else -0.85))
        track("+3V3", [(px, py), to], 0.2)
        via(to[0], to[1], net="+3V3")
    # C13 (4.7 uF at VDD W1) straight to W1's via
    wx, wy = pad("U1", "W1")
    track("+3V3", [(wx - 0.85, wy), pad("C13", "1")], 0.3)
    # VDDH (inner pad) tied to its neighbour W1 (normal-voltage mode)
    track("+3V3", [pad("U1", "Y2"), pad("U1", "W1")], 0.15)
    # USB-C ground pads (A1/B12 and A12/B1 share a pad position): a via right above each
    for num in ("A1", "A12"):
        gx, gy = pad("J1", num)
        track("GND", [(gx, gy), (gx, gy - 1.15)], 0.3)
        via(gx, gy - 1.15)
    # 32 MHz crystal ground pads straight to In1
    for num, (dx, dy) in (("4", (0.0, -1.0)), ("2", (0.95, 0.0))):
        gx, gy = pad("Y1", num)
        track("GND", [(gx, gy), (gx + dx, gy + dy)], 0.3)
        via(gx + dx, gy + dy)
    # every capacitor: a via at each GND / +3V3 pad, so the planes are one via away.
    # Try beyond the pad along the part's axis first, then to either side.
    def clear_spot(x, y, net, r=0.225, clr=0.2):
        P = pcbnew.VECTOR2I(pcbnew.FromMM(ORIGIN[0] + x), pcbnew.FromMM(ORIGIN[1] + y))
        if not (0.6 < x < placement.BOARD_W - 0.6 and 0.6 < y < placement.BOARD_H - 0.6):
            return False
        kx0, ky0, kx1, ky1 = placement.ANT_KEEPOUT
        if kx0 - 0.5 < x < kx1 + 0.5 and ky0 - 0.5 < y < ky1 + 0.5:
            return False
        for fp2 in board.GetFootprints():
            for z in fp2.Zones():
                if z.GetIsRuleArea() and z.GetDoNotAllowVias() and z.Outline().Collide(P, pcbnew.FromMM(r)):
                    return False
            for p2 in fp2.Pads():
                same = p2.GetNetname() == net
                bb = p2.GetBoundingBox()
                bb.Inflate(pcbnew.FromMM(r + (0.05 if same else clr)))
                if bb.Contains(P):
                    return False
        for t in board.GetTracks():
            if t.GetClass() == "PCB_VIA":
                if (t.GetPosition() - P).EuclideanNorm() < pcbnew.FromMM(2 * r + 0.3):
                    return False
            elif t.GetNetname() != net:
                seg = pcbnew.SEG(t.GetStart(), t.GetEnd())
                if seg.Distance(P) < pcbnew.FromMM(r + clr) + t.GetWidth() // 2:
                    return False
        return True

    for fp in board.GetFootprints():
        ref = fp.GetReference()
        if not ref.startswith("C") or ref in ("C19", "C20"):
            continue
        c = fp.GetPosition()
        for p in fp.Pads():
            net = p.GetNetname()
            if net not in ("GND", "+3V3"):
                continue
            px, py = pcbnew.ToMM(p.GetPosition().x) - ORIGIN[0], pcbnew.ToMM(p.GetPosition().y) - ORIGIN[1]
            ax, ay = pcbnew.ToMM(p.GetPosition().x - c.x), pcbnew.ToMM(p.GetPosition().y - c.y)
            n = math.hypot(ax, ay) or 1.0
            ux, uy = ax / n, ay / n
            half = max(pcbnew.ToMM(p.GetSize(pcbnew.F_Cu).x), pcbnew.ToMM(p.GetSize(pcbnew.F_Cu).y)) / 2
            for ox, oy in ((ux, uy), (-uy, ux), (uy, -ux)):
                d = half + 0.45
                vx, vy = px + ox * d, py + oy * d
                if clear_spot(vx, vy, net):
                    track(net, [(px, py), (vx, vy)], 0.3)
                    via(vx, vy, net=net)
                    break
            else:
                print(f"no fanout via for {ref}.{p.GetNumber()} ({net})")

    # exposed pad: 3 x 3 vias to the ground planes
    ep = pad("U1", "EP")
    for dx in (-1.5, 0.0, 1.5):
        for dy in (-1.5, 0.0, 1.5):
            via(ep[0] + dx, ep[1] + dy, d=0.4, drill=0.2)
    # ground: a via at every shunt's ground pad, and a fence above the line
    for ref in ("C19", "C20"):
        gx, gy = pad(ref, "2")
        track("GND", [(gx, gy), (gx, gy + 0.75)], 0.3)
        via(gx, gy + 0.75)
    for x in (44.6, 46.0, 47.4, 48.8, 50.2, 51.6, 53.0):
        via(x, y - 0.8)

    # 868 MHz: TCM RF_50 -> node; node -> R7 -> whip hole
    node = placement.RF_NODE_868
    rf = pad("U4", "2")
    track("/RF_868", [rf, node], W)
    track("/RF_868", [node, pad("R7", "1")], W)
    track("/ANT_868", [pad("R7", "2"), pad("TP1", "1")], W)
    for num in ("1", "3"):          # TCM ground pads next to RF_50, stitched to the planes
        gx, gy = pad("U4", num)
        track("GND", [(gx, gy), (gx - 1.5, gy)], 0.3)
        via(gx - 1.5, gy)


def write_dru():
    """Custom rule: the 2.4 GHz neck may pass the nRF's pads at 0.1 mm (JLC minimum)."""
    with open(os.path.join(PROJ, NAME + ".kicad_dru"), "w") as f:
        f.write("""(version 1)

# The ANT pad is an inner-row aQFN pad; its escape between pads E24 and J24 only
# fits with the fab's minimum clearance. Elsewhere RF nets keep 0.2 mm (CPWG gap).
(rule "RF escape at nRF52840"
  (condition "(A.NetClass == 'RF' || B.NetClass == 'RF') && A.intersectsCourtyard('U1') && B.intersectsCourtyard('U1')")
  (constraint clearance (min 0.1mm)))

# Vias in the pads of AC5 (DECUSB) and AC13 (nRESET): JLC's minimum via, epoxy-filled
# and capped. Only allowed inside the nRF52840's courtyard.
(rule "via in pad at nRF52840"
  (condition "A.Type == 'Via' && A.intersectsCourtyard('U1')")
  (constraint via_diameter (min 0.25mm))
  (constraint hole_size (min 0.15mm))
  (constraint annular_width (min 0.05mm)))
""")


def write_project_rules():
    """Net classes and JLCPCB 4-layer limits into the .kicad_pro (KiCad keeps them there)."""
    path = os.path.join(PROJ, NAME + ".kicad_pro")
    pro = json.load(open(path)) if os.path.exists(path) else {}

    def cls(name, track, clearance, via_d, via_drill, prio):
        return {"name": name, "track_width": track, "clearance": clearance,
                "via_diameter": via_d, "via_drill": via_drill,
                "microvia_diameter": 0.3, "microvia_drill": 0.1,
                "diff_pair_width": 0.2, "diff_pair_gap": 0.2, "diff_pair_via_gap": 0.25,
                "bus_width": 12, "wire_width": 6, "line_style": 0, "priority": prio,
                "pcb_color": "rgba(0, 0, 0, 0.000)", "schematic_color": "rgba(0, 0, 0, 0.000)"}

    pro["net_settings"] = {
        "classes": [
            cls("Default", 0.15, 0.15, 0.45, 0.25, 2147483647),
            # 50 ohm grounded coplanar waveguide on JLC04161H-7628 (L1-L2 0.2104 mm, er 4.4):
            # 0.37 mm track, 0.2 mm gap to the ground pour
            cls("RF", 0.37, 0.2, 0.45, 0.25, 0),
            cls("Power", 0.3, 0.15, 0.45, 0.25, 1),
        ],
        "meta": {"version": 4},
        "net_colors": None,
        "netclass_assignments": None,
        "netclass_patterns": [
            {"netclass": "RF", "pattern": "/RF_*"},
            {"netclass": "RF", "pattern": "/ANT_868"},
            {"netclass": "Power", "pattern": "+3V3"},
            {"netclass": "Power", "pattern": "VBUS"},
            {"netclass": "Power", "pattern": "/VBUS_*"},
            {"netclass": "Power", "pattern": "/VDD_TCM"},
        ],
    }
    board = pro.setdefault("board", {})
    ds = board.setdefault("design_settings", {})
    # JLCPCB multilayer capabilities (checked against their published rules; keep margins)
    ds["rules"] = {
        "allow_blind_buried_vias": False,
        "allow_microvias": False,
        "max_error": 0.005,
        "min_clearance": 0.1,
        "min_connection": 0.0,
        "min_copper_edge_clearance": 0.3,
        "min_groove_width": 0.0,
        "min_hole_clearance": 0.2,
        "min_hole_to_hole": 0.25,
        "min_microvia_diameter": 0.2,
        "min_microvia_drill": 0.1,
        "min_resolved_spokes": 2,
        "min_silk_clearance": 0.0,
        "min_text_height": 0.8,
        "min_text_thickness": 0.12,
        "min_through_hole_diameter": 0.2,
        "min_track_width": 0.09,           # JLC 4/6-layer: 3.5 mil track and spacing
        "min_via_annular_width": 0.1,
        "min_via_diameter": 0.4,
        "solder_mask_to_copper_clearance": 0.0,
        "use_height_for_length_calcs": True,
    }
    ds["track_widths"] = [0.0, 0.1, 0.15, 0.2, 0.3, 0.37, 0.5]
    ds["via_dimensions"] = [{"diameter": 0.0, "drill": 0.0},
                            {"diameter": 0.4, "drill": 0.2},
                            {"diameter": 0.45, "drill": 0.25},
                            {"diameter": 0.6, "drill": 0.3}]
    pro.setdefault("meta", {"filename": NAME + ".kicad_pro", "version": 3})
    with open(path, "w") as f:
        json.dump(pro, f, indent=2)
        f.write("\n")


def main():
    force = "--force" in sys.argv
    if os.path.exists(PCB) and not force:
        old = pcbnew.LoadBoard(PCB)
        if len(old.GetTracks()) > 0:
            sys.exit(f"{PCB} has {len(old.GetTracks())} tracks/vias; not overwriting (use --force)")

    board = pcbnew.BOARD()
    board.SetCopperLayerCount(4)
    ds = board.GetDesignSettings()
    ds.SetBoardThickness(pcbnew.FromMM(1.6))

    # nets and fields come from KiCad's own netlist of the schematic, exactly what
    # "Update PCB from Schematic" would use (label nets "/X", "unconnected-(...)" pins)
    sch = load_netlist()
    nets = {}
    for (_ref, _pin), n in sch["pins"].items():
        if n not in nets:
            ni = pcbnew.NETINFO_ITEM(board, n)
            board.Add(ni)
            nets[n] = ni

    # outline
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
        # small passives, crystals and test pads: reference only on the fab layer
        if ref.rstrip("0123456789") in ("C", "R", "L", "FB", "TP", "Y", "H", "F"):
            fp.Reference().SetVisible(False)
        else:
            fp.Reference().SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(0.8), pcbnew.FromMM(0.8)))
            fp.Reference().SetTextThickness(pcbnew.FromMM(0.12))
        x, y, rot, side = placement.PLACE[ref]
        board.Add(fp)
        fp.SetPosition(mm(x, y))
        if side == "B":
            fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        fp.SetOrientationDegrees(rot)
        for pad in fp.Pads():
            num = pad.GetNumber()
            # ICs, connectors, crystal and its caps: solid pour connection on GND
            # (thermal spokes get starved between tracks there)
            if sch["pins"].get((ref, num)) == "GND" and (ref[0] in "UJY" or ref in ("C15", "C16")):
                pad.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_FULL)
            net = sch["pins"].get((ref, num))
            if net:
                pad.SetNet(nets[net])
    if missing:
        sys.exit("no placement for: " + " ".join(missing))

    # zones: In1 is the solid GND reference under both radios, In2 the +3V3 plane
    # (decoupling caps and VDD pins reach it with one via), GND pours on top and bottom
    W, H = placement.BOARD_W, placement.BOARD_H
    gnd = nets["GND"]  # power net, global name
    for layer in (pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.B_Cu):
        add_zone(board, layer, gnd, rect_poly(0, 0, W, H), name="GND")
    add_zone(board, pcbnew.In2_Cu, nets["+3V3"], rect_poly(0, 0, W, H), name="+3V3")
    add_keepout(board, rect_poly(*placement.ANT_KEEPOUT), "2.4 GHz antenna keepout")

    # silkscreen
    def text(s, x, y, size=1.0, layer=pcbnew.F_SilkS):
        t = pcbnew.PCB_TEXT(board)
        t.SetText(s)
        t.SetPosition(mm(x, y))
        t.SetLayer(layer)
        t.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(size), pcbnew.FromMM(size)))
        t.SetTextThickness(pcbnew.FromMM(size * 0.15))
        board.Add(t)
    text("EnOcean-Matter bridge v0.1", 15.4, 24.6, 0.8)

    route_rf(board, nets)

    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())
    pcbnew.SaveBoard(PCB, board)
    write_project_rules()
    write_dru()
    print(f"{len(design.PARTS)} footprints, {len(nets)} nets -> {os.path.basename(PCB)}")


if __name__ == "__main__":
    main()
