"""Photo-style renders of the carrier in its case (Blender, Cycles).

    tools/render_case.sh            (exports the inputs, then runs this in Blender)

Inputs in the work folder given after `--`: base.stl, lid_asm.stl, pin_asm.stl (OpenSCAD,
mounted orientation) and board.glb (KiCad 3D export, origin at the board's lower-left
corner). Parts without a KiCad 3D model (Pro Micro on its headers, TCM 515, buttons,
whip) are modelled here as simple shapes. Dimensions follow carrier_case.scad's
defaults (pm_mount = "direct"); keep them in step when those change.

Output: render-closed.png, render-exploded.png, render-open.png in the output folder.
Mode "glb" (tools/render_case.sh glb): instead writes the scene as a glTF model to the file
given as output (enocean-carrier.glb), for hardware/pcb-viewer.html.
Mode "blend" (tools/render_case.sh blend): the scene of the USB clip (anim-usb), animated,
saved as a .blend file to the file given as output instead of rendered.
"""
import math
import os
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # for anim_case.py
args = sys.argv[sys.argv.index("--") + 1:]
WORK, OUT = args[0], args[1]
SAMPLES = int(args[2]) if len(args) > 2 else 192
MODE = args[3] if len(args) > 3 else "stills"        # "stills", "anim" (front view), "anim-usb" (USB side), "glb" or "blend"
SAVE = None
if MODE == "blend":                                  # the anim-usb scene, saved instead of rendered
    MODE, SAVE = "anim-usb", OUT
FRAMES = args[4] if len(args) > 4 else ""            # anim: comma list of frames to render (test), default all

# ---------------------------------------------------------------- dimensions (carrier_case.scad)
WALL, GAP, FLOOR, UNDER, BOARD_T = 2.0, 0.4, 3.0, 0.0, 1.6
BOARD_W, BOARD_H = 46.5, 33.4
SOCKET = False                        # carrier_case.scad pm_mount: "direct" (False) or "socket"
PM_GAP = 11.0 if SOCKET else 2.5
PM_PCB, PM_PARTS = 1.2, 3.5
USB_HEAD = 1.5                       # carrier_case.scad usb_head: wall above the USB opening
INNER_H = PM_GAP + PM_PCB + PM_PARTS + 0.8 + USB_HEAD
BOARD_Z = FLOOR + UNDER
TOP_Z = BOARD_Z + BOARD_T
BASE_H = TOP_Z + INNER_H
OUT_W, OUT_D = BOARD_W + 2 * GAP + 2 * WALL, BOARD_H + 2 * GAP + 2 * WALL
OFF = WALL + GAP
SW_H = 1.5
LID_T, LED_H = 2.0, 0.8                # LED_H: 0805 LEDs
ROD_D = 3.0                           # acrylic rods in the light pipes (carrier_case.scad rod_d)
PIPE_LEN = INNER_H - LED_H - 0.5      # light pipe below the lid
LEDS = [(43.2, 16.4), (43.2, 20.4), (43.2, 24.4)]   # D1 red, D2 green, D3 yellow, KiCad board coordinates
LED = LEDS[1]                         # the one that blinks in the USB clip (green)
PIEZO_AT, PIEZO_D, PIEZO_CH = (28.0, 18.5), 15.0, 1.2   # carrier_case.scad piezo_at / piezo_d / piezo_ch
J3_PADS = [(21.0, 26.4), (23.54, 26.4)]  # piezo wire pads, KiCad board coordinates


def C(x, y):
    """KiCad board coordinates (y down from the USB edge) -> case coordinates."""
    return (x + OFF, BOARD_H - y + OFF)


BUTTONS = [C(29.0, 30.75), C(41.6, 30.75)]
WHIP = C(44.4, 2.6)
PM_X0, PM_X1 = 1.02 + OFF, 19.02 + OFF
PM_Y0, PM_Y1 = BOARD_H - 33.02 + OFF, BOARD_H + OFF       # nice!nano v2, USB end flush with the board edge
PIN_ROWS_X = [2.4 + OFF, 17.64 + OFF]
PIN_YS = [BOARD_H - (3.81 + 2.54 * i) + OFF for i in range(12)]

# ---------------------------------------------------------------- helpers
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene


def mat(name, color, rough=0.5, metal=0.0, emit=None):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    p = m.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (*color, 1.0)
    p.inputs["Roughness"].default_value = rough
    p.inputs["Metallic"].default_value = metal
    if emit:
        p.inputs["Emission Color"].default_value = (*emit[0], 1.0)
        p.inputs["Emission Strength"].default_value = emit[1]
    return m


