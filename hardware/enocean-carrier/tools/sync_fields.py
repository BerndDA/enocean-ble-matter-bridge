#!/usr/bin/env python3
"""Copy symbol fields (LCSC, MPN, Description, ...) from the schematic onto the board's
footprints, like "Update PCB from Schematic" does for fields. Tracks are not touched.

    $KPY tools/sync_fields.py
"""
import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gen_pcb  # noqa: E402  (for load_netlist and the board path)


def main():
    sch = gen_pcb.load_netlist()
    board = pcbnew.LoadBoard(gen_pcb.PCB)
    changed = 0
    for fp in board.GetFootprints():
        for name, val in sch["fields"].get(fp.GetReference(), {}).items():
            if not fp.HasField(name) or fp.GetFieldText(name) != val:
                fp.SetField(name, val)
                fp.GetField(name).SetVisible(False)
                changed += 1
    pcbnew.SaveBoard(gen_pcb.PCB, board)
    print(f"{changed} fields updated on {os.path.basename(gen_pcb.PCB)}")


if __name__ == "__main__":
    main()
