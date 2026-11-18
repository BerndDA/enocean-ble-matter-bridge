#!/usr/bin/env python3
"""Route the board: several Freerouting strategies, keep the best.

    python3 tools/route.py        (plain python3 is fine; it calls KiCad's Python itself)

Starts from the board gen_pcb.py made (placement, RF paths, power fanout), and for
each strategy runs autoroute.py, then stitch.py, then KiCad's DRC. Scores are
(unconnected items, DRC errors, warnings); the best result becomes
enocean-bridge.kicad_pcb. Each attempt is kept in autoroute/try-<n>.kicad_pcb.
"""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
PCB = os.path.join(PROJ, "enocean-bridge.kicad_pcb")
KPY = "/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3"
CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
STRATEGIES = [
    "",
    "-is sequential",
    "-is random",
    "-us global",
    "-us hybrid -hr 1:1",
    "-is random -us global",
]


def run(args):
    return subprocess.run(args, cwd=PROJ, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def score(path):
    out = os.path.join(PROJ, "autoroute", "drc.json")
    run([CLI, "pcb", "drc", "--schematic-parity", "--severity-all", "--format", "json", "-o", out, path])
    rep = json.load(open(out))
    errors = sum(1 for v in rep["violations"] if v["severity"] == "error")
    warnings = sum(1 for v in rep["violations"] if v["severity"] == "warning")
    return (len(rep.get("unconnected_items", [])), errors, warnings)


def main():
    work = os.path.join(PROJ, "autoroute")
    os.makedirs(work, exist_ok=True)
    clean = os.path.join(work, "unrouted.kicad_pcb")
    shutil.copy(PCB, clean)
    results = []
    for i, strat in enumerate(STRATEGIES):
        shutil.copy(clean, PCB)
        r = run([KPY, os.path.join(HERE, "autoroute.py"), "--passes", "100", "--fr", strat])
        if r.returncode != 0:
            print(f"try {i} [{strat or 'default'}]: autoroute failed")
            continue
        run([KPY, os.path.join(HERE, "stitch.py")])
        sc = score(PCB)          # in the project folder, so the project's rules apply
        dst = os.path.join(work, f"try-{i}.kicad_pcb")
        shutil.copy(PCB, dst)
        results.append((sc, i, strat))
        print(f"try {i} [{strat or 'default'}]: unconnected {sc[0]}, errors {sc[1]}, warnings {sc[2]}", flush=True)
        if sc[:2] == (0, 0):
            break
    if not results:
        shutil.copy(clean, PCB)
        sys.exit("no routing attempt succeeded")
    best = min(results)
    shutil.copy(os.path.join(work, f"try-{best[1]}.kicad_pcb"), PCB)
    print(f"best: try {best[1]} [{best[2] or 'default'}] -> {os.path.basename(PCB)}")


if __name__ == "__main__":
    main()