M = {
    "cable": mat("cable", (0.72, 0.73, 0.74), 0.45),       # light grey USB cable and plug
    "case": mat("case", (0.045, 0.047, 0.052), 0.55),
    "lid": mat("lid", (0.05, 0.052, 0.058), 0.5),
    "pin": mat("pin", (0.95, 0.42, 0.08), 0.45),
    "pm_pcb": mat("pm_pcb", (0.015, 0.02, 0.06), 0.35),
    "chip": mat("chip", (0.02, 0.02, 0.02), 0.4),
    "metal": mat("metal", (0.8, 0.8, 0.82), 0.25, 1.0),
    "gold": mat("gold", (0.95, 0.75, 0.35), 0.25, 1.0),
    "header": mat("header", (0.02, 0.02, 0.02), 0.55),
    "tcm": mat("tcm", (0.03, 0.22, 0.1), 0.4),
    "label": mat("label", (0.95, 0.95, 0.93), 0.6),
    "copper": mat("copper", (0.95, 0.6, 0.45), 0.3, 1.0),
    "floor": mat("floor", (0.55, 0.56, 0.58), 0.85),
    "led": mat("led", (1.0, 0.75, 0.2), 0.3, 0.0, ((1.0, 0.7, 0.15), 12.0)),
    "acrylic": mat("acrylic", (0.95, 0.93, 0.85), 0.25),
}
_a = M["acrylic"].node_tree.nodes["Principled BSDF"].inputs
_a["Transmission Weight" if "Transmission Weight" in _a else "Transmission"].default_value = 0.9
_a["IOR"].default_value = 1.49


def box(name, x0, y0, z0, x1, y1, z1, material, bevel=0.15):
    bpy.ops.mesh.primitive_cube_add(size=1, location=((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))
    o = bpy.context.object
    o.name = name
    o.scale = (x1 - x0, y1 - y0, z1 - z0)
    bpy.ops.object.transform_apply(scale=True)
    if bevel:
        b = o.modifiers.new("bevel", "BEVEL")
        b.width = bevel
        b.segments = 2
    o.data.materials.append(material)
    return o


def cyl(name, x, y, z0, h, d, material, verts=48):
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=d / 2, depth=h, location=(x, y, z0 + h / 2))
    o = bpy.context.object
    o.name = name
    o.data.materials.append(material)
    bpy.ops.object.shade_smooth()
    return o


def stl(name, path, material, loc=(0, 0, 0)):
    bpy.ops.wm.stl_import(filepath=path)
    o = bpy.context.selected_objects[0]
    o.name = name
    o.location = loc
    o.data.materials.clear()
    o.data.materials.append(material)
    try:
        bpy.ops.object.shade_smooth_by_angle(angle=math.radians(35))
    except Exception:
        pass
    return o


# ---------------------------------------------------------------- objects (mm)
base = stl("base", os.path.join(WORK, "base.stl"), M["case"])
lid = stl("lid", os.path.join(WORK, "lid_asm.stl"), M["lid"], (0, 0, BASE_H))
# acrylic rod in the light pipe, flush with the lid top, moves with the lid
# one rod per LED; the green one (middle) carries the other two, so the clips move all three
rod = cyl("rod", C(*LED)[0], C(*LED)[1], -PIPE_LEN, PIPE_LEN + LID_T, ROD_D, M["acrylic"], 32)
rod.parent = lid
rod["led"] = "green"
rods = [rod]
for i, l in enumerate(LEDS):
    if l == LED:
        continue
    dx, dy = C(*l)[0] - C(*LED)[0], C(*l)[1] - C(*LED)[1]
    r = cyl(f"rod{i}", dx, dy, -(PIPE_LEN + LID_T) / 2, PIPE_LEN + LID_T, ROD_D, M["acrylic"], 32)
    r.parent = rod
    r["led"] = ("red", "green", "yellow")[i]
    rods.append(r)
pins = [stl(f"pin{i}", os.path.join(WORK, "pin_asm.stl"), M["pin"], (bx, by, TOP_Z + SW_H + 0.3))
        for i, (bx, by) in enumerate(BUTTONS)]

before = set(bpy.data.objects)
bpy.ops.import_scene.gltf(filepath=os.path.join(WORK, "board.glb"))
board_parts = [o for o in bpy.data.objects if o not in before]
# KiCad exports silkscreen (white) and solder mask (green) as see-through layers: the pale FR4
# shows through and, in real-time viewers, the layers can draw in the wrong order and wash the
# silkscreen out. Silkscreen opaque white; mask darker and denser (traces still show a little).
for m in {s.material for o in board_parts for s in getattr(o, "material_slots", []) if s.material}:
    p = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if m.use_nodes else None
    if p is None or p.inputs["Alpha"].is_linked or p.inputs["Alpha"].default_value >= 1.0:
        continue
    r, g, b, _ = p.inputs["Base Color"].default_value
    if min(r, g, b) > 0.9:                                   # silkscreen
        p.inputs["Alpha"].default_value = 1.0
        p.inputs["Roughness"].default_value = 0.7
        m.blend_method = "OPAQUE"
    elif g > r and g > b:                                    # solder mask
        p.inputs["Base Color"].default_value = (0.02, 0.11, 0.045, 1.0)
        p.inputs["Alpha"].default_value = 0.93
        p.inputs["Roughness"].default_value = 0.35
board_root = bpy.data.objects.new("board", None)
scene.collection.objects.link(board_root)
for o in board_parts:
    if o.parent is None:
        o.parent = board_root
