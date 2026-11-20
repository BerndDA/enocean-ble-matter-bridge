#!/usr/bin/env python3
"""Draw the placement of enocean-bridge.kicad_pcb as a picture, before routing.

Shows what KiCad's plots don't put together: the board areas of the schematic
blocks (placement.BLOCKS), the 2.4 GHz antenna keepout, every part's courtyard,
pads and reference, the tracks gen_pcb.py drew, and the ratsnest of each signal
net still to route (minimum spanning tree of its pads; GND and +3V3 are planes,
the RF nets are already drawn by gen_pcb.py).
Also prints the total ratsnest length, a rough measure of how much there is to
route.

    KPY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
    $KPY tools/render_placement.py [board.kicad_pcb]   # writes enocean-bridge-placement.png

Default board: enocean-bridge.kicad_pcb. After routing, pass autoroute/unrouted.kicad_pcb
(route.py's copy of the board before routing). Needs rsvg-convert.
"""
import math
import os
import subprocess
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import placement   # noqa: E402

NAME = "enocean-bridge"
ORIGIN = (100.0, 100.0)     # board corner on the KiCad canvas, as in gen_pcb.py
S = 24.0                    # px per mm
M = 40.0                    # margin, px
BLOCK_COLORS = ["#f2b134", "#4c9be8", "#e8604c", "#5cb85c"]


def xy(v):
    return (pcbnew.ToMM(v.x) - ORIGIN[0]) * S + M, (pcbnew.ToMM(v.y) - ORIGIN[1]) * S + M


def net_color(n):
    if n.startswith("/RF") or n == "/ANT_868":
        return "#9b30d9"
    if n.startswith("/USB") or n.startswith("/CC"):
        return "#1a9850"
    if "VBUS" in n or n == "/VDD_TCM":
        return "#e66101"
    return "#2166ac"


