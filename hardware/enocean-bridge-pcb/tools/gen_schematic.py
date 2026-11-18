#!/usr/bin/env python3
"""Generate enocean-bridge.kicad_sch (and the project's library tables) from design.py.

Every symbol comes from KiCad's own libraries (or ../lib for the TCM 515) and is
embedded in the schematic. Pins connect through net labels or power symbols
placed on the pin ends, unused pins get a no-connect flag. Regenerating
overwrites the schematic: edit design.py, not the .kicad_sch.

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
NAME = "enocean-bridge"
NS = uuidlib.UUID("5a1d3c2e-0e0c-4e5a-9d1b-6e0c3a7b9f10")


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


def place(px, py, rot, sx, sy):
    x, y = rot_xy(px, py, rot)
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
    out = ["symbol", ["lib_id", Q(p["lib_id"])], ["at", x, y, rot], ["unit", 1],
           ["exclude_from_sim", "no"], ["in_bom", "yes" if p["in_bom"] else "no"], ["on_board", "yes"],
           ["dnp", "yes" if p["dnp"] else "no"], ["uuid", uid("sym", p["ref"])]]
    values = {"Reference": p["ref"], "Value": p["value"], "Footprint": p["footprint"]}
    for lp in find(sym, "property"):
        name = lp[1]
        if name.startswith("ki_"):
            continue
        at = find1(lp, "at")
        lx, ly = place(float(at[1]), float(at[2]), rot, x, y)
        la = (int(float(at[3])) + rot) % 180 if len(at) > 3 else 0
        eff = find1(lp, "effects") or FONT
        hidden = name not in ("Reference", "Value")
        e = [c for c in eff if not (isinstance(c, list) and c[0] == "hide")]
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

    for p in design.PARTS:
        sym = libs.flat(p["lib_id"])
        lib_symbols.setdefault(p["lib_id"], sym)
        items.append(instance(libs, p, sym))
        pins = pins_of(sym)
        by_point = {}
        for num, name, typ, px, py, ang, hidden in pins:
            pt = place(px, py, p["rot"], p["x"], p["y"])
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
            ang = group[0][3]
            # pin angle points from the pin end into the body (symbol coords, CCW);
            # outward on the sheet is the opposite direction, after rotation
            outward = (ang + 180 + p["rot"]) % 360
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
        attach(net, x, y, 270, "PWR_FLAG")

    if problems:
        raise SystemExit("design problems:\n  " + "\n  ".join(problems))

    sch = ["kicad_sch", ["version", 20250114], ["generator", Q("eeschema")], ["generator_version", Q("9.0")],
           ["uuid", Q(ROOT)], ["paper", Q("A3")],
           ["title_block", ["title", Q("EnOcean-Matter bridge: nRF52840 + TCM 515 + USB-C")],
            ["rev", Q("0.1")], ["company", Q("matter_bridge")],
            ["comment", 1, Q("Generated by tools/gen_schematic.py from tools/design.py - edit those, not this file")],
            ["comment", 2, Q("Pin-compatible with the Pro Micro build (BOARD=promicro-uf2)")]],
           ["lib_symbols"] + list(lib_symbols.values())]
    sch += items
    sch.append(["sheet_instances", ["path", Q("/"), ["page", Q("1")]]])
    sch.append(["embedded_fonts", "no"])

    with open(os.path.join(PROJ, NAME + ".kicad_sch"), "w") as f:
        f.write(sexp.dump(sch) + "\n")

    with open(os.path.join(PROJ, "sym-lib-table"), "w") as f:
        f.write('(sym_lib_table\n\t(version 7)\n\t(lib (name "EnOcean")(type "KiCad")(uri "${KIPRJMOD}/../lib/EnOcean.kicad_sym")(options "")(descr "TCM 515"))\n)\n')
    with open(os.path.join(PROJ, "fp-lib-table"), "w") as f:
        f.write('(fp_lib_table\n\t(version 7)\n\t(lib (name "EnOcean")(type "KiCad")(uri "${KIPRJMOD}/../lib/EnOcean.pretty")(options "")(descr "TCM 515"))\n)\n')
    pro = os.path.join(PROJ, NAME + ".kicad_pro")
    if not os.path.exists(pro):
        with open(pro, "w") as f:
            f.write('{\n  "meta": {"filename": "%s.kicad_pro", "version": 3},\n  "sheets": [["%s", "Root"]]\n}\n' % (NAME, ROOT))
    print(f"{len(design.PARTS)} parts, {npwr - 1} power symbols, {len(items)} items -> {NAME}.kicad_sch")


if __name__ == "__main__":
    main()