board_root.scale = (1000, 1000, 1000)
board_root.location = (OFF, OFF, BOARD_Z)

inside = []
# Pro Micro on its pin headers (plus female sockets when SOCKET)
for i, x in enumerate(PIN_ROWS_X):
    z_spacer = TOP_Z
    if SOCKET:
        inside.append(box(f"socket{i}", x - 1.27, PIN_YS[-1] - 1.27, TOP_Z, x + 1.27, PIN_YS[0] + 1.27, TOP_Z + 8.5, M["header"], 0.1))
        z_spacer = TOP_Z + 8.5
    inside.append(box(f"spacer{i}", x - 1.27, PIN_YS[-1] - 1.27, z_spacer, x + 1.27, PIN_YS[0] + 1.27, TOP_Z + PM_GAP, M["header"], 0.1))
    for y in PIN_YS:
        inside.append(box("pintip", x - 0.32, y - 0.32, TOP_Z + PM_GAP + PM_PCB, x + 0.32, y + 0.32, TOP_Z + PM_GAP + PM_PCB + 1.6, M["gold"], 0.05))
pm_z = TOP_Z + PM_GAP
# ---- stand-ins for the two modules, after product photos (not exact, but recognisable):
# nice!nano v2 (circuitpython.org/board/nice_nano) and TCM 515 (EnOcean product photo).
FONT_DIR = "/System/Library/Fonts/Supplemental"


def font(name):
    path = os.path.join(FONT_DIR, name)
    return bpy.data.fonts.load(path, check_existing=True) if os.path.exists(path) else None


FONTS = {"bold": font("Arial Bold.ttf"), "regular": font("Arial.ttf"), "narrow": font("Arial Narrow.ttf")}


def text(name, body, x, y, z, size, material, rot=0.0, align="CENTER", style="regular", depth=0.01):
    """Flat raised text (glTF has no text: converted to a mesh). rot: text direction, radians from +X."""
    bpy.ops.object.text_add(location=(x, y, z + depth))
    o = bpy.context.object
    o.name = name
    o.data.body = body
    o.data.size = size
    o.data.align_x = align
    o.data.align_y = "CENTER"
    o.data.extrude = depth
    o.data.resolution_u = 3          # few segments per glyph curve: keeps the GLB small
    if FONTS.get(style):
        o.data.font = FONTS[style]
    o.rotation_euler = (0, 0, rot)
    bpy.ops.object.convert(target="MESH")
    o.data.materials.append(material)
    return o


def rects(name, rs, z, material):
    """One flat mesh from many rectangles (x0, y0, x1, y1): pads, data matrix cells."""
    verts, faces = [], []
    for x0, y0, x1, y1 in rs:
        i = len(verts)
        verts += [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)]
        faces.append((i, i + 1, i + 2, i + 3))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    o = bpy.data.objects.new(name, me)
    scene.collection.objects.link(o)
    o.data.materials.append(material)
    return o


M.update({
    "nn_pcb": mat("nn_pcb", (0.42, 0.02, 0.02), 0.45),          # red solder mask (the real one is black)
    "silk": mat("silk", (0.9, 0.9, 0.88), 0.6),
    "nrf_pkg": mat("nrf_pkg", (0.035, 0.035, 0.04), 0.35),
    "marking": mat("marking", (0.32, 0.32, 0.34), 0.5),
    "cap": mat("cap", (0.5, 0.36, 0.22), 0.45),
    "res": mat("res", (0.03, 0.03, 0.03), 0.5),
    "term": mat("term", (0.85, 0.85, 0.86), 0.3, 1.0),
    "led_body": mat("led_body", (0.92, 0.9, 0.82), 0.3),
    "xtal": mat("xtal", (0.82, 0.82, 0.84), 0.25, 1.0),
    "tcm_pcb": mat("tcm_pcb", (0.08, 0.3, 0.1), 0.45),
    "shield": mat("shield", (0.78, 0.76, 0.72), 0.3, 1.0),        # tin-plated can
    "sticker": mat("sticker", (0.96, 0.96, 0.95), 0.55),
    "ink": mat("ink", (0.04, 0.04, 0.05), 0.5),
    "usb_in": mat("usb_in", (0.02, 0.02, 0.02), 0.6),
    "tongue": mat("tongue", (0.12, 0.12, 0.13), 0.5),
})

# ---------------- nice!nano v2: red board (black in the photo), gold rings, USB-C sunk flush with its underside, nRF52840 towards the far end
# Module coordinates: d = mm from the USB end, f = fraction of the width from the +X edge
# (RAW/GND/RST/VCC side). The receptacle (3.2 mm high) sits in a notch of the module, its
# underside flush with the module's underside (carrier_case.scad pm_usb = "bottom").
USB_UZ = pm_z + 1.6                  # receptacle centre
PM_W = PM_X1 - PM_X0


def nn(d, f):
    return (PM_X1 - f * PM_W, PM_Y1 - d)