def mst(pts):
    edges, inside = [], {0}
    while len(inside) < len(pts):
        d, i, j = min((math.dist(pts[i], pts[j]), i, j)
                      for i in inside for j in range(len(pts)) if j not in inside)
        edges.append((pts[i], pts[j], d))
        inside.add(j)
    return edges


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(PROJ, NAME + ".kicad_pcb")
    board = pcbnew.LoadBoard(path)
    W, H = placement.BOARD_W * S + 2 * M, placement.BOARD_H * S + 2 * M + 70
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" '
           f'font-family="Helvetica, Arial, sans-serif">',
           f'<rect width="100%" height="100%" fill="white"/>',
           f'<rect x="{M}" y="{M}" width="{placement.BOARD_W * S}" height="{placement.BOARD_H * S}" '
           f'fill="#eef3ea" stroke="black" stroke-width="2"/>']

    # block areas
    for k, (title, areas) in enumerate(placement.BLOCKS.items()):
        c = BLOCK_COLORS[k % len(BLOCK_COLORS)]
        for x0, y0, x1, y1 in ([areas] if isinstance(areas, tuple) else areas):
            out.append(f'<rect x="{x0 * S + M}" y="{y0 * S + M}" width="{(x1 - x0) * S}" height="{(y1 - y0) * S}" '
                       f'fill="{c}" fill-opacity="0.10" stroke="{c}" stroke-width="2" stroke-dasharray="8 5"/>')
            out.append(f'<text x="{x0 * S + M + 6}" y="{y0 * S + M + 16}" font-size="13" fill="{c}" '
                       f'font-weight="bold">{title.split(" (")[0].split(",")[0]}</text>')

    # antenna keepout
    kx0, ky0, kx1, ky1 = placement.ANT_KEEPOUT
    out.append(f'<pattern id="h" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
               f'<line x1="0" y1="0" x2="0" y2="8" stroke="#c00" stroke-width="1.5"/></pattern>')
    out.append(f'<rect x="{kx0 * S + M}" y="{ky0 * S + M}" width="{(kx1 - kx0) * S}" height="{(ky1 - ky0) * S}" '
               f'fill="url(#h)" fill-opacity="0.35" stroke="#c00"/>')

    # footprints: courtyard, pads, reference
    nets = {}
    for fp in board.GetFootprints():
        side = pcbnew.B_Cu if fp.GetSide() else pcbnew.F_Cu
        cy = fp.GetCourtyard(side)
        bb = cy.BBox() if cy.OutlineCount() else fp.GetBoundingBox(False)
        (x0, y0), (x1, y1) = xy(bb.GetOrigin()), xy(bb.GetEnd())
        dashed = ' stroke-dasharray="4 3"' if fp.GetSide() else ""
        out.append(f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{x1 - x0:.1f}" height="{y1 - y0:.1f}" '
                   f'fill="white" fill-opacity="0.55" stroke="#555" stroke-width="1"{dashed}/>')
        for p in fp.Pads():
            pb = p.GetBoundingBox()
            (a0, b0), (a1, b1) = xy(pb.GetOrigin()), xy(pb.GetEnd())
            n = p.GetNetname()
            fill = "#9a9a9a" if n == "GND" else "#d6604d" if n == "+3V3" else "#c8a000"
            out.append(f'<rect x="{a0:.1f}" y="{b0:.1f}" width="{a1 - a0:.1f}" height="{b1 - b0:.1f}" fill="{fill}"/>')
            if n and n not in ("GND", "+3V3") and not n.startswith("unconnected"):
                nets.setdefault(n, []).append(xy(p.GetPosition()))
        cx, cyy = xy(fp.GetPosition())
        fs = 15 if len(list(fp.Pads())) > 8 else 11
        out.append(f'<text x="{cx:.1f}" y="{cyy + 4:.1f}" font-size="{fs}" text-anchor="middle" '
                   f'font-weight="bold" fill="#222">{fp.GetReference()}</text>')

    # tracks and vias gen_pcb.py placed (RF paths, fanout)
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA":
            x, y = xy(t.GetPosition())
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{max(2.0, pcbnew.ToMM(t.GetWidth(pcbnew.F_Cu)) * S / 2):.1f}" '
                       f'fill="none" stroke="#444" stroke-width="1"/>')
        else:
            (x0, y0), (x1, y1) = xy(t.GetStart()), xy(t.GetEnd())
            out.append(f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y1:.1f}" stroke="#b2182b" '
                       f'stroke-width="{max(1.5, pcbnew.ToMM(t.GetWidth()) * S):.1f}" stroke-linecap="round" opacity="0.8"/>')

    # ratsnest of the nets still to route (the RF paths are drawn by gen_pcb.py)
    routed = {t.GetNetname() for t in board.GetTracks() if t.GetClass() == "PCB_TRACK"}
    total = 0.0
    for n, pts in nets.items():
        if n in routed:
            continue
        for a, b, d in mst(pts):
            total += d / S
            out.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" '
                       f'stroke="{net_color(n)}" stroke-width="1.6" opacity="0.85"/>')

    ly = placement.BOARD_H * S + M + 30
    legend = [("#9b30d9", "RF"), ("#1a9850", "USB"), ("#e66101", "VBUS / VDD_TCM"), ("#2166ac", "other signals")]
    x = M
    for c, t in legend:
        out.append(f'<line x1="{x}" y1="{ly}" x2="{x + 26}" y2="{ly}" stroke="{c}" stroke-width="3"/>'
                   f'<text x="{x + 32}" y="{ly + 5}" font-size="14">{t}</text>')
        x += 50 + 8 * len(t)
    out.append(f'<text x="{x + 10}" y="{ly + 5}" font-size="14">still to route (GND, +3V3 are planes): '
               f'{total:.0f} mm  ·  board {placement.BOARD_W} × {placement.BOARD_H} mm  ·  '
               f'hatched: no copper (2.4 GHz antenna)</text>')
    out.append("</svg>")

    svg = os.path.join(PROJ, NAME + "-placement.svg")
    png = os.path.join(PROJ, NAME + "-placement.png")
    with open(svg, "w") as f:
        f.write("\n".join(out))
    subprocess.run(["rsvg-convert", "-o", png, svg], check=True)
    os.remove(svg)
    print(f"{os.path.basename(png)}: ratsnest {total:.1f} mm")


if __name__ == "__main__":
    main()
