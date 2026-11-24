#!/usr/bin/env python3
"""Top render with the TCM 515 pads marked: which ones carry a net and must be
soldered, which ones are NC / test points and can stay dry.

    tools/render_tcm_solder.py            -> enocean-carrier-tcm-solder.png

Needs kicad-cli and Pillow. The pad list comes from the .kicad_pcb, so the
picture follows the board.
"""
import math
import os
import re
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
BOARD_DIR = os.path.dirname(HERE)
PCB = os.path.join(BOARD_DIR, "enocean-carrier.kicad_pcb")
OUT = os.path.join(BOARD_DIR, "enocean-carrier-tcm-solder.png")
CLI = os.environ.get("KICAD_CLI", "kicad-cli")
W, H, ZOOM = 2400, 1000, 1.15

SOLDER = (40, 220, 90)
SKIP = (230, 60, 60)


def font(size):
    for f in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf",
              "/System/Library/Fonts/Helvetica.ttc",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        if os.path.exists(f):
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def board_parts(s):
    a = s.index('(footprint "EnOcean:TCM515"')
    b = s.find("\n\t(footprint ", a + 1)
    fp = s[a:b if b > 0 else len(s)]
    at = re.search(r"\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", fp)
    fx, fy, fr = float(at[1]), float(at[2]), float(at[3] or 0)
    pads = []
    for m in re.finditer(r'\(pad "(\d+)" \w+ \w+\s*\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)'
                         r'\s*\(size ([\d.]+) ([\d.]+)\)(.*?)\n\t\t\)', fp, re.S):
        net = re.search(r'\(net (?:\d+ )?"([^"]*)"\)', m[7])
        net = net[1] if net else ""
        lx, ly = float(m[2]), float(m[3])
        t = math.radians(fr)
        # KiCad: y down, positive angle counter-clockwise on screen
        gx = fx + lx * math.cos(t) + ly * math.sin(t)
        gy = fy - lx * math.sin(t) + ly * math.cos(t)
        w, h = float(m[5]), float(m[6])
        if round(float(m[4] or 0)) % 180 == 90:
            w, h = h, w
        pads.append(dict(num=int(m[1]), x=gx, y=gy, w=w, h=h,
                         net=net, used=bool(net) and not net.startswith("unconnected")))
    edge = re.search(r'\(gr_rect\s*\(start ([-\d.]+) ([-\d.]+)\)\s*\(end ([-\d.]+) ([-\d.]+)\)'
                     r'(?:(?!\(gr_).)*?"Edge.Cuts"', s, re.S)
    return (fx, fy), pads, tuple(float(edge[i]) for i in range(1, 5))


def main():
    s = open(PCB).read()
    centre, pads, (ex0, ey0, ex1, ey1) = board_parts(s)

    with tempfile.TemporaryDirectory() as tmp:
        png = os.path.join(tmp, "top.png")
        subprocess.run([CLI, "pcb", "render", "--side", "top", "--width", str(W),
                        "--height", str(H), "--zoom", str(ZOOM), "--quality", "high",
                        "-o", png, PCB], check=True, capture_output=True)
        base = Image.open(png).convert("RGBA")

    # Map board mm to pixels from the board outline (orthographic render).
    bx0, by0, bx1, by1 = base.getchannel("A").point(lambda a: 255 if a > 200 else 0).getbbox()
    sx, sy = (bx1 - bx0) / (ex1 - ex0), (by1 - by0) / (ey1 - ey0)
    px = lambda x, y: (bx0 + (x - ex0) * sx, by0 + (y - ey0) * sy)

    img = Image.new("RGBA", base.size, (255, 255, 255, 255))
    img.alpha_composite(base)
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    f_lab = font(17)
    cx, cy = centre

    for p in pads:
        x, y = px(p["x"], p["y"])
        hw, hh = p["w"] * sx / 2 + 3, p["h"] * sy / 2 + 3
        box = (x - hw, y - hh, x + hw, y + hh)
        if p["used"]:
            d.rounded_rectangle(box, 4, fill=SOLDER + (150,), outline=SOLDER + (255,), width=3)
        else:
            d.rounded_rectangle(box, 4, fill=(20, 20, 20, 170), outline=SKIP + (255,), width=2)
            d.line((box[0] + 3, box[1] + 3, box[2] - 3, box[3] - 3), fill=SKIP + (255,), width=2)
            d.line((box[0] + 3, box[3] - 3, box[2] - 3, box[1] + 3), fill=SKIP + (255,), width=2)

    # Pin number next to every pad, just inside the module outline.
    f_num = font(15)
    for p in pads:
        x, y = px(p["x"], p["y"])
        t = str(p["num"])
        tw, th = d.textbbox((0, 0), t, font=f_num, anchor="mm")[2:]
        if p["w"] > p["h"]:      # side column: number beside the pad, inward
            x += (1 if cx > p["x"] else -1) * (p["w"] * sx / 2 + 16)
        else:                    # top/bottom row: number above/below, inward
            y += (1 if cy > p["y"] else -1) * (p["h"] * sy / 2 + 13)
        if p["used"]:
            d.rounded_rectangle((x - 13, y - 10, x + 13, y + 10), 4, fill=(255, 255, 255, 235))
            d.text((x, y), t, font=f_num, anchor="mm", fill=(10, 110, 40, 255))
        else:
            d.text((x, y), t, font=f_num, anchor="mm", fill=(255, 140, 140, 220))

    img.alpha_composite(over)

    # Legend in the free space left of the board.
    d = ImageDraw.Draw(img)
    used = [p for p in sorted(pads, key=lambda p: p["num"]) if p["used"]]
    x0, y0 = 40, 150
    d.text((x0, y0), "TCM 515 (U2) pads", font=font(34), fill=(30, 30, 30))
    y0 += 60
    d.rounded_rectangle((x0, y0, x0 + 34, y0 + 26), 4, fill=SOLDER, outline=(20, 120, 50), width=2)
    d.text((x0 + 48, y0 - 2), f"solder ({len(used)} pads)", font=font(26), fill=(30, 30, 30))
    y0 += 44
    d.rounded_rectangle((x0, y0, x0 + 34, y0 + 26), 4, fill=(40, 40, 40), outline=SKIP, width=2)
    d.line((x0 + 4, y0 + 4, x0 + 30, y0 + 22), fill=SKIP, width=2)
    d.line((x0 + 4, y0 + 22, x0 + 30, y0 + 4), fill=SKIP, width=2)
    d.text((x0 + 48, y0 - 2), f"NC / test point, leave dry ({len(pads) - len(used)})",
           font=font(26), fill=(30, 30, 30))
    y0 += 64
    f_tab = font(24)
    for p in used:
        d.text((x0 + 34, y0), str(p["num"]), font=f_tab, anchor="ra", fill=(10, 110, 40))
        d.text((x0 + 52, y0), p["net"].lstrip("/"), font=f_tab, fill=(40, 40, 40))
        y0 += 34

    img.convert("RGB").save(OUT)
    print(os.path.relpath(OUT, os.getcwd()))
    for p in sorted(pads, key=lambda p: p["num"]):
        print(f'  {p["num"]:2d} {"SOLDER" if p["used"] else "  -   "} {p["net"]}')


if __name__ == "__main__":
    sys.exit(main())
