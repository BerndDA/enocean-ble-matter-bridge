#!/usr/bin/env python3
"""Generate enocean-carrier.kicad_sch (and the project's library tables) from design.py.

Every symbol comes from KiCad's own libraries (or ../lib for the TCM 515 and the Pro Micro) and is
embedded in the schematic. Parts sit in framed functional groups (design.GROUPS).
Inside a group, pins connect by wires (design.WIRES); a pin without a wire gets a
net label or power symbol on its end, and unused pins get a no-connect flag.
Every wired cluster carries its net name: from design.TAGS, or else a label the
generator puts on the cluster's longest wire. Junction dots are added where three
or more wire ends or pins meet. Regenerating overwrites the schematic: edit
design.py, not the .kicad_sch.

    python3 tools/gen_schematic.py [--kicad /Applications/KiCad/KiCad.app]
"""
import argparse
import os
import uuid as uuidlib

import sexp
from sexp import Q, find, find1, prop
import design

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
NAME = "enocean-carrier"
NS = uuidlib.UUID("7c0f6a52-3b1e-4d8a-a6f4-2e9d51c8b7a3")   # gen_pcb.py links footprints by it


def uid(*parts):
    """Stable UUIDs, so regenerating doesn't churn the file."""
    return Q(str(uuidlib.uuid5(NS, "/".join(map(str, parts)))))


def r2(v):
    return round(v, 4)


class Libs:
    def __init__(self, kicad):
        self.dirs = {
            "*": os.path.join(kicad, "Contents/SharedSupport/symbols"),
            "EnOcean": os.path.join(PROJ, "..", "lib"),
            "Modules": os.path.join(PROJ, "..", "lib"),
        }
        self.cache = {}

    def lib(self, name):
        if name not in self.cache:
            d = self.dirs.get(name, self.dirs["*"])
            self.cache[name] = {s[1]: s for s in find(sexp.parse(open(os.path.join(d, name + ".kicad_sym")).read()), "symbol")}
        return self.cache[name]

    def flat(self, lib_id):
        """The library symbol with 'extends' resolved, renamed to lib_id."""
        libname, name = lib_id.split(":")
        syms = self.lib(libname)
        s = syms[name]
        ext = find1(s, "extends")
        if ext:
            base = self.flat(f"{libname}:{ext[1]}")
            base_name = ext[1]
            out = ["symbol", Q(lib_id)]
            child_keys = {c[0] for c in s[2:] if isinstance(c, list)}
            for c in base[2:]:
                if not isinstance(c, list):
                    continue
                if c[0] == "symbol":
                    out.append(["symbol", Q(c[1].replace(base_name, name, 1))] + c[2:])
                elif c[0] == "property" or c[0] in child_keys:
                    continue
                else:
                    out.append(c)
            for c in s[2:]:
                if isinstance(c, list) and c[0] != "extends":
                    out.insert(2, c) if c[0] != "property" else out.append(c)
            # properties before unit symbols, as KiCad writes them
            props = [c for c in out[2:] if c[0] == "property"]
            units = [c for c in out[2:] if c[0] == "symbol"]
            rest = [c for c in out[2:] if c[0] not in ("property", "symbol")]
            return ["symbol", Q(lib_id)] + rest + props + units
        out = ["symbol", Q(lib_id)]
        for c in s[2:]:
            if isinstance(c, list) and c[0] == "symbol":
                c = ["symbol", Q(c[1])] + c[2:]
            out.append(c)
        return out


def pins_of(sym):
    """[(number, name, type, x, y, angle, hidden)] in symbol coordinates (y up), unit 1."""
    out = []
    for u in find(sym, "symbol"):
        parts = u[1].rsplit("_", 2)
        if parts[-2] not in ("0", "1"):
            continue
        for p in find(u, "pin"):
            at = find1(p, "at")
            hidden = "hide" in p or any(isinstance(c, list) and c[0] == "hide" and c[1] == "yes" for c in p)
            out.append((find1(p, "number")[1], find1(p, "name")[1], p[1],
                        float(at[1]), float(at[2]), int(float(at[3])) if len(at) > 3 else 0, hidden))
    return out


