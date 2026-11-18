#!/usr/bin/env python3
"""Compare KiCad's netlist of enocean-carrier.kicad_sch with design.py.

Exports the netlist with kicad-cli, then checks that every pin sits on the net
design.py gives it, that pins without a net are unconnected, and that no
signal net has only one pin (a typo in a net name shows up that way).
"""
import os
import subprocess
import sys
import tempfile

import sexp
from sexp import find, find1
import design

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"


def main():
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "net.net")
        subprocess.run([CLI, "sch", "export", "netlist", "--format", "kicadsexpr", "-o", out,
                        os.path.join(PROJ, "enocean-carrier.kicad_sch")],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        net = sexp.parse(open(out).read())

    actual = {}      # (ref, pin) -> net name
    members = {}
    for n in find(find1(net, "nets"), "net"):
        name = find1(n, "name")[1].lstrip("/")
        for node in find(n, "node"):
            ref, pin = find1(node, "ref")[1], find1(node, "pin")[1]
            if ref.startswith("#"):
                continue
            actual[(ref, pin)] = name
            members.setdefault(name, []).append(f"{ref}.{pin}")

    errors = []
    checked = 0
    for p in design.PARTS:
        for pin, want in p["nets"].items():
            got = actual.get((p["ref"], pin))
            checked += 1
            if want is None:
                if got is not None and not got.startswith("unconnected-"):
                    errors.append(f"{p['ref']}.{pin}: expected unconnected, got {got}")
            elif got != want:
                errors.append(f"{p['ref']}.{pin}: expected {want}, got {got}")
    for name, m in sorted(members.items()):
        if len(m) < 2 and not name.startswith("unconnected-"):
            errors.append(f"net {name} has only {m}")

    nets = [n for n in members if not n.startswith("unconnected-")]
    print(f"{checked} pins checked, {len(nets)} nets")
    for n in sorted(nets):
        print(f"  {n:12s} {' '.join(sorted(members[n]))}")
    if errors:
        print("\nERRORS:\n  " + "\n  ".join(errors))
        sys.exit(1)
    print("netlist matches design.py")


if __name__ == "__main__":
    main()