top = pm_z + PM_PCB
inside.append(box("promicro", PM_X0, PM_Y0, pm_z, PM_X1, PM_Y1, top, M["nn_pcb"], 0.25))
# 13 gold rings per side: B+ / B- at 1.27 mm from the USB end (no pin), then the 12 header pins
ring_ys = [PM_Y1 - 1.27] + PIN_YS
for side, x in enumerate(PIN_ROWS_X):
    for j, y in enumerate(ring_ys):
        for z, n in ((top, "top"), (pm_z - 0.03, "bot")):
            inside.append(cyl(f"ring{side}_{j}_{n}", x, y, z, 0.03, 1.65, M["gold"], 20))
        if j == 0:   # battery pads: plated hole, no pin
            inside.append(cyl(f"bat_hole{side}", x, y, top, 0.04, 0.9, M["chip"], 20))
# the three inner pads near the far end (P1.07, P1.02, P1.01)
for i, f in enumerate((0.47, 0.62, 0.78)):
    x, y = nn(26.3, f)
    inside.append(cyl(f"inner_pad{i}", x, y, top, 0.03, 1.4, M["gold"], 20))
    inside.append(cyl(f"inner_hole{i}", x, y, top, 0.04, 0.7, M["chip"], 20))
# pin labels, white silkscreen inside the rows (as on the board: RAW, GND, RST, VCC ...)
LABELS_R = ["B+", "RAW", "GND", "RST", "VCC", "031", "029", "002", "115", "113", "111", "010", "009"]
LABELS_L = ["B-", "006", "008", "GND", "GND", "017", "020", "022", "024", "100", "011", "104", "106"]
for j, y in enumerate(ring_ys):
    inside.append(text(f"lbl_r{j}", LABELS_R[j], PIN_ROWS_X[1] - 1.15, y, top, 0.72, M["silk"], align="RIGHT", style="narrow", depth=0.005))
    inside.append(text(f"lbl_l{j}", LABELS_L[j], PIN_ROWS_X[0] + 1.15, y, top, 0.72, M["silk"], align="LEFT", style="narrow", depth=0.005))
# logo across the far end
lx, ly = nn(29.6, 0.5)
inside.append(text("nn_logo", "nice!nano", lx, ly, top, 1.7, M["silk"], style="bold", depth=0.005))
lx, ly = nn(31.6, 0.5)
inside.append(text("nn_ver", "v2.0", lx, ly, top, 0.9, M["silk"], depth=0.005))
# nRF52840 (aQFN73, 7 x 7 mm) with its marking
cx_, cy_ = nn(20.1, 0.5)
inside.append(box("nrf", cx_ - 3.5, cy_ - 3.5, top, cx_ + 3.5, cy_ + 3.5, top + 0.85, M["nrf_pkg"], 0.08))
inside.append(text("nrf_mark", "N52840\nQIAAD0", cx_, cy_, top + 0.85, 0.75, M["marking"], depth=0.003))
# 32 MHz crystal next to it, the regulator and the inductor near the USB end
x, y = nn(23.6, 0.17)
inside.append(box("xtal", x - 1.0, y - 0.8, top, x + 1.0, y + 0.8, top + 0.55, M["xtal"], 0.08))
for name, d, f, w, l, h in (("ldo", 13.6, 0.36, 1.6, 2.9, 0.9), ("ind", 10.6, 0.58, 2.0, 2.0, 1.0),
                            ("chg", 14.6, 0.62, 2.0, 2.0, 0.75)):
    x, y = nn(d, f)
    inside.append(box(name, x - w / 2, y - l / 2, top, x + w / 2, y + l / 2, top + h, M["nrf_pkg"], 0.06))
# two 0603 LEDs at the USB end (charge, user)
for i, f in enumerate((0.3, 0.7)):
    x, y = nn(8.6, f)
    inside.append(box(f"nn_led{i}", x - 0.4, y - 0.8, top, x + 0.4, y + 0.8, top + 0.45, M["led_body"], 0.05))
# 0402 passives (caps tan, resistors black), positions read off the photo
PASSIVES = [(9.2, 0.33), (9.2, 0.45), (10.4, 0.72), (11.8, 0.28), (11.8, 0.7), (12.6, 0.48),
            (15.6, 0.3), (15.6, 0.42), (16.0, 0.72), (16.0, 0.8), (24.9, 0.4), (24.9, 0.55),
            (25.1, 0.72), (18.9, 0.25), (21.3, 0.25), (18.7, 0.76), (21.5, 0.76)]
for i, (d, f) in enumerate(PASSIVES):
    x, y = nn(d, f)
    m_body = M["cap"] if i % 3 else M["res"]
    inside.append(box(f"p{i}", x - 0.25, y - 0.5, top, x + 0.25, y + 0.5, top + 0.35, m_body, 0.03))
    for s in (-1, 1):
        inside.append(box(f"p{i}t", x - 0.26, y + s * 0.5 - 0.13, top, x + 0.26, y + s * 0.5 + 0.13, top + 0.36, M["term"], 0.02))