def rot_xy(x, y, rot):
    """Symbol coordinates (y up) rotated by rot degrees CCW."""
    for _ in range((rot // 90) % 4):
        x, y = -y, x
    return x, y


def place(px, py, rot, sx, sy, mirror=None):
    """Symbol point -> sheet. mirror "y" flips left/right after the rotation (KiCad's (mirror y))."""
    x, y = rot_xy(px, py, rot)
    if mirror == "y":
        x = -x
    return r2(sx + x), r2(sy - y)


FONT = ["effects", ["font", ["size", 1.27, 1.27]]]


def label_for(net, x, y, outward):
    """Net label at a pin end; outward is the direction away from the body (deg, sheet)."""
    angle = outward % 360
    just = {0: "left", 90: "left", 180: "right", 270: "right"}[angle]
    return ["label", Q(net), ["at", x, y, angle],
            ["effects", ["font", ["size", 1.27, 1.27]], ["justify", just, "bottom"]],
            ["uuid", uid("label", net, x, y)]]


def power_sym(libs, net, x, y, outward, n):
    lib_id = f"power:{net}"
    s = libs.flat(lib_id)
    # power symbols point up (+V) or down (GND) at rotation 0
    natural = 270 if net == "GND" else 90
    rot = (outward - natural) % 360
    ref = f"#PWR{n:03d}"
    return ["symbol", ["lib_id", Q(lib_id)], ["at", x, y, rot], ["unit", 1],
            ["exclude_from_sim", "no"], ["in_bom", "no"], ["on_board", "yes"], ["dnp", "no"],
            ["uuid", uid("pwr", net, x, y)],
            ["property", Q("Reference"), Q(ref), ["at", x, y, 0], FONT + [["hide", "yes"]]],
            ["property", Q("Value"), Q(net), ["at", x, r2(y + (3.5 if outward == 270 else -3.5)), 0], FONT],
            ["property", Q("Footprint"), Q(""), ["at", x, y, 0], FONT + [["hide", "yes"]]],
            ["property", Q("Datasheet"), Q(""), ["at", x, y, 0], FONT + [["hide", "yes"]]],
            ["pin", Q("1"), ["uuid", uid("pwrpin", net, x, y)]],
            ["instances", ["project", Q(NAME), ["path", Q("/" + ROOT), ["reference", Q(ref)], ["unit", 1]]]]]


def instance(libs, p, sym):
    x, y, rot = r2(p["x"]), r2(p["y"]), p["rot"]
    mir = p.get("mirror")
    out = ["symbol", ["lib_id", Q(p["lib_id"])], ["at", x, y, rot]] + ([["mirror", mir]] if mir else []) + [["unit", 1],
           ["exclude_from_sim", "no"], ["in_bom", "yes" if p["in_bom"] else "no"], ["on_board", "yes"],
           ["dnp", "yes" if p["dnp"] else "no"], ["uuid", uid("sym", p["ref"])]]
    values = {"Reference": p["ref"], "Value": p["value"], "Footprint": p["footprint"]}
    # Rotated two-pin parts: keep reference and value upright and off the wires,
    # above/below a horizontal part, right of a vertical one.
    text_at = {}
    pins = pins_of(sym)
    if rot and len(pins) == 2:
        (_, _, _, ax, ay, _, _), (_, _, _, bx, by, _, _) = pins
        a_, b_ = place(ax, ay, rot, x, y, mir), place(bx, by, rot, x, y, mir)
        if a_[1] == b_[1]:
            text_at = {"Reference": (x, r2(y - 2.6), "center"), "Value": (x, r2(y + 3.2), "center")}
        else:
            text_at = {"Reference": (r2(x + 2.5), r2(y - 0.6), "left"), "Value": (r2(x + 2.5), r2(y + 1.9), "left")}
    for lp in find(sym, "property"):
        name = lp[1]
        if name.startswith("ki_"):
            continue
        at = find1(lp, "at")
        lx, ly = place(float(at[1]), float(at[2]), rot, x, y, mir)
        la = (int(float(at[3])) + rot) % 180 if len(at) > 3 else 0
        eff = find1(lp, "effects") or FONT
        hidden = name not in ("Reference", "Value")
        e = [c for c in eff if not (isinstance(c, list) and c[0] == "hide")]
        if name in text_at:
            lx, ly, just = text_at[name]
            la = rot % 180          # KiCad turns field text with the symbol: undo it
            e = ["effects", ["font", ["size", 1.27, 1.27]]] + ([["justify", just]] if just != "center" else [])
        if hidden:
            e = e + [["hide", "yes"]]
        out.append(["property", Q(name), Q(values.get(name, lp[2])), ["at", lx, ly, la], e])
    for k, v in (("LCSC", p["lcsc"]), ("MPN", p["mpn"])):
        out.append(["property", Q(k), Q(v), ["at", x, y, 0], FONT + [["hide", "yes"]]])
    for num, *_ in pins_of(sym):
        out.append(["pin", Q(num), ["uuid", uid("pin", p["ref"], num)]])
    out.append(["instances", ["project", Q(NAME), ["path", Q("/" + ROOT), ["reference", Q(p["ref"])], ["unit", 1]]]])
    return out


ROOT = str(uuidlib.uuid5(NS, "root"))
G = design.G


class Wiring:
    """design.WIRES / TAGS resolved to sheet mm, with connectivity helpers."""

    def __init__(self, pin_at, problems, extra_points=()):
        self.pin_at = pin_at            # "REF.PIN" -> (x, y) mm
        self.problems = problems
        self.segs = []                  # ((x1, y1), (x2, y2), wire index)
        for i, poly in enumerate(getattr(design, "WIRES", [])):
            pts = [self.pt(p) for p in poly]
            for a, b in zip(pts, pts[1:]):
                if a == b:
                    continue
                if a[0] != b[0] and a[1] != b[1]:
                    problems.append(f"wire {poly}: segment {a} -> {b} is not horizontal or vertical")
                self.segs.append((a, b, i))
        # KiCad connects wires end to end only: split each wire wherever another wire's
        # end, a pin, a tag or a flag lands on its middle
        stops = {q for a, b, _ in self.segs for q in (a, b)} | set(extra_points)
        out = []
        for a, b, i in self.segs:
            cut = sorted((q for q in stops if q not in (a, b) and self.on_seg(q, a, b)),
                         key=lambda q: abs(q[0] - a[0]) + abs(q[1] - a[1]))
            pts = [a] + cut + [b]
            out += [(u, v, i) for u, v in zip(pts, pts[1:])]
        self.segs = out

    def pt(self, p):
        if isinstance(p, str):
            if p not in self.pin_at:
                self.problems.append(f"wire point {p}: no such pin")
                return (0.0, 0.0)
            return self.pin_at[p]
        return (r2(p[0] * G), r2(p[1] * G))

    @staticmethod
    def grid(q):
        return (r2(q[0] * G), r2(q[1] * G))

    @staticmethod
    def on_seg(q, a, b):
        """q on segment a-b (ends included)?"""
        return (min(a[0], b[0]) - 1e-6 <= q[0] <= max(a[0], b[0]) + 1e-6 and
                min(a[1], b[1]) - 1e-6 <= q[1] <= max(a[1], b[1]) + 1e-6 and
                (a[0] == b[0] == q[0] or a[1] == b[1] == q[1]))

    def on_wire(self, q):
        return any(self.on_seg(q, a, b) for a, b, _ in self.segs)

    def clusters(self):
        """Lists of segment indices that touch (end on end, or end on another segment)."""
        n = len(self.segs)
        parent = list(range(n))

        def root(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        for i, (a, b, _) in enumerate(self.segs):
            for j, (c, d, _) in enumerate(self.segs[:i]):
                if (self.on_seg(a, c, d) or self.on_seg(b, c, d) or
                        self.on_seg(c, a, b) or self.on_seg(d, a, b)):
                    parent[root(i)] = root(j)
        out = {}
        for i in range(n):
            out.setdefault(root(i), []).append(i)
        return list(out.values())

    def junctions(self, pin_points):
        """Points where three or more wire ends / wire passes / pins meet."""
        ends = {}
        for a, b, _ in self.segs:
            for q in (a, b):
                ends[q] = ends.get(q, 0) + 1
        out = []
        for q, k in ends.items():
            k += sum(2 for a, b, _ in self.segs if q not in (a, b) and self.on_seg(q, a, b))
            k += 1 if q in pin_points else 0
            if k >= 3:
                out.append(q)
        return sorted(out)


def wire_item(a, b):
    return ["wire", ["pts", ["xy", a[0], a[1]], ["xy", b[0], b[1]]],
            ["stroke", ["width", 0], ["type", "default"]], ["uuid", uid("wire", a, b)]]


def junction_item(q):
    return ["junction", ["at", q[0], q[1]], ["diameter", 0], ["color", 0, 0, 0, 0], ["uuid", uid("junction", q)]]


def group_items(title, x0, y0, x1, y1):
    x0, y0, x1, y1 = (r2(v * G) for v in (x0, y0, x1, y1))
    return [["rectangle", ["start", x0, y0], ["end", x1, y1],
             ["stroke", ["width", 0.3], ["type", "dash"], ["color", 72, 72, 160, 1]],
             ["fill", ["type", "none"]], ["uuid", uid("group", title)]],
            note_item(title, x0 / G + 0.6, y0 / G + 1.6, size=2.2, bold=True)]


def note_item(text, x, y, size=1.5, bold=False):
    font = ["font", ["size", size, size]] + ([["thickness", 0.44], ["bold", "yes"]] if bold else [])
    return ["text", Q(text), ["exclude_from_sim", "no"], ["at", r2(x * G), r2(y * G), 0],
            ["effects", font, ["justify", "left", "bottom"]], ["uuid", uid("text", text, x, y)]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kicad", default="/Applications/KiCad/KiCad.app")
    args = ap.parse_args()
    libs = Libs(args.kicad)

    lib_symbols = {}
    items = []
    npwr = 1
    problems = []
    seen_points = {}

    def attach(net, x, y, outward, who):
        nonlocal npwr
        key = (x, y)
        if key in seen_points:
            if seen_points[key] != net:
                problems.append(f"{who}: point {key} already {seen_points[key]}, wanted {net}")
            return
        seen_points[key] = net
        if net in design.POWER_NETS:
            lib_symbols.setdefault(f"power:{net}", libs.flat(f"power:{net}"))
            items.append(power_sym(libs, net, x, y, outward, npwr))
            npwr += 1
        else:
            items.append(label_for(net, x, y, outward))

    # pin ends on the sheet, for the wiring
    pin_at, pin_net = {}, {}
    for p in design.PARTS:
        for num, name, typ, px, py, ang, hidden in pins_of(libs.flat(p["lib_id"])):
            pt = place(px, py, p["rot"], p["x"], p["y"], p.get("mirror"))
            pin_at[f"{p['ref']}.{num}"] = pt
            if p["nets"].get(num):
                pin_net.setdefault(pt, set()).add(p["nets"][num])
    extra = list(pin_at.values()) + [Wiring.grid(q) for _, q, _ in getattr(design, "TAGS", [])
                                     if not isinstance(q, str)]
    extra += [(r2(x), r2(y)) for x, y in design.PWR_FLAGS.values()]
    wiring = Wiring(pin_at, problems, extra)
    for a, b, _ in wiring.segs:
        items.append(wire_item(a, b))
    for q in wiring.junctions(set(pin_at.values())):
        items.append(junction_item(q))

    # tags (labels / power symbols placed on wires), then one label per untagged cluster
    tagged = []
    for net, q, outward in getattr(design, "TAGS", []):
        q = wiring.pt(q)
        tagged.append((net, q))
        attach(net, q[0], q[1], outward, "TAG")
    for cl in wiring.clusters():
        segs = [wiring.segs[i] for i in cl]
        nets = set()
        for a, b, _ in segs:
            for q, ns in pin_net.items():
                if wiring.on_seg(q, a, b):
                    nets |= ns
        tags = {net for net, q in tagged if any(wiring.on_seg(q, a, b) for a, b, _ in segs)}
        if len(nets | tags) != 1:
            problems.append(f"wires {sorted({i for _, _, i in segs})}: nets {sorted(nets)}, tags {sorted(tags)}")
            continue
        net = next(iter(nets | tags))
        if tags:
            continue
        if net in design.POWER_NETS:
            problems.append(f"wired {net} cluster (wires {sorted({i for _, _, i in segs})}) needs a TAG")
            continue
        # label near the left / top end of the longest wire
        a, b, _ = max(segs, key=lambda s: abs(s[0][0] - s[1][0]) + abs(s[0][1] - s[1][1]))
        if a[1] == b[1]:
            x = min(a[0], b[0]) + G * 0.5
            attach(net, r2(x), a[1], 0, "auto")
        else:
            y = max(a[1], b[1]) - G * 0.5
            attach(net, a[0], r2(y), 90, "auto")

    for p in design.PARTS:
        sym = libs.flat(p["lib_id"])
        lib_symbols.setdefault(p["lib_id"], sym)
        items.append(instance(libs, p, sym))
        pins = pins_of(sym)
        by_point = {}
        for num, name, typ, px, py, ang, hidden in pins:
            pt = place(px, py, p["rot"], p["x"], p["y"], p.get("mirror"))
            by_point.setdefault(pt, []).append((num, name, typ, ang, hidden))
        known = {num for num, *_ in pins}
        for num in p["nets"]:
            if num not in known:
                problems.append(f"{p['ref']}: no pin {num}")
        for pt, group in by_point.items():
            nets = {p["nets"][n] for n, *_ in group if n in p["nets"]}
            unassigned = [n for n, _, typ, _, _ in group if n not in p["nets"] and typ != "no_connect"]
            if unassigned and not p["nc_rest"]:
                problems.append(f"{p['ref']}: pins {unassigned} have no net")
            if len(nets) > 1:
                problems.append(f"{p['ref']}: stacked pins {[g[0] for g in group]} on different nets {nets}")
                continue
            net = next(iter(nets)) if nets else None
            if all(typ == "no_connect" for _, _, typ, _, _ in group):
                continue
            if wiring.on_wire(pt):
                if net is None:
                    problems.append(f"{p['ref']}: unconnected pin at {pt} sits on a wire")
                continue
            ang = group[0][3]
            # pin angle points from the pin end into the body (symbol coords, CCW);
            # outward on the sheet is the opposite direction, after rotation
            outward = (ang + 180 + p["rot"]) % 360
            if p.get("mirror") == "y":
                outward = (180 - outward) % 360
            if net is None:
                items.append(["no_connect", ["at", pt[0], pt[1]], ["uuid", uid("nc", p["ref"], pt)]])
            else:
                attach(net, pt[0], pt[1], outward, p["ref"])

    # power flags
    lib_symbols["power:PWR_FLAG"] = libs.flat("power:PWR_FLAG")
    for i, (net, (x, y)) in enumerate(sorted(design.PWR_FLAGS.items())):
        x, y = r2(x), r2(y)
        ref = f"#FLG{i + 1:02d}"
        items.append(["symbol", ["lib_id", Q("power:PWR_FLAG")], ["at", x, y, 0], ["unit", 1],
                      ["exclude_from_sim", "no"], ["in_bom", "no"], ["on_board", "yes"], ["dnp", "no"],
                      ["uuid", uid("flag", net)],
                      ["property", Q("Reference"), Q(ref), ["at", x, r2(y - 6), 0], FONT + [["hide", "yes"]]],
                      ["property", Q("Value"), Q("PWR_FLAG"), ["at", x, r2(y - 4), 0], FONT + [["hide", "yes"]]],
                      ["property", Q("Footprint"), Q(""), ["at", x, y, 0], FONT + [["hide", "yes"]]],
                      ["property", Q("Datasheet"), Q(""), ["at", x, y, 0], FONT + [["hide", "yes"]]],
                      ["pin", Q("1"), ["uuid", uid("flagpin", net)]],
                      ["instances", ["project", Q(NAME), ["path", Q("/" + ROOT), ["reference", Q(ref)], ["unit", 1]]]]])
        if not wiring.on_wire((x, y)):
            attach(net, x, y, 270, "PWR_FLAG")

    for g in getattr(design, "GROUPS", []):
        items.extend(group_items(*g))
    for text, x, y in getattr(design, "NOTES", []):
        items.append(note_item(text, x, y))

    if problems:
        raise SystemExit("design problems:\n  " + "\n  ".join(problems))

    sch = ["kicad_sch", ["version", 20250114], ["generator", Q("eeschema")], ["generator_version", Q("9.0")],
           ["uuid", Q(ROOT)], ["paper", Q("A3")],
           ["title_block", ["title", Q(design.TITLE)],
            ["rev", Q("0.4")], ["company", Q("matter_bridge")],
            ["comment", 1, Q("Generated by tools/gen_schematic.py from tools/design.py - edit those, not this file")],
            ["comment", 2, Q(design.COMMENT)]],
           ["lib_symbols"] + list(lib_symbols.values())]
    sch += items
    sch.append(["sheet_instances", ["path", Q("/"), ["page", Q("1")]]])
    sch.append(["embedded_fonts", "no"])

    with open(os.path.join(PROJ, NAME + ".kicad_sch"), "w") as f:
        f.write(sexp.dump(sch) + "\n")

    def table(kind, ext):
        rows = "".join('\t(lib (name "%s")(type "KiCad")(uri "${KIPRJMOD}/../lib/%s%s")(options "")(descr ""))\n'
                       % (lib, lib, ext) for lib in design.LIBS)
        return "(%s_lib_table\n\t(version 7)\n%s)\n" % (kind, rows)
    with open(os.path.join(PROJ, "sym-lib-table"), "w") as f:
        f.write(table("sym", ".kicad_sym"))
    with open(os.path.join(PROJ, "fp-lib-table"), "w") as f:
        f.write(table("fp", ".pretty"))
    pro = os.path.join(PROJ, NAME + ".kicad_pro")
    if not os.path.exists(pro):
        with open(pro, "w") as f:
            f.write('{\n  "meta": {"filename": "%s.kicad_pro", "version": 3},\n  "sheets": [["%s", "Root"]]\n}\n' % (NAME, ROOT))
    print(f"{len(design.PARTS)} parts, {npwr - 1} power symbols, {len(items)} items -> {NAME}.kicad_sch")


if __name__ == "__main__":
    main()
