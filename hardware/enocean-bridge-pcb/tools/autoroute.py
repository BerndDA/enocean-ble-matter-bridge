#!/usr/bin/env python3
"""Autoroute enocean-bridge.kicad_pcb with Freerouting.

Runs under KiCad's bundled Python (needs pcbnew):

    $KPY tools/autoroute.py [--passes 100]

Exports the board as Specctra DSN, runs Freerouting headless (the jar is
downloaded once to ~/.cache/freerouting), imports the session, refills the
zones and saves. Tracks and vias that are locked (the RF paths from
gen_pcb.py) are passed as fixed wiring, so Freerouting routes around them.
The board is backed up to enocean-bridge.kicad_pcb.pre-autoroute first.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import urllib.request

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
PCB = os.path.join(PROJ, "enocean-bridge.kicad_pcb")
VERSION = "2.5.0"
JAR = os.path.expanduser(f"~/.cache/freerouting/freerouting-{VERSION}.jar")
PLANE_LAYERS = os.environ.get("PLANE_LAYERS", "In1")
URL = f"https://github.com/freerouting/freerouting/releases/download/v{VERSION}/freerouting-{VERSION}.jar"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--passes", type=int, default=100)
    ap.add_argument("--fr", default="", help="extra Freerouting options, e.g. \"-is random -us global\"")
    args = ap.parse_args()

    if not os.path.exists(JAR):
        os.makedirs(os.path.dirname(JAR), exist_ok=True)
        print("downloading", URL)
        urllib.request.urlretrieve(URL, JAR)

    work = os.path.join(PROJ, "autoroute")
    os.makedirs(work, exist_ok=True)
    dsn = os.path.join(work, "board.dsn")
    ses = os.path.join(work, "board.ses")
    if os.path.exists(ses):
        os.remove(ses)

    shutil.copy(PCB, PCB + ".pre-autoroute")
    board = pcbnew.LoadBoard(PCB)
    before = len(board.GetTracks())
    if not pcbnew.ExportSpecctraDSN(board, dsn):
        sys.exit("DSN export failed")

    # Offer the router only the normal via. KiCad lists every via size on the board,
    # including the 0.25/0.15 mm via-in-pad at the nRF52840, which must stay there.
    text = open(dsn).read()
    def keep_normal(m):
        names = re.findall(r'"[^"]*"|\S+', m.group(1))
        normal = [n for n in names if "250:150" not in n]
        return "(via " + " ".join(normal) + ")"
    text = re.sub(r"\(via ((?:\s*\"?Via[^()]*?)+)\)", keep_normal, text, count=1)
    # In1 (GND) is a pure plane; In2 (+3V3 pour) may take signals.
    text = re.sub(r"(\(layer (?:%s)\.Cu\s*\(type )signal\)" % PLANE_LAYERS, r"\1power)", text)
    open(dsn, "w").write(text)

    cmd = ["java", "-jar", JAR, "-de", dsn, "-do", ses, "-mp", str(args.passes),
           "--gui.enabled=false"] + args.fr.split()
    print(" ".join(cmd))
    r = subprocess.run(cmd, cwd=work, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    with open(os.path.join(work, "freerouting.log"), "w") as f:
        f.write(r.stdout)
    tail = [l for l in r.stdout.splitlines() if "INFO" in l or "WARN" in l or "ERROR" in l][-12:]
    print("\n".join(tail))
    if not os.path.exists(ses):
        sys.exit(f"Freerouting wrote no session (exit {r.returncode}); see autoroute/freerouting.log")

    if not pcbnew.ImportSpecctraSES(board, ses):
        sys.exit("SES import failed")
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(PCB, board)
    print(f"tracks/vias: {before} -> {len(board.GetTracks())}; saved {os.path.basename(PCB)}")


if __name__ == "__main__":
    main()