# USB-C receptacle (8.94 x 7.35 x 3.2 mm), front about flush with the module edge
cx = (PM_X0 + PM_X1) / 2
uz = USB_UZ
inside.append(box("usb", cx - 4.47, PM_Y1 - 7.35 + 0.3, uz - 1.6, cx + 4.47, PM_Y1 + 0.3, uz + 1.6, M["metal"], 1.1))
inside.append(box("usb_mouth", cx - 3.9, PM_Y1 + 0.29, uz - 1.05, cx + 3.9, PM_Y1 + 0.33, uz + 1.05, M["usb_in"], 0.0))
inside.append(box("usb_tongue", cx - 3.3, PM_Y1 + 0.32, uz - 0.35, cx + 3.3, PM_Y1 + 0.36, uz + 0.35, M["tongue"], 0.0))

N_PROMICRO = len(inside)              # the Pro Micro stand-in (headers, module, its parts) so far
# ---------------- TCM 515: green module PCB with 31 castellated pads, tin shield can, white label
# Position and pads from the KiCad footprint EnOcean:TCM515 (at 27.6 / 14.0 on the board, -90 deg):
# footprint x (19 mm) runs along the board's y, footprint y (14.7 mm) against the board's x.
TCM_AT = (27.6, 14.0)


def tcm(lx, ly):
    """Footprint coordinates -> case coordinates."""
    return C(TCM_AT[0] - ly, TCM_AT[1] + lx)


def tbox(name, lx0, ly0, lx1, ly1, z0, z1, material, bevel=0.05):
    (ax, ay), (bx, by) = tcm(lx0, ly0), tcm(lx1, ly1)
    return box(name, min(ax, bx), min(ay, by), z0, max(ax, bx), max(ay, by), z1, material, bevel)


T_PCB, T_H = 0.8, 3.0
inside.append(tbox("tcm", -9.5, -7.35, 9.5, 7.35, TOP_Z, TOP_Z + T_PCB, M["tcm_pcb"], 0.05))
# castellations: gold pads wrapping the board edge, 0.7 mm wide (TCM 515 User Manual, Figure 15)
pads = ([(-9.5, y) for y in (-5.95, -4.95, -3.95, 3.95, 4.95, 5.95)] + [(9.5, y) for y in range(-3, 4)]
        + [(x + 0.1, s * 7.35) for x in range(0, 9) for s in (-1, 1)])
for i, (px, py) in enumerate(pads):
    if abs(px) == 9.5:
        inside.append(tbox(f"cast{i}", px - 0.75 * (px > 0) - 0.03 * (px < 0), py - 0.35, px + 0.03 * (px > 0) + 0.75 * (px < 0), py + 0.35,
                           TOP_Z - 0.01, TOP_Z + T_PCB + 0.01, M["gold"], 0.0))
    else:
        s = 1 if py > 0 else -1
        inside.append(tbox(f"cast{i}", px - 0.35, py - 0.75 * s, px + 0.35, py + 0.03 * s,
                           TOP_Z - 0.01, TOP_Z + T_PCB + 0.01, M["gold"], 0.0))
# shield can, 0.4 mm inside the board edge, with the four corner tabs of the photo
inside.append(tbox("shield", -9.1, -6.95, 9.1, 6.95, TOP_Z + T_PCB, TOP_Z + T_H, M["shield"], 0.12))
for sx in (-1, 1):
    for sy in (-1, 1):
        inside.append(tbox("tab", sx * 9.0 - 0.2, sy * 6.85 - 0.2, sx * 9.0 + 0.2, sy * 6.85 + 0.2,
                           TOP_Z + T_PCB - 0.3, TOP_Z + T_H - 0.1, M["shield"], 0.02))
# label: text runs along the module's long side (footprint +x), its top towards footprint -y
lt = TOP_Z + T_H
inside.append(tbox("tcm_label", -8.5, -6.35, 8.5, 6.35, lt, lt + 0.02, M["sticker"], 0.0))
lt += 0.02
rot = math.atan2(tcm(1, 0)[1] - tcm(0, 0)[1], tcm(1, 0)[0] - tcm(0, 0)[0])


def lbl(u, v):
    return tcm(u, -v)


x, y = lbl(-7.1, 3.6)                                      # logo: black square with a white fin
inside.append(rects("tcm_logo", [(x - 1.2, y - 1.2, x + 1.2, y + 1.2)], lt + 0.002, M["ink"]))
fin = [lbl(-7.1 + du, 3.6 + dv) for du, dv in ((-0.8, -0.7), (0.9, -0.7), (0.4, 0.8))]
me = bpy.data.meshes.new("tcm_fin")
me.from_pydata([(fx, fy, lt + 0.004) for fx, fy in fin], [], [(0, 1, 2)])
o = bpy.data.objects.new("tcm_fin", me)
scene.collection.objects.link(o)
o.data.materials.append(M["sticker"])
inside.append(o)
for name, body, u, v, size, style in (("tcm_brand", "DOLPHIN", -5.5, 3.6, 2.6, "bold"),
                                      ("tcm_model", "Model: TCM 515    CA 46/16", -7.9, 0.5, 1.05, "regular"),
                                      ("tcm_part", "S3003-K515.1", -7.9, -1.4, 1.05, "regular"),
                                      ("tcm_sn", "416001000070", -7.9, -3.3, 1.05, "regular")):
    x, y = lbl(u, v)
    inside.append(text(name, body, x, y, lt, size, M["ink"], rot, align="LEFT", style=style, depth=0.003))
