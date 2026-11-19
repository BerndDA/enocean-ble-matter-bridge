#!/usr/bin/env python3
"""Fabrication outputs for JLCPCB in fab/: Gerbers + drill (zipped), BOM and CPL for assembly.

    python3 tools/export_fab.py

Gerbers follow JLC's KiCad recommendations (no X2, Protel extensions, solder mask
subtracted from silkscreen); drill is one Excellon file in mm. The BOM and CPL list
only the parts JLC assembles: everything with an LCSC number that isn't DNP.
The Pro Micro (U1, on headers) and the TCM 515 (U2) are soldered by hand.
"""
import collections
import csv
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import design  # noqa: E402

NAME = "enocean-carrier"
PCB = os.path.join(PROJ, NAME + ".kicad_pcb")
CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
FAB = os.path.join(PROJ, "fab")
LAYERS = "F.Cu,B.Cu,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts"


def cli(*args):
    r = subprocess.run([CLI, *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if r.returncode != 0:
        sys.exit(f"kicad-cli {' '.join(args[:3])} failed:\n{r.stdout}")


def main():
    shutil.rmtree(FAB, ignore_errors=True)
    gdir = os.path.join(FAB, "gerbers")
    os.makedirs(gdir)

    cli("pcb", "export", "gerbers", "-o", gdir + "/", "-l", LAYERS, "--no-x2", "--no-netlist",
        "--subtract-soldermask", "--check-zones", "--precision", "6", PCB)
    cli("pcb", "export", "drill", "-o", gdir + "/", "--format", "excellon", "--excellon-units", "mm",
        "--excellon-zeros-format", "decimal", "--drill-origin", "absolute", PCB)
    zpath = os.path.join(FAB, f"{NAME}-gerbers.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(gdir)):
            z.write(os.path.join(gdir, f), f)

    # parts JLC places: an LCSC number and not DNP
    placed = {p["ref"]: p for p in design.PARTS if p["lcsc"] and not p["dnp"]}

    # one line per LCSC part (e.g. both buttons), values joined
    groups = collections.OrderedDict()
    for p in sorted(placed.values(), key=lambda p: (p["lcsc"], p["ref"])):
        g = groups.setdefault((p["footprint"].split(":")[1], p["lcsc"]), {"values": [], "refs": []})
        if p["value"] not in g["values"]:
            g["values"].append(p["value"])
        g["refs"].append(p["ref"])
    with open(os.path.join(FAB, f"{NAME}-bom.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
        for (fp, lcsc), g in groups.items():
            w.writerow(["/".join(g["values"]), ",".join(g["refs"]), fp, lcsc])

    with tempfile.TemporaryDirectory() as d:
        pos = os.path.join(d, "pos.csv")
        cli("pcb", "export", "pos", "-o", pos, "--format", "csv", "--units", "mm", "--side", "both",
            "--exclude-dnp", PCB)
        rows = list(csv.DictReader(open(pos)))
    with open(os.path.join(FAB, f"{NAME}-cpl.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        found = set()
        for r in rows:
            if r["Ref"] in placed:
                found.add(r["Ref"])
                layer = "Top" if r["Side"].lower().startswith("top") else "Bottom"
                w.writerow([r["Ref"], f'{float(r["PosX"]):.4f}mm', f'{float(r["PosY"]):.4f}mm',
                            layer, f'{float(r["Rot"]) % 360:.1f}'])
    missing = set(placed) - found
    if missing:
        sys.exit(f"not in the position file: {sorted(missing)}")

    print(f"fab/{NAME}-gerbers.zip ({len(os.listdir(gdir))} files)")
    print(f"fab/{NAME}-bom.csv ({len(groups)} lines, {len(placed)} parts)")
    print(f"fab/{NAME}-cpl.csv ({len(found)} parts)")
    print("hand-soldered:", ", ".join(p["ref"] for p in design.PARTS
                                      if p["ref"] not in placed and p["in_bom"] and not p["dnp"]))


if __name__ == "__main__":
    main()