# data matrix (12 x 12, 0.27 mm cells): solid L finder on two edges, clock pattern on the others
import random  # noqa: E402
rng = random.Random(515)
cells = []
N, CELL = 12, 0.27
u0, v0 = 4.6, -4.9
for i in range(N):
    for j in range(N):
        on = (i == 0 or j == 0) or (j == N - 1 and i % 2 == 0) or (i == N - 1 and j % 2 == 0) or \
             (0 < i < N - 1 and 0 < j < N - 1 and rng.random() < 0.5)
        if on:
            (ax, ay), (bx, by) = lbl(u0 + i * CELL, v0 + j * CELL), lbl(u0 + (i + 1) * CELL, v0 + (j + 1) * CELL)
            cells.append((min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)))
inside.append(rects("tcm_dmc", cells, lt + 0.002, M["ink"]))
# buttons (XKB TS-1187A)
for i, (bx, by) in enumerate(BUTTONS):
    inside.append(box(f"sw{i}", bx - 2.55, by - 2.55, TOP_Z, bx + 2.55, by + 2.55, TOP_Z + 1.0, M["metal"], 0.1))
    inside.append(cyl(f"sw_cap{i}", bx, by, TOP_Z + 1.0, SW_H - 1.0, 3.0, M["chip"]))
whip = cyl("whip", WHIP[0], WHIP[1], TOP_Z - 0.5, 86.0, 0.8, M["copper"], 24)

# board + everything mounted on it move as one in the animation
board_group = bpy.data.objects.new("board_group", None)
scene.collection.objects.link(board_group)
board_root.parent = board_group
for o in inside:
    o.parent = board_group

floor = None
bpy.ops.mesh.primitive_plane_add(size=2000, location=(OUT_W / 2, OUT_D / 2, 0))
floor = bpy.context.object
floor.data.materials.append(M["floor"])

# everything into one root so the scene can be scaled to sensible light units (1 unit = 10 cm)
root = bpy.data.objects.new("root", None)
scene.collection.objects.link(root)
for o in list(scene.objects):
    if o is not root and o.parent is None:
        o.parent = root
root.scale = (0.01, 0.01, 0.01)
center = Vector((OUT_W / 2, OUT_D / 2, BASE_H / 2)) * 0.01



def rrect(name, cx, cz, w, h, r, y0, y1, material, seg=8):
    """Prism along Y with a rounded-rectangle cross-section (w x h, corner radius r) centred on cx/cz."""
    r = min(r, w / 2, h / 2)
    ring = []
    for qx, qz, a0 in ((1, 1, 0), (-1, 1, 90), (-1, -1, 180), (1, -1, 270)):
        ox, oz = cx + qx * (w / 2 - r), cz + qz * (h / 2 - r)
        for i in range(seg + 1):
            a = math.radians(a0 + 90 * i / seg)
            ring.append((ox + r * math.cos(a), oz + r * math.sin(a)))
    n = len(ring)
    verts = [(x, y0, z) for x, z in ring] + [(x, y1, z) for x, z in ring]
    faces = [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)]
    faces += [tuple(reversed(range(n))), tuple(range(n, 2 * n))]
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    o = bpy.data.objects.new(name, me)
    scene.collection.objects.link(o)
    o.data.materials.append(material)
    for f in me.polygons:
        f.use_smooth = len(f.vertices) == 4
    return o


def usb_plug():
    """USB-C plug with cable, mated (shell fully in the receptacle), pointing out of the end wall,
    as one group. Plug shell per the USB Type-C spec: 8.25 x 2.40 mm, 6.65 mm long. Overmold of a
    slim cable, 10.5 x 5.5 mm: clears the case's 12.4 x 6.6 mm oval by about 0.5 mm all round (the
    spec allows up to 12.35 x 6.5 mm, whose corners would not pass the oval). Light grey."""
    plug = bpy.data.objects.new("plug", None)
    scene.collection.objects.link(plug)
    plug.parent = root
    uz = USB_UZ                              # receptacle centre
    yf = PM_Y1 + 0.3                         # receptacle front face
    parts = [
        rrect("plug_shell", cx, uz, 8.25, 2.40, 1.2, yf - 6.45, yf + 0.2, M["metal"]),
        rrect("plug_body", cx, uz, 10.5, 5.5, 2.5, yf + 0.2, yf + 16.0, M["cable"]),
        rrect("plug_relief", cx, uz, 6.6, 4.4, 2.0, yf + 16.0, yf + 22.0, M["cable"]),
    ]
    bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=1.8, depth=60, location=(cx, yf + 52.0, uz),
                                        rotation=(math.radians(90), 0, 0))
    cable = bpy.context.object
    cable.name = "plug_cable"
    cable.data.materials.append(M["cable"])
    bpy.ops.object.shade_smooth()
    for o in parts + [cable]:
        o.parent = plug
    return plug


def piezo_disc():
    """The optional piezo: a brass disc with its ceramic facing the board, in the lid's ring (front
    chamber above it), and two wires out through the ring's notch down into J3's holes. One group."""
    grp = bpy.data.objects.new("piezo", None)
    scene.collection.objects.link(grp)
    grp.parent = root
    px, py = C(*PIEZO_AT)
    z_brass = BASE_H - PIEZO_CH - 0.2
    parts = [cyl("piezo_brass", px, py, z_brass, 0.2, PIEZO_D, mat("brass", (0.78, 0.6, 0.3), 0.3, 1.0), 96),
             cyl("piezo_ceramic", px, py, z_brass - 0.1, 0.1, PIEZO_D * 2 / 3, mat("ceramic", (0.85, 0.85, 0.82), 0.6), 96)]
    jx, jy = C((J3_PADS[0][0] + J3_PADS[1][0]) / 2, J3_PADS[0][1])
    d = math.hypot(jx - px, jy - py)
    ux, uy = (jx - px) / d, (jy - py) / d        # toward J3 (the ring's notch)
    vx, vy = -uy, ux
    starts = [(px + 2.0 * ux + 0.8 * vx, py + 2.0 * uy + 0.8 * vy, z_brass - 0.12),      # on the ceramic
              (px + 6.6 * ux - 0.8 * vx, py + 6.6 * uy - 0.8 * vy, z_brass - 0.02)]      # on the brass rim
    pads = sorted((C(*p) for p in J3_PADS), key=lambda q: (q[0] - px) * vx + (q[1] - py) * vy, reverse=True)
    for i, ((sx, sy, sz), (hx, hy), colour) in enumerate(zip(starts, pads, [(0.7, 0.05, 0.04), (0.03, 0.03, 0.03)])):
        side = 0.6 if i == 0 else -0.6
        pts = [(sx, sy, sz), (sx, sy, sz - 0.4),
               (px + 9.5 * ux + side * vx, py + 9.5 * uy + side * vy, BASE_H - 1.9),
               ((px + 9.5 * ux + hx) / 2, (py + 9.5 * uy + hy) / 2, TOP_Z + 4.0),
               (hx, hy, TOP_Z + 1.2), (hx, hy, TOP_Z - 0.3)]
        cu = bpy.data.curves.new(f"piezo_wire{i}", "CURVE")
        cu.dimensions = "3D"
        cu.bevel_depth = 0.25                    # 0.5 mm wire
        cu.bevel_resolution = 3
        sp = cu.splines.new("NURBS")
        sp.points.add(len(pts) - 1)
        for pt, q in zip(sp.points, pts):
            pt.co = (*q, 1.0)
        sp.order_u = 3
        sp.use_endpoint_u = True
        sp.resolution_u = 12
        o = bpy.data.objects.new(f"piezo_wire{i}", cu)
        scene.collection.objects.link(o)
        o.data.materials.append(mat(f"wire{i}", colour, 0.5))
        bpy.ops.object.select_all(action="DESELECT")
        o.select_set(True)
        bpy.context.view_layer.objects.active = o
        bpy.ops.object.convert(target="MESH")
        parts.append(bpy.context.object)
    for o in parts:
        o.parent = grp
    return grp


if MODE == "glb":
    # 3D model for viewing (hardware/pcb-viewer.html, Blender, any glTF viewer): the board with
    # its KiCad parts and the stand-ins above, in the closed case. glTF works in metres, so
    # 1 mm = 0.001. Top-level nodes for the viewer's toggles: base, lid (with the light-pipe
    # rods), push_pins (both button push pins), board_group (board + TCM + parts), promicro (the
    # Pro Micro on its headers; node "pro_micro"), whip, plug (USB-C plug), piezo (disc in the lid's ring, wires to J3).
    bpy.data.objects.remove(floor)
    root.scale = (0.001, 0.001, 0.001)
    # Hints for pcb-viewer.html (glTF extras): name in the parts list, hidden at first (it opens
    # on the bare board), left out when framing the view (the whip is twice the case height).
    plug = usb_plug()
    piezo = piezo_disc()
    # the Pro Micro (module on its headers) and the two push pins as groups of their own
    promicro = bpy.data.objects.new("pro_micro", None)
    scene.collection.objects.link(promicro)
    promicro.parent = root
    for o in inside[:N_PROMICRO]:            # board_group and promicro are both unit transforms under root
        o.parent = promicro
    push_pins = bpy.data.objects.new("push_pins", None)
    scene.collection.objects.link(push_pins)
    push_pins.parent = root
    for o in pins:                           # root -> push_pins (unit transform) -> pin
        o.parent = push_pins
    for o, label, hidden in [(board_group, "Board with parts", False), (whip, "868 MHz whip", False),
                             (base, "Case base", True), (lid, "Lid with light pipes", True),
                             (promicro, "Pro Micro nRF52840", False), (push_pins, "Push pins", True),
                             (plug, "USB-C plug and cable", True), (piezo, "Piezo disc and wires", True)]:
        o["viewer_label"] = label
        o["viewer_hidden"] = hidden
    whip["viewer_noframe"] = True
    plug["viewer_noframe"] = True
    bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", export_apply=True, export_yup=True,
                              export_extras=True)
    print("wrote", OUT)
    sys.exit(0)

# ---------------------------------------------------------------- lights, world, render
world = bpy.data.worlds.new("world")
scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.82, 0.85, 0.9, 1)
world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.25


def area(name, loc, size, power, color=(1, 1, 1)):
    l = bpy.data.lights.new(name, "AREA")
    l.size = size
    l.energy = power
    l.color = color
    o = bpy.data.objects.new(name, l)
    scene.collection.objects.link(o)
    o.location = loc
    d = center - Vector(loc)
    o.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    return o


area("key", (center.x + 0.9, center.y - 0.8, center.z + 1.1), 0.8, 70, (1.0, 0.96, 0.9))
area("fill", (center.x - 1.0, center.y - 0.4, center.z + 0.6), 1.2, 22, (0.88, 0.94, 1.0))
area("rim", (center.x - 0.3, center.y + 1.2, center.z + 0.9), 0.6, 60)

cam_data = bpy.data.cameras.new("cam")
cam_data.lens = 70
cam_data.clip_start = 0.01
cam_data.clip_end = 100
cam = bpy.data.objects.new("cam", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam
target = bpy.data.objects.new("target", None)
scene.collection.objects.link(target)
track = cam.constraints.new("TRACK_TO")
track.target = target
track.track_axis = "TRACK_NEGATIVE_Z"
track.up_axis = "UP_Y"
cam_data.dof.use_dof = True
cam_data.dof.focus_object = target
cam_data.dof.aperture_fstop = 5.6

scene.render.engine = "CYCLES"
try:
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "METAL"
    prefs.get_devices()
    for d in prefs.devices:
        d.use = True
    scene.cycles.device = "GPU"
except Exception:
    pass
scene.cycles.samples = SAMPLES
scene.cycles.use_denoising = True
scene.render.resolution_x = 1600
scene.render.resolution_y = 1100
scene.render.film_transparent = False
try:
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
except Exception:
    pass


def shot(name, cam_loc, target_loc, lens=70, lid_z=None, pin_lift=0.0, show_lid=True, show_whip=False, fstop=5.6):
    lid.hide_render = not show_lid
    for r in rods:
        r.hide_render = not show_lid
    for p in pins:
        p.hide_render = not show_lid
        p.location.z = TOP_Z + SW_H + 0.3 + pin_lift
    lid.location.z = BASE_H if lid_z is None else lid_z
    whip.hide_render = not show_whip
    cam.location = cam_loc
    target.location = target_loc
    cam_data.lens = lens
    cam_data.dof.aperture_fstop = fstop
    scene.render.filepath = os.path.join(OUT, f"render-{name}.png")
    bpy.ops.render.render(write_still=True)
    print("wrote", scene.render.filepath)


c = center
if MODE.startswith("anim"):
    import anim_case   # noqa: E402  (tools/anim_case.py, next to this script)
    plug = None
    if MODE == "anim-usb":
        plug = usb_plug()
        # status LEDs: each acrylic rod lights up in its LED's colour once the cable is in
        glows = []
        for name, l, rgb in (("red", LEDS[0], (1.0, 0.08, 0.05)), ("green", LEDS[1], (0.15, 1.0, 0.3)),
                             ("yellow", LEDS[2], (1.0, 0.75, 0.05))):
            r = next(o for o in rods if o.get("led") == name)
            gm = mat(f"led_{name}", tuple(0.35 + 0.3 * c for c in rgb), 0.3, 0.0, (rgb, 0.0))
            r.data.materials[0] = gm
            ld = bpy.data.lights.new(f"led_{name}", "POINT")
            ld.color = rgb
            ld.energy = 0.0
            ld.shadow_soft_size = 0.002
            lo = bpy.data.objects.new(f"led_{name}", ld)
            scene.collection.objects.link(lo)
            lo.parent = lid
            lo.location = (*C(*l), 3.5)
            gm["light"] = ld.name
            glows.append((name, gm))
    anim_case.run(scene, cam, cam_data, target, center, lid, pins, whip, board_group,
                  dict(BASE_H=BASE_H, TOP_Z=TOP_Z, SW_H=SW_H), OUT, FRAMES,
                  view="usb" if MODE == "anim-usb" else "front", plug=plug,
                  glows=glows if MODE == "anim-usb" else None, rod=rod,
                  samples=SAMPLES, save=SAVE)
    raise SystemExit(0)
shot("closed", (c.x + 0.95, c.y - 1.05, c.z + 0.75), (c.x, c.y, c.z + 0.02), lens=60, show_whip=True)
shot("exploded", (c.x + 1.0, c.y - 1.15, c.z + 0.95), (c.x, c.y, c.z + 0.12), lens=55,
     lid_z=BASE_H + 32, pin_lift=32 - 12)
shot("open", (c.x + 0.4, c.y - 0.85, c.z + 1.15), (c.x, c.y + 0.02, c.z - 0.06), lens=50, show_lid=False)
